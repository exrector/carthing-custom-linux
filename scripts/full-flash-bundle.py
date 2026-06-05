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
    os.environ.setdefault("CARTHING_FLASH_USE_RESTORE_PARTITION", "1")
    os.environ.setdefault("CARTHING_FLASH_WRITE_CHUNK_SECTORS", "512")
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
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        help="leave the device in Burn Mode instead of sending a final reset command",
    )
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
    print("\n=== Restoring BOOTFS with standard restore_partition ===", flush=True)
    dev.restore_partition(0, str(bootfs))
    print("\n=== Restoring ROOT with standard restore_partition ===", flush=True)
    dev.restore_partition(flasher.ROOT_RESTORE_BLOCK_OFFSET, str(rootfs))

    env = bundle / "env.txt"
    if env.exists():
        print("\n=== Restoring env.txt with standard env writer ===", flush=True)
        dev.send_env_file(str(env))
        dev.bulkcmd("saveenv")
    if args.no_reboot:
        print("\n=== DONE. Device left in Burn Mode (--no-reboot). ===", flush=True)
        return 0

    print("\n=== DONE. Sending reset for normal boot. ===", flush=True)
    print("If the reset command times out, that is expected when the device reboots.", flush=True)
    dev.bulkcmd("reset", ignore_timeout=True)
    print("If normal boot does not appear, reconnect USB without holding buttons.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
