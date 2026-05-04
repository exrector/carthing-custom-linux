#!/usr/bin/env python3

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = REPO_ROOT / "artifacts" / "flash-device1"
MANUAL_DIR = BUNDLE_DIR / "manual"
ROOTFS_IMG = BUNDLE_DIR / "rootfs.img"
ROOT_RESTORE_BLOCK_OFFSET = 352256

sys.path.insert(0, str(MANUAL_DIR))

from superbird_device import SuperbirdDevice, enter_burn_mode, find_device  # type: ignore  # noqa: E402


def get_device() -> SuperbirdDevice:
    print("finding device...")
    device_status = find_device(silent=True)
    device = SuperbirdDevice()

    if device_status not in ("usb", "usb-burn"):
        print("device could not be found. please try again.")
        sys.exit(1)

    if device_status == "usb":
        print("entering usb burn mode:\n")
        device = enter_burn_mode(device)
        print()

    if device is None:
        print("device could not be found. please try again.")
        sys.exit(1)

    print("device found!")
    return device


def main() -> int:
    if not ROOTFS_IMG.is_file():
        print(f"missing rootfs image: {ROOTFS_IMG}")
        return 1

    print("WARNING: this writes only rootfs.img to device №1.")
    print("bootfs.bin and env.txt are left unchanged.\n")
    input("boot device №1 into Burn Mode, then press enter >>> ")

    device = get_device()
    device.bulkcmd("amlmmc key", ignore_timeout=True)

    print("\nwriting root filesystem only...")
    device.restore_partition(ROOT_RESTORE_BLOCK_OFFSET, str(ROOTFS_IMG))
    print("\nrootfs write complete. power-cycle the device and test normal boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
