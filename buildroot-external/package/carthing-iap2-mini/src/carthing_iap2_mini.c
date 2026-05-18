#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

#define IAP2_CSM_START          0x4040
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

#define HELPER_PATH_DEFAULT "/usr/bin/carthing-mfi-probe"

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
    const char *helper = mfi_helper_path();
    const char *argv[] = {helper, subcmd, NULL};
    uint8_t *out = NULL;
    size_t out_len = 0;
    int rc;

    rc = run_helper_capture(argv, NULL, 0, &out, &out_len);
    if (rc < 0) {
        perror("run helper");
        return -1;
    }
    rc = write_all_fd(STDOUT_FILENO, out, out_len);
    free(out);
    return rc;
}

static int forward_helper_aa03(const uint8_t challenge[32], size_t challenge_len) {
    const char *helper = mfi_helper_path();
    char hex[65];
    const char *argv[4];
    uint8_t *out = NULL;
    size_t out_len = 0;
    int rc;

    challenge_to_hex(challenge, challenge_len, hex);
    argv[0] = helper;
    argv[1] = "aa03";
    argv[2] = hex;
    argv[3] = NULL;

    rc = run_helper_capture(argv, NULL, 0, &out, &out_len);
    if (rc < 0) {
        perror("run helper");
        return -1;
    }
    rc = write_all_fd(STDOUT_FILENO, out, out_len);
    free(out);
    return rc;
}

static int handle_message(uint16_t msg_id, const uint8_t *payload, size_t payload_len, int *auth_ok) {
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
            return write_control_msg(IAP2_MSG_ID_INFO, idbuf, idlen);
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

static int loop_messages(void) {
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

        rc = handle_message(msg_id, payload, payload_len, &auth_ok);
        free(payload);
        if (rc != 0) {
            return 1;
        }
    }
}

static void usage(FILE *out) {
    fprintf(out,
        "usage:\n"
        "  carthing-iap2-mini loop\n"
        "  carthing-iap2-mini identify\n"
        "\n"
        "env:\n"
        "  CARTHING_MFI_HELPER=/path/to/carthing-mfi-probe\n");
}

int main(int argc, char **argv) {
    if (argc != 2) {
        usage(stderr);
        return 2;
    }

    if (strcmp(argv[1], "loop") == 0) {
        return loop_messages();
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

    usage(stderr);
    return 2;
}
