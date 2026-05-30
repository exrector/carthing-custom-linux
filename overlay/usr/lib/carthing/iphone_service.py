"""iphone_service — адаптер источника iPhone (AMS + ANCS + CTS) на одну BLE-связь.

architecture.md: источник iPhone проецируется в ОДНУ MediaSession (runtime_model).
Все три клиента живут на ОДНОМ gatt_client этой connection (паттерн из 2026-05-19).
Это обёртка над проверенными ams_client/ancs_client/cts_client — без переписывания логики.
"""

import logging

from ams_client import (
    AMSClient, MediaState,
    CMD_TOGGLE, CMD_NEXT, CMD_PREV, CMD_VOL_UP, CMD_VOL_DOWN,
)

# GUI-intent -> AMS command (play/pause оба = TOGGLE: у AMS нет раздельных).
_AMS_CMD = {
    "play": CMD_TOGGLE, "pause": CMD_TOGGLE, "toggle": CMD_TOGGLE,
    "next": CMD_NEXT, "prev": CMD_PREV, "previous": CMD_PREV,
    "vol_up": CMD_VOL_UP, "vol_down": CMD_VOL_DOWN,
}

try:
    from ancs_client import ANCSClient
except Exception:
    ANCSClient = None
try:
    from cts_client import CTSClient
except Exception:
    CTSClient = None

logger = logging.getLogger(__name__)


class IPhoneService:
    def __init__(self, model, on_update=None):
        self.model = model
        self.on_update = on_update
        self._ams_state = MediaState()
        self.ams = None
        self.ancs = None
        self.cts = None

    async def setup(self, connection) -> bool:
        self.model.select_source("iphone")
        sess = self.model.session
        sess.connected = True
        try:
            sess.peer = str(connection.peer_address)
        except Exception:
            sess.peer = None

        self.ams = AMSClient(self._ams_state, on_update=self._on_ams)
        ok = await self.ams.setup(connection)

        if ANCSClient is not None:
            self.ancs = ANCSClient(on_fetched=self._on_notif, on_removed=self._on_removed)
            try:
                await self.ancs.setup(connection)
            except Exception as e:
                logger.warning("ANCS setup failed: %s", e)

        if CTSClient is not None:
            self.cts = CTSClient()
            try:
                await self.cts.setup(connection)
            except Exception as e:
                logger.warning("CTS setup failed: %s", e)

        self._publish()
        return ok

    # ── AMS -> MediaSession (живой elapsed через snapshot) ───────────────────
    def _on_ams(self, *args):
        s, sess = self._ams_state, self.model.session
        sess.title = s.title
        sess.artist = s.artist
        sess.album = getattr(s, "album", "")
        sess.duration = s.duration
        sess.volume = s.volume
        sess.set_playback(getattr(s, "_elapsed", 0.0), getattr(s, "_rate", 1.0), s.playing)
        self._publish()

    # ── ANCS -> notif-индикатор (не баннер) ──────────────────────────────────
    def _on_notif(self, notif):
        self.model.notif_count += 1
        self.model.notif_last = getattr(notif, "title", "") or getattr(notif, "app_id", "")
        self._publish()

    def _on_removed(self, uid):
        if self.model.notif_count > 0:
            self.model.notif_count -= 1
        self._publish()

    def reset(self):
        sess = self.model.session
        sess.connected = False
        sess.clear_track()
        self._publish()

    def _publish(self):
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    async def send_command(self, cmd):
        if self.ams is not None:
            await self.ams.send_command(cmd)

    async def command(self, intent: str):
        """GUI/encoder intent (строка) -> AMS-команда."""
        code = _AMS_CMD.get(intent)
        if code is not None and self.ams is not None:
            await self.ams.send_command(code)
