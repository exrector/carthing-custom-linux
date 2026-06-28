"""Runtime state for the minimal Play Now product."""

import json
import os
import time
from pathlib import Path


RUNTIME_BT_JSON = Path(
    os.environ.get("CARTHING_RUNTIME_BT_JSON", "/run/carthing/runtime-bt.json")
)
_ZONE_EDGES = (("near", -65), ("mid", -82), ("far", -93))


def _zone_from_rssi(rssi):
    if rssi is None:
        return "gone"
    for name, edge in _ZONE_EDGES:
        if rssi > edge:
            return name
    return "gone"


class MediaSession:
    """The single iPhone media session shown by Play Now."""

    def __init__(self, source="none"):
        self.source = source
        self.connected = False
        self.peer = None
        self.title = ""
        self.artist = ""
        self.album = ""
        self.duration = 0.0
        self.volume = 0.0
        self.playing = False
        self._elapsed = 0.0
        self._rate = 1.0
        self._ts = 0.0
        self.supported_commands = set()

    def set_playback(self, elapsed, rate, playing):
        self._elapsed = float(elapsed or 0.0)
        self._rate = float(rate if rate not in (None, 0) else 1.0)
        self.playing = bool(playing)
        self._ts = time.monotonic()

    @property
    def elapsed(self):
        elapsed = self._elapsed
        if self.playing and self._rate > 0:
            elapsed += (time.monotonic() - self._ts) * self._rate
        if self.duration:
            elapsed = min(elapsed, self.duration)
        return max(0.0, elapsed)

    def clear_track(self):
        self.title = ""
        self.artist = ""
        self.album = ""
        self.duration = 0.0
        self._elapsed = 0.0
        self.playing = False


class RuntimeModel:
    def __init__(self):
        self.session = MediaSession()
        self.notifications = []
        self.rssi = None
        self.proximity_zone = "gone"
        self.power_tier = "interactive"
        self.operation_mode = "playnow"
        self.remote_mic = {
            "enabled": False,
            "state": "off",
            "message": "Микрофон выключен",
            "transport": "none",
        }

    def select_source(self, source):
        if self.session.source != source:
            self.session = MediaSession(source)

    def update_rssi(self, rssi):
        self.rssi = rssi
        self.proximity_zone = _zone_from_rssi(rssi)

    def set_remote_mic(self, enabled, state=None, message=None, transport=None):
        self.remote_mic = {
            "enabled": bool(enabled),
            "state": str(state or ("listening" if enabled else "off")),
            "message": str(message or ""),
            "transport": str(
                transport or self.remote_mic.get("transport", "none")
            ),
        }

    def add_notification(self, uid, app, title, body=""):
        for notification in self.notifications:
            if notification["uid"] == uid:
                notification.update(app=app, title=title, body=body)
                return
        self.notifications.append(
            {"uid": uid, "app": app, "title": title, "body": body}
        )

    def remove_notification(self, uid):
        self.notifications = [
            notification
            for notification in self.notifications
            if notification["uid"] != uid
        ]

    def bt_block(self):
        session = self.session
        return {
            "source": session.source,
            "connected": session.connected,
            "peer": session.peer,
            "rssi": self.rssi,
            "proximity_zone": self.proximity_zone,
            "now_playing": {
                "title": session.title,
                "artist": session.artist,
                "album": session.album,
                "playing": session.playing,
                "elapsed": round(session.elapsed, 1),
                "duration": round(session.duration, 1),
                "volume": round(session.volume, 3),
                "supported_commands": sorted(session.supported_commands),
            },
            "notifications": {
                "count": len(self.notifications),
                "last": (
                    self.notifications[-1]["title"]
                    if self.notifications
                    else None
                ),
            },
            "operation_mode": self.operation_mode,
            "power_tier": self.power_tier,
            "remote_mic": dict(self.remote_mic),
        }

    def write_bt_json(self, path=RUNTIME_BT_JSON):
        document = {"schema": 1, "ts": time.time(), "bt": self.bt_block()}
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(document, ensure_ascii=False))
            os.replace(str(temporary), str(path))
        except Exception:
            pass
