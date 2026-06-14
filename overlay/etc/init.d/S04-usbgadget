#!/bin/sh
set -u

# Early USB gadget setup for the Car Thing rootfs.
# Goal: expose one stable USB device.
# Default boot mode is NCM-only for recovery/SSH. Optional functions such as
# USB Audio are kernel/runtime capabilities, but must be explicitly enabled by
# userspace later.

LOG=/run/carthing/S04-usbgadget.log
mkdir -p /run/carthing
exec >>"$LOG" 2>&1

[ -r /etc/default/carthing ] && . /etc/default/carthing

UDC_NAME=${CARTHING_USB_UDC:-}
PROFILE_FILE=${CARTHING_USB_PROFILE_FILE:-/run/carthing/usb-gadget-profile}
GADGET_MODE=${1:-${CARTHING_USB_GADGET_MODE:-}}
if [ -z "$GADGET_MODE" ] && [ -r "$PROFILE_FILE" ]; then
    GADGET_MODE=$(head -n 1 "$PROFILE_FILE" 2>/dev/null || true)
fi
GADGET_MODE=${GADGET_MODE:-ncm}
CONFIGFS=/sys/kernel/config
GADGET_DIR=$CONFIGFS/usb_gadget/g1
CONFIG_DIR=$GADGET_DIR/configs/c.1

log() {
    echo "[S04-usbgadget] $*"
}

unbind_if_bound() {
    if [ -f "$GADGET_DIR/UDC" ]; then
        bound=$(cat "$GADGET_DIR/UDC" 2>/dev/null || true)
        if [ -n "$bound" ]; then
            log "unbind existing UDC: $bound"
            echo "" >"$GADGET_DIR/UDC" 2>/dev/null || true
        fi
    fi
}

remove_link() {
    path=$1
    [ -L "$path" ] && rm -f "$path"
}

link_function() {
    name=$1
    mkdir -p "$GADGET_DIR/functions/$name" || return 1
    remove_link "$CONFIG_DIR/$name"
    ln -s "$GADGET_DIR/functions/$name" "$CONFIG_DIR/$name"
}

prepare_configfs() {
    [ -d "$CONFIGFS" ] || mkdir -p "$CONFIGFS"
    if ! grep -q " $CONFIGFS " /proc/mounts 2>/dev/null; then
        mount -t configfs none "$CONFIGFS" || return 1
    fi
    return 0
}

find_udc() {
    if [ -n "$UDC_NAME" ] && [ -d "/sys/class/udc/$UDC_NAME" ]; then
        echo "$UDC_NAME"
        return 0
    fi

    for try in 1 2 3 4 5; do
        for udc_path in /sys/class/udc/*; do
            [ -e "$udc_path" ] || continue
            basename "$udc_path"
            return 0
        done
        log "waiting for UDC ($try/5)"
        sleep 1
    done

    return 1
}

profile_has() {
    token=$1
    case ",$GADGET_MODE," in
        *",$token,"*) return 0 ;;
        *) return 1 ;;
    esac
}

profile_is_plain_ncm() {
    case "$GADGET_MODE" in
        ncm|legacy-ncm|rescue-ncm) return 0 ;;
        *) return 1 ;;
    esac
}

existing_usb_network_active() {
    for netdir in /sys/class/net/*; do
        [ -e "$netdir" ] || continue
        name=${netdir##*/}
        [ "$name" = "lo" ] && continue
        case "$name" in
            usb*|eth*|en*|ncm*|rndis*)
                log "existing USB network candidate: $name"
                return 0
                ;;
        esac
    done
    return 1
}

add_audio() {
    if link_function uac2.usb0 2>/dev/null; then
        echo 3 > functions/uac2.usb0/p_chmask 2>/dev/null || true
        echo 48000 > functions/uac2.usb0/p_srate 2>/dev/null || true
        echo 2 > functions/uac2.usb0/p_ssize 2>/dev/null || true
        echo 0 > functions/uac2.usb0/c_chmask 2>/dev/null || true
        echo uac2
        return 0
    fi

    if link_function uac1.usb0 2>/dev/null; then
        echo 3 > functions/uac1.usb0/p_chmask 2>/dev/null || true
        echo 48000 > functions/uac1.usb0/p_srate 2>/dev/null || true
        echo 2 > functions/uac1.usb0/p_ssize 2>/dev/null || true
        echo 0 > functions/uac1.usb0/c_chmask 2>/dev/null || true
        echo uac1
        return 0
    fi

    return 1
}

add_serial() {
    if link_function acm.usb0 2>/dev/null; then
        echo acm
        return 0
    fi
    if link_function gser.usb0 2>/dev/null; then
        echo serial
        return 0
    fi
    return 1
}

add_hid() {
    link_function hid.usb0 2>/dev/null || return 1
    echo 1 > functions/hid.usb0/protocol 2>/dev/null || true
    echo 1 > functions/hid.usb0/subclass 2>/dev/null || true
    echo 8 > functions/hid.usb0/report_length 2>/dev/null || true
    # Minimal boot keyboard report descriptor.
    printf '\x05\x01\x09\x06\xa1\x01\x05\x07\x19\xe0\x29\xe7\x15\x00\x25\x01\x75\x01\x95\x08\x81\x02\x95\x01\x75\x08\x81\x01\x95\x05\x75\x01\x05\x08\x19\x01\x29\x05\x91\x02\x95\x01\x75\x03\x91\x01\x95\x06\x75\x08\x15\x00\x25\x65\x05\x07\x19\x00\x29\x65\x81\x00\xc0' > functions/hid.usb0/report_desc 2>/dev/null || true
    echo hid
    return 0
}

add_storage() {
    backing=${CARTHING_USB_STORAGE_FILE:-/run/carthing/usb-storage.img}
    [ -f "$backing" ] || {
        log "storage backing file missing: $backing"
        return 1
    }
    link_function mass_storage.usb0 2>/dev/null || return 1
    mkdir -p functions/mass_storage.usb0/lun.0 2>/dev/null || true
    echo "$backing" > functions/mass_storage.usb0/lun.0/file 2>/dev/null || return 1
    echo 1 > functions/mass_storage.usb0/lun.0/removable 2>/dev/null || true
    echo 0 > functions/mass_storage.usb0/lun.0/ro 2>/dev/null || true
    echo storage
    return 0
}

add_midi() {
    link_function midi.usb0 2>/dev/null || return 1
    echo midi
    return 0
}

add_network_alt() {
    kind=$1
    case "$kind" in
        ecm) link_function ecm.usb0 2>/dev/null || return 1; echo ecm ;;
        eem) link_function eem.usb0 2>/dev/null || return 1; echo eem ;;
        rndis) link_function rndis.usb0 2>/dev/null || return 1; echo rndis ;;
        *) return 1 ;;
    esac
}

build_composite() {
    if profile_is_plain_ncm && existing_usb_network_active; then
        log "plain NCM already active; leaving legacy/rescue gadget untouched"
        return 0
    fi

    prepare_configfs || {
        log "configfs mount failed"
        return 1
    }

    active_udc=$(find_udc) || {
        log "no UDC present"
        return 1
    }
    log "using UDC: $active_udc"

    mkdir -p "$GADGET_DIR" || return 1
    cd "$GADGET_DIR" || return 1

    unbind_if_bound

    # Keep the Linux Foundation NCM gadget identity for continuity with macOS
    # network service matching. The interface set is expanded by configfs.
    echo 0x0525 > idVendor || return 1
    echo 0xa4a1 > idProduct || return 1
    echo 0x0100 > bcdDevice || true
    echo 0x0200 > bcdUSB || true

    mkdir -p strings/0x409
    echo "Spotify AB" > strings/0x409/manufacturer
    echo "Car Thing" > strings/0x409/product
    if [ -r /sys/class/efuse/usid ]; then
        tr -d '\000[:space:]' </sys/class/efuse/usid > strings/0x409/serialnumber 2>/dev/null || true
    fi

    mkdir -p "$CONFIG_DIR/strings/0x409" || return 1
    echo 0x80 > "$CONFIG_DIR/bmAttributes" || true
    echo 250 > "$CONFIG_DIR/MaxPower" || true

    mkdir -p functions/ncm.usb0 || {
        log "ncm function unavailable"
        return 1
    }
    echo 72:eb:0d:28:4a:54 > functions/ncm.usb0/dev_addr 2>/dev/null || true
    echo 5e:09:0d:51:23:61 > functions/ncm.usb0/host_addr 2>/dev/null || true
    remove_link "$CONFIG_DIR/ncm.usb0"
    ln -s "$GADGET_DIR/functions/ncm.usb0" "$CONFIG_DIR/ncm.usb0" || return 1

    enabled=ncm
    audio=disabled
    case "$GADGET_MODE" in
        audio|uac|uac1|uac2|ncm-audio|audio-ncm|composite)
            if audio=$(add_audio 2>/dev/null); then
                enabled="$enabled,$audio"
            else
                log "audio requested but unavailable"
                audio=unavailable
            fi
            ;;
        *)
            profile_has audio || profile_has uac || profile_has uac1 || profile_has uac2 || true
            ;;
    esac

    for token in audio uac uac1 uac2; do
        if profile_has "$token" && [ "$audio" = "disabled" ]; then
            if audio=$(add_audio 2>/dev/null); then
                enabled="$enabled,$audio"
            else
                log "$token requested but unavailable"
                audio=unavailable
            fi
        fi
    done

    if profile_has serial || profile_has acm; then
        if added=$(add_serial 2>/dev/null); then enabled="$enabled,$added"; else log "serial requested but unavailable"; fi
    fi
    if profile_has hid; then
        if added=$(add_hid 2>/dev/null); then enabled="$enabled,$added"; else log "hid requested but unavailable"; fi
    fi
    if profile_has storage || profile_has mass-storage; then
        if added=$(add_storage 2>/dev/null); then enabled="$enabled,$added"; else log "storage requested but unavailable"; fi
    fi
    if profile_has midi; then
        if added=$(add_midi 2>/dev/null); then enabled="$enabled,$added"; else log "midi requested but unavailable"; fi
    fi
    for net_alt in ecm eem rndis; do
        if profile_has "$net_alt"; then
            if added=$(add_network_alt "$net_alt" 2>/dev/null); then enabled="$enabled,$added"; else log "$net_alt requested but unavailable"; fi
        fi
    done

    echo "$enabled" > "$CONFIG_DIR/strings/0x409/configuration" || true

    echo "$active_udc" > UDC || {
        log "UDC bind failed"
        return 1
    }

    log "composite active: mode=$GADGET_MODE enabled=$enabled udc=$active_udc"
    return 0
}

fallback_g_ncm() {
    log "fallback to legacy g_ncm"
    if existing_usb_network_active; then
        log "legacy NCM already active"
        return 0
    fi
    modprobe g_ncm 2>/dev/null || {
        if existing_usb_network_active; then
            log "g_ncm appears built-in and active"
            return 0
        fi
        log "g_ncm fallback failed or unavailable"
        return 1
    }
    return 0
}

log "start"
if build_composite; then
    log "done: gadget active"
    log "end"
    exit 0
elif fallback_g_ncm; then
    if profile_is_plain_ncm; then
        log "done: g_ncm fallback"
        log "end"
        exit 0
    fi
    log "failed: requested composite mode '$GADGET_MODE' but only rescue NCM is active"
    log "end"
    exit 1
else
    log "failed: no USB gadget active"
    log "end"
    exit 1
fi
