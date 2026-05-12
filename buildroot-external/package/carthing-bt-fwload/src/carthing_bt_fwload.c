#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <termios.h>
#include <unistd.h>

#define ARRAY_SIZE(x) (sizeof(x) / sizeof((x)[0]))

struct options {
    const char *device;
    const char *firmware;
    unsigned int download_baud;
    unsigned int controller_baud;
    unsigned int sleep_us;
    bool debug;
};

static void usage(FILE *stream, const char *argv0) {
    fprintf(stream,
        "usage: %s --device <tty> --firmware <file> [options]\n"
        "\n"
        "options:\n"
        "  --download-baud <baud>  Initial UART baud rate before firmware upload\n"
        "  --baudrate <baud>       Final controller baud rate after upload\n"
        "  --sleep-us <usec>       Delay between HCD commands\n"
        "  --debug                 Print HCI packets\n"
        "  --help                  Show this help\n",
        argv0);
}

static speed_t speed_from_uint(unsigned int baud) {
    switch (baud) {
    case 9600:
        return B9600;
    case 19200:
        return B19200;
    case 38400:
        return B38400;
    case 57600:
        return B57600;
    case 115200:
        return B115200;
    case 230400:
#ifdef B230400
        return B230400;
#endif
        break;
    case 460800:
#ifdef B460800
        return B460800;
#endif
        break;
    case 921600:
#ifdef B921600
        return B921600;
#endif
        break;
    case 1000000:
#ifdef B1000000
        return B1000000;
#endif
        break;
    case 1500000:
#ifdef B1500000
        return B1500000;
#endif
        break;
    case 2000000:
#ifdef B2000000
        return B2000000;
#endif
        break;
    case 2500000:
#ifdef B2500000
        return B2500000;
#endif
        break;
    case 3000000:
#ifdef B3000000
        return B3000000;
#endif
        break;
    case 3500000:
#ifdef B3500000
        return B3500000;
#endif
        break;
    case 4000000:
#ifdef B4000000
        return B4000000;
#endif
        break;
    default:
        break;
    }

    return (speed_t)0;
}

static int set_serial_baud(int fd, unsigned int baud) {
    struct termios tio;
    speed_t speed = speed_from_uint(baud);

    if (speed == (speed_t)0) {
        fprintf(stderr, "unsupported baud rate: %u\n", baud);
        return -1;
    }

    if (tcgetattr(fd, &tio) != 0) {
        perror("tcgetattr");
        return -1;
    }

    cfmakeraw(&tio);
    tio.c_cflag |= CLOCAL | CREAD;
    tio.c_cflag &= ~CRTSCTS;
    tio.c_cc[VMIN] = 0;
    tio.c_cc[VTIME] = 1;

    if (cfsetispeed(&tio, speed) != 0 || cfsetospeed(&tio, speed) != 0) {
        perror("cfsetispeed/cfsetospeed");
        return -1;
    }

    if (tcsetattr(fd, TCSANOW, &tio) != 0) {
        perror("tcsetattr");
        return -1;
    }

    if (tcflush(fd, TCIOFLUSH) != 0) {
        perror("tcflush");
        return -1;
    }

    return 0;
}

static int read_exact_timeout(int fd, uint8_t *buf, size_t len, int timeout_ms) {
    size_t done = 0;

    while (done < len) {
        struct pollfd pfd = {
            .fd = fd,
            .events = POLLIN,
        };
        int ready = poll(&pfd, 1, timeout_ms);
        if (ready < 0) {
            perror("poll");
            return -1;
        }
        if (ready == 0) {
            fprintf(stderr, "timed out waiting for UART data\n");
            return -1;
        }

        ssize_t chunk = read(fd, buf + done, len - done);
        if (chunk < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("read");
            return -1;
        }
        if (chunk == 0) {
            fprintf(stderr, "unexpected EOF on UART\n");
            return -1;
        }
        done += (size_t)chunk;
    }

    return 0;
}

static void dump_packet(const char *prefix, const uint8_t *buf, size_t len) {
    size_t i;

    fprintf(stderr, "%s", prefix);
    for (i = 0; i < len; ++i) {
        fprintf(stderr, " %02x", buf[i]);
    }
    fputc('\n', stderr);
}

static int write_full(int fd, const uint8_t *buf, size_t len) {
    size_t done = 0;

    while (done < len) {
        ssize_t chunk = write(fd, buf + done, len - done);
        if (chunk < 0) {
            if (errno == EINTR) {
                continue;
            }
            perror("write");
            return -1;
        }
        done += (size_t)chunk;
    }

    return 0;
}

static int send_hci_cmd_no_response(int fd, const uint8_t *cmd, size_t len, bool debug) {
    if (debug) {
        dump_packet("=>", cmd, len);
    }

    return write_full(fd, cmd, len);
}

static int read_hci_event(int fd, uint8_t *buf, size_t cap, bool debug) {
    uint8_t header[3];
    size_t payload_len;

    if (cap < 3) {
        return -1;
    }

    if (read_exact_timeout(fd, header, sizeof(header), 3000) != 0) {
        return -1;
    }

    if (header[0] != 0x04) {
        fprintf(stderr, "unexpected packet type: 0x%02x\n", header[0]);
        return -1;
    }

    payload_len = header[2];
    if (3 + payload_len > cap) {
        fprintf(stderr, "HCI event too large: %zu\n", payload_len);
        return -1;
    }

    memcpy(buf, header, sizeof(header));
    if (read_exact_timeout(fd, buf + 3, payload_len, 3000) != 0) {
        return -1;
    }

    if (debug) {
        dump_packet("<=", buf, 3 + payload_len);
    }

    return (int)(3 + payload_len);
}

static int send_hci_cmd_expect_complete(int fd, const uint8_t *cmd, size_t len,
                                        uint16_t opcode, bool debug) {
    uint8_t event[260];
    int event_len;
    uint16_t returned_opcode;

    if (debug) {
        dump_packet("=>", cmd, len);
    }

    if (write_full(fd, cmd, len) != 0) {
        return -1;
    }

    event_len = read_hci_event(fd, event, sizeof(event), debug);
    if (event_len < 7) {
        fprintf(stderr, "short HCI event\n");
        return -1;
    }

    if (event[1] != 0x0e) {
        fprintf(stderr, "unexpected HCI event code: 0x%02x\n", event[1]);
        return -1;
    }

    returned_opcode = (uint16_t)event[4] | ((uint16_t)event[5] << 8);
    if (returned_opcode != opcode) {
        fprintf(stderr, "unexpected opcode in command complete: 0x%04x\n", returned_opcode);
        return -1;
    }

    if (event[6] != 0x00) {
        fprintf(stderr, "controller returned non-zero status 0x%02x for opcode 0x%04x\n",
                event[6], opcode);
        return -1;
    }

    return 0;
}

static int stream_hcd(FILE *fw, int fd, const struct options *opts) {
    uint8_t hdr[3];

    while (fread(hdr, 1, sizeof(hdr), fw) == sizeof(hdr)) {
        uint8_t cmd[260];
        uint16_t opcode = (uint16_t)hdr[0] | ((uint16_t)hdr[1] << 8);
        size_t payload_len = hdr[2];

        if (payload_len > 255) {
            fprintf(stderr, "invalid HCD payload length: %zu\n", payload_len);
            return -1;
        }

        cmd[0] = 0x01;
        cmd[1] = hdr[0];
        cmd[2] = hdr[1];
        cmd[3] = hdr[2];

        if (fread(cmd + 4, 1, payload_len, fw) != payload_len) {
            fprintf(stderr, "truncated HCD payload\n");
            return -1;
        }

        if (send_hci_cmd_expect_complete(fd, cmd, 4 + payload_len, opcode, opts->debug) != 0) {
            return -1;
        }

        if (opts->sleep_us != 0) {
            usleep(opts->sleep_us);
        }
    }

    if (!feof(fw)) {
        perror("fread");
        return -1;
    }

    return 0;
}

static void build_baudrate_cmd(uint8_t *cmd, uint32_t baud) {
    cmd[0] = 0x01;
    cmd[1] = 0x18;
    cmd[2] = 0xfc;
    cmd[3] = 0x06;
    cmd[4] = (uint8_t)(baud & 0xff);
    cmd[5] = (uint8_t)((baud >> 8) & 0xff);
    cmd[6] = (uint8_t)((baud >> 16) & 0xff);
    cmd[7] = (uint8_t)((baud >> 24) & 0xff);
    cmd[8] = 0x00;
    cmd[9] = 0x00;
}

static int maybe_set_final_baud(int fd, const struct options *opts) {
    uint8_t set_clock[] = {0x01, 0x45, 0xfc, 0x01, 0x01};
    uint8_t set_baud[10];

    if (opts->controller_baud == 0 || opts->controller_baud == opts->download_baud) {
        return 0;
    }

    if (opts->controller_baud > 3000000) {
        if (send_hci_cmd_expect_complete(fd, set_clock, sizeof(set_clock), 0xfc45, opts->debug) != 0) {
            return -1;
        }
    }

    build_baudrate_cmd(set_baud, opts->controller_baud);
    if (send_hci_cmd_expect_complete(fd, set_baud, sizeof(set_baud), 0xfc18, opts->debug) != 0) {
        return -1;
    }

    usleep(50000);
    if (set_serial_baud(fd, opts->controller_baud) != 0) {
        return -1;
    }

    return 0;
}

static int do_firmware_load(int fd, FILE *fw, const struct options *opts) {
    uint8_t hci_reset[] = {0x01, 0x03, 0x0c, 0x00};
    uint8_t hci_download_minidriver[] = {0x01, 0x2e, 0xfc, 0x00};
    uint8_t hci_launch_ram[] = {0x01, 0x4e, 0xfc, 0x00};

    if (send_hci_cmd_expect_complete(fd, hci_reset, sizeof(hci_reset), 0x0c03, opts->debug) != 0) {
        return -1;
    }

    if (send_hci_cmd_expect_complete(fd, hci_download_minidriver,
                                     sizeof(hci_download_minidriver), 0xfc2e,
                                     opts->debug) != 0) {
        return -1;
    }

    if (stream_hcd(fw, fd, opts) != 0) {
        return -1;
    }

    /*
     * Some Broadcom patchram flows reboot immediately after Launch RAM and
     * never send a Command Complete for opcode 0xFC4E. Treat Launch RAM as a
     * fire-and-reboot step: send it, give the controller time to restart, then
     * flush any stale bytes before the next HCI reset.
     */
    if (send_hci_cmd_no_response(fd, hci_launch_ram, sizeof(hci_launch_ram), opts->debug) != 0) {
        return -1;
    }

    usleep(500000);
    if (tcflush(fd, TCIOFLUSH) != 0) {
        perror("tcflush");
        return -1;
    }

    if (send_hci_cmd_expect_complete(fd, hci_reset, sizeof(hci_reset), 0x0c03, opts->debug) != 0) {
        return -1;
    }

    if (maybe_set_final_baud(fd, opts) != 0) {
        return -1;
    }

    if (opts->controller_baud != 0 && opts->controller_baud != opts->download_baud) {
        if (send_hci_cmd_expect_complete(fd, hci_reset, sizeof(hci_reset), 0x0c03, opts->debug) != 0) {
            return -1;
        }
    }

    return 0;
}

static int parse_u32(const char *arg, unsigned int *value) {
    char *end = NULL;
    unsigned long parsed = strtoul(arg, &end, 10);

    if (end == arg || *end != '\0') {
        return -1;
    }

    *value = (unsigned int)parsed;
    return 0;
}

static int parse_args(int argc, char **argv, struct options *opts) {
    int i;

    memset(opts, 0, sizeof(*opts));
    opts->download_baud = 115200;
    opts->controller_baud = 3000000;
    opts->sleep_us = 5000;

    for (i = 1; i < argc; ++i) {
        const char *arg = argv[i];

        if (strcmp(arg, "--help") == 0) {
            usage(stdout, argv[0]);
            exit(0);
        } else if (strcmp(arg, "--device") == 0 && i + 1 < argc) {
            opts->device = argv[++i];
        } else if (strcmp(arg, "--firmware") == 0 && i + 1 < argc) {
            opts->firmware = argv[++i];
        } else if (strcmp(arg, "--download-baud") == 0 && i + 1 < argc) {
            if (parse_u32(argv[++i], &opts->download_baud) != 0) {
                fprintf(stderr, "invalid --download-baud value\n");
                return -1;
            }
        } else if (strcmp(arg, "--baudrate") == 0 && i + 1 < argc) {
            if (parse_u32(argv[++i], &opts->controller_baud) != 0) {
                fprintf(stderr, "invalid --baudrate value\n");
                return -1;
            }
        } else if (strcmp(arg, "--sleep-us") == 0 && i + 1 < argc) {
            if (parse_u32(argv[++i], &opts->sleep_us) != 0) {
                fprintf(stderr, "invalid --sleep-us value\n");
                return -1;
            }
        } else if (strcmp(arg, "--debug") == 0) {
            opts->debug = true;
        } else {
            fprintf(stderr, "unknown argument: %s\n", arg);
            return -1;
        }
    }

    if (opts->device == NULL || opts->firmware == NULL) {
        usage(stderr, argv[0]);
        return -1;
    }

    return 0;
}

int main(int argc, char **argv) {
    struct options opts;
    FILE *fw = NULL;
    int fd = -1;
    int status = 1;

    if (parse_args(argc, argv, &opts) != 0) {
        return 1;
    }

    fw = fopen(opts.firmware, "rb");
    if (fw == NULL) {
        perror("fopen firmware");
        goto out;
    }

    fd = open(opts.device, O_RDWR | O_NOCTTY);
    if (fd < 0) {
        perror("open uart");
        goto out;
    }

    if (set_serial_baud(fd, opts.download_baud) != 0) {
        goto out;
    }

    if (do_firmware_load(fd, fw, &opts) != 0) {
        goto out;
    }

    status = 0;

out:
    if (fd >= 0) {
        close(fd);
    }
    if (fw != NULL) {
        fclose(fw);
    }
    return status;
}
