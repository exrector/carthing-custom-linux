#!/bin/sh
set -eu

TARGET_DIR="$1"

mkdir -p \
    "$TARGET_DIR/bin" \
    "$TARGET_DIR/lib/firmware/brcm" \
    "$TARGET_DIR/dev/pts" \
    "$TARGET_DIR/root/.ssh" \
    "$TARGET_DIR/run/dropbear" \
    "$TARGET_DIR/run/carthing" \
    "$TARGET_DIR/usr/lib/carthing/vendor" \
    "$TARGET_DIR/usr/share/carthing/firmware/brcm" \
    "$TARGET_DIR/usr/share/fonts/truetype" \
    "$TARGET_DIR/var/lib/bluetooth" \
    "$TARGET_DIR/var/log"

for obsolete in \
    "$TARGET_DIR/etc/init.d/S30-usbnet" \
    "$TARGET_DIR/etc/init.d/S40-ssh" \
    "$TARGET_DIR/etc/init.d/S40network" \
    "$TARGET_DIR/etc/init.d/S50dropbear"
do
    rm -f "$obsolete"
done

find "$TARGET_DIR/etc/init.d" -type f -name 'S*' -exec chmod 0755 {} +
find "$TARGET_DIR/usr/libexec/carthing" -type f -exec chmod 0755 {} +

if [ -d "$TARGET_DIR/root/.ssh" ]; then
    chmod 0700 "$TARGET_DIR/root/.ssh"
fi

if [ -f "$TARGET_DIR/root/.ssh/authorized_keys" ]; then
    chmod 0600 "$TARGET_DIR/root/.ssh/authorized_keys"
fi

if [ -L "$TARGET_DIR/etc/dropbear" ]; then
    rm -f "$TARGET_DIR/etc/dropbear"
fi

mkdir -p "$TARGET_DIR/etc/dropbear"
# Dropbear host keys are generated at runtime by S06-ssh when the image doesn't
# already contain valid Dropbear-format keys. Do not embed OpenSSH private keys
# here: Dropbear treats them as invalid host keys and exits during early boot.
find "$TARGET_DIR/etc/dropbear" -maxdepth 1 -type f -name 'dropbear_*_host_key' -exec chmod 0600 {} +

if [ ! -e "$TARGET_DIR/bin/init" ] && [ -e "$TARGET_DIR/bin/busybox" ]; then
    ln -sf busybox "$TARGET_DIR/bin/init"
fi

if [ -e "$TARGET_DIR/usr/libexec/carthing/init-wrapper" ]; then
    rm -f "$TARGET_DIR/bin/init"
    cat >"$TARGET_DIR/bin/init" <<'EOF'
#!/bin/sh
exec /usr/libexec/carthing/init-wrapper "$@"
EOF
    chmod 0755 "$TARGET_DIR/bin/init"
    rm -f "$TARGET_DIR/init"
    cat >"$TARGET_DIR/init" <<'EOF'
#!/bin/sh
exec /usr/libexec/carthing/init-wrapper "$@"
EOF
    chmod 0755 "$TARGET_DIR/init"
fi
