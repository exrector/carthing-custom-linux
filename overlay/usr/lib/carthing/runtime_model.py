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
        self.app_name = ""
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
        self.remote_media_active = False
        self.remote_media_id = ""
        self.remote_media_updated_at = 0.0
        self.notifications = []
        self.rssi = None
        self.proximity_zone = "gone"
        self.power_tier = "interactive"
        self.operation_mode = "playnow"
        self.server_status = {}
        self.remote_mic = {
            "enabled": False,
            "state": "off",
            "message": "Микрофон выключен",
            "transport": "none",
        }

    def select_source(self, source):
        if self.session.source != source:
            self.session = MediaSession(source)

    def apply_remote_media(self, payload):
        """Overlay an active AirPlay receiver session on the iPhone session."""
        payload = dict(payload or {})
        if not payload.get("active"):
            return self.clear_remote_media()

        identifier = str(payload.get("identifier") or "")
        playing = bool(payload.get("playing"))
        loading = bool(payload.get("loading"))
        same_session = bool(
            self.remote_media_active
            and identifier
            and identifier == self.remote_media_id
        )
        identified_media = bool(identifier and payload.get("title"))
        if not (playing or loading or same_session or identified_media):
            return False

        session = self.session
        self.remote_media_active = True
        self.remote_media_id = identifier
        self.remote_media_updated_at = time.monotonic()
        session.title = str(payload.get("title") or "")
        session.artist = str(payload.get("artist") or "")
        session.album = str(payload.get("album") or "")
        session.app_name = str(payload.get("route") or "AirPlay")
        if payload.get("volume") is not None:
            session.volume = max(0.0, min(1.0, float(payload["volume"])))
        session.duration = max(0.0, float(payload.get("duration") or 0.0))
        session.set_playback(
            max(0.0, float(payload.get("elapsed") or 0.0)),
            1.0,
            playing,
        )
        session.supported_commands = {0, 1, 2, 3, 4, 5, 6}
        return True

    def clear_remote_media(self):
        was_active = self.remote_media_active
        self.remote_media_active = False
        self.remote_media_id = ""
        self.remote_media_updated_at = 0.0
        return was_active

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

    def update_server_status(self, payload):
        payload = dict(payload or {})
        self.server_status = {
            "host": str(payload.get("host") or "Mac"),
            "connected": bool(payload.get("connected", True)),
            "assistant": bool(payload.get("assistant", False)),
            "cpu_load_pct": max(
                0.0, min(999.0, float(payload.get("cpu_load_pct") or 0.0))
            ),
            "memory_gb": max(0.0, float(payload.get("memory_gb") or 0.0)),
            "thermal": str(payload.get("thermal") or "unknown"),
            "uptime_s": max(0.0, float(payload.get("uptime_s") or 0.0)),
            "ctsp_rtt_ms": (
                max(0.0, float(payload["ctsp_rtt_ms"]))
                if payload.get("ctsp_rtt_ms") is not None
                else None
            ),
        }

    def set_server_disconnected(self):
        if not self.server_status:
            return
        self.server_status["connected"] = False
        self.server_status["assistant"] = False

    def add_notification(
        self,
        uid,
        app,
        title,
        body="",
        category="Other",
        important=False,
        positive_action=False,
        negative_action=False,
        positive_label="",
        negative_label="",
    ):
        fields = {
            "app": app,
            "title": title,
            "body": body,
            "category": str(category or "Other"),
            "important": bool(important),
            "positive_action": bool(positive_action),
            "negative_action": bool(negative_action),
            "positive_label": str(positive_label or ""),
            "negative_label": str(negative_label or ""),
        }
        for notification in self.notifications:
            if notification["uid"] == uid:
                notification.update(**fields)
                return
        self.notifications.append({"uid": uid, **fields})

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
                "app_name": session.app_name,
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
            "server_status": dict(self.server_status),
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
