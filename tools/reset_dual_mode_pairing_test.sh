#!/bin/sh
set -eu

# Reset the parts that make iOS first-pair tests sticky:
# - local Bumble keystore and source registry records
# - the device-side HCI proxy that owns HCI_CHANNEL_USER
#
# The iPhone must still do "Forget This Device" manually. iOS caches the first
# accessory image (SDP/EIR/CoD/keys) and the host cannot clear that cache.

REPO="$(cd "$(dirname "$0")/.." && pwd)"
DEVICE_HOST="${CARTHING_DEVICE_HOST:-172.16.42.77}"
DEVICE_SSH="${CARTHING_DEVICE_SSH:-root@$DEVICE_HOST}"
HCI_PROXY_PORT="${CARTHING_HCI_PROXY_PORT:-6402}"
HCI_PROXY_ADAPTER="${CARTHING_HCI_PROXY_ADAPTER:-0}"

echo "[reset] cleaning local Bumble keystore and iPhone/source registry"
python3 - "$REPO" <<'PY'
import json
import sys
from pathlib import Path

repo = Path(sys.argv[1])
(repo / "local-state").mkdir(exist_ok=True)
(repo / "local-state/keys.json").write_text(json.dumps({"CarThing": {}}, indent=2) + "\n")

state_path = repo / "local-state/state/carthing/state.json"
if state_path.exists():
    state = json.loads(state_path.read_text())
    state["devices"] = [
        d for d in state.get("devices", [])
        if d.get("role") != "source" and not str(d.get("id", "")).startswith("source:")
    ]
    state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n")
PY

echo "[reset] refreshing MFi auth modules/device node"
ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$DEVICE_SSH" \
    'CARTHING_MFI_MODULE_DIR=/run /run/S12-mfi-auth >/run/S12-mfi-auth.log 2>&1 || true'

if [ "${CARTHING_ALLOW_BUMBLE_RUN:-0}" = "1" ] && [ "${CARTHING_BUMBLE_QUARANTINE:-1}" = "0" ]; then
    echo "[reset] restarting HCI proxy on $DEVICE_SSH"
    ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null "$DEVICE_SSH" \
        "pkill -f '/tmp/hci_proxy.py' 2>/dev/null || true; sleep 0.5; nohup python3 /tmp/hci_proxy.py $HCI_PROXY_PORT $HCI_PROXY_ADAPTER >/run/hci_proxy.log 2>&1 &"
else
    echo "[reset] Bumble/HCI proxy quarantined; not restarting /tmp/hci_proxy.py"
fi

echo "[reset] done"
echo "[reset] next: on iPhone, Forget Car Thing; local Bumble tests require explicit lab override"
