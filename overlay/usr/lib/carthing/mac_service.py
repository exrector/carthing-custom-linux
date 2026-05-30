"""mac_service — источник macOS в ту же MediaSession (Фаза 4, runtime-contract §MacService).

MacService сливает ДВА транспорта (USB reverse-agent поверх NCM + Bluetooth) в одну
MediaSession, как iPhone. На текущем этапе — каркас с чётким интерфейсом: подключается к тем же
точкам (runtime_model.select_source('mac'), command()), реализация транспорта — отдельная фаза.
Решение из транскриптов: macOS Now Playing штатно (osascript Apple Music), без стороннего ПО.
"""

import logging

logger = logging.getLogger(__name__)


class MacService:
    def __init__(self, model, on_update=None):
        self.model = model
        self.on_update = on_update or (lambda: None)
        self.active = False

    def attach(self):
        """Активировать mac как источник (взаимоисключение с iPhone — один аудио-фокус)."""
        self.model.select_source("mac")
        self.model.session.connected = True
        self.active = True
        self.on_update()

    def update_now_playing(self, title="", artist="", album="", duration=0.0,
                           elapsed=0.0, playing=False, volume=0.0):
        s = self.model.session
        if s.source != "mac":
            return
        s.title, s.artist, s.album, s.duration, s.volume = title, artist, album, duration, volume
        s.set_playback(elapsed, 1.0, playing)
        self.on_update()

    def detach(self):
        self.active = False
        if self.model.session.source == "mac":
            self.model.session.connected = False
            self.model.session.clear_track()
        self.on_update()

    async def command(self, intent: str):
        """Управление Mac-источником (Apple Music через reverse-agent/osascript). Фаза 4."""
        logger.info("mac command (phase 4, not wired): %s", intent)
