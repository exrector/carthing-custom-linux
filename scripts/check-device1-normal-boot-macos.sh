#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
usage: check-device1-normal-boot-macos.sh [--wait SECONDS] [--ping-count COUNT]

Canonical macOS normal-boot diagnostic for device №1.

DO NOT use `adb devices` to decide whether the USB NCM gadget exists.
DO NOT infer "USB gadget absent" from failed ping or a VPN route.

Source of truth on macOS:
1. `ioreg` for `NCM Gadget` presence and `BSD Name`.
2. `ifconfig <bsd>` for link state and IP.
3. `route get <ip>` only after the USB gadget is confirmed.

If the gadget exists but macOS still leaves the link or route in a bad state,
use `./scripts/bring-up-device1-normal-boot-macos.sh` immediately.
Do not wait for `en14` or `utun*` routing to self-heal on this host.
EOF
}

repeat_after=
ping_count=1

while [ "$#" -gt 0 ]; do
    case "$1" in
        --wait)
            shift
            [ "$#" -gt 0 ] || { echo "missing value for --wait" >&2; exit 1; }
            repeat_after=$1
            ;;
        --ping-count)
            shift
            [ "$#" -gt 0 ] || { echo "missing value for --ping-count" >&2; exit 1; }
            ping_count=$1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

ROOT_DEFAULT_IP=${ROOT_DEFAULT_IP:-172.16.42.2}
ROOT_STAGE2_IP=${ROOT_STAGE2_IP:-172.16.42.77}

usb_dump() {
    ioreg -r -n 'NCM Gadget' -w 0 -l 2>/dev/null || true
}

extract_first() {
    pattern=$1
    sed -n "s/$pattern/\\1/p" | head -n 1
}

hex_mac() {
    raw=$1
    if [ -z "$raw" ]; then
        return 0
    fi
    echo "$raw" | sed 's/../&:/g; s/:$//'
}

route_iface() {
    ip=$1
    route_out=$(route get "$ip" 2>&1 || true)
    route_if=$(printf '%s\n' "$route_out" | sed -n 's/^[[:space:]]*interface: //p' | head -n 1)
    if [ -n "$route_if" ]; then
        echo "$route_if"
    elif printf '%s\n' "$route_out" | grep -qi 'Operation not permitted'; then
        echo "permission-denied"
    fi
}

ping_state() {
    ip=$1
    if ping -c "$ping_count" "$ip" >/tmp/carthing-ping.$$ 2>&1; then
        echo "ok"
    elif grep -q 'bytes from' /tmp/carthing-ping.$$ 2>/dev/null; then
        echo "partial"
    else
        echo "fail"
    fi
    rm -f /tmp/carthing-ping.$$
}

snapshot() {
    label=$1
    dump=$(usb_dump)

    echo "=== $label ==="
    echo "DO NOT USE adb OR RAW ping AS PRIMARY PRESENCE CHECKS ON macOS."
    echo "TRUST ioreg FIRST, THEN ifconfig, THEN route/ping."

    if [ -z "$dump" ]; then
        echo "usb_ncm_gadget: absent"
        echo "diagnosis: NCM Gadget not present in IOUSB tree"
        echo
        return 0
    fi

    vendor_dec=$(printf '%s\n' "$dump" | extract_first '.*"idVendor" = \([0-9][0-9]*\).*')
    product_dec=$(printf '%s\n' "$dump" | extract_first '.*"idProduct" = \([0-9][0-9]*\).*')
    bsd_name=$(printf '%s\n' "$dump" | extract_first '.*"BSD Name" = "\(.*\)".*')
    mac_hex=$(printf '%s\n' "$dump" | extract_first '.*"IOMACAddress" = <\([0-9a-fA-F]*\)>.*')
    usb_vendor=$(printf '%s\n' "$dump" | extract_first '.*"USB Vendor Name" = "\(.*\)".*')
    usb_product=$(printf '%s\n' "$dump" | extract_first '.*"USB Product Name" = "\(.*\)".*')

    vendor_hex=
    product_hex=
    if [ -n "$vendor_dec" ]; then
        vendor_hex=$(printf '0x%04x' "$vendor_dec")
    fi
    if [ -n "$product_dec" ]; then
        product_hex=$(printf '0x%04x' "$product_dec")
    fi

    echo "usb_ncm_gadget: present"
    echo "usb_vendor_name: ${usb_vendor:-unknown}"
    echo "usb_product_name: ${usb_product:-unknown}"
    echo "usb_vid_pid: ${vendor_hex:-unknown}:${product_hex:-unknown}"
    echo "usb_bsd_name: ${bsd_name:-unknown}"
    echo "usb_mac: $(hex_mac "${mac_hex:-}")"

    if [ -z "$bsd_name" ]; then
        echo "diagnosis: USB gadget exists but macOS did not publish a BSD network interface"
        echo
        return 0
    fi

    ifconfig_out=$(ifconfig "$bsd_name" 2>&1 || true)
    if_status=$(printf '%s\n' "$ifconfig_out" | sed -n 's/^[[:space:]]*status: //p' | head -n 1)
    if_inet4=$(printf '%s\n' "$ifconfig_out" | sed -n 's/^[[:space:]]*inet \([0-9.]*\).*/\1/p' | head -n 1)
    route_default=$(route_iface "$ROOT_DEFAULT_IP")
    route_stage2=$(route_iface "$ROOT_STAGE2_IP")
    ping_default=$(ping_state "$ROOT_DEFAULT_IP")
    ping_stage2=$(ping_state "$ROOT_STAGE2_IP")

    echo "ifconfig_status: ${if_status:-unknown}"
    echo "ifconfig_inet4: ${if_inet4:-none}"
    echo "route_${ROOT_DEFAULT_IP}_interface: ${route_default:-none}"
    echo "route_${ROOT_STAGE2_IP}_interface: ${route_stage2:-none}"
    echo "ping_${ROOT_DEFAULT_IP}: $ping_default"
    echo "ping_${ROOT_STAGE2_IP}: $ping_stage2"

    if [ "${if_status:-}" = "inactive" ]; then
        echo "diagnosis: USB gadget is present and mapped to ${bsd_name}, but the NCM link is not active yet"
        echo "rule: do not wait; force host-side bring-up now"
        echo "next_action: ./scripts/bring-up-device1-normal-boot-macos.sh --bsd ${bsd_name}"
    elif [ -n "${route_default:-}" ] && [ "$route_default" != "$bsd_name" ]; then
        echo "diagnosis: USB link exists on ${bsd_name}, but route to ${ROOT_DEFAULT_IP} is pinned elsewhere"
        echo "rule: do not wait; force host-side bring-up now"
        echo "next_action: ./scripts/bring-up-device1-normal-boot-macos.sh --bsd ${bsd_name}"
    elif [ "$ping_default" = "ok" ] || [ "$ping_stage2" = "ok" ]; then
        echo "diagnosis: USB gadget and network path are alive"
    else
        echo "diagnosis: USB gadget and BSD interface exist, but target IPs still do not answer"
    fi

    echo
}

snapshot "normal-boot pass 1"

if [ -n "${repeat_after:-}" ]; then
    sleep "$repeat_after"
    snapshot "normal-boot pass 2 after ${repeat_after}s"
fi
