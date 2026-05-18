#include <errno.h>
#include <fcntl.h>
#include <linux/i2c-dev.h>
#include <linux/i2c.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define MFI_DEVICE "/dev/apple_mfi"
#define MFI_I2C_DEVICE "/dev/i2c-3"
#define MFI_I2C_ADDR 0x10

struct mfi_buf {
    uint32_t len;
    uint32_t pad;
    uint64_t ptr;
};

#define MFI_GET_VERSION   _IOR(0x77, 1, struct mfi_buf)
#define MFI_GET_CERTLEN   _IOR(0x77, 4, struct mfi_buf)
#define MFI_GET_RESPONSE  _IOR(0x77, 5, struct mfi_buf)
#define MFI_SET_CHALLENGE _IOW(0x77, 6, struct mfi_buf)
#define MFI_GET_SIGNATURE _IOR(0x77, 7, struct mfi_buf)
#define MFI_GET_SERIAL    _IOR(0x77, 8, struct mfi_buf)

static int mfi_ioctl_wrap(int fd, unsigned long req, void *buf, size_t len) {
    struct mfi_buf mb;
    memset(&mb, 0, sizeof(mb));
    mb.len = (uint32_t)len;
    mb.ptr = (uint64_t)(uintptr_t)buf;
    return ioctl(fd, req, &mb);
}

static int i2c_rdwr_retry(int fd, struct i2c_rdwr_ioctl_data *rdwr) {
    int attempt;
    for (attempt = 0; attempt < 3; attempt++) {
        if (ioctl(fd, I2C_RDWR, rdwr) >= 0) {
            return 0;
        }
        if (errno != ENXIO && errno != EREMOTEIO && errno != EIO) {
            return -1;
        }
        usleep(50000);
    }
    return -1;
}

static int i2c_smbus_xfer(int fd, char rw, uint8_t command, int size, union i2c_smbus_data *data) {
    struct i2c_smbus_ioctl_data args;
    memset(&args, 0, sizeof(args));
    args.read_write = rw;
    args.command = command;
    args.size = size;
    args.data = data;
    return ioctl(fd, I2C_SMBUS, &args);
}

static int i2c_select_addr(int fd) {
    if (ioctl(fd, I2C_SLAVE, MFI_I2C_ADDR) == 0) {
        return 0;
    }
    return ioctl(fd, I2C_SLAVE_FORCE, MFI_I2C_ADDR);
}

static int i2c_short_write(int fd, uint8_t command) {
    ssize_t written;
    usleep(2000);
    written = write(fd, &command, 1);
    usleep(2000);
    return (written == 1) ? 0 : -1;
}

static int i2c_read_byte_data(int fd, uint8_t command, uint8_t *value) {
    union i2c_smbus_data data;
    memset(&data, 0, sizeof(data));
    if (i2c_smbus_xfer(fd, I2C_SMBUS_READ, command, I2C_SMBUS_BYTE_DATA, &data) < 0) {
        return -1;
    }
    *value = data.byte & 0xff;
    return 0;
}

static int i2c_read_word_data(int fd, uint8_t command, uint16_t *value) {
    union i2c_smbus_data data;
    memset(&data, 0, sizeof(data));
    if (i2c_smbus_xfer(fd, I2C_SMBUS_READ, command, I2C_SMBUS_WORD_DATA, &data) < 0) {
        return -1;
    }
    *value = data.word & 0xffff;
    return 0;
}

static int i2c_write_byte_data(int fd, uint8_t command, uint8_t value) {
    union i2c_smbus_data data;
    memset(&data, 0, sizeof(data));
    data.byte = value;
    return i2c_smbus_xfer(fd, I2C_SMBUS_WRITE, command, I2C_SMBUS_BYTE_DATA, &data);
}

static int acp_write(int fd, const uint8_t *buf, size_t len) {
    ssize_t written;
    usleep(2000);
    written = write(fd, buf, len);
    usleep(2000);
    return (written == (ssize_t)len) ? 0 : -1;
}

static int acp_reg_read(int fd, uint8_t reg, uint8_t *buf, size_t len) {
    if (acp_write(fd, &reg, 1) < 0) {
        return -1;
    }
    usleep(1000);
    if (read(fd, buf, len) != (ssize_t)len) {
        return -1;
    }
    usleep(2000);
    return 0;
}

static int i2c_reg_read(int fd, uint8_t reg, uint8_t *buf, uint16_t len) {
    struct i2c_msg msgs[2];
    struct i2c_rdwr_ioctl_data rdwr;

    msgs[0].addr = MFI_I2C_ADDR;
    msgs[0].flags = 0;
    msgs[0].len = 1;
    msgs[0].buf = &reg;

    msgs[1].addr = MFI_I2C_ADDR;
    msgs[1].flags = I2C_M_RD;
    msgs[1].len = len;
    msgs[1].buf = buf;

    rdwr.msgs = msgs;
    rdwr.nmsgs = 2;
    return i2c_rdwr_retry(fd, &rdwr);
}

static int i2c_reg_write(int fd, uint8_t reg, const uint8_t *buf, uint16_t len) {
    uint8_t *tmp;
    struct i2c_msg msg;
    struct i2c_rdwr_ioctl_data rdwr;
    int rc;

    tmp = calloc(1, (size_t)len + 1);
    if (!tmp) {
        errno = ENOMEM;
        return -1;
    }

    tmp[0] = reg;
    memcpy(tmp + 1, buf, len);

    msg.addr = MFI_I2C_ADDR;
    msg.flags = 0;
    msg.len = len + 1;
    msg.buf = tmp;

    rdwr.msgs = &msg;
    rdwr.nmsgs = 1;
    rc = i2c_rdwr_retry(fd, &rdwr);
    free(tmp);
    return rc;
}

static void hex_write(FILE *out, const uint8_t *buf, size_t len) {
    size_t i;
    for (i = 0; i < len; i++) {
        fprintf(out, "%02x", buf[i]);
    }
    fputc('\n', out);
}

static int hex_parse_32(const char *hex, uint8_t out[32]) {
    size_t hex_len = strlen(hex);
    size_t i;
    if (hex_len > 64 || (hex_len % 2) != 0) {
        return -1;
    }
    memset(out, 0, 32);
    for (i = 0; i < hex_len / 2; i++) {
        unsigned int v;
        if (sscanf(hex + (i * 2), "%2x", &v) != 1) {
            return -1;
        }
        out[i] = (uint8_t)v;
    }
    return (int)(hex_len / 2);
}

static void usage(FILE *out) {
    fprintf(out,
        "usage:\n"
        "  carthing-mfi-probe info\n"
        "  carthing-mfi-probe certlen\n"
        "  carthing-mfi-probe serial\n"
        "  carthing-mfi-probe response > pkcs7.bin\n"
        "  carthing-mfi-probe sign <challenge_hex>\n"
        "  carthing-mfi-probe raw-info\n"
        "  carthing-mfi-probe raw-sign <challenge_hex>\n"
        "\n"
        "notes:\n"
        "  - response writes raw ioctl nr5 bytes to stdout\n"
        "  - sign accepts up to 32 challenge bytes as hex and pads to 32\n"
        "  - raw-sign is experimental and reports ACP3-style sign state\n"
        "  - raw-* talks directly to %s at 0x%02x via i2c-dev\n",
        MFI_I2C_DEVICE,
        MFI_I2C_ADDR);
}

int main(int argc, char **argv) {
    int fd;
    uint8_t version = 0;
    uint16_t certlen_be = 0;
    uint16_t certlen = 0;
    char serial[256];

    if (argc < 2) {
        usage(stderr);
        return 2;
    }

    if (strcmp(argv[1], "raw-info") == 0) {
        uint8_t phase0_b0 = 0;
        uint8_t phase1_b0 = 0;
        uint8_t phase0_b21 = 0;
        uint8_t phase1_b21 = 0;
        uint16_t phase0_w30 = 0;
        uint16_t phase1_w30 = 0;
        uint8_t raw4[4] = {0};

        fd = open(MFI_I2C_DEVICE, O_RDWR);
        if (fd < 0) {
            perror("open /dev/i2c-3");
            return 1;
        }
        if (i2c_select_addr(fd) < 0) {
            perror("ioctl I2C_SLAVE");
            close(fd);
            return 1;
        }

        printf("device=%s\n", MFI_I2C_DEVICE);
        printf("addr=0x%02x\n", MFI_I2C_ADDR);

        if (i2c_short_write(fd, 0x00) < 0) {
            perror("short write 0x00");
        }

        if (i2c_read_byte_data(fd, 0x00, &phase0_b0) < 0) {
            fprintf(stderr, "byte read phase0 reg0x00 failed\n");
        }
        if (i2c_read_byte_data(fd, 0x21, &phase0_b21) < 0) {
            fprintf(stderr, "byte read phase0 reg0x21 failed\n");
        }
        if (i2c_read_word_data(fd, 0x30, &phase0_w30) < 0) {
            fprintf(stderr, "word read phase0 reg0x30 failed\n");
        }
        if (i2c_reg_read(fd, 0x00, raw4, sizeof(raw4)) < 0) {
            memset(raw4, 0, sizeof(raw4));
        }
        printf("phase0_reg00=0x%02x\n", phase0_b0);
        printf("phase0_reg21=0x%02x\n", phase0_b21);
        printf("phase0_reg30w=0x%04x\n", phase0_w30);
        printf("phase0_raw4=%02x%02x%02x%02x\n", raw4[0], raw4[1], raw4[2], raw4[3]);

        if (i2c_short_write(fd, 0x01) < 0) {
            perror("short write 0x01");
        }
        if (i2c_read_byte_data(fd, 0x00, &phase1_b0) < 0) {
            fprintf(stderr, "byte read phase1 reg0x00 failed\n");
        }
        if (i2c_read_byte_data(fd, 0x21, &phase1_b21) < 0) {
            fprintf(stderr, "byte read phase1 reg0x21 failed\n");
        }
        if (i2c_read_word_data(fd, 0x30, &phase1_w30) < 0) {
            fprintf(stderr, "word read phase1 reg0x30 failed\n");
        }
        if (i2c_reg_read(fd, 0x00, raw4, sizeof(raw4)) < 0) {
            memset(raw4, 0, sizeof(raw4));
        }
        printf("phase1_reg00=0x%02x\n", phase1_b0);
        printf("phase1_reg21=0x%02x\n", phase1_b21);
        printf("phase1_reg30w=0x%04x\n", phase1_w30);
        printf("phase1_raw4=%02x%02x%02x%02x\n", raw4[0], raw4[1], raw4[2], raw4[3]);

        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "raw-sign") == 0) {
        uint8_t challenge[32];
        uint8_t signature[64];
        uint8_t status = 0;
        uint8_t err_code = 0;
        uint8_t start_cmd[2] = {0x10, 0x01};
        uint8_t challenge_cmd[33];
        uint8_t siglen_buf[2] = {0, 0};
        uint16_t siglen = 0;
        int attempt;
        int nbytes;

        if (argc != 3) {
            usage(stderr);
            return 2;
        }

        nbytes = hex_parse_32(argv[2], challenge);
        if (nbytes < 0) {
            fprintf(stderr, "invalid challenge hex\n");
            return 2;
        }

        fd = open(MFI_I2C_DEVICE, O_RDWR);
        if (fd < 0) {
            perror("open /dev/i2c-3");
            return 1;
        }
        if (i2c_select_addr(fd) < 0) {
            perror("ioctl I2C_SLAVE");
            close(fd);
            return 1;
        }

        if (i2c_short_write(fd, 0x01) < 0) {
            perror("short write 0x01");
        }

        challenge_cmd[0] = 0x21;
        memcpy(challenge_cmd + 1, challenge, sizeof(challenge));
        if (acp_write(fd, challenge_cmd, sizeof(challenge_cmd)) < 0) {
            perror("acp write challenge 0x21");
            close(fd);
            return 1;
        }

        if (acp_write(fd, start_cmd, sizeof(start_cmd)) < 0) {
            perror("acp write start 0x10");
            close(fd);
            return 1;
        }

        status = 0;
        for (attempt = 0; attempt < 30; attempt++) {
            usleep(200 * 1000);
            if (acp_reg_read(fd, 0x10, &status, 1) == 0) {
                fprintf(stderr, "poll[%d]=0x%02x\n", attempt + 1, status);
                if (status == 0x10) {
                    break;
                }
            } else {
                fprintf(stderr, "poll[%d]=nack\n", attempt + 1);
            }
        }

        if (acp_reg_read(fd, 0x05, &err_code, 1) == 0) {
            fprintf(stderr, "error-code=0x%02x\n", err_code);
        }

        memset(siglen_buf, 0, sizeof(siglen_buf));
        if (acp_reg_read(fd, 0x11, siglen_buf, sizeof(siglen_buf)) == 0) {
            siglen = (uint16_t)((siglen_buf[0] << 8) | siglen_buf[1]);
            fprintf(stderr, "signature-len=0x%04x\n", siglen);
        } else {
            fprintf(stderr, "signature-len=unavailable\n");
        }

        memset(signature, 0, sizeof(signature));
        if (acp_reg_read(fd, 0x12, signature, sizeof(signature)) < 0) {
            perror("i2c read reg 0x12");
            close(fd);
            return 1;
        }

        hex_write(stdout, signature, sizeof(signature));
        close(fd);
        return (status == 0x10 && siglen != 0) ? 0 : 1;
    }

    fd = open(MFI_DEVICE, O_RDWR);
    if (fd < 0) {
        perror("open /dev/apple_mfi");
        return 1;
    }

    if (strcmp(argv[1], "info") == 0) {
        memset(serial, 0, sizeof(serial));
        if (mfi_ioctl_wrap(fd, MFI_GET_VERSION, &version, sizeof(version)) < 0) {
            perror("ioctl MFI_GET_VERSION");
            close(fd);
            return 1;
        }
        if (mfi_ioctl_wrap(fd, MFI_GET_CERTLEN, &certlen_be, sizeof(certlen_be)) < 0) {
            perror("ioctl MFI_GET_CERTLEN");
            close(fd);
            return 1;
        }
        certlen = (uint16_t)(((certlen_be & 0xFF) << 8) | (certlen_be >> 8));
        if (mfi_ioctl_wrap(fd, MFI_GET_SERIAL, serial, sizeof(serial) - 1) < 0) {
            perror("ioctl MFI_GET_SERIAL");
            close(fd);
            return 1;
        }
        printf("device=%s\n", MFI_DEVICE);
        printf("version=0x%02x\n", version);
        printf("certlen=%u\n", certlen);
        printf("serial=%s\n", serial);
        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "certlen") == 0) {
        if (mfi_ioctl_wrap(fd, MFI_GET_CERTLEN, &certlen_be, sizeof(certlen_be)) < 0) {
            perror("ioctl MFI_GET_CERTLEN");
            close(fd);
            return 1;
        }
        certlen = (uint16_t)(((certlen_be & 0xFF) << 8) | (certlen_be >> 8));
        printf("%u\n", certlen);
        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "serial") == 0) {
        memset(serial, 0, sizeof(serial));
        if (mfi_ioctl_wrap(fd, MFI_GET_SERIAL, serial, sizeof(serial) - 1) < 0) {
            perror("ioctl MFI_GET_SERIAL");
            close(fd);
            return 1;
        }
        printf("%s\n", serial);
        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "response") == 0) {
        uint8_t *buf;
        ssize_t written;
        if (mfi_ioctl_wrap(fd, MFI_GET_CERTLEN, &certlen_be, sizeof(certlen_be)) < 0) {
            perror("ioctl MFI_GET_CERTLEN");
            close(fd);
            return 1;
        }
        certlen = (uint16_t)(((certlen_be & 0xFF) << 8) | (certlen_be >> 8));
        if (certlen == 0 || certlen > 4096) {
            fprintf(stderr, "unexpected certlen=%u\n", certlen);
            close(fd);
            return 1;
        }
        buf = calloc(1, certlen);
        if (!buf) {
            perror("calloc");
            close(fd);
            return 1;
        }
        if (mfi_ioctl_wrap(fd, MFI_GET_RESPONSE, buf, certlen) < 0) {
            perror("ioctl MFI_GET_RESPONSE");
            free(buf);
            close(fd);
            return 1;
        }
        written = write(STDOUT_FILENO, buf, certlen);
        if (written < 0 || (size_t)written != certlen) {
            perror("write stdout");
            free(buf);
            close(fd);
            return 1;
        }
        free(buf);
        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "sign") == 0) {
        uint8_t challenge[32];
        uint8_t signature[64];
        int nbytes;
        if (argc != 3) {
            usage(stderr);
            close(fd);
            return 2;
        }
        nbytes = hex_parse_32(argv[2], challenge);
        if (nbytes < 0) {
            fprintf(stderr, "invalid challenge hex\n");
            close(fd);
            return 2;
        }
        if (mfi_ioctl_wrap(fd, MFI_SET_CHALLENGE, challenge, sizeof(challenge)) < 0) {
            perror("ioctl MFI_SET_CHALLENGE");
            close(fd);
            return 1;
        }
        memset(signature, 0, sizeof(signature));
        if (mfi_ioctl_wrap(fd, MFI_GET_SIGNATURE, signature, sizeof(signature)) < 0) {
            perror("ioctl MFI_GET_SIGNATURE");
            close(fd);
            return 1;
        }
        hex_write(stdout, signature, sizeof(signature));
        close(fd);
        return 0;
    }

    usage(stderr);
    close(fd);
    return 2;
}
