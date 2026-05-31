#!/usr/bin/env sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cc=${CC:-aarch64-linux-gnu-gcc}

mkdir -p "$repo_root/overlay/usr/lib/carthing"
"$cc" -O3 -s -fPIC -shared \
    "$repo_root/native/frame_rotate.c" \
    -o "$repo_root/overlay/usr/lib/carthing/libcarthing_frame.so"

echo "built $repo_root/overlay/usr/lib/carthing/libcarthing_frame.so"
