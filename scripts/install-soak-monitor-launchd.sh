#!/bin/sh
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TEMPLATE="$ROOT/scripts/launchd/com.carthing.soak-monitor.plist"
MONITOR="$ROOT/scripts/carthing-soak-monitor.py"
LABEL="com.carthing.soak-monitor"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs/CarThing"
PYTHON="$(command -v python3)"
DOMAIN="gui/$(id -u)"

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"
temporary="$(mktemp "${TMPDIR:-/tmp}/carthing-soak-plist.XXXXXX")"
trap 'rm -f "$temporary"' EXIT

sed \
    -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__MONITOR__|$MONITOR|g" \
    -e "s|__LOG_DIR__|$LOG_DIR|g" \
    "$TEMPLATE" > "$temporary"
plutil -lint "$temporary"
cp "$temporary" "$TARGET"

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$TARGET"
launchctl kickstart -k "$DOMAIN/$LABEL"
launchctl print "$DOMAIN/$LABEL"
