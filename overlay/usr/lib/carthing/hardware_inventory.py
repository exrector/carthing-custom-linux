"""hardware_inventory — per-boot инвентарь возможностей (runtime-contract §Hardware Capability).

DTB/kernel описывают, что плата МОЖЕТ иметь; источник истины — что РЕАЛЬНО отвечает на этом
экземпляре. Каждый boot пробуем runtime-интерфейсы и публикуем capabilities в RuntimeState.
GUI/сервисы делают feature-gate по этому, а не по старым таблицам (напр. LIS2DH12 на Q917 молчит).
Источник целей: carthing-device-backups/HARDWARE-INVENTORY.md.
"""

import fcntl
import os
import struct
import ctypes
from pathlib import Path


def _exists(p) -> bool:
    try:
        return Path(p).exists()
    except Exception:
        return False


def _read_text(p) -> str:
    try:
        return Path(p).read_text(errors="replace").strip()
    except Exception:
        return ""


def _proc_devices_major(name: str) -> int | None:
    for line in _read_text("/proc/devices").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1] == name:
            try:
                return int(parts[0])
            except ValueError:
                return None
    return None


def _ioc(direction: int, magic: int, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (magic << 8) | nr


def _mfi_auth_probe() -> dict:
    """Probe the Apple MFi auth ioctl device without making policy decisions."""
    node = "/sys/bus/i2c/devices/3-0010"
    name = _read_text(f"{node}/name") if _exists(node) else ""
    major = _proc_devices_major("apple_mfi_ioctl")
    out = {
        "mfi_i2c_node": _exists(node),
        "mfi_i2c_name": name,
        "mfi_auth_driver": major is not None,
        "mfi_auth_major": major,
        "mfi_auth_device": _exists("/dev/apple_mfi"),
    }

    if not out["mfi_auth_device"]:
        return out

    # apple_mfi_auth.ko ioctl ABI: struct { uint32 len; uint32 pad; uint64 ptr }.
    # We only read version and certificate length; no challenge/signature side effects.
    def call_ioc(fd: int, nr: int, size: int) -> bytearray:
        buf = ctypes.create_string_buffer(size)
        hdr = bytearray(struct.pack("<IIQ", size, 0, ctypes.addressof(buf)))
        fcntl.ioctl(fd, _ioc(2, 0x77, nr, 16), hdr, True)  # 2 == _IOC_READ
        return bytearray(buf.raw)

    try:
        fd = os.open("/dev/apple_mfi", os.O_RDWR)
        try:
            out["mfi_auth_open"] = True
            out["mfi_auth_version"] = call_ioc(fd, 1, 1)[0]
            cert_len = call_ioc(fd, 4, 2)
            out["mfi_auth_cert_len"] = (cert_len[0] << 8) | cert_len[1]
        finally:
            os.close(fd)
    except Exception as e:
        out["mfi_auth_open"] = False
        out["mfi_auth_error"] = str(e)
    return out


def _alsa_has(suffix: str) -> bool:
    # pcmC0D0p (playback) / pcmC0D0c (capture) и т.п.
    try:
        return any(name.endswith(suffix) or suffix in name
                   for name in os.listdir("/dev/snd"))
    except Exception:
        return False


def _thermal_zones() -> int:
    try:
        return sum(1 for d in os.listdir("/sys/class/thermal") if d.startswith("thermal_zone"))
    except Exception:
        return 0


def probe() -> dict:
    """Снимок фактических возможностей этого экземпляра."""
    caps = {
        "display_drm": _exists("/dev/dri/card0"),
        "backlight": _exists("/sys/class/backlight/aml-bl/brightness"),
        "touch": _exists("/dev/input/event3"),
        "encoder": _exists("/dev/input/event1"),
        "buttons": _exists("/dev/input/event0"),
        "accel_lis2dh12": _exists("/sys/bus/i2c/devices/2-0018/driver"),  # драйвер привязан?
        "als_prox_tmd2772": _exists("/sys/bus/iio/devices/iio:device0"),
        "audio_playback_t9015": _alsa_has("p"),   # pcmC0D0p
        "audio_capture_pdm": _alsa_has("c"),       # pcmC0D0c
        "thermal_zones": _thermal_zones(),
        "zram": _exists("/sys/block/zram0"),
        "hwrng": _exists("/dev/hwrng"),
        "usb_host": _exists("/sys/bus/usb/devices/usb1") or _exists("/sys/bus/usb/devices/usb2"),
        "efuse_usid": _exists("/sys/class/efuse/usid"),
    }
    mfi = _mfi_auth_probe()
    caps.update(mfi)
    caps["mfi_chip"] = bool(mfi.get("mfi_i2c_node"))
    return caps
