#!/bin/sh
# Car Thing — comprehensive hardware enumeration.
# Reads /sys, /proc, /dev only. No package installs, no writes.

set -u

hdr() {
    printf '\n=== %s ===\n' "$1"
}

dump() {
    if [ -e "$1" ]; then
        cat "$1" 2>&1
    else
        printf '(missing: %s)\n' "$1"
    fi
}

list_dir() {
    if [ -d "$1" ]; then
        ls -la "$1" 2>&1
    else
        printf '(no dir: %s)\n' "$1"
    fi
}

hdr "kernel"
dump /proc/version
dump /proc/cmdline

hdr "cpu"
grep -E "model name|Hardware|Revision|Serial|CPU implementer|CPU part" /proc/cpuinfo | head -20

hdr "loaded modules"
cut -d' ' -f1 /proc/modules 2>/dev/null | sort

hdr "/proc/devices (char + block)"
dump /proc/devices

hdr "/proc/partitions"
dump /proc/partitions

hdr "/proc/asound/cards"
dump /proc/asound/cards

hdr "/proc/asound/devices"
dump /proc/asound/devices

hdr "/dev/snd"
list_dir /dev/snd

for card in /proc/asound/card*; do
    [ -d "$card" ] || continue
    hdr "$card overview"
    list_dir "$card"
    [ -f "$card/id" ] && printf 'id: '; dump "$card/id"
    for pcm in "$card"/pcm*; do
        [ -d "$pcm" ] || continue
        hdr "$pcm"
        list_dir "$pcm"
        [ -f "$pcm/info" ] && dump "$pcm/info"
    done
done

hdr "/sys/class/sound"
list_dir /sys/class/sound

hdr "/sys/class/backlight"
list_dir /sys/class/backlight
for bl in /sys/class/backlight/*; do
    [ -d "$bl" ] || continue
    hdr "$bl details"
    for f in actual_brightness brightness max_brightness power scale type; do
        if [ -f "$bl/$f" ]; then
            printf '%s: ' "$f"; dump "$bl/$f"
        fi
    done
done

hdr "/sys/class/leds"
list_dir /sys/class/leds
for led in /sys/class/leds/*; do
    [ -d "$led" ] || continue
    hdr "$led details"
    for f in brightness max_brightness trigger; do
        if [ -f "$led/$f" ]; then
            printf '%s: ' "$f"; dump "$led/$f"
        fi
    done
done

hdr "/sys/bus/iio/devices (sensors)"
list_dir /sys/bus/iio/devices
for iio in /sys/bus/iio/devices/iio:device*; do
    [ -d "$iio" ] || continue
    hdr "$iio details"
    [ -f "$iio/name" ] && printf 'name: '; dump "$iio/name"
    for f in "$iio"/in_*_raw "$iio"/in_*_scale "$iio"/in_*_offset; do
        [ -f "$f" ] && { printf '%s: ' "$(basename "$f")"; dump "$f"; }
    done
done

hdr "/sys/class/thermal"
list_dir /sys/class/thermal
for tz in /sys/class/thermal/thermal_zone*; do
    [ -d "$tz" ] || continue
    name=$(cat "$tz/type" 2>/dev/null)
    temp=$(cat "$tz/temp" 2>/dev/null)
    printf '%s: type=%s temp=%s\n' "$tz" "$name" "$temp"
done

hdr "/sys/bus/i2c/devices"
list_dir /sys/bus/i2c/devices

hdr "/sys/bus/spi/devices"
list_dir /sys/bus/spi/devices

hdr "/sys/class/drm"
list_dir /sys/class/drm

hdr "/sys/class/gpio (exported)"
list_dir /sys/class/gpio

hdr "/sys/class/rtc"
list_dir /sys/class/rtc

hdr "/sys/class/power_supply"
list_dir /sys/class/power_supply

hdr "/sys/class/net"
ls -la /sys/class/net 2>&1 | head -20

hdr "/sys/firmware/devicetree (top)"
ls /sys/firmware/devicetree/base 2>&1 | head -30

hdr "dmesg (head)"
dmesg 2>&1 | head -120
