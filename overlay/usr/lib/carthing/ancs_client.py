"""ANCS (Apple Notification Center Service) GATT client.

Mirrors the AMS pattern: discover, subscribe Notification Source for
high-level notification events, optionally request detailed attributes
via Control Point and reassemble responses from Data Source.
"""

import logging
import struct
from collections import deque
from dataclasses import dataclass, field

from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.gatt_client import Client

logger = logging.getLogger(__name__)

ANCS_SERVICE_UUID             = UUID("7905F431-B5CE-4E99-A40F-4B1E122D00D0")
ANCS_NOTIFICATION_SOURCE_UUID = UUID("9FBF120D-6301-42D9-8C58-25E699A21DBD")
ANCS_CONTROL_POINT_UUID       = UUID("69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9")
ANCS_DATA_SOURCE_UUID         = UUID("22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB")

EVT_ADDED    = 0
EVT_MODIFIED = 1
EVT_REMOVED  = 2

FLAG_SILENT          = 0x01
FLAG_IMPORTANT       = 0x02
FLAG_PREEXISTING     = 0x04
FLAG_POSITIVE_ACTION = 0x08
FLAG_NEGATIVE_ACTION = 0x10

CATEGORY_NAMES = {
    0:  "Other",
    1:  "IncomingCall",
    2:  "MissedCall",
    3:  "Voicemail",
    4:  "Social",
    5:  "Schedule",
    6:  "Email",
    7:  "News",
    8:  "HealthAndFitness",
    9:  "BusinessAndFinance",
    10: "Location",
    11: "Entertainment",
}

CMD_GET_NOTIFICATION_ATTRIBUTES = 0
CMD_GET_APP_ATTRIBUTES          = 1
CMD_PERFORM_NOTIFICATION_ACTION = 2

ATTR_APP_IDENTIFIER         = 0
ATTR_TITLE                  = 1
ATTR_SUBTITLE               = 2
ATTR_MESSAGE                = 3
ATTR_MESSAGE_SIZE           = 4
ATTR_DATE                   = 5
ATTR_POSITIVE_ACTION_LABEL  = 6
ATTR_NEGATIVE_ACTION_LABEL  = 7

DEFAULT_ATTRS_WITH_LEN = (
    (ATTR_TITLE,    255),
    (ATTR_SUBTITLE, 255),
    (ATTR_MESSAGE,  255),
)
DEFAULT_ATTRS_NO_LEN = (
    ATTR_APP_IDENTIFIER,
    ATTR_DATE,
)


@dataclass
class Notification:
    uid: int
    event_id: int
    event_flags: int
    category_id: int
    category_count: int
    app_id: str = ""
    title: str = ""
    subtitle: str = ""
    message: str = ""
    date: str = ""

    @property
    def category(self) -> str:
        return CATEGORY_NAMES.get(self.category_id, f"Unknown({self.category_id})")

    @property
    def silent(self) -> bool:
        return bool(self.event_flags & FLAG_SILENT)

    @property
    def important(self) -> bool:
        return bool(self.event_flags & FLAG_IMPORTANT)

    def __repr__(self) -> str:
        ev = {EVT_ADDED: "+", EVT_MODIFIED: "~", EVT_REMOVED: "-"}.get(self.event_id, "?")
        head = f"{ev}#{self.uid} [{self.category}]"
        if self.title or self.message:
            return f"{head} {self.app_id}: {self.title} — {self.message}"
        return head


@dataclass
class _PendingFetch:
    uid: int
    expected_attrs: int
    buf: bytearray = field(default_factory=bytearray)


class ANCSClient:
    """Subscribes to ANCS and surfaces decoded Notification objects.

    Callbacks:
        on_event:       called for every Notification Source event (preview only)
        on_fetched:     called when full attributes have been reassembled
        on_removed:     called on Removed events
    """

    def __init__(self, on_event=None, on_fetched=None, on_removed=None,
                 fetch_details: bool = True, ignore_preexisting: bool = True):
        self.on_event = on_event
        self.on_fetched = on_fetched
        self.on_removed = on_removed
        self.fetch_details = fetch_details
        self.ignore_preexisting = ignore_preexisting

        self._client = None
        self._control_point = None
        self._notification_source = None
        self._data_source = None

        self._pending: _PendingFetch | None = None
        self._fetch_queue: deque[int] = deque()
        self._known: dict[int, Notification] = {}

    async def setup(self, connection) -> bool:
        client = connection.gatt_client
        if client is None:
            client = Client(connection)
            connection.gatt_client = client
        self._client = client

        logger.info("ANCS: discovering services on %s", connection.peer_address)
        await client.discover_service(ANCS_SERVICE_UUID)
        services = client.get_services_by_uuid(ANCS_SERVICE_UUID)
        if not services:
            logger.warning("ANCS service not found")
            return False

        svc = services[0]
        await svc.discover_characteristics()
        chars = {c.uuid: c for c in svc.characteristics}
        logger.info("ANCS: found characteristics: %s", [str(u) for u in chars.keys()])

        ns = chars.get(ANCS_NOTIFICATION_SOURCE_UUID)
        cp = chars.get(ANCS_CONTROL_POINT_UUID)
        ds = chars.get(ANCS_DATA_SOURCE_UUID)

        if ns is None:
            logger.error("ANCS: Notification Source missing")
            return False

        self._notification_source = ns
        self._control_point = cp
        self._data_source = ds

        if ds is not None:
            await ds.subscribe(self._handle_data_source)
            logger.info("ANCS: subscribed to Data Source")

        await ns.subscribe(self._handle_notification_source)
        logger.info("ANCS: subscribed to Notification Source — ready")
        return True

    def _handle_notification_source(self, value: bytes):
        if len(value) < 8:
            logger.warning("ANCS: short NS packet %s", value.hex())
            return
        event_id, event_flags, category_id, category_count = value[0], value[1], value[2], value[3]
        uid = struct.unpack("<I", value[4:8])[0]

        if event_id == EVT_REMOVED:
            self._known.pop(uid, None)
            logger.info("ANCS: removed #%d", uid)
            if self.on_removed:
                try:
                    self.on_removed(uid)
                except Exception as exc:
                    logger.exception("ANCS on_removed callback failed: %s", exc)
            return

        if event_id == EVT_ADDED and (event_flags & FLAG_PREEXISTING) and self.ignore_preexisting:
            return

        notif = Notification(uid, event_id, event_flags, category_id, category_count)
        self._known[uid] = notif
        logger.info("ANCS: %s", notif)
        if self.on_event:
            try:
                self.on_event(notif)
            except Exception as exc:
                logger.exception("ANCS on_event callback failed: %s", exc)

        if self.fetch_details and self._control_point and self._data_source:
            self._fetch_queue.append(uid)
            if self._pending is None:
                self._kick_fetch()

    def _kick_fetch(self):
        if self._pending is not None or not self._fetch_queue:
            return
        uid = self._fetch_queue.popleft()
        expected = len(DEFAULT_ATTRS_NO_LEN) + len(DEFAULT_ATTRS_WITH_LEN)
        self._pending = _PendingFetch(uid, expected)
        request = bytearray([CMD_GET_NOTIFICATION_ATTRIBUTES])
        request += struct.pack("<I", uid)
        for attr_id in DEFAULT_ATTRS_NO_LEN:
            request += bytes([attr_id])
        for attr_id, max_len in DEFAULT_ATTRS_WITH_LEN:
            request += bytes([attr_id])
            request += struct.pack("<H", max_len)

        import asyncio
        asyncio.ensure_future(self._send_request(bytes(request), uid))

    async def _send_request(self, payload: bytes, uid: int):
        try:
            await self._control_point.write_value(payload, with_response=True)
            logger.info("ANCS: requested attrs for #%d (%d bytes)", uid, len(payload))
        except Exception as exc:
            logger.warning("ANCS: control point write failed for #%d: %s", uid, exc)
            self._pending = None
            self._kick_fetch()

    def _handle_data_source(self, value: bytes):
        if self._pending is None:
            logger.warning("ANCS: unexpected DS chunk %s", value.hex())
            return
        self._pending.buf.extend(value)
        parsed = self._try_parse_pending()
        if parsed is not None:
            uid, attrs = parsed
            self._apply_attrs(uid, attrs)
            self._pending = None
            self._kick_fetch()

    def _try_parse_pending(self):
        buf = self._pending.buf
        if len(buf) < 5:
            return None
        cmd = buf[0]
        if cmd != CMD_GET_NOTIFICATION_ATTRIBUTES:
            logger.warning("ANCS: unexpected DS cmd 0x%02x", cmd)
            return None
        uid = struct.unpack("<I", bytes(buf[1:5]))[0]
        pos = 5
        attrs: dict[int, str] = {}
        expected = self._pending.expected_attrs
        while len(attrs) < expected:
            if pos + 3 > len(buf):
                return None
            attr_id = buf[pos]
            length = struct.unpack("<H", bytes(buf[pos + 1:pos + 3]))[0]
            pos += 3
            if pos + length > len(buf):
                return None
            data = bytes(buf[pos:pos + length]).decode("utf-8", errors="replace")
            pos += length
            attrs[attr_id] = data
        return uid, attrs

    def _apply_attrs(self, uid: int, attrs: dict):
        notif = self._known.get(uid)
        if notif is None:
            logger.info("ANCS: attrs for unknown uid #%d, discarding", uid)
            return
        notif.app_id   = attrs.get(ATTR_APP_IDENTIFIER, notif.app_id)
        notif.title    = attrs.get(ATTR_TITLE, notif.title)
        notif.subtitle = attrs.get(ATTR_SUBTITLE, notif.subtitle)
        notif.message  = attrs.get(ATTR_MESSAGE, notif.message)
        notif.date     = attrs.get(ATTR_DATE, notif.date)
        logger.info("ANCS detail: %s", notif)
        if self.on_fetched:
            try:
                self.on_fetched(notif)
            except Exception as exc:
                logger.exception("ANCS on_fetched callback failed: %s", exc)
