"""hardware_inventory — per-boot инвентарь возможностей (runtime-contract §Hardware Capability).

DTB/kernel описывают, что плата МОЖЕТ иметь; источник истины — что РЕАЛЬНО отвечает на этом
экземпляре. Каждый boot пробуем runtime-интерфейсы и публикуем capabilities в RuntimeState.
GUI/сервисы делают feature-gate по этому, а не по старым таблицам (напр. LIS2DH12 на Q917 молчит).
Источник целей: carthing-device-backups/HARDWARE-INVENTORY.md.
"""

import os
from pathlib import Path


def _exists(p) -> bool:
    try:
        return Path(p).exists()
    except Exception:
        return False


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
    return {
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
        "mfi_chip": _exists("/dev/i2c-3"),
        "zram": _exists("/sys/block/zram0"),
        "hwrng": _exists("/dev/hwrng"),
        "usb_host": _exists("/sys/bus/usb/devices/usb1") or _exists("/sys/bus/usb/devices/usb2"),
        "efuse_usid": _exists("/sys/class/efuse/usid"),
    }
