#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <unistd.h>

#define MFI_DEVICE "/dev/apple_mfi"

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
        "\n"
        "notes:\n"
        "  - response writes raw ioctl nr5 bytes to stdout\n"
        "  - sign accepts up to 32 challenge bytes as hex and pads to 32\n");
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
