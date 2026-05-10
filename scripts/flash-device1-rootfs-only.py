#!/usr/bin/env python3

import os
import sys
import time
import gc
from pathlib import Path
from struct import pack

import usb.util
import pyamlboot.pyamlboot as _pab


REPO_ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIR = REPO_ROOT / "artifacts" / "flash-device1"
MANUAL_DIR = BUNDLE_DIR / "manual"
ROOTFS_IMG = BUNDLE_DIR / "rootfs.img"
ROOT_RESTORE_BLOCK_OFFSET = 352256

sys.path.insert(0, str(MANUAL_DIR))


_REQ_WR_LARGE_MEM = 0x11


def _patched_writeLargeMemory(self, address, data, blockLength=64, appendZeros=False):
    if appendZeros:
        append = len(data) % blockLength
        if append:
            data = data + pack("b", 0) * append
    elif len(data) % blockLength != 0:
        raise ValueError("Large Data must be a multiple of block length")

    blockCount = int(len(data) / blockLength)
    if len(data) % blockLength > 0:
        blockCount += 1

    controlData = pack("<IIII", address, len(data), 0, 0)
    cfg = self.dev.get_active_configuration()
    intf = cfg[(0, 0)]
    ep = usb.util.find_descriptor(
        intf,
        custom_match=lambda e: usb.util.endpoint_direction(e.bEndpointAddress) == usb.util.ENDPOINT_OUT,
    )

    last_err = None
    for _ in range(10):
        try:
            self.dev.ctrl_transfer(0x40, _REQ_WR_LARGE_MEM, blockLength, blockCount, controlData, None)
            last_err = None
            break
        except Exception as exc:
            last_err = exc
            time.sleep(0.5)
    if last_err is not None:
        raise last_err

    offset = 0
    while blockCount > 0:
        last_err = None
        for _ in range(5):
            try:
                ep.write(data[offset : offset + blockLength], None)
                last_err = None
                break
            except Exception as exc:
                last_err = exc
                time.sleep(0.2)
        if last_err is not None:
            raise last_err
        offset += blockLength
        blockCount -= 1


_pab.AmlogicSoC._writeLargeMemory = _patched_writeLargeMemory

from superbird_device import SuperbirdDevice, enter_burn_mode, find_device  # type: ignore  # noqa: E402


SuperbirdDevice.TRANSFER_BLOCK_SIZE = 32768
SuperbirdDevice.WRITE_CHUNK_SIZE = 512


ADDR_TMP = 0x13000000
TRANSFER_BLOCK_SIZE = 32768
WRITE_CHUNK_SIZE = 256 * 1024
SECTOR = 512
MAX_RETRIES = 12
RECONNECT_WAIT = 4.0


def raw_bulkcmd(dev: SuperbirdDevice, cmd: str):
    resp = dev.device.bulkCmd(cmd)
    response = dev.decode(resp)
    if "success" not in response:
        raise RuntimeError(f"not success: {cmd!r}: {response!r}")
    time.sleep(0.05)


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


def make_dev(max_retries: int = 8, initial_settle: float = 2.0) -> SuperbirdDevice:
    import usb.core as _uc

    last_err = None
    for attempt in range(max_retries):
        dev = None
        try:
            if attempt > 0:
                try:
                    for usb_dev in _uc.find(find_all=True, idVendor=0x1B8E, idProduct=0xC003):
                        usb.util.dispose_resources(usb_dev)
                except Exception:
                    pass
                gc.collect()
                time.sleep(2.0)
            else:
                time.sleep(initial_settle)

            dev = SuperbirdDevice()
            time.sleep(1.0)
            raw_bulkcmd(dev, "amlmmc part 1")
            raw_bulkcmd(dev, "mmc dev 1 0")
            raw_bulkcmd(dev, "amlmmc key")
            return dev
        except SystemExit:
            raise
        except Exception as exc:
            if dev is not None:
                try:
                    usb.util.dispose_resources(dev.device.dev)
                except Exception:
                    pass
            last_err = exc
            print(f"  ~ make_dev #{attempt + 1}/{max_retries}: {exc.__class__.__name__}: {str(exc)[:80]}")

    raise RuntimeError(f"make_dev failed {max_retries}x last={last_err}")


def write_chunk(dev: SuperbirdDevice, data: bytes, target_blk: int, blk_count: int):
    dev.device.writeLargeMemory(ADDR_TMP, data, TRANSFER_BLOCK_SIZE, appendZeros=True)
    dev.bulkcmd(f"amlmmc write 1 {hex(ADDR_TMP)} {hex(target_blk)} {hex(blk_count)}", ignore_timeout=True)


def write_image(dev: SuperbirdDevice, infile: str, sector_offset: int, label: str):
    file_size = os.path.getsize(infile)
    print(f"\n>>> writing {label}: {infile} ({file_size // 1024 // 1024} MB) -> sector {sector_offset}")
    print(f"    block={TRANSFER_BLOCK_SIZE}B chunk={WRITE_CHUNK_SIZE // 1024}KB")

    with open(infile, "rb") as f:
        offset_bytes = 0
        start = time.time()
        failures = 0

        while offset_bytes < file_size:
            remaining = file_size - offset_bytes
            this_chunk = min(WRITE_CHUNK_SIZE, remaining)
            if this_chunk % SECTOR != 0:
                this_chunk = ((this_chunk + SECTOR - 1) // SECTOR) * SECTOR

            data = f.read(this_chunk)
            if len(data) < this_chunk:
                data = data + b"\x00" * (this_chunk - len(data))

            target_blk = sector_offset + (offset_bytes // SECTOR)
            blk_count = this_chunk // SECTOR
            ok = False

            for attempt in range(MAX_RETRIES):
                try:
                    write_chunk(dev, data, target_blk, blk_count)
                    ok = True
                    break
                except Exception as exc:
                    failures += 1
                    print(f"  ! {exc.__class__.__name__} blk={hex(target_blk)} #{attempt + 1}/{MAX_RETRIES}: {str(exc)[:80]}")
                    time.sleep(RECONNECT_WAIT)
                    dev = make_dev()
                    print("  + reconnected")

            if not ok:
                print(f"FATAL: {label} chunk failed {MAX_RETRIES}x")
                sys.exit(2)

            offset_bytes += this_chunk
            elapsed = time.time() - start
            speed = (offset_bytes / elapsed / 1024 / 1024) if elapsed > 0 else 0.0
            pct = offset_bytes * 100 // file_size
            print(
                f"  {label} {pct}% {offset_bytes // 1024 // 1024}/{file_size // 1024 // 1024} MB "
                f"at {speed:.2f} MB/s blk={hex(target_blk)} f={failures}"
            )

    print(f"DONE {label}: failures={failures}")
    return dev


def main() -> int:
    if not ROOTFS_IMG.is_file():
        print(f"missing rootfs image: {ROOTFS_IMG}")
        return 1

    print("WARNING: this writes only rootfs.img to device №1.")
    print("bootfs.bin and env.txt are left unchanged.\n")
    input("boot device №1 into Burn Mode, then press enter >>> ")

    dev = get_device()
    dev.bulkcmd("amlmmc part 1", ignore_timeout=True)
    dev.bulkcmd("amlmmc key", ignore_timeout=True)
    dev = write_image(dev, str(ROOTFS_IMG), ROOT_RESTORE_BLOCK_OFFSET, "ROOT")
    print("\nrootfs write complete. power-cycle the device and test normal boot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
