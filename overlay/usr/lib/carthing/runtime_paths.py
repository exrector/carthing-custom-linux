import os
import socket
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parent
REMOTE_DIR = SRC_DIR.parent

LIB_DIR = Path(os.environ.get("CAR_THING_LIB", str(REMOTE_DIR / "lib"))).expanduser()
KEYSTORE_PATH = Path(
    os.environ.get("CAR_THING_KEYSTORE", str(REMOTE_DIR / "keys.json"))
).expanduser()

TRANSPORT = os.environ.get("CAR_THING_TRANSPORT", "serial:/dev/ttyS1,3000000")
BD_ADDRESS = os.environ.get("CAR_THING_BD_ADDRESS", "30:E3:D6:00:5F:A4")

EFUSE_USID_PATH = Path(os.environ.get("CARTHING_EFUSE_USID_PATH", "/sys/class/efuse/usid"))
DEVICE_NAME = os.environ.get("CARTHING_DEVICE_NAME") or os.environ.get("CARTHING_BT_ALIAS")
NAME_BASE = os.environ.get("CARTHING_NAME_BASE", "CarThing")
FACTORY_NAME_PREFIX = os.environ.get("CARTHING_FACTORY_NAME_PREFIX", "Car Thing")


def name_from_mac(mac: str = BD_ADDRESS, base: str = NAME_BASE) -> str:
    """Unique name from a controller MAC: 30:E3:D6:00:5F:A4 -> CarThing-30E3D6005FA4."""
    suffix = (mac or "").replace(":", "").replace("-", "").upper()
    return f"{base}-{suffix}" if suffix else base


def manufacturing_serial() -> str:
    """Factory serial from efuse USID. Example: 8559RP88Q917 -> Q917."""
    try:
        usid = EFUSE_USID_PATH.read_text().strip()
    except Exception:
        return ""
    if len(usid) >= 4:
        return usid[-4:].upper()
    return usid.upper()


def factory_device_name() -> str:
    serial = manufacturing_serial()
    return f"{FACTORY_NAME_PREFIX} (SN: {serial})" if serial else ""


def configured_device_name() -> str:
    return (DEVICE_NAME or "").strip()


def device_name() -> str:
    """Single source of truth for the user-visible device name."""
    factory = factory_device_name()
    if factory:
        return factory
    configured = configured_device_name()
    if configured:
        return configured
    try:
        host = socket.gethostname()
    except Exception:
        host = ""
    if host and host not in {"(none)", "localhost"}:
        return host
    return name_from_mac()


def ensure_runtime_paths():
    src_dir = str(SRC_DIR)
    lib_dir = str(LIB_DIR)

    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)


ensure_runtime_paths()
