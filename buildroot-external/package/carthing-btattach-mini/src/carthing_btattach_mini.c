#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <termios.h>
#include <unistd.h>

#ifndef N_HCI
#define N_HCI 15
#endif

#define HCIUARTSETPROTO _IOW('U', 200, int)
#define HCIUARTGETDEVICE _IOR('U', 202, int)
#define HCIUARTSETFLAGS _IOW('U', 203, int)

#define HCI_UART_BCM 7
#define HCI_UART_RESET_ON_INIT 1

static volatile sig_atomic_t keep_running = 1;

static void on_signal(int signum) {
    (void)signum;
    keep_running = 0;
}

static speed_t parse_speed(unsigned int speed) {
    switch (speed) {
        case 9600: return B9600;
        case 19200: return B19200;
        case 38400: return B38400;
        case 57600: return B57600;
        case 115200: return B115200;
#ifdef B230400
        case 230400: return B230400;
#endif
#ifdef B460800
        case 460800: return B460800;
#endif
#ifdef B921600
        case 921600: return B921600;
#endif
#ifdef B1000000
        case 1000000: return B1000000;
#endif
#ifdef B1500000
        case 1500000: return B1500000;
#endif
#ifdef B2000000
        case 2000000: return B2000000;
#endif
#ifdef B2500000
        case 2500000: return B2500000;
#endif
#ifdef B3000000
        case 3000000: return B3000000;
#endif
        default: return 0;
    }
}

static int open_serial(const char *path, unsigned int speed, bool flowctl) {
    struct termios ti;
    int fd;
    int saved_ldisc;
    int ldisc = N_HCI;
    speed_t baud = parse_speed(speed);

    if (!baud) {
        fprintf(stderr, "unsupported speed: %u\n", speed);
        return -1;
    }

    fd = open(path, O_RDWR | O_NOCTTY);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    if (tcflush(fd, TCIOFLUSH) < 0) {
        perror("tcflush");
        close(fd);
        return -1;
    }

    if (ioctl(fd, TIOCGETD, &saved_ldisc) < 0) {
        perror("TIOCGETD");
        close(fd);
        return -1;
    }

    memset(&ti, 0, sizeof(ti));
    cfmakeraw(&ti);
    ti.c_cflag |= (CLOCAL | CREAD);
    if (flowctl) {
        ti.c_cflag |= CRTSCTS;
    }
    if (cfsetispeed(&ti, baud) < 0 || cfsetospeed(&ti, baud) < 0) {
        perror("cfset*speed");
        close(fd);
        return -1;
    }

    if (tcsetattr(fd, TCSANOW, &ti) < 0) {
        perror("tcsetattr");
        close(fd);
        return -1;
    }

    if (ioctl(fd, TIOCSETD, &ldisc) < 0) {
        perror("TIOCSETD");
        close(fd);
        return -1;
    }

    fprintf(stderr, "line discipline: %d -> %d\n", saved_ldisc, ldisc);
    return fd;
}

int main(int argc, char **argv) {
    const char *path = "/dev/ttyS1";
    unsigned int speed = 115200;
    bool flowctl = true;
    unsigned long flags = (1UL << HCI_UART_RESET_ON_INIT);
    int fd;
    int dev_id;
    int proto = HCI_UART_BCM;

    if (argc > 1) {
        path = argv[1];
    }
    if (argc > 2) {
        speed = (unsigned int)strtoul(argv[2], NULL, 10);
    }
    if (argc > 3 && strcmp(argv[3], "--noflowctl") == 0) {
        flowctl = false;
    }

    signal(SIGINT, on_signal);
    signal(SIGTERM, on_signal);

    fd = open_serial(path, speed, flowctl);
    if (fd < 0) {
        return 1;
    }

    if (ioctl(fd, HCIUARTSETFLAGS, flags) < 0) {
        perror("HCIUARTSETFLAGS");
        close(fd);
        return 1;
    }

    if (ioctl(fd, HCIUARTSETPROTO, proto) < 0) {
        perror("HCIUARTSETPROTO");
        close(fd);
        return 1;
    }

    dev_id = ioctl(fd, HCIUARTGETDEVICE);
    if (dev_id < 0) {
        perror("HCIUARTGETDEVICE");
        close(fd);
        return 1;
    }

    fprintf(stderr, "attached %s as hci%d (speed=%u flowctl=%s)\n",
            path, dev_id, speed, flowctl ? "on" : "off");

    while (keep_running) {
        pause();
    }

    close(fd);
    return 0;
}
