#!/bin/sh
set -eu

if [ "$#" -lt 1 ] || [ "$#" -gt 2 ]; then
    echo "usage: $0 <shell-command> [device]" >&2
    exit 1
fi

shell_command=$1
device=${2:-device1}
state_dir=${CARTHING_CONTROL_STATE_DIR:-/tmp/carthing-control-server}
pending_dir="$state_dir/pending/$device"

mkdir -p "$pending_dir"
command_id=$(date +%Y%m%d-%H%M%S)-$$
command_path="$pending_dir/$command_id.json"

python3 - "$command_path" "$command_id" "$device" "$shell_command" <<'EOF'
import json
import sys
from datetime import datetime, timezone

path, command_id, device, shell_command = sys.argv[1:]
payload = {
    "id": command_id,
    "device": device,
    "shell": shell_command,
    "created_at": datetime.now(timezone.utc).isoformat(),
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh, indent=2, sort_keys=True)
EOF

echo "$command_path"
