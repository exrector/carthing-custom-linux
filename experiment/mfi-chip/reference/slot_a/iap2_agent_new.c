/*
 * iap2_agent.c — iAP2 Bluetooth агент для Car Thing (замена qt-superbird-app)
 *
 * v2.7 — SERVER-ONLY mode: не инициируем RFCOMM к iPhone.
 *         Регистрируем ОБА профиля: caff (server, ch 3) + cafe (client, AutoConnect).
 *         При NewConnection: server_mode=0 → сразу шлём SYN.
 *
 * Архитектура: Car Thing = iAP2 RFCOMM server.
 *   iPhone's iapd видит наш SDP (UUID caff, ch 1) и сам открывает RFCOMM.
 *
 * Поток:
 *  1. Регистрируем SDP + профиль через BlueZ RegisterProfile (для NewConnection)
 *  2. При старте: отключаем уже подключённые устройства → iPhone переподключится
 *  3. При Connected=true: через 2с подключаемся к iPhone RFCOMM ch 1
 *  4. server_mode=0 (клиент): без LISTEN — сразу SYN (мы инициаторы)
 *  5. server_mode=1 (NewConnection): 30с LISTEN — ждём что iPhone пришлёт
 *
 * btmon capture рекомендуется: btmon -w /tmp/bt.snoop &
 *
 * Компиляция (Docker, arm32v7/debian:bullseye):
 *
 *   docker run --rm -v "$(pwd)":/work arm32v7/debian:bullseye bash -c "
 *     apt-get update -qq &&
 *     apt-get install -y gcc libglib2.0-dev libbluetooth-dev 2>/dev/null &&
 *     cd /work/slot_a &&
 *     gcc -o iap2_agent iap2_agent.c \
 *       \$(pkg-config --cflags --libs gio-2.0 gio-unix-2.0 glib-2.0) \
 *       -lpthread -lbluetooth -Os -Wl,--strip-all &&
 *     echo 'OK: iap2_agent built'"
 *
 * Деплой на устройство:
 *   adb push slot_a/iap2_agent /home/superbird/slot_a/iap2_agent
 *   adb shell supervisorctl restart iap2_agent
 */

#include <gio/gio.h>
#include <gio/gunixfdlist.h>
#include <glib.h>
#include <glib-unix.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <pthread.h>
#include <ctype.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <bluetooth/bluetooth.h>
#include <bluetooth/rfcomm.h>

/* ── iAP2 / BlueZ constants ─────────────────────────────────────────────── */
#define IAP2_SERVER_UUID    "00000000-deca-fade-deca-deafdecacaff"   /* accessory server */
#define IAP2_CLIENT_UUID    "00000000-deca-fade-deca-deafdecacafe"   /* iPhone server    */
#define IAP2_UUID           IAP2_SERVER_UUID                          /* compat alias     */
#define PROFILE_SERVER_PATH "/org/bluez/profile/iap2server"
#define PROFILE_CLIENT_PATH "/org/bluez/profile/iap2client"
#define PROFILE_PATH        PROFILE_SERVER_PATH                       /* compat alias     */
#define IAP2_RFCOMM_CHANNEL 3

/* ── iAP2 link-layer constants ──────────────────────────────────────────── */
/* Every iAP2 packet starts with 0xFF SOF, min 9-byte header:
 *  SOF(1) PKT_LEN(2) CTL(1) SID(1) SEQ(1) ACK(1) HDR_CKSUM(1) [PAYLOAD] [PAY_CKSUM(1)]
 * CTL bits: 7=SYN 6=ACK 5=EAK 4=RST; CTL=0x00 → data packet */
#define IAP2_SOF       0xFF
#define IAP2_CTL_SYN   0x80
#define IAP2_CTL_ACK   0x40
#define IAP2_CTL_EAK   0x20
#define IAP2_CTL_DATA  0x00
#define IAP2_SID_CTL   0x00   /* control session */

/* Control session message IDs */
#define IAP2_CSM_START              0x4040
#define IAP2_MSG_AUTH_CERT_REQ      0xAA00
#define IAP2_MSG_AUTH_CERT_RESP     0xAA01
#define IAP2_MSG_AUTH_CHAL_REQ      0xAA02
#define IAP2_MSG_AUTH_CHAL_RESP     0xAA03
#define IAP2_MSG_AUTH_FAILED        0xAA04
#define IAP2_MSG_AUTH_OK            0xAA05

/* ── Forward declarations ───────────────────────────────────────────────── */
typedef struct iap2_conn iap2_conn_t;
static iap2_conn_t *g_active_conn = NULL; /* current RFCOMM connection (for FIFO thread) */
static int  iap2_write_pkt(int fd, uint8_t ctl, uint8_t sid, uint8_t seq,
                            uint8_t ack, const uint8_t *payload, int plen);
static int  iap2_send_msg(int fd, uint8_t sid, uint8_t seq, uint8_t ack, uint16_t msg_id,
                           const uint8_t *params, int plen);
static void iap2_handle_control(iap2_conn_t *c, const uint8_t *payload,
                                 int plen, uint8_t *seq);
#define IAP2_MSG_NOWPLAYING_UPDATE  0x4800
#define IAP2_MSG_START_HID          0x6800
#define IAP2_MSG_HID_REPORT         0x6801
#define IAP2_MSG_DEVICE_HID_REPORT  0x6802
#define IAP2_MSG_STOP_HID           0x6803
#define HID_COMPONENT_ID            0x0001  /* must match Identification + StartHID */

/* HID descriptor: Consumer Control (play/pause, next, prev, vol +/-) */
static const uint8_t kHidConsumerDesc[] = {
    0x05, 0x0C,        /* Usage Page (Consumer) */
    0x09, 0x01,        /* Usage (Consumer Control) */
    0xA1, 0x01,        /* Collection (Application) */
    0x15, 0x00,        /*   Logical Minimum (0) */
    0x26, 0xFF, 0x03,  /*   Logical Maximum (1023) */
    0x19, 0x00,        /*   Usage Minimum (0) */
    0x2A, 0xFF, 0x03,  /*   Usage Maximum (1023) */
    0x75, 0x10,        /*   Report Size (16) */
    0x95, 0x01,        /*   Report Count (1) */
    0x81, 0x00,        /*   Input (Data, Array, Absolute) */
    0xC0               /* End Collection */
};

/* ── SDP XML — полная запись по образцу wiomoc/iap2 ─────────────────────── */
static const char SDP_XML[] =
    "<?xml version=\"1.0\" encoding=\"UTF-8\" ?>"
    "<record>"
    /* 0x0001 ServiceClassIDList */
    "  <attribute id=\"0x0001\">"
    "    <sequence>"
    "      <uuid value=\"00000000-deca-fade-deca-deafdecacaff\"/>"
    "    </sequence>"
    "  </attribute>"
    /* 0x0002 ServiceRecordState */
    "  <attribute id=\"0x0002\">"
    "    <uint32 value=\"0x00000000\"/>"
    "  </attribute>"
    /* 0x0004 ProtocolDescriptorList: L2CAP + RFCOMM ch 3 */
    "  <attribute id=\"0x0004\">"
    "    <sequence>"
    "      <sequence>"
    "        <uuid value=\"0x0100\"/>"
    "      </sequence>"
    "      <sequence>"
    "        <uuid value=\"0x0003\"/>"
    "        <uint8 value=\"0x03\"/>"
    "      </sequence>"
    "    </sequence>"
    "  </attribute>"
    /* 0x0005 BrowseGroupList */
    "  <attribute id=\"0x0005\">"
    "    <sequence>"
    "      <uuid value=\"0x1002\"/>"
    "    </sequence>"
    "  </attribute>"
    /* 0x0006 LanguageBaseAttributeIDList: en, fr, de, ja */
    "  <attribute id=\"0x0006\">"
    "    <sequence>"
    "      <uint16 value=\"0x656e\"/>"
    "      <uint16 value=\"0x006a\"/>"
    "      <uint16 value=\"0x0100\"/>"
    "      <uint16 value=\"0x6672\"/>"
    "      <uint16 value=\"0x006a\"/>"
    "      <uint16 value=\"0x0110\"/>"
    "      <uint16 value=\"0x6465\"/>"
    "      <uint16 value=\"0x006a\"/>"
    "      <uint16 value=\"0x0120\"/>"
    "      <uint16 value=\"0x6a61\"/>"
    "      <uint16 value=\"0x006a\"/>"
    "      <uint16 value=\"0x0130\"/>"
    "    </sequence>"
    "  </attribute>"
    /* 0x0008 ServiceAvailability */
    "  <attribute id=\"0x0008\">"
    "    <uint8 value=\"0xff\"/>"
    "  </attribute>"
    /* 0x0009 BluetoothProfileDescriptorList (matches known-working impl) */
    "  <attribute id=\"0x0009\">"
    "    <sequence>"
    "      <sequence>"
    "        <uuid value=\"0x1101\"/>"
    "        <uint16 value=\"0x0100\"/>"
    "      </sequence>"
    "    </sequence>"
    "  </attribute>"
    /* 0x0100 ServiceName */
    "  <attribute id=\"0x0100\">"
    "    <text value=\"Wireless iAP\"/>"
    "  </attribute>"
    "</record>";

/* ── D-Bus introspection XML for Profile1 ───────────────────────────────── */
static const char PROFILE_XML[] =
    "<node>"
    "  <interface name='org.bluez.Profile1'>"
    "    <method name='Release'/>"
    "    <method name='NewConnection'>"
    "      <arg name='device'        type='o'      direction='in'/>"
    "      <arg name='fd'            type='h'      direction='in'/>"
    "      <arg name='fd_properties' type='a{sv}'  direction='in'/>"
    "    </method>"
    "    <method name='RequestDisconnection'>"
    "      <arg name='device' type='o' direction='in'/>"
    "    </method>"
    "  </interface>"
    "</node>";

/* ── MFi authentication via /dev/apple_mfi ──────────────────────────────── */
/*
 * Reverse-engineered from apple_mfi_auth.ko (AArch64, verified via probe tests).
 *
 * ioctl struct (16 bytes in both ARM32 and AArch64 due to natural alignment):
 *   struct mfi_buf { uint32_t len; uint32_t pad; uint64_t ptr; }
 *
 * Magic: 0x77   (NOT 0xEF — that was wrong)
 *
 * Working auth sequence:
 *   1. MFI_GET_VERSION   (len=1)   → init chip, returns version byte (0x07)
 *   2. MFI_GET_CERTLEN   (len=2)   → 2-byte big-endian PKCS#7 response size (608)
 *                                     also sets driver-side response length
 *   3. MFI_SET_CHALLENGE (len=32)  → send challenge EXACTLY 32 bytes (pad if needed)
 *   4. MFI_GET_SIGNATURE (len=64)  → raw challenge-dependent 64-byte signature
 *   5. MFI_GET_RESPONSE  (len≥608) → full PKCS#7 SignedData auth blob (cert source)
 *
 * Size constraints from kernel disassembly:
 *   GET_VERSION: len ≥ 1  |  GET_CERTLEN: len ≥ 2  |  GET_SIGNATURE: len ≥ 64
 *   SET_CHALLENGE: len == 32 EXACTLY (EINVAL otherwise)
 *   GET_RESPONSE: len ≥ driver-side cert/response length (set by GET_CERTLEN)
 */
#include <sys/ioctl.h>

#define MFI_DEV  "/dev/apple_mfi"

struct mfi_buf { uint32_t len; uint32_t pad; uint64_t ptr; };

#define MFI_GET_VERSION   _IOR(0x77, 1, struct mfi_buf)  /* init + version byte    */
#define MFI_GET_CERTLEN   _IOR(0x77, 4, struct mfi_buf)  /* 2-byte BE blob size    */
#define MFI_GET_RESPONSE  _IOR(0x77, 5, struct mfi_buf)  /* PKCS#7 auth blob       */
#define MFI_SET_CHALLENGE _IOW(0x77, 6, struct mfi_buf)  /* 32-byte challenge      */
#define MFI_GET_SIGNATURE _IOR(0x77, 7, struct mfi_buf)  /* 64-byte signature      */

static int           mfi_fd        = -1;
static unsigned char mfi_cert[1024];
static int           mfi_cert_len  = 0;
static int           mfi_blob_size = 0;  /* PKCS#7 response size (from GET_CERTLEN) */
static uint16_t      g_iap2_test_hid_usage = 0;  /* optional one-shot HID usage after ID accepted */
static int           g_iap2_test_hid_mode  = 1;  /* 1=6801/u16be, 2=6801/rid2+u16be, 3=legacy6802, 4=all(be), 5=6801/u16le, 6=6801/rid1+u16le */
static int           g_iap2_hid_reset_first = 1; /* send StopHID before StartHID */
static int           g_iap2_hid_first       = 1; /* send StartHID before StartNowPlayingUpdates */

/* Perform one MFi ioctl.  data_buf is the payload (read or write). */
static int mfi_ioctl(int fd, unsigned long cmd, void *data_buf, uint32_t len)
{
    struct mfi_buf hdr;
    hdr.len = len;
    hdr.pad = 0;
    hdr.ptr = (uint64_t)(uintptr_t)data_buf;
    return ioctl(fd, cmd, &hdr);
}

static void mfi_init(void)
{
    mfi_fd = open(MFI_DEV, O_RDWR);
    if (mfi_fd < 0) {
        fprintf(stderr, "[mfi] WARNING: %s open failed: %s\n",
                MFI_DEV, strerror(errno));
        fprintf(stderr, "[mfi]   iAP2 auth will fail — AVRCP still works\n");
        return;
    }

    /* Step 1: initialise coprocessor, read version */
    uint8_t ver = 0;
    if (mfi_ioctl(mfi_fd, MFI_GET_VERSION, &ver, 1) < 0) {
        fprintf(stderr, "[mfi] GET_VERSION failed: %s\n", strerror(errno));
        goto fail;
    }
    fprintf(stderr, "[mfi] coprocessor version 0x%02x\n", ver);

    /* Step 2: get auth-blob size (2 big-endian bytes from chip).
     * CRITICAL: this also sets device_struct[160] inside the driver,
     * which GET_RESPONSE uses as the copy size — must call before sign. */
    uint8_t blen[2] = {0, 0};
    if (mfi_ioctl(mfi_fd, MFI_GET_CERTLEN, blen, 2) < 0) {
        fprintf(stderr, "[mfi] GET_CERTLEN failed: %s\n", strerror(errno));
        goto fail;
    }
    mfi_blob_size = ((int)blen[0] << 8) | blen[1];  /* big-endian */
    fprintf(stderr, "[mfi] auth blob size: %d bytes\n", mfi_blob_size);
    if (mfi_blob_size <= 0 || mfi_blob_size > 2048) {
        fprintf(stderr, "[mfi] unexpected blob size, aborting init\n");
        goto fail;
    }

    /* Step 3: extract device X.509 DER cert from a PKCS#7 auth blob.
     * MFI_GET_SIGNATURE (op7) returns challenge-signature data, not the certificate.
     * The reliable path is: sign a dummy zero-challenge,
     * get the PKCS#7 blob, and scan it for the embedded X.509 DER certificate.
     * The cert is the same regardless of which challenge we sign. */
    {
        uint8_t dummy[32] = {0};
        if (mfi_ioctl(mfi_fd, MFI_SET_CHALLENGE, dummy, 32) < 0) {
            fprintf(stderr, "[mfi] SET_CHALLENGE(dummy) failed: %s\n", strerror(errno));
            goto fail;
        }
        uint8_t pkcs7[1024] = {0};
        if (mfi_ioctl(mfi_fd, MFI_GET_RESPONSE, pkcs7, (uint32_t)mfi_blob_size) < 0) {
            fprintf(stderr, "[mfi] GET_RESPONSE(dummy) failed: %s\n", strerror(errno));
            goto fail;
        }

        /* Use raw PKCS#7 blob by default (iPhone expects full PKCS#7 container, not just X.509 cert).
         * Set IAP2_CERT_X509_ONLY=1 to extract X.509 cert only (legacy/testing). */
        int use_raw_blob = !getenv("IAP2_CERT_X509_ONLY");
        if (use_raw_blob) {
            memcpy(mfi_cert, pkcs7, mfi_blob_size);
            mfi_cert_len = mfi_blob_size;
            fprintf(stderr, "[mfi] using raw PKCS#7 blob as cert payload: %d bytes\n", mfi_cert_len);
            return;
        }

        /* Scan for X.509 v3 cert: SEQUENCE { [0] version INTEGER 2 }
         * Pattern: 30 82 xx xx  a0 03 02 01 02 */
        mfi_cert_len = 0;
        for (int i = 0; i < mfi_blob_size - 9; i++) {
            if (pkcs7[i]   == 0x30 && pkcs7[i+1] == 0x82 &&
                pkcs7[i+4] == 0xa0 && pkcs7[i+5] == 0x03 &&
                pkcs7[i+6] == 0x02 && pkcs7[i+7] == 0x01 &&
                pkcs7[i+8] == 0x02) {
                int sz = 4 + ((pkcs7[i+2] << 8) | pkcs7[i+3]);
                if (i + sz <= mfi_blob_size && sz <= (int)sizeof(mfi_cert)) {
                    memcpy(mfi_cert, pkcs7 + i, sz);
                    mfi_cert_len = sz;
                    break;
                }
            }
        }
        if (mfi_cert_len > 0)
            fprintf(stderr, "[mfi] cert extracted (X.509 only mode): %d bytes, starts %02x%02x%02x%02x\n",
                    mfi_cert_len, mfi_cert[0], mfi_cert[1], mfi_cert[2], mfi_cert[3]);
        else
            fprintf(stderr, "[mfi] WARNING: X.509 cert not found in PKCS#7 blob\n");
    }
    return;

fail:
    close(mfi_fd);
    mfi_fd = -1;
}

/*
 * Sign an iPhone challenge with the MFi coprocessor.
 *   challenge: bytes sent by iPhone (20 or 32 bytes; padded to 32 with zeros)
 *   resp:      caller-allocated buffer, must be >= mfi_blob_size (use 1024)
 *   rlen:      set to number of valid bytes in resp on success
 * Returns 0 on success, -1 on error.
 */
static int mfi_sign(const unsigned char *challenge, int clen,
                    unsigned char *resp, int *rlen)
{
    if (mfi_fd < 0) return -1;

    /* Kernel requires EXACTLY 32 bytes; pad iPhone's challenge if shorter */
    uint8_t padded[32] = {0};
    memcpy(padded, challenge, (clen < 32) ? clen : 32);

    if (mfi_ioctl(mfi_fd, MFI_SET_CHALLENGE, padded, 32) < 0) {
        fprintf(stderr, "[mfi] SET_CHALLENGE failed: %s\n", strerror(errno));
        return -1;
    }

    /* Preferred path: op7 returns challenge-dependent raw signature (64 bytes). */
    {
        uint8_t sig64[64] = {0};
        if (mfi_ioctl(mfi_fd, MFI_GET_SIGNATURE, sig64, 64) == 0) {
            int nonzero = 0;
            for (int i = 0; i < 64; i++) if (sig64[i] != 0) { nonzero = 1; break; }
            if (nonzero) {
                memcpy(resp, sig64, 64);
                *rlen = 64;
                fprintf(stderr, "[mfi] raw signature via op7: 64 bytes, head=%02x%02x%02x%02x\n",
                        resp[0], resp[1], resp[2], resp[3]);
                return 0;
            }
        }
    }

    /* GET_RESPONSE: buf must be >= mfi_blob_size (driver copies exactly that many bytes) */
    int sz = (mfi_blob_size > 0) ? mfi_blob_size : 1024;
    if (mfi_ioctl(mfi_fd, MFI_GET_RESPONSE, resp, (uint32_t)sz) < 0) {
        fprintf(stderr, "[mfi] GET_RESPONSE failed: %s\n", strerror(errno));
        return -1;
    }
    *rlen = sz;
    if (getenv("IAP2_DUMP_MFI_BLOB")) {
        FILE *fc = fopen("/tmp/mfi_last_challenge.bin", "wb");
        if (fc) { fwrite(padded, 1, 32, fc); fclose(fc); }
        FILE *fr = fopen("/tmp/mfi_last_response.bin", "wb");
        if (fr) { fwrite(resp, 1, *rlen, fr); fclose(fr); }
    }

    /* Some kernels return a PKCS#7 container here; iAP2 AA03 expects raw RSA signature bytes. */
    if (getenv("IAP2_MFI_EXTRACT_SIG")) {
        int extracted = 0;
        for (int i = 0; i + 4 + 128 <= *rlen; i++) {
            /* DER BIT STRING for RSA-1024 signature: 03 81 81 00 <128 bytes> */
            if (resp[i] == 0x03 && resp[i+1] == 0x81 &&
                resp[i+2] == 0x81 && resp[i+3] == 0x00) {
                memmove(resp, resp + i + 4, 128);
                *rlen = 128;
                extracted = 1;
                fprintf(stderr, "[mfi] extracted raw RSA signature (128B) from PKCS#7 blob\n");
                break;
            }
            /* Alternate encoding in some blobs: 04 81 80 <128 bytes> */
            if (resp[i] == 0x04 && resp[i+1] == 0x81 && resp[i+2] == 0x80) {
                memmove(resp, resp + i + 3, 128);
                *rlen = 128;
                extracted = 1;
                fprintf(stderr, "[mfi] extracted raw RSA signature (128B octet string)\n");
                break;
            }
        }
        if (!extracted) {
            fprintf(stderr, "[mfi] signature extraction enabled but pattern not found; sending full blob\n");
        }
    }
    uint32_t h = 2166136261u;
    for (int i = 0; i < *rlen; i++) { h ^= resp[i]; h *= 16777619u; }
    fprintf(stderr, "[mfi] auth blob: %d bytes, starts %02x%02x%02x%02x\n",
            *rlen, resp[0], resp[1], resp[2], resp[3]);
    if (*rlen >= 8) {
        fprintf(stderr, "[mfi] auth blob hash=0x%08x tail=%02x%02x%02x%02x%02x%02x%02x%02x\n",
                h,
                resp[*rlen-8], resp[*rlen-7], resp[*rlen-6], resp[*rlen-5],
                resp[*rlen-4], resp[*rlen-3], resp[*rlen-2], resp[*rlen-1]);
    }
    return 0;
}



static uint8_t cksum(const uint8_t *buf, int n)
{
    uint8_t s = 0;
    for (int i = 0; i < n; i++) s += buf[i];
    return (uint8_t)((~s) + 1);
}

/* Write one raw iAP2 link packet (data or link-control) */
static int iap2_write_pkt(int fd, uint8_t ctl, uint8_t sid,
                           uint8_t seq, uint8_t ack,
                           const uint8_t *payload, int plen)
{
    uint8_t hdr[9];
    int total = 9 + plen + (plen > 0 ? 1 : 0);  /* hdr + payload + payload cksum */
    hdr[0] = 0xFF;
    hdr[1] = 0x5A;
    hdr[2] = (total >> 8) & 0xFF;
    hdr[3] =  total       & 0xFF;
    hdr[4] = ctl;
    hdr[5] = seq;
    hdr[6] = ack;
    hdr[7] = sid;
    hdr[8] = cksum(hdr, 8);

    uint8_t buf[4096];
    memcpy(buf, hdr, 9);
    if (plen > 0) {
        memcpy(buf + 9, payload, plen);
        buf[9 + plen] = cksum(payload, plen);
    }
    return (write(fd, buf, total) == total) ? 0 : -1;
}

/* Send a control-session message: MSG_LEN(2) MSG_ID(2) [params] */
static int iap2_send_msg(int fd, uint8_t sid, uint8_t seq, uint8_t ack,
                          uint16_t msg_id, const uint8_t *params, int plen)
{
    uint8_t buf[2048];
    int total = 6 + plen;
    buf[0] = (IAP2_CSM_START >> 8) & 0xFF;
    buf[1] =  IAP2_CSM_START       & 0xFF;
    buf[2] = (total >> 8) & 0xFF;
    buf[3] =  total       & 0xFF;
    buf[4] = (msg_id >> 8) & 0xFF;
    buf[5] =  msg_id       & 0xFF;
    if (plen > 0) memcpy(buf + 6, params, plen);
    int ret = iap2_write_pkt(fd, IAP2_CTL_ACK, sid, seq, ack, buf, total);
    fprintf(stderr, "[iap2] tx msg 0x%04X sid=%u seq=%u ack=%u len=%d ret=%d\n",
            msg_id, sid, seq, ack, total, ret);
    return ret;
}

/* Append iAP2 parameter: LEN(2) ID(2) DATA */
static int iap2_param(uint8_t *buf, int off,
                       uint16_t param_id, const void *data, int dlen)
{
    uint16_t plen = 4 + dlen;
    buf[off++] = (plen >> 8) & 0xFF;
    buf[off++] =  plen       & 0xFF;
    buf[off++] = (param_id >> 8) & 0xFF;
    buf[off++] =  param_id       & 0xFF;
    if (dlen > 0) { memcpy(buf + off, data, dlen); off += dlen; }
    return off;
}

/* Build a SYN packet with mandatory link synchronisation parameters + session list.
 * Payload (14 bytes):
 *   Version(1)=1  MaxOutstandingPkts(1)=7  MaxPktLen(2)=0x0800
 *   RetxTimeout(2)=250 ms  CumAckTimeout(2)=25 ms
 *   MaxRetx(1)=3  MaxCumAck(1)=1
 *   NumSessions(1)=1  SID(1)=0  Type(1)=0(Control)  Ver(1)=1
 */
static int iap2_write_syn(int fd, uint8_t seq)
{
    uint8_t params[14] = {
        0x01,        /* version */
        0x07,        /* MaxOutstandingPackets */
        0x08, 0x00,  /* MaxPacketLength = 2048 */
        0x00, 0xFA,  /* RetransmissionTimeout = 250 ms */
        0x00, 0x19,  /* CumulativeAckTimeout  =  25 ms */
        0x03,        /* MaxRetransmissions */
        0x01,        /* MaxCumAck */
        /* Session list */
        0x01,        /* NumSessions = 1 */
        0x00,        /* Session 0: SID = 0 */
        0x00,        /* Session 0: Type = 0 (Control) */
        0x01,        /* Session 0: Version = 1 */
    };
    /* Log the full SYN packet for debugging */
    uint16_t total = 9 + (uint16_t)sizeof(params) + 1;
    fprintf(stderr, "[iap2] SYN pkt: ff 5a %02x %02x  80 %02x 00 00 XX  payload(%d): "
            "%02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x\n",
            (total >> 8) & 0xFF, total & 0xFF, seq,
            (int)sizeof(params),
            params[0], params[1], params[2], params[3], params[4], params[5],
            params[6], params[7], params[8], params[9],
            params[10], params[11], params[12], params[13]);
    return iap2_write_pkt(fd, IAP2_CTL_SYN, 0, seq, 0, params, sizeof(params));
}

typedef struct iap2_conn {
    int    fd;
    int    server_mode;  /* 1 = iPhone connected to us (NewConnection), 0 = we connected */
    uint8_t control_sid;
    uint8_t last_rx_seq;
    uint16_t last_tx_msg_id;
    uint8_t  last_tx_seq;
    uint8_t  tx_seq;     /* current outgoing seq — shared with FIFO thread */
    int      last_tx_params_len;
    uint8_t  last_tx_params[1536];
    char   device[256];
} iap2_conn_t;

static int iap2_send_control_msg(iap2_conn_t *c, uint8_t seq, uint16_t msg_id,
                                 const uint8_t *params, int plen, int cache_for_eak)
{
    uint8_t tx_sid = getenv("IAP2_TX_SID0") ? IAP2_SID_CTL : c->control_sid;
    int ret = iap2_send_msg(c->fd, tx_sid, seq, c->last_rx_seq, msg_id, params, plen);
    if (ret == 0) c->tx_seq = seq;  /* always track outgoing seq for FIFO thread */
    if (ret == 0 && cache_for_eak) {
        c->last_tx_msg_id = msg_id;
        c->last_tx_seq = seq;
        c->last_tx_params_len = 0;
        if (params && plen > 0) {
            int n = plen;
            if (n > (int)sizeof(c->last_tx_params)) n = (int)sizeof(c->last_tx_params);
            memcpy(c->last_tx_params, params, n);
            c->last_tx_params_len = n;
        }
    }
    return ret;
}

/* ── iAP2 identification ─────────────────────────────────────────────────── */
#define IAP2_MSG_ID_START           0x1D00  /* StartIdentification (dev → acc) */
#define IAP2_MSG_ID_INFO            0x1D01  /* IdentificationInformation (acc → dev) */
#define IAP2_MSG_ID_ACCEPTED        0x1D02  /* IdentificationAccepted (dev → acc) */
#define IAP2_MSG_ID_REJECTED        0x1D03  /* IdentificationRejected (dev → acc) */
#define IAP2_MSG_START_NOWPLAYING   0x40C8  /* StartNowPlayingUpdates (acc → dev) */
#define IAP2_MSG_STOP_NOWPLAYING    0x40C9  /* StopNowPlayingUpdates  (acc → dev) */

static void read_file_str(const char *path, char *buf, int maxlen,
                           const char *fallback)
{
    FILE *f = fopen(path, "r");
    if (!f) { snprintf(buf, maxlen, "%s", fallback); return; }
    if (!fgets(buf, maxlen, f)) snprintf(buf, maxlen, "%s", fallback);
    fclose(f);
    buf[strcspn(buf, "\r\n")] = '\0';
}

/* Build StartIdentification parameters into buf, return byte count */
static int iap2_build_identify_params(uint8_t *buf, int maxlen)
{
    int off = 0;
    const char *name  = "Spotify Car Thing";
    const char *model = "b07968e176d74bae";
    const char *mfr   = "Spotify USA Inc.";
    char serial[64];
    read_file_str("/var/etc/serial_number", serial, sizeof(serial), "8555R08SQN19");

    off = iap2_param(buf, off, 0x0000, name,   (int)strlen(name) + 1);
    off = iap2_param(buf, off, 0x0001, model,  (int)strlen(model) + 1);
    off = iap2_param(buf, off, 0x0002, mfr,    (int)strlen(mfr) + 1);
    off = iap2_param(buf, off, 0x0003, serial, (int)strlen(serial) + 1);

    off = iap2_param(buf, off, 0x0004, "0.48.2", 7);
    off = iap2_param(buf, off, 0x0005, "1.0.0", 6);

    /* 0x0006 — MessagesSentByAccessory: NowPlaying only (diagnostic, no HID) */
    {
        uint8_t tx_ids[] = {
            0x40, 0xC8,  /* StartNowPlayingUpdates */
            0x40, 0xC9,  /* StopNowPlayingUpdates */
        };
        off = iap2_param(buf, off, 0x0006, tx_ids, (int)sizeof(tx_ids));
    }
    /* 0x0007 — MessagesReceivedByAccessory */
    {
        uint8_t rx_ids[] = {
            0x48, 0x00,  /* NowPlayingUpdates (from iPhone → us) */
        };
        off = iap2_param(buf, off, 0x0007, rx_ids, (int)sizeof(rx_ids));
    }

    uint8_t power_cap = 0x00; /* self-powered */
    off = iap2_param(buf, off, 0x0008, &power_cap, 1);
    uint8_t max_current[2] = {0x00, 0x64};  /* 100 mA */
    off = iap2_param(buf, off, 0x0009, max_current, 2);

    /* Try MINIMAL IdentificationInformation: NO 0x000A at all
     * Just Name, Model, Manufacturer, Serial, FW, HW, Power, Current */

    uint8_t btc[96]; int boff = 0;
    uint8_t tid[2] = {0x00, 0x01};
    char mac_str[20];
    uint8_t mac[6] = {0};
    boff = iap2_param(btc, boff, 0x0000, tid, 2);
    boff = iap2_param(btc, boff, 0x0001, "Bluetooth", 10);
    boff = iap2_param(btc, boff, 0x0002, NULL, 0); /* supports iAP2 connection */
    read_file_str("/sys/class/bluetooth/hci0/address", mac_str, sizeof(mac_str),
                  "30:E3:D6:00:5F:A4");
    mac_str[strcspn(mac_str, "\r\n")] = '\0';
    sscanf(mac_str, "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
           &mac[0],&mac[1],&mac[2],&mac[3],&mac[4],&mac[5]);
    boff = iap2_param(btc, boff, 0x0003, mac, 6);
    off  = iap2_param(buf, off,  0x0011, btc, boff);

    off = iap2_param(buf, off, 0x000C, "en", 3);
    off = iap2_param(buf, off, 0x000D, "en", 3);

    /* HIDComponent omitted in this build — diagnostic: test if identification
     * passes without HID. If yes, add back with correct HIDComponentFunction. */

    (void)maxlen;
    return off;
}

/* Send a raw iAP2 message (0xFF 0x5A framing, NO link-layer) */
static int iap2_send_raw_msg(int fd, uint16_t msg_id,
                              const uint8_t *params, int plen)
{
    uint8_t buf[2048];
    uint16_t total = (uint16_t)(6 + plen);
    buf[0] = 0xFF; buf[1] = 0x5A;
    buf[2] = (total >> 8) & 0xFF;
    buf[3] =  total       & 0xFF;
    buf[4] = (msg_id >> 8) & 0xFF;
    buf[5] =  msg_id       & 0xFF;
    if (plen > 0) memcpy(buf + 6, params, plen);
    fprintf(stderr, "[iap2] raw → msg_id=0x%04x total=%d bytes\n", msg_id, total);
    return (write(fd, buf, total) == total) ? 0 : -1;
}

static void send_identification(iap2_conn_t *c, uint8_t *seq)
{
    uint8_t buf[2048];
    int off = iap2_build_identify_params(buf, sizeof(buf));
    fprintf(stderr, "[iap2] → IdentificationInformation (%d param bytes)\n", off);
    fprintf(stderr, "[iap2] IdentificationInformation head:");
    for (int i = 0; i < off && i < 128; i++) fprintf(stderr, " %02x", buf[i]);
    if (off > 128) fprintf(stderr, " ...");
    fprintf(stderr, "\n");
    iap2_send_control_msg(c, ++(*seq), IAP2_MSG_ID_INFO, buf, off, 1);
}

static void send_start_nowplaying(iap2_conn_t *c, uint8_t *seq)
{
    uint8_t buf[64]; int off = 0;
    uint16_t fields[] = {0x0001, 0x0002, 0x0003, 0x0008, 0x000F, 0x0010};
    for (int i = 0; i < (int)(sizeof(fields)/sizeof(fields[0])); i++) {
        uint8_t fid[2] = {fields[i] >> 8, fields[i] & 0xFF};
        off = iap2_param(buf, off, 0x0000, fid, 2);
    }
    fprintf(stderr, "[iap2] → StartNowPlayingUpdates\n");
    iap2_send_control_msg(c, ++(*seq), IAP2_MSG_START_NOWPLAYING, buf, off, 1);
}

static void send_start_hid(iap2_conn_t *c, uint8_t *seq)
{
    if (g_iap2_hid_reset_first) {
        fprintf(stderr, "[iap2] → StopHID\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_STOP_HID, NULL, 0, 1);
    }
    fprintf(stderr, "[iap2] → StartHID (with Consumer Control descriptor, %d bytes)\n",
            (int)sizeof(kHidConsumerDesc));
    uint8_t sbuf[128]; int soff = 0;
    uint8_t cid[2] = { HID_COMPONENT_ID >> 8, HID_COMPONENT_ID & 0xFF };
    soff = iap2_param(sbuf, soff, 0x0000, cid, 2);                           /* HIDComponentIdentifier */
    soff = iap2_param(sbuf, soff, 0x0001, kHidConsumerDesc,
                      (int)sizeof(kHidConsumerDesc));                          /* HIDDescriptor */
    iap2_send_control_msg(c, ++(*seq), IAP2_MSG_START_HID, sbuf, soff, 1);
}

static void send_accessory_hid_report(iap2_conn_t *c, uint8_t *seq, uint16_t usage)
{
    uint8_t pbuf[32];
    uint8_t cid[2] = { HID_COMPONENT_ID >> 8, HID_COMPONENT_ID & 0xFF };
    uint8_t press2[2] = { (uint8_t)(usage >> 8), (uint8_t)(usage & 0xFF) };
    uint8_t rel2[2]   = { 0x00, 0x00 };
    uint8_t press3[3] = { 0x02, (uint8_t)(usage >> 8), (uint8_t)(usage & 0xFF) };
    uint8_t rel3[3]   = { 0x02, 0x00, 0x00 };
    uint8_t press2_le[2] = { (uint8_t)(usage & 0xFF), (uint8_t)(usage >> 8) };
    uint8_t rel2_le[2]   = { 0x00, 0x00 };
    uint8_t press3_le[3] = { 0x01, (uint8_t)(usage & 0xFF), (uint8_t)(usage >> 8) };
    uint8_t rel3_le[3]   = { 0x01, 0x00, 0x00 };

    if (g_iap2_test_hid_mode == 1 || g_iap2_test_hid_mode == 4) {
        int off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, press2, 2);
        fprintf(stderr, "[iap2] → HID mode1 msg=0x6801 usage=0x%04X (press)\n", usage);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
        off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, rel2, 2);
        fprintf(stderr, "[iap2] → HID mode1 msg=0x6801 usage=0x0000 (release)\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
    }
    if (g_iap2_test_hid_mode == 2 || g_iap2_test_hid_mode == 4) {
        int off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, press3, 3);
        fprintf(stderr, "[iap2] → HID mode2 msg=0x6801 rid=0x02 usage=0x%04X (press)\n", usage);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
        off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, rel3, 3);
        fprintf(stderr, "[iap2] → HID mode2 msg=0x6801 rid=0x02 usage=0x0000 (release)\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
    }
    if (g_iap2_test_hid_mode == 3 || g_iap2_test_hid_mode == 4) {
        int off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, press2, 2);
        fprintf(stderr, "[iap2] → HID mode3 legacy msg=0x6802 usage=0x%04X (press)\n", usage);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_DEVICE_HID_REPORT, pbuf, off, 1);
        off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, rel2, 2);
        fprintf(stderr, "[iap2] → HID mode3 legacy msg=0x6802 usage=0x0000 (release)\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_DEVICE_HID_REPORT, pbuf, off, 1);
    }
    if (g_iap2_test_hid_mode == 5) {
        int off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, press2_le, 2);
        fprintf(stderr, "[iap2] → HID mode5 msg=0x6801 usage(le)=0x%04X (press)\n", usage);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
        off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, rel2_le, 2);
        fprintf(stderr, "[iap2] → HID mode5 msg=0x6801 usage(le)=0x0000 (release)\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
    }
    if (g_iap2_test_hid_mode == 6) {
        int off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, press3_le, 3);
        fprintf(stderr, "[iap2] → HID mode6 msg=0x6801 rid=0x01 usage(le)=0x%04X (press)\n", usage);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
        off = iap2_param(pbuf, 0, 0x0000, cid, 2);
        off = iap2_param(pbuf, off, 0x0001, rel3_le, 3);
        fprintf(stderr, "[iap2] → HID mode6 msg=0x6801 rid=0x01 usage(le)=0x0000 (release)\n");
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_HID_REPORT, pbuf, off, 1);
    }
}

/* Handle one raw iAP2 message (0xFF 0x5A mode, no link-layer) */
static void iap2_handle_raw_msg(iap2_conn_t *c, uint16_t msg_id,
                                 const uint8_t *params, int plen)
{
    fprintf(stderr, "[iap2] raw ← msg_id=0x%04x plen=%d\n", msg_id, plen);
    uint8_t buf[1100]; int off;

    switch (msg_id) {
    case IAP2_MSG_AUTH_CERT_REQ:
        fprintf(stderr, "[iap2] raw → AuthCertificate\n");
        if (mfi_cert_len <= 0) { iap2_send_raw_msg(c->fd, IAP2_MSG_AUTH_FAILED, NULL, 0); break; }
        off = iap2_param(buf, 0, 0x0000, mfi_cert, mfi_cert_len);
        iap2_send_raw_msg(c->fd, IAP2_MSG_AUTH_CERT_RESP, buf, off);
        break;

    case IAP2_MSG_AUTH_CHAL_REQ:
        fprintf(stderr, "[iap2] raw → AuthChallengeResponse\n");
        if (plen < 4) break;
        {
            uint16_t pl2  = ((uint16_t)params[0] << 8) | params[1];
            const uint8_t *chal = params + 4;
            int clen = (int)pl2 - 4;
            if (clen <= 0) break;
            unsigned char resp[1024]; int rlen = 0;
            if (mfi_sign(chal, clen, resp, &rlen) == 0 && rlen > 0) {
                off = iap2_param(buf, 0, 0x0000, resp, rlen);
                iap2_send_raw_msg(c->fd, IAP2_MSG_AUTH_CHAL_RESP, buf, off);
            } else {
                iap2_send_raw_msg(c->fd, IAP2_MSG_AUTH_FAILED, NULL, 0);
            }
        }
        break;

    case IAP2_MSG_AUTH_OK: {
        fprintf(stderr, "[iap2] raw ✓ Auth OK — waiting for StartIdentification\n");
        break;
    }

    case IAP2_MSG_ID_START: {
        fprintf(stderr, "[iap2] raw ← StartIdentification\n");
        uint8_t pbuf[512];
        int plen2 = iap2_build_identify_params(pbuf, sizeof(pbuf));
        iap2_send_raw_msg(c->fd, IAP2_MSG_ID_INFO, pbuf, plen2);
        break;
    }

    case IAP2_MSG_AUTH_FAILED:
        fprintf(stderr, "[iap2] raw ✗ Auth FAILED\n");
        break;

    case IAP2_MSG_ID_ACCEPTED:
        fprintf(stderr, "[iap2] raw ✓ Identification accepted!\n");
        {
            uint8_t pbuf[64]; int poff = 0;
            uint16_t fields[] = {0x0001, 0x0002, 0x0003, 0x0008, 0x000F, 0x0010};
            for (int i = 0; i < (int)(sizeof(fields)/sizeof(fields[0])); i++) {
                uint8_t fid[2] = {fields[i] >> 8, fields[i] & 0xFF};
                poff = iap2_param(pbuf, poff, 0x0000, fid, 2);
            }
            iap2_send_raw_msg(c->fd, IAP2_MSG_START_NOWPLAYING, pbuf, poff);
        }
        break;

    case IAP2_MSG_ID_REJECTED:
        fprintf(stderr, "[iap2] raw ✗ Identification REJECTED\n");
        break;

    case IAP2_MSG_NOWPLAYING_UPDATE: {
        char title[256]="", artist[256]="", album[256]="";
        int p = 0;
        while (p + 4 <= plen) {
            uint16_t pl  = ((uint16_t)params[p] << 8) | params[p+1];
            uint16_t pi  = ((uint16_t)params[p+2] << 8) | params[p+3];
            int dl = (int)pl - 4;
            if (pl < 4 || p + (int)pl > plen) break;
            switch (pi) {
            case 0x0001: snprintf(title,  256, "%.*s", dl, params+p+4); break;
            case 0x0002: snprintf(artist, 256, "%.*s", dl, params+p+4); break;
            case 0x0003: snprintf(album,  256, "%.*s", dl, params+p+4); break;
            }
            p += (int)pl;
        }
        printf("NOWPLAYING title=%s artist=%s album=%s\n", title, artist, album);
        fflush(stdout);
        break;
    }
    default:
        fprintf(stderr, "[iap2] raw unhandled msg_id=0x%04x\n", msg_id);
        break;
    }
}

static void iap2_handle_control(iap2_conn_t *c,
                                 const uint8_t *payload, int plen,
                                 uint8_t *seq)
{
    if (plen < 6) return;
    uint16_t start = ((uint16_t)payload[0] << 8) | payload[1];
    if (start != IAP2_CSM_START) {
        fprintf(stderr, "[iap2] ctrl payload without CSM start: %02x%02x\n", payload[0], payload[1]);
        return;
    }
    uint16_t csm_len = ((uint16_t)payload[2] << 8) | payload[3];
    uint16_t msg_id  = ((uint16_t)payload[4] << 8) | payload[5];
    if (csm_len < 6 || csm_len > plen) {
        fprintf(stderr, "[iap2] ctrl bad CSM length=%u plen=%d\n", csm_len, plen);
        return;
    }
    const uint8_t *params = payload + 6;
    int           params_len = (int)csm_len - 6;

    fprintf(stderr, "[iap2] ctrl msg 0x%04X (%d bytes params)\n",
            msg_id, params_len);

    uint8_t buf[1100];
    int off;

    switch (msg_id) {

    case IAP2_MSG_AUTH_CERT_REQ:
        fprintf(stderr, "[iap2] → AuthenticationCertificate\n");
        if (mfi_cert_len <= 0) {
            iap2_send_control_msg(c, ++(*seq), IAP2_MSG_AUTH_FAILED, NULL, 0, 1);
            break;
        }
        off = iap2_param(buf, 0, 0x0000, mfi_cert, mfi_cert_len);
        iap2_send_control_msg(c, ++(*seq), IAP2_MSG_AUTH_CERT_RESP, buf, off, 1);
        break;

    case IAP2_MSG_AUTH_CHAL_REQ:
        fprintf(stderr, "[iap2] → AuthenticationChallengeResponse\n");
        if (params_len < 4) break;
        {
            /* param 0: challenge bytes */
            uint16_t plen2 = ((uint16_t)params[0] << 8) | params[1];
            const uint8_t *challenge = params + 4;
            int            clen      = (int)plen2 - 4;
            if (clen <= 0) break;
            fprintf(stderr, "[iap2] challenge len=%d:", clen);
            for (int i = 0; i < clen && i < 64; i++) fprintf(stderr, " %02x", challenge[i]);
            if (clen > 64) fprintf(stderr, " ...");
            fprintf(stderr, "\n");

            unsigned char resp[1024];
            int           rlen = 0;
            if (mfi_sign(challenge, clen, resp, &rlen) == 0 && rlen > 0) {
                fprintf(stderr, "[iap2] challenge response len=%d head=%02x%02x%02x%02x tail=%02x%02x%02x%02x\n",
                        rlen, resp[0], resp[1], resp[2], resp[3],
                        resp[rlen-4], resp[rlen-3], resp[rlen-2], resp[rlen-1]);
                off = iap2_param(buf, 0, 0x0000, resp, rlen);
                iap2_send_control_msg(c, ++(*seq), IAP2_MSG_AUTH_CHAL_RESP, buf, off, 1);
            } else {
                iap2_send_control_msg(c, ++(*seq), IAP2_MSG_AUTH_FAILED, NULL, 0, 1);
            }
        }
        break;

    case IAP2_MSG_AUTH_OK:
        fprintf(stderr, "[iap2] ✓ Authentication succeeded!\n");
        fprintf(stderr, "[iap2] waiting for StartIdentification from iPhone\n");
        break;

    case IAP2_MSG_ID_START:
        fprintf(stderr, "[iap2] ← StartIdentification\n");
        send_identification(c, seq);
        break;

    case IAP2_MSG_ID_ACCEPTED:
        fprintf(stderr, "[iap2] ✓ Identification accepted!\n");
        if (g_iap2_hid_first) {
            send_start_hid(c, seq);
            send_start_nowplaying(c, seq);
        } else {
            send_start_nowplaying(c, seq);
            send_start_hid(c, seq);
        }
        if (g_iap2_test_hid_usage != 0) {
            send_accessory_hid_report(c, seq, g_iap2_test_hid_usage);
        }
        break;

    case IAP2_MSG_ID_REJECTED:
        fprintf(stderr, "[iap2] ✗ Identification REJECTED\n");
        if (params_len > 0) {
            fprintf(stderr, "[iap2] IdentificationRejected params:");
            for (int i = 0; i < params_len; i++) fprintf(stderr, " %02x", params[i]);
            fprintf(stderr, "\n");
        }
        break;

    case IAP2_MSG_AUTH_FAILED:
        fprintf(stderr, "[iap2] ✗ Authentication FAILED\n");
        break;

    case IAP2_MSG_NOWPLAYING_UPDATE:
        /* Parse title/artist/album and print to stdout for display layer */
        {
            char title[256]="", artist[256]="", album[256]="";
            int p = 0;
            while (p + 4 <= params_len) {
                uint16_t pl = ((uint16_t)params[p] << 8) | params[p+1];
                uint16_t pi = ((uint16_t)params[p+2] << 8) | params[p+3];
                int dl = (int)pl - 4;
                if (pl < 4 || p + pl > params_len) break;
                switch (pi) {
                case 0x0001: snprintf(title,  256, "%.*s", dl, params+p+4); break;
                case 0x0002: snprintf(artist, 256, "%.*s", dl, params+p+4); break;
                case 0x0003: snprintf(album,  256, "%.*s", dl, params+p+4); break;
                }
                p += pl;
            }
            printf("NOWPLAYING title=%s artist=%s album=%s\n",
                   title, artist, album);
            fflush(stdout);
        }
        break;

    case IAP2_MSG_DEVICE_HID_REPORT:
        fprintf(stderr, "[iap2] ← DeviceHIDReport (%d bytes)\n", params_len);
        break;

    default:
        break;
    }
}

static void *iap2_conn_thread(void *arg)
{
    iap2_conn_t *c = (iap2_conn_t *)arg;
    uint8_t buf[4096];
    int     total = 0;
    uint8_t seq   = 0;

    fprintf(stderr, "[iap2] connection from %s (fd=%d) server_mode=%d\n",
            c->device, c->fd, c->server_mode);

    /* Diagnose fd */
    {
        int type = -1; socklen_t tl = sizeof(type);
        getsockopt(c->fd, SOL_SOCKET, SO_TYPE, &type, &tl);
        struct sockaddr_storage ss = {0}; socklen_t sl = sizeof(ss);
        int gpret = getpeername(c->fd, (struct sockaddr *)&ss, &sl);
        fprintf(stderr, "[iap2] fd=%d SO_TYPE=%d af=%d getpeername=%d errno=%d\n",
                c->fd, type, ss.ss_family, gpret, gpret < 0 ? errno : 0);
        uint8_t pk[32] = {0};
        int pn = recv(c->fd, pk, sizeof(pk), MSG_PEEK | MSG_DONTWAIT);
        fprintf(stderr, "[iap2] peek immediately: n=%d errno=%d\n", pn, pn<0?errno:0);
        if (pn > 0) fprintf(stderr, "[iap2] peek data: %02x %02x %02x %02x\n",
                            pk[0], pk[1], pk[2], pk[3]);
    }

    /* Clear O_NONBLOCK set by BlueZ */
    {
        int flags = fcntl(c->fd, F_GETFL, 0);
        if (flags >= 0) fcntl(c->fd, F_SETFL, flags & ~O_NONBLOCK);
        fprintf(stderr, "[iap2] fd flags before=0x%x → now blocking\n", flags);
    }

    /* ── CLIENT MODE: мы инициаторы — не ждём, сразу SYN ── */
    if (!c->server_mode) {
        fprintf(stderr, "[iap2] CLIENT MODE: sending SYN immediately (we are initiator)\n");
        seq = 0;
        struct timeval tv = { .tv_sec = 15, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        for (int attempt = 1; attempt <= 5; attempt++) {
            int ret = iap2_write_syn(c->fd, seq);
            fprintf(stderr, "[iap2] CLIENT SYN #%d sent (ret=%d errno=%d %s)\n",
                    attempt, ret, errno, strerror(errno));
            if (ret < 0) goto done_conn;
            errno = 0;
            total = 0;
            for (;;) {
                int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
                if (n <= 0) {
                    if (errno == EINTR) continue;
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        fprintf(stderr, "[iap2] CLIENT SYN #%d: no reply in 15s\n", attempt);
                    } else {
                        fprintf(stderr, "[iap2] CLIENT SYN #%d: read error errno=%d %s\n",
                                attempt, errno, strerror(errno));
                        goto done_conn;
                    }
                    break;
                }
                fprintf(stderr, "[iap2] CLIENT rx %d bytes:", n);
                for (int i = 0; i < n && i < 64; i++) fprintf(stderr, " %02x", buf[total + i]);
                if (n > 64) fprintf(stderr, " ...");
                fprintf(stderr, "\n");
                total += n;
                if (total >= 5 && buf[0] == 0xFF && buf[1] == 0x5A) {
                    uint8_t ctl = (total >= 5) ? buf[4] : 0;
                    fprintf(stderr, "[iap2] CLIENT: iPhone replied ctl=0x%02x\n", ctl);
                    if (ctl & IAP2_CTL_SYN) {
                        uint8_t pkt_seq = (total >= 6) ? buf[5] : 0;
                        fprintf(stderr, "[iap2] CLIENT: ← SYN+ACK (seq=%d), sending ACK\n",
                                pkt_seq);
                        seq = 0;
                        iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
                        total = 0;
                        goto link_data_loop;
                    }
                    goto link_data_loop;
                }
                if (total >= 2 && buf[0] == 0xFF && buf[1] == 0x5A) {
                    fprintf(stderr, "[iap2] CLIENT: iPhone replied raw iAP2\n");
                    goto raw_data_loop;
                }
                if (total >= (int)sizeof(buf)) break;
            }
        }
        fprintf(stderr, "[iap2] CLIENT: iPhone did not respond to SYN after 5 attempts\n");
        goto done_conn;
    }

    /* ── SERVER MODE (NewConnection): short LISTEN PHASE ── */
    {
        struct timeval tv = { .tv_sec = 5, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        fprintf(stderr, "[iap2] LISTEN phase: waiting 5s for iPhone to send anything...\n");
        for (;;) {
            int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    fprintf(stderr, "[iap2] LISTEN timeout (5s): iPhone sent %d bytes total\n", total);
                } else {
                    fprintf(stderr, "[iap2] LISTEN closed (errno=%d %s): iPhone sent %d bytes\n",
                            errno, strerror(errno), total);
                }
                break;
            }
            fprintf(stderr, "[iap2] LISTEN rx %d bytes:", n);
            for (int i = 0; i < n && i < 64; i++) fprintf(stderr, " %02x", buf[total + i]);
            if (n > 64) fprintf(stderr, " ...");
            fprintf(stderr, "\n");
            total += n;
            if (total >= (int)sizeof(buf)) break;
        }
    }

    /* Decide mode based on what iPhone sent (or didn't send) */
    if (total >= 2 && buf[0] == 0xFF && buf[1] == 0x5A) {
        fprintf(stderr, "[iap2] MODE: iPhone speaks raw iAP2 (0xFF 0x5A)\n");
        goto raw_data_loop;
    }
    if (total >= 5 && buf[0] == 0xFF && buf[1] == 0x5A) {
        uint8_t ctl = (total >= 5) ? buf[4] : 0;
        fprintf(stderr, "[iap2] MODE: iPhone sent link-layer ctl=0x%02x\n", ctl);
        if (ctl & IAP2_CTL_SYN) {
            uint8_t pkt_seq = (total >= 6) ? buf[5] : 0;
            fprintf(stderr, "[iap2] ← iPhone SYN (seq=%d), sending SYN+ACK\n", pkt_seq);
            iap2_write_pkt(c->fd, IAP2_CTL_SYN | IAP2_CTL_ACK,
                           0, ++seq, pkt_seq, NULL, 0);
            total = 0;
        }
        goto link_data_loop;
    }

    if (c->server_mode && total == 0) {
        fprintf(stderr, "[iap2] SERVER MODE: no initial bytes, sending SYN probe\n");
        seq = 0;
        if (iap2_write_syn(c->fd, seq) < 0) {
            fprintf(stderr, "[iap2] SERVER MODE: SYN probe send failed\n");
            goto done_conn;
        }
        {
            struct timeval tv = { .tv_sec = 8, .tv_usec = 0 };
            setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
            total = 0;
            for (;;) {
                int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
                if (n <= 0) {
                    if (errno == EINTR) continue;
                    if (errno == EAGAIN || errno == EWOULDBLOCK) {
                        fprintf(stderr, "[iap2] SERVER MODE: no reply to SYN probe in 8s\n");
                    } else {
                        fprintf(stderr, "[iap2] SERVER MODE: SYN probe read error errno=%d %s\n",
                                errno, strerror(errno));
                    }
                    break;
                }
                fprintf(stderr, "[iap2] SERVER SYN-probe rx %d bytes:", n);
                for (int i = 0; i < n && i < 64; i++) fprintf(stderr, " %02x", buf[total + i]);
                if (n > 64) fprintf(stderr, " ...");
                fprintf(stderr, "\n");
                total += n;
                if (total >= 5 && buf[0] == 0xFF && buf[1] == 0x5A) {
                    uint8_t ctl = (total >= 5) ? buf[4] : 0;
                    if (ctl & IAP2_CTL_SYN) {
                        uint8_t pkt_seq = (total >= 6) ? buf[5] : 0;
                        fprintf(stderr, "[iap2] SERVER MODE: got SYN+ACK (seq=%d), sending ACK\n", pkt_seq);
                        seq = 0;
                        iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
                        total = 0;
                    }
                    goto link_data_loop;
                }
                if (total >= 2 && buf[0] == 0xFF && buf[1] == 0x5A) {
                    goto raw_data_loop;
                }
                if (total >= (int)sizeof(buf)) break;
            }
        }
        if (total == 0) {
            fprintf(stderr, "[iap2] SERVER MODE: iPhone ignored SYN probe, closing socket for clean retry\n");
            goto done_conn;
        }
        {
            struct timeval tv = { 0, 0 };
            setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        }
        fprintf(stderr, "[iap2] SERVER MODE: fallback to passive wait loop\n");
        goto link_data_loop;
    }

    /* iPhone sent nothing — try three modes in order ───────────────── */

    /* ── TRY-A: Raw iAP2 (0xFF 0x5A), no link-layer at all ── */
    fprintf(stderr, "[iap2] TRY-A: raw StartIdentification (0xFF 0x5A)\n");
    {
        uint8_t pbuf[512];
        int plen = iap2_build_identify_params(pbuf, sizeof(pbuf));
        iap2_send_raw_msg(c->fd, IAP2_MSG_ID_INFO, pbuf, plen);
    }
    {
        struct timeval tv = { .tv_sec = 5, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        total = 0;
        for (;;) {
            int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                fprintf(stderr, "[iap2] TRY-A: no reply in 5s\n");
                break;
            }
            fprintf(stderr, "[iap2] TRY-A rx %d bytes:", n);
            for (int i = 0; i < n; i++) fprintf(stderr, " %02x", buf[total + i]);
            fprintf(stderr, "\n");
            total += n;
            if (total >= 2 && buf[0] == 0xFF && buf[1] == 0x5A) {
                fprintf(stderr, "[iap2] TRY-A: iPhone replied raw iAP2 ✓\n");
                goto raw_data_loop;
            }
            if (total >= (int)sizeof(buf)) break;
        }
    }

    /* ── TRY-B: link-layer DATA(seq=0)+StartIdentification (skip SYN) ── */
    fprintf(stderr, "[iap2] TRY-B: direct link-layer DATA without SYN\n");
    seq = 0;
    send_identification(c, &seq);
    {
        struct timeval tv = { .tv_sec = 5, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        total = 0;
        for (;;) {
            int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                fprintf(stderr, "[iap2] TRY-B: no reply in 5s\n");
                break;
            }
            fprintf(stderr, "[iap2] TRY-B rx %d bytes:", n);
            for (int i = 0; i < n; i++) fprintf(stderr, " %02x", buf[total + i]);
            fprintf(stderr, "\n");
            total += n;
            if (total >= 3 && buf[0] == 0xFF) {
                fprintf(stderr, "[iap2] TRY-B: iPhone replied link-layer ✓\n");
                goto link_data_loop;
            }
            if (total >= (int)sizeof(buf)) break;
        }
    }

    /* ── TRY-C: classic SYN/ACK handshake × 3 ── */
    fprintf(stderr, "[iap2] TRY-C: classic SYN/ACK handshake\n");
    seq = 0;
    {
        struct timeval tv = { .tv_sec = 10, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    }
    for (int attempt = 1; attempt <= 3; attempt++) {
        int ret = iap2_write_syn(c->fd, seq);
        fprintf(stderr, "[iap2] SYN #%d sent (ret=%d errno=%d %s)\n",
                attempt, ret, errno, strerror(errno));
        if (ret < 0) goto done_conn;

        total = 0;
        int got_reply = 0;
        while (!got_reply) {
            int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                fprintf(stderr, "[iap2] SYN attempt %d: no reply (errno=%d %s)\n",
                        attempt, errno, strerror(errno));
                break;
            }
            fprintf(stderr, "[iap2] TRY-C rx %d bytes:", n);
            for (int i = 0; i < n; i++) fprintf(stderr, " %02x", buf[total + i]);
            fprintf(stderr, "\n");
            total += n;
            while (total >= 5) {
                if (!(buf[0] == 0xFF && buf[1] == 0x5A)) {
                    int skip = 1;
                    while (skip < total - 1 &&
                           !(buf[skip] == 0xFF && buf[skip+1] == 0x5A)) skip++;
                    memmove(buf, buf + skip, total - skip); total -= skip;
                    continue;
                }
                if (total < 4) break;
                uint16_t pkt_len = ((uint16_t)buf[2] << 8) | buf[3];
                if (pkt_len < 9 || pkt_len > (int)sizeof(buf)) { total = 0; break; }
                if (total < pkt_len) break;
                uint8_t ctl = buf[4], pkt_seq = buf[5];
                fprintf(stderr, "[iap2] TRY-C pkt ctl=0x%02x seq=%d len=%d\n",
                        ctl, pkt_seq, pkt_len);
                if ((ctl & IAP2_CTL_SYN) && (ctl & IAP2_CTL_ACK)) {
                    fprintf(stderr, "[iap2] ← SYN+ACK from iPhone, sending ACK\n");
                    iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
                    struct timeval tv = { 0, 0 };
                    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
                    total = 0;
                    goto link_data_loop;
                } else if ((ctl & IAP2_CTL_SYN) && !(ctl & IAP2_CTL_ACK)) {
                    fprintf(stderr, "[iap2] ← SYN collision, sending SYN+ACK\n");
                    iap2_write_pkt(c->fd, IAP2_CTL_SYN | IAP2_CTL_ACK,
                                   0, ++seq, pkt_seq, NULL, 0);
                    total = 0;
                    goto link_data_loop;
                } else {
                    fprintf(stderr, "[iap2] TRY-C unexpected ctl=0x%02x\n", ctl);
                    got_reply = 1;
                }
                memmove(buf, buf + pkt_len, total - pkt_len); total -= pkt_len;
            }
        }
    }
    fprintf(stderr, "[iap2] all three modes failed — giving up\n");
    goto done_conn;

    /* ── RAW DATA LOOP (0xFF 0x5A messages, no link-layer) ── */
raw_data_loop: {
    fprintf(stderr, "[iap2] ✓ raw iAP2 session active\n");
    struct timeval tv = { 0, 0 };
    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    while (1) {
        int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
        if (n <= 0) {
            fprintf(stderr, "[iap2] raw fd closed: n=%d errno=%d (%s)\n",
                    n, errno, strerror(errno));
            goto done_conn;
        }
        fprintf(stderr, "[iap2] raw rx %d bytes:", n);
        for (int i = 0; i < n; i++) fprintf(stderr, " %02x", buf[total + i]);
        fprintf(stderr, "\n");
        total += n;
        while (total >= 6) {
            if (buf[0] != 0xFF || buf[1] != 0x5A) {
                int skip = 1;
                while (skip < total - 1 &&
                       !(buf[skip] == 0xFF && buf[skip+1] == 0x5A)) skip++;
                memmove(buf, buf + skip, total - skip); total -= skip;
                continue;
            }
            if (total < 4) break;
            uint16_t msg_len = ((uint16_t)buf[2] << 8) | buf[3];
            if (msg_len < 6 || msg_len > (int)sizeof(buf)) {
                fprintf(stderr, "[iap2] raw bad msg_len=%d\n", msg_len);
                total = 0; break;
            }
            if (total < msg_len) break;
            uint16_t msg_id = ((uint16_t)buf[4] << 8) | buf[5];
            iap2_handle_raw_msg(c, msg_id, buf + 6, (int)msg_len - 6);
            memmove(buf, buf + msg_len, total - msg_len); total -= msg_len;
        }
    }
}

    /* ── LINK DATA LOOP (link-layer framing) ── */
link_data_loop: {
    uint8_t control_sid = c->control_sid;
    uint8_t last_ctrl_seq = 0xFF;
    uint16_t last_ctrl_msg = 0xFFFF;
    fprintf(stderr, "[iap2] ✓ link-layer iAP2 session active\n");
    struct timeval tv = { 0, 0 };
    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    while (1) {
        int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
        if (n <= 0) {
            fprintf(stderr, "[iap2] fd closed: n=%d errno=%d (%s)\n",
                    n, errno, strerror(errno));
            goto done_conn;
        }
        fprintf(stderr, "[iap2] rx %d bytes:", n);
        for (int i = 0; i < n; i++) fprintf(stderr, " %02x", buf[total + i]);
        fprintf(stderr, "\n");
        total += n;
        while (total >= 5) {
            if (!(buf[0] == 0xFF && buf[1] == 0x5A)) {
                int skip = 1;
                while (skip < total - 1 &&
                       !(buf[skip] == 0xFF && buf[skip+1] == 0x5A)) skip++;
                memmove(buf, buf + skip, total - skip); total -= skip;
                continue;
            }
            if (total < 4) break;
            uint16_t pkt_len = ((uint16_t)buf[2] << 8) | buf[3];
            if (pkt_len < 9 || pkt_len > (int)sizeof(buf)) {
                fprintf(stderr, "[iap2] bad pkt_len=%d\n", pkt_len);
                total = 0; break;
            }
            if (total < pkt_len) break;
            uint8_t ctl     = buf[4];
            uint8_t pkt_seq = buf[5];
            uint8_t pkt_ack = buf[6];
            uint8_t sid     = buf[7];
            int payload_len = (int)pkt_len - 10;
            c->last_rx_seq = pkt_seq;
            (void)pkt_ack;
            fprintf(stderr, "[iap2] pkt: ctl=0x%02x seq=%d ack=%d sid=%d len=%d\n",
                    ctl, pkt_seq, pkt_ack, sid, pkt_len);
            if (payload_len > 0 && control_sid == IAP2_SID_CTL && sid != IAP2_SID_CTL) {
                control_sid = sid;
                c->control_sid = control_sid;
                fprintf(stderr, "[iap2] adopting control sid=%u from first payload packet\n", control_sid);
            }
            if (ctl & IAP2_CTL_SYN) {
                if (payload_len >= 4) {
                    uint8_t num_sessions = buf[9 + 10];
                    if (num_sessions >= 1 && payload_len >= 13) {
                        control_sid = buf[9 + 11];
                        c->control_sid = control_sid;
                        fprintf(stderr, "[iap2] link sync: negotiated control sid=%u\n", control_sid);
                    }
                }
                fprintf(stderr, "[iap2] link sync: replying ACK to seq=%d\n", pkt_seq);
                iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
            } else if (payload_len > 0 && sid == control_sid) {
                iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
                uint16_t msg_id = 0xFFFF;
                if (payload_len >= 6 &&
                    buf[9] == ((IAP2_CSM_START >> 8) & 0xFF) &&
                    buf[10] == (IAP2_CSM_START & 0xFF)) {
                    msg_id = ((uint16_t)buf[13] << 8) | buf[14];
                }
                fprintf(stderr, "[iap2] ← msg seq=%u 0x%04X len=%d\n", pkt_seq, msg_id, payload_len);
                if (pkt_seq == last_ctrl_seq && msg_id == last_ctrl_msg) {
                    fprintf(stderr, "[iap2] duplicate control pkt seq=%u msg=0x%04X (ignored)\n",
                            pkt_seq, msg_id);
                } else {
                    iap2_handle_control(c, buf + 9, (int)pkt_len - 10, &seq);
                    last_ctrl_seq = pkt_seq;
                    last_ctrl_msg = msg_id;
                }
            } else if (ctl & IAP2_CTL_EAK) {
                fprintf(stderr, "[iap2] EAK received, payload_len=%d\n", payload_len);
                iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq, NULL, 0);
                if (payload_len > 0) {
                    for (int i = 0; i < payload_len; i++) {
                        uint8_t need_seq = buf[9 + i];
                        fprintf(stderr, "[iap2] EAK requests seq=%u\n", need_seq);
                        if (need_seq == c->last_tx_seq && c->last_tx_msg_id != 0) {
                            fprintf(stderr, "[iap2] retransmit msg 0x%04X seq=%u\n",
                                    c->last_tx_msg_id, c->last_tx_seq);
                            iap2_send_control_msg(c, c->last_tx_seq, c->last_tx_msg_id,
                                                  c->last_tx_params_len > 0 ? c->last_tx_params : NULL,
                                                  c->last_tx_params_len, 0);
                        }
                    }
                }
            } else if (ctl & IAP2_CTL_ACK) {
                /* ACK-only */
            } else {
                fprintf(stderr, "[iap2] unknown ctl=0x%02x sid=%d\n", ctl, sid);
            }
            memmove(buf, buf + pkt_len, total - pkt_len); total -= pkt_len;
        }
    }
}

done_conn:
    close(c->fd);
    if (g_active_conn == c) g_active_conn = NULL;  /* clear global reference */
    free(c);
    return NULL;
}

/* ── D-Bus Profile1 method handler ─────────────────────────────────────── */

static void profile_method_call(GDBusConnection       *conn,
                                const gchar           *sender,
                                const gchar           *obj_path,
                                const gchar           *iface,
                                const gchar           *method,
                                GVariant              *params,
                                GDBusMethodInvocation *invocation,
                                gpointer               user_data)
{
    (void)conn; (void)sender; (void)obj_path; (void)iface; (void)user_data;

    if (g_strcmp0(method, "NewConnection") == 0) {
        const gchar *device = "?";
        gint32       fd_idx = 0;
        GVariant    *props  = NULL;
        g_variant_get(params, "(oha{sv})", &device, &fd_idx, &props);

        GDBusMessage *msg = g_dbus_method_invocation_get_message(invocation);
        GUnixFDList  *fdl = g_dbus_message_get_unix_fd_list(msg);
        gint fd = -1;
        if (fdl) {
            GError *e = NULL;
            fd = g_unix_fd_list_get(fdl, fd_idx, &e);
            if (e) { g_error_free(e); fd = -1; }
        }

        fprintf(stderr, "[iap2] NewConnection: %s (fd=%d)\n", device, fd);

        if (fd >= 0) {
            iap2_conn_t *c = calloc(1, sizeof(iap2_conn_t));
            c->fd = fd;
            c->server_mode = 1;  /* inbound NewConnection: wait for iPhone link-init first */
            c->control_sid = IAP2_SID_CTL;
            strncpy(c->device, device, sizeof(c->device) - 1);
            g_active_conn = c;  /* save for FIFO thread access */
            pthread_t t;
            pthread_create(&t, NULL, iap2_conn_thread, c);
            pthread_detach(t);
        }

        g_dbus_method_invocation_return_value(invocation, NULL);
        /* props is a child of params — GLib owns the ref, do NOT unref */

    } else if (g_strcmp0(method, "Release") == 0) {
        fprintf(stderr, "[iap2] Release\n");
        g_dbus_method_invocation_return_value(invocation, NULL);

    } else if (g_strcmp0(method, "RequestDisconnection") == 0) {
        const gchar *device = "?";
        g_variant_get(params, "(o)", &device);
        fprintf(stderr, "[iap2] RequestDisconnection: %s\n", device);
        g_dbus_method_invocation_return_value(invocation, NULL);
    }
}

static const GDBusInterfaceVTable profile_vtable = {
    profile_method_call, NULL, NULL, { 0 }
};

/* ── GLib main-loop & D-Bus setup ───────────────────────────────────────── */

static GMainLoop       *g_loop   = NULL;
static guint            g_reg_id = 0;
static GDBusConnection *g_conn   = NULL;
static volatile int     g_iap2_active = 0; /* 1 = RFCOMM session in progress */
static volatile time_t  g_next_fallback_try = 0;
static volatile int     g_services_resolved = 0;
static int              g_iap2_active_connect = 0; /* fallback RFCOMM client connect on ACL up */
static int              g_iap2_force_reconnect = 0; /* do not drop active ACL by default */
static int              g_iap2_register_client = 1; /* register cafe profile by default */
static int env_bool(const char *name, int defv)
{
    const char *v = getenv(name);
    if (!v || !*v) return defv;
    if (!strcmp(v, "1") || !strcasecmp(v, "true") || !strcasecmp(v, "yes") || !strcasecmp(v, "on")) return 1;
    if (!strcmp(v, "0") || !strcasecmp(v, "false") || !strcasecmp(v, "no") || !strcasecmp(v, "off")) return 0;
    return defv;
}

static uint16_t env_u16_hex(const char *name, uint16_t defv)
{
    const char *v = getenv(name);
    if (!v || !*v) return defv;
    char *end = NULL;
    unsigned long n = strtoul(v, &end, 0);
    if (!end || *end != '\0' || n > 0xFFFFUL) return defv;
    return (uint16_t)n;
}

static int discover_rfcomm_channel(const char *addr_str, const char *uuid)
{
    char cmd[256];
    snprintf(cmd, sizeof(cmd), "sdptool search --bdaddr %s %s 2>/dev/null", addr_str, uuid);
    FILE *fp = popen(cmd, "r");
    if (!fp) return -1;
    char line[256];
    int ch = -1;
    while (fgets(line, sizeof(line), fp)) {
        int v = -1;
        if (sscanf(line, "Channel: %d", &v) == 1 && v > 0 && v < 31) {
            ch = v;
            break;
        }
    }
    pclose(fp);
    return ch;
}

/* ── RFCOMM client connection ───────────────────────────────────────────── */

/* Open a raw RFCOMM socket and connect to addr_str:channel */
static int rfcomm_client_connect(const char *addr_str, int channel)
{
    int s = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);
    if (s < 0) {
        fprintf(stderr, "[iap2] socket() failed: %s\n", strerror(errno));
        return -1;
    }
    struct sockaddr_rc addr;
    memset(&addr, 0, sizeof(addr));
    addr.rc_family  = AF_BLUETOOTH;
    addr.rc_channel = (uint8_t)channel;
    str2ba(addr_str, &addr.rc_bdaddr);

    fprintf(stderr, "[iap2] RFCOMM connecting to %s ch %d...\n",
            addr_str, channel);
    if (connect(s, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        fprintf(stderr, "[iap2] RFCOMM connect failed: %s\n", strerror(errno));
        close(s);
        return -1;
    }
    fprintf(stderr, "[iap2] ✓ RFCOMM connected to %s ch %d\n",
            addr_str, channel);
    return s;
}

typedef struct { char mac[18]; } connect_arg_t;

/* Thread: waits 1s for ACL to settle, then connects RFCOMM and runs iAP2 */
static void *device_connect_thread(void *arg)
{
    connect_arg_t *a = (connect_arg_t *)arg;
    char mac[18] = {0};
    strncpy(mac, a->mac, sizeof(mac) - 1);
    free(a);

    /* No sleep — do SDP discovery immediately (SDP query itself keeps ACL alive).
     * Cache result; iPhone iapd channel changes per session. */
    int ch = discover_rfcomm_channel(mac, IAP2_CLIENT_UUID);
    if (ch <= 0) {
        /* SDP fallback: try our own server UUID (iPhone may list it too) */
        ch = discover_rfcomm_channel(mac, IAP2_SERVER_UUID);
    }
    if (ch <= 0) ch = 1;  /* last resort */
    fprintf(stderr, "[iap2] fallback: iPhone iAP2 device channel=%d\n", ch);
    int fd = rfcomm_client_connect(mac, ch);
    if (fd < 0) {
        g_next_fallback_try = time(NULL) + 30;
        g_iap2_active = 0;
        return NULL;
    }

    iap2_conn_t *c = calloc(1, sizeof(iap2_conn_t));
    c->fd = fd;
    c->server_mode = 0;  /* WE are the RFCOMM client → send SYN first, iPhone replies SYN+ACK */
    c->control_sid = IAP2_SID_CTL;
    strncpy(c->device, mac, sizeof(c->device) - 1);
    
    /* Set global connection pointer for FIFO thread */
    g_active_conn = c;
    
    iap2_conn_thread(c);    /* blocks until connection drops; frees c on exit */
    
    /* Clear global connection pointer */
    g_active_conn = NULL;
    g_iap2_active = 0;
    return NULL;
}

static void schedule_active_connect(const char *mac)
{
    time_t now = time(NULL);
    if (now < g_next_fallback_try) {
        fprintf(stderr, "[iap2] fallback: cooldown active, skip connect\n");
        return;
    }
    if (__sync_lock_test_and_set(&g_iap2_active, 1) == 0) {
        connect_arg_t *a = calloc(1, sizeof(*a));
        strncpy(a->mac, mac, sizeof(a->mac) - 1);
        pthread_t t;
        pthread_create(&t, NULL, device_connect_thread, a);
        pthread_detach(t);
        fprintf(stderr, "[iap2] fallback: active RFCOMM connect scheduled for %s\n", mac);
    } else {
        fprintf(stderr, "[iap2] fallback: session already active, skip duplicate connect\n");
    }
}

/* ── BlueZ Device1.PropertiesChanged signal handler ─────────────────────── */

/* Fires when any BlueZ device property changes.  We look for Connected=true
 * on org.bluez.Device1 and immediately start a client RFCOMM connection. */
static void on_device_property_changed(GDBusConnection *conn,
                                        const gchar *sender_name,
                                        const gchar *object_path,
                                        const gchar *iface_name,
                                        const gchar *signal_name,
                                        GVariant    *parameters,
                                        gpointer     user_data)
{
    (void)conn; (void)sender_name; (void)iface_name; (void)signal_name;
    (void)user_data;

    const gchar *iface   = NULL;
    GVariant    *changed = NULL, *invalid = NULL;
    g_variant_get(parameters, "(&s@a{sv}@as)", &iface, &changed, &invalid);

    if (g_strcmp0(iface, "org.bluez.Device1") != 0) goto done;

    GVariant *cv = g_variant_lookup_value(changed, "Connected",
                                           G_VARIANT_TYPE_BOOLEAN);
    gboolean connected = FALSE;
    if (cv) {
        connected = g_variant_get_boolean(cv);
        g_variant_unref(cv);
    }

    GVariant *sv = g_variant_lookup_value(changed, "ServicesResolved",
                                           G_VARIANT_TYPE_BOOLEAN);
    if (sv) {
        g_services_resolved = g_variant_get_boolean(sv) ? 1 : 0;
        fprintf(stderr, "[iap2] ServicesResolved=%d\n", g_services_resolved);
        g_variant_unref(sv);
    }

    /* Extract MAC from D-Bus path: /org/bluez/hciX/dev_AA_BB_CC_DD_EE_FF */
    const gchar *dev_part = strstr(object_path, "/dev_");
    if (!dev_part) goto done;
    const char *u = dev_part + 5;
    char mac[18] = {0};
    for (int i = 0, j = 0; u[i] && j < 17; i++, j++)
        mac[j] = (u[i] == '_') ? ':' : u[i];

    fprintf(stderr, "[iap2] Device %s: %s\n", mac, connected ? "connected (ACL)" : "disconnected");

    /* Primary mode: wait for iPhone iapd NewConnection.
     * Fallback mode: actively connect RFCOMM to iPhone when ACL is up.
     * NOTE: Classic BT does not use ServicesResolved — connect immediately on ACL up. */
    if (cv && connected) {
        fprintf(stderr, "[iap2] ACL up — scheduling active RFCOMM connect\n");
        if (g_iap2_active_connect) {
            schedule_active_connect(mac);
        }
    }

done:
    if (changed) g_variant_unref(changed);
    if (invalid) g_variant_unref(invalid);
}

/* Register Profile1 D-Bus object for the server profile (once, at startup) */
static int register_dbus_object(GDBusConnection *conn)
{
    GError        *err  = NULL;
    GDBusNodeInfo *info = g_dbus_node_info_new_for_xml(PROFILE_XML, &err);
    if (!info) {
        fprintf(stderr, "[iap2] XML parse error: %s\n", err->message);
        g_error_free(err);
        return -1;
    }
    /* Server profile object at PROFILE_SERVER_PATH */
    g_reg_id = g_dbus_connection_register_object(
                   conn, PROFILE_SERVER_PATH, info->interfaces[0],
                   &profile_vtable, NULL, NULL, &err);
    g_dbus_node_info_unref(info);
    if (!g_reg_id) {
        fprintf(stderr, "[iap2] register_object failed: %s\n", err->message);
        g_error_free(err);
        return -1;
    }
    fprintf(stderr, "[iap2] D-Bus object registered at %s\n", PROFILE_SERVER_PATH);
    return 0;
}

/* Call RegisterProfile on BlueZ — called whenever org.bluez (re)appears.
 *
 * Critical: must use the SAME D-Bus connection that hosts the Profile1 object.
 * BlueZ ties the SDP record lifetime to the unique bus name of that connection.
 */
static void do_register_profile(GDBusConnection *conn)
{
    GError          *err  = NULL;
    GVariantBuilder  opts;

    /* ── Server profile: caff UUID, ch 3, full SDP record ── */
    g_variant_builder_init(&opts, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&opts, "{sv}", "ServiceRecord",
                          g_variant_new_string(SDP_XML));
    g_variant_builder_add(&opts, "{sv}", "Channel",
                          g_variant_new_uint16(IAP2_RFCOMM_CHANNEL));
    g_variant_builder_add(&opts, "{sv}", "Role",
                          g_variant_new_string("server"));
    g_variant_builder_add(&opts, "{sv}", "RequireAuthentication",
                          g_variant_new_boolean(TRUE));
    g_variant_builder_add(&opts, "{sv}", "RequireAuthorization",
                          g_variant_new_boolean(TRUE));

    GVariant *result = g_dbus_connection_call_sync(
                           conn,
                           "org.bluez", "/org/bluez",
                           "org.bluez.ProfileManager1", "RegisterProfile",
                           g_variant_new("(osa{sv})",
                                         PROFILE_SERVER_PATH, IAP2_SERVER_UUID, &opts),
                           NULL, G_DBUS_CALL_FLAGS_NONE, 5000, NULL, &err);
    if (err) {
        if (g_strstr_len(err->message, -1, "Already Exists"))
            fprintf(stderr, "[iap2] server profile already registered (OK)\n");
        else
            fprintf(stderr, "[iap2] RegisterProfile(server) error: %s\n", err->message);
        g_error_free(err);
    } else {
        fprintf(stderr, "[iap2] ✓ iAP2 server SDP registered (caff, ch %d)\n",
                IAP2_RFCOMM_CHANNEL);
        if (result) g_variant_unref(result);
    }

    /* Optional client profile for iPhone-side autoconnect behavior on some stacks. */
    if (g_iap2_register_client) {
        g_variant_builder_init(&opts, G_VARIANT_TYPE("a{sv}"));
        g_variant_builder_add(&opts, "{sv}", "Role",
                              g_variant_new_string("client"));
        g_variant_builder_add(&opts, "{sv}", "AutoConnect",
                              g_variant_new_boolean(TRUE));
        result = g_dbus_connection_call_sync(
                     conn,
                     "org.bluez", "/org/bluez",
                     "org.bluez.ProfileManager1", "RegisterProfile",
                     g_variant_new("(osa{sv})",
                                   PROFILE_CLIENT_PATH, IAP2_CLIENT_UUID, &opts),
                     NULL, G_DBUS_CALL_FLAGS_NONE, 5000, NULL, &err);
        if (err) {
            if (g_strstr_len(err->message, -1, "Already Exists"))
                fprintf(stderr, "[iap2] client profile already registered (OK)\n");
            else
                fprintf(stderr, "[iap2] RegisterProfile(client) error: %s\n", err->message);
            g_error_free(err);
            err = NULL;
        } else {
            fprintf(stderr, "[iap2] ✓ iAP2 client profile registered (cafe, AutoConnect)\n");
            if (result) g_variant_unref(result);
        }
    }
}

/* Disconnect all already-connected BT devices so they will reconnect fresh,
 * which causes iPhone's iapd to see our newly registered SDP and call NewConnection. */
static void force_bt_reconnect(GDBusConnection *conn)
{
    GError   *err  = NULL;
    GVariant *objs = g_dbus_connection_call_sync(
                         conn, "org.bluez", "/",
                         "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                         NULL, G_VARIANT_TYPE("(a{oa{sa{sv}}})"),
                         G_DBUS_CALL_FLAGS_NONE, 5000, NULL, &err);
    if (!objs) {
        if (err) { g_error_free(err); err = NULL; }
        return;
    }

    GVariant *obj_dict = g_variant_get_child_value(objs, 0);
    GVariantIter iter;
    g_variant_iter_init(&iter, obj_dict);
    gchar    *path   = NULL;
    GVariant *ifaces = NULL;

    while (g_variant_iter_next(&iter, "{o@a{sa{sv}}}", &path, &ifaces)) {
        GVariant *dev = g_variant_lookup_value(ifaces, "org.bluez.Device1", NULL);
        if (dev) {
            GVariant *cv = g_variant_lookup_value(dev, "Connected",
                                                   G_VARIANT_TYPE_BOOLEAN);
            if (cv && g_variant_get_boolean(cv)) {
                fprintf(stderr, "[iap2] startup: %s connected → disconnecting to trigger iapd\n",
                        path);
                g_dbus_connection_call_sync(conn, "org.bluez", path,
                    "org.bluez.Device1", "Disconnect",
                    NULL, NULL, G_DBUS_CALL_FLAGS_NONE, 5000, NULL, NULL);
            }
            if (cv) g_variant_unref(cv);
            g_variant_unref(dev);
        }
        g_free(path);
        g_variant_unref(ifaces);
    }
    g_variant_unref(obj_dict);
    g_variant_unref(objs);
}

/* Initiate active RFCOMM connection to any already-connected Apple device */
static void startup_active_connect_if_available(GDBusConnection *conn)
{
    if (!g_iap2_active_connect) return;

    GError   *err  = NULL;
    GVariant *objs = g_dbus_connection_call_sync(
                         conn, "org.bluez", "/",
                         "org.freedesktop.DBus.ObjectManager", "GetManagedObjects",
                         NULL, G_VARIANT_TYPE("(a{oa{sa{sv}}})"),
                         G_DBUS_CALL_FLAGS_NONE, 5000, NULL, &err);
    if (!objs) {
        if (err) { g_error_free(err); err = NULL; }
        return;
    }

    GVariant *obj_dict = g_variant_get_child_value(objs, 0);
    GVariantIter iter;
    g_variant_iter_init(&iter, obj_dict);
    gchar    *path   = NULL;
    GVariant *ifaces = NULL;

    while (g_variant_iter_next(&iter, "{o@a{sa{sv}}}", &path, &ifaces)) {
        GVariant *dev = g_variant_lookup_value(ifaces, "org.bluez.Device1", NULL);
        if (!dev) {
            g_free(path);
            g_variant_unref(ifaces);
            continue;
        }

        GVariant *cv = g_variant_lookup_value(dev, "Connected",
                                               G_VARIANT_TYPE_BOOLEAN);
        GVariant *av = g_variant_lookup_value(dev, "Address",
                                               G_VARIANT_TYPE_STRING);

        if (cv && g_variant_get_boolean(cv) && av) {
            const char *addr = g_variant_get_string(av, NULL);
            fprintf(stderr, "[iap2] startup: found connected device %s → initiating active RFCOMM connect\n", addr);
            schedule_active_connect(addr);
            if (av) g_variant_unref(av);
            if (cv) g_variant_unref(cv);
            g_variant_unref(dev);
            g_free(path);
            g_variant_unref(ifaces);
            break;  /* Connect to first one found */
        }
        if (av) g_variant_unref(av);
        if (cv) g_variant_unref(cv);
        g_variant_unref(dev);
        g_free(path);
        g_variant_unref(ifaces);
    }
    g_variant_unref(obj_dict);
    g_variant_unref(objs);
}

/* org.bluez appeared — bluetoothd just started or restarted */
static void on_bluez_appeared(GDBusConnection *conn,
                               const gchar     *name,
                               const gchar     *name_owner,
                               gpointer         user_data)
{
    (void)name; (void)name_owner; (void)user_data;
    fprintf(stderr, "[iap2] bluetoothd appeared, registering iAP2 profile...\n");
    do_register_profile(conn);

    if (g_iap2_force_reconnect) {
        force_bt_reconnect(conn);
    }

    /* Subscribe to Device1.Connected changes — just for logging, no client mode. */
    g_dbus_connection_signal_subscribe(
        conn,
        "org.bluez",
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        NULL,
        "org.bluez.Device1",
        G_DBUS_SIGNAL_FLAGS_NONE,
        on_device_property_changed,
        NULL, NULL);

    /* Try to connect to any already-connected device at startup */
    startup_active_connect_if_available(conn);

    fprintf(stderr, "[iap2] Waiting for iPhone iapd NewConnection...\n");
}

/* org.bluez vanished — bluetoothd crashed; SDP will re-register on restart */
static void on_bluez_vanished(GDBusConnection *conn,
                               const gchar     *name,
                               gpointer         user_data)
{
    (void)conn; (void)name; (void)user_data;
    fprintf(stderr, "[iap2] bluetoothd vanished — will re-register on restart\n");
}

static gboolean on_signal(gpointer ud)
{
    (void)ud;
    fprintf(stderr, "[iap2] signal received, shutting down\n");
    g_main_loop_quit(g_loop);
    return G_SOURCE_REMOVE;
}

/* ── HID command FIFO reader (button integration) ─────────────────────────── */

static void* thread_read_hid_fifo(void *arg)
{
    (void)arg;
    const char *fifo_path = "/tmp/iap2_hid_cmd";
    
    /* Create FIFO if it doesn't exist */
    unlink(fifo_path);
    if (mkfifo(fifo_path, 0666) < 0 && errno != EEXIST) {
        fprintf(stderr, "[hid] Cannot create FIFO %s: %s\n", fifo_path, strerror(errno));
        return NULL;
    }
    
    fprintf(stderr, "[hid] Reading HID commands from %s\n", fifo_path);

    while (1) {
        /* Open FIFO in O_RDWR to avoid blocking on no writers */
        int fd = open(fifo_path, O_RDWR);
        if (fd < 0) {
            fprintf(stderr, "[hid] Cannot open FIFO: %s\n", strerror(errno));
            sleep(1);
            continue;
        }

        fprintf(stderr, "[hid] FIFO opened, waiting for commands\n");
        uint16_t usage_code;

        while (read(fd, &usage_code, sizeof(usage_code)) == sizeof(usage_code)) {
            iap2_conn_t *c = g_active_conn;
            if (c && c->fd > 0) {
                /* Use connection's seq counter — no more jump from 6 to 101 */
                fprintf(stderr, "[hid] FIFO → HID usage 0x%04X seq=%u\n", usage_code, c->tx_seq);
                send_accessory_hid_report(c, &c->tx_seq, usage_code);
            } else {
                fprintf(stderr, "[hid] FIFO → HID usage 0x%04X (device not ready)\n", usage_code);
            }
        }
        close(fd);
        fprintf(stderr, "[hid] FIFO closed, will reopen in 1s\n");
        sleep(1);
    }
    return NULL;
}

/* ── main ───────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    (void)argc; (void)argv;

    g_iap2_active_connect  = env_bool("IAP2_ACTIVE_CONNECT", 1);
    g_iap2_force_reconnect = env_bool("IAP2_FORCE_RECONNECT", 0);
    g_iap2_register_client = env_bool("IAP2_REGISTER_CLIENT_PROFILE", 1);
    g_iap2_test_hid_usage  = env_u16_hex("IAP2_TEST_HID_USAGE", 0);
    g_iap2_test_hid_mode   = (int)env_u16_hex("IAP2_TEST_HID_MODE", 1);
    g_iap2_hid_reset_first = env_bool("IAP2_HID_RESET_FIRST", 1);
    g_iap2_hid_first       = env_bool("IAP2_HID_FIRST", 1);

    fprintf(stderr, "[iap2] iAP2 Agent v2.4  (client mode + btmon diagnostic)\n");
    fprintf(stderr, "[iap2] UUID:    %s\n", IAP2_UUID);
    fprintf(stderr, "[iap2] Channel: %d\n", IAP2_RFCOMM_CHANNEL);
    fprintf(stderr, "[iap2] mode: active_connect=%d force_reconnect=%d client_profile=%d test_hid=0x%04X mode=%d hid_reset=%d hid_first=%d\n",
            g_iap2_active_connect, g_iap2_force_reconnect, g_iap2_register_client,
            g_iap2_test_hid_usage, g_iap2_test_hid_mode, g_iap2_hid_reset_first, g_iap2_hid_first);

    mfi_init();

    g_loop = g_main_loop_new(NULL, FALSE);
    g_unix_signal_add(SIGINT,  on_signal, NULL);
    g_unix_signal_add(SIGTERM, on_signal, NULL);

    /* Connect to system bus.
     * BlueZ tracks our profile by unique bus name (:1.xx), not well-known name,
     * so we don't need to own a well-known name (which would require a policy
     * file in /etc/dbus-1/system.d/ that we don't have on the device). */
    GError *conn_err = NULL;
    g_conn = g_bus_get_sync(G_BUS_TYPE_SYSTEM, NULL, &conn_err);
    if (!g_conn) {
        fprintf(stderr, "[iap2] Failed to connect to system bus: %s\n",
                conn_err->message);
        g_error_free(conn_err);
        return 1;
    }

    /* Register Profile1 D-Bus object once — it must stay registered for the
     * lifetime of the connection so BlueZ can call NewConnection on us. */
    if (register_dbus_object(g_conn) < 0) {
        g_object_unref(g_conn);
        return 1;
    }

    /* Watch org.bluez: on_bluez_appeared fires immediately if bluetoothd is
     * already running, OR later when it starts.  Also fires again after any
     * bluetoothd crash+restart, so SDP is always re-registered automatically.
     * This eliminates the startup race condition entirely. */
    g_bus_watch_name_on_connection(
        g_conn, "org.bluez",
        G_BUS_NAME_WATCHER_FLAGS_NONE,
        on_bluez_appeared,
        on_bluez_vanished,
        NULL, NULL);

    /* Start HID FIFO reader thread for button integration */
    pthread_t hid_thread;
    if (pthread_create(&hid_thread, NULL, thread_read_hid_fifo, NULL) == 0) {
        pthread_detach(hid_thread);
    }

    g_main_loop_run(g_loop);
    g_main_loop_unref(g_loop);

    g_object_unref(g_conn);
    if (mfi_fd >= 0) close(mfi_fd);
    fprintf(stderr, "[iap2] done\n");
    return 0;
}
