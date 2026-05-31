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
        # AudioRoute: куда идёт звук (builtin = телефон сам; speaker = Transfer-relay).
        self.audio_sink = "builtin"          # builtin|speaker
        self.speaker_name = None
        self.speaker_connected = False
        self.transfer_active = False
        # ControlRoute: кто рулит источником (local/speaker_remote -> source).
        self.control_routes = []             # list[(controller, source)]
        self.transfer_control_available = False
        # уведомления (ANCS) — полный список зеркала iPhone: [{uid, app, text}].
        self.notifications = []
        # presence
        self.rssi = None
        self.proximity_zone = "gone"

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

    # ── уведомления (зеркало iPhone) ─────────────────────────────────────────
    def add_notification(self, uid, app, text):
        for n in self.notifications:
            if n["uid"] == uid:
                n["app"], n["text"] = app, text
                return
        self.notifications.append({"uid": uid, "app": app, "text": text})

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
            },
            "speaker": {"connected": self.speaker_connected, "name": self.speaker_name},
            "notifications": {"count": len(self.notifications),
                              "last": (self.notifications[-1]["text"] if self.notifications else None)},
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
