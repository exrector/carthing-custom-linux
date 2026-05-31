#!/bin/sh
set -eu

[ -r /etc/default/carthing ] && . /etc/default/carthing

profile_file=${CARTHING_USB_PROFILE_FILE:-/run/carthing/usb-gadget-profile}
service=${CARTHING_USB_GADGET_SERVICE:-/etc/init.d/S04-usbgadget}

usage() {
    echo "usage: usb-profile get|set <profile>|apply|list" >&2
    exit 2
}

ensure_dirs() {
    mkdir -p "$(dirname "$profile_file")"
}

case "${1:-}" in
    get)
        if [ -r "$profile_file" ]; then
            cat "$profile_file"
        else
            echo "${CARTHING_USB_GADGET_MODE:-ncm}"
        fi
        ;;
    set)
        [ $# -eq 2 ] || usage
        ensure_dirs
        "$service" "$2"
        printf '%s\n' "$2" > "$profile_file"
        ;;
    apply)
        profile="${2:-}"
        if [ -z "$profile" ] && [ -r "$profile_file" ]; then
            profile=$(head -n 1 "$profile_file" 2>/dev/null || true)
        fi
        profile=${profile:-${CARTHING_USB_GADGET_MODE:-ncm}}
        "$service" "$profile"
        ;;
    list)
        cat <<'EOF'
ncm
ncm,audio
ncm,serial
ncm,hid
ncm,midi
ncm,storage
ncm,ecm
ncm,eem
ncm,rndis
ncm,audio,serial,hid,midi
EOF
        ;;
    *)
        usage
        ;;
esac
