"""Локальный аудиовыход Car Thing: T9015 DAC через голые ALSA ioctl.

АРХИТЕКТУРНОЕ МЕСТО (читай, Codex, прежде чем трогать):
  Это НИЖНИЙ слой будущего endpoint'а «Car Thing line-out» в Routes:
    iPhone --BT A2DP--> a2dp_bridge --PCM--> T9015AudioOutput --analog--> провод
  Слой умеет ТОЛЬКО играть готовый PCM (S16_LE). Декод AAC/SBC -> PCM — слой ВЫШЕ
  (кандидаты: /dev/audiodsp0 — задача B ранбука; либо программный декодер).
  Когда декод появится, этот модуль регистрируется в route_outputs как
  полноправный audio-output endpoint (см. RUNBOOK-NEXT §дизайн задачи №5 и
  carthing-vision: «мир делится на сервисы/endpoint'ы»).

ДОКАЗАТЕЛЬНАЯ БАЗА (не переоткрывать):
  - 2026-05-24: тракт доказан на nixos-ядре — carthing-release-architecture/
    docs/hardware-capability-inventory.md §«Audio Output — T9015 Playback»
    (PVERSION 2.0.13; HW_REFINE cmask=0x0007f300; HW_PARAMS rate 48000/1
    msbits=16; запись 3с синуса принята).
  - 2026-06-12: живое buildroot-ядро несёт тот же тракт (dmesg:
    «T9015 acodec used by auge, tdmout:0», TDM lane_cnt=4), узел pcmC0D0p есть.
  - DTS-патчи: carthing-device-backups/artifacts/T9015-PLAYBACK-DTS-PATCHES.md.

ПОЧЕМУ ГОЛЫЕ ioctl: на устройстве НЕТ libasound/aplay/tinyalsa, и тащить их в
rootfs не хочется (минимализм). Структуры ниже — uapi ядра 4.9
(include/uapi/sound/asound.h), aarch64 (unsigned long = 8 байт).

CLI-проверка железа (звук/осциллограф — владелец):
    python3 /usr/lib/carthing/audio_out_t9015.py tone 3      # 440 Гц, 3 с
    python3 /usr/lib/carthing/audio_out_t9015.py raw f.raw   # s16le/48k/stereo

[CLAUDE 2026-06-12] первый камень «работы над чипом» по слову владельца.
"""
from __future__ import annotations

import fcntl
import math
import os
import struct
import sys

PCM_DEV = os.environ.get("CARTHING_PCM_DEV", "/dev/snd/pcmC0D0p")

# ── uapi/sound/asound.h (ядро 4.9) ────────────────────────────────────────────
# Маски (индексы параметров): ACCESS=0, FORMAT=1, SUBFORMAT=2 (FIRST_MASK=0)
_PARAM_ACCESS, _PARAM_FORMAT, _PARAM_SUBFORMAT = 0, 1, 2
# Интервалы: FIRST_INTERVAL=8 → индекс в массиве = (param - 8)
_PARAM_SAMPLE_BITS = 8
_PARAM_FRAME_BITS = 9
_PARAM_CHANNELS = 10
_PARAM_RATE = 11
# Значения
_ACCESS_RW_INTERLEAVED = 3          # обычный write(), без mmap
_FORMAT_S16_LE = 2
_SUBFORMAT_STD = 0

# Раскладка struct snd_pcm_hw_params (608 байт, проверено по 4.9):
#   u32 flags
#   snd_mask masks[3] + mres[5]   — 8 масок × 32 байта (u32 bits[8])
#   snd_interval intervals[12] + ires[9] — 21 × 12 байт (u32 min,max,flags)
#   u32 rmask, cmask, info, msbits, rate_num, rate_den
#   unsigned long fifo_size (8, выровнено)
#   u8 reserved[64]
_HW_PARAMS_SIZE = 4 + 8 * 32 + 21 * 12 + 6 * 4 + 8 + 64   # = 608
assert _HW_PARAMS_SIZE == 608

def _ioc(direction: int, nr: int, size: int) -> int:
    # _IOC(dir, 'A', nr, size); dir: 0=none, 1=W, 2=R, 3=RW (в терминах _IOC_*)
    return (direction << 30) | (size << 16) | (ord("A") << 8) | nr

_IOCTL_PVERSION = _ioc(2, 0x00, 4)                       # _IOR('A',0x00,int)
_IOCTL_HW_REFINE = _ioc(3, 0x10, _HW_PARAMS_SIZE)        # _IOWR
_IOCTL_HW_PARAMS = _ioc(3, 0x11, _HW_PARAMS_SIZE)        # _IOWR
_IOCTL_PREPARE = _ioc(0, 0x40, 0)                        # _IO
_IOCTL_DRAIN = _ioc(0, 0x44, 0)                          # _IO


class _HwParams:
    """Сборка/разбор snd_pcm_hw_params. Всё в little-endian (aarch64)."""

    def __init__(self):
        self.flags = 0
        self.masks = [bytearray(32) for _ in range(8)]
        # интервал = (min, max, flags); «любое» = (0, 0xFFFFFFFF, 0)
        self.intervals = [(0, 0xFFFFFFFF, 0) for _ in range(21)]
        self.rmask = 0xFFFFFFFF       # просим ядро уточнить все параметры
        self.cmask = 0
        self.info = 0
        self.msbits = 0
        self.rate_num = 0
        self.rate_den = 0
        self.fifo_size = 0

    def set_mask_bit(self, param: int, bit: int) -> None:
        # эксклюзивный выбор: чистим маску и ставим один бит
        m = bytearray(32)
        m[bit // 8] |= 1 << (bit % 8)
        self.masks[param] = m

    def set_interval(self, param: int, value: int) -> None:
        # фикс-значение: min=max=value, флаг integer (бит 2 => 0x4)
        self.intervals[param - 8] = (value, value, 0x4)

    def pack(self) -> bytearray:
        buf = bytearray()
        buf += struct.pack("<I", self.flags)
        for m in self.masks:
            buf += m
        for lo, hi, fl in self.intervals:
            buf += struct.pack("<III", lo, hi, fl)
        buf += struct.pack("<6I", self.rmask, self.cmask, self.info,
                           self.msbits, self.rate_num, self.rate_den)
        buf += struct.pack("<Q", self.fifo_size)
        buf += bytes(64)
        assert len(buf) == _HW_PARAMS_SIZE, len(buf)
        return buf

    @staticmethod
    def unpack_info(buf: (bytes | bytearray)) -> dict:
        off = 4 + 8 * 32 + 21 * 12
        rmask, cmask, info, msbits, rate_num, rate_den = struct.unpack_from("<6I", buf, off)
        return {"cmask": cmask, "info": info, "msbits": msbits,
                "rate_num": rate_num, "rate_den": rate_den}


class T9015AudioOutput:
    """PCM-выход на T9015 DAC. Интерфейс для слоя выше:
        out = T9015AudioOutput(); out.open(); out.write(pcm_s16le); out.close()
    Codex: при интеграции в runtime НЕ играть из BT event-loop — писать из
    отдельного потока/процесса (write() блокируется на глубине буфера ALSA;
    это ЖЕЛАЕМОЕ поведение для темпа, но смертельное для event-loop — тот же
    урок, что с рендером, см. carthing-debug-log 2026-06-12)."""

    def __init__(self, device: str = PCM_DEV, rate: int = 48000, channels: int = 2):
        self.device = device
        self.rate = rate
        self.channels = channels
        self.fd = -1

    def open(self) -> dict:
        self.fd = os.open(self.device, os.O_WRONLY)
        ver = bytearray(4)
        fcntl.ioctl(self.fd, _IOCTL_PVERSION, ver)
        version = struct.unpack("<I", ver)[0]

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
        return {"alsa_version": f"{version >> 16}.{(version >> 8) & 0xFF}.{version & 0xFF}",
                **info}

    def write(self, pcm: bytes) -> int:
        # write() на PCM-узле блокируется по мере заполнения кольцевого буфера —
        # темп задаёт железо. Возвращает записанные БАЙТЫ.
        # XRUN (underrun): если буфер опустел между кусками live-потока, ядро
        # отвечает EPIPE (BrokenPipeError) — это НЕ фатал, штатное восстановление:
        # PREPARE и продолжить запись (пауза слышна как короткий провал).
        total = 0
        view = memoryview(pcm)
        while total < len(pcm):
            try:
                total += os.write(self.fd, view[total:total + 32768])
            except BrokenPipeError:
                self.xruns = getattr(self, "xruns", 0) + 1
                fcntl.ioctl(self.fd, _IOCTL_PREPARE)
        return total

    def drain(self) -> None:
        try:
            fcntl.ioctl(self.fd, _IOCTL_DRAIN)
        except OSError:
            pass

    def close(self) -> None:
        if self.fd >= 0:
            self.drain()
            os.close(self.fd)
            self.fd = -1

    # ── утилиты проверки железа ───────────────────────────────────────────────
    def tone(self, seconds: float = 3.0, freq: float = 440.0, amplitude: int = 12000) -> int:
        n = int(self.rate * seconds)
        pcm = bytearray()
        for i in range(n):
            v = int(amplitude * math.sin(2 * math.pi * freq * i / self.rate))
            pcm += struct.pack("<hh", v, v)[:2 * self.channels]
        return self.write(bytes(pcm))


def _main(argv):
    cmd = argv[1] if len(argv) > 1 else "tone"
    out = T9015AudioOutput()
    info = out.open()
    print(f"T9015 open: {info}")
    try:
        if cmd == "tone":
            secs = float(argv[2]) if len(argv) > 2 else 3.0
            written = out.tone(secs)
            print(f"tone {secs}s written={written} bytes")
        elif cmd == "raw":
            data = open(argv[2], "rb").read()
            written = out.write(data)
            print(f"raw written={written} bytes")
        else:
            print("usage: audio_out_t9015.py tone [sec] | raw <file.s16le-48k-stereo>")
            return 2
    finally:
        out.close()
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
