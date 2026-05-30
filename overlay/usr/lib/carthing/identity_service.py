"""identity_service — ЕДИНСТВЕННЫЙ источник видимого имени устройства.

runtime-contract.md §Identity. Корень боли «два устройства в рекламе» был в том,
что BLE звался одним именем, classic — другим («Car Thing Audio»). Здесь — ОДНО имя
на ВСЕ транспорты (BLE adv + BLE device.name + classic Local Name + hostname).

Приоритет (по контракту):
  1. CARTHING_BT_ALIAS — только если ЯВНО задан (ручной override).
  2. /sys/class/efuse/usid -> "Car Thing (SN: XXXX)" (заводская идентичность, из кремния).
  3. CARTHING_DEVICE_NAME_FALLBACK.
  4. "Car Thing".

A2DP берёт то же имя через classic_audio_name() — НЕ "Car Thing Audio".
"""

import os
from pathlib import Path

EFUSE_USID_PATH = Path(os.environ.get("CARTHING_EFUSE_USID_PATH", "/sys/class/efuse/usid"))
DEFAULT_NAME = "Car Thing"


def manufacturing_serial() -> str:
    """Последние 4 символа заводского USID. 8559RP88Q917 -> Q917."""
    try:
        usid = EFUSE_USID_PATH.read_text().strip()
    except Exception:
        return ""
    return (usid[-4:] if len(usid) >= 4 else usid).upper()


def _factory_name() -> str:
    serial = manufacturing_serial()
    return f"Car Thing (SN: {serial})" if serial else ""


def visible_name() -> str:
    """Единое видимое имя для ВСЕХ транспортов. Приоритет по контракту."""
    alias = (os.environ.get("CARTHING_BT_ALIAS") or "").strip()
    if alias:
        return alias
    factory = _factory_name()
    if factory:
        return factory
    fallback = (os.environ.get("CARTHING_DEVICE_NAME_FALLBACK") or "").strip()
    if fallback:
        return fallback
    return DEFAULT_NAME


def classic_audio_name() -> str:
    """Имя для A2DP/classic = ТО ЖЕ видимое имя. Никаких отдельных персон."""
    return visible_name()


def hostname() -> str:
    """Имя для ОС/SSH-приглашения. То же имя (скобки/пробелы busybox разворачивает в PS1)."""
    return visible_name()
