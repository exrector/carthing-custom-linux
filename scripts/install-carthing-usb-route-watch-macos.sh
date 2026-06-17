#!/bin/sh
set -eu

LABEL=com.exrector.carthing.usb-route-watch
PLIST=/Library/LaunchDaemons/$LABEL.plist
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
WATCH_SCRIPT=$ROOT/scripts/carthing-usb-route-watch-macos.sh
BRING_UP_SCRIPT=$ROOT/scripts/bring-up-device1-normal-boot-macos.sh
INSTALL_DIR=/usr/local/sbin
INSTALL_WATCH=$INSTALL_DIR/carthing-usb-route-watch-macos.sh
INSTALL_BRING_UP=$INSTALL_DIR/bring-up-device1-normal-boot-macos.sh
ROOT_STAGE2_IP=${ROOT_STAGE2_IP:-172.16.42.77}
USB_ROUTE_CIDR=${USB_ROUTE_CIDR:-172.16.42.0/24}

usage() {
    cat <<EOF
usage: install-carthing-usb-route-watch-macos.sh [--uninstall]

Installs a root launchd watchdog that keeps the Car Thing USB/NCM route pinned
to the current Exrector QN19 BSD interface. It does not disable or reconfigure
VPN; it only repairs the specific $ROOT_STAGE2_IP/$USB_ROUTE_CIDR access path.
EOF
}

as_root() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    else
        sudo "$@"
    fi
}

uninstall=0
case "${1:-}" in
    --uninstall) uninstall=1 ;;
    -h|--help) usage; exit 0 ;;
    "") ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 1 ;;
esac

if [ "$(uname -s)" != "Darwin" ]; then
    echo "This installer is macOS-only." >&2
    exit 1
fi

if [ "$uninstall" = 1 ]; then
    as_root launchctl bootout system "$PLIST" >/dev/null 2>&1 || true
    as_root rm -f "$PLIST"
    as_root rm -f "$INSTALL_WATCH" "$INSTALL_BRING_UP"
    echo "uninstalled: $PLIST"
    exit 0
fi

[ -x "$WATCH_SCRIPT" ] || chmod +x "$WATCH_SCRIPT"
[ -x "$BRING_UP_SCRIPT" ] || chmod +x "$BRING_UP_SCRIPT"
as_root mkdir -p "$INSTALL_DIR"
as_root install -o root -g wheel -m 0755 "$WATCH_SCRIPT" "$INSTALL_WATCH"
as_root install -o root -g wheel -m 0755 "$BRING_UP_SCRIPT" "$INSTALL_BRING_UP"

tmp=$(mktemp /tmp/carthing-route-watch.XXXXXX.plist)
trap 'rm -f "$tmp"' EXIT INT TERM

cat > "$tmp" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
 "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>$INSTALL_WATCH</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>StartInterval</key>
  <integer>10</integer>
  <key>StandardOutPath</key>
  <string>/var/log/carthing-usb-route-watch.log</string>
  <key>StandardErrorPath</key>
  <string>/var/log/carthing-usb-route-watch.err</string>
</dict>
</plist>
EOF

as_root install -o root -g wheel -m 0644 "$tmp" "$PLIST"
as_root launchctl bootout system "$PLIST" >/dev/null 2>&1 || true
as_root launchctl bootstrap system "$PLIST"
as_root launchctl kickstart -k "system/$LABEL"
echo "installed: $PLIST"
echo "helpers: $INSTALL_WATCH $INSTALL_BRING_UP"
echo "logs: /var/log/carthing-usb-route-watch.log /var/log/carthing-usb-route-watch.err"
