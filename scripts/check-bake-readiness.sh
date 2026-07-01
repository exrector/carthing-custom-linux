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
import base64
import hashlib
import hmac
import json
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

from app_state import AppState
from gui_controller import ASSISTANT, HOME, NOTIFICATIONS, PLUGINS, GuiController
from runtime_model import RuntimeModel
from screens import (
    AssistantScreen,
    NotificationsScreen,
    NowPlayingScreen,
    PluginDashboardScreen,
    SettingsScreen,
)
from ui_components import truncate
from ui_components import RegionSet
from ui_screen import Input, notification_indicator_visible

sys.path.append("overlay/usr/lib/carthing/vendor")
from hid_remote_service import install_hid_remote_profile, send_consumer_usage
from ams_client import AMSClient, MediaState
from session_plane_service import SessionPlaneService
from power_policy import IdlePowerController
import maintenance_service

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
    PluginDashboardScreen(),
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
    "server_status",
    "plugins",
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
    "volume": 0.42,
}):
    raise SystemExit("active AirPlay metadata was rejected")
if model.session.title != "AirPlay title" or not model.remote_media_active:
    raise SystemExit("AirPlay metadata did not overlay the AMS session")
if model.session.volume != 0.42:
    raise SystemExit("AirPlay volume did not replace stale AMS volume")
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
if not model.apply_remote_media({
    "active": True,
    "identifier": "paused-airplay-track",
    "title": "Paused AirPlay title",
    "elapsed": 12,
    "playing": False,
}):
    raise SystemExit("identified paused AirPlay session was rejected after a gap")
if not model.remote_media_active:
    raise SystemExit("paused AirPlay session did not restore remote ownership")
model.clear_remote_media()
model.update_server_status({
    "host": "Test Mac",
    "connected": True,
    "assistant": True,
    "cpu_load_pct": 12.5,
    "memory_gb": 32,
    "thermal": "nominal",
    "uptime_s": 3600,
    "ctsp_rtt_ms": 8.5,
})
if model.server_status["host"] != "Test Mac":
    raise SystemExit("Bluetooth server status was not retained")
model.set_server_disconnected()
if model.server_status["connected"] or model.server_status["assistant"]:
    raise SystemExit("server status remained online after CTSP disconnect")
model.update_server_status({
    "host": "Test Mac",
    "connected": True,
    "assistant": True,
})
model.update_plugin_catalog({
    "schema": 1,
    "plugins": [{
        "manifest": {
            "schema": 1,
            "id": "dev.carthing.test",
            "name": "Test Plugin",
            "version": "1.0.0",
            "executable": "test",
            "summary": "",
            "permissions": [],
            "default_enabled": False,
        },
        "enabled": True,
        "status": "running",
        "message": "",
        "card_count": 1,
    }],
})
model.update_plugin_snapshot({
    "schema": 1,
    "plugin_id": "dev.carthing.test",
    "revision": 1,
    "cards": [{
        "id": "main",
        "title": "Test Plugin",
        "rows": [{"id": "value", "label": "VALUE", "value": "42"}],
        "actions": [{
            "id": "run",
            "label": "RUN",
            "style": "primary",
            "enabled": True,
        }],
    }],
})
state.plugin_catalog = list(model.plugin_catalog)
state.plugin_snapshots = dict(model.plugin_snapshots)
plugin_screen = PluginDashboardScreen()
plugin_screen.on_state(state)
plugin_regions = RegionSet()
plugin_screen.render(plugin_regions)
plugin_action = plugin_regions.hit(80, 80)
if (
    plugin_action is None
    or plugin_action.intent != "plugin_action"
    or plugin_action.payload.get("action_id") != "run"
):
    raise SystemExit("plugin dashboard did not expose its touch action")

class FakePluginChannel:
    def __init__(self):
        self.frames = []

    def write(self, frame):
        self.frames.append(frame)

fake_channel = FakePluginChannel()
service = SessionPlaneService.__new__(SessionPlaneService)
service._plugin_owner = "AA:BB:CC:DD:EE:FF"
service._runtimes = {
    "AA:BB:CC:DD:EE:FF": SimpleNamespace(
        connector=SimpleNamespace(channel=fake_channel)
    )
}
if not service.send_plugin_action({
    "plugin_id": "dev.carthing.test",
    "card_id": "main",
    "action_id": "run",
}):
    raise SystemExit("plugin action did not enter CTSP")
if b"plugin_action:" not in fake_channel.frames[-1][16:]:
    raise SystemExit("plugin action CTSP payload has the wrong command")

with tempfile.TemporaryDirectory() as maintenance_tmp:
    maintenance_root = Path(maintenance_tmp)
    key_path = maintenance_root / "maintenance.key"
    key = bytes(range(32))
    key_path.write_text(key.hex())
    maintenance_service.KEY_PATH = key_path
    maintenance_service.ALLOWED_ROOTS = (maintenance_root,)
    maintenance_service.WORK_ROOT = maintenance_root / "work"
    maintenance = maintenance_service.MaintenanceService()

    def maintenance_envelope(request_id, operation, payload):
        payload64 = base64.b64encode(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).decode()
        session_id = maintenance.session_id
        signed = (
            f"1\n{session_id}\n{request_id}\n{operation}\n{payload64}"
        ).encode()
        return json.dumps({
            "version": 1,
            "session": session_id,
            "id": request_id,
            "op": operation,
            "payload": payload64,
            "auth": hmac.new(key, signed, hashlib.sha256).hexdigest(),
        }).encode()

    response, restart = maintenance.handle(
        maintenance_envelope("status-001", "status", {})
    )
    if restart or b'"op":"result"' not in response:
        raise SystemExit("maintenance status protocol failed")
    payload = b"abc"
    digest = hashlib.sha256(payload).hexdigest()
    maintenance.handle(maintenance_envelope(
        "upload-001",
        "put_begin",
        {
            "path": str(maintenance_root / "screens.py"),
            "size": len(payload),
            "sha256": digest,
            "mode": 0o644,
        },
    ))
    maintenance.handle(maintenance_envelope(
        "upload-001",
        "put_chunk",
        {"seq": 0, "data": base64.b64encode(payload).decode()},
    ))
    upload = maintenance._uploads["upload-001"]
    if upload["received"] != 3 or upload["hasher"].hexdigest() != digest:
        raise SystemExit("maintenance upload chunk failed")
    maintenance.handle(
        maintenance_envelope("upload-001", "put_abort", {})
    )
model.add_notification(
    42,
    "Телефон",
    "Тестовый звонок",
    category="IncomingCall",
    positive_action=True,
    negative_action=True,
)

ams_state = MediaState()
ams = AMSClient(ams_state)
ams._handle_entity_update(bytes([0, 0, 0]) + "Музыка".encode())
ams._handle_entity_update(bytes([2, 1, 0]) + "Альбом".encode())
ams_state.duration = 123.0
ams._handle_entity_update(bytes([2, 3, 0]))
if ams_state.app_name != "Музыка" or ams_state.album != "Альбом":
    raise SystemExit("AMS app/album metadata was not retained")
if ams_state.duration != 0.0:
    raise SystemExit("empty AMS duration retained stale track length")

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
stable_model.select_source("iphone")
stable_model.session.connected = True
if not navigation.apply(stable_model):
    raise SystemExit("first GUI model apply was not marked dirty")
if navigation.apply(stable_model):
    raise SystemExit("unchanged GUI model still requested a full render")
stable_model.session.set_playback(10, 1, True)
if navigation.apply(stable_model):
    raise SystemExit("empty Play Now repainted for invisible playback position")
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
navigation.handle_input(Input.PRESS)
if navigation.compositor.active != ASSISTANT:
    raise SystemExit("encoder press did not open Assistant")
if capture_toggles[-1:] != [True]:
    raise SystemExit("first encoder press did not enable microphone")
navigation.handle_input(Input.PRESS)
if capture_toggles[-1:] != [False]:
    raise SystemExit("second encoder press did not disable microphone")
for button, expected_screen in (
    (Input.BTN_1, HOME),
    (Input.BTN_2, ASSISTANT),
    (Input.BTN_3, NOTIFICATIONS),
    (Input.BTN_4, PLUGINS),
):
    navigation.handle_input(button)
    if navigation.compositor.active != expected_screen:
        raise SystemExit(f"{button} did not open fixed view {expected_screen}")
navigation.show_home()
navigation.handle_input(Input.SWIPE_LEFT)
if navigation.compositor.active != ASSISTANT:
    raise SystemExit("left swipe did not move to the next view")
if not navigation.needs_fast_render():
    raise SystemExit("swipe transition did not request animation frames")
navigation.handle_input(Input.SWIPE_RIGHT)
if navigation.compositor.active != 0:
    raise SystemExit("right swipe did not return to the previous view")

class CountingDraw:
    def __init__(self):
        self.calls = 0

    def textbbox(self, _origin, text, font=None):
        self.calls += 1
        return (0, 0, len(text), 1)

counting_draw = CountingDraw()
if not truncate(counting_draw, "x" * 10000, None, 100).endswith("…"):
    raise SystemExit("long UI text was not truncated")
if counting_draw.calls > 20:
    raise SystemExit("UI truncation regressed to linear text measurement")

capture_events = []
session_gate = SessionPlaneService.__new__(SessionPlaneService)
session_gate._listening = False
session_gate._remote_media_owner = "AA:BB:CC:DD:EE:FF"
session_gate._runtimes = {
    "AA:BB:CC:DD:EE:FF": SimpleNamespace(
        connector=SimpleNamespace(channel=object(), connected=True),
    )
}
session_commands = []
def record_session_command(_channel, frame_type, payload):
    session_commands.append((frame_type, payload))
    return True
session_gate._write = record_session_command
session_gate._start_mic = lambda _runtime, _channel: capture_events.append("start")
session_gate._stop_mic = lambda _runtime: capture_events.append("stop")
session_gate._sync_model = lambda: None
session_gate._notify_status = lambda: None
session_gate.model = RuntimeModel()
session_gate.on_change = lambda: None
session_gate.on_remote_media_clear = lambda: None
session_gate.set_listening(True)
session_gate.set_listening(False)
if capture_events != ["start", "stop"]:
    raise SystemExit("microphone task is not strictly gated by listening state")
if not session_gate.send_media_control("vol_up"):
    raise SystemExit("connected CTSP route rejected media control")
if session_commands != [(0x05, b"media_control:vol_up")]:
    raise SystemExit("CTSP media control payload is incorrect")
session_gate._apply_server_status(
    b'{"host":"Mac","connected":true,"cpu_load_pct":20}'
)
if session_gate.model.server_status.get("host") != "Mac":
    raise SystemExit("CTSP server status payload was rejected")

timeout_updates = []
screensaver_toggles = []
settings_controller = GuiController(
    FakeDisplay(),
    on_set_screensaver_timeout=lambda value: timeout_updates.append(value),
    on_toggle_screensaver=lambda value: screensaver_toggles.append(value),
)
settings_controller.app_state.screensaver_enabled = True
settings_controller.app_state.screen_off_sec = 60
settings_controller.dispatcher.dispatch(
    "display_adjust",
    ("screensaver", "-"),
)
if timeout_updates[-1:] != [30] or screensaver_toggles[-1:] != [True]:
    raise SystemExit("screensaver minus control did not select 30 seconds")
settings_controller.dispatcher.dispatch(
    "display_adjust",
    ("screensaver", "+"),
)
if timeout_updates[-1:] != [60] or screensaver_toggles[-1:] != [True]:
    raise SystemExit("screensaver plus control did not select next timeout")
settings_controller.app_state.screen_off_sec = 600
settings_controller.dispatcher.dispatch(
    "display_adjust",
    ("screensaver", "+"),
)
if timeout_updates[-1:] != [600]:
    raise SystemExit("screensaver exceeded the 10 minute maximum")

typewriter = AppState()
typewriter.set_assistant_live_target("Посимвольно")
typewriter.advance_assistant_live(typewriter._assistant_typewriter_at + 0.05)
if len(typewriter.assistant_live_text) != 1:
    raise SystemExit("assistant typewriter is not advancing character by character")

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

with tempfile.TemporaryDirectory() as directory:
    panel = Path(directory) / "aml-bl"
    panel.mkdir()
    for name, value in (
        ("brightness", "1"),
        ("bl_power", "0"),
        ("max_brightness", "255"),
    ):
        (panel / name).write_text(value)
    power = IdlePowerController(
        {
            "sleep_on_idle": False,
            "screensaver_enabled": True,
            "screen_off_after_sec": 30,
        },
        directory,
    )
    power._last_activity = time.monotonic() - 31
    if power.tick() != "screensaver" or not power.screensaver_active:
        raise SystemExit("idle power policy did not enter screensaver")
    power.note_activity("smoke")
    if power.tick() != "active" or power.screensaver_active:
        raise SystemExit("screensaver did not wake on activity")
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
