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
import asyncio
import sys
from types import SimpleNamespace

from app_state import AppState
from gui_controller import ASSISTANT, GuiController
from runtime_model import RuntimeModel
from screens import AssistantScreen, NotificationsScreen, NowPlayingScreen, SettingsScreen
from ui_screen import notification_indicator_visible

sys.path.append("overlay/usr/lib/carthing/vendor")
from hid_remote_service import install_hid_remote_profile, send_consumer_usage
from session_plane_service import SessionPlaneService

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
if not model.apply_remote_media({
    "active": True,
    "identifier": "airplay-track",
    "title": "AirPlay title",
    "artist": "AirPlay artist",
    "duration": 120,
    "elapsed": 10,
    "playing": True,
}):
    raise SystemExit("active AirPlay metadata was rejected")
if model.session.title != "AirPlay title" or not model.remote_media_active:
    raise SystemExit("AirPlay metadata did not overlay the AMS session")
if not model.apply_remote_media({
    "active": True,
    "identifier": "airplay-track",
    "title": "AirPlay title",
    "elapsed": 11,
    "playing": False,
}):
    raise SystemExit("paused selected AirPlay session was not retained")
model.clear_remote_media()
if model.remote_media_active:
    raise SystemExit("AirPlay metadata overlay did not clear")

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
if not notification_indicator_visible(1, True, now=0.5):
    raise SystemExit("notification indicator did not enter its short on-window")
if notification_indicator_visible(1, True, now=1.5):
    raise SystemExit("notification indicator on-window is too long")
if not notification_indicator_visible(1, True, now=8.5):
    raise SystemExit("notification indicator period is not stable")
if notification_indicator_visible(0, True, now=0.5):
    raise SystemExit("notification indicator ignored unread count")

class FakeDisplay:
    def set_on_event(self, _callback):
        pass

    def blit(self, _frame):
        pass

capture_toggles = []
navigation = GuiController(
    FakeDisplay(),
    on_toggle_client=lambda enabled: capture_toggles.append(enabled),
)
navigation.show_screen(ASSISTANT)
if capture_toggles:
    raise SystemExit("opening Assistant view changed microphone capture")
if navigation.app_state.remote_mic_enabled:
    raise SystemExit("opening Assistant view enabled microphone state")
stable_model = RuntimeModel()
if not navigation.apply(stable_model):
    raise SystemExit("first GUI model apply was not marked dirty")
if navigation.apply(stable_model):
    raise SystemExit("unchanged GUI model still requested a full render")
navigation.show_home()
navigation.apply(stable_model)
navigation.app_state.set_assistant_live_target("hidden assistant update")
if navigation.apply(stable_model):
    raise SystemExit("hidden Assistant state invalidated the visible view")
navigation.show_screen(ASSISTANT)
navigation.dispatcher.dispatch("remote_mic_set", True)
navigation.show_home()
if capture_toggles[-2:] != [True, False]:
    raise SystemExit("leaving Assistant did not stop microphone capture")
if navigation.app_state.remote_mic_enabled:
    raise SystemExit("microphone remained enabled outside Assistant")

capture_events = []
session_gate = SessionPlaneService.__new__(SessionPlaneService)
session_gate._listening = False
session_gate._runtimes = {
    "mac": SimpleNamespace(
        connector=SimpleNamespace(channel=object()),
    )
}
session_gate._start_mic = lambda _runtime, _channel: capture_events.append("start")
session_gate._stop_mic = lambda _runtime: capture_events.append("stop")
session_gate._sync_model = lambda: None
session_gate._notify_status = lambda: None
session_gate.set_listening(True)
session_gate.set_listening(False)
if capture_events != ["start", "stop"]:
    raise SystemExit("microphone task is not strictly gated by listening state")

class FakeHIDDevice:
    def __init__(self):
        self.notifications = []

    def add_service(self, _service):
        pass

    async def notify_subscribers(self, _attribute, value):
        self.notifications.append(bytes(value))

hid_device = FakeHIDDevice()
install_hid_remote_profile(hid_device)
asyncio.run(send_consumer_usage("vol_up"))
if hid_device.notifications != [b"\x08", b"\x00"]:
    raise SystemExit("HID volume usage did not send press and release")
hid_device.notifications.clear()
asyncio.run(send_consumer_usage("play_pause"))
if hid_device.notifications != [b"\x01", b"\x00"]:
    raise SystemExit("HID play/pause usage did not send press and release")
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
