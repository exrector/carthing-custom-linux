# BUILD-AND-FLASH — единый источник истины (2026-06-16)

Этот документ описывает **текущую рабочую прошивку** Car Thing и полный цикл
«изменение кода → пересборка → прошивка». Всё что здесь написано — проверено
на железе (устройство QN19, сессия 2026-06-16).

---

## Два репозитория, одна прошивка

| Репозиторий | Назначение |
|-------------|------------|
| `carthing-release-integration/` | Разработка: Python-рантайм, документация, скрипты. Здесь вносятся изменения. |
| `carthing_full_real/` | Публикация: готовые образы + инструмент прошивки. Отсюда прошивается устройство. |

`overlay/` в обоих репозиториях **идентичен** (синхронизируется вручную при изменениях).
Bake-инструмент читает overlay из `carthing_full_real/source/overlay/`.

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
- Лежит внутри `carthing_full_real/image/bootfs.bin` (FAT-образ).
- **Пересборка ядра без NixOS-окружения невозможна.** Не пересобирать без причины.

### Python-рантайм

Весь Python-код лежит в `overlay/usr/lib/carthing/*.py`. Это единственное что
меняется в обычной работе. Входная точка: `carthing_runtime.py`.

---

## Текущие образы (canonical, 2026-06-16)

```
carthing_full_real/image/
├── bootfs.bin   # FAT-образ p1: ядро + DTB + env
├── rootfs.img   # ext4 512MB p2: Buildroot + overlay
├── env.txt      # U-Boot переменные окружения
└── SHA256SUMS
```

SHA256SUMS (актуальные):
```
971a79105c88e66466a0d981bda347f35dc06f099d159d89ba8f611a92d96004  bootfs.bin
f204ac3d535bbc639061c594af1a5f7eaa327ecc1d636a7a63b829a7bd3e1fc0  rootfs.img
bee43a070ad18a764a7a0f97827e6213757976f6b7a8a3987331a9396c196cb9  env.txt
```

Runtime tree SHA1 (Python-файлы в overlay): `880bd037b7f43df44ac203b3f6d5089a06ad0320`

---

## ПРОШИВКА (быстрый путь)

Если образы уже актуальны (хэши совпадают) — просто флешишь:

```sh
# 1. Войти в Maskrom: зажми кнопки 1+4, воткни USB, держи 2 сек, отпусти.
sh carthing_full_real/tools/check-device.sh    # -> MASKROM/BURN (1b8e:c003)

# 2. Флешим
cd ~/Documents/ПРОЕКТЫ/carthing_full_real
python3 tools/flash.py
# Время: ~15–25 минут. Пишет bootfs → rootfs → env → reset.

# 3. После первой загрузки — поднять USB-сеть на Mac
cd (local repo root)
scripts/bring-up-device1-normal-boot-macos.sh --bsd en14
# (en14 — это NCM-интерфейс; проверить через: ifconfig | grep en)

# 4. SSH
ssh-keygen -R 172.16.42.77      # обязательно после каждой перепрошивки
ssh root@172.16.42.77            # ключ id_carthing; пароль: carthing
```

---

## ПЕРЕСБОРКА ROOTFS (если изменялся Python-код)

Пересборка = заменить `rootfs.img` в `carthing_full_real/image/`, сохранив `bootfs.bin`.

### Шаг 1. Синхронизировать overlay

Если изменения вносились в `carthing-release-integration/overlay/` — синхронизировать
в `carthing_full_real/source/overlay/`:

```sh
rsync -av --delete \
  overlay/ \
  ~/Documents/ПРОЕКТЫ/carthing_full_real/source/overlay/
```

### Шаг 2. Обновить runtime SHA1 (если менялся Python-код)

```python
# В картинге carthing_full_real/source/overlay/usr/lib/carthing/:
python3 << 'EOF'
import hashlib
from pathlib import Path

RETIRED = {
    "classic_profile_probe.py", "hid_pair.py", "media_remote.py",
    "media_remote_v3.py", "now_playing_ui.py", "system_menu.py", "trusted_devices.py"
}
d = Path("~/Documents/ПРОЕКТЫ/carthing_full_real/source/overlay/usr/lib/carthing")
lines = []
for path in sorted(d.glob("*.py")):
    if path.name in RETIRED:
        continue
    h = hashlib.sha1(path.read_bytes()).hexdigest()
    lines.append(f"{h}  {path.name}\n")
print(hashlib.sha1("".join(lines).encode()).hexdigest())
EOF
```

Скопировать вывод → вставить в `EXPECTED_RUNTIME_TREE_SHA1` в `bake-rootfs.py`.

### Шаг 3. Запечь rootfs

```sh
cd ~/Documents/ПРОЕКТЫ/carthing_full_real

# Зависимости (однократно): brew install e2tools e2fsprogs
python3 source/bake-rootfs.py
# Создаст: flash-bake-unified-stable-YYYYMMDD-HHMMSS/
# Автоматически:
#   - копирует base-bundle/rootfs.img
#   - вносит overlay (Python, vendor/bumble, init-скрипты, gesftpserver, shadow)
#   - запускает e2fsck (исправляет checksums ext4 — без этого загрузка занимает 10 мин)
#   - верифицирует результат
```

### Шаг 4. Переложить rootfs в image/ и обновить хэши

```sh
BUNDLE=$(ls -d flash-bake-unified-stable-* | sort | tail -1)
cp "$BUNDLE/rootfs.img" image/rootfs.img
shasum -a 256 image/bootfs.bin image/rootfs.img image/env.txt | \
  sed 's|image/||g' > image/SHA256SUMS
cat image/SHA256SUMS
```

### Шаг 5. Флешить (см. «ПРОШИВКА» выше)

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

Если SSH не отвечает — сначала проверить USB-сеть:
```sh
scripts/bring-up-device1-normal-boot-macos.sh --bsd en14
```

Экстренный доступ (если SSH совсем недоступен):
```sh
scripts/reverse-control-server.py         # Mac side, порт 8099
scripts/reverse-agent-enqueue.sh '<cmd>' device1   # команда через USB-канал
```

---

## Что НЕ пересобираем

| Компонент | Почему |
|-----------|--------|
| Ядро Linux 4.9.113 | Требует GCC 6.5.0 + NixOS-окружение; стабилен; не трогать без причины |
| Buildroot rootfs (base-bundle) | Требует Buildroot + macOS APFS sparse image; базовая система стабильна |
| U-Boot | Стоковый ThingLabs; fastboot unlock запрещён |
| DTB | Стоковый Amlogic S905D2 |

Единственное, что меняем в штатной разработке: **Python-файлы в overlay/usr/lib/carthing/**.

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
(или `bake-rootfs.py` делает это автоматически).

### shadow при перепрошивке
`/etc/shadow` с хэшем пароля "carthing" включён в overlay и копируется при bake.
До 2026-06-16 — не копировался, пароль терялся при перепрошивке.
