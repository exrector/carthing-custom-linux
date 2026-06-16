#!/bin/bash
# build_iap2.sh — Собрать iap2_agent для ARM32 (Car Thing) через Docker
#
# Требования: Docker desktop запущен, arm32v7 image будет скачан автоматически.
# Запуск: cd carthing-remote && bash slot_a/build_iap2.sh

set -e
# Запускать из корня репо: cd carthing-remote && bash device_root/home/superbird/slot_a/build_iap2.sh
REPO_ROOT="$(pwd)"

echo "[build] Собираю iap2_agent для arm32v7/debian:bullseye..."
echo "[build] Репозиторий: $REPO_ROOT"

docker run --rm \
    --platform linux/arm/v7 \
    -v "$REPO_ROOT":/work \
    arm32v7/debian:bullseye \
    bash -c "
        set -e
        echo '[build] Устанавливаю зависимости...'
        apt-get update -qq
        apt-get install -y -q gcc libglib2.0-dev libbluetooth-dev 2>/dev/null

        echo '[build] Компилирую iap2_agent...'
        cd /work/device_root/home/superbird/slot_a
        gcc -o iap2_agent iap2_agent_new.c \
            \$(pkg-config --cflags --libs gio-2.0 gio-unix-2.0 glib-2.0) \
            -lpthread -lbluetooth -Os -Wl,--strip-all

        echo '[build] Компилирую encoder_hid...'
        gcc -o /work/slot_a/encoder_hid /work/slot_a/encoder_hid.c \
            -Os -Wl,--strip-all

        echo '[build] Компилирую encoder_avrcp...'
        gcc -o /work/slot_a/encoder_avrcp /work/slot_a/encoder_avrcp.c \
            -lbluetooth -lpthread -Os -Wl,--strip-all

        echo '[build] Проверяю...'
        ls -lh iap2_agent /work/slot_a/encoder_hid /work/slot_a/encoder_avrcp
        readelf -h iap2_agent | grep -E 'Class|Machine'
        echo '[build] ГОТОВО: iap2_agent + encoder_hid + encoder_avrcp'
    "

echo ""
echo "Деплой на устройство:"
echo "  scp slot_a/iap2_agent root@<IP>:/home/superbird/slot_a/"
echo "  scp slot_a/supervisor_slot_a.conf root@<IP>:/etc/supervisor.d/slot_a.conf"
echo "  ssh root@<IP> 'supervisorctl reread && supervisorctl update'"
echo ""
echo "Проверить SDP запись:"
echo "  ssh root@<IP> 'sdptool browse local | grep -A5 iAP'"
