#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
APP_DIR=${CARTHING_BTLINK_APP_DIR:-"$HOME/Applications/CarThingBTLink.app"}
SOURCE_BIN=${1:-"$ROOT/.build/release/CarThingBTLink"}
SIGNING_TEAM=${CARTHING_CODESIGN_TEAM:-66CSVZPSDT}
IDENTITY=${CARTHING_CODESIGN_IDENTITY:-}
AGENT_TEMPLATE="$ROOT/launchd/com.carthing.btlink.plist"
AGENT_PATH="$HOME/Library/LaunchAgents/com.carthing.btlink.plist"
LOAD_AGENT=${CARTHING_BTLINK_LOAD_AGENT:-1}
DOMAIN="gui/$(id -u)"
OPUS_DYLIB=${CARTHING_OPUS_DYLIB:-/opt/homebrew/opt/opus/lib/libopus.0.dylib}

[ -x "$SOURCE_BIN" ] || {
    echo "missing release binary: $SOURCE_BIN" >&2
    exit 1
}
[ -f "$OPUS_DYLIB" ] || {
    echo "missing Opus runtime: $OPUS_DYLIB" >&2
    exit 1
}
OPUS_LOAD_PATH=$(
    otool -L "$SOURCE_BIN" | awk '/libopus.*dylib/ { print $1; exit }'
)
[ -n "$OPUS_LOAD_PATH" ] || {
    echo "release binary is not linked with Opus" >&2
    exit 1
}

if [ -z "$IDENTITY" ]; then
    IDENTITY=$(
        security find-identity -v -p codesigning \
            | awk -v team="$SIGNING_TEAM" 'index($0, team) { print $2; exit }'
    )
fi
[ -n "$IDENTITY" ] || {
    echo "missing Apple Development signing identity for team $SIGNING_TEAM" >&2
    exit 1
}

launchctl bootout "$DOMAIN" "$AGENT_PATH" >/dev/null 2>&1 || true
mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Frameworks"
install -m 755 "$SOURCE_BIN" "$APP_DIR/Contents/MacOS/CarThingBTLink"
install -m 755 "$OPUS_DYLIB" "$APP_DIR/Contents/Frameworks/libopus.0.dylib"
install -m 644 "$ROOT/CarThingBTLink-Info.plist" "$APP_DIR/Contents/Info.plist"
install_name_tool \
    -change "$OPUS_LOAD_PATH" \
    "@executable_path/../Frameworks/libopus.0.dylib" \
    "$APP_DIR/Contents/MacOS/CarThingBTLink"
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
