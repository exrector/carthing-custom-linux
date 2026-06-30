#!/bin/sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY_DIR="$HOME/Library/Application Support/CarThingBTLink"
KEY_FILE="$KEY_DIR/maintenance.key"
HOST="${CARTHING_SSH_HOST:-carthing}"
DOMAIN="gui/$(id -u)"

"$ROOT/scripts/bring-up-device1-normal-boot-macos.sh"
mkdir -p "$KEY_DIR"
if [ ! -s "$KEY_FILE" ]; then
    umask 077
    temporary="$KEY_FILE.tmp"
    openssl rand -hex 32 > "$temporary"
    mv "$temporary" "$KEY_FILE"
fi
chmod 600 "$KEY_FILE"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" '
set -eu
mount -o remount,rw /
mkdir -p /var/lib/carthing
umask 077
cat > /var/lib/carthing/maintenance.key
chmod 600 /var/lib/carthing/maintenance.key
sync
mount -o remount,ro /
' < "$KEY_FILE"

ssh -o BatchMode=yes -o ConnectTimeout=8 "$HOST" '
PID=$(ps | grep carthing_runtime.py | grep -v grep | awk "{print \$1}")
[ -n "$PID" ] && kill "$PID" 2>/dev/null || true
'
launchctl kickstart -k "$DOMAIN/com.carthing.btlink"
echo "Bluetooth maintenance key provisioned"
