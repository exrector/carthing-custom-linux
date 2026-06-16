#!/usr/bin/env python3
"""Car Thing — прошивка чистого образа. Одна команда.

Запуск (устройство в Maskrom, см. README шаг 1):
    python3 tools/flash.py

Делает по порядку:
  1. загружает временный U-Boot (BL2) -> переводит плату в USB Burn Mode
  2. amlmmc part 1 / amlmmc key
  3. bootfs.bin -> sector 0
  4. rootfs.img -> sector 352256
  5. env.txt -> env + saveenv
  6. reset

macOS-safe параметры (block 32768, restore_partition) выставляются автоматически.
"""
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

# boot/superbird.bl2.encrypted.bin читается по относительному пути
os.chdir(IMAGE)

spec = importlib.util.spec_from_file_location("flasher", TOOLS / "_flasher.py")
flasher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flasher)

print("=== Загрузка временного U-Boot (BL2) -> USB Burn Mode ===", flush=True)
dev = flasher.get_device()

dev.bulkcmd("amlmmc part 1", ignore_timeout=True)
dev.bulkcmd("amlmmc key", ignore_timeout=True)

print("=== bootfs.bin -> sector 0 ===", flush=True)
dev.restore_partition(0, str(IMAGE / "bootfs.bin"))

print("=== rootfs.img -> sector 352256 ===", flush=True)
dev.restore_partition(flasher.ROOT_RESTORE_BLOCK_OFFSET, str(IMAGE / "rootfs.img"))

print("=== env ===", flush=True)
env_bytes = (IMAGE / "env.txt").read_text(encoding="utf-8").encode("ascii")
dev.bulkcmd("amlmmc env", ignore_timeout=True)
dev.write(dev.ADDR_TMP, env_bytes)
dev.bulkcmd(f"env import -t {hex(dev.ADDR_TMP)} {hex(len(env_bytes))}", ignore_timeout=True)
dev.bulkcmd("saveenv", ignore_timeout=True)

print("=== reset ===", flush=True)
dev.bulkcmd("reset", ignore_timeout=True)
print("\nГОТОВО. Переткни USB-кабель БЕЗ кнопок — холодная загрузка.", flush=True)
