"""AppState — the single source of truth (unidirectional data flow).

BLE events and input mutate AppState; screens read it and re-render. Screens
never talk to BLE directly — they emit intents (see intents.py) which the
dispatcher applies here and forwards to the device.

Holds one MediaSession per source (iPhone, Mac) plus UI state. The transport's
"control source" is derived: the active media desktop's source, or the last
active source on non-media desktops.
"""

import json
import os
from pathlib import Path
from runtime_paths import device_name


DEFAULT_TRUSTED_DEVICES_PATH = "/run/carthing-state/carthing/trusted-devices.json"
DEFAULT_KEYSTORE_PATH = "/run/carthing-state/carthing/keys.json"


def normalize_address(address) -> str:
    text = str(address or "").strip().upper()
    return text.split("/", 1)[0]


def _bonded_source_rows(keystore_path=None):
    """BLE bonds from Bumble keystore are trusted sources even before reconnect."""
    keystore_path = Path(keystore_path or os.environ.get("CAR_THING_KEYSTORE", DEFAULT_KEYSTORE_PATH))
    try:
        data = json.loads(keystore_path.read_text())
    except Exception:
        return []
    namespace = data.get("CarThing", data) if isinstance(data, dict) else {}
    if not isinstance(namespace, dict):
        return []
    rows = []
    for raw_address, keys in namespace.items():
        if not isinstance(keys, dict):
            continue
        if not (keys.get("ltk") or keys.get("irk")):
            continue
        address = normalize_address(raw_address)
        if address:
            rows.append({
                "key": "iphone" if not rows else f"source:{address}",
                "address": address,
                "label": "iPhone" if not rows else "Bluetooth Source",
                "type": "iPhone" if not rows else "Источник",
                "role": "source",
                "online": False,
                "connected": False,
                "default": False,
            })
    return rows


def _has_capability(device, capability):
    return capability in set(device.get("capabilities") or [])


def _endpoint_dirs(device):
    return {
        endpoint.get("direction")
        for endpoint in (device.get("endpoints") or [])
        if isinstance(endpoint, dict)
    }


def _device_is_input(device):
    return (
        device.get("role") == "source"
        or _has_capability(device, "audio_input")
        or "input" in _endpoint_dirs(device)
    )


def _device_is_output(device):
    return (
        device.get("role") == "speaker"
        or _has_capability(device, "audio_output")
        or "output" in _endpoint_dirs(device)
    )


class MediaSession:
    """Per-source playback state (one for iPhone, one for Mac)."""

    def __init__(self, key, label):
        self.key = key          # "iphone" / "mac"
        self.label = label      # "iPhone" / "Mac"
        self.connected = False
        self.title = ""
        self.artist = ""
        self.duration = 0.0
        self.position = 0.0
        self.playing = False
        self.volume = 0.0
        # AMS RemoteCommand-список текущего приложения (какие кнопки рисовать).
        self.supported_commands = set()
        # «В избранном» — ЛОКАЛЬНЫЙ optimistic-флаг (AMS не сообщает реальное состояние).
        # Сбрасывается при смене трека; тап по сердцу переключает (add/remove).
        self.liked = False


class AppState:
    # screen indices (navigation is explicit; no desktop swipe ring)
    IPHONE, SETTINGS, NOTIFICATIONS, SESSIONS, ROUTER, MAC = 0, 1, 2, 3, 4, 5
    MODES = SESSIONS      # compatibility alias
    TRANSFER = ROUTER     # compatibility alias
    # index -> media source. Один home (0)=iPhone; прочие view (Settings/Notifications)
    # не медиа -> control_source падает на last_media_source (=iphone), бар рулит реальным источником.
    DESKTOP_SOURCE = {IPHONE: "iphone", TRANSFER: "iphone", MAC: "mac"}

    def __init__(self):
        self.iphone = MediaSession("iphone", "iPhone")
        self.mac = MediaSession("mac", "Mac")
        self.active_desktop = 0
        self.last_media_source = "iphone"   # fallback for non-media desktops
        self.unread_count = 0
        self.notifications = []             # list of {"app","title","message"}
        self.trusted = []                   # {"key","label","type","role","online","connected","default"}
        self.transfer_active = False
        self.transfer_scanning = False
        self.transfer_source = ""
        self.route_input = ""
        self.route_output = ""
        self.active_session = "remote"
        self.device_mode = "remote"
        self.mode_status = "remote"
        self.power_tier = "boot"
        self.sleep_on_idle = True       # [CLAUDE] сон/гашение экрана (тумблер в Settings)
        self.screen_off_sec = 150       # [CLAUDE] тайм-аут полного гашения (настройка ± в Settings)
        self.clock_text = "--:--"
        self.device_name = device_name()
        self.pairing_mode = False
        self.pairing_role = "source"   # source|speaker
        self.speaker_candidates = []   # classic inquiry candidates while adding a speaker
        self.speaker_pairing_status = ""
        self.pairing_message = ""
        self.assistant_state = "idle"   # idle|listening|thinking|responding (Фаза 5)
        self.trusted_path = Path(os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_TRUSTED_DEVICES_PATH))
        self.load_trusted()

    @property
    def sources(self):
        return {"iphone": self.iphone, "mac": self.mac}

    def desktop_source(self, idx):
        return self.DESKTOP_SOURCE.get(idx)

    @property
    def control_source_key(self):
        """Which source the bottom-bar transport controls right now."""
        return self.desktop_source(self.active_desktop) or self.last_media_source

    @property
    def control_source(self):
        return self.sources[self.control_source_key]

    def load_trusted(self, path=None):
        path = Path(path or os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_TRUSTED_DEVICES_PATH))
        self.trusted_path = path
        try:
            data = json.loads(path.read_text())
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}
        if isinstance(data, list):
            data = {"sources": [], "speakers": data}
        elif not isinstance(data, dict):
            data = {}

        devices = []
        if data.get("schema") == 2 and isinstance(data.get("devices"), list):
            for peer in data.get("devices", []):
                if not isinstance(peer, dict):
                    continue
                address = normalize_address(peer.get("address"))
                key = peer.get("id") or peer.get("key") or address
                label = peer.get("name") or peer.get("label") or address or key
                capabilities = list(peer.get("capabilities") or [])
                endpoints = list(peer.get("endpoints") or [])
                devices.append({
                    "key": key,
                    "address": address,
                    "label": label,
                    "type": peer.get("type") or "Устройство",
                    "role": peer.get("role") or "device",
                    "online": bool(peer.get("online", False)),
                    "connected": bool(peer.get("connected", False)),
                    "default": bool(peer.get("default", False)),
                    "capabilities": capabilities,
                    "endpoints": endpoints,
                    "constraints": list(peer.get("constraints") or []),
                    "metadata": dict(peer.get("metadata") or {}),
                })
        else:
            for role, section in (("source", "sources"), ("speaker", "speakers")):
                peers = data.get(section, [])
                if isinstance(peers, dict):
                    peers = [{"address": address, **details} for address, details in peers.items()]
                for index, peer in enumerate(peers):
                    if not isinstance(peer, dict):
                        peer = {"address": peer}
                    address = normalize_address(peer.get("address"))
                    if not address:
                        continue
                    capabilities = ["audio_input", "metadata_input", "control_output"] if role == "source" else [
                        "audio_output", "control_input", "volume_control", "transport_control"
                    ]
                    endpoint_direction = "input" if role == "source" else "output"
                    devices.append({
                        "key": peer.get("key") or address,
                        "address": address,
                        "label": peer.get("name") or peer.get("label") or address,
                        "type": peer.get("type") or ("Источник" if role == "source" else "Динамик"),
                        "role": role,
                        "online": bool(peer.get("online", False)),
                        "connected": bool(peer.get("connected", False)),
                        "default": bool(peer.get("default", index == 0 and role == "speaker")),
                        "capabilities": capabilities,
                        "endpoints": [{"id": role, "direction": endpoint_direction, "capabilities": capabilities}],
                        "constraints": ["idle_link_allowed", "active_media_requires_route"],
                        "metadata": {"legacy_role": role},
                    })
        by_key = {device.get("key"): device for device in devices if device.get("key")}
        by_address = {device.get("address"): device for device in devices if device.get("address")}
        for bonded in _bonded_source_rows():
            existing = by_key.get(bonded["key"]) or by_address.get(bonded["address"])
            if existing is None:
                devices.append(bonded)
                by_key[bonded["key"]] = bonded
                by_address[bonded["address"]] = bonded
            else:
                existing.setdefault("role", "source")
                existing.setdefault("type", bonded["type"])
                existing.setdefault("label", bonded["label"])
                if not existing.get("address"):
                    existing["address"] = bonded["address"]
        self.trusted = devices

    def save_trusted(self, path=None):
        path = Path(path or self.trusted_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": 2, "devices": []}
        seen = set()
        for device in self.trusted:
            address = normalize_address(device.get("address"))
            key = device.get("key") or address
            if not key:
                continue
            dedupe = address or key
            if dedupe in seen:
                continue
            seen.add(dedupe)
            row = {
                "id": key,
                "address": address,
                "name": device.get("label") or key,
                "type": device.get("type") or "Устройство",
                "role": device.get("role") or "device",
                "trusted": True,
                "capabilities": list(device.get("capabilities") or []),
                "endpoints": list(device.get("endpoints") or []),
                "constraints": list(device.get("constraints") or []),
                "metadata": dict(device.get("metadata") or {}),
            }
            if device.get("default"):
                row["default"] = True
            data["devices"].append(row)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(path)

    def trusted_by_role(self, role):
        return [device for device in self.trusted if device.get("role") == role]

    @property
    def trusted_sources(self):
        return [device for device in self.trusted if _device_is_input(device)]

    @property
    def trusted_speakers(self):
        return [device for device in self.trusted if _device_is_output(device)]

    @property
    def route_inputs(self):
        return self.trusted_sources

    @property
    def route_outputs(self):
        return self.trusted_speakers

    def select_route_input(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for device in self.route_inputs:
            match = device.get("key") == key_or_address or device.get("address") == needle
            device["route_input"] = match
            if match:
                selected = device.get("key") or device.get("address")
        if selected:
            self.route_input = selected
        return selected

    def select_route_output(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for device in self.route_outputs:
            match = device.get("key") == key_or_address or device.get("address") == needle
            device["route_output"] = match
            if match:
                selected = device.get("key") or device.get("address")
        if selected:
            self.route_output = selected
        return selected

    def is_trusted_source(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_sources)

    def is_trusted_speaker(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_speakers)

    def upsert_speaker_candidate(self, address, name=None, class_of_device=None, rssi=None, audio=None):
        address = normalize_address(address)
        if not address:
            return None
        label = str(name or "").strip() or address
        for candidate in self.speaker_candidates:
            if candidate.get("address") == address:
                if name:
                    candidate["label"] = label
                if class_of_device is not None:
                    candidate["class_of_device"] = class_of_device
                if rssi is not None:
                    candidate["rssi"] = rssi
                if audio is not None:
                    candidate["audio"] = bool(audio)
                candidate["trusted"] = self.is_trusted_speaker(address)
                return candidate
        candidate = {
            "key": address,
            "address": address,
            "label": label,
            "type": "Динамик",
            "role": "speaker",
            "class_of_device": class_of_device,
            "rssi": rssi,
            "audio": bool(audio),
            "trusted": self.is_trusted_speaker(address),
        }
        self.speaker_candidates.append(candidate)
        return candidate

    def clear_speaker_candidates(self):
        self.speaker_candidates = []

    def trust_speaker(self, address, name=None):
        address = normalize_address(address)
        if not address:
            return None
        if self.is_trusted_source(address):
            return None
        candidate = next((c for c in self.speaker_candidates if c.get("address") == address), None)
        if candidate is not None and not candidate.get("audio"):
            return None
        label = str(name or "").strip() or address
        existing = next((d for d in self.trusted_speakers if d.get("address") == address), None)
        if existing is None:
            existing = {
                "key": address,
                "address": address,
                "label": label,
                "type": "Динамик",
                "role": "speaker",
                "online": True,
                "connected": False,
                "default": not bool(self.trusted_speakers),
            }
            self.trusted.append(existing)
        else:
            existing["label"] = label
            existing["online"] = True
        for candidate in self.speaker_candidates:
            if candidate.get("address") == address:
                candidate["trusted"] = True
        return existing

    def remove_trusted(self, key_or_address):
        needle = normalize_address(key_or_address)
        before = len(self.trusted)
        self.trusted = [
            device for device in self.trusted
            if device.get("key") != key_or_address and normalize_address(device.get("address")) != needle
        ]
        if len(self.trusted) == before:
            return False
        speakers = self.trusted_speakers
        if speakers and not any(s.get("default") for s in speakers):
            speakers[0]["default"] = True
        return True

    def default_speaker_address(self):
        speakers = self.trusted_speakers
        for speaker in speakers:
            if speaker.get("default"):
                return speaker.get("address")
        return speakers[0].get("address") if speakers else None

    def select_default_speaker(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for speaker in self.trusted_speakers:
            match = speaker.get("key") == key_or_address or speaker.get("address") == needle
            speaker["default"] = match
            if match:
                selected = speaker.get("address")
        return selected

    def set_speaker_online(self, address, online=True):
        address = normalize_address(address)
        for device in self.trusted_speakers:
            if device.get("address") == address:
                device["online"] = bool(online)

    def clear_speaker_online(self):
        for device in self.trusted_speakers:
            device["online"] = False

    def set_connected_speaker(self, address):
        address = normalize_address(address)
        for device in self.trusted_speakers:
            device["connected"] = device.get("address") == address
            if device["connected"]:
                device["online"] = True

    def set_speaker_connected(self, address, connected=True):
        address = normalize_address(address)
        for device in self.trusted_speakers:
            if device.get("address") == address:
                device["connected"] = bool(connected)
                if connected:
                    device["online"] = True

    def clear_connected_speakers(self):
        for device in self.trusted_speakers:
            device["connected"] = False
