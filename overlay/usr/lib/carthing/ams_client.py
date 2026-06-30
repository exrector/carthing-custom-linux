import asyncio
import logging
import time
from runtime_paths import ensure_runtime_paths
ensure_runtime_paths()
from bumble.gatt_client import Client
from bumble.core import UUID

logger = logging.getLogger(__name__)

AMS_SERVICE_UUID          = UUID("89D3502B-0F36-433A-8EF4-C502AD55F8DC")
AMS_REMOTE_COMMAND_UUID   = UUID("9B3C81D8-57B1-4A8A-B8DF-0E56F7CA51C2")
AMS_ENTITY_UPDATE_UUID    = UUID("2F7CABCE-808D-411F-9A0C-BB92BA96C102")
AMS_ENTITY_ATTRIBUTE_UUID = UUID("C6B2F38C-23AB-46D8-A6AB-A3A870BBD5D7")

ENTITY_PLAYER = 0
ENTITY_TRACK  = 2

# Player attributes (correct per AMS spec)
PLAYER_ATTR_NAME          = 0  # app name, e.g. "Music", "Podcasts"
PLAYER_ATTR_PLAYBACK_INFO = 1  # "playState,playbackRate,elapsedTime"
PLAYER_ATTR_VOLUME        = 2

# Track attributes (ascending order required)
TRACK_ATTR_ARTIST   = 0
TRACK_ATTR_ALBUM    = 1
TRACK_ATTR_TITLE    = 2
TRACK_ATTR_DURATION = 3

CMD_PLAY     = 0
CMD_PAUSE    = 1
CMD_TOGGLE   = 2
CMD_NEXT     = 3
CMD_PREV     = 4
CMD_VOL_UP   = 5
CMD_VOL_DOWN = 6
# AMS spec: 7=AdvanceRepeat, 8=AdvanceShuffle, 9=SkipForward, 10=SkipBackward,
# 11=LikeTrack, 12=DislikeTrack, 13=BookmarkTrack. Seek по абсолютной позиции AMS
# НЕ умеет (бар прогресса остаётся индикатором). Skip±: интервал задаёт само
# приложение (Podcasts ~15-30с; Music обычно НЕ заявляет 9/10 для песен).
CMD_REPEAT    = 7
CMD_SHUFFLE   = 8
CMD_SKIP_FWD  = 9
CMD_SKIP_BACK = 10
CMD_LIKE      = 11
CMD_DISLIKE   = 12
CMD_BOOKMARK  = 13

# Человекочитаемые имена для лога supported-списка.
CMD_NAMES = {
    0: "Play", 1: "Pause", 2: "Toggle", 3: "Next", 4: "Prev",
    5: "VolUp", 6: "VolDown", 7: "Repeat", 8: "Shuffle",
    9: "SkipFwd", 10: "SkipBack", 11: "Like", 12: "Dislike", 13: "Bookmark",
}


class MediaState:
    app_name = ""
    title    = ""
    artist   = ""
    album    = ""
    duration = 0.0
    volume   = 0.0
    playing  = False
    _elapsed = 0.0
    _rate    = 1.0
    _ts      = 0.0

    @property
    def position(self):
        # живой прогресс: экстраполяция от снимка AMS (elapsed + прошедшее*rate)
        if not self.playing or self._rate <= 0:
            base = self._elapsed
        else:
            base = self._elapsed + (time.monotonic() - self._ts) * self._rate
        if self.duration:
            base = min(base, self.duration)
        return max(0.0, base)

    @position.setter
    def position(self, v):
        # совместимость: присвоение position = снимок elapsed (живой бар продолжит экстраполяцию)
        try:
            self._elapsed = float(v)
        except (TypeError, ValueError):
            self._elapsed = 0.0
        self._ts = time.monotonic()

    def __repr__(self):
        st = "▶" if self.playing else "⏸"
        return (f"{st} {self.title} — {self.artist} "
                f"[{self.position:.0f}/{self.duration:.0f}s] vol={self.volume:.0%}")


class AMSClient:
    def __init__(self, state: MediaState, on_update=None, on_commands=None):
        self.state = state
        self.on_update = on_update
        self.on_commands = on_commands        # колбэк: set(int) поддерживаемых команд
        self.supported = set()                # текущий supported-список (меняется с приложением)
        self._remote_cmd_char = None
        self._client = None

    async def setup(self, connection):
        self._client = Client(connection)
        connection.gatt_client = self._client  # route GATT PDUs to this client
        logger.info("AMS: discovering services on %s", connection.peer_address)

        await self._client.discover_service(AMS_SERVICE_UUID)
        services = self._client.get_services_by_uuid(AMS_SERVICE_UUID)

        if not services:
            logger.warning("AMS service not found")
            return False

        svc = services[0]
        await svc.discover_characteristics()

        chars = {c.uuid: c for c in svc.characteristics}
        logger.info("AMS: found characteristics: %s", [str(u) for u in chars.keys()])
        remote_cmd = chars.get(AMS_REMOTE_COMMAND_UUID)
        entity_upd = chars.get(AMS_ENTITY_UPDATE_UUID)

        if not remote_cmd or not entity_upd:
            logger.error("AMS: missing characteristics (found: %s)", list(chars.keys()))
            logger.error("AMS: looking for remote_cmd=%s entity_upd=%s",
                         AMS_REMOTE_COMMAND_UUID, AMS_ENTITY_UPDATE_UUID)
            return False

        self._remote_cmd_char = remote_cmd

        # Subscribe to RemoteCommand notifications: iPhone NOTIFIES the array of
        # currently-supported RemoteCommandIDs (меняется при смене приложения/состояния).
        # Тот же характеристик мы используем для записи команд — это нормально по AMS spec.
        try:
            await remote_cmd.subscribe(self._handle_remote_command_update)
            logger.info("AMS: subscribed to RemoteCommand (supported-commands list)")
        except Exception as e:
            logger.warning("AMS: RemoteCommand subscribe failed: %s", e)

        # Subscribe to EntityUpdate notifications
        await entity_upd.subscribe(self._handle_entity_update)
        logger.info("AMS: subscribed to EntityUpdate notifications")

        # Tell iPhone which entities/attributes we want
        await self._subscribe_entities(entity_upd)

        logger.info("AMS: ready")
        return True

    async def _subscribe_entities(self, entity_upd_char):
        # Attribute IDs must be in ascending order per AMS spec
        subscriptions = [
            bytes([ENTITY_TRACK,  TRACK_ATTR_ARTIST, TRACK_ATTR_ALBUM, TRACK_ATTR_TITLE, TRACK_ATTR_DURATION]),
            bytes([ENTITY_PLAYER, PLAYER_ATTR_NAME, PLAYER_ATTR_PLAYBACK_INFO, PLAYER_ATTR_VOLUME]),
        ]
        for sub in subscriptions:
            try:
                await entity_upd_char.write_value(sub, with_response=True)
                logger.info("AMS: entity subscription write OK: %s", sub.hex())
            except Exception as e:
                logger.warning("AMS entity subscribe error: %s", e)

    def _handle_entity_update(self, value):
        logger.info("AMS raw notification: %s", value.hex() if value else "empty")
        if len(value) < 3:
            return
        entity_id, attr_id = value[0], value[1]
        data = value[3:].decode("utf-8", errors="replace")

        if entity_id == ENTITY_TRACK:
            if attr_id == TRACK_ATTR_TITLE:
                self.state.title = data
            elif attr_id == TRACK_ATTR_ARTIST:
                self.state.artist = data
            elif attr_id == TRACK_ATTR_ALBUM:
                self.state.album = data
            elif attr_id == TRACK_ATTR_DURATION:
                try:
                    self.state.duration = float(data) if data.strip() else 0.0
                except ValueError:
                    pass
        elif entity_id == ENTITY_PLAYER:
            if attr_id == PLAYER_ATTR_NAME:
                self.state.app_name = data
                logger.info("AMS player: %s", data)
            elif attr_id == PLAYER_ATTR_PLAYBACK_INFO:
                # Format: "playState,playbackRate,elapsedTime"
                parts = data.split(",")
                if parts:
                    self.state.playing = (parts[0].strip() == "1")
                try:
                    self.state._rate = float(parts[1].strip()) if len(parts) >= 2 and parts[1].strip() else 1.0
                except ValueError:
                    self.state._rate = 1.0
                if len(parts) >= 3:
                    try:
                        self.state._elapsed = float(parts[2].strip()) if parts[2].strip() else 0.0
                        self.state._ts = time.monotonic()
                    except ValueError:
                        pass
            elif attr_id == PLAYER_ATTR_VOLUME:
                try:
                    self.state.volume = float(data)
                except ValueError:
                    pass

        logger.info("State: %s", self.state)
        if self.on_update:
            self.on_update(self.state)

    def _handle_remote_command_update(self, value):
        """Notify на RemoteCommand = массив байт, каждый = поддерживаемый RemoteCommandID.
        Меняется при смене активного приложения/состояния (Music vs Podcasts и т.п.).
        Источник истины «какие кнопки реально работают сейчас»."""
        cmds = set(value) if value else set()
        if cmds == self.supported:
            return
        self.supported = cmds
        names = [CMD_NAMES.get(c, str(c)) for c in sorted(cmds)]
        logger.info("AMS: supported commands -> %s", names)
        if self.on_commands:
            try:
                self.on_commands(set(cmds))
            except Exception as e:
                logger.warning("on_commands callback error: %s", e)

    async def send_command(self, cmd_id: int):
        if not self._remote_cmd_char:
            logger.warning("AMS: not connected")
            return
        if self.supported and cmd_id not in self.supported:
            logger.info("AMS: command %s not supported by current app — skip",
                        CMD_NAMES.get(cmd_id, cmd_id))
            return
        try:
            await self._remote_cmd_char.write_value(bytes([cmd_id]), with_response=True)
            logger.info("AMS: command 0x%02x sent OK", cmd_id)
        except Exception as e:
            logger.error("AMS send_command error: %s", e)

    async def toggle(self):    await self.send_command(CMD_TOGGLE)
    async def next(self):      await self.send_command(CMD_NEXT)
    async def prev(self):      await self.send_command(CMD_PREV)
    async def vol_up(self):    await self.send_command(CMD_VOL_UP)
    async def vol_down(self):  await self.send_command(CMD_VOL_DOWN)
    async def skip_fwd(self):  await self.send_command(CMD_SKIP_FWD)
    async def skip_back(self): await self.send_command(CMD_SKIP_BACK)
    async def like(self):      await self.send_command(CMD_LIKE)
    async def dislike(self):   await self.send_command(CMD_DISLIKE)
