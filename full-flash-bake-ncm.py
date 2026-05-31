#!/usr/bin/env python3
# Полный флеш ЗАПЕЧЁННОГО образа на №2: bootfs.bin@0 (курированный kernel) + rootfs.img@352256 (наш runtime).
# Переиспользует проверенный flash-device1-rootfs-only.py. Device должен быть в BURN MODE (1b8e:c003).
import os, importlib.util
REPO = "(local repo root)"
BUNDLE = "flash-bake-ncm-20260530"
os.environ["CARTHING_FLASH_BUNDLE_DIR"] = BUNDLE
os.environ["CARTHING_FLASH_USE_RESTORE_PARTITION"] = "0"
os.environ["CARTHING_FLASH_WRITE_CHUNK_SECTORS"] = "1024"
os.environ["CARTHING_FLASH_TRANSFER_BLOCK_SIZE"] = "32768"
spec = importlib.util.spec_from_file_location("flasher", REPO + "/scripts/flash-device1-rootfs-only.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
print("=== FULL FLASH №2 (bootfs@0 + rootfs@352256) bundle:", BUNDLE, "===", flush=True)
dev = m.get_device()
dev.bulkcmd("amlmmc part 1", ignore_timeout=True)
dev.bulkcmd("amlmmc key", ignore_timeout=True)
dev = m.write_image(dev, BUNDLE + "/bootfs.bin", 0, "BOOTFS")
dev = m.write_image(dev, BUNDLE + "/rootfs.img", m.ROOT_RESTORE_BLOCK_OFFSET, "ROOT")
print("\n=== DONE. Power-cycle БЕЗ кнопок для загрузки. ===", flush=True)
