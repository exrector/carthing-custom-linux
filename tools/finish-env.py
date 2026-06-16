#!/usr/bin/env python3
"""Дописать только env + saveenv + reset (если основная запись уже прошла).

Использовать, когда bootfs+rootfs уже записаны, а нужно только обновить env
и перезагрузить. Устройство должно быть в USB Burn Mode (1b8e:c003).

    python3 tools/finish-env.py
"""
import os
import importlib.util
from pathlib import Path

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent
IMAGE = REPO / "image"

os.environ["CARTHING_FLASH_BUNDLE_DIR"] = str(IMAGE)
os.environ.setdefault("CARTHING_FLASH_TRANSFER_BLOCK_SIZE", "32768")
os.chdir(IMAGE)

spec = importlib.util.spec_from_file_location("flasher", TOOLS / "_flasher.py")
flasher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flasher)

dev = flasher.get_device()
env_bytes = (IMAGE / "env.txt").read_text(encoding="utf-8").encode("ascii")
dev.bulkcmd("amlmmc env", ignore_timeout=True)
dev.write(dev.ADDR_TMP, env_bytes)
dev.bulkcmd(f"env import -t {hex(dev.ADDR_TMP)} {hex(len(env_bytes))}", ignore_timeout=True)
dev.bulkcmd("saveenv", ignore_timeout=True)
dev.bulkcmd("reset", ignore_timeout=True)
print("env записан, reset отправлен. Переткни USB БЕЗ кнопок.", flush=True)
