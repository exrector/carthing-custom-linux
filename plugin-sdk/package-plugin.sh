#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 || $# -gt 2 ]]; then
  echo "usage: $0 PLUGIN_DIRECTORY [OUTPUT.ctplugin]" >&2
  exit 2
fi

SOURCE="$(cd "$1" && pwd)"
OUTPUT="${2:-$(basename "$SOURCE").ctplugin}"
[[ "$OUTPUT" = /* ]] || OUTPUT="$PWD/$OUTPUT"

test -f "$SOURCE/manifest.json"
rm -f "$OUTPUT"
/usr/bin/ditto -c -k --norsrc "$SOURCE/." "$OUTPUT"
echo "$OUTPUT"
