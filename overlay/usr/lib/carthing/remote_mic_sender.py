#!/usr/bin/env python3
"""Direct ALSA PCM capture used by the Bluetooth session plane."""

from __future__ import annotations

import argparse
import errno
import fcntl
import os
import socket
import struct
import sys
import time

PCM_DEV = os.environ.get("CARTHING_MIC_PCM_DEV", "/dev/snd/pcmC0D1c")
DEFAULT_HOST = os.environ.get("CARTHING_MIC_HOST", "172.16.42.1")
DEFAULT_PORT = int(os.environ.get("CARTHING_MIC_PORT", "49321"))
DEFAULT_RATE = int(os.environ.get("CARTHING_MIC_RATE", "48000"))
DEFAULT_CHANNELS = int(os.environ.get("CARTHING_MIC_CHANNELS", "2"))

_PARAM_ACCESS, _PARAM_FORMAT, _PARAM_SUBFORMAT = 0, 1, 2
_PARAM_SAMPLE_BITS = 8
_PARAM_FRAME_BITS = 9
_PARAM_CHANNELS = 10
_PARAM_RATE = 11
_ACCESS_RW_INTERLEAVED = 3
_FORMAT_S16_LE = 2
_SUBFORMAT_STD = 0
_HW_PARAMS_SIZE = 4 + 8 * 32 + 21 * 12 + 6 * 4 + 8 + 64


def _ioc(direction: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord("A") << 8) | nr


_IOCTL_PVERSION = _ioc(2, 0x00, 4)
_IOCTL_HW_PARAMS = _ioc(3, 0x11, _HW_PARAMS_SIZE)
_IOCTL_PREPARE = _ioc(0, 0x40, 0)
_IOCTL_DROP = _ioc(0, 0x43, 0)


class _HwParams:
    def __init__(self):
        self.flags = 0
        self.masks = [bytearray(32) for _ in range(8)]
        self.intervals = [(0, 0xFFFFFFFF, 0) for _ in range(21)]
        self.rmask = 0xFFFFFFFF
        self.cmask = 0
        self.info = 0
        self.msbits = 0
        self.rate_num = 0
        self.rate_den = 0
        self.fifo_size = 0

    def set_mask_bit(self, param: int, bit: int) -> None:
        mask = bytearray(32)
        mask[bit // 8] |= 1 << (bit % 8)
        self.masks[param] = mask

    def set_interval(self, param: int, value: int) -> None:
        self.intervals[param - 8] = (value, value, 0x4)

    def pack(self) -> bytearray:
        buf = bytearray()
        buf += struct.pack("<I", self.flags)
        for mask in self.masks:
            buf += mask
        for lo, hi, flags in self.intervals:
            buf += struct.pack("<III", lo, hi, flags)
        buf += struct.pack(
            "<6I",
            self.rmask,
            self.cmask,
            self.info,
            self.msbits,
            self.rate_num,
            self.rate_den,
        )
        buf += struct.pack("<Q", self.fifo_size)
        buf += bytes(64)
        assert len(buf) == _HW_PARAMS_SIZE, len(buf)
        return buf

    @staticmethod
    def unpack_info(buf: bytes | bytearray) -> dict:
        offset = 4 + 8 * 32 + 21 * 12
        _rmask, cmask, info, msbits, rate_num, rate_den = struct.unpack_from(
            "<6I", buf, offset
        )
        return {
            "cmask": cmask,
            "info": info,
            "msbits": msbits,
            "rate_num": rate_num,
            "rate_den": rate_den,
        }


class AlsaPcmCapture:
    def __init__(self, device: str, rate: int, channels: int):
        self.device = device
        self.rate = rate
        self.channels = channels
        self.fd = -1

    def open(self) -> dict:
        self.fd = os.open(self.device, os.O_RDONLY)
        version_buf = bytearray(4)
        fcntl.ioctl(self.fd, _IOCTL_PVERSION, version_buf)
        version = struct.unpack("<I", version_buf)[0]

        hw = _HwParams()
        hw.set_mask_bit(_PARAM_ACCESS, _ACCESS_RW_INTERLEAVED)
        hw.set_mask_bit(_PARAM_FORMAT, _FORMAT_S16_LE)
        hw.set_mask_bit(_PARAM_SUBFORMAT, _SUBFORMAT_STD)
        hw.set_interval(_PARAM_CHANNELS, self.channels)
        hw.set_interval(_PARAM_RATE, self.rate)
        hw.set_interval(_PARAM_SAMPLE_BITS, 16)
        hw.set_interval(_PARAM_FRAME_BITS, 16 * self.channels)
        buf = hw.pack()
        fcntl.ioctl(self.fd, _IOCTL_HW_PARAMS, buf)
        info = _HwParams.unpack_info(buf)
        fcntl.ioctl(self.fd, _IOCTL_PREPARE)
        return {
            "alsa_version": (
                f"{version >> 16}.{(version >> 8) & 0xFF}.{version & 0xFF}"
            ),
            **info,
        }

    def read(self, frames: int) -> bytes:
        size = max(1, frames) * self.channels * 2
        while True:
            try:
                return os.read(self.fd, size)
            except OSError as exc:
                if exc.errno == errno.EPIPE:
                    fcntl.ioctl(self.fd, _IOCTL_PREPARE)
                    continue
                raise

    def close(self) -> None:
        if self.fd < 0:
            return
        try:
            fcntl.ioctl(self.fd, _IOCTL_DROP)
        except OSError:
            pass
        os.close(self.fd)
        self.fd = -1


def send_header(sock: socket.socket, rate: int, channels: int) -> None:
    sock.sendall(f"CARTHING_MIC_RAW s16le {rate} {channels}\n".encode("ascii"))


def run_capture(args) -> int:
    cap = AlsaPcmCapture(args.device, args.rate, args.channels)
    info = cap.open()
    print(
        f"remote_mic_sender: capture open device={args.device} "
        f"rate={args.rate} channels={args.channels} info={info}",
        file=sys.stderr,
    )
    try:
        with socket.create_connection((args.host, args.port), timeout=5) as sock:
            send_header(sock, args.rate, args.channels)
            deadline = time.monotonic() + args.seconds if args.seconds > 0 else None
            while deadline is None or time.monotonic() < deadline:
                payload = cap.read(args.frames)
                if not payload:
                    break
                sock.sendall(payload)
    finally:
        cap.close()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--device", default=PCM_DEV)
    parser.add_argument("--rate", type=int, default=DEFAULT_RATE)
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    parser.add_argument("--frames", type=int, default=1024)
    parser.add_argument("--seconds", type=float, default=0.0)
    args = parser.parse_args(argv)
    return run_capture(args)


if __name__ == "__main__":
    raise SystemExit(main())
