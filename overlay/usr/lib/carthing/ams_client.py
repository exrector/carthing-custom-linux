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


class MediaState:
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
    def __init__(self, state: MediaState, on_update=None):
        self.state = state
        self.on_update = on_update
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
            elif attr_id == TRACK_ATTR_DURATION:
                try:
                    self.state.duration = float(data)
                except ValueError:
                    pass
        elif entity_id == ENTITY_PLAYER:
            if attr_id == PLAYER_ATTR_NAME:
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

    async def send_command(self, cmd_id: int):
        if not self._remote_cmd_char:
            logger.warning("AMS: not connected")
            return
        try:
            await self._remote_cmd_char.write_value(bytes([cmd_id]), with_response=True)
            logger.info("AMS: command 0x%02x sent OK", cmd_id)
        except Exception as e:
            logger.error("AMS send_command error: %s", e)

    async def toggle(self):   await self.send_command(CMD_TOGGLE)
    async def next(self):     await self.send_command(CMD_NEXT)
    async def prev(self):     await self.send_command(CMD_PREV)
    async def vol_up(self):   await self.send_command(CMD_VOL_UP)
    async def vol_down(self): await self.send_command(CMD_VOL_DOWN)
