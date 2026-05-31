#!/usr/bin/env python3
"""Full flash a Car Thing bundle in USB Burn Mode.

Writes:
- bootfs.bin at sector 0
- rootfs.img at sector 352256

The low-level Amlogic writer is reused from scripts/flash-device1-rootfs-only.py.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FLASHER = REPO_ROOT / "scripts/flash-device1-rootfs-only.py"


def import_flasher(bundle: Path):
    os.environ["CARTHING_FLASH_BUNDLE_DIR"] = str(bundle)
    os.environ.setdefault("CARTHING_FLASH_USE_RESTORE_PARTITION", "0")
    os.environ.setdefault("CARTHING_FLASH_WRITE_CHUNK_SECTORS", "1024")
    os.environ.setdefault("CARTHING_FLASH_TRANSFER_BLOCK_SIZE", "32768")
    spec = importlib.util.spec_from_file_location("carthing_flasher", FLASHER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import flasher: {FLASHER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path, help="flash bundle containing bootfs.bin and rootfs.img")
    args = parser.parse_args()

    bundle = args.bundle.resolve()
    bootfs = bundle / "bootfs.bin"
    rootfs = bundle / "rootfs.img"
    for path in (bootfs, rootfs):
        if not path.exists():
            raise SystemExit(f"missing required image: {path}")

    flasher = import_flasher(bundle)
    print(f"=== FULL FLASH bundle: {bundle} ===", flush=True)
    print("Device must already be in USB Burn Mode (Amlogic GX-CHIP 1b8e:c003).", flush=True)

    dev = flasher.get_device()
    dev.bulkcmd("amlmmc part 1", ignore_timeout=True)
    dev.bulkcmd("amlmmc key", ignore_timeout=True)
    dev = flasher.write_image(dev, str(bootfs), 0, "BOOTFS")
    dev = flasher.write_image(dev, str(rootfs), flasher.ROOT_RESTORE_BLOCK_OFFSET, "ROOT")
    print("\n=== DONE. Power-cycle without buttons for normal boot. ===", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
