"""iphone_service — адаптер источника iPhone (AMS + ANCS + CTS) на одну BLE-связь.

architecture.md: источник iPhone проецируется в ОДНУ MediaSession (runtime_model).
Все три клиента живут на ОДНОМ gatt_client этой connection (паттерн из 2026-05-19).
Это обёртка над проверенными ams_client/ancs_client/cts_client — без переписывания логики.
"""

import logging
import time as _time

from ams_client import (
    AMSClient, MediaState,
    CMD_TOGGLE, CMD_NEXT, CMD_PREV, CMD_VOL_UP, CMD_VOL_DOWN,
    CMD_REPEAT, CMD_SHUFFLE, CMD_SKIP_FWD, CMD_SKIP_BACK,
    CMD_LIKE, CMD_DISLIKE, CMD_BOOKMARK,
)

# GUI-intent -> AMS command (play/pause оба = TOGGLE: у AMS нет раздельных).
_AMS_CMD = {
    "play": CMD_TOGGLE, "pause": CMD_TOGGLE, "toggle": CMD_TOGGLE,
    "next": CMD_NEXT, "prev": CMD_PREV, "previous": CMD_PREV,
    "vol_up": CMD_VOL_UP, "vol_down": CMD_VOL_DOWN,
    "skip_fwd": CMD_SKIP_FWD, "skip_back": CMD_SKIP_BACK,
    "like": CMD_LIKE, "dislike": CMD_DISLIKE,
    "repeat": CMD_REPEAT, "shuffle": CMD_SHUFFLE, "bookmark": CMD_BOOKMARK,
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
    def __init__(self, model, on_update=None, hci_gate=None):
        self.model = model
        self.on_update = on_update
        self.hci_gate = hci_gate
        self._ams_state = MediaState()
        self._peer = None
        self._connected = False
        self._supported_commands = set()
        self.ams = None
        self.ancs = None
        self.cts = None

    async def _gate(self, label, operation):
        if self.hci_gate is None:
            return await operation()
        return await self.hci_gate.run(label, operation)

    async def setup(self, connection) -> bool:
        self.model.select_source("iphone")
        sess = self.model.session
        sess.connected = True
        try:
            sess.peer = str(connection.peer_address)
        except Exception:
            sess.peer = None
        self._peer = sess.peer
        self._connected = True

        self.ams = AMSClient(self._ams_state, on_update=self._on_ams,
                             on_commands=self._on_commands)
        ok = await self._gate("iphone-ams-setup", lambda: self.ams.setup(connection))

        if ANCSClient is not None:
            # ignore_preexisting=False: при подключении iOS переигрывает ВСЕ уже висящие
            # уведомления (флаг PreExisting). Так список = живое зеркало Центра уведомлений
            # и НАПОЛНЯЕТСЯ после ребута/реконнекта, а не остаётся пустым.
            self.ancs = ANCSClient(on_fetched=self._on_notif, on_removed=self._on_removed,
                                   ignore_preexisting=False)
            try:
                await self._gate("iphone-ancs-setup", lambda: self.ancs.setup(connection))
            except Exception as e:
                logger.warning("ANCS setup failed: %s", e)

        if CTSClient is not None:
            self.cts = CTSClient()
            try:
                await self._gate("iphone-cts-setup", lambda: self.cts.setup(connection))
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
        # Копируем СНИМОК воспроизведения как есть (_elapsed/_rate/_ts), НЕ пере-штампуя
        # _ts=now: иначе нотификация громкости сбрасывала живой прогресс на старый снимок
        # (прогресс «прыгал» при кручении энкодера). _ts источника = момент playbackInfo.
        sess._elapsed = getattr(s, "_elapsed", 0.0)
        sess._rate = getattr(s, "_rate", 1.0)
        sess._ts = getattr(s, "_ts", _time.monotonic())
        sess.playing = s.playing
        self._publish()

    # ── AMS supported-команды -> сессия (GUI рисует только рабочие кнопки) ────
    def _on_commands(self, cmds):
        self._supported_commands = set(cmds)
        self.model.session.supported_commands = set(cmds)
        self._publish()

    # ── ANCS -> список уведомлений (зеркало iPhone) ──────────────────────────
    def _on_notif(self, notif):
        # Несём title и body РАЗДЕЛЬНО: у iOS «текст» лежит в разных полях для разных
        # приложений (Напоминания: title=текст, message=дата; Сообщения: title=отправитель,
        # message=текст). title = главное содержание, body = вторичное.
        title = (getattr(notif, "title", "") or "").strip()
        body = (getattr(notif, "message", "") or getattr(notif, "subtitle", "") or "").strip()
        if not title:                      # если title пуст — поднять body в заголовок
            title, body = body, ""
        self.model.add_notification(notif.uid, notif.app_name, title, body)
        self._publish()

    def _on_removed(self, uid):
        self.model.remove_notification(uid)
        self._publish()

    async def dismiss(self, uid):
        """Свайп-влево на гаджете -> очистить уведомление И на iPhone (ANCS negative)."""
        if self.ancs is not None:
            try:
                await self._gate("iphone-ancs-dismiss", lambda: self.ancs.perform_action(uid))
            except Exception as e:
                logger.warning("ANCS dismiss failed: %s", e)
        self.model.remove_notification(uid)
        self._publish()

    def reset(self):
        self._connected = False
        sess = self.model.session
        sess.connected = False
        sess.clear_track()
        self._publish()

    def activate_source(self):
        """Return runtime focus to the existing iPhone BLE session."""
        self.model.select_source("iphone")
        sess = self.model.session
        sess.connected = bool(self._connected)
        sess.peer = self._peer
        sess.title = self._ams_state.title
        sess.artist = self._ams_state.artist
        sess.album = getattr(self._ams_state, "album", "")
        sess.duration = self._ams_state.duration
        sess.volume = self._ams_state.volume
        sess._elapsed = getattr(self._ams_state, "_elapsed", 0.0)
        sess._rate = getattr(self._ams_state, "_rate", 1.0)
        sess._ts = getattr(self._ams_state, "_ts", _time.monotonic())
        sess.playing = self._ams_state.playing
        sess.supported_commands = set(self._supported_commands)
        self._publish()

    def _publish(self):
        if self.on_update:
            try:
                self.on_update()
            except Exception:
                pass

    async def send_command(self, cmd):
        if self.ams is not None:
            await self._gate("iphone-ams-send", lambda: self.ams.send_command(cmd))

    async def command(self, intent: str):
        """GUI/encoder intent (строка) -> AMS-команда."""
        code = _AMS_CMD.get(intent)
        if code is not None and self.ams is not None:
            await self._gate("iphone-ams-command", lambda: self.ams.send_command(code))
