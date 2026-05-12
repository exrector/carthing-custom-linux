#!/bin/sh
set -eu

TARGET_DIR="$1"
DEFAULT_ROOT_PASSWORD="carthing"
DEFAULT_ROOT_PASSWORD_HASH='$6$carthing$V4FPwXVBv//YUovhGvEi6cpjtEVxhUUQ7NqTjMfiRdslZ.O0j.9CA5W.Z14GOcmB7O1/vsscFyuoWKz9vm2jD.'

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

if [ -f "$TARGET_DIR/etc/shadow" ]; then
    python3 - "$TARGET_DIR/etc/shadow" "$DEFAULT_ROOT_PASSWORD_HASH" <<'EOF'
import sys
from pathlib import Path

shadow_path = Path(sys.argv[1])
root_hash = sys.argv[2]
lines = shadow_path.read_text(encoding="utf-8").splitlines()
updated = False
for idx, line in enumerate(lines):
    if line.startswith("root:"):
        parts = line.split(":")
        while len(parts) < 9:
            parts.append("")
        parts[1] = root_hash
        parts[2] = parts[2] or "0"
        parts[3] = parts[3] or "0"
        parts[4] = parts[4] or "99999"
        parts[5] = parts[5] or "7"
        lines[idx] = ":".join(parts[:9])
        updated = True
        break
if not updated:
    lines.append(f"root:{root_hash}:0:0:99999:7:::")
shadow_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
EOF
else
    mkdir -p "$TARGET_DIR/etc"
    printf 'root:%s:0:0:99999:7:::\n' "$DEFAULT_ROOT_PASSWORD_HASH" >"$TARGET_DIR/etc/shadow"
fi
chmod 0600 "$TARGET_DIR/etc/shadow"

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
