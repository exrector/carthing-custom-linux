#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "usage: $0 <buildroot-dir> [output-dir]"
    exit 1
fi

buildroot_dir="$1"
output_dir="${2:-$buildroot_dir/output-carthing}"
repo_root=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
CARTHING_REPO_ROOT="$repo_root"
export CARTHING_REPO_ROOT

. "$repo_root/scripts/buildroot-repo-alias.sh"
. "$repo_root/scripts/buildroot-host-env.sh"
prepare_buildroot_repo_alias
prepare_buildroot_host_env

sh "$repo_root/scripts/repair-buildroot-ownership.sh" "$buildroot_dir" "$output_dir"

sh "$repo_root/scripts/configure-buildroot.sh" "$buildroot_dir" "$output_dir"

make -C "$buildroot_dir" \
    O="$output_dir" \
    BR2_EXTERNAL="$CARTHING_BR2_EXTERNAL" \
    HOSTCC="$HOSTCC" \
    HOSTCXX="$HOSTCXX" \
    olddefconfig

sh "$repo_root/scripts/refresh-buildroot-toolchainfile.sh" "$output_dir"
sh "$repo_root/scripts/refresh-buildroot-toolchain-state.sh" "$output_dir"

make -C "$buildroot_dir" \
    O="$output_dir" \
    BR2_EXTERNAL="$CARTHING_BR2_EXTERNAL" \
    HOSTCC="$HOSTCC" \
    HOSTCXX="$HOSTCXX"
