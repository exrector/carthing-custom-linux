#!/bin/sh
set -eu

# Idempotent macOS watchdog for the Car Thing USB/NCM link.
# Intended for launchd as root. It deliberately does not touch VPN state; it only
# pins the more-specific Car Thing USB subnet route back to the USB interface.

ROOT_DEFAULT_IP=${ROOT_DEFAULT_IP:-172.16.42.2}
ROOT_STAGE2_IP=${ROOT_STAGE2_IP:-172.16.42.77}
HOST_USB_IP=${HOST_USB_IP:-172.16.42.1}
USB_ROUTE_CIDR=${USB_ROUTE_CIDR:-172.16.42.0/24}

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
BRING_UP=${CARTHING_BRING_UP:-"$SCRIPT_DIR/bring-up-device1-normal-boot-macos.sh"}
LOCK_DIR=${CARTHING_ROUTE_WATCH_LOCK:-/tmp/carthing-usb-route-watch.lock}

log() {
    printf '%s carthing-usb-route-watch: %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

discover_bsd_name() {
    ioreg -r -n "Exrector QN19" -w 0 -l 2>/dev/null \
        | sed -n 's/.*"BSD Name" = "\(.*\)".*/\1/p' \
        | head -n 1
}

route_iface() {
    ip=$1
    route get "$ip" 2>/dev/null | sed -n 's/^[[:space:]]*interface: //p' | head -n 1
}

iface_has_host_ip() {
    iface=$1
    ifconfig "$iface" 2>/dev/null | grep -q "inet $HOST_USB_IP "
}

if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT INT TERM

bsd_name=$(discover_bsd_name || true)
[ -n "$bsd_name" ] || exit 0

stage2_if=$(route_iface "$ROOT_STAGE2_IP" || true)
default_if=$(route_iface "$ROOT_DEFAULT_IP" || true)

if iface_has_host_ip "$bsd_name" \
    && [ "$stage2_if" = "$bsd_name" ] \
    && [ "$default_if" = "$bsd_name" ]; then
    exit 0
fi

log "repairing USB route: bsd=$bsd_name host_ip=$HOST_USB_IP stage2_if=${stage2_if:-none} default_if=${default_if:-none}"
"$BRING_UP" --bsd "$bsd_name"
