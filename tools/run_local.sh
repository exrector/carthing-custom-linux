#!/bin/sh
# Запуск carthing_runtime на маке с GUI окном.
# Запускать в foreground (не через &) — pygame требует main thread.
#
# Использование:
#   ./tools/run_local.sh
#   ./tools/run_local.sh --no-gui      # только BT, без окна
#   ./tools/run_local.sh --no-pairing  # не арминовать pairing автоматически

REPO="$(cd "$(dirname "$0")/.." && pwd)"
OVERLAY="$REPO/overlay/usr/lib/carthing"

export PYTHONPATH="$OVERLAY/vendor:$OVERLAY"
export CAR_THING_TRANSPORT="${CAR_THING_TRANSPORT:-tcp-client:172.16.42.77:6402}"
export CAR_THING_BD_ADDRESS="${CAR_THING_BD_ADDRESS:-30:E3:D6:00:5F:A4}"
export CARTHING_DEVICE_NAME="${CARTHING_DEVICE_NAME:-Car Thing (SN: QN19)}"
export CARTHING_MFI_REMOTE_SSH="${CARTHING_MFI_REMOTE_SSH:-root@172.16.42.77}"
export CARTHING_POST_PAIR_CLASSIC_PROBE="${CARTHING_POST_PAIR_CLASSIC_PROBE:-0}"
export CARTHING_IAP2_ENABLE="${CARTHING_IAP2_ENABLE:-0}"
export CARTHING_BUMBLE_QUARANTINE="${CARTHING_BUMBLE_QUARANTINE:-1}"
export CARTHING_ALLOW_BUMBLE_RUN="${CARTHING_ALLOW_BUMBLE_RUN:-0}"

# Local run_local used to be convenient, but it starts the same Bumble-owned
# runtime through the device HCI proxy. Keep it available for old experiments,
# while making accidental launches impossible.
if [ "$CARTHING_BUMBLE_QUARANTINE" != "0" ] || [ "$CARTHING_ALLOW_BUMBLE_RUN" != "1" ]; then
    echo "[run_local] Bumble runtime quarantined; refusing to start"
    echo "[run_local] manual lab override:"
    echo "  CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 ./tools/run_local.sh"
    exit 0
fi
# [CLAUDE 2026-06-03] Имя вычисляем из РЕАЛЬНОГО efuse-usid устройства (снят с /sys/class/efuse/usid
# = 8555R08SQN19 -> SN QN19), а не из захардкоженной строки. Если подключишь другой юнит — обнови файл.
export CARTHING_EFUSE_USID_PATH="${CARTHING_EFUSE_USID_PATH:-$REPO/local-state/usid}"
export CAR_THING_KEYSTORE="${CAR_THING_KEYSTORE:-$REPO/local-state/keys.json}"

# [CLAUDE 2026-06-03] DEV-PERSISTENCE на Mac: на маке нет смонтированного state-раздела,
# поэтому настройки/доверенные/карточки НЕ сохранялись между запусками. Кладём состояние
# в локальную папку репо и разрешаем non-mount persistence. На устройстве этого нет.
export CARTHING_STATE_ROOT="${CARTHING_STATE_ROOT:-$REPO/local-state/state}"
export CARTHING_STATE_ALLOW_NONMOUNT=1
export CARTHING_TRUSTED_DEVICES="${CARTHING_TRUSTED_DEVICES:-$CARTHING_STATE_ROOT/carthing/state.json}"

# Создать локальные папки состояния
mkdir -p "$REPO/local-state" "$CARTHING_STATE_ROOT/carthing"
[ -f "$REPO/local-state/keys.json" ] || echo '{}' > "$REPO/local-state/keys.json"

NO_GUI=0
NO_PAIRING=0
for arg in "$@"; do
    case "$arg" in
        --no-gui)      NO_GUI=1 ;;
        --no-pairing)  NO_PAIRING=1 ;;
    esac
done

if [ "$NO_GUI" = "0" ]; then
    export CAR_THING_MAC_DISPLAY=1
fi

if [ "$NO_PAIRING" = "0" ]; then
    export CAR_THING_AUTO_PAIRING=1
fi

# [CLAUDE 2026-06-03] Дублируем вывод в файл, чтобы агент читал лог вживую при совместных тестах.
mkdir -p "$REPO/local-state"
LOGFILE="$REPO/local-state/run.log"
: > "$LOGFILE"
echo "[run_local] log -> $LOGFILE"
python3 -u "$REPO/tools/run_local_main.py" 2>&1 | tee "$LOGFILE"
