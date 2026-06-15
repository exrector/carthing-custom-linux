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
import state_paths


# [CLAUDE 2026-06-03] ЕДИНЫЙ файл состояния: devices + settings в одном state.json (один источник
# правды). Реестр (TrustedDeviceRegistry) импортирует этот же путь -> читает devices оттуда.
DEFAULT_TRUSTED_DEVICES_PATH = str(state_paths.STATE_FILE)
DEFAULT_KEYSTORE_PATH = str(state_paths.KEYS_PATH)


def normalize_address(address) -> str:
    text = str(address or "").strip().upper()
    return text.split("/", 1)[0]


def _dedupe_registry(devices):
    """[CLAUDE 2026-06-13] УНИВЕРСАЛЬНАЯ картотека: одна карточка на одно устройство.

    Принцип владельца: нашли устройство -> сверились с картотекой по ИДЕНТИЧНОСТИ ->
    дописали свойства (merge), а не плодим новую карточку. Ключевой урок «трёх
    айфонов»: BLE-источник при каждом пересопряжении даёт НОВЫЙ адрес бонда (iOS
    вращает адреса / новый IRK), и раньше каждый бонд становился отдельной карточкой.

    Идентичность:
      • source (телефон): рантайм моделирует РОВНО один источник (один a.iphone) ->
        все source-карточки сливаются в ОДНУ. Канон = подключённая, иначе самая
        полная (есть label/endpoints), иначе первая. Адрес кануна = подключённый.
      • output (колонка): classic-MAC стабилен (не вращается) -> дедуп по адресу.
    Свойства (capabilities/endpoints/metadata/label) объединяются по всем дублям.
    """
    def merge_into(dst, src):
        dst["capabilities"] = _merge_unique_strings(dst.get("capabilities"), src.get("capabilities"))
        dst["endpoints"] = _merge_endpoints(dst.get("endpoints"), src.get("endpoints"))
        dst["constraints"] = _merge_unique_strings(dst.get("constraints"), src.get("constraints"))
        md = dict(dst.get("metadata") or {}); md.update(src.get("metadata") or {}); dst["metadata"] = md
        # label: предпочитаем осмысленный (не равный адресу)
        if (not dst.get("label") or dst.get("label") == dst.get("address")) and src.get("label"):
            dst["label"] = src["label"]
        dst["online"] = bool(dst.get("online") or src.get("online"))
        dst["connected"] = bool(dst.get("connected") or src.get("connected"))
        return dst

    sources, others, out, seen_addr = [], [], [], {}
    for d in devices:
        if d.get("role") == "source":
            sources.append(d)
        else:
            others.append(d)
    # источники -> одна карточка
    if sources:
        def score(d):
            return (2 if d.get("connected") else 0) + (1 if (d.get("label") and d.get("label") != d.get("address")) else 0) + (1 if d.get("endpoints") else 0)
        canon = max(sources, key=score)
        for d in sources:
            if d is not canon:
                merge_into(canon, d)
        # адрес кануна = подключённого источника, если есть
        conn = next((d for d in sources if d.get("connected") and d.get("address")), None)
        if conn:
            canon["address"] = conn["address"]
        canon["key"] = "source:" + normalize_address(canon.get("address") or "") if canon.get("address") else (canon.get("key") or "source")
        out.append(canon)
    # выходы/прочее -> дедуп по адресу
    for d in others:
        addr = normalize_address(d.get("address"))
        if addr and addr in seen_addr:
            merge_into(seen_addr[addr], d)
            continue
        out.append(d)
        if addr:
            seen_addr[addr] = d
    return out


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
                "key": f"source:{address}",
                "address": address,
                "label": "Bluetooth Source",
                "type": "Источник",
                "role": "source",
                "online": False,
                "connected": False,
                "capabilities": ["audio_input", "metadata_input", "control_output", "notifications_input"],
                "endpoints": [
                    {
                        "id": "audio-input",
                        "direction": "input",
                        "protocols": ["classic_a2dp_sink"],
                        "capabilities": ["audio_input"],
                        "label": "Bluetooth audio input",
                    },
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
                ],
                "constraints": ["idle_link_allowed", "active_media_requires_route"],
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


def _value(value):
    return value.value if hasattr(value, "value") else value


def _endpoint_id(endpoint):
    if isinstance(endpoint, dict):
        return endpoint.get("id") or endpoint.get("direction")
    return getattr(endpoint, "id", None)


def _endpoint_to_row(endpoint):
    if isinstance(endpoint, dict):
        return endpoint
    return {
        "id": endpoint.id,
        "direction": _value(endpoint.direction),
        "protocols": sorted(str(_value(value)) for value in endpoint.protocols),
        "capabilities": sorted(str(_value(value)) for value in endpoint.capabilities),
        "label": endpoint.label,
        "metadata": dict(endpoint.metadata or {}),
    }


def _trusted_device_to_row(device):
    capabilities = sorted(str(_value(value)) for value in device.capabilities)
    endpoints = [_endpoint_to_row(endpoint) for endpoint in device.endpoints]
    has_input = any(endpoint.get("direction") == "input" for endpoint in endpoints)
    has_output = any(endpoint.get("direction") == "output" for endpoint in endpoints)
    if has_input and has_output:
        role = "device"
        dtype = "Маршрутизируемое устройство"
    elif has_output:
        role = "speaker"
        dtype = "Динамик"
    elif has_input:
        role = "source"
        dtype = "Источник"
    else:
        role = "device"
        dtype = "Устройство"
    return {
        "key": device.id,
        "address": normalize_address(device.address),
        "label": _clean_label(device.name),
        "type": dtype,
        "role": role,
        "online": bool(device.online),
        "connected": bool(device.connected),
        "capabilities": capabilities,
        "endpoints": endpoints,
        "constraints": sorted(str(_value(value)) for value in device.constraints),
        "metadata": dict(device.metadata or {}),
    }


def _merge_unique_strings(left, right):
    result = list(left or [])
    seen = set(result)
    for value in right or []:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _looks_like_address(value):
    text = str(value or "").strip()
    parts = text.split(":")
    if len(parts) != 6:
        return False
    return all(len(part) == 2 and all(ch in "0123456789abcdefABCDEF" for ch in part) for part in parts)


def _clean_label(value):
    text = str(value or "")
    text = "".join(ch for ch in text if ch >= " " and ch != "\x7f")
    return " ".join(text.strip().split())


def _merge_label(current, incoming, address=""):
    current = _clean_label(current)
    incoming = _clean_label(incoming)
    address = normalize_address(address)
    if not incoming:
        return current
    if _looks_like_address(incoming) or normalize_address(incoming) == address:
        return current or incoming
    if not current or _looks_like_address(current) or normalize_address(current) == address:
        return incoming
    return current


def _merge_endpoints(left, right):
    result = list(left or [])
    by_id = {_endpoint_id(endpoint): endpoint for endpoint in result if _endpoint_id(endpoint)}
    for endpoint in right or []:
        endpoint = _endpoint_to_row(endpoint)
        eid = _endpoint_id(endpoint)
        existing = by_id.get(eid)
        if existing is None:
            result.append(endpoint)
            if eid:
                by_id[eid] = endpoint
            continue
        existing["protocols"] = _merge_unique_strings(existing.get("protocols"), endpoint.get("protocols"))
        existing["capabilities"] = _merge_unique_strings(existing.get("capabilities"), endpoint.get("capabilities"))
        existing.setdefault("metadata", {}).update(endpoint.get("metadata") or {})
        if endpoint.get("label"):
            existing["label"] = endpoint["label"]
    return result


def _merge_metadata(left, right):
    result = dict(left or {})
    for key, value in (right or {}).items():
        if key == "capability_profile" and isinstance(value, dict):
            current = dict(result.get(key) or {})
            for list_key in ("evidence_sources", "verified_capabilities", "protocols"):
                current[list_key] = sorted(set(current.get(list_key) or []) | set(value.get(list_key) or []))
            unknowns = set(current.get("unknowns") or []) | set(value.get("unknowns") or [])
            evidence_sources = set(current.get("evidence_sources") or [])
            if "classic_sdp" in evidence_sources:
                unknowns.discard("classic_sdp")
            if "ble_gatt" in evidence_sources:
                unknowns.discard("ble_gatt")
            current["unknowns"] = sorted(unknowns)
            current["probe_status"] = value.get("probe_status") or current.get("probe_status")
            result[key] = current
        elif key == "enrollment_evidence" and isinstance(value, dict):
            current = dict(result.get(key) or {})
            for list_key in ("service_uuids", "ble_services", "missing_capabilities"):
                current[list_key] = sorted(set(current.get(list_key) or []) | set(value.get(list_key) or []))
            for scalar_key, scalar_value in value.items():
                if scalar_key not in ("service_uuids", "ble_services", "missing_capabilities"):
                    current[scalar_key] = scalar_value
            result[key] = current
        else:
            result[key] = value
    return result


def _default_endpoint_rows_for_capabilities(device):
    capabilities = set(device.get("capabilities") or [])
    endpoints = list(device.get("endpoints") or [])
    directions = {
        endpoint.get("direction")
        for endpoint in endpoints
        if isinstance(endpoint, dict)
    }
    defaults = []
    if "audio_input" in capabilities and "input" not in directions:
        defaults.append({
            "id": "audio-input",
            "direction": "input",
            "protocols": ["classic_a2dp_sink"],
            "capabilities": ["audio_input"],
            "label": "Bluetooth audio input",
        })
    if "audio_output" in capabilities and "output" not in directions:
        defaults.append({
            "id": "audio-output",
            "direction": "output",
            "protocols": ["classic_a2dp_source"],
            "capabilities": ["audio_output"],
            "label": "Bluetooth audio output",
        })
    return defaults


def _normalize_trusted_row(device):
    device["address"] = normalize_address(device.get("address"))
    device["capabilities"] = list(device.get("capabilities") or [])
    device["endpoints"] = _merge_endpoints(
        _default_endpoint_rows_for_capabilities(device),
        device.get("endpoints") or [],
    )
    if _device_is_input(device) and _device_is_output(device):
        device["role"] = "device"
        device["type"] = device.get("type") or "Маршрутизируемое устройство"
    elif _device_is_output(device):
        device["role"] = device.get("role") if device.get("role") not in ("source",) else "speaker"
        device["type"] = device.get("type") or "Динамик"
    elif _device_is_input(device):
        device["role"] = device.get("role") if device.get("role") not in ("speaker",) else "source"
        device["type"] = device.get("type") or "Источник"
    _ensure_capability_profile(device)
    return device


def _ensure_capability_profile(device):
    metadata = dict(device.get("metadata") or {})
    if metadata.get("capability_profile"):
        device["metadata"] = metadata
        return
    evidence = dict(metadata.get("enrollment_evidence") or {})
    capabilities = sorted(set(str(value) for value in (device.get("capabilities") or [])))
    protocols = sorted({
        str(protocol)
        for endpoint in (device.get("endpoints") or [])
        for protocol in (endpoint.get("protocols") or [])
    })
    if not capabilities and not protocols and not evidence:
        device["metadata"] = metadata
        return
    sources = []
    if evidence.get("class_of_device") is not None:
        sources.append("classic_cod")
    if evidence.get("service_uuids"):
        sources.append("classic_sdp")
    if evidence.get("ble_services"):
        sources.append("ble_gatt")
    unknowns = []
    if not evidence.get("service_uuids"):
        unknowns.append("classic_sdp")
    if not evidence.get("ble_services"):
        unknowns.append("ble_gatt")
    metadata["capability_profile"] = {
        "probe_status": evidence.get("enrollment_state") or ("ready" if capabilities or protocols else "degraded"),
        "evidence_sources": sorted(set(sources)),
        "verified_capabilities": capabilities,
        "protocols": protocols,
        "unknowns": sorted(set(unknowns)),
    }
    device["metadata"] = metadata


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
        self._dyn_sources = {}              # [CLAUDE] мультиустройство: сессии по адресу (2-й+ источник)
        self.active_desktop = 0
        self.last_media_source = "iphone"   # fallback for non-media desktops
        self.unread_count = 0
        self.notifications = []             # list of {"app","title","message"}
        self.trusted = []                   # {"key","label","type","role","online","connected",...}
        self.transfer_active = False
        self.transfer_scanning = False
        self.transfer_source = ""
        self._route_input = ""
        self._route_output = ""
        self._active_route_output = ""
        # [CLAUDE 2026-06-02] какая колонка активна (для скролла/подсветки) и совместимость
        # выбранной пары вход→выход: True=зелёный, False=красный (нельзя), None=ещё не оба выбраны.
        self.route_focus = "input"
        self.route_compatible = None
        self.route_name = ""
        self.route_protocols = []
        self.route_warnings = []
        self.route_cables = []
        self._active_session = "remote"
        self.power_tier = "boot"
        self.sleep_on_idle = True       # [CLAUDE] сон/гашение экрана (тумблер в Settings)
        self.screen_off_sec = 150       # [CLAUDE] тайм-аут полного гашения (настройка ± в Settings)
        self.notif_blink = True         # [CLAUDE] моргание кружка уведомлений под энкодером (тумблер)
        self.screen_brightness = 100    # [CLAUDE 2026-06-10] яркость экрана, % (цикл в Settings)
        self.ui_theme = "dark"          # [CLAUDE 2026-06-11] тема UI (dark|terminal); применяется рестартом runtime
        self.clock_text = "--:--"
        self.device_name = device_name()
        self.pairing_mode = False
        self.pairing_role = "source"   # source|speaker
        self.speaker_candidates = []   # classic inquiry candidates while adding a speaker
        self.selected_speaker_candidate = ""
        self.speaker_pairing_status = ""
        self.pairing_message = ""
        self.assistant_state = "idle"   # idle|listening|thinking|responding (Фаза 5)
        self.operation_mode = "commutator"   # [CLAUDE 2026-06-13] playnow|commutator|reserved; рантайм берёт из settings
        self.power_unplug_status = "idle"   # idle|preparing|ready|error
        self.power_unplug_message = ""
        self.trusted_path = Path(os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_TRUSTED_DEVICES_PATH))
        self.load_trusted()

    @staticmethod
    def _normalize_session(value):
        value = str(value or "remote").strip()
        return "router" if value == "transfer" else value

    @property
    def active_session(self):
        return self._active_session

    @active_session.setter
    def active_session(self, value):
        self._active_session = self._normalize_session(value)

    @property
    def device_mode(self):
        # Legacy alias for older UI/runtime code paths.
        return self._active_session

    @device_mode.setter
    def device_mode(self, value):
        self.active_session = value

    @property
    def route_input(self):
        return self._route_input

    @route_input.setter
    def route_input(self, key_or_address):
        self.select_route_input(key_or_address)

    @property
    def route_output(self):
        selected_speaker = next(
            (
                device.get("key") or device.get("address")
                for device in self.trusted_speakers
                if device.get("route_output")
            ),
            "",
        )
        if selected_speaker:
            self._route_output = selected_speaker
            return selected_speaker
        return self._route_output

    @route_output.setter
    def route_output(self, key_or_address):
        self.select_route_output(key_or_address)

    @property
    def active_route_output(self):
        return self._active_route_output or self.SELF_OUTPUT_KEY

    @active_route_output.setter
    def active_route_output(self, key_or_address):
        self.select_active_route_output(key_or_address)

    @property
    def route_active(self):
        return bool(
            self.route_input
            and self.active_route_output
            and self.active_route_output != self.SELF_OUTPUT_KEY
            and self.transfer_active
        )

    @property
    def sources(self):
        # [CLAUDE 2026-06-03] Мультиустройство: фикс. iphone/mac + динамические сессии по адресу
        # (для 2-го+ источника). Раньше словарь был жёстким {iphone,mac} -> выбор иного источника
        # давал KeyError. Теперь любой источник имеет валидную сессию.
        merged = {"iphone": self.iphone, "mac": self.mac}
        merged.update(self._dyn_sources)
        return merged

    def source_for(self, key):
        """Сессия источника по ключу/адресу. Неизвестный (2-й iPhone и т.п.) -> ленивое создание,
        чтобы выбор маршрута/транспорт не падал. Метаданные наполнит рантайм, когда подключится."""
        s = self.sources
        if key in s:
            return s[key]
        if key not in self._dyn_sources:
            self._dyn_sources[key] = MediaSession(str(key), str(key))
        return self._dyn_sources[key]

    def desktop_source(self, idx):
        return self.DESKTOP_SOURCE.get(idx)

    @property
    def control_source_key(self):
        """Which source the bottom-bar transport controls right now."""
        return self.desktop_source(self.active_desktop) or self.last_media_source

    @property
    def control_source(self):
        return self.source_for(self.control_source_key)

    def load_trusted(self, path=None):
        path = Path(path or os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_TRUSTED_DEVICES_PATH))
        self.trusted_path = path
        current_route_input = self._route_input
        current_route_output = self._route_output
        current_active_route_output = self._active_route_output
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
        persisted_route_output = str(data.get("route_output") or "").strip()
        persisted_active_route_output = str(data.get("active_route_output") or "").strip()

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
                    "route_input": bool(peer.get("route_input", False)),
                    "route_output": bool(peer.get("route_output", False)),
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
                        "capabilities": capabilities,
                        "endpoints": [{"id": role, "direction": endpoint_direction, "capabilities": capabilities}],
                        "constraints": ["idle_link_allowed", "active_media_requires_route"],
                        "metadata": {"legacy_role": role},
                    })
        devices = [_normalize_trusted_row(device) for device in devices]
        by_key = {device.get("key"): device for device in devices if device.get("key")}
        by_address = {device.get("address"): device for device in devices if device.get("address")}
        # [CLAUDE 2026-06-03] keys.json (keystore Bumble) только ЧИТАЕМ — узнать, какие источники
        # привязаны. Но device-ЗАПИСЬ должна жить в state.json вместе со всеми (один источник правды).
        # Если бонд ещё не записан как устройство — добавляем и помечаем на персист.
        new_bond = False
        for bonded in _bonded_source_rows():
            bonded = _normalize_trusted_row(bonded)
            existing = by_key.get(bonded["key"]) or by_address.get(bonded["address"])
            if existing is None:
                devices.append(bonded)
                by_key[bonded["key"]] = bonded
                by_address[bonded["address"]] = bonded
                new_bond = True
            else:
                existing.setdefault("role", "source")
                existing.setdefault("type", bonded["type"])
                existing.setdefault("label", bonded["label"])
                had_address = bool(existing.get("address"))
                had_endpoints = bool(existing.get("endpoints"))
                if not had_address:
                    existing["address"] = bonded["address"]
                existing["capabilities"] = _merge_unique_strings(existing.get("capabilities"), bonded.get("capabilities"))
                existing["endpoints"] = _merge_endpoints(existing.get("endpoints"), bonded.get("endpoints"))
                _normalize_trusted_row(existing)
                # [CLAUDE 2026-06-04] Если запись была stub (нет адреса или endpoints) —
                # пересохраняем в state.json чтобы TrustedDeviceRegistry видел полные данные.
                # Иначе route_planner не найдёт endpoints → RoutePlanError → кнопка красная.
                if not had_address or not had_endpoints:
                    new_bond = True
        devices = _dedupe_registry(devices)   # [CLAUDE 2026-06-13] одна карточка на устройство
        self.trusted = devices
        loaded_route_input = next(
            (device.get("key") or device.get("address") for device in self.route_inputs if device.get("route_input")),
            "",
        )
        self.route_input = current_route_input or loaded_route_input
        # Loading the registry must not mutate route ownership flags. Runtime
        # boot policy can still choose Play Now explicitly. After that, later
        # reloads preserve the live route instead of resurrecting a stale
        # persisted selection during AMS/source sync.
        loaded_route_output = next(
            (device.get("key") or device.get("address") for device in self.route_outputs if device.get("route_output")),
            "",
        )
        if current_route_output:
            self.route_output = current_route_output
        elif persisted_route_output:
            self.route_output = persisted_route_output
        else:
            self._route_output = loaded_route_output
        if current_active_route_output:
            self._active_route_output = current_active_route_output
        elif persisted_active_route_output:
            self._active_route_output = persisted_active_route_output
        self._ensure_route_selection()
        # [CLAUDE 2026-06-03] Новый bonded-источник -> ПЕРСИСТИМ в state.json, чтобы ВСЕ устройства
        # (iPhone и колонки) жили в одном месте. Идемпотентно: на следующем load он уже device,
        # new_bond=False -> повторной записи нет. На Mac degraded write_state просто no-op.
        if new_bond:
            try:
                self.save_trusted()
            except Exception:
                pass

    def _ensure_route_selection(self):
        if not self.route_input and len(self.route_inputs) == 1:
            selected = self.route_inputs[0]
            selected["route_input"] = True
            self.route_input = selected.get("key") or selected.get("address")
        if not self.route_output:
            self.route_output = self.SELF_OUTPUT_KEY
        if not self._active_route_output:
            self._active_route_output = self.SELF_OUTPUT_KEY

    def save_trusted(self, path=None):
        path = Path(path or self.trusted_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"schema": 2, "devices": []}
        seen = set()
        route_input_key = self._route_input
        route_input_address = normalize_address(route_input_key)
        route_output_key = self._route_output
        route_output_address = normalize_address(route_output_key)
        for device in self.trusted:
            device = _normalize_trusted_row(dict(device))
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
                "name": _clean_label(device.get("label")) or key,
                "type": device.get("type") or "Устройство",
                "role": device.get("role") or "device",
                "trusted": True,
                "capabilities": list(device.get("capabilities") or []),
                "endpoints": list(device.get("endpoints") or []),
                "constraints": list(device.get("constraints") or []),
                "metadata": dict(device.get("metadata") or {}),
            }
            if key == route_input_key or (address and address == route_input_address):
                row["route_input"] = True
            if key == route_output_key or (address and address == route_output_address):
                row["route_output"] = True
            data["devices"].append(row)
        # [CLAUDE 2026-06-03] Пишем devices в ЕДИНЫЙ state.json через write_state (read-modify-write:
        # секция settings сохраняется). Один источник правды вместо отдельного trusted-devices.json.
        import state_paths
        state_paths.write_state({"schema": 2, "devices": data["devices"]})

    def trusted_by_role(self, role):
        return [device for device in self.trusted if device.get("role") == role]

    def upsert_trusted_device(self, device):
        row = _trusted_device_to_row(device)
        address = normalize_address(row.get("address"))
        existing = next(
            (
                item for item in self.trusted
                if item.get("key") == row.get("key")
                or (address and normalize_address(item.get("address")) == address)
            ),
            None,
        )
        if existing is None:
            self.trusted.append(row)
            return row

        existing["label"] = _merge_label(existing.get("label"), row.get("label"), address)
        existing["type"] = row.get("type") or existing.get("type") or "Устройство"
        existing["role"] = "device" if (
            (_device_is_input(existing) or _device_is_input(row))
            and (_device_is_output(existing) or _device_is_output(row))
        ) else row.get("role") or existing.get("role") or "device"
        existing["online"] = bool(existing.get("online") or row.get("online"))
        existing["connected"] = bool(existing.get("connected") or row.get("connected"))
        existing["capabilities"] = _merge_unique_strings(existing.get("capabilities"), row.get("capabilities"))
        existing["endpoints"] = _merge_endpoints(existing.get("endpoints"), row.get("endpoints"))
        existing["constraints"] = _merge_unique_strings(existing.get("constraints"), row.get("constraints"))
        existing["metadata"] = _merge_metadata(existing.get("metadata"), row.get("metadata"))
        return existing

    def enroll_trusted_device(self, address, name=None, class_of_device=None,
                              service_uuids=None, ble_services=None, metadata=None,
                              capabilities=None, endpoints=None, constraints=None,
                              missing_capabilities=None):
        from enrollment_manager import EnrollmentEvidence, EnrollmentManager

        class _Registry:
            devices = []

            def by_id(self, _device_id):
                return None

        evidence = EnrollmentEvidence(
            address=address,
            name=_clean_label(name),
            class_of_device=class_of_device,
            service_uuids=set(service_uuids or []),
            ble_services=set(ble_services or []),
            capabilities=set(capabilities or []),
            endpoints=list(endpoints or []),
            constraints=set(constraints or []),
            missing_capabilities=set(missing_capabilities or []),
            metadata=dict(metadata or {}),
        )
        device = EnrollmentManager(_Registry()).build_device(evidence)
        for marker in ("input_enrolled", "output_enrolled"):
            if marker in evidence.metadata:
                device.metadata[marker] = bool(evidence.metadata[marker])
        return self.upsert_trusted_device(device)

    @property
    def trusted_sources(self):
        return [device for device in self.trusted if _device_is_input(device)]

    @property
    def trusted_speakers(self):
        return [device for device in self.trusted if _device_is_output(device)]

    @property
    def route_inputs(self):
        return self.trusted_sources

    # [CLAUDE 2026-06-03] Car Thing САМ как виртуальный выход (Play Now / control).
    # Иначе в Play Now к iPhone нечего привязать как output. Это НЕ audio-sink (нет playback-
    # железа) — это control/metadata поверхность: iPhone остаётся источником, Car Thing рулит
    # по BLE (AMS/ANCS). connected=True всегда — BLE-control постоянен.
    SELF_OUTPUT_KEY = "carthing"

    def _self_output_device(self):
        return {
            "key": self.SELF_OUTPUT_KEY,
            "address": "",
            "label": "Car Thing",          # self-выход — это сам хаб (Play Now), не hostname
            "type": "Play Now",
            "role": "self",
            "online": True,
            "connected": True,
            "capabilities": ["control_input", "metadata_input"],
            "endpoints": [{
                "id": "playnow",
                "direction": "output",
                "capabilities": ["control_input", "metadata_input"],
                "protocols": ["ble_ams"],
            }],
            "constraints": [],
            "metadata": {"self": True},
            "route_output": self._route_output == self.SELF_OUTPUT_KEY,
        }

    # Future lab endpoint only. The board exposes T9015/ALSA, but this product
    # unit has no populated analog line-out path, so it must not appear in the
    # release route graph. Keep it behind an explicit experimental flag for
    # later hardware-audio/remote-mic research.
    LINEOUT_OUTPUT_KEY = "carthing-lineout"

    def _lineout_output_device(self):
        return {
            "key": self.LINEOUT_OUTPUT_KEY,
            "address": "",
            "label": "Line out",
            "type": "T9015 DAC",         # вторая строка карточки (адреса нет)
            "role": "lineout",            # НЕ "speaker": standby-петля не пейджит
            "online": True,
            "connected": True,            # ЦАП всегда на месте
            "capabilities": ["audio_output"],
            "endpoints": [{
                "id": "lineout",
                "direction": "output",
                "capabilities": ["audio_output"],
                "protocols": ["local_t9015"],
            }],
            "constraints": [],
            "metadata": {"self": True, "local_audio": True},
            "route_output": self._route_output == self.LINEOUT_OUTPUT_KEY,
        }

    @property
    def route_outputs(self):
        # Car Thing-self первым в списке выходов, затем доверенные колонки.
        outputs = [self._self_output_device()]
        if os.environ.get("CARTHING_EXPERIMENTAL_LINEOUT_ENABLE") == "1":
            outputs.append(self._lineout_output_device())
        return outputs + self.trusted_speakers

    def select_route_input(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for device in self.route_inputs:
            match = device.get("key") == key_or_address or device.get("address") == needle
            device["route_input"] = match
            if match:
                selected = device.get("key") or device.get("address")
        self._route_input = selected or ""
        self.route_focus = "input"
        self.route_compatible = None        # пересчитает рантайм
        return selected

    def select_route_output(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for device in self.route_outputs:
            match = device.get("key") == key_or_address or device.get("address") == needle
            device["route_output"] = match
            if match:
                selected = device.get("key") or device.get("address")
        self._route_output = selected or ""
        self.route_focus = "output"
        self.route_compatible = None        # пересчитает рантайм
        return selected

    def select_active_route_output(self, key_or_address):
        selected = None
        needle = normalize_address(key_or_address)
        for device in self.route_outputs:
            match = device.get("key") == key_or_address or device.get("address") == needle
            if match:
                selected = device.get("key") or device.get("address")
        self._active_route_output = selected or self.SELF_OUTPUT_KEY
        return self._active_route_output

    def is_trusted_source(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_sources)

    def is_trusted_speaker(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted_speakers)

    def is_trusted_device(self, address):
        address = normalize_address(address)
        return any(device.get("address") == address for device in self.trusted)

    def upsert_speaker_candidate(self, address, name=None, class_of_device=None, rssi=None, audio=None):
        address = normalize_address(address)
        if not address:
            return None
        label = _clean_label(name) or address
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
                candidate["trusted"] = self.is_trusted_device(address)
                candidate["trusted_input"] = self.is_trusted_source(address)
                candidate["trusted_output"] = self.is_trusted_speaker(address)
                return candidate
        candidate = {
            "key": address,
            "address": address,
            "label": label,
            "type": "Динамик" if audio else "Устройство",
            "role": "speaker" if audio else "device",
            "class_of_device": class_of_device,
            "rssi": rssi,
            "audio": bool(audio),
            "trusted": self.is_trusted_device(address),
            "trusted_input": self.is_trusted_source(address),
            "trusted_output": self.is_trusted_speaker(address),
        }
        self.speaker_candidates.append(candidate)
        return candidate

    def clear_speaker_candidates(self):
        self.speaker_candidates = []
        self.selected_speaker_candidate = ""

    def select_speaker_candidate(self, address):
        address = normalize_address(address)
        if not address:
            return None
        candidate = next((c for c in self.speaker_candidates if c.get("address") == address), None)
        if candidate is None:
            return None
        self.selected_speaker_candidate = address
        return candidate

    def trust_speaker(self, address, name=None):
        address = normalize_address(address)
        if not address:
            return None
        candidate = next((c for c in self.speaker_candidates if c.get("address") == address), None)
        if candidate is not None and not candidate.get("audio"):
            return None
        label = _clean_label(name) or _clean_label((candidate or {}).get("label")) or address
        existing = self.enroll_trusted_device(
            address,
            name=label,
            class_of_device=(candidate or {}).get("class_of_device"),
            service_uuids={"110b", "audio_sink"},
            metadata={
                "enrolled_from": "classic_pairing",
                "audio": True,
                "output_enrolled": True,
                "probe_stage": "classic_cod_provisional",
            },
        )
        existing["online"] = True
        for candidate in self.speaker_candidates:
            if candidate.get("address") == address:
                candidate["trusted"] = True
                candidate["trusted_output"] = True
        return existing

    def revoke_speaker_role(self, key_or_address):
        """Remove only the output role from a card, preserving input identity."""
        needle = normalize_address(key_or_address)
        device = next(
            (
                item for item in self.trusted
                if item.get("key") == key_or_address or normalize_address(item.get("address")) == needle
            ),
            None,
        )
        if device is None:
            return False
        if not _device_is_input(device):
            return self.remove_trusted(key_or_address)
        output_caps = {"audio_output", "control_input", "volume_control", "transport_control"}
        device["capabilities"] = [
            cap for cap in (device.get("capabilities") or [])
            if cap not in output_caps
        ]
        device["endpoints"] = [
            endpoint for endpoint in (device.get("endpoints") or [])
            if endpoint.get("direction") != "output"
            and endpoint.get("id") not in {"audio-output", "remote-control", "speaker-remote"}
        ]
        metadata = dict(device.get("metadata") or {})
        metadata.pop("output_enrolled", None)
        device["metadata"] = metadata
        device["role"] = "source"
        device["type"] = "Источник"
        device["connected"] = False
        if self._route_output in {device.get("key"), normalize_address(device.get("address"))}:
            self._route_output = self.SELF_OUTPUT_KEY
        if self._active_route_output in {device.get("key"), normalize_address(device.get("address"))}:
            self._active_route_output = self.SELF_OUTPUT_KEY
        _normalize_trusted_row(device)
        return True

    def remove_trusted(self, key_or_address):
        needle = normalize_address(key_or_address)
        removed = [
            device for device in self.trusted
            if device.get("key") == key_or_address or normalize_address(device.get("address")) == needle
        ]
        before = len(self.trusted)
        self.trusted = [
            device for device in self.trusted
            if device.get("key") != key_or_address and normalize_address(device.get("address")) != needle
        ]
        if len(self.trusted) == before:
            return False
        removed_keys = {
            value
            for device in removed
            for value in (device.get("key"), normalize_address(device.get("address")))
            if value
        }
        if self._route_input in removed_keys:
            self._route_input = ""
        if self._route_output in removed_keys:
            self._route_output = self.SELF_OUTPUT_KEY
        if self._active_route_output in removed_keys:
            self._active_route_output = self.SELF_OUTPUT_KEY
        for candidate in self.speaker_candidates:
            if normalize_address(candidate.get("address")) == needle:
                candidate["trusted"] = False
        return True

    def route_speaker_address(self):
        output = normalize_address(self.route_output)
        if not output:
            return None
        for speaker in self.trusted_speakers:
            if speaker.get("key") == self.route_output or normalize_address(speaker.get("address")) == output:
                return normalize_address(speaker.get("address"))
        return None

    def active_route_speaker_address(self):
        output_key = self.active_route_output
        output = normalize_address(output_key)
        if not output:
            return None
        for speaker in self.trusted_speakers:
            if speaker.get("key") == output_key or normalize_address(speaker.get("address")) == output:
                return normalize_address(speaker.get("address"))
        return None

    def select_route_speaker(self, key_or_address):
        """Select an active output route without changing any standby ownership."""
        needle = normalize_address(key_or_address)
        for speaker in self.trusted_speakers:
            match = speaker.get("key") == key_or_address or speaker.get("address") == needle
            if match:
                self.select_route_output(key_or_address)
                return speaker.get("address")
        return None

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
