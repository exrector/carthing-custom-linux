#!/bin/sh
set -eu

if [ "$#" -ne 1 ]; then
    echo "usage: $0 <buildroot-output-dir>" >&2
    exit 1
fi

output_dir=$1
images_dir="$output_dir/images"
rootfs_tar="$images_dir/rootfs.tar"

if [ ! -f "$rootfs_tar" ]; then
    echo "missing rootfs tar: $rootfs_tar" >&2
    exit 1
fi

check_absent() {
    pattern=$1
    label=$2
    if tar -tf "$rootfs_tar" | grep -Eq "$pattern"; then
        echo "forbidden content found in rootfs: $label" >&2
        exit 1
    fi
}

check_present() {
    path=$1
    if ! tar -tf "$rootfs_tar" | grep -Fxq "$path"; then
        echo "required path missing from rootfs: $path" >&2
        exit 1
    fi
}

check_absent '(^|/)(systemd|systemctl)(/|$)' 'systemd'
check_absent '(^|/)usr/sbin/bluetoothd$' 'bluetoothd'
check_absent '(^|/)usr/bin/bluetoothctl$' 'bluetoothctl'
check_absent '(^|/)usr/bin/btattach$' 'btattach'
check_absent '(^|/)usr/lib/systemd(/|$)' 'systemd libraries'
check_absent '(^|/)etc/init\.d/S30-usbnet$' 'obsolete late usbnet init script'
check_absent '(^|/)etc/init\.d/S40-ssh$' 'obsolete late ssh init script'
check_absent '(^|/)etc/init\.d/S40network$' 'buildroot ifupdown network init script'
check_absent '(^|/)etc/init\.d/S50dropbear$' 'buildroot dropbear init script'

check_present './etc/init.d/S02-runtime-tmp'
check_present './etc/init.d/S05-usbnet'
check_present './etc/init.d/S06-ssh'
check_present './etc/init.d/S07-debug-http'
check_present './etc/init.d/S08-debug-telnet'
check_present './etc/init.d/S09-reverse-agent'
check_present './etc/init.d/S20-bt-init'
check_present './init'
check_present './bin/init'
check_present './usr/libexec/carthing/beacon'
check_present './usr/libexec/carthing/reverse-agent.py'
check_present './usr/libexec/carthing/run-media-remote'
check_present './usr/libexec/carthing/init-wrapper'
check_present './usr/libexec/carthing/python-runtime-selftest'
check_present './usr/lib/carthing/carthing_runtime.py'
check_present './usr/lib/carthing/vendor/BUMBLE-VERSION'
check_present './usr/lib/carthing/vendor/bumble/_version.py'
check_present './usr/lib/carthing/vendor/bumble/pairing.py'
check_present './usr/lib/carthing/vendor/bumble/transport/hci_socket.py'
check_present './usr/share/carthing/firmware/brcm/BCM.hcd'
check_present './usr/share/carthing/firmware/brcm/BCM20703A2.hcd'
check_present './usr/share/carthing/firmware/brcm/BCM4345C0.hcd'
check_present './usr/bin/carthing-btattach-mini'
check_present './root/.ssh/authorized_keys'
check_present './usr/sbin/dropbear'
check_present './usr/bin/dropbearkey'
check_present './usr/bin/pip3'
check_present './usr/lib/python3.14/sqlite3/__init__.py'
check_present './usr/lib/python3.14/sqlite3/__pycache__/__init__.cpython-314.pyc'
check_present './usr/lib/python3.14/bz2.py'
check_present './usr/lib/python3.14/lzma.py'
check_present './usr/lib/python3.14/curses/__init__.py'
check_present './usr/lib/carthing/__pycache__/carthing_runtime.cpython-314.pyc'

echo "target rootfs verification passed"
echo "  no bluez/systemd artifacts detected in rootfs.tar"
echo "  required Car Thing runtime files are present"
