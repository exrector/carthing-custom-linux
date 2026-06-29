#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export PYTHONDONTWRITEBYTECODE=1
PYCACHE_DIR="$(mktemp -d "${TMPDIR:-/tmp}/carthing-bake-readiness-pycache.XXXXXX")"
trap 'rm -rf "$PYCACHE_DIR"' EXIT
export PYTHONPYCACHEPREFIX="$PYCACHE_DIR"

python3 -m py_compile overlay/usr/lib/carthing/*.py

PYTHONPATH=overlay/usr/lib/carthing python3 - <<'PY'
from app_state import AppState
from gui_controller import GuiController
from runtime_model import RuntimeModel
from screens import AssistantScreen, NotificationsScreen, NowPlayingScreen, SettingsScreen

state = AppState()
model = RuntimeModel()
model.select_source("iphone")
model.session.connected = True
model.session.title = "Bake readiness"
state.iphone.connected = True
state.iphone.title = model.session.title

for screen in (
    NowPlayingScreen(),
    AssistantScreen(),
    NotificationsScreen(),
    SettingsScreen(),
):
    screen.on_state(state)
    screen.render()

expected = {
    "source",
    "connected",
    "peer",
    "rssi",
    "proximity_zone",
    "now_playing",
    "notifications",
    "operation_mode",
    "power_tier",
    "remote_mic",
}
if set(model.bt_block()) != expected:
    raise SystemExit("runtime model exposes non-minimal state")
if state.control_source_key != "iphone":
    raise SystemExit("encoder control target is not iPhone")

controller = GuiController.__new__(GuiController)
controller.app_state = AppState()
controller._volume_touch_ts = 0.0
controller._iphone_transport_connected = False
controller._iphone_grace_until = 0.0
controller._iphone_disconnect_at = 0.0
controller._iphone_disconnect_grace = 3.0
model.select_source("iphone")
model.session.connected = True
model.session.title = "Stable Play Now"
controller.apply(model)
model.session.connected = False
model.session.clear_track()
controller.apply(model)
if not controller.app_state.iphone.connected:
    raise SystemExit("brief iPhone disconnect cleared GUI immediately")
if controller.app_state.iphone.title != "Stable Play Now":
    raise SystemExit("brief iPhone disconnect cleared cached metadata")
controller._iphone_grace_until = 0.0
controller.apply(model)
if controller.app_state.iphone.connected or controller.app_state.iphone.title:
    raise SystemExit("expired iPhone GUI grace retained stale session")
print("MINIMAL RUNTIME SMOKE: OK")
PY

PYTHONPATH=overlay/usr/lib/carthing python3 - <<'PY'
import json
import tempfile
from pathlib import Path

from connection_journal import ConnectionJournal

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "connection-events.jsonl"
    journal = ConnectionJournal(path)
    if not journal.append("iphone_disconnected", peer="test", reason=40):
        raise SystemExit("connection journal append failed")
    if not journal.append("iphone_services_ready", peer="test"):
        raise SystemExit("connection journal second append failed")
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    if [row["event"] for row in rows] != [
        "iphone_disconnected",
        "iphone_services_ready",
    ]:
        raise SystemExit("connection journal is not append-only")
print("CONNECTION JOURNAL SMOKE: OK")
PY

python3 - <<'PY'
import importlib.util
from pathlib import Path

modules = []
for script in (
    Path("scripts/bake-unified-runtime-rootfs.py"),
    Path("tools/bake-rootfs.py"),
):
    spec = importlib.util.spec_from_file_location(script.stem.replace("-", "_"), script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    modules.append((script, module))

actual = modules[0][1].runtime_tree_sha1(Path("overlay/usr/lib/carthing"))
expected = modules[0][1].EXPECTED_RUNTIME_TREE_SHA1
if actual != expected:
    raise SystemExit(f"runtime tree sha mismatch: {actual} != {expected}")
for script, module in modules[1:]:
    if module.EXPECTED_RUNTIME_TREE_SHA1 != expected:
        raise SystemExit(f"{script} runtime tree sha constant differs")
print(f"RUNTIME TREE SHA OK: {actual}")
PY

echo "BAKE READINESS: OK"
