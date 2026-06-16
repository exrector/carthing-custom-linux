#!/usr/bin/env python3
"""Car Thing — прошивка только bootfs.bin (ядро). rootfs/env/logo не трогает."""
import os
import importlib.util
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
IMAGE = REPO / "image"

os.environ["CARTHING_FLASH_BUNDLE_DIR"] = str(IMAGE)
os.environ.setdefault("CARTHING_FLASH_TRANSFER_BLOCK_SIZE", "32768")
os.environ.setdefault("CARTHING_FLASH_WRITE_CHUNK_SECTORS", "512")
os.environ.setdefault("CARTHING_FLASH_USE_RESTORE_PARTITION", "1")

os.chdir(IMAGE)

spec = importlib.util.spec_from_file_location("flasher", TOOLS / "_flasher.py")
flasher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flasher)

print("=== Загрузка временного U-Boot (BL2) -> USB Burn Mode ===", flush=True)
dev = flasher.get_device()

dev.bulkcmd("amlmmc part 1", ignore_timeout=True)
dev.bulkcmd("amlmmc key", ignore_timeout=True)

print("=== bootfs.bin -> sector 0 (только ядро, rootfs не трогаем) ===", flush=True)
dev.restore_partition(0, str(IMAGE / "bootfs.bin"))

print("=== reset ===", flush=True)
dev.bulkcmd("reset", ignore_timeout=True)
print("\nГОТОВО. Переткни USB БЕЗ кнопок — холодная загрузка.", flush=True)
