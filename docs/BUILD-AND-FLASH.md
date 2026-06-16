# BUILD-AND-FLASH — единый источник истины (2026-06-16)

Этот документ описывает **текущую рабочую прошивку** Car Thing и полный цикл
«изменение кода → пересборка → прошивка». Всё что здесь написано — проверено
на железе (устройство QN19, сессия 2026-06-16).

Один репозиторий: `carthing-release-integration/` содержит всё — код, образы,
инструменты прошивки, документацию.

---

## Архитектура прошивки

### Загрузчик (не трогаем)

Стоковый ThingLabs U-Boot BL33 — **только он умеет грузить FAT-раздел p1**.
Fastboot unlock запрещён. Заменять загрузчик — нарушение инварианта.

### Цепочка загрузки

```
stock BL33 (U-Boot)
  → fatload mmc 1:1 → superbird.dtb (0x1000000)
  → fatload mmc 1:1 → Image (0x1080000)
  → booti 0x1080000 - 0x1000000   ← ("-" = no initrd)
  → Buildroot init (/sbin/init → /etc/inittab)
  → S-скрипты /etc/init.d/*
  → carthing_runtime.py
```

**Нет никакого NixOS, нет initrd, нет systemd.** Удалено 2026-06-16.

### Разметка eMMC

| Раздел | Сектор | Размер | Содержимое |
|--------|--------|--------|------------|
| p1 | 8192 | FAT32 (bootfs.bin) | Image, superbird.dtb, bootargs.txt, U-Boot env |
| p2 | 352256 | ext4 512MB (rootfs.img) | Buildroot rootfs + наш overlay |

### Ядро

- Linux 4.9.113, собран с GCC 6.5.0 в NixOS-окружении (JoeyEamigh/nixos-superbird).
- `CONFIG_EXT4_FS=y`, `CONFIG_MMC=y` — встроены в ядро, модули при загрузке не нужны.
- Лежит внутри `image/bootfs.bin` (FAT-образ, в git не хранится — только SHA256SUMS).
- **Пересборка ядра без NixOS-окружения невозможна.** Не пересобирать без причины.

### Python-рантайм

Весь Python-код лежит в `overlay/usr/lib/carthing/*.py`. Это единственное что
меняется в обычной работе. Входная точка: `carthing_runtime.py`.

---

## Структура репозитория

```
carthing-release-integration/
├── image/                     готовые образы к прошивке (бинари gitignored)
│   ├── bootfs.bin             FAT-образ p1: ядро + DTB + env
│   ├── rootfs.img             ext4 512MB p2: Buildroot + overlay
│   ├── env.txt                U-Boot переменные окружения
│   └── SHA256SUMS             хэши всех трёх файлов
├── source/
│   └── base-bundle/           Buildroot baseline rootfs (бинари gitignored)
├── overlay/                   наш userspace overlay (Python + init + etc)
│   └── usr/lib/carthing/      Python-рантайм (*.py — единственное что правим)
├── tools/
│   ├── flash.py               ← ПРОШИВКА: python3 tools/flash.py
│   ├── bake-rootfs.py         ← СБОРКА: python3 tools/bake-rootfs.py
│   ├── _flasher.py            низкоуровневый Amlogic-флешер
│   ├── check-device.sh        статус устройства по VID:PID
│   ├── finish-env.py          дописать только env (без перепрошивки образов)
│   ├── deploy                 горячий деплой файлов без перепрошивки
│   └── screenshot.py          снимок экрана с устройства
├── scripts/
│   ├── bring-up-device1-normal-boot-macos.sh   поднять USB-сеть после загрузки
│   ├── check-device1-normal-boot-macos.sh      найти BSD-интерфейс NCM
│   └── reverse-control-server.py               экстренный доступ без SSH
└── docs/
    └── BUILD-AND-FLASH.md     этот файл
```

---

## Текущие образы (canonical, 2026-06-17)

SHA256SUMS (актуальные):
```
2ff2159a8733759576b4bda9c52e0bfc8cb02b1115766a8379e8f8d610dba76f  bootfs.bin
f204ac3d535bbc639061c594af1a5f7eaa327ecc1d636a7a63b829a7bd3e1fc0  rootfs.img
bee43a070ad18a764a7a0f97827e6213757976f6b7a8a3987331a9396c196cb9  env.txt
40a74a8c3fa2d18480dcbc38ddc7f37209da2b1d071d23c8e3f23232aa6f2402  bootlogos.bin
```

`bootfs.bin` обновлён 2026-06-17: ядро пересобрано с `CONFIG_AMLOGIC_MEDIA_GE2D=y` → `/dev/ge2d` доступен.
Артефакт сборки: `carthing-device-backups/artifacts/kernel-build-ge2d-20260617/`
Сборщик: Colima + builder контейнер + GCC 6.5.0 (тот же тулчейн что и оригинал).

`bootlogos.bin` — кастомный загрузочный логотип (5 слотов: bootup/burn_mode/bad_charger/shell_mode/overheat).
Прошивается автоматически в p7 (сектор 319488) как часть `flash.py`.

Runtime tree SHA1 (Python-файлы в overlay): `880bd037b7f43df44ac203b3f6d5089a06ad0320`

Проверить что у тебя именно эти образы:
```sh
cd (local repo root)
shasum -a 256 image/bootfs.bin image/rootfs.img image/env.txt | sed 's|image/||g'
# должно совпасть с image/SHA256SUMS
```

---

## ПРОШИВКА (быстрый путь)

```sh
cd (local repo root)

# 1. Войти в Maskrom: зажми кнопки 1+4, воткни USB, держи 2 сек, отпусти.
sh tools/check-device.sh       # -> MASKROM/BURN (1b8e:c003)

# 2. Прошивка
python3 tools/flash.py
# Время: ~15–25 минут. Пишет bootfs → rootfs → env → reset.

# 3. Поднять USB-сеть на Mac
scripts/bring-up-device1-normal-boot-macos.sh --bsd en18
# (en18 — NCM-интерфейс на текущей машине; проверить: ifconfig | grep en; pyusb видит 0525:a4a1)

# 4. SSH
ssh-keygen -R 172.16.42.77      # обязательно после каждой перепрошивки
ssh root@172.16.42.77            # ключ id_carthing; пароль: carthing
```

---

## ПЕРЕСБОРКА ROOTFS (если изменялся Python-код)

Пересборка = заменить `image/rootfs.img`, сохранив `image/bootfs.bin`.

### Шаг 1. Обновить runtime SHA1 (если менялся Python-код)

```sh
python3 << 'EOF'
import hashlib
from pathlib import Path

RETIRED = {
    "classic_profile_probe.py", "hid_pair.py", "media_remote.py",
    "media_remote_v3.py", "now_playing_ui.py", "system_menu.py", "trusted_devices.py"
}
d = Path("overlay/usr/lib/carthing")
lines = []
for path in sorted(d.glob("*.py")):
    if path.name in RETIRED:
        continue
    h = hashlib.sha1(path.read_bytes()).hexdigest()
    lines.append(f"{h}  {path.name}\n")
print(hashlib.sha1("".join(lines).encode()).hexdigest())
EOF
```

Скопировать вывод → вставить в `EXPECTED_RUNTIME_TREE_SHA1` в `tools/bake-rootfs.py`.

### Шаг 2. Запечь rootfs

```sh
# Зависимости (однократно): brew install e2tools e2fsprogs
python3 tools/bake-rootfs.py
# Создаст: flash-bake-unified-stable-YYYYMMDD-HHMMSS/ (gitignored)
# Автоматически:
#   - копирует source/base-bundle/rootfs.img
#   - вносит overlay (Python, vendor/bumble, init-скрипты, gesftpserver, shadow)
#   - запускает e2fsck (исправляет checksums ext4 — без этого загрузка занимает 10 мин)
#   - верифицирует результат
```

### Шаг 3. Переложить rootfs в image/ и обновить хэши

```sh
BUNDLE=$(ls -d flash-bake-unified-stable-* | sort | tail -1)
cp "$BUNDLE/rootfs.img" image/rootfs.img
shasum -a 256 image/bootfs.bin image/rootfs.img image/env.txt | \
  sed 's|image/||g' > image/SHA256SUMS
cat image/SHA256SUMS
```

### Шаг 4. Флешить (см. «ПРОШИВКА» выше)

---

## ГОРЯЧИЙ ДЕПЛОЙ (без перепрошивки)

Для быстрой итерации при разработке Python-рантайма:

```sh
cd (local repo root)

# Один файл с рестартом рантайма
tools/deploy overlay/usr/lib/carthing/carthing_runtime.py --restart

# Несколько файлов
tools/deploy overlay/usr/lib/carthing/gui_controller.py
tools/deploy overlay/usr/lib/carthing/app_state.py --restart
```

`tools/deploy` монтирует rootfs RW, копирует через tar + chown root, опционально
рестартует рантайм. НЕ использовать scp/sftp — на buildroot-образе нет sftp-server.

---

## SSH-доступ

| Параметр | Значение |
|----------|----------|
| IP | `172.16.42.77` |
| Порт | 22 (dropbear) |
| Юзер | `root` |
| Пароль | `carthing` |
| Ключи | `~/.ssh/id_carthing` (без passphrase), `id_ed25519`, `id_rsa` |
| Алиас | `ssh carthing` |

После перепрошивки: `ssh-keygen -R 172.16.42.77` (меняется host key).

Если SSH не отвечает — сначала поднять USB-сеть:
```sh
scripts/bring-up-device1-normal-boot-macos.sh --bsd en14
```

Экстренный доступ (если SSH совсем недоступен):
```sh
scripts/reverse-control-server.py                      # Mac side, порт 8099
scripts/reverse-agent-enqueue.sh '<cmd>' device1       # команда через USB-канал
```

---

## Что НЕ пересобираем

| Компонент | Почему |
|-----------|--------|
| Ядро Linux 4.9.113 | Требует GCC 6.5.0 + NixOS-окружение; стабилен; не трогать без причины |
| Buildroot rootfs (base-bundle) | Требует Buildroot + macOS APFS sparse image; базовая система стабильна |
| U-Boot | Стоковый ThingLabs; fastboot unlock запрещён |
| DTB | Стоковый Amlogic S905D2 |

Единственное, что меняем в штатной разработке: **Python-файлы в `overlay/usr/lib/carthing/`**.

---

## Известные ловушки

### Boot mode
`halt=True` в GUI → плата уходит в Amlogic burn mode (= Maskrom), не выключается.
Переменная-предохранитель: `CARTHING_ALLOW_LINUX_POWEROFF=1`.
Кнопка в GUI = «Сон экрана», не настоящий poweroff.

### USB-сеть
NCM Gadget (`0x0525:0xa4a1`) может быть виден в ioreg, но en14 всё равно `inactive`.
Всегда делать bring-up явно через скрипт, не ждать macOS.

### e2cp без e2fsck
`e2cp` не обновляет block group descriptor checksums → ext4-журнал откатывается при
каждой загрузке → загрузка занимает 10+ минут. Решение: `e2fsck -f -y rootfs.img`
(или `tools/bake-rootfs.py` делает это автоматически).

### shadow при перепрошивке
`/etc/shadow` с хэшем пароля "carthing" включён в overlay и копируется при bake.
До 2026-06-16 — не копировался, пароль терялся при перепрошивке.

### BT state при перепрошивке
`bake-rootfs.py` вычищает `/var/lib/carthing-state` при каждой сборке.
До 2026-06-17 — base-bundle мог содержать BT bonds от исходного устройства,
и все прошитые девайсы «знали» чужие MAC-адреса бондов.

### bootlogos.bin отсутствует
Если `image/bootlogos.bin` не найден, `flash.py` выводит WARNING и пропускает p7.
Пересобрать: `sh tools/logo/build-and-flash-logo.sh --dry-run && cp /tmp/bootlogos.bin image/bootlogos.bin`
