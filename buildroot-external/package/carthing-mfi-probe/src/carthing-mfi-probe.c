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
        uint8_t reg21 = 0;
        uint8_t reg00 = 0;
        uint8_t certlen_raw[2] = {0, 0};
        uint16_t raw_certlen = 0;

        fd = open(MFI_I2C_DEVICE, O_RDWR);
        if (fd < 0) {
            perror("open /dev/i2c-3");
            return 1;
        }

        if (i2c_reg_read(fd, 0x21, &reg21, 1) < 0) {
            perror("i2c read reg 0x21");
            close(fd);
            return 1;
        }
        if (i2c_reg_read(fd, 0x00, &reg00, 1) < 0) {
            perror("i2c read reg 0x00");
            close(fd);
            return 1;
        }

        printf("device=%s\n", MFI_I2C_DEVICE);
        printf("addr=0x%02x\n", MFI_I2C_ADDR);
        printf("reg21=0x%02x\n", reg21);
        printf("reg00=0x%02x\n", reg00);

        if (i2c_reg_read(fd, 0x30, certlen_raw, sizeof(certlen_raw)) == 0) {
            raw_certlen = (uint16_t)((certlen_raw[0] << 8) | certlen_raw[1]);
            printf("certlen=%u\n", raw_certlen);
        } else {
            printf("certlen=unavailable\n");
        }

        close(fd);
        return 0;
    }

    if (strcmp(argv[1], "raw-sign") == 0) {
        uint8_t challenge[32];
        uint8_t signature[64];
        uint8_t reg21 = 0;
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

        if (i2c_reg_write(fd, 0x4E, challenge, sizeof(challenge)) < 0) {
            perror("i2c write reg 0x4E");
            close(fd);
            return 1;
        }

        if (i2c_reg_read(fd, 0x21, &reg21, 1) < 0) {
            perror("i2c read reg 0x21");
            close(fd);
            return 1;
        }
        fprintf(stderr, "challenge-len=0x%02x\n", reg21);

        memset(signature, 0, sizeof(signature));
        if (i2c_reg_read(fd, 0x12, signature, sizeof(signature)) < 0) {
            perror("i2c read reg 0x12");
            close(fd);
            return 1;
        }

        hex_write(stdout, signature, sizeof(signature));
        close(fd);
        return 0;
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
