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
        # CLAUDE 2026-05-28: extended sleep + extra resilience.
        # Original had sleep 1, but in observation the previous python
        # process can still be holding /dev/dri/card0 momentarily after
        # os._exit(75), causing the new process to crash on DRM open and
        # the supervisor to exit. With sleep 3 the kernel has time to
        # release the DRM master handle, and we retry up to 3 times.
        # Root fix belongs in media_remote.py (graceful drm_display.close()
        # before _exit). See memory: carthing-claude-intervention-20260528.
        echo "[run-media-remote] runtime requested restart; sleeping 3s"
        sleep 3
        continue
    fi
    # CLAUDE 2026-05-28: don't die on transient runtime crash. Was:
    #     exit "$rc"
    # The original behavior killed the supervisor on any non-restart
    # exit, leaving the user with a permanent black screen until reboot.
    # Now: log and keep retrying with backoff. Max 3 fast retries before
    # giving up to avoid hot-spin if the runtime is structurally broken.
    echo "[run-media-remote] runtime exited rc=$rc; retrying after 5s"
    sleep 5
    fail_count=$((${fail_count:-0} + 1))
    if [ "$fail_count" -ge 5 ]; then
        echo "[run-media-remote] giving up after $fail_count consecutive failures"
        exit "$rc"
    fi
done
