#!/bin/sh
# build-and-flash-logo.sh — сборка и заливка логотипа загрузчика Car Thing
#
# АРХИТЕКТУРА ДИСПЛЕЯ (критично для подготовки изображений):
#   U-Boot framebuffer: 480×800 px (portrait, software coordinate space)
#   Аппаратная ротация: 90° CCW (применяется display controller, S905D2 MIPI DSI)
#   Физический экран:   800×480 px (landscape, как смотрит пользователь)
#
#   Следствие: изображение в BMP нужно подготавливать с учётом ротации.
#   Если источник — portrait-ориентированное изображение (голова вверху в файле),
#   оно появится на экране повёрнутым на 90° CCW (голова влево).
#   Чтобы выглядело правильно → поворачиваем источник на 90° CW перед упаковкой.
#   Результат в BMP: «лежащий на боку» файл → после аппаратной ротации = правильно.
#
# LOGO PARTITION:
#   Устройство: /dev/mmcblk0p7 (mmcblk0, раздел 7, имя «logo» в U-Boot)
#   Смещение:   сектор 319488 (× 512 = 163 577 856 байт от начала eMMC)
#   Размер:     16 384 сектора = 8 МБ
#   Формат:     Amlogic proprietary logo binary (несколько BMP-слотов)
#
#   Слоты (имена = ключи, по которым U-Boot читает через imgread pic logo <name>):
#     bootup_spotify — показывается при нормальной загрузке
#     burn_mode   — показывается при входе в USB Burn Mode
#     shell_mode  — показывается при входе в shell mode
#     bad_charger — показывается при подключении несовместимого зарядника
#     overheat    — показывается при перегреве
#
# BMP ФОРМАТ (обязателен для Amlogic U-Boot):
#   Размер:  480×800 px (ширина×высота в BMP-координатах, portrait)
#   Глубина: 16 bpp, RGB565
#   Заголовок: BMP4 (Windows 98/2000+), offset 138 байт до данных
#
# ИНСТРУМЕНТ УПАКОВКИ:
#   aml-imgpack.py — Python-скрипт, bishopdynamics/aml-imgpack
#   rev c68715971ec0dd85485b9bd4006946a182984a92
#   Скачать: https://raw.githubusercontent.com/bishopdynamics/aml-imgpack/c68715971ec0dd85485b9bd4006946a182984a92/aml-imgpack.py
#
# ЗАВИСИМОСТИ:
#   brew install imagemagick
#   pip3 install / или просто python3 (aml-imgpack.py — pure stdlib)
#
# ЗАПИСЬ НА УСТРОЙСТВО:
#   НЕ нужен Maskrom/burn mode — пишем напрямую с работающего Linux через SSH.
#   Раздел logo НЕ монтируется Linux (не является rootfs или boot).
#   Смещение 319488 секторов от начала /dev/mmcblk0.
#
# ОТКАТ К ОРИГИНАЛЬНОМУ THINGLABS ЛОГОТИПУ:
#   BOOTUP_SRC=bootup_thinglabs.bmp <этот скрипт> --no-convert

set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Файлы слотов (лежат рядом со скриптом)
BURN_MODE_BMP="$SCRIPT_DIR/burn_mode.bmp"
BAD_CHARGER_BMP="$SCRIPT_DIR/bad_charger.bmp"
SHELL_MODE_BMP="$SCRIPT_DIR/shell_mode.bmp"
OVERHEAT_BMP="$SCRIPT_DIR/overheat.bmp"

# Источник для bootup_spotify (по умолчанию наш PNG, можно override через env)
BOOTUP_SRC="${BOOTUP_SRC:-$SCRIPT_DIR/bootup-source.png}"

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

AML_IMGPACK="${AML_IMGPACK:-$WORK/aml-imgpack.py}"
DEVICE_IP="${DEVICE_IP:-172.16.42.77}"
LOGO_SECTOR=319488

usage() {
    cat <<EOF
Usage: $0 [--no-convert] [--dry-run]

  --no-convert   BOOTUP_SRC уже является готовым 480×800 BMP (пропустить magick)
  --dry-run      Собрать bootlogos.bin, но не заливать на устройство
  BOOTUP_SRC     env-переменная: путь к PNG/BMP источнику (default: bootup-source.png)
  DEVICE_IP      env-переменная: IP устройства (default: 172.16.42.77)

Примеры:
  $0                                      # пересобрать из bootup-source.png и залить
  $0 --dry-run                            # только собрать, проверить файл
  BOOTUP_SRC=bootup_thinglabs.bmp $0 --no-convert   # откат к ThingLabs логотипу
EOF
}

NO_CONVERT=0
DRY_RUN=0
for arg in "$@"; do
    case "$arg" in
        --no-convert) NO_CONVERT=1 ;;
        --dry-run)    DRY_RUN=1 ;;
        -h|--help)    usage; exit 0 ;;
        *) echo "Unknown arg: $arg" >&2; usage >&2; exit 1 ;;
    esac
done

# Скачиваем aml-imgpack.py если не передан
if [ ! -f "$AML_IMGPACK" ]; then
    echo "Скачиваю aml-imgpack.py..."
    curl -fsSL \
      "https://raw.githubusercontent.com/bishopdynamics/aml-imgpack/c68715971ec0dd85485b9bd4006946a182984a92/aml-imgpack.py" \
      -o "$AML_IMGPACK"
fi

# --- Конвертация bootup_spotify ---
if [ "$NO_CONVERT" = "1" ]; then
    BOOTUP_BMP="$WORK/bootup_spotify.bmp"
    cp "$BOOTUP_SRC" "$BOOTUP_BMP"
    echo "bootup_spotify: используем готовый BMP $BOOTUP_SRC"
else
    BOOTUP_BMP="$WORK/bootup_spotify.bmp"
    echo "bootup_spotify: конвертация $BOOTUP_SRC → 480×800 BMP RGB565 (+90° CW)"

    # Определяем размеры источника
    W=$(magick identify -format "%w" "$BOOTUP_SRC")
    H=$(magick identify -format "%h" "$BOOTUP_SRC")
    echo "  источник: ${W}×${H}"

    # Если источник landscape (ширина > высоты): НЕ нужен доп. поворот,
    # источник уже горизонтальный → просто вписываем в 480×800.
    # Если portrait или square (высота ≥ ширины): поворачиваем +90° CW,
    # иначе на физическом экране будет 90° CCW мимо правильного.
    if [ "$W" -gt "$H" ]; then
        ROTATE_ARG=""
    else
        ROTATE_ARG="-rotate 90"
    fi

    # shellcheck disable=SC2086
    magick "$BOOTUP_SRC" \
        $ROTATE_ARG \
        -resize 480x800 \
        -background black \
        -gravity center \
        -extent 480x800 \
        -define bmp:format=bmp4 \
        -type truecolor \
        -define bmp:subtype=RGB565 \
        -depth 16 \
        "$BOOTUP_BMP"

    ACTUAL=$(magick identify -format "%wx%h" "$BOOTUP_BMP")
    echo "  результат: $ACTUAL BMP RGB565"
fi

# --- Упаковка ---
OUTPUT="$WORK/bootlogos.bin"
echo "Упаковка слотов..."
python3 "$AML_IMGPACK" --pack "$OUTPUT" \
    "$BOOTUP_BMP" \
    "$BURN_MODE_BMP" \
    "$BAD_CHARGER_BMP" \
    "$SHELL_MODE_BMP" \
    "$OVERHEAT_BMP"

SIZE=$(wc -c < "$OUTPUT")
echo "bootlogos.bin: $SIZE байт"

if [ "$DRY_RUN" = "1" ]; then
    echo "DRY RUN: файл готов, запись пропущена."
    cp "$OUTPUT" "/tmp/bootlogos.bin"
    echo "Сохранён в /tmp/bootlogos.bin"
    exit 0
fi

# --- Запись на устройство ---
echo "Запись на $DEVICE_IP (сектор $LOGO_SECTOR)..."
# shellcheck disable=SC2029
cat "$OUTPUT" | ssh -i ~/.ssh/id_carthing "root@$DEVICE_IP" \
    "dd of=/dev/mmcblk0 bs=512 seek=$LOGO_SECTOR conv=fsync 2>&1"

echo ""
echo "Готово. Перезагрузи устройство чтобы увидеть новый логотип:"
echo "  ssh root@$DEVICE_IP 'reboot'"
