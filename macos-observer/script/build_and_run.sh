#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_DIR="${CARTHING_BTLINK_APP_DIR:-$HOME/Applications/CarThingBTLink.app}"

cd "$ROOT"
swift build -c release
./install-btlink-app.sh
sleep 2

count="$(pgrep -x CarThingBTLink | wc -l | tr -d ' ')"
if [[ "$count" != "1" ]]; then
  echo "expected one CarThingBTLink process, found $count" >&2
  pgrep -alf CarThingBTLink >&2 || true
  exit 1
fi

echo "$APP_DIR"
