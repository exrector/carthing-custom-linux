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

NAME_BASE = os.environ.get("CARTHING_NAME_BASE", "CarThing")


def name_from_mac(mac: str = BD_ADDRESS, base: str = NAME_BASE) -> str:
    """The one unique device name, derived from the controller MAC:
    e.g. 30:E3:D6:00:5F:A4 -> CarThing-30E3D6005FA4."""
    suffix = (mac or "").replace(":", "").replace("-", "").upper()
    return f"{base}-{suffix}" if suffix else base


def device_name() -> str:
    """Single source of truth for the device's name. Prefer the OS hostname
    (set early from the MAC, so `ssh root@…` shows it); fall back to computing
    it from the MAC if the hostname is unset/generic."""
    try:
        host = socket.gethostname()
    except Exception:
        host = ""
    if host and host.lower().startswith(NAME_BASE.lower()):
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
