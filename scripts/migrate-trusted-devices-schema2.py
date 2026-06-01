#!/usr/bin/env python3
"""Migrate trusted-devices.json to the route-graph registry schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "lib" / "carthing"
sys.path.insert(0, str(LIB))

from app_state import DEFAULT_TRUSTED_DEVICES_PATH  # noqa: E402
from trusted_device_registry import TrustedDeviceRegistry  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_TRUSTED_DEVICES_PATH,
        help="trusted-devices.json path",
    )
    args = parser.parse_args()
    path = Path(args.path)
    registry = TrustedDeviceRegistry(path).migrate_legacy_in_place()
    print(f"migrated {path}: {len(registry.devices)} devices")


if __name__ == "__main__":
    main()
