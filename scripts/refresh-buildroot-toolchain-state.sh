#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <buildroot-output-dir>" >&2
    exit 1
fi

output_dir=$1
config_file="$output_dir/.config"

[ -f "$config_file" ] || exit 0

if grep -q '^BR2_INSTALL_LIBSTDCPP=y$' "$config_file"; then
    cxx_enabled=1
else
    cxx_enabled=0
fi

find_first_dir() {
    find "$1" -maxdepth 1 -type d -name "$2" | sort | sed -n '1p'
}

clear_package_stamps() {
    package_dir=$1
    [ -n "$package_dir" ] || return 0

    rm -f \
        "$package_dir/.stamp_configured" \
        "$package_dir/.stamp_built" \
        "$package_dir/.stamp_host_installed" \
        "$package_dir/.stamp_staging_installed" \
        "$package_dir/.stamp_target_installed" \
        "$package_dir/.stamp_images_installed" \
        "$package_dir/.stamp_installed"
}

host_gcc_final_dir=$(find_first_dir "$output_dir/build" 'host-gcc-final-*')
gcc_final_dir=$(find_first_dir "$output_dir/build" 'gcc-final-*')
host_gcc_config_status="${host_gcc_final_dir:+$host_gcc_final_dir/build/config.status}"

[ -f "$host_gcc_config_status" ] || exit 0

if grep -q -- '--enable-languages=.*c++' "$host_gcc_config_status"; then
    host_gcc_has_cxx=1
else
    host_gcc_has_cxx=0
fi

if [ "$cxx_enabled" -eq 1 ] && [ "$host_gcc_has_cxx" -eq 0 ]; then
    clear_package_stamps "$host_gcc_final_dir"
    clear_package_stamps "$gcc_final_dir"
fi
