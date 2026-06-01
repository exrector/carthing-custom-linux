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
    IPHONE, SETTINGS, NOTIFICATIONS, MODES, TRANSFER, MAC = 0, 1, 2, 3, 4, 5
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
        self.device_mode = "remote"
        self.mode_status = "remote"
        self.power_tier = "boot"
        self.sleep_on_idle = True       # [CLAUDE] сон/гашение экрана (тумблер в Settings)
        self.clock_text = "--:--"
        self.device_name = device_name()
        self.pairing_mode = False
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
                devices.append({
                    "key": peer.get("key") or address,
                    "address": address,
                    "label": peer.get("name") or peer.get("label") or address,
                    "type": peer.get("type") or ("Источник" if role == "source" else "Динамик"),
                    "role": role,
                    "online": bool(peer.get("online", False)),
                    "connected": bool(peer.get("connected", False)),
                    "default": bool(peer.get("default", index == 0 and role == "speaker")),
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
        data = {"sources": [], "speakers": []}
        for device in self.trusted:
            row = {
                "name": device.get("label"),
                "address": device.get("address"),
                "type": device.get("type"),
            }
            if device.get("default"):
                row["default"] = True
            if device.get("role") == "source":
                data["sources"].append(row)
            elif device.get("role") == "speaker":
                data["speakers"].append(row)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(path)

    def trusted_by_role(self, role):
        return [device for device in self.trusted if device.get("role") == role]

    @property
    def trusted_sources(self):
        return self.trusted_by_role("source")

    @property
    def trusted_speakers(self):
        return self.trusted_by_role("speaker")

    def is_trusted_source(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_sources)

    def is_trusted_speaker(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_speakers)

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

    def clear_connected_speakers(self):
        for device in self.trusted_speakers:
            device["connected"] = False
