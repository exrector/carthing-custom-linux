#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <target-rootfs>"
    exit 1
fi

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
target_rootfs="$1"
overlay_root="$repo_root/overlay"

if [ ! -d "$target_rootfs" ]; then
    echo "target rootfs does not exist: $target_rootfs"
    exit 1
fi

if command -v rsync >/dev/null 2>&1; then
    rsync -a \
        --delete-excluded \
        --exclude='__pycache__/' \
        "$overlay_root/" "$target_rootfs/"
else
    (
        cd "$overlay_root"
        tar --exclude='__pycache__' -cf - .
    ) | (
        cd "$target_rootfs"
        tar -xf -
    )
fi

for obsolete in \
    "$target_rootfs/etc/init.d/S30-usbnet" \
    "$target_rootfs/etc/init.d/S40-ssh" \
    "$target_rootfs/etc/init.d/S40network" \
    "$target_rootfs/etc/init.d/S50dropbear"
do
    rm -f "$obsolete"
done

find "$target_rootfs/etc/init.d" -type f -name 'S*' -exec chmod +x {} +
find "$target_rootfs/usr/libexec/carthing" -type f -exec chmod +x {} +

echo "overlay installed into $target_rootfs"
