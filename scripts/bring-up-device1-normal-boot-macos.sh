#!/bin/sh
set -eu

usage() {
    cat <<'EOF'
usage: bring-up-device1-normal-boot-macos.sh [--bsd IFACE]

Host-side macOS remediation for device №1 normal boot.

This script does not decide whether the USB gadget exists.
Run `check-device1-normal-boot-macos.sh` first to confirm `NCM Gadget`
and the BSD interface name, then use this script to:

1. assign `172.16.42.1/24` to the BSD interface
2. clear stale ARP entries for the target IPs
3. pin `172.16.42.0/24` back to that interface
4. re-check ICMP on `.2`, `.77`, `.84`, and `.85`
EOF
}

ROOT_DEFAULT_IP=${ROOT_DEFAULT_IP:-172.16.42.2}
ROOT_STAGE2_IP=${ROOT_STAGE2_IP:-172.16.42.77}
ROOT_S09_ENTER_IP=${ROOT_S09_ENTER_IP:-172.16.42.84}
ROOT_S09_ALIVE_IP=${ROOT_S09_ALIVE_IP:-172.16.42.85}
HOST_USB_IP=${HOST_USB_IP:-172.16.42.1}
USB_NETMASK=${USB_NETMASK:-255.255.255.0}
USB_ROUTE_CIDR=${USB_ROUTE_CIDR:-172.16.42.0/24}

bsd_name=

while [ "$#" -gt 0 ]; do
    case "$1" in
        --bsd)
            shift
            [ "$#" -gt 0 ] || { echo "missing value for --bsd" >&2; exit 1; }
            bsd_name=$1
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

discover_bsd_name() {
    ioreg -r -n 'NCM Gadget' -w 0 -l 2>/dev/null \
        | sed -n 's/.*"BSD Name" = "\(.*\)".*/\1/p' \
        | head -n 1
}

ping_state() {
    ip=$1
    if ping -c 1 -W 1000 "$ip" >/tmp/carthing-host-up-ping.$$ 2>&1; then
        echo "ok"
    elif grep -q 'bytes from' /tmp/carthing-host-up-ping.$$ 2>/dev/null; then
        echo "partial"
    else
        echo "fail"
    fi
    rm -f /tmp/carthing-host-up-ping.$$
}

route_iface() {
    ip=$1
    route get "$ip" 2>/dev/null | sed -n 's/^[[:space:]]*interface: //p' | head -n 1
}

arp_state() {
    ip=$1
    arp -an | sed -n "s/^.*(\\($ip\\)).* at \\([^ ]*\\) .*$/\\2/p" | head -n 1
}

pin_route() {
    attempts=3
    while [ "$attempts" -gt 0 ]; do
        attempts=$((attempts - 1))
        sudo route -n delete -net "$USB_ROUTE_CIDR" >/dev/null 2>&1 || true
        sudo route -n add -net "$USB_ROUTE_CIDR" -interface "$bsd_name" >/dev/null 2>&1 \
            || sudo route -n change -net "$USB_ROUTE_CIDR" -interface "$bsd_name" >/dev/null 2>&1 \
            || true

        default_if=$(route_iface "$ROOT_DEFAULT_IP")
        stage2_if=$(route_iface "$ROOT_STAGE2_IP")
        if [ "$default_if" = "$bsd_name" ] && [ "$stage2_if" = "$bsd_name" ]; then
            return 0
        fi
        sleep 1
    done
    return 1
}

if [ -z "${bsd_name:-}" ]; then
    bsd_name=$(discover_bsd_name || true)
fi

if [ -z "${bsd_name:-}" ]; then
    echo "NCM Gadget BSD interface not found in ioreg" >&2
    echo "run ./scripts/check-device1-normal-boot-macos.sh first" >&2
    exit 1
fi

echo "host_bsd_name: $bsd_name"
echo "host_assign_ip: $HOST_USB_IP/$USB_NETMASK"
sudo ifconfig "$bsd_name" "$HOST_USB_IP" netmask "$USB_NETMASK" up

for ip in "$ROOT_DEFAULT_IP" "$ROOT_STAGE2_IP" "$ROOT_S09_ENTER_IP" "$ROOT_S09_ALIVE_IP"; do
    sudo arp -d "$ip" >/dev/null 2>&1 || true
done

route_ok=0
if pin_route; then
    route_ok=1
fi

ifconfig "$bsd_name"
echo "route_pin_verified: $route_ok"
echo "route_${ROOT_DEFAULT_IP}_interface: $(route_iface "$ROOT_DEFAULT_IP")"
echo "route_${ROOT_STAGE2_IP}_interface: $(route_iface "$ROOT_STAGE2_IP")"
echo "ping_${ROOT_DEFAULT_IP}: $(ping_state "$ROOT_DEFAULT_IP")"
echo "ping_${ROOT_STAGE2_IP}: $(ping_state "$ROOT_STAGE2_IP")"
echo "ping_${ROOT_S09_ENTER_IP}: $(ping_state "$ROOT_S09_ENTER_IP")"
echo "ping_${ROOT_S09_ALIVE_IP}: $(ping_state "$ROOT_S09_ALIVE_IP")"
echo "arp_${ROOT_DEFAULT_IP}: $(arp_state "$ROOT_DEFAULT_IP")"
echo "arp_${ROOT_STAGE2_IP}: $(arp_state "$ROOT_STAGE2_IP")"
echo "arp_${ROOT_S09_ENTER_IP}: $(arp_state "$ROOT_S09_ENTER_IP")"
echo "arp_${ROOT_S09_ALIVE_IP}: $(arp_state "$ROOT_S09_ALIVE_IP")"
