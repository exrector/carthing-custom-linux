import os
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


def ensure_runtime_paths():
    src_dir = str(SRC_DIR)
    lib_dir = str(LIB_DIR)

    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    if lib_dir not in sys.path:
        sys.path.insert(0, lib_dir)


ensure_runtime_paths()
