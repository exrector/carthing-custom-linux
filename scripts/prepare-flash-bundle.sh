#!/bin/sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "usage: $0 <buildroot-output-dir> <dest-dir> [source-flash-dir]" >&2
    exit 1
fi

output_dir=$1
dest_dir=$2
source_flash_dir=${3:-~/Documents/ПРОЕКТЫ/CAR-THING/carthing-media-remote/carthing-remote/nixos-superbird/flash}

images_dir="$output_dir/images"
rootfs_src=
for candidate in "$images_dir/rootfs.ext4" "$images_dir/rootfs.ext2"; do
    if [ -f "$candidate" ]; then
        rootfs_src=$candidate
        break
    fi
done

if [ -z "$rootfs_src" ]; then
    echo "missing rootfs image in $images_dir" >&2
    exit 1
fi

for required in \
    "$source_flash_dir/bootfs.bin" \
    "$source_flash_dir/env.txt" \
    "$source_flash_dir/meta.json" \
    "$source_flash_dir/manual/manual.py"; do
    if [ ! -e "$required" ]; then
        echo "missing source flash artifact: $required" >&2
        exit 1
    fi
done

mkdir -p "$dest_dir"
rm -rf "$dest_dir/boot" "$dest_dir/manual" "$dest_dir/scripts" "$dest_dir/ssh"

cp "$source_flash_dir/bootfs.bin" "$dest_dir/bootfs.bin"
cp "$source_flash_dir/env.txt" "$dest_dir/env.txt"
cp "$source_flash_dir/meta.json" "$dest_dir/meta.json"
cp "$rootfs_src" "$dest_dir/rootfs.img"

for optional_dir in boot manual scripts ssh; do
    if [ -d "$source_flash_dir/$optional_dir" ]; then
        cp -R "$source_flash_dir/$optional_dir" "$dest_dir/$optional_dir"
    fi
done

if [ -f "$source_flash_dir/readme.md" ]; then
    cp "$source_flash_dir/readme.md" "$dest_dir/readme.md"
fi

(
    cd "$dest_dir"
    shasum -a 256 bootfs.bin env.txt meta.json rootfs.img > SHA256SUMS
)

file "$dest_dir/rootfs.img"
echo "flash bundle prepared"
echo "  source flash: $source_flash_dir"
echo "  rootfs image:  $rootfs_src"
echo "  bundle dir:    $dest_dir"
