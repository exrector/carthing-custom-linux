"""runtime_model — центральный координатор одной MediaSession + маршрутов.

architecture.md §Media Session Contract + runtime-state-schema.md.

Продукт построен вокруг ОДНОЙ MediaSession (а не GUI-страниц):
  source -> audio route -> sink
  controllers -> control routes -> source
  runtime state -> GUI views

В процессе media_remote это in-process мост между событиями AMS/ANCS/A2DP/control и
GUI-facing RuntimeState. Пишет ТОЛЬКО свою bt-часть в /run/carthing/runtime-bt.json
(дирижёр мёржит её в общий /run/carthing/runtime-state.json — schema §Контракт).
"""

import json
import os
import time
from pathlib import Path

RUNTIME_BT_JSON = Path(os.environ.get("CARTHING_RUNTIME_BT_JSON", "/run/carthing/runtime-bt.json"))

# proximity-зоны из RSSI (runtime-state-schema.md, замер 2026-05-30) + гистерезис.
_ZONE_EDGES = (("near", -65), ("mid", -82), ("far", -93))  # > edge => зона


def _zone_from_rssi(rssi, prev=None):
    if rssi is None:
        return "gone"
    for name, edge in _ZONE_EDGES:
        if rssi > edge:
            return name
    return "gone"


class MediaSession:
    """Активный источник (iphone|mac) + живой now-playing. Один аудио-фокус."""

    def __init__(self, source="none"):
        self.source = source          # iphone|mac|none
        self.connected = False
        self.peer = None              # RPA, меняется
        self.title = ""
        self.artist = ""
        self.album = ""
        self.duration = 0.0
        self.volume = 0.0
        self.playing = False
        self._elapsed = 0.0           # снимок elapsed от источника (AMS/AVRCP)
        self._rate = 1.0              # playbackRate
        self._ts = 0.0                # monotonic снимка
        # Какие транспорт-команды реально поддерживает текущее приложение (AMS
        # RemoteCommand-список). Меняется Music<->Podcasts. GUI рисует ТОЛЬКО их.
        self.supported_commands = set()

    def set_playback(self, elapsed, rate, playing):
        self._elapsed = float(elapsed or 0.0)
        self._rate = float(rate if rate not in (None, 0) else 1.0)
        self.playing = bool(playing)
        self._ts = time.monotonic()

    @property
    def elapsed(self):
        """Живой прогресс: экстраполяция между снимками источника."""
        if not self.playing or self._rate <= 0:
            base = self._elapsed
        else:
            base = self._elapsed + (time.monotonic() - self._ts) * self._rate
        if self.duration:
            base = min(base, self.duration)
        return max(0.0, base)

    def clear_track(self):
        self.title = self.artist = self.album = ""
        self.duration = 0.0
        self._elapsed = 0.0
        self.playing = False


class RuntimeModel:
    def __init__(self):
        self.session = MediaSession()
        self._active_session = "remote"
        self.operation_mode = "playnow"
        self.mode_resources = {}
        self.power_tier = "boot"
        self.mode_status = "remote"
        # AudioRoute: куда идёт звук (builtin = телефон сам; speaker = Transfer-relay).
        self.audio_sink = "builtin"          # builtin|speaker
        self.speaker_name = None
        self.speaker_connected = False
        self.speakers = []
        self.transfer_active = False
        # ControlRoute: кто рулит источником (local/speaker_remote -> source).
        self.control_routes = []             # list[(controller, source)]
        self.transfer_control_available = False
        # Route graph summary: the currently active planned session.
        self.route_name = ""
        self.route_input = ""
        self.route_output = ""
        self.route_protocols = []
        self.route_warnings = []
        self.route_cables = []
        self.route_active = False
        # уведомления (ANCS) — полный список зеркала iPhone: [{uid, app, text}].
        self.notifications = []
        # presence
        self.rssi = None
        self.proximity_zone = "gone"

    @property
    def active_session(self):
        return self._active_session

    @active_session.setter
    def active_session(self, value):
        value = str(value or "remote")
        if value == "transfer":
            value = "router"
        self._active_session = value

    @property
    def device_mode(self):
        # Legacy runtime-state alias; keep for compatibility with older readers.
        return self._active_session

    @device_mode.setter
    def device_mode(self, value):
        self.active_session = value

    # ── источник / взаимоисключение (Play на Mac глушит iPhone) ──────────────
    def select_source(self, source):
        if self.session.source != source:
            self.session = MediaSession(source)

    def update_rssi(self, rssi):
        self.rssi = rssi
        self.proximity_zone = _zone_from_rssi(rssi, self.proximity_zone)

    def add_control_route(self, controller, source):
        route = (controller, source)
        if route not in self.control_routes:
            self.control_routes.append(route)
        if controller == "speaker_remote":
            self.transfer_control_available = True

    def set_route_plan(self, plan, cables=None):
        self.route_name = str(getattr(plan, "name", "") or "")
        routes = list(getattr(plan, "routes", []) or [])
        route = routes[0] if routes else None
        self.route_input = getattr(route, "input_device_id", "") if route is not None else ""
        self.route_output = getattr(route, "output_device_id", "") if route is not None else ""
        self.route_protocols = sorted(
            str(value.value if hasattr(value, "value") else value)
            for value in getattr(plan, "required_protocols", []) or []
        )
        self.route_warnings = list(getattr(plan, "warnings", []) or [])
        self.route_cables = [
            str(getattr(cable, "id", cable))
            for cable in (cables or [])
        ]
        self.route_active = bool(routes)

    def clear_route_plan(self):
        self.route_name = ""
        self.route_input = ""
        self.route_output = ""
        self.route_protocols = []
        self.route_warnings = []
        self.route_cables = []
        self.route_active = False

    def set_operation_mode(self, mode, resources=None):
        self.operation_mode = str(mode or "playnow")
        self.mode_resources = dict(resources or {})

    # ── уведомления (зеркало iPhone) ─────────────────────────────────────────
    def add_notification(self, uid, app, title, body=""):
        # title = содержание (у Напоминаний — сам текст; у Сообщений — отправитель);
        # body = вторичное (дата/время, текст сообщения). Несём оба — единого «того
        # самого» поля у iOS нет, оно разное для разных приложений.
        for n in self.notifications:
            if n["uid"] == uid:
                n["app"], n["title"], n["body"] = app, title, body
                return
        self.notifications.append({"uid": uid, "app": app, "title": title, "body": body})

    def remove_notification(self, uid):
        self.notifications = [n for n in self.notifications if n["uid"] != uid]

    # ── сериализация bt-части (runtime-state-schema.md §bt) ───────────────────
    def bt_block(self) -> dict:
        s = self.session
        return {
            "source": s.source,
            "connected": s.connected,
            "peer": s.peer,
            "rssi": self.rssi,
            "proximity_zone": self.proximity_zone,
            "now_playing": {
                "title": s.title, "artist": s.artist, "album": s.album,
                "playing": s.playing,
                "elapsed": round(s.elapsed, 1),
                "duration": round(s.duration, 1),
                "supported_commands": sorted(s.supported_commands),
            },
            "speaker": {"connected": self.speaker_connected, "name": self.speaker_name},
            "speakers": list(self.speakers),
            "route": {
                "name": self.route_name,
                "input": self.route_input,
                "output": self.route_output,
                "protocols": list(self.route_protocols),
                "warnings": list(self.route_warnings),
                "cables": list(self.route_cables),
                "active": self.route_active,
            },
            "notifications": {"count": len(self.notifications),
                              "last": (self.notifications[-1]["title"] if self.notifications else None)},
            "active_session": self.active_session,
            "device_mode": self.device_mode,
            "operation_mode": self.operation_mode,
            "mode_resources": dict(self.mode_resources),
            "mode_status": self.mode_status,
            "power_tier": self.power_tier,
            "transfer_active": self.transfer_active,
            "transfer_control_available": self.transfer_control_available,
        }

    def write_bt_json(self, path: Path = RUNTIME_BT_JSON):
        """Атомарная запись своей bt-части. Дирижёр её мёржит в общий документ."""
        doc = {"schema": 1, "ts": time.time(), "bt": self.bt_block()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(doc, ensure_ascii=False))
            os.replace(str(tmp), str(path))
        except Exception:
            pass
