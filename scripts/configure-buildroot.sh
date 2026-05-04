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

if [ ! -d "$buildroot_dir" ]; then
    echo "buildroot dir does not exist: $buildroot_dir"
    exit 1
fi

. "$repo_root/scripts/buildroot-repo-alias.sh"
. "$repo_root/scripts/buildroot-host-env.sh"
prepare_buildroot_repo_alias
prepare_buildroot_host_env
sh "$repo_root/scripts/patch-buildroot-darwin.sh" "$buildroot_dir"

make -C "$buildroot_dir" \
    O="$output_dir" \
    BR2_EXTERNAL="$CARTHING_BR2_EXTERNAL" \
    HOSTCC="$HOSTCC" \
    HOSTCXX="$HOSTCXX" \
    carthing_superbird_rootfs_defconfig

echo "Buildroot configured."
echo "  buildroot: $buildroot_dir"
echo "  output:    $output_dir"
echo "  external:  $CARTHING_BR2_EXTERNAL"
echo "  alias:     ${CARTHING_REPO_ALIAS_ROOT:-unset}"
echo "  hostcc:    ${HOSTCC:-unset}"
echo "  hostcxx:   ${HOSTCXX:-unset}"
