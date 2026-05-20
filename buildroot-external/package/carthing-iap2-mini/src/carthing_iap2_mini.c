#include <errno.h>
#include <ctype.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <poll.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define IAP2_CSM_START          0x4040
#define IAP2_RAW_SOF            0xFF5A
#define IAP2_CTL_SYN            0x80
#define IAP2_CTL_ACK            0x40
#define IAP2_CTL_EAK            0x20
#define IAP2_CTL_DATA           0x00
#define IAP2_SID_CTL            0x00
#define IAP2_MSG_AUTH_CERT_REQ  0xAA00
#define IAP2_MSG_AUTH_CERT_RESP 0xAA01
#define IAP2_MSG_AUTH_CHAL_REQ  0xAA02
#define IAP2_MSG_AUTH_CHAL_RESP 0xAA03
#define IAP2_MSG_AUTH_FAILED    0xAA04
#define IAP2_MSG_AUTH_OK        0xAA05

#define IAP2_MSG_ID_START       0x1D00
#define IAP2_MSG_ID_INFO        0x1D01
#define IAP2_MSG_ID_ACCEPTED    0x1D02
#define IAP2_MSG_ID_REJECTED    0x1D03
#define IAP2_MSG_EA_START       0xEA00
#define IAP2_MSG_EA_STOP        0xEA01
#define IAP2_MSG_APP_LAUNCH     0xEA02
#define IAP2_MSG_EA_STATUS      0xEA03
#define IAP2_MSG_START_NOWPLAYING 0x40C8
#define IAP2_MSG_STOP_NOWPLAYING  0x40C9
#define IAP2_MSG_NOWPLAYING_UPDATE 0x4800
#define IAP2_MSG_START_HID        0x6800
#define IAP2_MSG_HID_REPORT       0x6801
#define IAP2_MSG_DEVICE_HID_REPORT 0x6802
#define IAP2_MSG_STOP_HID         0x6803
#define HID_COMPONENT_ID          0x0001

#define SDP_PDU_ERROR_RESPONSE              0x01
#define SDP_PDU_SERVICE_SEARCH_REQUEST      0x02
#define SDP_PDU_SERVICE_SEARCH_RESPONSE     0x03
#define SDP_PDU_SERVICE_ATTRIBUTE_REQUEST   0x04
#define SDP_PDU_SERVICE_ATTRIBUTE_RESPONSE  0x05
#define SDP_PDU_SERVICE_SEARCH_ATTR_REQUEST 0x06
#define SDP_PDU_SERVICE_SEARCH_ATTR_RESP    0x07

#define SDP_ERR_INVALID_HANDLE              0x0002
#define SDP_ERR_INVALID_SYNTAX              0x0003
#define SDP_ERR_INVALID_PDU_SIZE            0x0004
#define SDP_ERR_INVALID_CONT_STATE          0x0005

#define HELPER_PATH_DEFAULT "/usr/bin/carthing-mfi-probe"
#define RFCOMM_CHANNEL_DEFAULT 3
#define L2CAP_PSM_SDP 0x0001
#define SDP_RECORD_HANDLE 0x00010000U
#define HCI_DEV_DEFAULT 0
#define CLASS_OF_DEVICE_CAR_AUDIO 0x240420U

#ifndef BTPROTO_HCI
#define BTPROTO_HCI 1
#endif

#define HCI_CHANNEL_RAW 0
#define HCI_COMMAND_PKT 0x01
#define HCI_EVENT_PKT   0x04
#define BT_H4_EVT_PKT   0x04
#define EVT_CONN_COMPLETE 0x03
#define EVT_DISCONN_COMPLETE 0x05
#define EVT_AUTH_COMPLETE 0x06
#define EVT_REMOTE_NAME_REQ_COMPLETE 0x07
#define EVT_CMD_COMPLETE 0x0E
#define EVT_CMD_STATUS 0x0F
#define EVT_PIN_CODE_REQ 0x16
#define EVT_LINK_KEY_REQ 0x17
#define EVT_LINK_KEY_NOTIFY 0x18
#define EVT_INQUIRY_RESULT_WITH_RSSI 0x22
#define EVT_EXTENDED_INQUIRY_RESULT 0x2F
#define EVT_IO_CAPABILITY_REQUEST 0x31
#define EVT_IO_CAPABILITY_RESPONSE 0x32
#define EVT_USER_CONFIRMATION_REQUEST 0x33
#define EVT_USER_PASSKEY_REQUEST 0x34
#define EVT_SIMPLE_PAIRING_COMPLETE 0x36
#define OGF_LINK_CTL    0x01
#define OGF_HOST_CTL    0x03
#define OGF_INFO_PARAM  0x04
#define OCF_SET_EVENT_MASK 0x0001
#define OCF_INQUIRY 0x0001
#define OCF_CREATE_CONN 0x0005
#define OCF_LINK_KEY_REQUEST_REPLY 0x000B
#define OCF_LINK_KEY_REQUEST_NEGATIVE_REPLY 0x000C
#define OCF_PIN_CODE_REQUEST_NEGATIVE_REPLY 0x000E
#define OCF_REMOTE_NAME_REQUEST 0x0019
#define OCF_IO_CAPABILITY_REQUEST_REPLY 0x002B
#define OCF_USER_CONFIRMATION_REQUEST_REPLY 0x002C
#define OCF_USER_CONFIRMATION_REQUEST_NEGATIVE_REPLY 0x002D
#define OCF_USER_PASSKEY_REQUEST_NEGATIVE_REPLY 0x0033
#define OCF_WRITE_LOCAL_NAME  0x0013
#define OCF_READ_LOCAL_NAME   0x0014
#define OCF_READ_SCAN_ENABLE  0x0019
#define OCF_WRITE_SCAN_ENABLE 0x001A
#define OCF_READ_CLASS_OF_DEV  0x0023
#define OCF_WRITE_CLASS_OF_DEV 0x0024
#define OCF_WRITE_INQUIRY_MODE 0x0045
#define OCF_READ_BD_ADDR      0x0009
#define OCF_WRITE_EXTENDED_INQUIRY_RESPONSE 0x0052
#define OCF_WRITE_SIMPLE_PAIRING_MODE 0x0056
#define HCI_OPCODE(ogf, ocf) ((uint16_t)((ocf) | ((ogf) << 10)))
#define SOL_HCI 0
#define HCI_FILTER 2

#ifndef HCIDEVUP
#define HCIDEVUP _IOW('H', 201, int)
#endif

#define HCI_IO_CAPABILITY_DISPLAY_YESNO 0x01
#define HCI_OOB_DATA_NOT_PRESENT 0x00
#define HCI_AUTH_REQ_GENERAL_BONDING_MITM 0x05

#define LINK_KEY_PATH_DEFAULT "/run/carthing-state/carthing/iap2-link-keys.txt"
#define LINK_KEY_MAX_ENTRIES 16
#define IAP2_TEST_NAME_DEFAULT "CarThing iAP2"

#ifndef AF_BLUETOOTH
#define AF_BLUETOOTH 31
#endif

#ifndef BTPROTO_L2CAP
#define BTPROTO_L2CAP 0
#endif

#ifndef BTPROTO_RFCOMM
#define BTPROTO_RFCOMM 3
#endif

#ifndef SOL_BLUETOOTH
#define SOL_BLUETOOTH 274
#endif

#ifndef BT_SECURITY
#define BT_SECURITY 4
#endif

#define BT_SECURITY_HIGH 3

typedef struct {
    uint8_t b[6];
} bdaddr_t;

struct sockaddr_rc_local {
    sa_family_t rc_family;
    bdaddr_t rc_bdaddr;
    uint8_t rc_channel;
};

struct sockaddr_l2_local {
    sa_family_t l2_family;
    uint16_t l2_psm;
    bdaddr_t l2_bdaddr;
    uint16_t l2_cid;
    uint8_t l2_bdaddr_type;
};

struct sockaddr_hci_local {
    sa_family_t hci_family;
    uint16_t hci_dev;
    uint16_t hci_channel;
};

struct bt_security_local {
    uint8_t level;
    uint8_t key_size;
};

struct link_key_entry {
    bdaddr_t addr;
    uint8_t key[16];
    uint8_t type;
    int valid;
};

static struct link_key_entry g_link_keys[LINK_KEY_MAX_ENTRIES];
static int g_link_keys_loaded = 0;

struct hci_filter_local {
    uint32_t type_mask;
    uint32_t event_mask[2];
    uint16_t opcode;
};

struct input_event_local {
    long tv_sec;
    long tv_usec;
    uint16_t type;
    uint16_t code;
    int32_t value;
};

enum output_mode {
    OUTPUT_CONTROL = 0,
    OUTPUT_RAW = 1,
};

struct link_state {
    uint8_t tx_seq;
    uint8_t control_sid;
    uint8_t last_rx_ctrl_seq;
    uint16_t last_rx_ctrl_msg_id;
    int last_rx_ctrl_valid;
    uint8_t last_tx_seq;
    uint16_t last_tx_msg_id;
    size_t last_tx_payload_len;
    uint8_t last_tx_payload[2048];
    int last_tx_valid;
    int auth_ok;
    uint8_t ea_protocol_id[8];
    size_t ea_protocol_id_len;
    uint8_t ea_session_id[8];
    size_t ea_session_id_len;
    int ea_session_open;
};

static const uint8_t SDP_UUID_CAFF[16] = {
    0x00, 0x00, 0x00, 0x00, 0xde, 0xca, 0xfa, 0xde,
    0xde, 0xca, 0xde, 0xaf, 0xde, 0xca, 0xca, 0xff
};
static const uint8_t SDP_UUID_CAFE[16] = {
    0x00, 0x00, 0x00, 0x00, 0xde, 0xca, 0xfa, 0xde,
    0xde, 0xca, 0xde, 0xaf, 0xde, 0xca, 0xca, 0xfe
};
static const uint8_t EIR_UUID_CAFF_LE[16] = {
    0xff, 0xca, 0xca, 0xde, 0xaf, 0xde, 0xca, 0xde,
    0xde, 0xfa, 0xca, 0xde, 0x00, 0x00, 0x00, 0x00
};

static const uint8_t kHidConsumerDesc[] = {
    0x05, 0x0C,
    0x09, 0x01,
    0xA1, 0x01,
    0x15, 0x00,
    0x26, 0xFF, 0x03,
    0x19, 0x00,
    0x2A, 0xFF, 0x03,
    0x75, 0x10,
    0x95, 0x01,
    0x81, 0x00,
    0xC0
};

static const uint8_t SDP_ATTR_HANDLE[] = { 0x0A, 0x00, 0x01, 0x00, 0x00 };

static int env_u8(const char *name, int defv, int minv, int maxv);

static int open_input_event(const char *path) {
    if (!path || !*path) {
        errno = ENOENT;
        return -1;
    }
    return open(path, O_RDONLY | O_NONBLOCK);
}

static int wait_for_local_user_trigger(void) {
    const char *trigger = getenv("CARTHING_IAP2_APP_LAUNCH_TRIGGER");
    const char *trigger_file = getenv("CARTHING_IAP2_APP_LAUNCH_TRIGGER_FILE");
    const char *ev0_path;
    const char *ev1_path;
    struct pollfd pfds[2];
    int fds[2] = {-1, -1};
    int nfds = 0;
    int timeout_ms;
    int i;

    if (trigger && strcmp(trigger, "none") == 0) {
        return 1;
    }

    ev0_path = getenv("CARTHING_IAP2_TRIGGER_EVENT0");
    ev1_path = getenv("CARTHING_IAP2_TRIGGER_EVENT1");
    if (!ev0_path || !*ev0_path) {
        ev0_path = "/dev/input/event0";
    }
    if (!ev1_path || !*ev1_path) {
        ev1_path = "/dev/input/event1";
    }
    if (!trigger_file || !*trigger_file) {
        trigger_file = "/run/carthing-iap2-trigger-launch";
    }
    timeout_ms = env_u8("CARTHING_IAP2_APP_LAUNCH_TRIGGER_TIMEOUT", 20, 1, 120) * 1000;

    fds[nfds] = open_input_event(ev0_path);
    if (fds[nfds] >= 0) {
        pfds[nfds].fd = fds[nfds];
        pfds[nfds].events = POLLIN;
        nfds++;
    }
    fds[nfds] = open_input_event(ev1_path);
    if (fds[nfds] >= 0) {
        pfds[nfds].fd = fds[nfds];
        pfds[nfds].events = POLLIN;
        nfds++;
    }

    if (nfds == 0) {
        fprintf(stderr, "[iap2-mini] no local input trigger devices available, sending EA02 immediately\n");
        return 1;
    }

    fprintf(stderr, "[iap2-mini] waiting up to %d ms for local user trigger on %s / %s\n",
            timeout_ms, ev0_path, ev1_path);

    for (;;) {
        int poll_ms = timeout_ms > 1000 ? 1000 : timeout_ms;
        int rc;
        if (access(trigger_file, F_OK) == 0) {
            unlink(trigger_file);
            for (i = 0; i < nfds; i++) {
                if (pfds[i].fd >= 0) close(pfds[i].fd);
            }
            fprintf(stderr, "[iap2-mini] user trigger file hit: %s\n", trigger_file);
            return 1;
        }
        rc = poll(pfds, (nfds_t)nfds, poll_ms);
        if (timeout_ms > 1000) {
            timeout_ms -= 1000;
        } else {
            timeout_ms = 0;
        }
        if (rc <= 0) {
            if (timeout_ms > 0) {
                continue;
            }
            for (i = 0; i < nfds; i++) {
                if (pfds[i].fd >= 0) close(pfds[i].fd);
            }
            fprintf(stderr, "[iap2-mini] no local user trigger observed before timeout\n");
            errno = ETIMEDOUT;
            return 0;
        }
        for (i = 0; i < nfds; i++) {
            if (pfds[i].revents & POLLIN) {
                struct input_event_local ev;
                ssize_t n;
                for (;;) {
                    n = read(pfds[i].fd, &ev, sizeof(ev));
                    if (n == (ssize_t)sizeof(ev)) {
                        if (ev.type != 0) {
                            fprintf(stderr,
                                    "[iap2-mini] local user trigger type=0x%04x code=0x%04x value=%d fd=%d\n",
                                    ev.type, ev.code, ev.value, pfds[i].fd);
                            for (int j = 0; j < nfds; j++) {
                                if (pfds[j].fd >= 0) close(pfds[j].fd);
                            }
                            return 1;
                        }
                    } else {
                        break;
                    }
                }
            }
        }
        timeout_ms = 0;
    }
}
static const uint8_t SDP_ATTR_SERVICE_CLASS_ID_LIST[] = {
    0x35, 0x11, 0x1C,
    0x00, 0x00, 0x00, 0x00, 0xde, 0xca, 0xfa, 0xde,
    0xde, 0xca, 0xde, 0xaf, 0xde, 0xca, 0xca, 0xff
};
static const uint8_t SDP_ATTR_SERVICE_RECORD_STATE[] = { 0x0A, 0x00, 0x00, 0x00, 0x00 };
static const uint8_t SDP_ATTR_PROTOCOL_DESCRIPTOR_LIST[] = {
    0x35, 0x0C,
      0x35, 0x03, 0x19, 0x01, 0x00,
      0x35, 0x05, 0x19, 0x00, 0x03, 0x08, 0x03
};
static const uint8_t SDP_ATTR_BROWSE_GROUP_LIST[] = { 0x35, 0x03, 0x19, 0x10, 0x02 };
static const uint8_t SDP_ATTR_LANGUAGE_BASE[] = {
    0x35, 0x24,
      0x09, 0x65, 0x6E, 0x09, 0x00, 0x6A, 0x09, 0x01, 0x00,
      0x09, 0x66, 0x72, 0x09, 0x00, 0x6A, 0x09, 0x01, 0x10,
      0x09, 0x64, 0x65, 0x09, 0x00, 0x6A, 0x09, 0x01, 0x20,
      0x09, 0x6A, 0x61, 0x09, 0x00, 0x6A, 0x09, 0x01, 0x30
};
static const uint8_t SDP_ATTR_SERVICE_AVAILABILITY[] = { 0x08, 0xFF };
static const uint8_t SDP_ATTR_PROFILE_DESCRIPTOR_LIST[] = {
    0x35, 0x08,
      0x35, 0x06, 0x19, 0x11, 0x01, 0x09, 0x01, 0x00
};
static const uint8_t SDP_ATTR_SERVICE_NAME[] = {
    0x25, 0x0C, 'W', 'i', 'r', 'e', 'l', 'e', 's', 's', ' ', 'i', 'A', 'P'
};

static int capture_helper_aa03(const uint8_t challenge[32], size_t challenge_len,
                               uint8_t **out, size_t *out_len);

static int write_all_fd(int fd, const uint8_t *buf, size_t len) {
    size_t off = 0;
    while (off < len) {
        ssize_t n = write(fd, buf + off, len - off);
        if (n < 0) {
            return -1;
        }
        off += (size_t)n;
    }
    return 0;
}

static int append_buf(uint8_t *buf, size_t cap, size_t *off, const void *src, size_t len) {
    if (*off + len > cap) {
        errno = ENOSPC;
        return -1;
    }
    memcpy(buf + *off, src, len);
    *off += len;
    return 0;
}

static int append_u8(uint8_t *buf, size_t cap, size_t *off, uint8_t v) {
    return append_buf(buf, cap, off, &v, 1);
}

static int append_be16(uint8_t *buf, size_t cap, size_t *off, uint16_t v) {
    uint8_t tmp[2] = { (uint8_t)(v >> 8), (uint8_t)(v & 0xff) };
    return append_buf(buf, cap, off, tmp, sizeof(tmp));
}

static int append_be32(uint8_t *buf, size_t cap, size_t *off, uint32_t v) {
    uint8_t tmp[4] = {
        (uint8_t)(v >> 24), (uint8_t)((v >> 16) & 0xff),
        (uint8_t)((v >> 8) & 0xff), (uint8_t)(v & 0xff)
    };
    return append_buf(buf, cap, off, tmp, sizeof(tmp));
}

static void hex_preview_bytes(const uint8_t *buf, size_t len, char *out, size_t out_len) {
    size_t off = 0;
    size_t i;

    if (out_len == 0) {
        return;
    }
    out[0] = '\0';
    for (i = 0; i < len; ++i) {
        int n;
        if (off + 3 >= out_len) {
            break;
        }
        n = snprintf(out + off, out_len - off, "%02x", buf[i]);
        if (n < 0 || (size_t)n >= out_len - off) {
            break;
        }
        off += (size_t)n;
        if (i + 1 < len) {
            if (off + 2 >= out_len) {
                break;
            }
            out[off++] = ' ';
            out[off] = '\0';
        }
    }
    if (i < len && off + 4 < out_len) {
        snprintf(out + off, out_len - off, " ...");
    }
}

static int read_exact_fd(int fd, uint8_t *buf, size_t len) {
    size_t off = 0;
    while (off < len) {
        ssize_t n = read(fd, buf + off, len - off);
        if (n < 0) {
            return -1;
        }
        if (n == 0) {
            errno = 0;
            return 1;
        }
        off += (size_t)n;
    }
    return 0;
}

static int read_fd_all(int fd, uint8_t **buf_out, size_t *len_out) {
    size_t cap = 4096;
    size_t len = 0;
    uint8_t *buf = calloc(1, cap);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    for (;;) {
        ssize_t n;
        if (len == cap) {
            uint8_t *tmp;
            cap *= 2;
            tmp = realloc(buf, cap);
            if (!tmp) {
                free(buf);
                errno = ENOMEM;
                return -1;
            }
            buf = tmp;
        }
        n = read(fd, buf + len, cap - len);
        if (n < 0) {
            free(buf);
            return -1;
        }
        if (n == 0) {
            break;
        }
        len += (size_t)n;
    }
    *buf_out = buf;
    *len_out = len;
    return 0;
}

static int env_u8(const char *name, int defv, int minv, int maxv) {
    const char *v = getenv(name);
    char *end = NULL;
    long n;
    if (!v || !*v) {
        return defv;
    }
    n = strtol(v, &end, 0);
    if (!end || *end != '\0' || n < minv || n > maxv) {
        return defv;
    }
    return (int)n;
}

static void bdaddr_to_str(const bdaddr_t *addr, char out[18]) {
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             addr->b[5], addr->b[4], addr->b[3],
             addr->b[2], addr->b[1], addr->b[0]);
}

static int str_to_bdaddr_local(const char *str, bdaddr_t *addr) {
    unsigned int b0, b1, b2, b3, b4, b5;
    if (sscanf(str, "%02x:%02x:%02x:%02x:%02x:%02x",
               &b0, &b1, &b2, &b3, &b4, &b5) != 6) {
        errno = EINVAL;
        return -1;
    }
    addr->b[5] = (uint8_t)b0;
    addr->b[4] = (uint8_t)b1;
    addr->b[3] = (uint8_t)b2;
    addr->b[2] = (uint8_t)b3;
    addr->b[1] = (uint8_t)b4;
    addr->b[0] = (uint8_t)b5;
    return 0;
}

static int sdp_de_parse_header(const uint8_t *buf, size_t len,
                               uint8_t *type, size_t *hdr_len, size_t *val_len) {
    uint8_t desc;
    uint8_t sz_idx;
    if (len < 1) {
        return -1;
    }
    desc = buf[0];
    *type = (uint8_t)(desc >> 3);
    sz_idx = (uint8_t)(desc & 0x07);
    *hdr_len = 1;
    switch (sz_idx) {
        case 0: *val_len = 1; break;
        case 1: *val_len = 2; break;
        case 2: *val_len = 4; break;
        case 3: *val_len = 8; break;
        case 4: *val_len = 16; break;
        case 5:
            if (len < 2) return -1;
            *hdr_len = 2;
            *val_len = buf[1];
            break;
        case 6:
            if (len < 3) return -1;
            *hdr_len = 3;
            *val_len = (size_t)((buf[1] << 8) | buf[2]);
            break;
        case 7:
            if (len < 5) return -1;
            *hdr_len = 5;
            *val_len = ((size_t)buf[1] << 24) | ((size_t)buf[2] << 16) |
                       ((size_t)buf[3] << 8) | (size_t)buf[4];
            break;
        default:
            return -1;
    }
    if (*hdr_len + *val_len > len) {
        return -1;
    }
    return 0;
}

static int sdp_pattern_matches_service(const uint8_t *pattern, size_t pattern_len) {
    uint8_t type;
    size_t hdr_len;
    size_t val_len;
    size_t off;

    if (sdp_de_parse_header(pattern, pattern_len, &type, &hdr_len, &val_len) < 0 || type != 6) {
        return 0;
    }
    off = hdr_len;
    while (off < hdr_len + val_len) {
        const uint8_t *elem = pattern + off;
        size_t remain = hdr_len + val_len - off;
        size_t eh, ev;
        uint8_t et;
        if (sdp_de_parse_header(elem, remain, &et, &eh, &ev) < 0 || et != 3) {
            return 0;
        }
        if (ev == 2) {
            uint16_t u16 = (uint16_t)((elem[eh] << 8) | elem[eh + 1]);
            if (u16 == 0x1002) {
                return 1;
            }
        } else if (ev == 16 && memcmp(elem + eh, SDP_UUID_CAFF, 16) == 0) {
            return 1;
        }
        off += eh + ev;
    }
    return 0;
}

static int sdp_attr_requested(uint16_t attr_id, const uint8_t *list, size_t list_len) {
    uint8_t type;
    size_t hdr_len;
    size_t val_len;
    size_t off;

    if (sdp_de_parse_header(list, list_len, &type, &hdr_len, &val_len) < 0 || type != 6) {
        return 0;
    }
    off = hdr_len;
    while (off < hdr_len + val_len) {
        const uint8_t *elem = list + off;
        size_t remain = hdr_len + val_len - off;
        size_t eh, ev;
        uint8_t et;
        if (sdp_de_parse_header(elem, remain, &et, &eh, &ev) < 0 || et != 1) {
            return 0;
        }
        if (ev == 2) {
            uint16_t one = (uint16_t)((elem[eh] << 8) | elem[eh + 1]);
            if (one == attr_id) {
                return 1;
            }
        } else if (ev == 4) {
            uint16_t lo = (uint16_t)((elem[eh] << 8) | elem[eh + 1]);
            uint16_t hi = (uint16_t)((elem[eh + 2] << 8) | elem[eh + 3]);
            if (attr_id >= lo && attr_id <= hi) {
                return 1;
            }
        } else {
            return 0;
        }
        off += eh + ev;
    }
    return 0;
}

static int sdp_append_attr_pair(uint8_t *buf, size_t cap, size_t *off, uint16_t attr_id,
                                const uint8_t *value, size_t value_len) {
    if (append_u8(buf, cap, off, 0x09) < 0) return -1;
    if (append_be16(buf, cap, off, attr_id) < 0) return -1;
    return append_buf(buf, cap, off, value, value_len);
}

static int sdp_build_attr_list(uint8_t *buf, size_t cap, size_t *out_len,
                               const uint8_t *attr_req, size_t attr_req_len) {
    uint8_t inner[512];
    size_t inner_len = 0;

    if (sdp_attr_requested(0x0000, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0000,
                             SDP_ATTR_HANDLE, sizeof(SDP_ATTR_HANDLE)) < 0) return -1;
    if (sdp_attr_requested(0x0001, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0001,
                             SDP_ATTR_SERVICE_CLASS_ID_LIST,
                             sizeof(SDP_ATTR_SERVICE_CLASS_ID_LIST)) < 0) return -1;
    if (sdp_attr_requested(0x0002, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0002,
                             SDP_ATTR_SERVICE_RECORD_STATE,
                             sizeof(SDP_ATTR_SERVICE_RECORD_STATE)) < 0) return -1;
    if (sdp_attr_requested(0x0004, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0004,
                             SDP_ATTR_PROTOCOL_DESCRIPTOR_LIST,
                             sizeof(SDP_ATTR_PROTOCOL_DESCRIPTOR_LIST)) < 0) return -1;
    if (sdp_attr_requested(0x0005, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0005,
                             SDP_ATTR_BROWSE_GROUP_LIST,
                             sizeof(SDP_ATTR_BROWSE_GROUP_LIST)) < 0) return -1;
    if (sdp_attr_requested(0x0006, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0006,
                             SDP_ATTR_LANGUAGE_BASE,
                             sizeof(SDP_ATTR_LANGUAGE_BASE)) < 0) return -1;
    if (sdp_attr_requested(0x0008, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0008,
                             SDP_ATTR_SERVICE_AVAILABILITY,
                             sizeof(SDP_ATTR_SERVICE_AVAILABILITY)) < 0) return -1;
    if (sdp_attr_requested(0x0009, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0009,
                             SDP_ATTR_PROFILE_DESCRIPTOR_LIST,
                             sizeof(SDP_ATTR_PROFILE_DESCRIPTOR_LIST)) < 0) return -1;
    if (sdp_attr_requested(0x0100, attr_req, attr_req_len) &&
        sdp_append_attr_pair(inner, sizeof(inner), &inner_len, 0x0100,
                             SDP_ATTR_SERVICE_NAME,
                             sizeof(SDP_ATTR_SERVICE_NAME)) < 0) return -1;

    if (inner_len <= 0xFF) {
        size_t off = 0;
        if (append_u8(buf, cap, &off, 0x35) < 0) return -1;
        if (append_u8(buf, cap, &off, (uint8_t)inner_len) < 0) return -1;
        if (append_buf(buf, cap, &off, inner, inner_len) < 0) return -1;
        *out_len = off;
        return 0;
    }
    return -1;
}

static int sdp_write_response_fd(int out_fd, uint8_t pdu_id, uint16_t txn_id,
                                 const uint8_t *params, size_t params_len) {
    uint8_t packet[705];
    size_t off = 0;

    if (sizeof(packet) < 5 + params_len) {
        errno = EOVERFLOW;
        return -1;
    }
    packet[off++] = pdu_id;
    packet[off++] = (uint8_t)(txn_id >> 8);
    packet[off++] = (uint8_t)(txn_id & 0xff);
    packet[off++] = (uint8_t)((params_len >> 8) & 0xff);
    packet[off++] = (uint8_t)(params_len & 0xff);
    if (params_len > 0) {
        memcpy(packet + off, params, params_len);
        off += params_len;
    }
    if (write_all_fd(out_fd, packet, off) < 0) return -1;
    return 0;
}

static int sdp_write_error_fd(int out_fd, uint16_t txn_id, uint16_t err_code) {
    uint8_t params[2] = { (uint8_t)(err_code >> 8), (uint8_t)(err_code & 0xff) };
    return sdp_write_response_fd(out_fd, SDP_PDU_ERROR_RESPONSE, txn_id, params, sizeof(params));
}

static const char *iap2_local_name(void) {
    const char *name = getenv("CARTHING_IAP2_LOCAL_NAME");

    if (name && *name) {
        return name;
    }
    name = getenv("CARTHING_IAP2_EIR_NAME");
    if (name && *name) {
        return name;
    }
    return IAP2_TEST_NAME_DEFAULT;
}

static const char *sdp_pdu_name(uint8_t pdu_id) {
    switch (pdu_id) {
    case SDP_PDU_ERROR_RESPONSE:
        return "ERROR_RESPONSE";
    case SDP_PDU_SERVICE_SEARCH_REQUEST:
        return "SERVICE_SEARCH_REQUEST";
    case SDP_PDU_SERVICE_SEARCH_RESPONSE:
        return "SERVICE_SEARCH_RESPONSE";
    case SDP_PDU_SERVICE_ATTRIBUTE_REQUEST:
        return "SERVICE_ATTRIBUTE_REQUEST";
    case SDP_PDU_SERVICE_ATTRIBUTE_RESPONSE:
        return "SERVICE_ATTRIBUTE_RESPONSE";
    case SDP_PDU_SERVICE_SEARCH_ATTR_REQUEST:
        return "SERVICE_SEARCH_ATTR_REQUEST";
    case SDP_PDU_SERVICE_SEARCH_ATTR_RESP:
        return "SERVICE_SEARCH_ATTR_RESPONSE";
    default:
        return "UNKNOWN";
    }
}

static int sdp_handle_request_fd(int out_fd, uint8_t pdu_id,
                                 uint16_t txn_id, const uint8_t *params, size_t params_len) {
    if (pdu_id == SDP_PDU_SERVICE_SEARCH_REQUEST) {
        uint8_t resp[16];
        size_t off = 0;
        size_t pat_hdr, pat_len;
        uint8_t pat_type;
        uint16_t max_count;
        size_t pat_total;
        int match;

        if (sdp_de_parse_header(params, params_len, &pat_type, &pat_hdr, &pat_len) < 0 || pat_type != 6) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
        }
        pat_total = pat_hdr + pat_len;
        if (params_len < pat_total + 3) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        max_count = (uint16_t)((params[pat_total] << 8) | params[pat_total + 1]);
        if (params[pat_total + 2] != 0x00) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_CONT_STATE);
        }
        match = sdp_pattern_matches_service(params, pat_total);
        if (append_be16(resp, sizeof(resp), &off, (uint16_t)(match ? 1 : 0)) < 0) return -1;
        if (append_be16(resp, sizeof(resp), &off,
                        (uint16_t)((match && max_count > 0) ? 1 : 0)) < 0) return -1;
        if (match && max_count > 0 && append_be32(resp, sizeof(resp), &off, SDP_RECORD_HANDLE) < 0) return -1;
        if (append_u8(resp, sizeof(resp), &off, 0x00) < 0) return -1;
        return sdp_write_response_fd(out_fd, SDP_PDU_SERVICE_SEARCH_RESPONSE, txn_id, resp, off);
    }

    if (pdu_id == SDP_PDU_SERVICE_ATTRIBUTE_REQUEST) {
        uint8_t attr_list[512];
        uint8_t resp[640];
        size_t attr_len = 0;
        size_t off = 0;
        uint32_t handle;
        uint16_t max_bytes;
        const uint8_t *attr_req;
        size_t attr_req_len;

        if (params_len < 7) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        handle = ((uint32_t)params[0] << 24) | ((uint32_t)params[1] << 16) |
                 ((uint32_t)params[2] << 8) | (uint32_t)params[3];
        if (handle != SDP_RECORD_HANDLE) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_HANDLE);
        }
        max_bytes = (uint16_t)((params[4] << 8) | params[5]);
        attr_req = params + 6;
        attr_req_len = params_len - 6;
        {
            uint8_t t;
            size_t h, v;
            if (sdp_de_parse_header(attr_req, attr_req_len, &t, &h, &v) < 0 || t != 6) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
            }
            if (attr_req_len < h + v + 1) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
            }
            if (attr_req[h + v] != 0x00) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_CONT_STATE);
            }
            attr_req_len = h + v;
        }
        if (sdp_build_attr_list(attr_list, sizeof(attr_list), &attr_len, attr_req, attr_req_len) < 0) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
        }
        if (max_bytes > 0 && attr_len > max_bytes) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        if (append_be16(resp, sizeof(resp), &off, (uint16_t)attr_len) < 0) return -1;
        if (append_buf(resp, sizeof(resp), &off, attr_list, attr_len) < 0) return -1;
        if (append_u8(resp, sizeof(resp), &off, 0x00) < 0) return -1;
        return sdp_write_response_fd(out_fd, SDP_PDU_SERVICE_ATTRIBUTE_RESPONSE, txn_id, resp, off);
    }

    if (pdu_id == SDP_PDU_SERVICE_SEARCH_ATTR_REQUEST) {
        uint8_t service_attrs[512];
        uint8_t outer[640];
        uint8_t resp[700];
        size_t service_len = 0;
        size_t outer_len = 0;
        size_t off = 0;
        uint8_t type;
        size_t hdr_len, val_len, pat_total;
        uint16_t max_bytes;
        const uint8_t *attr_req;
        size_t attr_req_len;

        if (sdp_de_parse_header(params, params_len, &type, &hdr_len, &val_len) < 0 || type != 6) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
        }
        pat_total = hdr_len + val_len;
        if (params_len < pat_total + 3) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        if (!sdp_pattern_matches_service(params, pat_total)) {
            if (append_be16(resp, sizeof(resp), &off, 0x0000) < 0) return -1;
            if (append_u8(resp, sizeof(resp), &off, 0x00) < 0) return -1;
            return sdp_write_response_fd(out_fd, SDP_PDU_SERVICE_SEARCH_ATTR_RESP, txn_id, resp, off);
        }
        max_bytes = (uint16_t)((params[pat_total] << 8) | params[pat_total + 1]);
        attr_req = params + pat_total + 2;
        attr_req_len = params_len - pat_total - 2;
        {
            uint8_t t;
            size_t h, v;
            if (sdp_de_parse_header(attr_req, attr_req_len, &t, &h, &v) < 0 || t != 6) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
            }
            if (attr_req_len < h + v + 1) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
            }
            if (attr_req[h + v] != 0x00) {
                return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_CONT_STATE);
            }
            attr_req_len = h + v;
        }
        if (sdp_build_attr_list(service_attrs, sizeof(service_attrs), &service_len, attr_req, attr_req_len) < 0) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
        }
        if (service_len <= 0xFF) {
            if (append_u8(outer, sizeof(outer), &outer_len, 0x35) < 0) return -1;
            if (append_u8(outer, sizeof(outer), &outer_len, (uint8_t)service_len) < 0) return -1;
            if (append_buf(outer, sizeof(outer), &outer_len, service_attrs, service_len) < 0) return -1;
        } else {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        if (max_bytes > 0 && outer_len > max_bytes) {
            return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
        }
        if (append_be16(resp, sizeof(resp), &off, (uint16_t)outer_len) < 0) return -1;
        if (append_buf(resp, sizeof(resp), &off, outer, outer_len) < 0) return -1;
        if (append_u8(resp, sizeof(resp), &off, 0x00) < 0) return -1;
        return sdp_write_response_fd(out_fd, SDP_PDU_SERVICE_SEARCH_ATTR_RESP, txn_id, resp, off);
    }

    return sdp_write_error_fd(out_fd, txn_id, SDP_ERR_INVALID_SYNTAX);
}

static int hci_open_raw(int dev_id) {
    int fd;
    struct sockaddr_hci_local addr;
    struct hci_filter_local flt;

    fd = socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/HCI)");
        return -1;
    }
    memset(&addr, 0, sizeof(addr));
    addr.hci_family = AF_BLUETOOTH;
    addr.hci_dev = (uint16_t)dev_id;
    addr.hci_channel = HCI_CHANNEL_RAW;
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind(HCI)");
        close(fd);
        return -1;
    }
    memset(&flt, 0, sizeof(flt));
    flt.type_mask = (uint32_t)(1u << BT_H4_EVT_PKT);
    flt.event_mask[0] = 0xffffffffu;
    flt.event_mask[1] = 0xffffffffu;
    if (setsockopt(fd, SOL_HCI, HCI_FILTER, &flt, sizeof(flt)) < 0) {
        perror("setsockopt(HCI_FILTER)");
        close(fd);
        return -1;
    }
    return fd;
}

static int hci_dev_up(int dev_id) {
    int fd;

    fd = socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/HCI devup)");
        return 1;
    }
    if (ioctl(fd, HCIDEVUP, dev_id) < 0) {
        if (errno != EALREADY) {
            perror("ioctl(HCIDEVUP)");
            close(fd);
            return 1;
        }
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI dev hci%d up\n", dev_id);
    return 0;
}

static int hci_open_event_raw(int dev_id) {
    int fd;
    struct sockaddr_hci_local addr;
    struct hci_filter_local flt;

    fd = socket(AF_BLUETOOTH, SOCK_RAW, BTPROTO_HCI);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/HCI events)");
        return -1;
    }
    memset(&addr, 0, sizeof(addr));
    addr.hci_family = AF_BLUETOOTH;
    addr.hci_dev = (uint16_t)dev_id;
    addr.hci_channel = HCI_CHANNEL_RAW;
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind(HCI events)");
        close(fd);
        return -1;
    }
    memset(&flt, 0, sizeof(flt));
    flt.type_mask = (uint32_t)(1u << BT_H4_EVT_PKT);
    flt.event_mask[0] = 0xffffffffu;
    flt.event_mask[1] = 0xffffffffu;
    if (setsockopt(fd, SOL_HCI, HCI_FILTER, &flt, sizeof(flt)) < 0) {
        perror("setsockopt(HCI_FILTER events)");
        close(fd);
        return -1;
    }
    return fd;
}

static int hci_write_cmd_fd(int fd, uint16_t opcode, const uint8_t *payload, size_t payload_len) {
    uint8_t cmd[260];

    if (payload_len > 255 || 4 + payload_len > sizeof(cmd)) {
        errno = EINVAL;
        return -1;
    }
    cmd[0] = HCI_COMMAND_PKT;
    cmd[1] = (uint8_t)(opcode & 0xff);
    cmd[2] = (uint8_t)(opcode >> 8);
    cmd[3] = (uint8_t)payload_len;
    if (payload_len > 0) {
        memcpy(cmd + 4, payload, payload_len);
    }
    return write_all_fd(fd, cmd, 4 + payload_len);
}

static int hci_wait_cmd_status_ex(int fd, uint16_t opcode, uint8_t *status_out) {
    for (;;) {
        uint8_t buf[260];
        ssize_t n;
        struct pollfd pfd;

        pfd.fd = fd;
        pfd.events = POLLIN;
        pfd.revents = 0;
        if (poll(&pfd, 1, 5000) <= 0) {
            errno = ETIMEDOUT;
            return -1;
        }
        n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            return -1;
        }
        if (n < 3 || buf[0] != HCI_EVENT_PKT) {
            continue;
        }
        if (buf[1] == EVT_CMD_STATUS) {
            uint16_t evt_opcode;
            uint8_t status;
            if (n < 7) {
                continue;
            }
            evt_opcode = (uint16_t)(buf[5] | (buf[6] << 8));
            if (evt_opcode != opcode) {
                continue;
            }
            status = buf[3];
            if (status_out) {
                *status_out = status;
            }
            if (status != 0x00) {
                errno = EIO;
                return -1;
            }
            return 0;
        }
        if (buf[1] == EVT_CMD_COMPLETE) {
            uint16_t evt_opcode;
            uint8_t status;
            if (n < 7) {
                continue;
            }
            evt_opcode = (uint16_t)(buf[4] | (buf[5] << 8));
            if (evt_opcode != opcode) {
                continue;
            }
            status = buf[6];
            if (status_out) {
                *status_out = status;
            }
            if (status != 0x00) {
                errno = EIO;
                return -1;
            }
            return 0;
        }
    }
}

static int hci_wait_cmd_status(int fd, uint16_t opcode) {
    return hci_wait_cmd_status_ex(fd, opcode, NULL);
}

static size_t eir_extract_name(const uint8_t *eir, size_t eir_len, char *out, size_t out_cap) {
    size_t off = 0;
    if (out_cap == 0) {
        return 0;
    }
    out[0] = '\0';
    while (off < eir_len) {
        uint8_t field_len = eir[off];
        uint8_t field_type;
        size_t copy_len;
        if (field_len == 0) {
            break;
        }
        if (off + 1 + field_len > eir_len || field_len < 1) {
            break;
        }
        field_type = eir[off + 1];
        if (field_type == 0x08 || field_type == 0x09) {
            copy_len = field_len - 1;
            if (copy_len >= out_cap) {
                copy_len = out_cap - 1;
            }
            memcpy(out, eir + off + 2, copy_len);
            out[copy_len] = '\0';
            return copy_len;
        }
        off += 1 + field_len;
    }
    return 0;
}

static int hci_cmd_complete(int fd, uint16_t opcode, const uint8_t *payload, size_t payload_len,
                            uint8_t *resp, size_t resp_cap, size_t *resp_len) {
    uint8_t cmd[260];
    struct pollfd pfd;
    int rc;

    if (payload_len > 255 || 4 + payload_len > sizeof(cmd)) {
        errno = EINVAL;
        return -1;
    }
    cmd[0] = HCI_COMMAND_PKT;
    cmd[1] = (uint8_t)(opcode & 0xff);
    cmd[2] = (uint8_t)(opcode >> 8);
    cmd[3] = (uint8_t)payload_len;
    if (payload_len > 0) {
        memcpy(cmd + 4, payload, payload_len);
    }
    if (write_all_fd(fd, cmd, 4 + payload_len) < 0) {
        perror("write(HCI cmd)");
        return -1;
    }

    for (;;) {
        uint8_t buf[260];
        ssize_t n;
        uint16_t evt_opcode;
        size_t out_len;

        pfd.fd = fd;
        pfd.events = POLLIN;
        pfd.revents = 0;
        rc = poll(&pfd, 1, 2000);
        if (rc <= 0) {
            errno = ETIMEDOUT;
            return -1;
        }
        n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            return -1;
        }
        if (n < 7 || buf[0] != HCI_EVENT_PKT || buf[1] != EVT_CMD_COMPLETE) {
            continue;
        }
        evt_opcode = (uint16_t)(buf[4] | (buf[5] << 8));
        if (evt_opcode != opcode) {
            continue;
        }
        if (buf[6] != 0x00) {
            errno = EIO;
            return -1;
        }
        out_len = (size_t)n - 7;
        if (out_len > resp_cap) {
            errno = ENOSPC;
            return -1;
        }
        memcpy(resp, buf + 7, out_len);
        *resp_len = out_len;
        return 0;
    }
}

static int hci_read_scan_enable_value(int dev_id, uint8_t *scan_enable_out) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_READ_SCAN_ENABLE),
                         NULL, 0, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Read Scan Enable");
        close(fd);
        return 1;
    }
    close(fd);
    if (resp_len < 1) {
        errno = EPROTO;
        perror("HCI Read Scan Enable short reply");
        return 1;
    }
    *scan_enable_out = resp[0];
    return 0;
}

static int hci_read_scan_enable(int dev_id) {
    uint8_t scan_enable;

    if (hci_read_scan_enable_value(dev_id, &scan_enable) != 0) {
        return 1;
    }
    fprintf(stderr, "[iap2-mini] HCI scan enable=0x%02x\n", scan_enable);
    printf("0x%02x\n", scan_enable);
    return 0;
}

static int hci_write_scan_enable(int dev_id, uint8_t scan_enable) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_SCAN_ENABLE),
                         &scan_enable, 1, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Scan Enable");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote scan enable=0x%02x\n", scan_enable);
    return 0;
}

static int hci_scan_watchdog_loop(int dev_id, uint8_t expected_scan_enable) {
    for (;;) {
        uint8_t current = 0;

        sleep(1);
        if (hci_read_scan_enable_value(dev_id, &current) != 0) {
            continue;
        }
        if (current != expected_scan_enable) {
            fprintf(stderr,
                    "[iap2-mini] scan watchdog: current=0x%02x expected=0x%02x -> restore\n",
                    current, expected_scan_enable);
            hci_write_scan_enable(dev_id, expected_scan_enable);
        }
    }

    return 0;
}

static int hci_write_simple_pairing_mode(int dev_id, uint8_t enabled) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_SIMPLE_PAIRING_MODE),
                         &enabled, 1, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Simple Pairing Mode");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote simple pairing mode=%u\n", enabled);
    return 0;
}

static int hci_write_event_mask(int dev_id, const uint8_t mask[8]) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_SET_EVENT_MASK),
                         mask, 8, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Set Event Mask");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote event mask=%02x%02x%02x%02x%02x%02x%02x%02x\n",
            mask[7], mask[6], mask[5], mask[4], mask[3], mask[2], mask[1], mask[0]);
    return 0;
}

static int hci_write_inquiry_mode(int dev_id, uint8_t mode) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_INQUIRY_MODE),
                         &mode, 1, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Inquiry Mode");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote inquiry mode=0x%02x\n", mode);
    return 0;
}

static int hci_write_eir_iap2(int dev_id, const char *name) {
    int fd;
    uint8_t payload[241];
    uint8_t resp[8];
    size_t resp_len = 0;
    size_t name_len = strlen(name);
    size_t off = 0;

    if (name_len > 32) {
        name_len = 32;
    }
    memset(payload, 0, sizeof(payload));
    payload[0] = 0x00;
    off = 1;

    if (name_len > 0) {
        payload[off++] = (uint8_t)(name_len + 1);
        payload[off++] = 0x09;
        memcpy(payload + off, name, name_len);
        off += name_len;
    }

    payload[off++] = 17;
    payload[off++] = 0x07;
    memcpy(payload + off, EIR_UUID_CAFF_LE, sizeof(EIR_UUID_CAFF_LE));
    off += sizeof(EIR_UUID_CAFF_LE);

    fd = hci_open_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_EXTENDED_INQUIRY_RESPONSE),
                         payload, sizeof(payload), resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Extended Inquiry Response");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote EIR name=%s uuid=caff\n", name);
    return 0;
}

static void bt_require_high_security(int fd, const char *what) {
    struct bt_security_local sec;

    memset(&sec, 0, sizeof(sec));
    sec.level = BT_SECURITY_HIGH;
    sec.key_size = 0;
    if (setsockopt(fd, SOL_BLUETOOTH, BT_SECURITY, &sec, sizeof(sec)) < 0) {
        fprintf(stderr, "[iap2-mini] %s BT_SECURITY_HIGH failed: %s\n", what, strerror(errno));
    } else {
        fprintf(stderr, "[iap2-mini] %s BT_SECURITY_HIGH set\n", what);
    }
}

static int hci_read_local_name(int dev_id) {
    int fd;
    uint8_t resp[256];
    size_t resp_len = 0;
    size_t nlen;

    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_READ_LOCAL_NAME),
                         NULL, 0, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Read Local Name");
        close(fd);
        return 1;
    }
    close(fd);
    nlen = resp_len;
    while (nlen > 0 && resp[nlen - 1] == '\0') nlen--;
    fprintf(stderr, "[iap2-mini] HCI local name len=%zu\n", nlen);
    fwrite(resp, 1, nlen, stdout);
    fputc('\n', stdout);
    return 0;
}

static int hci_write_local_name(int dev_id, const char *name) {
    int fd;
    uint8_t payload[248];
    uint8_t resp[8];
    size_t resp_len = 0;
    size_t len = strlen(name);

    if (len >= sizeof(payload)) {
        errno = EINVAL;
        perror("HCI Write Local Name");
        return 1;
    }
    memset(payload, 0, sizeof(payload));
    memcpy(payload, name, len);
    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_LOCAL_NAME),
                         payload, sizeof(payload), resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Local Name");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote local name=%s\n", name);
    return 0;
}

static int hci_read_class_of_dev(int dev_id) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_READ_CLASS_OF_DEV),
                         NULL, 0, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Read Class Of Device");
        close(fd);
        return 1;
    }
    close(fd);
    if (resp_len < 3) {
        errno = EPROTO;
        perror("HCI Read Class Of Device short reply");
        return 1;
    }
    fprintf(stderr, "[iap2-mini] HCI class of device=0x%02x%02x%02x\n",
            resp[2], resp[1], resp[0]);
    printf("0x%02x%02x%02x\n", resp[2], resp[1], resp[0]);
    return 0;
}

static int hci_write_class_of_dev(int dev_id, uint32_t cod) {
    int fd;
    uint8_t payload[3];
    uint8_t resp[8];
    size_t resp_len = 0;

    payload[0] = (uint8_t)(cod & 0xff);
    payload[1] = (uint8_t)((cod >> 8) & 0xff);
    payload[2] = (uint8_t)((cod >> 16) & 0xff);
    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_HOST_CTL, OCF_WRITE_CLASS_OF_DEV),
                         payload, sizeof(payload), resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Write Class Of Device");
        close(fd);
        return 1;
    }
    close(fd);
    fprintf(stderr, "[iap2-mini] HCI wrote class of device=0x%06x\n", cod & 0xffffffu);
    return 0;
}

static int hci_read_bd_addr(int dev_id) {
    int fd;
    uint8_t resp[8];
    size_t resp_len = 0;
    char out[18];
    bdaddr_t addr;

    fd = hci_open_raw(dev_id);
    if (fd < 0) return 1;
    if (hci_cmd_complete(fd, HCI_OPCODE(OGF_INFO_PARAM, OCF_READ_BD_ADDR),
                         NULL, 0, resp, sizeof(resp), &resp_len) < 0) {
        perror("HCI Read BD_ADDR");
        close(fd);
        return 1;
    }
    close(fd);
    if (resp_len < 6) {
        errno = EPROTO;
        perror("HCI Read BD_ADDR short reply");
        return 1;
    }
    memcpy(addr.b, resp, 6);
    bdaddr_to_str(&addr, out);
    fprintf(stderr, "[iap2-mini] HCI bdaddr=%s\n", out);
    printf("%s\n", out);
    return 0;
}

static int hci_inquiry_scan(int dev_id, uint8_t inquiry_len) {
    static const uint8_t giac[3] = { 0x33, 0x8b, 0x9e };
    uint8_t payload[5];
    int fd;
    int seen = 0;

    payload[0] = giac[0];
    payload[1] = giac[1];
    payload[2] = giac[2];
    payload[3] = inquiry_len;
    payload[4] = 0x00;

    fd = hci_open_event_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_write_cmd_fd(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_INQUIRY), payload, sizeof(payload)) < 0) {
        perror("write(HCI Inquiry)");
        close(fd);
        return 1;
    }
    if (hci_wait_cmd_status(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_INQUIRY)) < 0) {
        perror("HCI Inquiry status");
        close(fd);
        return 1;
    }
    fprintf(stderr, "[iap2-mini] HCI inquiry started len=0x%02x\n", inquiry_len);

    for (;;) {
        uint8_t buf[260];
        ssize_t n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            perror("read(HCI inquiry)");
            close(fd);
            return 1;
        }
        if (n < 3 || buf[0] != HCI_EVENT_PKT) {
            continue;
        }
        if (buf[1] == 0x01) {
            uint8_t status = (n >= 4) ? buf[3] : 0xff;
            fprintf(stderr, "[iap2-mini] HCI inquiry complete status=0x%02x seen=%d\n", status, seen);
            close(fd);
            return status == 0x00 ? 0 : 1;
        }
        if (buf[1] == EVT_INQUIRY_RESULT_WITH_RSSI) {
            uint8_t count;
            int i;
            if (n < 4) {
                continue;
            }
            count = buf[3];
            for (i = 0; i < count; i++) {
                size_t base = 4 + (size_t)i * 14;
                bdaddr_t addr;
                char addr_str[18];
                uint32_t cod;
                int8_t rssi;
                if ((size_t)n < base + 14) {
                    break;
                }
                memcpy(addr.b, buf + base, 6);
                bdaddr_to_str(&addr, addr_str);
                cod = (uint32_t)buf[base + 8] | ((uint32_t)buf[base + 9] << 8) | ((uint32_t)buf[base + 10] << 16);
                rssi = (int8_t)buf[base + 13];
                printf("%s\tcod=0x%06x\trssi=%d\n", addr_str, cod & 0xffffffu, (int)rssi);
                seen++;
            }
            continue;
        }
        if (buf[1] == EVT_EXTENDED_INQUIRY_RESULT) {
            bdaddr_t addr;
            char addr_str[18];
            char name[249];
            uint32_t cod;
            int8_t rssi;
            if (n < 3 + 255) {
                continue;
            }
            memcpy(addr.b, buf + 4, 6);
            bdaddr_to_str(&addr, addr_str);
            cod = (uint32_t)buf[12] | ((uint32_t)buf[13] << 8) | ((uint32_t)buf[14] << 16);
            rssi = (int8_t)buf[17];
            eir_extract_name(buf + 18, (size_t)n - 18, name, sizeof(name));
            printf("%s\tcod=0x%06x\trssi=%d\tname=%s\n", addr_str, cod & 0xffffffu, (int)rssi, name[0] ? name : "-");
            seen++;
            continue;
        }
    }
}

static int hci_remote_name_request(int dev_id, const char *addr_str) {
    uint8_t payload[10];
    int fd;
    bdaddr_t addr;

    if (str_to_bdaddr_local(addr_str, &addr) < 0) {
        perror("str_to_bdaddr_local");
        return 1;
    }
    memcpy(payload, addr.b, 6);
    payload[6] = 0x01;
    payload[7] = 0x00;
    payload[8] = 0x00;
    payload[9] = 0x00;

    fd = hci_open_event_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_write_cmd_fd(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_REMOTE_NAME_REQUEST), payload, sizeof(payload)) < 0) {
        perror("write(HCI Remote Name Request)");
        close(fd);
        return 1;
    }
    if (hci_wait_cmd_status(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_REMOTE_NAME_REQUEST)) < 0) {
        perror("HCI Remote Name Request status");
        close(fd);
        return 1;
    }
    fprintf(stderr, "[iap2-mini] HCI remote name request peer=%s\n", addr_str);

    for (;;) {
        uint8_t buf[260];
        ssize_t n = read(fd, buf, sizeof(buf));
        char name[249];
        if (n < 0) {
            perror("read(HCI remote name)");
            close(fd);
            return 1;
        }
        if (n < 3 || buf[0] != HCI_EVENT_PKT || buf[1] != EVT_REMOTE_NAME_REQ_COMPLETE) {
            continue;
        }
        if (n < 10) {
            errno = EPROTO;
            perror("HCI Remote Name Request short reply");
            close(fd);
            return 1;
        }
        if (buf[3] != 0x00) {
            fprintf(stderr, "[iap2-mini] HCI remote name status=0x%02x\n", buf[3]);
            close(fd);
            return 1;
        }
        memset(name, 0, sizeof(name));
        if (n > 10) {
            size_t copy_len = (size_t)n - 10;
            if (copy_len >= sizeof(name)) {
                copy_len = sizeof(name) - 1;
            }
            memcpy(name, buf + 10, copy_len);
            name[copy_len] = '\0';
        }
        printf("%s\n", name);
        close(fd);
        return 0;
    }
}

static int hci_create_acl_link(int dev_id, const char *addr_str, uint16_t *handle_out) {
    uint8_t payload[13];
    int fd;
    bdaddr_t addr;
    uint8_t status = 0;
    struct pollfd pfd;

    if (handle_out) {
        *handle_out = 0;
    }
    if (str_to_bdaddr_local(addr_str, &addr) < 0) {
        perror("str_to_bdaddr_local");
        return 1;
    }

    memcpy(payload, addr.b, 6);
    payload[6] = 0x18;
    payload[7] = 0xcc;
    payload[8] = 0x01;
    payload[9] = 0x00;
    payload[10] = 0x00;
    payload[11] = 0x00;
    payload[12] = 0x01;

    fd = hci_open_event_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    if (hci_write_cmd_fd(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_CREATE_CONN), payload, sizeof(payload)) < 0) {
        perror("write(HCI Create Connection)");
        close(fd);
        return 1;
    }
    if (hci_wait_cmd_status_ex(fd, HCI_OPCODE(OGF_LINK_CTL, OCF_CREATE_CONN), &status) < 0) {
        if (status == 0x0b || status == 0x0c) {
            fprintf(stderr,
                    "[iap2-mini] HCI create ACL status=0x%02x for %s, assuming link already exists or controller refuses duplicate create\n",
                    status, addr_str);
            close(fd);
            return 0;
        }
        perror("HCI Create Connection status");
        fprintf(stderr, "[iap2-mini] HCI create ACL failed status=0x%02x peer=%s\n", status, addr_str);
        close(fd);
        return 1;
    }
    fprintf(stderr, "[iap2-mini] HCI create ACL started peer=%s\n", addr_str);

    for (;;) {
        uint8_t buf[260];
        ssize_t n;

        pfd.fd = fd;
        pfd.events = POLLIN;
        pfd.revents = 0;
        if (poll(&pfd, 1, 8000) <= 0) {
            errno = ETIMEDOUT;
            perror("HCI Create Connection complete");
            close(fd);
            return 1;
        }
        n = read(fd, buf, sizeof(buf));
        if (n < 0) {
            perror("read(HCI create connection)");
            close(fd);
            return 1;
        }
        if (n < 3 || buf[0] != HCI_EVENT_PKT || buf[1] != EVT_CONN_COMPLETE) {
            continue;
        }
        if (n < 14) {
            errno = EPROTO;
            perror("HCI Connection Complete short reply");
            close(fd);
            return 1;
        }
        if (memcmp(buf + 6, addr.b, 6) != 0) {
            continue;
        }
        status = buf[3];
        if (status != 0x00) {
            fprintf(stderr, "[iap2-mini] HCI ACL connect complete status=0x%02x peer=%s\n", status, addr_str);
            close(fd);
            return 1;
        }
        if (handle_out) {
            *handle_out = (uint16_t)(buf[4] | ((buf[5] & 0x0f) << 8));
        }
        fprintf(stderr, "[iap2-mini] HCI ACL up peer=%s handle=0x%04x link_type=0x%02x\n",
                addr_str, handle_out ? *handle_out : 0, buf[12]);
        close(fd);
        return 0;
    }
}

static int hci_cmd_status_only(int dev_id, uint16_t opcode, const uint8_t *payload, size_t payload_len) {
    int fd;
    uint8_t resp[32];
    size_t resp_len = 0;

    fd = hci_open_raw(dev_id);
    if (fd < 0) return -1;
    if (hci_cmd_complete(fd, opcode, payload, payload_len, resp, sizeof(resp), &resp_len) < 0) {
        close(fd);
        return -1;
    }
    close(fd);
    return 0;
}

static void bdaddr_event_to_str(const uint8_t *addr_le, char out[18]) {
    snprintf(out, 18, "%02X:%02X:%02X:%02X:%02X:%02X",
             addr_le[5], addr_le[4], addr_le[3], addr_le[2], addr_le[1], addr_le[0]);
}

static const char *link_key_store_path(void) {
    const char *path = getenv("CARTHING_IAP2_LINK_KEYS");
    if (!path || !*path) {
        path = LINK_KEY_PATH_DEFAULT;
    }
    return path;
}

static void link_key_to_hex(const uint8_t key[16], char out[33]) {
    static const char hex[] = "0123456789abcdef";
    int i;
    for (i = 0; i < 16; i++) {
        out[i * 2] = hex[(key[i] >> 4) & 0x0f];
        out[i * 2 + 1] = hex[key[i] & 0x0f];
    }
    out[32] = '\0';
}

static int hex_to_nybble(int c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

static int hex_to_link_key(const char *hex, uint8_t key[16]) {
    int i;
    for (i = 0; i < 16; i++) {
        int hi = hex_to_nybble((unsigned char)hex[i * 2]);
        int lo = hex_to_nybble((unsigned char)hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return -1;
        }
        key[i] = (uint8_t)((hi << 4) | lo);
    }
    return 0;
}

static void load_link_keys(void) {
    const char *path = link_key_store_path();
    FILE *fp;
    char line[128];

    if (g_link_keys_loaded) {
        return;
    }
    g_link_keys_loaded = 1;
    memset(g_link_keys, 0, sizeof(g_link_keys));

    fp = fopen(path, "r");
    if (!fp) {
        return;
    }
    while (fgets(line, sizeof(line), fp)) {
        char addr_str[32];
        char key_hex[64];
        unsigned type = 0;
        bdaddr_t addr;
        uint8_t key[16];
        int slot;

        if (sscanf(line, "%31s %63s %x", addr_str, key_hex, &type) != 3) {
            continue;
        }
        if (strlen(key_hex) != 32) {
            continue;
        }
        if (str_to_bdaddr_local(addr_str, &addr) < 0) {
            continue;
        }
        if (hex_to_link_key(key_hex, key) < 0) {
            continue;
        }
        for (slot = 0; slot < LINK_KEY_MAX_ENTRIES; slot++) {
            if (!g_link_keys[slot].valid) {
                g_link_keys[slot].addr = addr;
                memcpy(g_link_keys[slot].key, key, 16);
                g_link_keys[slot].type = (uint8_t)type;
                g_link_keys[slot].valid = 1;
                break;
            }
        }
    }
    fclose(fp);
}

static void save_link_keys(void) {
    const char *path = link_key_store_path();
    FILE *fp;
    int i;

    fp = fopen(path, "w");
    if (!fp) {
        fprintf(stderr, "[iap2-mini] failed to save link keys to %s: %s\n", path, strerror(errno));
        return;
    }
    for (i = 0; i < LINK_KEY_MAX_ENTRIES; i++) {
        char addr_str[18];
        char key_hex[33];
        if (!g_link_keys[i].valid) {
            continue;
        }
        bdaddr_to_str(&g_link_keys[i].addr, addr_str);
        link_key_to_hex(g_link_keys[i].key, key_hex);
        fprintf(fp, "%s %s %02x\n", addr_str, key_hex, g_link_keys[i].type);
    }
    fclose(fp);
}

static struct link_key_entry *find_link_key_entry(const bdaddr_t *addr) {
    int i;
    load_link_keys();
    for (i = 0; i < LINK_KEY_MAX_ENTRIES; i++) {
        if (g_link_keys[i].valid && memcmp(g_link_keys[i].addr.b, addr->b, 6) == 0) {
            return &g_link_keys[i];
        }
    }
    return NULL;
}

static void remember_link_key(const bdaddr_t *addr, const uint8_t key[16], uint8_t type) {
    struct link_key_entry *entry = find_link_key_entry(addr);
    int i;

    if (!entry) {
        for (i = 0; i < LINK_KEY_MAX_ENTRIES; i++) {
            if (!g_link_keys[i].valid) {
                entry = &g_link_keys[i];
                break;
            }
        }
        if (!entry) {
            entry = &g_link_keys[0];
        }
    }

    entry->addr = *addr;
    memcpy(entry->key, key, 16);
    entry->type = type;
    entry->valid = 1;
    save_link_keys();
}

static pid_t hci_spawn_peer_watch(int dev_id, const char *addr_str, uint16_t handle, unsigned timeout_secs) {
    pid_t pid = fork();
    if (pid != 0) {
        return pid;
    }

    {
        int fd;
        bdaddr_t peer;
        time_t deadline = time(NULL) + (time_t)timeout_secs;

        setvbuf(stderr, NULL, _IONBF, 0);
        if (str_to_bdaddr_local(addr_str, &peer) < 0) {
            perror("str_to_bdaddr_local");
            _exit(1);
        }
        fd = hci_open_event_raw(dev_id);
        if (fd < 0) {
            _exit(1);
        }
        fprintf(stderr, "[iap2-mini] peer-watch start peer=%s handle=0x%04x timeout=%us\n",
                addr_str, handle, timeout_secs);

        for (;;) {
            struct pollfd pfd;
            long ms_left;
            uint8_t buf[260];
            ssize_t n;
            uint8_t event_code;
            const uint8_t *p;
            char ev_addr[18];

            ms_left = (long)((deadline - time(NULL)) * 1000);
            if (ms_left <= 0) {
                break;
            }
            pfd.fd = fd;
            pfd.events = POLLIN;
            pfd.revents = 0;
            if (poll(&pfd, 1, (int)ms_left) <= 0) {
                break;
            }
            n = read(fd, buf, sizeof(buf));
            if (n < 3 || buf[0] != HCI_EVENT_PKT) {
                continue;
            }
            event_code = buf[1];
            p = buf + 3;

            switch (event_code) {
            case EVT_CONN_COMPLETE:
                if (n >= 14 && memcmp(p + 3, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p + 3, ev_addr);
                    fprintf(stderr,
                            "[iap2-mini] peer-watch CONN_COMPLETE peer=%s status=0x%02x handle=0x%04x link_type=0x%02x enc=0x%02x\n",
                            ev_addr, p[0], (uint16_t)(p[1] | ((p[2] & 0x0f) << 8)), p[9], p[10]);
                }
                break;
            case EVT_DISCONN_COMPLETE:
                if (n >= 7) {
                    uint16_t ev_handle = (uint16_t)(p[1] | ((p[2] & 0x0f) << 8));
                    if (handle != 0 && ev_handle == handle) {
                        fprintf(stderr,
                                "[iap2-mini] peer-watch DISCONN_COMPLETE handle=0x%04x status=0x%02x reason=0x%02x\n",
                                ev_handle, p[0], p[3]);
                    }
                }
                break;
            case EVT_AUTH_COMPLETE:
                if (n >= 6) {
                    uint16_t ev_handle = (uint16_t)(p[1] | ((p[2] & 0x0f) << 8));
                    if (handle != 0 && ev_handle == handle) {
                        fprintf(stderr,
                                "[iap2-mini] peer-watch AUTH_COMPLETE handle=0x%04x status=0x%02x\n",
                                ev_handle, p[0]);
                    }
                }
                break;
            case EVT_LINK_KEY_REQ:
                if (n >= 9 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch LINK_KEY_REQ peer=%s\n", ev_addr);
                }
                break;
            case EVT_LINK_KEY_NOTIFY:
                if (n >= 26 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch LINK_KEY_NOTIFY peer=%s type=0x%02x\n",
                            ev_addr, p[22]);
                }
                break;
            case EVT_PIN_CODE_REQ:
                if (n >= 9 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch PIN_CODE_REQ peer=%s\n", ev_addr);
                }
                break;
            case EVT_IO_CAPABILITY_REQUEST:
                if (n >= 9 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch IO_CAPABILITY_REQUEST peer=%s\n", ev_addr);
                }
                break;
            case EVT_IO_CAPABILITY_RESPONSE:
                if (n >= 12 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr,
                            "[iap2-mini] peer-watch IO_CAPABILITY_RESPONSE peer=%s io_cap=0x%02x auth=0x%02x\n",
                            ev_addr, p[6], p[8]);
                }
                break;
            case EVT_USER_CONFIRMATION_REQUEST:
                if (n >= 13 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch USER_CONFIRMATION_REQUEST peer=%s\n", ev_addr);
                }
                break;
            case EVT_USER_PASSKEY_REQUEST:
                if (n >= 9 && memcmp(p, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch USER_PASSKEY_REQUEST peer=%s\n", ev_addr);
                }
                break;
            case EVT_SIMPLE_PAIRING_COMPLETE:
                if (n >= 10 && memcmp(p + 1, peer.b, 6) == 0) {
                    bdaddr_event_to_str(p + 1, ev_addr);
                    fprintf(stderr, "[iap2-mini] peer-watch SIMPLE_PAIRING_COMPLETE peer=%s status=0x%02x\n",
                            ev_addr, p[0]);
                }
                break;
            default:
                break;
            }
        }
        fprintf(stderr, "[iap2-mini] peer-watch done peer=%s handle=0x%04x\n", addr_str, handle);
        close(fd);
    }
    _exit(0);
}

static int hci_ssp_agent_loop(int dev_id) {
    int fd;

    fd = hci_open_event_raw(dev_id);
    if (fd < 0) {
        return 1;
    }
    fprintf(stderr, "[iap2-mini] SSP agent listening on hci%d\n", dev_id);

    for (;;) {
        uint8_t buf[260];
        ssize_t n = read(fd, buf, sizeof(buf));
        uint8_t event_code;
        uint8_t plen;
        const uint8_t *p;
        char addr[18];

        if (n < 0) {
            perror("read(HCI events)");
            close(fd);
            return 1;
        }
        if (n < 3 || buf[0] != HCI_EVENT_PKT) {
            continue;
        }
        event_code = buf[1];
        plen = buf[2];
        if ((size_t)n < (size_t)(3 + plen)) {
            continue;
        }
        p = buf + 3;

        switch (event_code) {
            case EVT_IO_CAPABILITY_REQUEST: {
                uint8_t payload[9];
                memcpy(payload, p, 6);
                payload[6] = HCI_IO_CAPABILITY_DISPLAY_YESNO;
                payload[7] = HCI_OOB_DATA_NOT_PRESENT;
                payload[8] = HCI_AUTH_REQ_GENERAL_BONDING_MITM;
                bdaddr_event_to_str(p, addr);
                fprintf(stderr, "[iap2-mini] SSP IO_CAP_REQ from %s\n", addr);
                if (hci_cmd_status_only(dev_id,
                        HCI_OPCODE(OGF_LINK_CTL, OCF_IO_CAPABILITY_REQUEST_REPLY),
                        payload, sizeof(payload)) < 0) {
                    perror("HCI IO Capability Request Reply");
                }
                break;
            }
            case EVT_USER_CONFIRMATION_REQUEST:
                bdaddr_event_to_str(p, addr);
                fprintf(stderr, "[iap2-mini] SSP USER_CONFIRM_REQ from %s\n", addr);
                if (hci_cmd_status_only(dev_id,
                        HCI_OPCODE(OGF_LINK_CTL, OCF_USER_CONFIRMATION_REQUEST_REPLY),
                        p, 6) < 0) {
                    perror("HCI User Confirmation Reply");
                }
                break;
            case EVT_USER_PASSKEY_REQUEST:
                bdaddr_event_to_str(p, addr);
                fprintf(stderr, "[iap2-mini] SSP USER_PASSKEY_REQ from %s -> negative\n", addr);
                if (hci_cmd_status_only(dev_id,
                        HCI_OPCODE(OGF_LINK_CTL, OCF_USER_PASSKEY_REQUEST_NEGATIVE_REPLY),
                        p, 6) < 0) {
                    perror("HCI User Passkey Negative Reply");
                }
                break;
            case EVT_PIN_CODE_REQ:
                bdaddr_event_to_str(p, addr);
                fprintf(stderr, "[iap2-mini] SSP PIN_CODE_REQ from %s -> negative\n", addr);
                if (hci_cmd_status_only(dev_id,
                        HCI_OPCODE(OGF_LINK_CTL, OCF_PIN_CODE_REQUEST_NEGATIVE_REPLY),
                        p, 6) < 0) {
                    perror("HCI PIN Code Negative Reply");
                }
                break;
            case EVT_LINK_KEY_REQ:
                {
                    struct link_key_entry *entry;
                    bdaddr_t bdaddr;
                    uint8_t payload[22];

                    memcpy(bdaddr.b, p, 6);
                    bdaddr_event_to_str(p, addr);
                    entry = find_link_key_entry(&bdaddr);
                    if (entry) {
                        memcpy(payload, p, 6);
                        memcpy(payload + 6, entry->key, 16);
                        fprintf(stderr, "[iap2-mini] SSP LINK_KEY_REQ from %s -> cached reply type=0x%02x\n",
                                addr, entry->type);
                        if (hci_cmd_status_only(dev_id,
                                HCI_OPCODE(OGF_LINK_CTL, OCF_LINK_KEY_REQUEST_REPLY),
                                payload, sizeof(payload)) < 0) {
                            perror("HCI Link Key Request Reply");
                        }
                    } else {
                        fprintf(stderr, "[iap2-mini] SSP LINK_KEY_REQ from %s -> negative\n", addr);
                        if (hci_cmd_status_only(dev_id,
                                HCI_OPCODE(OGF_LINK_CTL, OCF_LINK_KEY_REQUEST_NEGATIVE_REPLY),
                                p, 6) < 0) {
                            perror("HCI Link Key Negative Reply");
                        }
                    }
                }
                break;
            case EVT_LINK_KEY_NOTIFY:
                {
                    bdaddr_t bdaddr;
                    memcpy(bdaddr.b, p, 6);
                    bdaddr_event_to_str(p, addr);
                    fprintf(stderr, "[iap2-mini] SSP LINK_KEY_NOTIFY from %s type=0x%02x\n",
                            addr, plen >= 23 ? p[22] : 0xff);
                    if (plen >= 23) {
                        remember_link_key(&bdaddr, p + 6, p[22]);
                    }
                }
                break;
            case EVT_IO_CAPABILITY_RESPONSE:
                bdaddr_event_to_str(p, addr);
                fprintf(stderr, "[iap2-mini] SSP IO_CAP_RSP from %s io=0x%02x auth=0x%02x\n",
                        addr, plen >= 8 ? p[6] : 0xff, plen >= 8 ? p[8] : 0xff);
                break;
            case EVT_SIMPLE_PAIRING_COMPLETE:
                bdaddr_event_to_str(p + 1, addr);
                fprintf(stderr, "[iap2-mini] SSP COMPLETE status=0x%02x peer=%s\n", p[0], addr);
                break;
            case EVT_AUTH_COMPLETE:
                fprintf(stderr, "[iap2-mini] AUTH COMPLETE status=0x%02x handle=0x%02x%02x\n",
                        plen >= 1 ? p[0] : 0xff, plen >= 3 ? p[2] : 0xff, plen >= 2 ? p[1] : 0xff);
                break;
            default:
                break;
        }
    }
}

static uint32_t env_u24(const char *name, uint32_t defv) {
    const char *v = getenv(name);
    char *end = NULL;
    unsigned long n;
    if (!v || !*v) {
        return defv;
    }
    n = strtoul(v, &end, 0);
    if (!end || *end != '\0' || n > 0xfffffful) {
        return defv;
    }
    return (uint32_t)n;
}

static const char *mfi_helper_path(void) {
    const char *path = getenv("CARTHING_MFI_HELPER");
    return (path && path[0]) ? path : HELPER_PATH_DEFAULT;
}

static int run_helper_capture(const char *const argv[], const uint8_t *stdin_buf, size_t stdin_len,
                              uint8_t **out_buf, size_t *out_len) {
    int in_pipe[2];
    int out_pipe[2];
    pid_t pid;
    int status;
    uint8_t *buf = NULL;
    size_t len = 0;

    if (pipe(in_pipe) < 0 || pipe(out_pipe) < 0) {
        return -1;
    }

    pid = fork();
    if (pid < 0) {
        close(in_pipe[0]); close(in_pipe[1]);
        close(out_pipe[0]); close(out_pipe[1]);
        return -1;
    }

    if (pid == 0) {
        dup2(in_pipe[0], STDIN_FILENO);
        dup2(out_pipe[1], STDOUT_FILENO);
        close(in_pipe[0]); close(in_pipe[1]);
        close(out_pipe[0]); close(out_pipe[1]);
        execv(argv[0], (char *const *)argv);
        perror("execv helper");
        _exit(127);
    }

    close(in_pipe[0]);
    close(out_pipe[1]);
    if (stdin_len > 0 && write_all_fd(in_pipe[1], stdin_buf, stdin_len) < 0) {
        close(in_pipe[1]);
        close(out_pipe[0]);
        waitpid(pid, NULL, 0);
        return -1;
    }
    close(in_pipe[1]);

    if (read_fd_all(out_pipe[0], &buf, &len) < 0) {
        close(out_pipe[0]);
        waitpid(pid, NULL, 0);
        return -1;
    }
    close(out_pipe[0]);

    if (waitpid(pid, &status, 0) < 0) {
        free(buf);
        return -1;
    }
    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        free(buf);
        errno = EIO;
        return -1;
    }

    *out_buf = buf;
    *out_len = len;
    return 0;
}

static int append_tlv(uint8_t *buf, size_t maxlen, size_t *off, uint16_t type,
                      const uint8_t *data, size_t len) {
    uint16_t plen = (uint16_t)(4 + len);

    if (*off + 4 + len > maxlen) {
        errno = ENOSPC;
        return -1;
    }
    buf[*off + 0] = (uint8_t)((plen >> 8) & 0xff);
    buf[*off + 1] = (uint8_t)(plen & 0xff);
    buf[*off + 2] = (uint8_t)((type >> 8) & 0xff);
    buf[*off + 3] = (uint8_t)(type & 0xff);
    if (len > 0 && data) {
        memcpy(buf + *off + 4, data, len);
    }
    *off += 4 + len;
    return 0;
}

static int append_tlv_cstr(uint8_t *buf, size_t maxlen, size_t *off, uint16_t type, const char *s) {
    return append_tlv(buf, maxlen, off, type, (const uint8_t *)s, strlen(s) + 1);
}

static void read_file_str(const char *path, char *buf, size_t maxlen, const char *fallback) {
    FILE *fp = fopen(path, "r");
    if (!fp) {
        snprintf(buf, maxlen, "%s", fallback);
        return;
    }
    if (!fgets(buf, (int)maxlen, fp)) {
        snprintf(buf, maxlen, "%s", fallback);
    }
    fclose(fp);
    buf[strcspn(buf, "\r\n")] = '\0';
}

static void read_serial(char *buf, size_t maxlen) {
    read_file_str("/run/carthing-state/serial_number", buf, maxlen, "");
    if (!buf[0]) {
        read_file_str("/var/etc/serial_number", buf, maxlen, "");
    }
    if (!buf[0]) {
        read_file_str("/etc/serial_number", buf, maxlen, "8555R08SQN19");
    }
}

enum identification_msgset {
    ID_MSGSET_EMPTY = 0,
    ID_MSGSET_EA02_ONLY,
    ID_MSGSET_EA02_SENT_ONLY,
    ID_MSGSET_NOWPLAYING_ONLY,
    ID_MSGSET_HID_NOWPLAYING,
    ID_MSGSET_HID_NOWPLAYING_EA02,
};

enum post_identification_mode {
    POST_ID_HID_NOWPLAYING = 0,
    POST_ID_HID_ONLY,
    POST_ID_NOWPLAYING_ONLY,
    POST_ID_APP_LAUNCH,
    POST_ID_ALL,
    POST_ID_NONE,
};

static enum identification_msgset identification_msgset(void) {
    const char *v = getenv("CARTHING_IAP2_ID_MSGSET");
    if (!v || !*v || strcmp(v, "baseline") == 0 || strcmp(v, "empty") == 0) {
        return ID_MSGSET_EMPTY;
    }
    if (strcmp(v, "ea02") == 0 || strcmp(v, "ea02-only") == 0) {
        return ID_MSGSET_EA02_ONLY;
    }
    if (strcmp(v, "ea02-sent-only") == 0 || strcmp(v, "ea02-tx-only") == 0 ||
        strcmp(v, "app-launch-sent-only") == 0) {
        return ID_MSGSET_EA02_SENT_ONLY;
    }
    if (strcmp(v, "nowplaying") == 0 || strcmp(v, "nowplaying-only") == 0 || strcmp(v, "np") == 0) {
        return ID_MSGSET_NOWPLAYING_ONLY;
    }
    if (strcmp(v, "all") == 0 || strcmp(v, "hid-nowplaying-ea02") == 0 ||
        strcmp(v, "hybrid") == 0 || strcmp(v, "ea02-hid-nowplaying") == 0) {
        return ID_MSGSET_HID_NOWPLAYING_EA02;
    }
    if (strcmp(v, "hid-nowplaying") == 0 || strcmp(v, "legacy") == 0) {
        return ID_MSGSET_HID_NOWPLAYING;
    }
    return ID_MSGSET_EMPTY;
}

static enum post_identification_mode post_identification_mode(void) {
    const char *v = getenv("CARTHING_IAP2_POST_ID_MODE");
    if (!v || !*v || strcmp(v, "hid-nowplaying") == 0 || strcmp(v, "default") == 0) {
        return POST_ID_HID_NOWPLAYING;
    }
    if (strcmp(v, "hid") == 0 || strcmp(v, "hid-only") == 0) {
        return POST_ID_HID_ONLY;
    }
    if (strcmp(v, "nowplaying") == 0 || strcmp(v, "nowplaying-only") == 0 || strcmp(v, "np") == 0) {
        return POST_ID_NOWPLAYING_ONLY;
    }
    if (strcmp(v, "app-launch") == 0 || strcmp(v, "ea02") == 0) {
        return POST_ID_APP_LAUNCH;
    }
    if (strcmp(v, "all") == 0) {
        return POST_ID_ALL;
    }
    if (strcmp(v, "none") == 0) {
        return POST_ID_NONE;
    }
    return POST_ID_HID_NOWPLAYING;
}

static const char *ea_protocol_name(void) {
    const char *v = getenv("CARTHING_IAP2_EA_PROTOCOL");
    return (v && v[0]) ? v : NULL;
}

static const char *preferred_bundle_seed_identifier(void) {
    const char *v = getenv("CARTHING_IAP2_PREFERRED_BUNDLE_SEED");
    return (v && v[0]) ? v : NULL;
}

static const char *app_launch_bundle_id(void) {
    const char *v = getenv("CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID");
    return (v && v[0]) ? v : NULL;
}

static int parse_message_id_list_env(const char *name, uint8_t *buf, size_t maxlen,
                                     size_t *out_len, int *was_set) {
    const char *v = getenv(name);
    size_t off = 0;

    *out_len = 0;
    *was_set = 0;
    if (!v) {
        return 0;
    }
    *was_set = 1;

    while (*v) {
        char *end = NULL;
        unsigned long msg_id;

        while (*v && (isspace((unsigned char)*v) || *v == ',' || *v == ';')) {
            v++;
        }
        if (!*v) {
            break;
        }
        errno = 0;
        msg_id = strtoul(v, &end, 0);
        if (end == v || errno != 0 || msg_id > 0xfffful) {
            return -1;
        }
        if (off + 2 > maxlen) {
            errno = ENOSPC;
            return -1;
        }
        buf[off++] = (uint8_t)((msg_id >> 8) & 0xff);
        buf[off++] = (uint8_t)(msg_id & 0xff);
        v = end;
        while (*v && isspace((unsigned char)*v)) {
            v++;
        }
        if (*v == ',' || *v == ';') {
            v++;
        } else if (*v != '\0') {
            errno = EINVAL;
            return -1;
        }
    }

    *out_len = off;
    return 0;
}

static int build_identification_params(uint8_t *buf, size_t maxlen, size_t *out_len) {
    size_t off = 0;
    size_t btc_off = 0;
    char serial[64];
    char mac_str[20];
    uint8_t btc[96];
    uint8_t transport_id[2] = {0x00, 0x01};
    uint8_t mac[6] = {0};
    uint8_t power = 0x00;
    uint8_t current[2] = {0x00, 0x64};
    uint8_t sent_ids_custom[64];
    uint8_t recv_ids_custom[64];
    size_t sent_ids_custom_len = 0;
    size_t recv_ids_custom_len = 0;
    int sent_ids_custom_set = 0;
    int recv_ids_custom_set = 0;
    enum identification_msgset msgset = identification_msgset();
    const char *protocol = ea_protocol_name();
    const char *bundle_seed = preferred_bundle_seed_identifier();

    read_serial(serial, sizeof(serial));
    if (parse_message_id_list_env("CARTHING_IAP2_ID_MSGSET_SENT_IDS",
                                  sent_ids_custom, sizeof(sent_ids_custom),
                                  &sent_ids_custom_len, &sent_ids_custom_set) < 0) {
        perror("parse CARTHING_IAP2_ID_MSGSET_SENT_IDS");
        return -1;
    }
    if (parse_message_id_list_env("CARTHING_IAP2_ID_MSGSET_RECV_IDS",
                                  recv_ids_custom, sizeof(recv_ids_custom),
                                  &recv_ids_custom_len, &recv_ids_custom_set) < 0) {
        perror("parse CARTHING_IAP2_ID_MSGSET_RECV_IDS");
        return -1;
    }

    if (append_tlv_cstr(buf, maxlen, &off, 0x0000, "Spotify Car Thing") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0001, "Car Thing") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0002, "Spotify USA Inc.") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0003, serial) < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0004, "1.0.0") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0005, "1.0") < 0) return -1;
    if (sent_ids_custom_set || recv_ids_custom_set) {
        if (append_tlv(buf, maxlen, &off, 0x0006,
                       sent_ids_custom_set ? sent_ids_custom : NULL,
                       sent_ids_custom_set ? sent_ids_custom_len : 0) < 0) return -1;
        if (append_tlv(buf, maxlen, &off, 0x0007,
                       recv_ids_custom_set ? recv_ids_custom : NULL,
                       recv_ids_custom_set ? recv_ids_custom_len : 0) < 0) return -1;
    } else {
        switch (msgset) {
            case ID_MSGSET_EA02_ONLY:
            {
                static const uint8_t sent_ids[] = {0xEA, 0x02};
                static const uint8_t recv_ids[] = {0xEA, 0x00, 0xEA, 0x01};
                if (append_tlv(buf, maxlen, &off, 0x0006, sent_ids, sizeof(sent_ids)) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, recv_ids, sizeof(recv_ids)) < 0) return -1;
                break;
            }
            case ID_MSGSET_EA02_SENT_ONLY:
            {
                static const uint8_t sent_ids[] = {0xEA, 0x02};
                if (append_tlv(buf, maxlen, &off, 0x0006, sent_ids, sizeof(sent_ids)) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, NULL, 0) < 0) return -1;
                break;
            }
            case ID_MSGSET_NOWPLAYING_ONLY:
            {
                static const uint8_t sent_ids[] = {0x40, 0xC8, 0x40, 0xC9};
                static const uint8_t recv_ids[] = {0x48, 0x00};
                if (append_tlv(buf, maxlen, &off, 0x0006, sent_ids, sizeof(sent_ids)) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, recv_ids, sizeof(recv_ids)) < 0) return -1;
                break;
            }
            case ID_MSGSET_HID_NOWPLAYING:
            {
                static const uint8_t sent_ids[] = {0x40, 0xC8, 0x68, 0x00};
                static const uint8_t recv_ids[] = {0x48, 0x00};
                if (append_tlv(buf, maxlen, &off, 0x0006, sent_ids, sizeof(sent_ids)) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, recv_ids, sizeof(recv_ids)) < 0) return -1;
                break;
            }
            case ID_MSGSET_HID_NOWPLAYING_EA02:
            {
                static const uint8_t sent_ids[] = {0x40, 0xC8, 0x68, 0x00, 0xEA, 0x02};
                static const uint8_t recv_ids[] = {0x48, 0x00, 0xEA, 0x00, 0xEA, 0x01};
                if (append_tlv(buf, maxlen, &off, 0x0006, sent_ids, sizeof(sent_ids)) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, recv_ids, sizeof(recv_ids)) < 0) return -1;
                break;
            }
            case ID_MSGSET_EMPTY:
            default:
                if (append_tlv(buf, maxlen, &off, 0x0006, NULL, 0) < 0) return -1;
                if (append_tlv(buf, maxlen, &off, 0x0007, NULL, 0) < 0) return -1;
                break;
        }
    }
    if (append_tlv(buf, maxlen, &off, 0x0008, &power, 1) < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0009, current, sizeof(current)) < 0) return -1;
    if (protocol && protocol[0]) {
        uint8_t eap[256];
        size_t eap_off = 0;
        uint8_t protocol_id = 0x00;
        uint8_t match_action = (uint8_t)env_u8("CARTHING_IAP2_EA_MATCH_ACTION", 1, 0, 2);

        if (append_tlv(eap, sizeof(eap), &eap_off, 0x0000, &protocol_id, sizeof(protocol_id)) < 0) return -1;
        if (append_tlv_cstr(eap, sizeof(eap), &eap_off, 0x0001, protocol) < 0) return -1;
        if (append_tlv(eap, sizeof(eap), &eap_off, 0x0002, &match_action, sizeof(match_action)) < 0) return -1;
        if (append_tlv(buf, maxlen, &off, 0x000A, eap, eap_off) < 0) return -1;
    }
    if (bundle_seed && bundle_seed[0]) {
        if (append_tlv_cstr(buf, maxlen, &off, 0x000B, bundle_seed) < 0) return -1;
    }
    if (append_tlv_cstr(buf, maxlen, &off, 0x000C, "en") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x000D, "en") < 0) return -1;

    read_file_str("/sys/class/bluetooth/hci0/address", mac_str, sizeof(mac_str),
                  "30:E3:D6:00:5F:A4");
    mac_str[strcspn(mac_str, "\r\n")] = '\0';
    sscanf(mac_str, "%hhx:%hhx:%hhx:%hhx:%hhx:%hhx",
           &mac[0], &mac[1], &mac[2], &mac[3], &mac[4], &mac[5]);
    if (append_tlv(btc, sizeof(btc), &btc_off, 0x0000, transport_id, sizeof(transport_id)) < 0) return -1;
    if (append_tlv_cstr(btc, sizeof(btc), &btc_off, 0x0001, "Bluetooth") < 0) return -1;
    if (append_tlv(btc, sizeof(btc), &btc_off, 0x0002, NULL, 0) < 0) return -1;
    if (append_tlv(btc, sizeof(btc), &btc_off, 0x0003, mac, sizeof(mac)) < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0011, btc, btc_off) < 0) return -1;

    *out_len = off;
    return 0;
}

static int build_start_nowplaying_params(uint8_t *buf, size_t maxlen, size_t *out_len) {
    size_t off = 0;
    static const uint16_t fields[] = {0x0001, 0x0002, 0x0003, 0x0008, 0x000F, 0x0010};
    size_t i;

    for (i = 0; i < sizeof(fields) / sizeof(fields[0]); i++) {
        uint8_t field_id[2] = {
            (uint8_t)((fields[i] >> 8) & 0xff),
            (uint8_t)(fields[i] & 0xff),
        };
        if (append_tlv(buf, maxlen, &off, 0x0000, field_id, sizeof(field_id)) < 0) {
            return -1;
        }
    }

    *out_len = off;
    return 0;
}

static int write_control_msg(uint16_t msg_id, const uint8_t *payload, size_t payload_len) {
    uint8_t header[6];
    uint16_t total = (uint16_t)(6 + payload_len);

    header[0] = (uint8_t)((IAP2_CSM_START >> 8) & 0xff);
    header[1] = (uint8_t)(IAP2_CSM_START & 0xff);
    header[2] = (uint8_t)((total >> 8) & 0xff);
    header[3] = (uint8_t)(total & 0xff);
    header[4] = (uint8_t)((msg_id >> 8) & 0xff);
    header[5] = (uint8_t)(msg_id & 0xff);
    if (write_all_fd(STDOUT_FILENO, header, sizeof(header)) < 0) {
        return -1;
    }
    if (payload_len > 0 && write_all_fd(STDOUT_FILENO, payload, payload_len) < 0) {
        return -1;
    }
    return 0;
}

static int write_raw_msg(uint16_t msg_id, const uint8_t *payload, size_t payload_len) {
    uint8_t header[6];
    uint16_t total = (uint16_t)(6 + payload_len);

    header[0] = 0xFF;
    header[1] = 0x5A;
    header[2] = (uint8_t)((total >> 8) & 0xff);
    header[3] = (uint8_t)(total & 0xff);
    header[4] = (uint8_t)((msg_id >> 8) & 0xff);
    header[5] = (uint8_t)(msg_id & 0xff);
    if (write_all_fd(STDOUT_FILENO, header, sizeof(header)) < 0) {
        return -1;
    }
    if (payload_len > 0 && write_all_fd(STDOUT_FILENO, payload, payload_len) < 0) {
        return -1;
    }
    return 0;
}

static uint8_t iap2_cksum(const uint8_t *buf, size_t n) {
    uint8_t s = 0;
    size_t i;
    for (i = 0; i < n; i++) {
        s = (uint8_t)(s + buf[i]);
    }
    return (uint8_t)((~s) + 1);
}

static int build_control_msg_buf(uint16_t msg_id, const uint8_t *payload, size_t payload_len,
                                 uint8_t **out_buf, size_t *out_len) {
    uint8_t *buf;
    uint16_t total = (uint16_t)(6 + payload_len);

    buf = calloc(1, total);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    buf[0] = (uint8_t)((IAP2_CSM_START >> 8) & 0xff);
    buf[1] = (uint8_t)(IAP2_CSM_START & 0xff);
    buf[2] = (uint8_t)((total >> 8) & 0xff);
    buf[3] = (uint8_t)(total & 0xff);
    buf[4] = (uint8_t)((msg_id >> 8) & 0xff);
    buf[5] = (uint8_t)(msg_id & 0xff);
    if (payload_len > 0) {
        memcpy(buf + 6, payload, payload_len);
    }
    *out_buf = buf;
    *out_len = total;
    return 0;
}

static int write_iap2_msg(enum output_mode mode, uint16_t msg_id, const uint8_t *payload, size_t payload_len) {
    if (mode == OUTPUT_RAW) {
        return write_raw_msg(msg_id, payload, payload_len);
    }
    return write_control_msg(msg_id, payload, payload_len);
}

static void challenge_to_hex(const uint8_t *buf, size_t len, char *hex_out) {
    static const char hexdig[] = "0123456789abcdef";
    size_t i;
    for (i = 0; i < len; i++) {
        hex_out[i * 2] = hexdig[(buf[i] >> 4) & 0x0f];
        hex_out[i * 2 + 1] = hexdig[buf[i] & 0x0f];
    }
    hex_out[len * 2] = '\0';
}

static int parse_challenge_param(const uint8_t *params, size_t params_len, uint8_t challenge[32], size_t *challenge_len) {
    uint16_t plen;
    uint16_t pid;

    if (params_len < 4) {
        return -1;
    }
    plen = (uint16_t)((params[0] << 8) | params[1]);
    pid = (uint16_t)((params[2] << 8) | params[3]);
    if (pid != 0x0000 || plen < 4 || plen > params_len) {
        return -1;
    }
    if ((size_t)(plen - 4) > 32) {
        return -1;
    }
    memset(challenge, 0, 32);
    memcpy(challenge, params + 4, plen - 4);
    *challenge_len = (size_t)(plen - 4);
    return 0;
}

static int forward_helper_noinput(const char *subcmd) {
    uint8_t *out = NULL;
    size_t out_len = 0;
    int rc;

    rc = run_helper_capture((const char *const[]){mfi_helper_path(), subcmd, NULL}, NULL, 0, &out, &out_len);
    if (rc < 0) {
        perror("run helper");
        return -1;
    }
    rc = write_all_fd(STDOUT_FILENO, out, out_len);
    free(out);
    return rc;
}

static int capture_helper_noinput(const char *subcmd, uint8_t **out, size_t *out_len) {
    const char *helper = mfi_helper_path();
    const char *argv[] = {helper, subcmd, NULL};
    return run_helper_capture(argv, NULL, 0, out, out_len);
}

static int forward_helper_aa03(const uint8_t challenge[32], size_t challenge_len) {
    uint8_t *out = NULL;
    size_t out_len = 0;
    int rc;

    rc = capture_helper_aa03(challenge, challenge_len, &out, &out_len);
    if (rc < 0) {
        perror("run helper");
        return -1;
    }
    rc = write_all_fd(STDOUT_FILENO, out, out_len);
    free(out);
    return rc;
}

static int capture_helper_aa03(const uint8_t challenge[32], size_t challenge_len,
                               uint8_t **out, size_t *out_len) {
    const char *helper = mfi_helper_path();
    char hex[65];
    const char *argv[4];

    challenge_to_hex(challenge, challenge_len, hex);
    argv[0] = helper;
    argv[1] = "aa03";
    argv[2] = hex;
    argv[3] = NULL;
    return run_helper_capture(argv, NULL, 0, out, out_len);
}

static int capture_identification_msg(uint8_t **out, size_t *out_len) {
    uint8_t params[512];
    size_t params_len = 0;
    return build_identification_params(params, sizeof(params), &params_len) < 0
        ? -1
        : build_control_msg_buf(IAP2_MSG_ID_INFO, params, params_len, out, out_len);
}

static int capture_start_nowplaying_msg(uint8_t **out, size_t *out_len) {
    uint8_t params[128];
    size_t params_len = 0;
    return build_start_nowplaying_params(params, sizeof(params), &params_len) < 0
        ? -1
        : build_control_msg_buf(IAP2_MSG_START_NOWPLAYING, params, params_len, out, out_len);
}

static int capture_request_app_launch_msg(uint8_t **out, size_t *out_len) {
    uint8_t params[256];
    size_t off = 0;
    uint8_t method = (uint8_t)env_u8("CARTHING_IAP2_APP_LAUNCH_METHOD", 0, 0, 255);
    const char *bundle_id = app_launch_bundle_id();

    if (!bundle_id || !bundle_id[0]) {
        errno = ENOENT;
        return -1;
    }
    if (append_tlv_cstr(params, sizeof(params), &off, 0x0000, bundle_id) < 0) {
        return -1;
    }
    if (append_tlv(params, sizeof(params), &off, 0x0001, &method, sizeof(method)) < 0) {
        return -1;
    }
    return build_control_msg_buf(IAP2_MSG_APP_LAUNCH, params, off, out, out_len);
}

static int tlv_find_param(const uint8_t *params, size_t params_len, uint16_t want_id,
                          const uint8_t **data, size_t *data_len) {
    size_t off = 0;
    while (off + 4 <= params_len) {
        uint16_t plen = (uint16_t)((params[off] << 8) | params[off + 1]);
        uint16_t pid = (uint16_t)((params[off + 2] << 8) | params[off + 3]);
        if (plen < 4 || off + plen > params_len) {
            return -1;
        }
        if (pid == want_id) {
            *data = params + off + 4;
            *data_len = (size_t)(plen - 4);
            return 0;
        }
        off += plen;
    }
    return -1;
}

static void log_rejected_param_ids(const char *prefix, const uint8_t *params, size_t params_len) {
    size_t off = 0;

    while (off + 4 <= params_len) {
        uint16_t plen = (uint16_t)((params[off] << 8) | params[off + 1]);
        uint16_t pid = (uint16_t)((params[off + 2] << 8) | params[off + 3]);
        if (plen < 4 || off + plen > params_len) {
            fprintf(stderr, "[iap2-mini] %s malformed rejected-param TLV at off=%zu\n", prefix, off);
            return;
        }
        fprintf(stderr, "[iap2-mini] %s rejected param id=0x%04x\n", prefix, pid);
        off += plen;
    }
}

static int parse_ea_session_handles(const uint8_t *params, size_t params_len,
                                    uint8_t *protocol_id, size_t *protocol_id_len,
                                    uint8_t *session_id, size_t *session_id_len) {
    const uint8_t *data = NULL;
    size_t data_len = 0;

    if (tlv_find_param(params, params_len, 0x0000, &data, &data_len) < 0 ||
        data_len == 0 || data_len > 8) {
        return -1;
    }
    memcpy(protocol_id, data, data_len);
    *protocol_id_len = data_len;

    if (tlv_find_param(params, params_len, 0x0001, &data, &data_len) < 0 ||
        data_len == 0 || data_len > 8) {
        return -1;
    }
    memcpy(session_id, data, data_len);
    *session_id_len = data_len;
    return 0;
}

static int capture_ea_status_msg(const uint8_t *protocol_id, size_t protocol_id_len,
                                 const uint8_t *session_id, size_t session_id_len,
                                 int open, uint8_t **out, size_t *out_len) {
    uint8_t params[64];
    size_t off = 0;
    uint8_t status = open ? 1 : 0;

    if (!protocol_id || protocol_id_len == 0 || !session_id || session_id_len == 0) {
        errno = EINVAL;
        return -1;
    }
    if (append_tlv(params, sizeof(params), &off, 0x0000, protocol_id, protocol_id_len) < 0) {
        return -1;
    }
    if (append_tlv(params, sizeof(params), &off, 0x0001, session_id, session_id_len) < 0) {
        return -1;
    }
    if (append_tlv(params, sizeof(params), &off, 0x0002, &status, sizeof(status)) < 0) {
        return -1;
    }
    return build_control_msg_buf(IAP2_MSG_EA_STATUS, params, off, out, out_len);
}

static int capture_start_hid_msg(uint8_t **out, size_t *out_len) {
    uint8_t params[128];
    size_t off = 0;
    uint8_t cid[2] = {
        (uint8_t)((HID_COMPONENT_ID >> 8) & 0xff),
        (uint8_t)(HID_COMPONENT_ID & 0xff),
    };

    if (append_tlv(params, sizeof(params), &off, 0x0000, cid, sizeof(cid)) < 0) {
        return -1;
    }
    if (append_tlv(params, sizeof(params), &off, 0x0001,
                   kHidConsumerDesc, sizeof(kHidConsumerDesc)) < 0) {
        return -1;
    }
    return build_control_msg_buf(IAP2_MSG_START_HID, params, off, out, out_len);
}

static int write_link_control_msg(struct link_state *state, uint8_t ack_seq, const uint8_t *payload,
                                  size_t payload_len, uint16_t msg_id, int cache_reply);

static int write_post_identification_raw(void) {
    enum post_identification_mode mode = post_identification_mode();
    uint8_t *msg = NULL;
    size_t msg_len = 0;
    int rc;

    if (mode == POST_ID_NONE) {
        return 0;
    }
    if (mode == POST_ID_NOWPLAYING_ONLY) {
        if (capture_start_nowplaying_msg(&msg, &msg_len) < 0) {
            perror("build StartNowPlaying");
            return -1;
        }
        rc = write_all_fd(STDOUT_FILENO, msg, msg_len);
        fprintf(stderr, "[iap2-mini] -> 40C8 StartNowPlaying len=%zu\n", msg_len);
        free(msg);
        return rc;
    }
    if (mode == POST_ID_HID_ONLY || mode == POST_ID_HID_NOWPLAYING || mode == POST_ID_ALL) {
        if (capture_start_hid_msg(&msg, &msg_len) < 0) {
            perror("build StartHID");
            return -1;
        }
        rc = write_all_fd(STDOUT_FILENO, msg, msg_len);
        fprintf(stderr, "[iap2-mini] -> 6800 StartHID len=%zu\n", msg_len);
        free(msg);
        msg = NULL;
        if (rc < 0) {
            return rc;
        }
        if (mode == POST_ID_HID_ONLY) {
            return 0;
        }

        if (capture_start_nowplaying_msg(&msg, &msg_len) < 0) {
            perror("build StartNowPlaying");
            return -1;
        }
        rc = write_all_fd(STDOUT_FILENO, msg, msg_len);
        fprintf(stderr, "[iap2-mini] -> 40C8 StartNowPlaying len=%zu\n", msg_len);
        free(msg);
        msg = NULL;
        if (rc < 0) {
            return rc;
        }
    }
    if (mode == POST_ID_APP_LAUNCH || mode == POST_ID_ALL) {
        if (!wait_for_local_user_trigger()) {
            return 0;
        }
        if (capture_request_app_launch_msg(&msg, &msg_len) < 0) {
            fprintf(stderr, "[iap2-mini] app-launch skipped: set CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID\n");
            return 0;
        }
        rc = write_all_fd(STDOUT_FILENO, msg, msg_len);
        fprintf(stderr, "[iap2-mini] -> EA02 RequestAppLaunch len=%zu bundle_id=%s\n",
                msg_len, app_launch_bundle_id());
        free(msg);
        return rc;
    }
    return 0;
}

static int write_post_identification_link(struct link_state *state, uint8_t ack_seq) {
    enum post_identification_mode mode = post_identification_mode();
    uint8_t *msg = NULL;
    size_t msg_len = 0;

    if (mode == POST_ID_NONE) {
        return 0;
    }
    if (mode == POST_ID_NOWPLAYING_ONLY) {
        if (capture_start_nowplaying_msg(&msg, &msg_len) < 0) {
            perror("build link StartNowPlaying");
            return -1;
        }
        if (write_link_control_msg(state, ack_seq, msg, msg_len, IAP2_MSG_START_NOWPLAYING, 1) < 0) {
            free(msg);
            return -1;
        }
        fprintf(stderr, "[iap2-mini] -> link 0x40c8 seq=%u sid=%u len=%zu\n",
                state->last_tx_seq, state->control_sid, msg_len);
        free(msg);
        return 0;
    }
    if (mode == POST_ID_HID_ONLY || mode == POST_ID_HID_NOWPLAYING || mode == POST_ID_ALL) {
        if (capture_start_hid_msg(&msg, &msg_len) < 0) {
            perror("build link StartHID");
            return -1;
        }
        if (write_link_control_msg(state, ack_seq, msg, msg_len, IAP2_MSG_START_HID, 1) < 0) {
            free(msg);
            return -1;
        }
        fprintf(stderr, "[iap2-mini] -> link 0x6800 seq=%u sid=%u len=%zu\n",
                state->last_tx_seq, state->control_sid, msg_len);
        free(msg);
        msg = NULL;
        if (mode == POST_ID_HID_ONLY) {
            return 0;
        }

        if (capture_start_nowplaying_msg(&msg, &msg_len) < 0) {
            perror("build link StartNowPlaying");
            return -1;
        }
        if (write_link_control_msg(state, ack_seq, msg, msg_len, IAP2_MSG_START_NOWPLAYING, 0) < 0) {
            free(msg);
            return -1;
        }
        fprintf(stderr, "[iap2-mini] -> link 0x40c8 seq=%u sid=%u len=%zu\n",
                state->tx_seq, state->control_sid, msg_len);
        free(msg);
        msg = NULL;
    }
    if (mode == POST_ID_APP_LAUNCH || mode == POST_ID_ALL) {
        if (!wait_for_local_user_trigger()) {
            return 0;
        }
        if (capture_request_app_launch_msg(&msg, &msg_len) < 0) {
            fprintf(stderr, "[iap2-mini] link app-launch skipped: set CARTHING_IAP2_APP_LAUNCH_BUNDLE_ID\n");
            return 0;
        }
        if (write_link_control_msg(state, ack_seq, msg, msg_len, IAP2_MSG_APP_LAUNCH, 0) < 0) {
            free(msg);
            return -1;
        }
        fprintf(stderr, "[iap2-mini] -> link 0xEA02 seq=%u sid=%u len=%zu bundle_id=%s\n",
                state->tx_seq, state->control_sid, msg_len, app_launch_bundle_id());
        free(msg);
    }
    return 0;
}

static int handle_message(uint16_t msg_id, const uint8_t *payload, size_t payload_len, int *auth_ok, enum output_mode mode) {
    uint8_t idbuf[512];
    size_t idlen = 0;
    uint8_t challenge[32];
    size_t challenge_len = 0;
    uint8_t *reply = NULL;
    size_t reply_len = 0;
    int rc;

    switch (msg_id) {
        case IAP2_MSG_AUTH_CERT_REQ:
            fprintf(stderr, "[iap2-mini] <- AA00\n");
            return forward_helper_noinput("aa01-live");
        case IAP2_MSG_AUTH_CHAL_REQ:
            fprintf(stderr, "[iap2-mini] <- AA02\n");
            if (parse_challenge_param(payload, payload_len, challenge, &challenge_len) < 0) {
                fprintf(stderr, "[iap2-mini] malformed AA02 param\n");
                return -1;
            }
            return forward_helper_aa03(challenge, challenge_len);
        case IAP2_MSG_AUTH_OK:
            fprintf(stderr, "[iap2-mini] <- AA05 auth success\n");
            *auth_ok = 1;
            return 0;
        case IAP2_MSG_AUTH_FAILED:
            fprintf(stderr, "[iap2-mini] <- AA04 auth failure\n");
            return -1;
        case IAP2_MSG_ID_START:
            fprintf(stderr, "[iap2-mini] <- 1D00 StartIdentification\n");
            if (!*auth_ok) {
                fprintf(stderr, "[iap2-mini] identification before AA05\n");
                return -1;
            }
            if (build_identification_params(idbuf, sizeof(idbuf), &idlen) < 0) {
                perror("build identification");
                return -1;
            }
            return write_iap2_msg(mode, IAP2_MSG_ID_INFO, idbuf, idlen);
        case IAP2_MSG_ID_ACCEPTED:
            fprintf(stderr, "[iap2-mini] <- 1D02 IdentificationAccepted\n");
            return write_post_identification_raw();
        case IAP2_MSG_ID_REJECTED:
            fprintf(stderr, "[iap2-mini] <- 1D03 IdentificationRejected\n");
            if (payload_len >= 4) {
                log_rejected_param_ids("1D03", payload, payload_len);
            }
            return -1;
        case IAP2_MSG_EA_START:
            fprintf(stderr, "[iap2-mini] <- EA00 StartExternalAccessoryProtocolSession len=%zu\n",
                    payload_len);
            if (parse_ea_session_handles(payload, payload_len,
                                         challenge, &challenge_len,
                                         idbuf, &idlen) < 0) {
                fprintf(stderr, "[iap2-mini] malformed EA00 params\n");
                return 0;
            }
            if (capture_ea_status_msg(challenge, challenge_len, idbuf, idlen, 1, &reply, &reply_len) < 0) {
                perror("build EA03");
                return -1;
            }
            rc = write_iap2_msg(mode, IAP2_MSG_EA_STATUS, reply + 6, reply_len - 6);
            free(reply);
            if (rc < 0) {
                return -1;
            }
            fprintf(stderr, "[iap2-mini] -> EA03 StatusExternalAccessoryProtocolSession open=1\n");
            return 0;
        case IAP2_MSG_EA_STOP:
            fprintf(stderr, "[iap2-mini] <- EA01 StopExternalAccessoryProtocolSession len=%zu\n",
                    payload_len);
            return 0;
        case IAP2_MSG_NOWPLAYING_UPDATE:
            fprintf(stderr, "[iap2-mini] <- 4800 NowPlayingUpdate len=%zu\n", payload_len);
            return 0;
        default:
            fprintf(stderr, "[iap2-mini] ignoring unsupported msg 0x%04x\n", msg_id);
            return 0;
    }
}

static int loop_control_messages(void) {
    int auth_ok = 0;

    for (;;) {
        uint8_t header[6];
        uint16_t start;
        uint16_t total;
        uint16_t msg_id;
        uint8_t *payload = NULL;
        size_t payload_len = 0;
        int rc;

        rc = read_exact_fd(STDIN_FILENO, header, sizeof(header));
        if (rc == 1) {
            return 0;
        }
        if (rc < 0) {
            perror("read header");
            return 1;
        }

        start = (uint16_t)((header[0] << 8) | header[1]);
        total = (uint16_t)((header[2] << 8) | header[3]);
        msg_id = (uint16_t)((header[4] << 8) | header[5]);
        if (start != IAP2_CSM_START || total < 6) {
            fprintf(stderr, "[iap2-mini] bad header start=0x%04x len=%u\n", start, total);
            return 1;
        }

        payload_len = (size_t)total - 6;
        if (payload_len > 0) {
            payload = calloc(1, payload_len);
            if (!payload) {
                perror("calloc");
                return 1;
            }
            rc = read_exact_fd(STDIN_FILENO, payload, payload_len);
            if (rc != 0) {
                perror("read payload");
                free(payload);
                return 1;
            }
        }

        rc = handle_message(msg_id, payload, payload_len, &auth_ok, OUTPUT_CONTROL);
        free(payload);
        if (rc != 0) {
            return 1;
        }
    }
}

static int write_link_pkt(uint8_t ctl, uint8_t sid, uint8_t seq, uint8_t ack,
                          const uint8_t *payload, size_t payload_len) {
    uint8_t header[9];
    uint8_t *buf;
    size_t total = 9 + payload_len + (payload_len > 0 ? 1 : 0);
    int rc;

    buf = calloc(1, total);
    if (!buf) {
        errno = ENOMEM;
        return -1;
    }
    header[0] = 0xFF;
    header[1] = 0x5A;
    header[2] = (uint8_t)((total >> 8) & 0xff);
    header[3] = (uint8_t)(total & 0xff);
    header[4] = ctl;
    header[5] = seq;
    header[6] = ack;
    header[7] = sid;
    header[8] = iap2_cksum(header, 8);
    memcpy(buf, header, sizeof(header));
    if (payload_len > 0) {
        memcpy(buf + 9, payload, payload_len);
        buf[9 + payload_len] = iap2_cksum(payload, payload_len);
    }
    rc = write_all_fd(STDOUT_FILENO, buf, total);
    free(buf);
    return rc;
}

static int write_link_ack_only(struct link_state *state, uint8_t ack_seq) {
    return write_link_pkt(IAP2_CTL_ACK, IAP2_SID_CTL, state->tx_seq, ack_seq, NULL, 0);
}

static int write_link_syn(struct link_state *state) {
    static const uint8_t syn_payload[14] = {
        0x01, 0x07, 0x08, 0x00, 0x00, 0xFA, 0x00, 0x19,
        0x03, 0x01, 0x01, 0x00, 0x00, 0x01
    };
    return write_link_pkt(IAP2_CTL_SYN, IAP2_SID_CTL, state->tx_seq, 0,
                          syn_payload, sizeof(syn_payload));
}

static int write_link_synack(struct link_state *state, uint8_t ack_seq) {
    static const uint8_t syn_payload[14] = {
        0x01, 0x07, 0x08, 0x00, 0x00, 0xFA, 0x00, 0x19,
        0x03, 0x01, 0x01, 0x00, 0x00, 0x01
    };
    uint8_t tx_seq = (uint8_t)(state->tx_seq + 1);
    state->tx_seq = tx_seq;
    return write_link_pkt(IAP2_CTL_SYN | IAP2_CTL_ACK, IAP2_SID_CTL, tx_seq, ack_seq,
                          syn_payload, sizeof(syn_payload));
}

static int write_link_reply_seq(struct link_state *state, uint8_t tx_seq, uint8_t ack_seq,
                                const uint8_t *payload, size_t payload_len, uint16_t msg_id,
                                int cache_reply) {
    if (cache_reply) {
        if (payload_len > sizeof(state->last_tx_payload)) {
            errno = EOVERFLOW;
            return -1;
        }
        if (payload_len > 0) {
            memcpy(state->last_tx_payload, payload, payload_len);
        }
        state->last_tx_payload_len = payload_len;
        state->last_tx_seq = tx_seq;
        state->last_tx_msg_id = msg_id;
        state->last_tx_valid = 1;
    }
    return write_link_pkt(IAP2_CTL_ACK, state->control_sid, tx_seq, ack_seq, payload, payload_len);
}

static int write_link_control_msg(struct link_state *state, uint8_t ack_seq, const uint8_t *payload,
                                  size_t payload_len, uint16_t msg_id, int cache_reply) {
    uint8_t tx_seq = (uint8_t)(state->tx_seq + 1);
    state->tx_seq = tx_seq;
    return write_link_reply_seq(state, tx_seq, ack_seq, payload, payload_len, msg_id, cache_reply);
}

static int write_link_reply(struct link_state *state, uint8_t ack_seq, const uint8_t *payload,
                            size_t payload_len, uint16_t msg_id) {
    return write_link_control_msg(state, ack_seq, payload, payload_len, msg_id, 1);
}

static int handle_link_control_msg(struct link_state *state, uint8_t rx_seq,
                                   uint16_t msg_id, const uint8_t *payload, size_t payload_len) {
    uint8_t *reply = NULL;
    size_t reply_len = 0;
    uint8_t challenge[32];
    size_t challenge_len = 0;

    switch (msg_id) {
        case IAP2_MSG_AUTH_CERT_REQ:
            fprintf(stderr, "[iap2-mini] <- link AA00\n");
            if (capture_helper_noinput("aa01-live", &reply, &reply_len) < 0) {
                perror("helper aa01-live");
                return -1;
            }
            break;
        case IAP2_MSG_AUTH_CHAL_REQ:
            fprintf(stderr, "[iap2-mini] <- link AA02\n");
            if (parse_challenge_param(payload, payload_len, challenge, &challenge_len) < 0) {
                fprintf(stderr, "[iap2-mini] malformed link AA02 param\n");
                return -1;
            }
            if (capture_helper_aa03(challenge, challenge_len, &reply, &reply_len) < 0) {
                perror("helper aa03");
                return -1;
            }
            break;
        case IAP2_MSG_AUTH_OK:
            fprintf(stderr, "[iap2-mini] <- link AA05 auth success\n");
            state->auth_ok = 1;
            return write_link_ack_only(state, rx_seq);
        case IAP2_MSG_AUTH_FAILED:
            fprintf(stderr, "[iap2-mini] <- link AA04 auth failure\n");
            return -1;
        case IAP2_MSG_ID_START:
            fprintf(stderr, "[iap2-mini] <- link 1D00 StartIdentification\n");
            if (!state->auth_ok) {
                fprintf(stderr, "[iap2-mini] link identification before AA05\n");
                return -1;
            }
            if (capture_identification_msg(&reply, &reply_len) < 0) {
                perror("build link identification");
                return -1;
            }
            if (reply_len > 0) {
                char preview[193];
                size_t show = reply_len < 48 ? reply_len : 48;
                hex_preview_bytes(reply, show, preview, sizeof(preview));
                fprintf(stderr, "[iap2-mini] identification payload len=%zu preview=%s\n",
                        reply_len, preview);
            }
            break;
        case IAP2_MSG_ID_ACCEPTED:
            fprintf(stderr, "[iap2-mini] <- link 1D02 IdentificationAccepted\n");
            return write_post_identification_link(state, rx_seq);
        case IAP2_MSG_ID_REJECTED:
            fprintf(stderr, "[iap2-mini] <- link 1D03 IdentificationRejected\n");
            if (payload_len > 0) {
                char preview[193];
                size_t show = payload_len < 48 ? payload_len : 48;
                hex_preview_bytes(payload, show, preview, sizeof(preview));
                fprintf(stderr, "[iap2-mini] 1D03 params len=%zu preview=%s\n",
                        payload_len, preview);
                log_rejected_param_ids("1D03", payload, payload_len);
            }
            return -1;
        case IAP2_MSG_EA_START:
            fprintf(stderr, "[iap2-mini] <- link EA00 StartExternalAccessoryProtocolSession len=%zu\n",
                    payload_len);
            if (payload_len > 0) {
                char preview[193];
                size_t show = payload_len < 48 ? payload_len : 48;
                hex_preview_bytes(payload, show, preview, sizeof(preview));
                fprintf(stderr, "[iap2-mini] EA00 params preview=%s\n", preview);
            }
            if (parse_ea_session_handles(payload, payload_len,
                                         state->ea_protocol_id, &state->ea_protocol_id_len,
                                         state->ea_session_id, &state->ea_session_id_len) < 0) {
                fprintf(stderr, "[iap2-mini] malformed link EA00 params\n");
                return write_link_ack_only(state, rx_seq);
            }
            state->ea_session_open = 1;
            if (capture_ea_status_msg(state->ea_protocol_id, state->ea_protocol_id_len,
                                      state->ea_session_id, state->ea_session_id_len,
                                      1, &reply, &reply_len) < 0) {
                perror("build link EA03");
                return -1;
            }
            if (write_link_control_msg(state, rx_seq, reply, reply_len, IAP2_MSG_EA_STATUS, 0) < 0) {
                free(reply);
                return -1;
            }
            fprintf(stderr, "[iap2-mini] -> link 0xEA03 seq=%u sid=%u len=%zu open=1\n",
                    state->tx_seq, state->control_sid, reply_len);
            free(reply);
            return 0;
        case IAP2_MSG_EA_STOP:
            fprintf(stderr, "[iap2-mini] <- link EA01 StopExternalAccessoryProtocolSession len=%zu\n",
                    payload_len);
            if (state->ea_protocol_id_len > 0 && state->ea_session_id_len > 0) {
                state->ea_session_open = 0;
                if (capture_ea_status_msg(state->ea_protocol_id, state->ea_protocol_id_len,
                                          state->ea_session_id, state->ea_session_id_len,
                                          0, &reply, &reply_len) < 0) {
                    perror("build link EA03 close");
                    return -1;
                }
                if (write_link_control_msg(state, rx_seq, reply, reply_len, IAP2_MSG_EA_STATUS, 0) < 0) {
                    free(reply);
                    return -1;
                }
                fprintf(stderr, "[iap2-mini] -> link 0xEA03 seq=%u sid=%u len=%zu open=0\n",
                        state->tx_seq, state->control_sid, reply_len);
                free(reply);
                return 0;
            }
            return write_link_ack_only(state, rx_seq);
        case IAP2_MSG_NOWPLAYING_UPDATE:
            fprintf(stderr, "[iap2-mini] <- link 4800 NowPlayingUpdate len=%zu\n", payload_len);
            return write_link_ack_only(state, rx_seq);
        case IAP2_MSG_DEVICE_HID_REPORT:
            fprintf(stderr, "[iap2-mini] <- link 6802 DeviceHIDReport len=%zu\n", payload_len);
            return write_link_ack_only(state, rx_seq);
        default:
            fprintf(stderr, "[iap2-mini] ignoring unsupported link msg 0x%04x\n", msg_id);
            return write_link_ack_only(state, rx_seq);
    }

    if (write_link_reply(state, rx_seq, reply, reply_len, msg_id) < 0) {
        free(reply);
        return -1;
    }
    fprintf(stderr, "[iap2-mini] -> link 0x%04x seq=%u sid=%u len=%zu\n",
            msg_id, state->last_tx_seq, state->control_sid, reply_len);
    free(reply);
    return 0;
}

static int loop_link_messages_mode(int initiator) {
    struct link_state state;
    memset(&state, 0, sizeof(state));
    state.control_sid = IAP2_SID_CTL;

    if (initiator) {
        fprintf(stderr, "[iap2-mini] -> link SYN (client mode)\n");
        if (write_link_syn(&state) < 0) {
            perror("write link SYN");
            return 1;
        }
    }

    for (;;) {
        uint8_t header[9];
        uint16_t start;
        uint16_t total;
        uint8_t ctl;
        uint8_t seq;
        uint8_t sid;
        uint8_t *payload = NULL;
        size_t payload_len = 0;
        uint8_t payload_cksum = 0;
        int rc;

        rc = read_exact_fd(STDIN_FILENO, header, sizeof(header));
        if (rc == 1) {
            return 0;
        }
        if (rc < 0) {
            perror("read link header");
            return 1;
        }

        start = (uint16_t)((header[0] << 8) | header[1]);
        total = (uint16_t)((header[2] << 8) | header[3]);
        ctl = header[4];
        seq = header[5];
        sid = header[7];
        if (start != IAP2_RAW_SOF || total < 9) {
            fprintf(stderr, "[iap2-mini] bad link header start=0x%04x len=%u\n", start, total);
            return 1;
        }
        if (iap2_cksum(header, 8) != header[8]) {
            fprintf(stderr, "[iap2-mini] bad link header checksum\n");
            return 1;
        }

        if (total > 9) {
            payload_len = (size_t)total - 10;
            payload = calloc(1, payload_len + 1);
            if (!payload) {
                perror("calloc");
                return 1;
            }
            rc = read_exact_fd(STDIN_FILENO, payload, payload_len);
            if (rc != 0) {
                perror("read link payload");
                free(payload);
                return 1;
            }
            rc = read_exact_fd(STDIN_FILENO, &payload_cksum, 1);
            if (rc != 0) {
                perror("read link payload checksum");
                free(payload);
                return 1;
            }
            if (iap2_cksum(payload, payload_len) != payload_cksum) {
                fprintf(stderr, "[iap2-mini] bad link payload checksum\n");
                free(payload);
                return 1;
            }
        }

        if (ctl & IAP2_CTL_SYN) {
            fprintf(stderr, "[iap2-mini] <- link SYN ctl=0x%02x seq=%u\n", ctl, seq);
            if (payload_len >= 13 && state.control_sid == IAP2_SID_CTL) {
                uint8_t num_sessions = payload[10];
                if (num_sessions >= 1) {
                    state.control_sid = payload[11];
                    fprintf(stderr, "[iap2-mini] link sync: negotiated control sid=%u\n",
                            state.control_sid);
                }
            }
            free(payload);
            if (ctl & IAP2_CTL_ACK) {
                if (write_link_ack_only(&state, seq) < 0) {
                    return 1;
                }
                if (initiator) {
                    continue;
                }
                return 0;
            }
            if (write_link_synack(&state, seq) < 0) {
                return 1;
            }
            continue;
        }

        if (ctl & IAP2_CTL_EAK) {
            size_t i;
            fprintf(stderr, "[iap2-mini] <- link EAK sid=%u len=%zu\n", sid, payload_len);
            if (write_link_ack_only(&state, seq) < 0) {
                free(payload);
                return 1;
            }
            for (i = 0; i < payload_len; ++i) {
                uint8_t need_seq = payload[i];
                fprintf(stderr, "[iap2-mini] EAK requests seq=%u\n", need_seq);
                if (state.last_tx_valid && need_seq == state.last_tx_seq) {
                    if (write_link_reply_seq(&state, state.last_tx_seq, seq,
                                             state.last_tx_payload, state.last_tx_payload_len,
                                             state.last_tx_msg_id, 0) < 0) {
                        free(payload);
                        return 1;
                    }
                    fprintf(stderr, "[iap2-mini] retransmit link 0x%04x seq=%u sid=%u len=%zu\n",
                            state.last_tx_msg_id, state.last_tx_seq, state.control_sid,
                            state.last_tx_payload_len);
                }
            }
            free(payload);
            continue;
        }

        if (payload_len > 0 && state.control_sid == IAP2_SID_CTL && sid != IAP2_SID_CTL) {
            state.control_sid = sid;
            fprintf(stderr, "[iap2-mini] adopting control sid=%u from first payload packet\n",
                    state.control_sid);
        }

        if (payload_len >= 6 && sid == state.control_sid) {
            uint16_t csm = (uint16_t)((payload[0] << 8) | payload[1]);
            uint16_t csm_total = (uint16_t)((payload[2] << 8) | payload[3]);
            uint16_t msg_id = (uint16_t)((payload[4] << 8) | payload[5]);
            if (csm != IAP2_CSM_START || csm_total > payload_len || csm_total < 6) {
                fprintf(stderr, "[iap2-mini] malformed link control payload\n");
                free(payload);
                return 1;
            }
            fprintf(stderr, "[iap2-mini] <- link ctrl seq=%u sid=%u msg=0x%04x len=%zu\n",
                    seq, sid, msg_id, payload_len);
            if (state.last_rx_ctrl_valid &&
                state.last_rx_ctrl_seq == seq &&
                state.last_rx_ctrl_msg_id == msg_id) {
                fprintf(stderr, "[iap2-mini] duplicate link ctrl seq=%u msg=0x%04x\n",
                        seq, msg_id);
                if (state.last_tx_valid &&
                    write_link_reply_seq(&state, state.last_tx_seq, seq,
                                         state.last_tx_payload, state.last_tx_payload_len,
                                         state.last_tx_msg_id, 0) == 0) {
                    fprintf(stderr, "[iap2-mini] retransmit cached link 0x%04x seq=%u sid=%u len=%zu\n",
                            state.last_tx_msg_id, state.last_tx_seq, state.control_sid,
                            state.last_tx_payload_len);
                }
                free(payload);
                continue;
            }
            state.last_rx_ctrl_seq = seq;
            state.last_rx_ctrl_msg_id = msg_id;
            state.last_rx_ctrl_valid = 1;
            rc = handle_link_control_msg(&state, seq, msg_id, payload + 6, csm_total - 6);
            free(payload);
            if (rc != 0) {
                return 1;
            }
            continue;
        }

        if (payload_len > 0) {
            char preview[193];
            size_t show = payload_len < 48 ? payload_len : 48;
            hex_preview_bytes(payload, show, preview, sizeof(preview));
            fprintf(stderr,
                    "[iap2-mini] ignoring non-control link packet ctl=0x%02x seq=%u sid=%u len=%zu preview=%s\n",
                    ctl, seq, sid, payload_len, preview);
        } else {
            fprintf(stderr,
                    "[iap2-mini] ignoring non-control link packet ctl=0x%02x seq=%u sid=%u len=0\n",
                    ctl, seq, sid);
        }
        free(payload);
    }
}

static int loop_link_messages(void) {
    return loop_link_messages_mode(0);
}

static int rfcomm_listen_socket(int channel) {
    int fd;
    struct sockaddr_rc_local addr;

    fd = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/RFCOMM)");
        return -1;
    }
    bt_require_high_security(fd, "RFCOMM listen");

    memset(&addr, 0, sizeof(addr));
    addr.rc_family = AF_BLUETOOTH;
    addr.rc_channel = (uint8_t)channel;
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind(RFCOMM)");
        close(fd);
        return -1;
    }
    if (listen(fd, 1) < 0) {
        perror("listen(RFCOMM)");
        close(fd);
        return -1;
    }
    fprintf(stderr, "[iap2-mini] RFCOMM listen ch=%d\n", channel);
    return fd;
}

static int serve_rfcomm_once(int channel) {
    int listen_fd;
    int conn_fd;
    socklen_t peer_len;
    struct sockaddr_rc_local peer;
    char peer_str[18];

    listen_fd = rfcomm_listen_socket(channel);
    if (listen_fd < 0) {
        return 1;
    }

    memset(&peer, 0, sizeof(peer));
    peer_len = sizeof(peer);
    conn_fd = accept(listen_fd, (struct sockaddr *)&peer, &peer_len);
    if (conn_fd < 0) {
        perror("accept(RFCOMM)");
        close(listen_fd);
        return 1;
    }
    bt_require_high_security(conn_fd, "RFCOMM accepted");
    close(listen_fd);

    bdaddr_to_str(&peer.rc_bdaddr, peer_str);
    fprintf(stderr, "[iap2-mini] RFCOMM accepted peer=%s ch=%u\n",
            peer_str, (unsigned)peer.rc_channel);

    if (dup2(conn_fd, STDIN_FILENO) < 0 || dup2(conn_fd, STDOUT_FILENO) < 0) {
        perror("dup2(RFCOMM)");
        close(conn_fd);
        return 1;
    }
    if (conn_fd > STDERR_FILENO) {
        close(conn_fd);
    }

    return loop_link_messages();
}

static int serve_rfcomm_forever(int channel) {
    for (;;) {
        int rc = serve_rfcomm_once(channel);
        if (rc != 0) {
            sleep(1);
        }
    }
    return 0;
}

static int rfcomm_client_connect(const char *addr_str, int channel) {
    int fd;
    struct sockaddr_rc_local addr;
    char peer_str[18];

    fd = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/RFCOMM client)");
        return -1;
    }
    bt_require_high_security(fd, "RFCOMM client");
    memset(&addr, 0, sizeof(addr));
    addr.rc_family = AF_BLUETOOTH;
    addr.rc_channel = (uint8_t)channel;
    if (str_to_bdaddr_local(addr_str, &addr.rc_bdaddr) < 0) {
        perror("str_to_bdaddr_local");
        close(fd);
        return -1;
    }
    bdaddr_to_str(&addr.rc_bdaddr, peer_str);
    fprintf(stderr, "[iap2-mini] RFCOMM connect peer=%s ch=%d\n", peer_str, channel);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("connect(RFCOMM client)");
        close(fd);
        return -1;
    }
    return fd;
}

static int l2cap_listen_socket(uint16_t psm) {
    int fd;
    struct sockaddr_l2_local addr;

    fd = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/L2CAP)");
        return -1;
    }
    bt_require_high_security(fd, "L2CAP listen");

    memset(&addr, 0, sizeof(addr));
    addr.l2_family = AF_BLUETOOTH;
    addr.l2_psm = psm;
    if (bind(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("bind(L2CAP)");
        close(fd);
        return -1;
    }
    if (listen(fd, 1) < 0) {
        perror("listen(L2CAP)");
        close(fd);
        return -1;
    }
    fprintf(stderr, "[iap2-mini] L2CAP listen psm=0x%04x\n", psm);
    return fd;
}

static int l2cap_client_connect(const char *addr_str, uint16_t psm) {
    int fd;
    struct sockaddr_l2_local addr;
    char peer_str[18];

    fd = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/L2CAP client)");
        return -1;
    }
    bt_require_high_security(fd, "L2CAP client");
    memset(&addr, 0, sizeof(addr));
    addr.l2_family = AF_BLUETOOTH;
    addr.l2_psm = psm;
    if (str_to_bdaddr_local(addr_str, &addr.l2_bdaddr) < 0) {
        perror("str_to_bdaddr_local");
        close(fd);
        return -1;
    }
    bdaddr_to_str(&addr.l2_bdaddr, peer_str);
    fprintf(stderr, "[iap2-mini] L2CAP connect peer=%s psm=0x%04x\n", peer_str, psm);
    if (connect(fd, (struct sockaddr *)&addr, sizeof(addr)) < 0) {
        perror("connect(L2CAP client)");
        close(fd);
        return -1;
    }
    return fd;
}

static int serve_l2cap_once(uint16_t psm) {
    int listen_fd;
    int conn_fd;
    socklen_t peer_len;
    struct sockaddr_l2_local peer;
    char peer_str[18];

    listen_fd = l2cap_listen_socket(psm);
    if (listen_fd < 0) {
        return 1;
    }

    memset(&peer, 0, sizeof(peer));
    peer_len = sizeof(peer);
    conn_fd = accept(listen_fd, (struct sockaddr *)&peer, &peer_len);
    if (conn_fd < 0) {
        perror("accept(L2CAP)");
        close(listen_fd);
        return 1;
    }
    bt_require_high_security(conn_fd, "L2CAP accepted");
    close(listen_fd);

    bdaddr_to_str(&peer.l2_bdaddr, peer_str);
    fprintf(stderr, "[iap2-mini] L2CAP accepted peer=%s psm=0x%04x cid=0x%04x\n",
            peer_str, peer.l2_psm, peer.l2_cid);
    {
        int rc = 0;
        for (;;) {
            uint8_t packet[1029];
            uint8_t params[1024];
            uint8_t pdu_id;
            uint16_t txn_id;
            uint16_t param_len;
            char preview[193];
            ssize_t n;

            n = read(conn_fd, packet, sizeof(packet));
            if (n == 0) {
                break;
            }
            if (n < 0) {
                perror("read SDP packet");
                rc = 1;
                break;
            }
            if (n < 5) {
                hex_preview_bytes(packet, (size_t)n, preview, sizeof(preview));
                fprintf(stderr, "[iap2-mini] SDP short packet len=%zd preview=%s\n", n, preview);
                rc = 1;
                break;
            }
            pdu_id = packet[0];
            txn_id = (uint16_t)((packet[1] << 8) | packet[2]);
            param_len = (uint16_t)((packet[3] << 8) | packet[4]);
            fprintf(stderr,
                    "[iap2-mini] SDP rx hdr pdu=0x%02x(%s) txn=0x%04x param_len=%u\n",
                    pdu_id, sdp_pdu_name(pdu_id), txn_id, param_len);
            if (param_len > sizeof(params)) {
                fprintf(stderr,
                        "[iap2-mini] SDP param_len too large=%u cap=%zu\n",
                        param_len, sizeof(params));
                sdp_write_error_fd(conn_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
                rc = 1;
                break;
            }
            if ((size_t)n != (size_t)(5 + param_len)) {
                size_t body_len = (size_t)n > 5 ? (size_t)n - 5 : 0;
                if (body_len > sizeof(params)) {
                    body_len = sizeof(params);
                }
                if (body_len > 0) {
                    memcpy(params, packet + 5, body_len);
                    hex_preview_bytes(params, body_len < 48 ? body_len : 48, preview, sizeof(preview));
                } else {
                    preview[0] = '\0';
                }
                fprintf(stderr,
                        "[iap2-mini] SDP packet size mismatch got=%zd expected=%u body_preview=%s\n",
                        n, (unsigned)(5 + param_len), body_len > 0 ? preview : "<none>");
                rc = 1;
                break;
            }
            if (param_len > 0) {
                memcpy(params, packet + 5, param_len);
            }
            hex_preview_bytes(params, param_len < 48 ? param_len : 48, preview, sizeof(preview));
            fprintf(stderr, "[iap2-mini] SDP rx params len=%u preview=%s\n",
                    param_len, param_len > 0 ? preview : "<empty>");
            if (sdp_handle_request_fd(conn_fd, pdu_id, txn_id, params, param_len) < 0) {
                perror("write SDP response");
                rc = 1;
                break;
            }
            fprintf(stderr, "[iap2-mini] SDP tx ok pdu=0x%02x(%s) txn=0x%04x\n",
                    pdu_id, sdp_pdu_name(pdu_id), txn_id);
        }
        close(conn_fd);
        return rc;
    }
}

static int serve_l2cap_forever(uint16_t psm) {
    for (;;) {
        int rc = serve_l2cap_once(psm);
        if (rc != 0) {
            sleep(1);
        }
    }
    return 0;
}

static int sdp_extract_rfcomm_channel_from_pdl(const uint8_t *value, size_t value_len) {
    uint8_t type;
    size_t hdr_len;
    size_t val_len;
    size_t off;

    if (sdp_de_parse_header(value, value_len, &type, &hdr_len, &val_len) < 0 || type != 6) {
        return -1;
    }
    off = hdr_len;
    while (off < hdr_len + val_len) {
        const uint8_t *elem = value + off;
        size_t remain = hdr_len + val_len - off;
        uint8_t et;
        size_t eh;
        size_t ev;
        size_t sub_off;
        uint16_t proto_uuid = 0;

        if (sdp_de_parse_header(elem, remain, &et, &eh, &ev) < 0 || et != 6) {
            return -1;
        }
        sub_off = eh;
        while (sub_off < eh + ev) {
            const uint8_t *sub = elem + sub_off;
            size_t sub_remain = eh + ev - sub_off;
            uint8_t st;
            size_t sh;
            size_t sv;
            if (sdp_de_parse_header(sub, sub_remain, &st, &sh, &sv) < 0) {
                return -1;
            }
            if (proto_uuid == 0 && st == 3 && sv == 2) {
                proto_uuid = (uint16_t)((sub[sh] << 8) | sub[sh + 1]);
            } else if (proto_uuid == 0x0003 && st == 1 && sv == 1) {
                return sub[sh];
            }
            sub_off += sh + sv;
        }
        off += eh + ev;
    }
    return -1;
}

static int sdp_extract_rfcomm_channel_from_attr_list(const uint8_t *attr_list, size_t attr_list_len) {
    uint8_t type;
    size_t hdr_len;
    size_t val_len;
    size_t off;

    if (sdp_de_parse_header(attr_list, attr_list_len, &type, &hdr_len, &val_len) < 0 || type != 6) {
        return -1;
    }
    off = hdr_len;
    while (off < hdr_len + val_len) {
        const uint8_t *id_de = attr_list + off;
        size_t remain = hdr_len + val_len - off;
        uint8_t id_type;
        size_t id_hdr;
        size_t id_val;
        const uint8_t *value_de;
        uint8_t value_type;
        size_t value_hdr;
        size_t value_val;
        uint16_t attr_id;

        if (sdp_de_parse_header(id_de, remain, &id_type, &id_hdr, &id_val) < 0 || id_type != 1 || id_val != 2) {
            return -1;
        }
        attr_id = (uint16_t)((id_de[id_hdr] << 8) | id_de[id_hdr + 1]);
        off += id_hdr + id_val;
        if (off >= hdr_len + val_len) {
            return -1;
        }
        value_de = attr_list + off;
        remain = hdr_len + val_len - off;
        if (sdp_de_parse_header(value_de, remain, &value_type, &value_hdr, &value_val) < 0) {
            return -1;
        }
        if (attr_id == 0x0004) {
            return sdp_extract_rfcomm_channel_from_pdl(value_de, value_hdr + value_val);
        }
        off += value_hdr + value_val;
    }
    return -1;
}

static int sdp_discover_rfcomm_channel(const char *addr_str, const uint8_t uuid[16]) {
    int fd;
    uint8_t req[64];
    uint8_t rsp[2048];
    size_t req_len = 0;
    uint16_t txn_id = 1;
    uint16_t param_len;
    uint16_t attr_bytes;
    int channel = -1;

    fd = l2cap_client_connect(addr_str, L2CAP_PSM_SDP);
    if (fd < 0) {
        return -1;
    }

    req[req_len++] = SDP_PDU_SERVICE_SEARCH_ATTR_REQUEST;
    req[req_len++] = (uint8_t)(txn_id >> 8);
    req[req_len++] = (uint8_t)(txn_id & 0xff);
    req_len += 2;

    req[req_len++] = 0x35;
    req[req_len++] = 0x11;
    req[req_len++] = 0x1C;
    memcpy(req + req_len, uuid, 16);
    req_len += 16;
    req[req_len++] = 0x02;
    req[req_len++] = 0x00;
    req[req_len++] = 0x35;
    req[req_len++] = 0x05;
    req[req_len++] = 0x0A;
    req[req_len++] = 0x00;
    req[req_len++] = 0x00;
    req[req_len++] = 0xFF;
    req[req_len++] = 0xFF;
    req[req_len++] = 0x00;

    req[3] = (uint8_t)(((req_len - 5) >> 8) & 0xff);
    req[4] = (uint8_t)((req_len - 5) & 0xff);

    if (write_all_fd(fd, req, req_len) < 0) {
        perror("write SDP query");
        close(fd);
        return -1;
    }
    {
        uint8_t rsp_packet[705];
        ssize_t n = read(fd, rsp_packet, sizeof(rsp_packet));
        if (n <= 0) {
            if (n < 0) {
                perror("read SDP rsp packet");
            } else {
                errno = 0;
                perror("read SDP rsp packet");
            }
            close(fd);
            return -1;
        }
        if (n < 5) {
            errno = EPROTO;
            perror("read SDP rsp short packet");
            close(fd);
            return -1;
        }
        if (rsp_packet[0] != SDP_PDU_SERVICE_SEARCH_ATTR_RESP) {
            fprintf(stderr, "[iap2-mini] unexpected SDP rsp pdu=0x%02x\n", rsp_packet[0]);
            close(fd);
            return -1;
        }
        param_len = (uint16_t)((rsp_packet[3] << 8) | rsp_packet[4]);
        if ((size_t)n != (size_t)(5 + param_len)) {
            errno = EPROTO;
            perror("read SDP rsp packet size mismatch");
            close(fd);
            return -1;
        }
        if (param_len > sizeof(rsp)) {
            errno = EOVERFLOW;
            perror("SDP response too large");
            close(fd);
            return -1;
        }
        if (param_len > 0) {
            memcpy(rsp, rsp_packet + 5, param_len);
        }
    }
    close(fd);

    if (param_len < 3) {
        errno = EPROTO;
        perror("SDP short response");
        return -1;
    }
    attr_bytes = (uint16_t)((rsp[0] << 8) | rsp[1]);
    if ((size_t)(2 + attr_bytes + 1) > param_len) {
        errno = EPROTO;
        perror("SDP invalid attr byte count");
        return -1;
    }
    channel = sdp_extract_rfcomm_channel_from_attr_list(rsp + 2, attr_bytes);
    fprintf(stderr, "[iap2-mini] SDP discovered RFCOMM channel=%d for peer=%s\n", channel, addr_str);
    return channel;
}

static int run_cafe_connect(int hci_dev, const char *addr_str) {
    int channel;
    int fd;
    uint16_t handle = 0;
    pid_t watch_pid = -1;

    if (getenv("CARTHING_IAP2_SKIP_ACL_CREATE") == NULL) {
        if (hci_create_acl_link(hci_dev, addr_str, &handle) != 0) {
            return 1;
        }
        fprintf(stderr, "[iap2-mini] waiting for classic ACL settle peer=%s handle=0x%04x\n",
                addr_str, handle);
        sleep(2);
    }
    watch_pid = hci_spawn_peer_watch(hci_dev, addr_str, handle, 12);

    channel = sdp_discover_rfcomm_channel(addr_str, SDP_UUID_CAFE);
    if (channel <= 0) {
        fprintf(stderr, "[iap2-mini] CAFE discovery failed, trying CAFF fallback\n");
        channel = sdp_discover_rfcomm_channel(addr_str, SDP_UUID_CAFF);
    }
    if (channel <= 0) {
        channel = 1;
        fprintf(stderr, "[iap2-mini] SDP fallback channel=%d\n", channel);
    }

    fd = rfcomm_client_connect(addr_str, channel);
    if (fd < 0) {
        if (watch_pid > 0) {
            waitpid(watch_pid, NULL, 0);
        }
        return 1;
    }
    if (dup2(fd, STDIN_FILENO) < 0 || dup2(fd, STDOUT_FILENO) < 0) {
        perror("dup2(RFCOMM client)");
        close(fd);
        if (watch_pid > 0) {
            waitpid(watch_pid, NULL, 0);
        }
        return 1;
    }
    if (fd > STDERR_FILENO) {
        close(fd);
    }
    if (watch_pid > 0) {
        kill(watch_pid, SIGTERM);
        waitpid(watch_pid, NULL, 0);
    }
    return loop_link_messages_mode(1);
}

static int loop_raw_messages(void) {
    int auth_ok = 0;

    for (;;) {
        uint8_t header[6];
        uint16_t start;
        uint16_t total;
        uint16_t msg_id;
        uint8_t *payload = NULL;
        size_t payload_len = 0;
        int rc;

        rc = read_exact_fd(STDIN_FILENO, header, sizeof(header));
        if (rc == 1) {
            return 0;
        }
        if (rc < 0) {
            perror("read raw header");
            return 1;
        }

        start = (uint16_t)((header[0] << 8) | header[1]);
        total = (uint16_t)((header[2] << 8) | header[3]);
        msg_id = (uint16_t)((header[4] << 8) | header[5]);
        if (start != IAP2_RAW_SOF || total < 6) {
            fprintf(stderr, "[iap2-mini] bad raw header start=0x%04x len=%u\n", start, total);
            return 1;
        }

        payload_len = (size_t)total - 6;
        if (payload_len > 0) {
            payload = calloc(1, payload_len);
            if (!payload) {
                perror("calloc");
                return 1;
            }
            rc = read_exact_fd(STDIN_FILENO, payload, payload_len);
            if (rc != 0) {
                perror("read raw payload");
                free(payload);
                return 1;
            }
        }

        rc = handle_message(msg_id, payload, payload_len, &auth_ok, OUTPUT_RAW);
        free(payload);
        if (rc != 0) {
            return 1;
        }
    }
}

static int loop_sdp_messages(void) {
    for (;;) {
        uint8_t hdr[5];
        uint8_t params[1024];
        uint16_t txn_id;
        uint16_t param_len;
        int rc;

        rc = read_exact_fd(STDIN_FILENO, hdr, sizeof(hdr));
        if (rc == 1) {
            return 0;
        }
        if (rc < 0) {
            perror("read sdp header");
            return 1;
        }
        txn_id = (uint16_t)((hdr[1] << 8) | hdr[2]);
        param_len = (uint16_t)((hdr[3] << 8) | hdr[4]);
        if (param_len > sizeof(params)) {
            sdp_write_error_fd(STDOUT_FILENO, txn_id, SDP_ERR_INVALID_PDU_SIZE);
            return 1;
        }
        rc = read_exact_fd(STDIN_FILENO, params, param_len);
        if (rc != 0) {
            perror("read sdp params");
            return 1;
        }
        if (sdp_handle_request_fd(STDOUT_FILENO, hdr[0], txn_id, params, param_len) < 0) {
            perror("write sdp response");
            return 1;
        }
    }
}

static int run_transport_daemon(int hci_dev, int channel, uint16_t psm, uint8_t scan_enable,
                                uint32_t class_of_dev) {
    static const uint8_t classic_event_mask[8] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x3f };
    const char *eir_name = iap2_local_name();
    pid_t sdp_pid;
    pid_t rf_pid;
    pid_t ssp_pid;
    pid_t scan_pid;
    int status;

    if (hci_dev_up(hci_dev) != 0) {
        return 1;
    }
    if (hci_write_local_name(hci_dev, eir_name) != 0) {
        return 1;
    }
    if (hci_write_class_of_dev(hci_dev, class_of_dev) != 0) {
        return 1;
    }
    if (hci_write_inquiry_mode(hci_dev, 0x02) != 0) {
        return 1;
    }
    if (hci_write_eir_iap2(hci_dev, eir_name) != 0) {
        return 1;
    }
    if (hci_write_event_mask(hci_dev, classic_event_mask) != 0) {
        return 1;
    }
    if (hci_write_simple_pairing_mode(hci_dev, 1) != 0) {
        return 1;
    }
    if (hci_write_scan_enable(hci_dev, scan_enable) != 0) {
        return 1;
    }

    ssp_pid = fork();
    if (ssp_pid < 0) {
        perror("fork ssp");
        return 1;
    }
    if (ssp_pid == 0) {
        _exit(hci_ssp_agent_loop(hci_dev));
    }

    scan_pid = fork();
    if (scan_pid < 0) {
        perror("fork scan-watchdog");
        kill(ssp_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        return 1;
    }
    if (scan_pid == 0) {
        _exit(hci_scan_watchdog_loop(hci_dev, scan_enable));
    }

    sdp_pid = fork();
    if (sdp_pid < 0) {
        perror("fork sdp");
        kill(ssp_pid, SIGTERM);
        kill(scan_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        waitpid(scan_pid, NULL, 0);
        return 1;
    }
    if (sdp_pid == 0) {
        _exit(serve_l2cap_forever(psm));
    }

    rf_pid = fork();
    if (rf_pid < 0) {
        perror("fork rfcomm");
        kill(ssp_pid, SIGTERM);
        kill(scan_pid, SIGTERM);
        kill(sdp_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        waitpid(scan_pid, NULL, 0);
        waitpid(sdp_pid, NULL, 0);
        return 1;
    }
    if (rf_pid == 0) {
        _exit(serve_rfcomm_forever(channel));
    }

    fprintf(stderr,
            "[iap2-mini] transport daemon up: name=%s class=0x%06x scan=0x%02x ssp=on sdp_psm=0x%04x rfcomm_ch=%d\n",
            eir_name, class_of_dev & 0xffffffu, scan_enable, psm, channel);

    if (wait(&status) > 0) {
        kill(ssp_pid, SIGTERM);
        kill(scan_pid, SIGTERM);
        kill(sdp_pid, SIGTERM);
        kill(rf_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        waitpid(scan_pid, NULL, 0);
        waitpid(sdp_pid, NULL, 0);
        waitpid(rf_pid, NULL, 0);
    }
    return 0;
}

static int run_transport_active_connect(int hci_dev, int channel, uint16_t psm, uint8_t scan_enable,
                                        uint32_t class_of_dev, const char *peer_addr) {
    static const uint8_t classic_event_mask[8] = { 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x3f };
    const char *eir_name = iap2_local_name();
    pid_t sdp_pid;
    pid_t rf_pid;
    pid_t ssp_pid;
    pid_t scan_pid;
    int rc;

    if (hci_dev_up(hci_dev) != 0) {
        return 1;
    }
    if (hci_write_local_name(hci_dev, eir_name) != 0) {
        return 1;
    }
    if (hci_write_class_of_dev(hci_dev, class_of_dev) != 0) {
        return 1;
    }
    if (hci_write_inquiry_mode(hci_dev, 0x02) != 0) {
        return 1;
    }
    if (hci_write_eir_iap2(hci_dev, eir_name) != 0) {
        return 1;
    }
    if (hci_write_event_mask(hci_dev, classic_event_mask) != 0) {
        return 1;
    }
    if (hci_write_simple_pairing_mode(hci_dev, 1) != 0) {
        return 1;
    }
    if (hci_write_scan_enable(hci_dev, scan_enable) != 0) {
        return 1;
    }

    ssp_pid = fork();
    if (ssp_pid < 0) {
        perror("fork ssp");
        return 1;
    }
    if (ssp_pid == 0) {
        _exit(hci_ssp_agent_loop(hci_dev));
    }

    scan_pid = fork();
    if (scan_pid < 0) {
        perror("fork scan-watchdog");
        kill(ssp_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        return 1;
    }
    if (scan_pid == 0) {
        _exit(hci_scan_watchdog_loop(hci_dev, scan_enable));
    }

    sdp_pid = fork();
    if (sdp_pid < 0) {
        perror("fork sdp");
        kill(ssp_pid, SIGTERM);
        kill(scan_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        waitpid(scan_pid, NULL, 0);
        return 1;
    }
    if (sdp_pid == 0) {
        _exit(serve_l2cap_forever(psm));
    }

    rf_pid = fork();
    if (rf_pid < 0) {
        perror("fork rfcomm");
        kill(ssp_pid, SIGTERM);
        kill(scan_pid, SIGTERM);
        kill(sdp_pid, SIGTERM);
        waitpid(ssp_pid, NULL, 0);
        waitpid(scan_pid, NULL, 0);
        waitpid(sdp_pid, NULL, 0);
        return 1;
    }
    if (rf_pid == 0) {
        _exit(serve_rfcomm_forever(channel));
    }

    fprintf(stderr,
            "[iap2-mini] transport-active up: name=%s class=0x%06x scan=0x%02x ssp=on sdp_psm=0x%04x rfcomm_ch=%d peer=%s\n",
            eir_name, class_of_dev & 0xffffffu, scan_enable, psm, channel, peer_addr);
    sleep(1);
    rc = run_cafe_connect(hci_dev, peer_addr);

    kill(ssp_pid, SIGTERM);
    kill(scan_pid, SIGTERM);
    kill(sdp_pid, SIGTERM);
    kill(rf_pid, SIGTERM);
    waitpid(ssp_pid, NULL, 0);
    waitpid(scan_pid, NULL, 0);
    waitpid(sdp_pid, NULL, 0);
    waitpid(rf_pid, NULL, 0);
    return rc;
}

static void usage(FILE *out) {
    fprintf(out,
        "usage:\n"
        "  carthing-iap2-mini loop\n"
        "  carthing-iap2-mini raw-loop\n"
        "  carthing-iap2-mini link-loop\n"
        "  carthing-iap2-mini sdp-loop\n"
        "  carthing-iap2-mini rfcomm-listen\n"
        "  carthing-iap2-mini sdp-listen\n"
        "  carthing-iap2-mini cafe-connect <AA:BB:CC:DD:EE:FF>\n"
        "  carthing-iap2-mini transport-daemon\n"
        "  carthing-iap2-mini transport-active <AA:BB:CC:DD:EE:FF>\n"
        "  carthing-iap2-mini hci-read-bdaddr\n"
        "  carthing-iap2-mini hci-inquiry\n"
        "  carthing-iap2-mini hci-create-acl <AA:BB:CC:DD:EE:FF>\n"
        "  carthing-iap2-mini hci-remote-name <AA:BB:CC:DD:EE:FF>\n"
        "  carthing-iap2-mini hci-read-name\n"
        "  carthing-iap2-mini hci-write-name <name>\n"
        "  carthing-iap2-mini hci-read-class\n"
        "  carthing-iap2-mini hci-write-class <0xNNNNNN>\n"
        "  carthing-iap2-mini hci-read-scan\n"
        "  carthing-iap2-mini hci-write-scan <off|page|both|0xNN>\n"
        "  carthing-iap2-mini identify\n"
        "  carthing-iap2-mini identify-raw\n"
        "\n"
        "env:\n"
        "  CARTHING_MFI_HELPER=/path/to/carthing-mfi-probe\n"
        "  CARTHING_IAP2_RFCOMM_CHANNEL=3\n"
        "  CARTHING_IAP2_L2CAP_PSM=0x0001\n"
        "  CARTHING_IAP2_HCI_DEV=0\n"
        "  CARTHING_IAP2_LOCAL_NAME='CarThing iAP2'\n"
        "  CARTHING_IAP2_CLASS_OF_DEVICE=0x240420\n"
        "  CARTHING_IAP2_SKIP_ACL_CREATE=1\n"
        "  CARTHING_IAP2_ID_MSGSET_SENT_IDS='0xEA02,0x40C8'\n"
        "  CARTHING_IAP2_ID_MSGSET_RECV_IDS='0xEA00,0x4800'\n");
}

int main(int argc, char **argv) {
    int hci_dev = env_u8("CARTHING_IAP2_HCI_DEV", HCI_DEV_DEFAULT, 0, 255);
    signal(SIGPIPE, SIG_IGN);

    if (argc < 2 || argc > 3) {
        usage(stderr);
        return 2;
    }

    if (strcmp(argv[1], "loop") == 0) {
        return loop_control_messages();
    }

    if (strcmp(argv[1], "raw-loop") == 0) {
        return loop_raw_messages();
    }

    if (strcmp(argv[1], "link-loop") == 0) {
        return loop_link_messages();
    }

    if (strcmp(argv[1], "rfcomm-listen") == 0) {
        return serve_rfcomm_once(env_u8("CARTHING_IAP2_RFCOMM_CHANNEL",
                                        RFCOMM_CHANNEL_DEFAULT, 1, 30));
    }

    if (strcmp(argv[1], "sdp-loop") == 0) {
        return loop_sdp_messages();
    }

    if (strcmp(argv[1], "sdp-listen") == 0) {
        return serve_l2cap_once((uint16_t)env_u8("CARTHING_IAP2_L2CAP_PSM",
                                                 L2CAP_PSM_SDP, 1, 0xffff));
    }

    if (strcmp(argv[1], "cafe-connect") == 0) {
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        return run_cafe_connect(hci_dev, argv[2]);
    }

    if (strcmp(argv[1], "transport-daemon") == 0) {
        return run_transport_daemon(hci_dev,
                                    env_u8("CARTHING_IAP2_RFCOMM_CHANNEL",
                                           RFCOMM_CHANNEL_DEFAULT, 1, 30),
                                    (uint16_t)env_u8("CARTHING_IAP2_L2CAP_PSM",
                                                     L2CAP_PSM_SDP, 1, 0xffff),
                                    0x03,
                                    env_u24("CARTHING_IAP2_CLASS_OF_DEVICE",
                                            CLASS_OF_DEVICE_CAR_AUDIO));
    }

    if (strcmp(argv[1], "transport-active") == 0) {
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        return run_transport_active_connect(hci_dev,
                                            env_u8("CARTHING_IAP2_RFCOMM_CHANNEL",
                                                   RFCOMM_CHANNEL_DEFAULT, 1, 30),
                                            (uint16_t)env_u8("CARTHING_IAP2_L2CAP_PSM",
                                                             L2CAP_PSM_SDP, 1, 0xffff),
                                            0x03,
                                            env_u24("CARTHING_IAP2_CLASS_OF_DEVICE",
                                                    CLASS_OF_DEVICE_CAR_AUDIO),
                                            argv[2]);
    }

    if (strcmp(argv[1], "hci-read-bdaddr") == 0) {
        return hci_read_bd_addr(hci_dev);
    }

    if (strcmp(argv[1], "hci-inquiry") == 0) {
        return hci_inquiry_scan(hci_dev, 0x08);
    }

    if (strcmp(argv[1], "hci-create-acl") == 0) {
        uint16_t handle = 0;
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        if (hci_create_acl_link(hci_dev, argv[2], &handle) != 0) {
            return 1;
        }
        printf("0x%04x\n", handle);
        return 0;
    }

    if (strcmp(argv[1], "hci-remote-name") == 0) {
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        return hci_remote_name_request(hci_dev, argv[2]);
    }

    if (strcmp(argv[1], "hci-read-name") == 0) {
        return hci_read_local_name(hci_dev);
    }

    if (strcmp(argv[1], "hci-write-name") == 0) {
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        return hci_write_local_name(hci_dev, argv[2]);
    }

    if (strcmp(argv[1], "hci-read-class") == 0) {
        return hci_read_class_of_dev(hci_dev);
    }

    if (strcmp(argv[1], "hci-write-class") == 0) {
        char *end = NULL;
        unsigned long cod;
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        cod = strtoul(argv[2], &end, 0);
        if (!end || *end != '\0' || cod > 0xfffffful) {
            usage(stderr);
            return 2;
        }
        return hci_write_class_of_dev(hci_dev, (uint32_t)cod);
    }

    if (strcmp(argv[1], "hci-read-scan") == 0) {
        return hci_read_scan_enable(hci_dev);
    }

    if (strcmp(argv[1], "hci-write-scan") == 0) {
        uint8_t v;
        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        if (strcmp(argv[2], "off") == 0) v = 0x00;
        else if (strcmp(argv[2], "page") == 0) v = 0x02;
        else if (strcmp(argv[2], "both") == 0) v = 0x03;
        else v = (uint8_t)env_u8("CARTHING_IAP2_SCAN_VALUE", 0xff, 0, 255);
        if (v == 0xff && strcmp(argv[2], "off") != 0 &&
            strcmp(argv[2], "page") != 0 && strcmp(argv[2], "both") != 0) {
            char *end = NULL;
            long n = strtol(argv[2], &end, 0);
            if (!end || *end != '\0' || n < 0 || n > 255) {
                usage(stderr);
                return 2;
            }
            v = (uint8_t)n;
        }
        return hci_write_scan_enable(hci_dev, v);
    }

    if (strcmp(argv[1], "identify") == 0) {
        uint8_t buf[512];
        size_t len = 0;
        if (build_identification_params(buf, sizeof(buf), &len) < 0) {
            perror("build identification");
            return 1;
        }
        if (write_control_msg(IAP2_MSG_ID_INFO, buf, len) < 0) {
            perror("write stdout");
            return 1;
        }
        return 0;
    }

    if (strcmp(argv[1], "identify-raw") == 0) {
        uint8_t buf[512];
        size_t len = 0;
        if (build_identification_params(buf, sizeof(buf), &len) < 0) {
            perror("build identification");
            return 1;
        }
        if (write_raw_msg(IAP2_MSG_ID_INFO, buf, len) < 0) {
            perror("write stdout");
            return 1;
        }
        return 0;
    }

    usage(stderr);
    return 2;
}
