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
print("MINIMAL RUNTIME SMOKE: OK")
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
