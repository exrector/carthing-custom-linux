#!/bin/sh
set -eu

load_runtime_env() {
    . /etc/default/carthing
    [ -r "${CARTHING_BT_RUNTIME_PROFILE:-/run/carthing/bt-runtime.env}" ] && . "${CARTHING_BT_RUNTIME_PROFILE:-/run/carthing/bt-runtime.env}"
    [ -r "${CARTHING_AUDIO_RUNTIME_PROFILE:-/run/carthing/audio-runtime.env}" ] && . "${CARTHING_AUDIO_RUNTIME_PROFILE:-/run/carthing/audio-runtime.env}"
    [ -r "${CARTHING_SENSOR_RUNTIME_PROFILE:-/run/carthing/sensor-runtime.env}" ] && . "${CARTHING_SENSOR_RUNTIME_PROFILE:-/run/carthing/sensor-runtime.env}"

    export PYTHONPATH="$CARTHING_RUNTIME_LIB"
    export CAR_THING_LIB="$CARTHING_RUNTIME_LIB"
    export CAR_THING_KEYSTORE="$CARTHING_RUNTIME_KEYS"

    transport=${CARTHING_BT_BUMBLE_TRANSPORT:-}
    if [ -z "$transport" ]; then
        case "${CARTHING_BT_INIT_BACKEND:-fwload}" in
            attach)
                transport=hci-socket:0
                ;;
            *)
                transport="serial:${CARTHING_BT_UART},${CARTHING_BT_CONTROLLER_BAUD:-3000000}"
                ;;
        esac
    fi

    export CAR_THING_TRANSPORT="$transport"
    export CAR_THING_BD_ADDRESS="$CARTHING_BD_ADDRESS"
    export CARTHING_INPUT_BUTTONS=/run/carthing/input-buttons
    export CARTHING_INPUT_ROTARY=/run/carthing/input-rotary
}

load_runtime_env

if [ ! -f "$CARTHING_RUNTIME_ENTRY" ]; then
    echo "[run-media-remote] missing runtime entry: $CARTHING_RUNTIME_ENTRY"
    exit 1
fi

restart_code=${CARTHING_RUNTIME_RESTART_EXIT_CODE:-75}

while :; do
    load_runtime_env
    python3 "$CARTHING_RUNTIME_ENTRY"
    rc=$?
    if [ "$rc" = "$restart_code" ]; then
        echo "[run-media-remote] runtime requested restart"
        sleep 1
        continue
    fi
    exit "$rc"
done
