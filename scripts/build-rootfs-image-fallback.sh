#!/bin/sh
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "usage: $0 <buildroot-output-dir> <rootfs-img> [stage-dir]" >&2
    exit 1
fi

output_dir=$1
rootfs_img=$2
stage_dir=${3:-${TMPDIR:-/tmp}/carthing-rootfs-stage}

repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
target_dir="$output_dir/target"
fakeroot_bin="$output_dir/host/bin/fakeroot"
mke2fs_bin=${MKE2FS_BIN:-$(command -v mke2fs || true)}
rootfs_size=${CARTHING_ROOTFS_SIZE:-60M}
fake_root_ownership=${CARTHING_FAKE_ROOT_OWNERSHIP:-0}
rootfs_block_size=${CARTHING_ROOTFS_BLOCK_SIZE:-1024}
rootfs_fs_type=${CARTHING_ROOTFS_FS_TYPE:-ext4}
rootfs_feature_flags=${CARTHING_ROOTFS_FEATURE_FLAGS:-^64bit}

if [ ! -d "$target_dir" ]; then
    echo "missing target dir: $target_dir" >&2
    exit 1
fi

if [ "$fake_root_ownership" = "1" ] && [ ! -x "$fakeroot_bin" ]; then
    echo "missing fakeroot: $fakeroot_bin" >&2
    exit 1
fi

if [ -z "$mke2fs_bin" ] || [ ! -x "$mke2fs_bin" ]; then
    echo "mke2fs not found; set MKE2FS_BIN or install e2fsprogs" >&2
    exit 1
fi

check_absent() {
    path=$1
    label=$2
    if [ -e "$target_dir/$path" ]; then
        echo "forbidden content found in target: $label" >&2
        exit 1
    fi
}

check_present() {
    path=$1
    if [ ! -e "$target_dir/$path" ]; then
        echo "required path missing from target: $path" >&2
        exit 1
    fi
}

check_absent "usr/sbin/bluetoothd" "bluetoothd"
check_absent "usr/bin/bluetoothctl" "bluetoothctl"
check_absent "usr/bin/btattach" "btattach"
check_absent "usr/lib/systemd" "systemd libraries"
check_absent "etc/init.d/S30-usbnet" "obsolete late usbnet init script"
check_absent "etc/init.d/S40-ssh" "obsolete late ssh init script"
check_absent "etc/init.d/S40network" "buildroot ifupdown network init script"
check_absent "etc/init.d/S50dropbear" "buildroot dropbear init script"
check_absent "etc/init.d/S50telnet" "buildroot telnet init script"

check_present "etc/init.d/S05-usbnet"
check_present "etc/init.d/S06-ssh"
check_present "etc/init.d/S07-debug-http"
check_present "etc/init.d/S08-debug-telnet"
check_present "etc/init.d/S09-reverse-agent"
check_present "etc/init.d/S20-bt-init"
check_present "init"
check_present "bin/init"
check_present "usr/libexec/carthing/beacon"
check_present "usr/libexec/carthing/debug-ip-mark"
check_present "usr/libexec/carthing/init-wrapper"
check_present "usr/libexec/carthing/reverse-agent.py"
check_present "usr/libexec/carthing/run-media-remote"
check_present "usr/lib/carthing/media_remote.py"
check_present "usr/share/carthing/firmware/brcm/BCM.hcd"
check_present "usr/share/carthing/firmware/brcm/BCM20703A2.hcd"
check_present "root/.ssh/authorized_keys"
check_present "usr/sbin/dropbear"
check_present "usr/bin/dropbearkey"

rm -rf "$stage_dir"
mkdir -p "$stage_dir"
rsync -a --no-o --no-g --delete "$target_dir/" "$stage_dir/"
mkdir -p "$(dirname "$rootfs_img")"
rm -f "$rootfs_img"
truncate -s "$rootfs_size" "$rootfs_img"

if [ -e "$stage_dir/bin/busybox" ]; then
    chmod 4755 "$stage_dir/bin/busybox"
fi

build_image() {
    "$mke2fs_bin" \
        -q \
        -t "$rootfs_fs_type" \
        -b "$rootfs_block_size" \
        -I 256 \
        -L rootfs \
        -m 0 \
        -O "$rootfs_feature_flags" \
        -F \
        -d "$1" \
        "$2"
}

if [ "$fake_root_ownership" = "1" ]; then
    STAGE_DIR=$stage_dir ROOTFS_IMG=$rootfs_img MKE2FS_BIN=$mke2fs_bin "$fakeroot_bin" sh -eu <<'EOF'
chown -hR 0:0 "$STAGE_DIR"
"$MKE2FS_BIN" \
    -q \
    -t "${CARTHING_ROOTFS_FS_TYPE:-ext4}" \
    -b "${CARTHING_ROOTFS_BLOCK_SIZE:-1024}" \
    -I 256 \
    -L rootfs \
    -m 0 \
    -O "${CARTHING_ROOTFS_FEATURE_FLAGS:-^64bit}" \
    -F \
    -d "$STAGE_DIR" \
    "$ROOTFS_IMG"
EOF
else
    build_image "$stage_dir" "$rootfs_img"
fi

file "$rootfs_img"
echo "fallback rootfs image built"
echo "  target: $target_dir"
echo "  stage:  $stage_dir"
echo "  image:  $rootfs_img"
if [ "$fake_root_ownership" != "1" ]; then
    echo "  ownership: host uid/gid preserved in image"
fi
