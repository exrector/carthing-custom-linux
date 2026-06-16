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
#include <sys/socket.h>
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
#define IAP2_CTL_DATA  0x00
#define IAP2_SID_CTL   0x00   /* control session */

/* Control session message IDs */
#define IAP2_MSG_AUTH_CERT_REQ      0x1D50
#define IAP2_MSG_AUTH_CERT_RESP     0x1D51
#define IAP2_MSG_AUTH_CHAL_REQ      0x1D52
#define IAP2_MSG_AUTH_CHAL_RESP     0x1D53
#define IAP2_MSG_AUTH_OK            0x1D54   /* AuthenticationSucceeded (device → acc) */
#define IAP2_MSG_AUTH_FAILED        0x1D55   /* AuthenticationFailed    (device → acc) */

/* ── Forward declarations ───────────────────────────────────────────────── */
typedef struct iap2_conn iap2_conn_t;
static int  iap2_write_pkt(int fd, uint8_t ctl, uint8_t sid, uint8_t seq,
                            uint8_t ack, const uint8_t *payload, int plen);
static int  iap2_send_msg(int fd, uint8_t seq, uint16_t msg_id,
                           const uint8_t *params, int plen);
static void iap2_handle_control(iap2_conn_t *c, const uint8_t *payload,
                                 int plen, uint8_t *seq);
#define IAP2_MSG_NOWPLAYING_UPDATE  0x4800
#define IAP2_MSG_HID_REPORT         0x6800

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
    /* 0x0009 BluetoothProfileDescriptorList */
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
 *   1. MFI_GET_VERSION  (len=1)   → init chip, returns version byte (0x07)
 *   2. MFI_GET_CERTLEN  (len=2)   → 2-byte big-endian PKCS#7 response size (608)
 *                                    also sets device_struct[160] used by GET_RESPONSE!
 *   3. MFI_GET_CERTCHUNK(len=64)  → 64-byte cert page (auto-increment); read in loop
 *   4. MFI_SET_CHALLENGE(len=32)  → send challenge EXACTLY 32 bytes (pad if needed)
 *   5. MFI_GET_RESPONSE (len≥608) → 608-byte PKCS#7 SignedData auth blob
 *
 * Size constraints from kernel disassembly:
 *   GET_VERSION: len ≥ 1  |  GET_CERTLEN: len ≥ 2  |  GET_CERTCHUNK: len ≥ 64
 *   SET_CHALLENGE: len == 32 EXACTLY (EINVAL otherwise)
 *   GET_RESPONSE: len ≥ device_struct[160] (set by GET_CERTLEN call)
 */
#include <sys/ioctl.h>

#define MFI_DEV  "/dev/apple_mfi"

struct mfi_buf { uint32_t len; uint32_t pad; uint64_t ptr; };

#define MFI_GET_VERSION   _IOR(0x77, 1, struct mfi_buf)  /* init + version byte    */
#define MFI_GET_CERTLEN   _IOR(0x77, 4, struct mfi_buf)  /* 2-byte BE blob size    */
#define MFI_GET_RESPONSE  _IOR(0x77, 5, struct mfi_buf)  /* PKCS#7 auth blob       */
#define MFI_SET_CHALLENGE _IOW(0x77, 6, struct mfi_buf)  /* 32-byte challenge      */
#define MFI_GET_CERTCHUNK _IOR(0x77, 7, struct mfi_buf)  /* 64-byte cert page      */

static int           mfi_fd        = -1;
static unsigned char mfi_cert[1024];
static int           mfi_cert_len  = 0;
static int           mfi_blob_size = 0;  /* PKCS#7 response size (from GET_CERTLEN) */

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
     * GET_CERTCHUNK (op=0x12) only returns data AFTER SET_CHALLENGE, and even
     * then it's not the raw cert.  The reliable path: sign a dummy zero-challenge,
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
            fprintf(stderr, "[mfi] cert extracted: %d bytes, starts %02x%02x%02x%02x\n",
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

    /* GET_RESPONSE: buf must be >= mfi_blob_size (driver copies exactly that many bytes) */
    int sz = (mfi_blob_size > 0) ? mfi_blob_size : 1024;
    if (mfi_ioctl(mfi_fd, MFI_GET_RESPONSE, resp, (uint32_t)sz) < 0) {
        fprintf(stderr, "[mfi] GET_RESPONSE failed: %s\n", strerror(errno));
        return -1;
    }
    *rlen = sz;
    fprintf(stderr, "[mfi] auth blob: %d bytes, starts %02x%02x%02x%02x\n",
            *rlen, resp[0], resp[1], resp[2], resp[3]);
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
    uint8_t hdr[8];
    int total = 8 + plen + (plen > 0 ? 1 : 0);  /* +1 payload cksum */
    hdr[0] = IAP2_SOF;
    hdr[1] = (total >> 8) & 0xFF;
    hdr[2] =  total       & 0xFF;
    hdr[3] = ctl;
    hdr[4] = seq;   /* iAP2 spec: byte4=SEQ, byte5=ACK, byte6=SID */
    hdr[5] = ack;
    hdr[6] = sid;
    hdr[7] = cksum(hdr, 7);

    uint8_t buf[4096];
    memcpy(buf, hdr, 8);
    if (plen > 0) {
        memcpy(buf + 8, payload, plen);
        buf[8 + plen] = cksum(payload, plen);
    }
    return (write(fd, buf, total) == total) ? 0 : -1;
}

/* Send a control-session message: MSG_LEN(2) MSG_ID(2) [params] */
static int iap2_send_msg(int fd, uint8_t seq,
                          uint16_t msg_id, const uint8_t *params, int plen)
{
    uint8_t buf[2048];
    int total = 4 + plen;
    buf[0] = (total >> 8) & 0xFF;
    buf[1] =  total       & 0xFF;
    buf[2] = (msg_id >> 8) & 0xFF;
    buf[3] =  msg_id       & 0xFF;
    if (plen > 0) memcpy(buf + 4, params, plen);
    return iap2_write_pkt(fd, IAP2_CTL_DATA, IAP2_SID_CTL,
                          seq, 0, buf, total);
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
    uint16_t total = 8 + (uint16_t)sizeof(params) + 1;
    fprintf(stderr, "[iap2] SYN pkt: ff %02x %02x  80 %02x 00 00 XX  payload(%d): "
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
    char   device[256];
} iap2_conn_t;

/* ── iAP2 identification ─────────────────────────────────────────────────── */
#define IAP2_MSG_ID_INFO            0x1D00  /* StartIdentification (acc → dev) */
#define IAP2_MSG_ID_ACCEPTED        0x1D01  /* IdentificationAccepted (dev → acc) */
#define IAP2_MSG_ID_REJECTED        0x1D02  /* IdentificationRejected (dev → acc) */
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
    const char *model = "Car Thing";
    const char *mfr   = "Spotify USA Inc.";
    char serial[64];
    read_file_str("/var/etc/serial_number", serial, sizeof(serial), "8555R08SQN19");

    off = iap2_param(buf, off, 0x0000, name,   strlen(name));
    off = iap2_param(buf, off, 0x0001, model,  strlen(model));
    off = iap2_param(buf, off, 0x0002, mfr,    strlen(mfr));
    off = iap2_param(buf, off, 0x0003, serial, strlen(serial));

    uint8_t fw[3] = {0, 48, 2}, hw[3] = {1, 0, 0};
    off = iap2_param(buf, off, 0x0004, fw, 3);
    off = iap2_param(buf, off, 0x0005, hw, 3);

    uint8_t sent[4] = {0x40, 0xC8, 0x68, 0x00};
    off = iap2_param(buf, off, 0x0006, sent, 4);
    uint8_t recv_ids[2] = {0x48, 0x00};
    off = iap2_param(buf, off, 0x0007, recv_ids, 2);

    uint8_t cur = 0;
    off = iap2_param(buf, off, 0x0009, &cur, 1);

    uint8_t btc[64]; int boff = 0;
    uint8_t tid = 0;
    boff = iap2_param(btc, boff, 0x0000, &tid, 1);
    boff = iap2_param(btc, boff, 0x0002, "BT RFCOMM", 9);
    char mac_str[20];
    read_file_str("/sys/class/bluetooth/hci0/address", mac_str, sizeof(mac_str),
                  "30:E3:D6:00:5F:A4");
    mac_str[strcspn(mac_str, "\r\n")] = '\0';
    uint8_t mac[6] = {0};
    sscanf(mac_str, "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
           &mac[0],&mac[1],&mac[2],&mac[3],&mac[4],&mac[5]);
    boff = iap2_param(btc, boff, 0x0003, mac, 6);
    off  = iap2_param(buf, off,  0x0012, btc, boff);

    off = iap2_param(buf, off, 0x0012, "en", 2);
    off = iap2_param(buf, off, 0x0013, "en", 2);
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
    fprintf(stderr, "[iap2] → StartIdentification (%d param bytes)\n", off);
    iap2_send_msg(c->fd, ++(*seq), IAP2_MSG_ID_INFO, buf, off);
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
    iap2_send_msg(c->fd, ++(*seq), IAP2_MSG_START_NOWPLAYING, buf, off);
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
        fprintf(stderr, "[iap2] raw ✓ Auth OK — sending raw StartIdentification\n");
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
    if (plen < 4) return;
    uint16_t msg_id = ((uint16_t)payload[2] << 8) | payload[3];
    const uint8_t *params = payload + 4;
    int           params_len = plen - 4;

    fprintf(stderr, "[iap2] ctrl msg 0x%04X (%d bytes params)\n",
            msg_id, params_len);

    uint8_t buf[1100];
    int off;

    switch (msg_id) {

    case IAP2_MSG_AUTH_CERT_REQ:
        fprintf(stderr, "[iap2] → AuthenticationCertificate\n");
        if (mfi_cert_len <= 0) {
            iap2_send_msg(c->fd, ++(*seq), IAP2_MSG_AUTH_FAILED, NULL, 0);
            break;
        }
        off = iap2_param(buf, 0, 0x0000, mfi_cert, mfi_cert_len);
        iap2_send_msg(c->fd, ++(*seq), IAP2_MSG_AUTH_CERT_RESP, buf, off);
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

            unsigned char resp[1024];
            int           rlen = 0;
            if (mfi_sign(challenge, clen, resp, &rlen) == 0 && rlen > 0) {
                off = iap2_param(buf, 0, 0x0000, resp, rlen);
                iap2_send_msg(c->fd, ++(*seq),
                              IAP2_MSG_AUTH_CHAL_RESP, buf, off);
            } else {
                iap2_send_msg(c->fd, ++(*seq),
                              IAP2_MSG_AUTH_FAILED, NULL, 0);
            }
        }
        break;

    case IAP2_MSG_AUTH_OK:
        fprintf(stderr, "[iap2] ✓ Authentication succeeded!\n");
        send_identification(c, seq);
        break;

    case IAP2_MSG_ID_INFO:
        /* iPhone sent StartIdentification — shouldn't happen (we send first),
         * but respond with accepted if it does */
        fprintf(stderr, "[iap2] ← StartIdentification from iPhone (unexpected)\n");
        send_identification(c, seq);
        break;

    case IAP2_MSG_ID_ACCEPTED:
        fprintf(stderr, "[iap2] ✓ Identification accepted!\n");
        send_start_nowplaying(c, seq);
        break;

    case IAP2_MSG_ID_REJECTED:
        fprintf(stderr, "[iap2] ✗ Identification REJECTED\n");
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
                if (total >= 3 && buf[0] == 0xFF) {
                    uint8_t ctl = (total >= 4) ? buf[3] : 0;
                    fprintf(stderr, "[iap2] CLIENT: iPhone replied ctl=0x%02x\n", ctl);
                    if (ctl & IAP2_CTL_SYN) {
                        uint8_t pkt_seq = (total >= 5) ? buf[4] : 0;
                        fprintf(stderr, "[iap2] CLIENT: ← SYN+ACK (seq=%d), sending ACK\n",
                                pkt_seq);
                        seq = 1;
                        iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, seq, pkt_seq + 1, NULL, 0);
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

    /* ── SERVER MODE (NewConnection): LISTEN PHASE (30s) ── */
    {
        struct timeval tv = { .tv_sec = 30, .tv_usec = 0 };
        setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
        fprintf(stderr, "[iap2] LISTEN phase: waiting 30s for iPhone to send anything...\n");
        for (;;) {
            int n = read(c->fd, buf + total, (int)sizeof(buf) - total);
            if (n <= 0) {
                if (errno == EINTR) continue;
                if (errno == EAGAIN || errno == EWOULDBLOCK) {
                    fprintf(stderr, "[iap2] LISTEN timeout (30s): iPhone sent %d bytes total\n", total);
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
    if (total >= 3 && buf[0] == 0xFF) {
        uint8_t ctl = (total >= 4) ? buf[3] : 0;
        fprintf(stderr, "[iap2] MODE: iPhone sent link-layer ctl=0x%02x\n", ctl);
        if (ctl & IAP2_CTL_SYN) {
            uint8_t pkt_seq = (total >= 5) ? buf[4] : 0;
            fprintf(stderr, "[iap2] ← iPhone SYN (seq=%d), sending SYN+ACK\n", pkt_seq);
            iap2_write_pkt(c->fd, IAP2_CTL_SYN | IAP2_CTL_ACK,
                           0, ++seq, pkt_seq + 1, NULL, 0);
            total = 0;
        }
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
            while (total >= 4) {
                if (buf[0] != IAP2_SOF) {
                    int skip = 1;
                    while (skip < total && buf[skip] != IAP2_SOF) skip++;
                    memmove(buf, buf + skip, total - skip); total -= skip;
                    continue;
                }
                if (total < 3) break;
                uint16_t pkt_len = ((uint16_t)buf[1] << 8) | buf[2];
                if (pkt_len < 9 || pkt_len > (int)sizeof(buf)) { total = 0; break; }
                if (total < pkt_len) break;
                uint8_t ctl = buf[3], pkt_seq = buf[4];
                fprintf(stderr, "[iap2] TRY-C pkt ctl=0x%02x seq=%d len=%d\n",
                        ctl, pkt_seq, pkt_len);
                if ((ctl & IAP2_CTL_SYN) && (ctl & IAP2_CTL_ACK)) {
                    fprintf(stderr, "[iap2] ← SYN+ACK from iPhone, sending ACK\n");
                    iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, ++seq, pkt_seq+1, NULL, 0);
                    struct timeval tv = { 0, 0 };
                    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
                    total = 0;
                    goto link_data_loop;
                } else if ((ctl & IAP2_CTL_SYN) && !(ctl & IAP2_CTL_ACK)) {
                    fprintf(stderr, "[iap2] ← SYN collision, sending SYN+ACK\n");
                    iap2_write_pkt(c->fd, IAP2_CTL_SYN | IAP2_CTL_ACK,
                                   0, ++seq, pkt_seq+1, NULL, 0);
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
    fprintf(stderr, "[iap2] ✓ link-layer iAP2 session active, sending StartIdentification\n");
    struct timeval tv = { 0, 0 };
    setsockopt(c->fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    send_identification(c, &seq);
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
        while (total >= 4) {
            if (buf[0] != IAP2_SOF) {
                int skip = 1;
                while (skip < total && buf[skip] != IAP2_SOF) skip++;
                memmove(buf, buf + skip, total - skip); total -= skip;
                continue;
            }
            if (total < 3) break;
            uint16_t pkt_len = ((uint16_t)buf[1] << 8) | buf[2];
            if (pkt_len < 9 || pkt_len > (int)sizeof(buf)) {
                fprintf(stderr, "[iap2] bad pkt_len=%d\n", pkt_len);
                total = 0; break;
            }
            if (total < pkt_len) break;
            uint8_t ctl     = buf[3];
            uint8_t pkt_seq = buf[4];
            uint8_t pkt_ack = buf[5];
            uint8_t sid     = buf[6];
            (void)pkt_ack;
            fprintf(stderr, "[iap2] pkt: ctl=0x%02x seq=%d ack=%d sid=%d len=%d\n",
                    ctl, pkt_seq, pkt_ack, sid, pkt_len);
            if (ctl == IAP2_CTL_DATA && sid == IAP2_SID_CTL) {
                iap2_write_pkt(c->fd, IAP2_CTL_ACK, 0, ++seq, pkt_seq+1, NULL, 0);
                iap2_handle_control(c, buf + 8, (int)pkt_len - 9, &seq);
            } else if (ctl & IAP2_CTL_ACK) {
                /* ACK-only, normal */
            } else {
                fprintf(stderr, "[iap2] unknown ctl=0x%02x sid=%d\n", ctl, sid);
            }
            memmove(buf, buf + pkt_len, total - pkt_len); total -= pkt_len;
        }
    }
}

done_conn:
    close(c->fd);
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
            c->server_mode = 0;  /* accessory always initiates SYN, even when iPhone called us */
            strncpy(c->device, device, sizeof(c->device) - 1);
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
    char mac[18];
    strncpy(mac, a->mac, sizeof(mac) - 1);
    free(a);

    sleep(2);   /* let ACL link + AVRCP fully settle before opening RFCOMM */

    int fd = rfcomm_client_connect(mac, 1);
    if (fd < 0) {
        g_iap2_active = 0;
        return NULL;
    }

    iap2_conn_t *c = calloc(1, sizeof(iap2_conn_t));
    c->fd = fd;
    c->server_mode = 0;  /* WE are the RFCOMM client → send SYN first, iPhone replies SYN+ACK */
    strncpy(c->device, mac, sizeof(c->device) - 1);
    iap2_conn_thread(c);    /* blocks until connection drops; frees c on exit */
    g_iap2_active = 0;
    return NULL;
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
    if (!cv) goto done;
    gboolean connected = g_variant_get_boolean(cv);
    g_variant_unref(cv);

    /* Extract MAC from D-Bus path: /org/bluez/hciX/dev_AA_BB_CC_DD_EE_FF */
    const gchar *dev_part = strstr(object_path, "/dev_");
    if (!dev_part) goto done;
    const char *u = dev_part + 5;
    char mac[18] = {0};
    for (int i = 0, j = 0; u[i] && j < 17; i++, j++)
        mac[j] = (u[i] == '_') ? ':' : u[i];

    fprintf(stderr, "[iap2] Device %s: %s\n", mac, connected ? "connected (ACL)" : "disconnected");

    /* v2.6: НЕ инициируем RFCOMM к iPhone.
     * iPhone's iapd сам подключится к нашему RFCOMM server (ch 1) и вызовет NewConnection.
     * Просто логируем ACL-событие и ждём. */
    if (connected) {
        fprintf(stderr, "[iap2] ACL up — waiting for iPhone iapd to call NewConnection\n");
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
                          g_variant_new_boolean(FALSE));
    g_variant_builder_add(&opts, "{sv}", "RequireAuthorization",
                          g_variant_new_boolean(FALSE));

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

    /* NOTE: cafe client profile (AutoConnect) intentionally NOT registered here.
     * On first connection iPhone's iapd initiates to our caff server.
     * cafe client is only needed for subsequent auto-reconnects (future feature). */
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

/* org.bluez appeared — bluetoothd just started or restarted */
static void on_bluez_appeared(GDBusConnection *conn,
                               const gchar     *name,
                               const gchar     *name_owner,
                               gpointer         user_data)
{
    (void)name; (void)name_owner; (void)user_data;
    fprintf(stderr, "[iap2] bluetoothd appeared, registering iAP2 profile...\n");
    do_register_profile(conn);

    /* Disconnect any already-connected devices so they reconnect fresh.
     * iPhone reconnects → iapd sees our new SDP → NewConnection fires. */
    force_bt_reconnect(conn);

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

/* ── main ───────────────────────────────────────────────────────────────── */

int main(int argc, char *argv[])
{
    (void)argc; (void)argv;

    fprintf(stderr, "[iap2] iAP2 Agent v2.4  (client mode + btmon diagnostic)\n");
    fprintf(stderr, "[iap2] UUID:    %s\n", IAP2_UUID);
    fprintf(stderr, "[iap2] Channel: %d\n", IAP2_RFCOMM_CHANNEL);

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

    g_main_loop_run(g_loop);
    g_main_loop_unref(g_loop);

    g_object_unref(g_conn);
    if (mfi_fd >= 0) close(mfi_fd);
    fprintf(stderr, "[iap2] done\n");
    return 0;
}
