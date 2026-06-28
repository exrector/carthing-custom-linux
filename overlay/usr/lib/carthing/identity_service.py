"""Single visible identity for the LE accessory."""

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


def hostname() -> str:
    return visible_name()
