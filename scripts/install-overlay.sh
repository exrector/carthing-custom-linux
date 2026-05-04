#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <target-rootfs>"
    exit 1
fi

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
target_rootfs="$1"

if [ ! -d "$target_rootfs" ]; then
    echo "target rootfs does not exist: $target_rootfs"
    exit 1
fi

cp -R "$repo_root/overlay/." "$target_rootfs/"

find "$target_rootfs/etc/init.d" -type f -name 'S*' -exec chmod +x {} +
find "$target_rootfs/usr/libexec/carthing" -type f -exec chmod +x {} +

echo "overlay installed into $target_rootfs"
