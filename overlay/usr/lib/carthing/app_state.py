"""Presentation state for Play Now, Assistant, Notifications, and Settings."""

import json
import os
import time
from pathlib import Path

from runtime_paths import device_name
import state_paths


DEFAULT_STATE_PATH = str(state_paths.STATE_FILE)
DEFAULT_KEYSTORE_PATH = str(state_paths.KEYS_PATH)


def normalize_address(address):
    return str(address or "").strip().upper().split("/", 1)[0]


def _source_endpoints():
    return [
        {
            "id": "media-control",
            "direction": "control",
            "protocols": ["ble_ams", "ble_hid"],
            "capabilities": ["control_output", "metadata_input"],
            "label": "Media control",
        },
        {
            "id": "notifications",
            "direction": "metadata",
            "protocols": ["ble_ancs"],
            "capabilities": ["notifications_input"],
            "label": "Notifications",
        },
    ]


def _source_row(address, name="iPhone", metadata=None):
    address = normalize_address(address)
    raw_metadata = dict(metadata or {})
    metadata = {
        key: raw_metadata[key]
        for key in ("enrolled_from", "input_enrolled", "probe_stage")
        if key in raw_metadata
    }
    return {
        "key": f"source:{address}",
        "address": address,
        "label": str(name or "iPhone"),
        "type": "Источник",
        "role": "source",
        "online": False,
        "connected": False,
        "capabilities": [
            "metadata_input",
            "control_output",
            "notifications_input",
        ],
        "endpoints": _source_endpoints(),
        "constraints": ["idle_link_allowed"],
        "metadata": metadata,
    }


def _bonded_source_rows(keystore_path=None):
    path = Path(
        keystore_path
        or os.environ.get("CAR_THING_KEYSTORE", DEFAULT_KEYSTORE_PATH)
    )
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    namespace = data.get("CarThing", data) if isinstance(data, dict) else {}
    if not isinstance(namespace, dict):
        return []
    rows = []
    for raw_address, keys in namespace.items():
        if isinstance(keys, dict) and (keys.get("ltk") or keys.get("irk")):
            address = normalize_address(raw_address)
            if address:
                rows.append(_source_row(address, "Bluetooth Source"))
    return rows


class MediaSession:
    def __init__(self):
        self.key = "iphone"
        self.label = "iPhone"
        self.connected = False
        self.app_name = ""
        self.title = ""
        self.artist = ""
        self.duration = 0.0
        self.position = 0.0
        self.playing = False
        self.volume = 0.0
        self.supported_commands = set()
        self.liked = False


class AppState:
    IPHONE, SETTINGS, NOTIFICATIONS, ASSISTANT, PLUGINS = 0, 1, 2, 3, 4
    SERVER = PLUGINS

    def __init__(self):
        self.iphone = MediaSession()
        self.active_desktop = self.IPHONE
        self.last_media_source = "iphone"
        self.remote_media_active = False
        self.server_status = {}
        self.plugin_catalog = []
        self.plugin_snapshots = {}
        self.notifications = []
        self.unread_count = 0
        self.trusted = []
        self.session_peers = []
        self.sleep_on_idle = True
        self.screen_off_sec = 150
        self.screensaver_enabled = True
        self.screensaver_pacman_enabled = False
        self.screensaver_active = False
        self.notif_blink = True
        self.screen_brightness = 100
        self.remote_mic_enabled = False
        self.remote_mic_state = "off"
        self.remote_mic_message = "Микрофон выключен"
        self.assistant_transcript = []
        self.assistant_status = ""
        self.assistant_text = ""
        self.assistant_live_text = ""
        self.assistant_live_target = ""
        self._assistant_typewriter_at = time.monotonic()
        self._assistant_typewriter_credit = 0.0
        self.clock_text = "--:--"
        self.clock_date_text = ""
        self.device_name = device_name()
        self.pairing_mode = False
        self.pairing_role = "input"
        self.pairing_message = ""
        self.power_unplug_status = "idle"
        self.power_unplug_message = ""
        self.trusted_path = Path(
            os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_STATE_PATH)
        )
        self.load_trusted()

    @property
    def control_source(self):
        return self.iphone

    @property
    def control_source_key(self):
        return "iphone"

    def source_for(self, _key):
        return self.iphone

    def desktop_source(self, _index):
        return "iphone"

    def set_remote_mic(self, enabled, state=None, message=None):
        self.remote_mic_enabled = bool(enabled)
        self.remote_mic_state = str(
            state or ("listening" if enabled else "off")
        )
        if message is not None:
            self.remote_mic_message = str(message)
        elif enabled:
            self.remote_mic_message = "Подключение к Mac"
        else:
            self.remote_mic_message = "Микрофон выключен"
        return self.remote_mic_enabled

    def set_assistant_live_target(self, text):
        target = str(text or "")
        current = self.assistant_live_text
        was_idle = not self.assistant_live_target and not current
        if not target.startswith(current):
            common = 0
            limit = min(len(current), len(target))
            while common < limit and current[common] == target[common]:
                common += 1
            self.assistant_live_text = current[:common]
            self._assistant_typewriter_credit = 0.0
            self._assistant_typewriter_at = time.monotonic()
        self.assistant_live_target = target
        if was_idle:
            self._assistant_typewriter_at = time.monotonic()

    def clear_assistant_live(self):
        self.assistant_live_text = ""
        self.assistant_live_target = ""
        self._assistant_typewriter_credit = 0.0
        self._assistant_typewriter_at = time.monotonic()

    def advance_assistant_live(self, now=None):
        now = time.monotonic() if now is None else float(now)
        elapsed = max(0.0, min(0.25, now - self._assistant_typewriter_at))
        self._assistant_typewriter_at = now
        backlog = len(self.assistant_live_target) - len(self.assistant_live_text)
        if backlog <= 0:
            return False
        chars_per_second = 28.0
        self._assistant_typewriter_credit += elapsed * chars_per_second
        count = min(backlog, int(self._assistant_typewriter_credit))
        if count <= 0:
            return False
        self._assistant_typewriter_credit -= count
        end = len(self.assistant_live_text) + count
        self.assistant_live_text = self.assistant_live_target[:end]
        return True

    def load_trusted(self, path=None):
        path = Path(path or self.trusted_path)
        self.trusted_path = path
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}

        rows = []
        for device in data.get("devices", []) if isinstance(data, dict) else []:
            if not isinstance(device, dict):
                continue
            capabilities = set(device.get("capabilities") or [])
            if device.get("role") != "source" and "metadata_input" not in capabilities:
                continue
            address = normalize_address(device.get("address"))
            if not address:
                continue
            row = _source_row(
                address,
                device.get("name") or device.get("label") or "iPhone",
                device.get("metadata"),
            )
            row["online"] = bool(device.get("online", False))
            row["connected"] = bool(device.get("connected", False))
            rows.append(row)

        known = {row["address"] for row in rows}
        for bonded in _bonded_source_rows():
            if bonded["address"] not in known:
                rows.append(bonded)

        if rows:
            preferred = max(
                rows,
                key=lambda row: (
                    bool(row.get("connected")),
                    row.get("label") not in ("", "Bluetooth Source"),
                ),
            )
            self.trusted = [preferred]
        else:
            self.trusted = []

    def save_trusted(self, path=None):
        devices = []
        for source in self.trusted_sources:
            address = normalize_address(source.get("address"))
            if not address:
                continue
            devices.append(
                {
                    "id": f"source:{address}",
                    "address": address,
                    "name": source.get("label") or "iPhone",
                    "type": "Источник",
                    "role": "source",
                    "trusted": True,
                    "capabilities": list(source.get("capabilities") or []),
                    "endpoints": list(source.get("endpoints") or []),
                    "constraints": list(source.get("constraints") or []),
                    "metadata": dict(source.get("metadata") or {}),
                }
            )
        state_paths.write_state({"schema": 2, "devices": devices})

    @property
    def trusted_sources(self):
        return [
            device for device in self.trusted
            if device.get("role") == "source"
        ]

    def enroll_trusted_device(
        self,
        address,
        name=None,
        service_uuids=None,
        ble_services=None,
        metadata=None,
        **_unused,
    ):
        address = normalize_address(address)
        evidence = dict(metadata or {})
        evidence["service_uuids"] = sorted(set(service_uuids or []))
        evidence["ble_services"] = sorted(set(ble_services or []))
        row = _source_row(address, name or "iPhone", evidence)
        current = self.trusted_sources[0] if self.trusted_sources else None
        if current is None:
            self.trusted = [row]
            return row
        current.update(row)
        self.trusted = [current]
        return current

    def remove_trusted(self, key_or_address):
        address = normalize_address(key_or_address)
        self.trusted = [
            device
            for device in self.trusted
            if device.get("key") != key_or_address
            and normalize_address(device.get("address")) != address
        ]

    def note_peer_presence(self, address, event="", **details):
        address = normalize_address(address)
        if not address:
            return
        self.session_peers = [
            peer for peer in self.session_peers
            if peer.get("address") != address
        ]
        if event != "disconnect":
            self.session_peers.append(
                {"address": address, "event": event, **details}
            )
