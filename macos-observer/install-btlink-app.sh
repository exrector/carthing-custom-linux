#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR=${CARTHING_BTLINK_APP_DIR:-"$HOME/Applications/CarThingBTLink.app"}
SOURCE_BIN=${1:-"$ROOT/.build/release/CarThingBTLink"}
IDENTITY=${CARTHING_CODESIGN_IDENTITY:--}
AGENT_TEMPLATE="$ROOT/launchd/com.carthing.btlink.plist"
AGENT_PATH="$HOME/Library/LaunchAgents/com.carthing.btlink.plist"
LOAD_AGENT=${CARTHING_BTLINK_LOAD_AGENT:-1}
DOMAIN="gui/$(id -u)"

[ -x "$SOURCE_BIN" ] || {
    echo "missing release binary: $SOURCE_BIN" >&2
    exit 1
}

launchctl bootout "$DOMAIN" "$AGENT_PATH" >/dev/null 2>&1 || true
mkdir -p "$APP_DIR/Contents/MacOS"
install -m 755 "$SOURCE_BIN" "$APP_DIR/Contents/MacOS/CarThingBTLink"
install -m 644 "$ROOT/CarThingBTLink-Info.plist" "$APP_DIR/Contents/Info.plist"
codesign --force --deep --sign "$IDENTITY" "$APP_DIR"
mkdir -p "$(dirname "$AGENT_PATH")"
install -m 644 "$AGENT_TEMPLATE" "$AGENT_PATH"
/usr/libexec/PlistBuddy \
    -c "Set :ProgramArguments:0 $APP_DIR/Contents/MacOS/CarThingBTLink" \
    "$AGENT_PATH"
if [ "$LOAD_AGENT" != "0" ]; then
    launchctl bootstrap "$DOMAIN" "$AGENT_PATH"
fi
echo "$APP_DIR"
