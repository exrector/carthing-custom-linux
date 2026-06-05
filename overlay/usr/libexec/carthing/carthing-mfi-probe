#!/usr/bin/env python3
import ctypes
import fcntl
import hashlib
import os
import struct
import sys


DEV = "/dev/apple_mfi"
IOC_READ = 2
IOC_WRITE = 1
MFI_MAGIC = 0x77
MFI_GET_VERSION = 1
MFI_GET_CERTLEN = 4
MFI_GET_RESPONSE = 5
MFI_SET_CHALLENGE = 6
MFI_GET_SIGNATURE = 7


def ioc(direction, magic, nr, size):
    return (direction << 30) | (size << 16) | (magic << 8) | nr


def ioctl_buf(fd, direction, nr, payload):
    buf = ctypes.create_string_buffer(bytes(payload), len(payload))
    hdr = bytearray(struct.pack("<IIQ", len(payload), 0, ctypes.addressof(buf)))
    fcntl.ioctl(fd, ioc(direction, MFI_MAGIC, nr, 16), hdr, True)
    return bytes(buf.raw)


def read_ioc(fd, nr, size):
    return ioctl_buf(fd, IOC_READ, nr, b"\x00" * size)


def write_ioc(fd, nr, payload):
    return ioctl_buf(fd, IOC_WRITE, nr, payload)


def main():
    fd = os.open(DEV, os.O_RDWR)
    try:
        version = read_ioc(fd, MFI_GET_VERSION, 1)[0]
        cert_len_b = read_ioc(fd, MFI_GET_CERTLEN, 2)
        cert_len = (cert_len_b[0] << 8) | cert_len_b[1]
        cert = read_ioc(fd, MFI_GET_RESPONSE, cert_len)
        challenge = bytes(range(32))
        write_ioc(fd, MFI_SET_CHALLENGE, challenge)
        signature = read_ioc(fd, MFI_GET_SIGNATURE, 64)
    finally:
        os.close(fd)

    print(f"MFI_VERSION=0x{version:02x}")
    print(f"MFI_CERT_LEN={cert_len}")
    print(f"MFI_CERT_HEAD={cert[:12].hex()}")
    print(f"MFI_CERT_SHA256={hashlib.sha256(cert).hexdigest()}")
    print(f"MFI_SIG_LEN={len(signature)}")
    print(f"MFI_SIG_HEAD={signature[:16].hex()}")
    print(f"MFI_SIG_SHA256={hashlib.sha256(signature).hexdigest()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"MFI_PROBE_ERROR={exc}", file=sys.stderr)
        raise SystemExit(1)
