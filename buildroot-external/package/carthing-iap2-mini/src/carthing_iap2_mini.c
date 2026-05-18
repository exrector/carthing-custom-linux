#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>
#include <sys/wait.h>
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

#ifndef AF_BLUETOOTH
#define AF_BLUETOOTH 31
#endif

#ifndef BTPROTO_L2CAP
#define BTPROTO_L2CAP 0
#endif

#ifndef BTPROTO_RFCOMM
#define BTPROTO_RFCOMM 3
#endif

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

enum output_mode {
    OUTPUT_CONTROL = 0,
    OUTPUT_RAW = 1,
};

struct link_state {
    uint8_t tx_seq;
    int auth_ok;
};

static const uint8_t SDP_UUID_CAFF[16] = {
    0x00, 0x00, 0x00, 0x00, 0xde, 0xca, 0xfa, 0xde,
    0xde, 0xca, 0xde, 0xaf, 0xde, 0xca, 0xca, 0xff
};

static const uint8_t SDP_ATTR_HANDLE[] = { 0x0A, 0x00, 0x01, 0x00, 0x00 };
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
    uint8_t hdr[5];
    hdr[0] = pdu_id;
    hdr[1] = (uint8_t)(txn_id >> 8);
    hdr[2] = (uint8_t)(txn_id & 0xff);
    hdr[3] = (uint8_t)((params_len >> 8) & 0xff);
    hdr[4] = (uint8_t)(params_len & 0xff);
    if (write_all_fd(out_fd, hdr, sizeof(hdr)) < 0) return -1;
    if (params_len > 0 && write_all_fd(out_fd, params, params_len) < 0) return -1;
    return 0;
}

static int sdp_write_error_fd(int out_fd, uint16_t txn_id, uint16_t err_code) {
    uint8_t params[2] = { (uint8_t)(err_code >> 8), (uint8_t)(err_code & 0xff) };
    return sdp_write_response_fd(out_fd, SDP_PDU_ERROR_RESPONSE, txn_id, params, sizeof(params));
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
    if (*off + 4 + len > maxlen) {
        errno = ENOSPC;
        return -1;
    }
    buf[*off + 0] = (uint8_t)((type >> 8) & 0xff);
    buf[*off + 1] = (uint8_t)(type & 0xff);
    buf[*off + 2] = (uint8_t)((len >> 8) & 0xff);
    buf[*off + 3] = (uint8_t)(len & 0xff);
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

static int build_identification_params(uint8_t *buf, size_t maxlen, size_t *out_len) {
    size_t off = 0;
    char serial[64];
    uint8_t power = 0x00;
    uint8_t current[2] = {0x00, 0x64};

    read_serial(serial, sizeof(serial));

    if (append_tlv_cstr(buf, maxlen, &off, 0x0000, "Spotify Car Thing") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0001, "Car Thing") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0002, "Spotify USA Inc.") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0003, serial) < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0004, "1.0.0") < 0) return -1;
    if (append_tlv_cstr(buf, maxlen, &off, 0x0005, "1.0") < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0006, NULL, 0) < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0007, NULL, 0) < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0008, &power, 1) < 0) return -1;
    if (append_tlv(buf, maxlen, &off, 0x0009, current, sizeof(current)) < 0) return -1;

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

static int handle_message(uint16_t msg_id, const uint8_t *payload, size_t payload_len, int *auth_ok, enum output_mode mode) {
    uint8_t idbuf[512];
    size_t idlen = 0;
    uint8_t challenge[32];
    size_t challenge_len = 0;

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
            return 0;
        case IAP2_MSG_ID_REJECTED:
            fprintf(stderr, "[iap2-mini] <- 1D03 IdentificationRejected\n");
            if (payload_len >= 4) {
                uint16_t rejected = (uint16_t)((payload[2] << 8) | payload[3]);
                fprintf(stderr, "[iap2-mini] rejected param id=0x%04x\n", rejected);
            }
            return -1;
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
    return write_link_pkt(IAP2_CTL_ACK, IAP2_SID_CTL, state->tx_seq++, ack_seq, NULL, 0);
}

static int write_link_synack(struct link_state *state, uint8_t ack_seq) {
    static const uint8_t syn_payload[14] = {
        0x01, 0x07, 0x08, 0x00, 0x00, 0xFA, 0x00, 0x19,
        0x03, 0x01, 0x01, 0x00, 0x00, 0x01
    };
    return write_link_pkt(IAP2_CTL_SYN | IAP2_CTL_ACK, IAP2_SID_CTL, state->tx_seq++, ack_seq,
                          syn_payload, sizeof(syn_payload));
}

static int write_link_reply(struct link_state *state, uint8_t ack_seq, const uint8_t *payload, size_t payload_len) {
    return write_link_pkt(IAP2_CTL_ACK, IAP2_SID_CTL, state->tx_seq++, ack_seq, payload, payload_len);
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
            break;
        case IAP2_MSG_ID_ACCEPTED:
            fprintf(stderr, "[iap2-mini] <- link 1D02 IdentificationAccepted\n");
            return write_link_ack_only(state, rx_seq);
        case IAP2_MSG_ID_REJECTED:
            fprintf(stderr, "[iap2-mini] <- link 1D03 IdentificationRejected\n");
            return -1;
        default:
            fprintf(stderr, "[iap2-mini] ignoring unsupported link msg 0x%04x\n", msg_id);
            return write_link_ack_only(state, rx_seq);
    }

    if (write_link_reply(state, rx_seq, reply, reply_len) < 0) {
        free(reply);
        return -1;
    }
    free(reply);
    return 0;
}

static int loop_link_messages(void) {
    struct link_state state;
    memset(&state, 0, sizeof(state));

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
            free(payload);
            if (ctl & IAP2_CTL_ACK) {
                return write_link_ack_only(&state, seq) < 0 ? 1 : 0;
            }
            if (write_link_synack(&state, seq) < 0) {
                return 1;
            }
            continue;
        }

        if (ctl & IAP2_CTL_EAK) {
            fprintf(stderr, "[iap2-mini] <- link EAK ignored\n");
            free(payload);
            continue;
        }

        if (payload_len >= 6 && sid == IAP2_SID_CTL) {
            uint16_t csm = (uint16_t)((payload[0] << 8) | payload[1]);
            uint16_t csm_total = (uint16_t)((payload[2] << 8) | payload[3]);
            uint16_t msg_id = (uint16_t)((payload[4] << 8) | payload[5]);
            if (csm != IAP2_CSM_START || csm_total > payload_len || csm_total < 6) {
                fprintf(stderr, "[iap2-mini] malformed link control payload\n");
                free(payload);
                return 1;
            }
            rc = handle_link_control_msg(&state, seq, msg_id, payload + 6, csm_total - 6);
            free(payload);
            if (rc != 0) {
                return 1;
            }
            continue;
        }

        fprintf(stderr, "[iap2-mini] ignoring non-control link packet ctl=0x%02x sid=%u\n", ctl, sid);
        free(payload);
    }
}

static int rfcomm_listen_socket(int channel) {
    int fd;
    struct sockaddr_rc_local addr;

    fd = socket(AF_BLUETOOTH, SOCK_STREAM, BTPROTO_RFCOMM);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/RFCOMM)");
        return -1;
    }

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

static int l2cap_listen_socket(uint16_t psm) {
    int fd;
    struct sockaddr_l2_local addr;

    fd = socket(AF_BLUETOOTH, SOCK_SEQPACKET, BTPROTO_L2CAP);
    if (fd < 0) {
        perror("socket(AF_BLUETOOTH/L2CAP)");
        return -1;
    }

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
    close(listen_fd);

    bdaddr_to_str(&peer.l2_bdaddr, peer_str);
    fprintf(stderr, "[iap2-mini] L2CAP accepted peer=%s psm=0x%04x cid=0x%04x\n",
            peer_str, peer.l2_psm, peer.l2_cid);
    {
        int rc = 0;
        for (;;) {
            uint8_t hdr[5];
            uint8_t params[1024];
            uint16_t txn_id;
            uint16_t param_len;
            int rr;

            rr = read_exact_fd(conn_fd, hdr, sizeof(hdr));
            if (rr == 1) {
                break;
            }
            if (rr < 0) {
                perror("read SDP header");
                rc = 1;
                break;
            }
            txn_id = (uint16_t)((hdr[1] << 8) | hdr[2]);
            param_len = (uint16_t)((hdr[3] << 8) | hdr[4]);
            if (param_len > sizeof(params)) {
                sdp_write_error_fd(conn_fd, txn_id, SDP_ERR_INVALID_PDU_SIZE);
                rc = 1;
                break;
            }
            rr = read_exact_fd(conn_fd, params, param_len);
            if (rr != 0) {
                perror("read SDP params");
                rc = 1;
                break;
            }
            if (sdp_handle_request_fd(conn_fd, hdr[0], txn_id, params, param_len) < 0) {
                perror("write SDP response");
                rc = 1;
                break;
            }
        }
        close(conn_fd);
        return rc;
    }
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

static void usage(FILE *out) {
    fprintf(out,
        "usage:\n"
        "  carthing-iap2-mini loop\n"
        "  carthing-iap2-mini raw-loop\n"
        "  carthing-iap2-mini link-loop\n"
        "  carthing-iap2-mini sdp-loop\n"
        "  carthing-iap2-mini rfcomm-listen\n"
        "  carthing-iap2-mini sdp-listen\n"
        "  carthing-iap2-mini identify\n"
        "  carthing-iap2-mini identify-raw\n"
        "\n"
        "env:\n"
        "  CARTHING_MFI_HELPER=/path/to/carthing-mfi-probe\n"
        "  CARTHING_IAP2_RFCOMM_CHANNEL=3\n"
        "  CARTHING_IAP2_L2CAP_PSM=0x0001\n");
}

int main(int argc, char **argv) {
    signal(SIGPIPE, SIG_IGN);

    if (argc != 2) {
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
