# Car Thing — от железа до userspace

**Дата:** 2026-05-22  
**Цель:** полный контроль над устройством от BL2 до userspace

---

## История открытия Car Thing

### 2022 — Первые открытия

| Дата | Событие | Авторы |
|------|---------|--------|
| 2022-02-22 | Car Thing публичный релиз | Spotify |
| 2022-07-29 | Car Thing discontinued | Spotify |
| 2022-10-20 | Initial notice to Spotify | err4o4 |
| 2022-10-21 | Spotify EOL response | Spotify |
| 2022-11 | Root achieved | Frédéric Basse & Nolen Johnson |

### Ключевые открытия 2022

**1. USB Burning Mode (buttons 1+4)**
- VID:PID = `1b8e:c003` (GX-CHIP, Amlogic)
- U-Boot shell доступен через `bulkcmd`
- Позволяет читать/писать любые partition

**2. UART Pinout**
```
Pin 1: GND
Pin 2: 3.3V
Pin 3: TX (SoC → UART)
Pin 4: RX (UART → SoC)
```
Расположение: под стикером на задней панели.

**3. Amlogic S905D2 SoC**
- ARM Cortex-A53 (4-core)
- 512MB RAM
- eMMC storage
- SDIO controller (for WiFi/Bluetooth combo)

**4. U-Boot Source**
- GitHub: [spsgsb/uboot](https://github.com/spsgsb/uboot)
- Branch: `buildroot-openlinux-201904-g12a`

**5. Linux Kernel Source**
- GitHub: [spsgsb/kernel-common](https://github.com/spsgsb/kernel-common)
- Version: 4.9.x (stock), 6.6.x (community)

---

## Эволюция инструментов

### 1. frederic/superbird-bulkcmd (2022-10-20)

**Назначение:** U-Boot shell over USB

**Ключевые файлы:**
- `bin/update` — proprietary Amlogic USB burning client
- `scripts/burn-mode.sh` — загрузка U-Boot в burn mode
- `scripts/enable-adb.sh.client` — persistent ADB
- `scripts/disable-avb2.sh` — отключение AVB2

**Ограничения:**
- Требует Linux (libusb)
- Проприетарный `update` binary
- Нет macOS поддержки

### 2. bishopdynamics/superbird-tool (2022-11)

**Назначение:** Cross-platform hacking toolkit

**Ключевые изменения:**
- Использует `pyamlboot` вместо `update`
- Работает на macOS/Linux
- Полный набор команд:
  - `--burn_mode`, `--continue_boot`
  - `--bulkcmd COMMAND`
  - `--dump_device`, `--restore_device`
  - `--boot_adb_kernel`
  - `--enable_burn_mode`, `--disable_avb2`

**Ограничения:**
- Медленный dump (545KB/s vs 12MB/s)
- Windows нестабилен

### 3. err4o4/spotify-car-thing-reverse-engineering (2023)

**Назначение:** Полное reverse engineering

**Ключевые достижения:**
- Buildroot + kernel 6.6.41
- UART shell
- Partitioning guide
- DTB decryption
- Persistent root access

**Ключевые файлы:**
- `superbird/scripts/` — скрипты сборки
- `esp32-wifi-ncm/` — WiFi dongle
- `research/` — технические заметки

### 4. ThingLabsOSS (2024-2026)

**Назначение:** Восстановление функциональности

**Проекты:**
- `unnamed-superbird-connector` — Spotify Web API
- `superbird-tool` — fork bishopdynamics
- `superbird-webapp` — reconstructed webapp
- `deskthing.app` — replacement OS

---

## Архитектура устройства

### Boot Sequence

```
ROM Bootloader (Amlogic)
    ↓
BL2 (U-Boot SPL)
    ↓
BL33 (U-Boot)
    ↓
[Buttons 1+4 held?]
    ├─ YES → USB Burn Mode (bulkcmd)
    └─ NO → Normal Boot
             ↓
        [AVB2 enabled?]
             ├─ YES → A/B slot selection
             └─ NO → Direct boot
                      ↓
                 Kernel + Initrd
                      ↓
                 Userspace
```

### Partition Layout (eMMC)

| Partition | Offset | Size | Description |
|-----------|--------|------|-------------|
| bootloader | 0x0 | 2MB | BL2 + BL33 |
| reserved | 0x12000 | 64MB | Reserved |
| env | 0x3a000 | 8MB | U-Boot env |
| fip_a | 0x42000 | 4MB | ARM Trusted Firmware A |
| fip_b | 0x48000 | 4MB | ARM Trusted Firmware B |
| logo | 0x4e000 | 8MB | Boot logo |
| dtbo_a | 0x56000 | 4MB | DTBO A |
| dtbo_b | 0x5c000 | 4MB | DTBO B |
| vbmeta_a | 0x62000 | 1MB | AVB metadata A |
| vbmeta_b | 0x66800 | 1MB | AVB metadata B |
| boot_a | 0x6b000 | 16MB | Kernel + Initrd A |
| boot_b | 0x77000 | 16MB | Kernel + Initrd B |
| system_a | 0x83000 | 516MB | Rootfs A |
| system_b | 0x189058 | 516MB | Rootfs B |
| misc | 0x28f0b0 | 8MB | AVB state |
| settings | 0x2970b0 | 256MB | User data |
| data | 0x31b0b0 | 2185MB | Full data |

### Hardware Components

| Component | Chip | Notes |
|-----------|------|-------|
| SoC | Amlogic S905D2 | Cortex-A53, 4-core |
| RAM | DDR3 | 512MB |
| Storage | eMMC | 4GB (256MB boot + 3.5GB data) |
| Bluetooth | Broadcom BCM20703A2 | UART @ 3Mbps |
| WiFi | Broadcom BCM4345C0 | Combo (WiFi+BT), **не распаян** |
| Display | LCD | 2.8" 480×800 |
| Audio | T9015 DAC | TDM interface |
| Microphones | 4× PDM | MEMS microphones |

---

## Путь к полному контролю

### Уровень 0: Hardware Access

**Инструменты:**
- `superbird-tool` — flashing, dump/restore
- UART pins — console access
- USB Burn Mode — U-Boot shell

**Команды:**
```bash
# Enter USB Burn Mode
superbird-tool --burn_mode

# Dump all partitions
superbird-tool --dump_device ./dump/

# Restore from dump
superbird-tool --restore_device ./dump/

# U-Boot shell
superbird-tool --bulkcmd 'amlmmc part 1'
superbird-tool --bulkcmd 'amlmmc read boot_a 0x10000000 0 0x1000000'
```

### Уровень 1: Bootloader

**Источники:**
- U-Boot: [spsgsb/uboot](https://github.com/spsgsb/uboot)
- BL2: `boot0` partition dump
- BL33: `bootloader` partition dump

**Ключевые файлы:**
- `include/spotify/avb.h` — AVB A/B logic
- `common/cmd_bootctl_avb.c` — consume_boot_try()
- `board/amlogic/configs/superbird_production.h` — storeboot

**Исследование:**
```bash
# Dump U-Boot env
superbird-tool --get_env env.txt

# Dump BL2
dd if=/dev/mmcblk0 bs=512 count=32 of=bl2.bin

# Dump BL33
dd if=/dev/mmcblk0 bs=512 skip=32 count=4096 of=bl33.bin
```

### Уровень 2: Kernel

**Источники:**
- Stock: [spsgsb/kernel-common](https://github.com/spsgsb/kernel-common)
- Community: [linux-superbird-6.6](https://github.com/alexcaoys/linux-superbird-6.6.y)

**Ключевые файлы:**
- `arch/arm64/boot/dts/amlogic/meson-g12a-superbird.dts`
- `drivers/bluetooth/hci_bcm.c`
- `drivers/mmc/host/meson-gx-mmc.c`

**Исследование:**
```bash
# Extract kernel from boot_a
dd if=/dev/mmcblk0 bs=2048 skip=69632 count=67584 of=kernel.img

# Extract DTB
dtb_offset=$((0xD25000 / 2048))
dd if=/dev/mmcblk0 bs=2048 skip=$dtb_offset count=100 of=dtb.img

# Decrypt DTB (if encrypted)
# See err4o4/spotify-car-thing-reverse-engineering#22
```

### Уровень 3: Rootfs

**Источники:**
- Stock: `system_a` partition
- Buildroot: [frederic/superbird-buildroot](https://github.com/frederic/superbird-buildroot)
- NixOS: [joeyeamigh/nixos-superbird](https://github.com/joeyeamigh/nixos-superbird)

**Ключевые файлы:**
- `/opt/car-thing/` — ваш userspace
- `/etc/init.d/` — init scripts
- `/lib/firmware/brcm/` — BT firmware

**Исследование:**
```bash
# Dump rootfs
superbird-tool --dump_partition system_a rootfs.img

# Mount and explore
sudo mount -o loop rootfs.img /mnt
```

### У��овень 4: Userspace

**Ваша реализация:**
```
/opt/car-thing/
├── src/
│   ├── media_remote.py      # Main orchestrator
│   ├── ble_transport.py     # Bumble HCI
│   ├── ams_client.py        # Apple Media Service
│   ├── hid_pair.py          # BLE HID pairing
│   ├── drm_display.py       # DRM/KMS UI
│   ├── now_playing_ui.py    # UI renderer
│   └── input_handler.py     # evdev input
├── lib/                     # Python dependencies
└── vendor/                  # vendored libs
```

**Ключевые процессы:**
- `carthing-btattach-mini` — HCI attach
- `media_remote.py` — main app
- `dropbear` — SSH server
- `httpd` / `telnetd` — debug services

---

## Инструменты для исследования

### 1. U-Boot Shell

```bash
# List partitions
amlmmc list

# Read partition
amlmmc read boot_a 0x10000000 0 0x1000000

# Write partition
amlmmc write boot_a 0x10000000 0 0x1000000

# Save env
env save

# Boot kernel
bootm 0x10000000
```

### 2. ADB

```bash
# Enable ADB (persistent)
adb shell mount -o remount,rw /
adb shell echo "enable-adb" > /etc/init.d/S49usbgadget
adb shell reboot
```

### 3. UART

```bash
# Connect via UART
picocom -b 115200 /dev/ttyUSB0

# U-Boot console
# (press any key during boot)
```

### 4. pyamlboot

```bash
# Install
pip install git+https://github.com/superna9999/pyamlboot

# Use
python3 -c "from pyamlboot import pyamlboot; dev = pyamlboot.AmlogicSoC(); dev.findDevice(); dev.burnMode()"
```

---

## Следующие шаги

### 1. Документация

Создать документ `HARDWARE-ROOT-TO-USERSPACE.md` с:
- [x] Историей открытия
- [x] Архитектурой
- [x] Инструментами
- [ ] Полным реверсом BL2/BL33
- [ ] Документацией DTB
- [ ] Сборкой кастомного kernel
- [ ] Сборкой кастомного rootfs

### 2. Инструменты

Создать набор скриптов:
- `scripts/dump-hardware.sh` — дамп всех уровней
- `scripts/extract-boot.sh` — извлечение kernel/dtb
- `scripts/build-kernel.sh` — сборка кастомного kernel
- `scripts/flash-full.sh` — прошивка полной системы

### 3. Исследование

- [ ] BL2/BL33 disassembly
- [ ] DTB analysis (encrypted vs decrypted)
- [ ] Kernel module reverse engineering
- [ ] U-Boot env analysis
- [ ] AVB A/B mechanism

---

## Ключевые ссылки

### Оригинальные репозитории
- [spsgsb/uboot](https://github.com/spsgsb/uboot) — U-Boot source
- [spsgsb/kernel-common](https://github.com/spsgsb/kernel-common) — Kernel source
- [frederic/superbird-bulkcmd](https://github.com/frederic/superbird-bulkcmd) — First hack
- [bishopdynamics/superbird-tool](https://github.com/bishopdynamics/superbird-tool) — Cross-platform
- [err4o4/spotify-car-thing-reverse-engineering](https://github.com/err4o4/spotify-car-thing-reverse-engineering) — Full reverse

### Сообщество
- [ThingLabsOSS](https://github.com/ThingLabsOSS) — Active team
- [Car-Thing-Hax-Community](https://github.com/topics/car-thing) — GitHub topics
- Discord: https://discord.gg/DM2AqyPJAA

### Ваш проект
- `carthing-custom-linux/` — Buildroot overlay
- `carthing-fix-ancs-reconnect/` — BLE/AMS/GUI
- `carthing-services-experiment/` — Testing
- `carthing-device-backups/` — Device #2 backup

---

*Этот документ — живой справочник. Обновляйте его при каждом значимом открытии.*
