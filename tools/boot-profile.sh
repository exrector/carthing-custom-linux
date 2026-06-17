#!/bin/sh
set -eu

host=carthing
bring_up=1

usage() {
    cat <<'EOF'
Usage: tools/boot-profile.sh [--host HOST] [--no-bring-up]

Collect a read-only boot profile from a running Car Thing over SSH.
The report combines kernel dmesg markers, init-wrapper logs, runtime
BOOT_PROFILE milestones, mounts, partition layout, and key process state.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --host)
            host=${2:?missing host after --host}
            shift 2
            ;;
        --no-bring-up)
            bring_up=0
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "boot-profile: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if [ "$bring_up" = 1 ] && [ -x "$repo_root/scripts/bring-up-device1-normal-boot-macos.sh" ]; then
    "$repo_root/scripts/bring-up-device1-normal-boot-macos.sh" >/dev/null 2>&1 || true
fi

ssh -o BatchMode=yes -o ConnectTimeout=5 "$host" 'sh -s' <<'REMOTE'
set -eu

section() {
    printf '\n== %s ==\n' "$1"
}

show_file() {
    path=$1
    if [ -f "$path" ]; then
        printf '%s\n' "--- $path ---"
        cat "$path"
    else
        printf '%s missing\n' "$path"
    fi
}

clean_ascii() {
    tr -cd '\11\12\15\40-\176'
}

runtime_log=/run/carthing/carthing-remote.log
if [ -f /etc/default/carthing ]; then
    # shellcheck disable=SC1091
    . /etc/default/carthing
    runtime_log=${CARTHING_RUNTIME_LOG:-$runtime_log}
fi

section "device"
date -u 2>/dev/null || true
uname -a 2>/dev/null || true
printf 'uptime: '
cat /proc/uptime 2>/dev/null || true
printf 'cmdline: '
cat /proc/cmdline 2>/dev/null | clean_ascii || true
printf '\n'

section "partitions"
cat /proc/partitions 2>/dev/null || true

section "mounts"
mount | grep -E ' / |carthing-state|mmcblk|vfat|ext4' || true

section "p1 boot/state files"
if [ -d /run/carthing-state ]; then
    ls -la /run/carthing-state 2>/dev/null | sed -n '1,80p' || true
    show_file /run/carthing-state/bootargs.txt
else
    echo "/run/carthing-state missing"
fi

section "kernel/init timeline"
dmesg 2>/dev/null | clean_ascii | grep -E \
'Linux version|Kernel command line|mmcblk0|EXT4-fs|VFS: Mounted root|init-wrapper|S0[3-9]|S10|S12|S20|btattach|Bluetooth|brcm|hci|usb0|g_ether|NCM|dropbear|disabled-S50|carthing-remote|am_drm_lcd|am_meson_crtc|aml_bl_on_function|apple_mfi_auth' \
| tail -n 220 || true

section "init-wrapper log"
show_file /run/carthing/init-wrapper.log

section "runtime profile"
if [ -f "$runtime_log" ]; then
    printf '%s\n' "--- $runtime_log ---"
    grep -E 'BOOT_PROFILE|GUI active|GUI disabled|runtime up|transfer disabled|transfer ready|apply_visibility done|kick_reconnect scheduled|Traceback|Exception' "$runtime_log" | tail -n 240 || true
else
    printf '%s missing\n' "$runtime_log"
fi

section "processes"
ps w | grep -E 'PID|dropbear|btattach|carthing_runtime|run-media-remote|disabled-S50|python3|reverse-agent' || true

section "runtime state"
ls -la /run/carthing 2>/dev/null | sed -n '1,120p' || true
show_file /run/carthing/runtime-bt.json

section "profile verdict hints"
echo "Kernel/init markers come from dmesg seconds since kernel start."
echo "BOOT_PROFILE proc_uptime_s comes from /proc/uptime inside carthing_runtime.py."
echo "If BOOT_PROFILE is absent, the live rootfs predates runtime milestone logging."
REMOTE
