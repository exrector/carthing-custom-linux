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

#define IAP2_CSM_START          0x4040
#define IAP2_MSG_AUTH_CERT_RESP 0xAA01
#define IAP2_MSG_AUTH_CHAL_RESP 0xAA03

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

static void hex_write(FILE *out, const uint8_t *buf, size_t len) {
    size_t i;
    for (i = 0; i < len; i++) {
        fprintf(out, "%02x", buf[i]);
    }
    fputc('\n', out);
}

static int write_all_stdout(const uint8_t *buf, size_t len) {
    size_t off = 0;
    while (off < len) {
        ssize_t written = write(STDOUT_FILENO, buf + off, len - off);
        if (written < 0) {
            return -1;
        }
        off += (size_t)written;
    }
    return 0;
}

static int load_file(const char *path, uint8_t **buf_out, size_t *len_out) {
    FILE *fp;
    long size;
    uint8_t *buf;

    fp = fopen(path, "rb");
    if (!fp) {
        return -1;
    }
    if (fseek(fp, 0, SEEK_END) != 0) {
        fclose(fp);
        return -1;
    }
    size = ftell(fp);
    if (size < 0) {
        fclose(fp);
        return -1;
    }
    if (fseek(fp, 0, SEEK_SET) != 0) {
        fclose(fp);
        return -1;
    }
    buf = calloc(1, (size_t)size);
    if (!buf) {
        fclose(fp);
        errno = ENOMEM;
        return -1;
    }
    if (size > 0 && fread(buf, 1, (size_t)size, fp) != (size_t)size) {
        free(buf);
        fclose(fp);
        return -1;
    }
    fclose(fp);
    *buf_out = buf;
    *len_out = (size_t)size;
    return 0;
}

static size_t iap2_param(uint8_t *buf, uint16_t param_id, const uint8_t *data, size_t dlen) {
    uint16_t plen = (uint16_t)(4 + dlen);
    buf[0] = (uint8_t)((plen >> 8) & 0xff);
    buf[1] = (uint8_t)(plen & 0xff);
    buf[2] = (uint8_t)((param_id >> 8) & 0xff);
    buf[3] = (uint8_t)(param_id & 0xff);
    if (dlen > 0) {
        memcpy(buf + 4, data, dlen);
    }
    return (size_t)plen;
}

static int iap2_write_control_msg(uint16_t msg_id, const uint8_t *params, size_t params_len) {
    uint8_t header[6];
    uint16_t total = (uint16_t)(6 + params_len);
    header[0] = (uint8_t)((IAP2_CSM_START >> 8) & 0xff);
    header[1] = (uint8_t)(IAP2_CSM_START & 0xff);
    header[2] = (uint8_t)((total >> 8) & 0xff);
    header[3] = (uint8_t)(total & 0xff);
    header[4] = (uint8_t)((msg_id >> 8) & 0xff);
    header[5] = (uint8_t)(msg_id & 0xff);
    if (write_all_stdout(header, sizeof(header)) < 0) {
        return -1;
    }
    if (params_len > 0 && write_all_stdout(params, params_len) < 0) {
        return -1;
    }
    return 0;
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
        "  carthing-mfi-probe aa01-file <pkcs7.bin>\n"
        "  carthing-mfi-probe aa03-file <sig64.bin>\n"
        "  carthing-mfi-probe aa03 <challenge_hex>\n"
        "\n"
        "notes:\n"
        "  - response writes raw ioctl nr5 bytes to stdout\n"
        "  - sign accepts up to 32 challenge bytes as hex and pads to 32\n"
        "  - raw-sign is experimental and reports ACP3-style sign state\n"
        "  - aa01-file and aa03-file write raw iAP2 control-session payload bytes\n"
        "  - aa03 signs through the live ACP3 path and wraps result as iAP2 AA03\n"
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

    if (strcmp(argv[1], "aa01-file") == 0) {
        uint8_t *file_buf = NULL;
        size_t file_len = 0;
        uint8_t *param = NULL;
        size_t param_len;
        int rc = 1;

        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        if (load_file(argv[2], &file_buf, &file_len) < 0) {
            perror("load pkcs7 file");
            return 1;
        }
        param = calloc(1, file_len + 4);
        if (!param) {
            perror("calloc");
            free(file_buf);
            return 1;
        }
        param_len = iap2_param(param, 0x0000, file_buf, file_len);
        if (iap2_write_control_msg(IAP2_MSG_AUTH_CERT_RESP, param, param_len) == 0) {
            rc = 0;
        } else {
            perror("write stdout");
        }
        free(param);
        free(file_buf);
        return rc;
    }

    if (strcmp(argv[1], "aa03-file") == 0) {
        uint8_t *file_buf = NULL;
        size_t file_len = 0;
        uint8_t param[68];
        size_t param_len;

        if (argc != 3) {
            usage(stderr);
            return 2;
        }
        if (load_file(argv[2], &file_buf, &file_len) < 0) {
            perror("load signature file");
            return 1;
        }
        if (file_len != 64) {
            fprintf(stderr, "signature file must be exactly 64 bytes, got %zu\n", file_len);
            free(file_buf);
            return 1;
        }
        param_len = iap2_param(param, 0x0000, file_buf, file_len);
        free(file_buf);
        if (iap2_write_control_msg(IAP2_MSG_AUTH_CHAL_RESP, param, param_len) < 0) {
            perror("write stdout");
            return 1;
        }
        return 0;
    }

    if (strcmp(argv[1], "aa03") == 0) {
        uint8_t challenge[32];
        uint8_t signature[64];
        uint8_t status = 0;
        uint8_t err_code = 0;
        uint8_t start_cmd[2] = {0x10, 0x01};
        uint8_t challenge_cmd[33];
        uint8_t siglen_buf[2] = {0, 0};
        uint16_t siglen = 0;
        uint8_t param[68];
        size_t param_len;
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
        if (acp_reg_read(fd, 0x11, siglen_buf, sizeof(siglen_buf)) == 0) {
            siglen = (uint16_t)((siglen_buf[0] << 8) | siglen_buf[1]);
            fprintf(stderr, "signature-len=0x%04x\n", siglen);
        }
        memset(signature, 0, sizeof(signature));
        if (acp_reg_read(fd, 0x12, signature, sizeof(signature)) < 0) {
            perror("i2c read reg 0x12");
            close(fd);
            return 1;
        }
        close(fd);
        if (status != 0x10 || siglen != 0x0040) {
            fprintf(stderr, "signature not ready\n");
            return 1;
        }
        param_len = iap2_param(param, 0x0000, signature, sizeof(signature));
        if (iap2_write_control_msg(IAP2_MSG_AUTH_CHAL_RESP, param, param_len) < 0) {
            perror("write stdout");
            return 1;
        }
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
