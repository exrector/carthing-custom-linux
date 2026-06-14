import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field

from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.gatt_client import Client

logger = logging.getLogger(__name__)

ANCS_SERVICE_UUID = UUID("7905F431-B5CE-4E99-A40F-4B1E122D00D0")
ANCS_NOTIFICATION_SOURCE_UUID = UUID("9FBF120D-6301-42D9-8C58-25E699A21DBD")
ANCS_CONTROL_POINT_UUID = UUID("69D1D8F3-45E1-49A8-9821-9BBDFDAAD9D9")
ANCS_DATA_SOURCE_UUID = UUID("22EAC6E9-24D6-4BB5-BE44-B36ACE7C7BFB")

EVENT_ADDED = 0
EVENT_MODIFIED = 1
EVENT_REMOVED = 2

COMMAND_GET_NOTIFICATION_ATTRIBUTES = 0x00
COMMAND_PERFORM_NOTIFICATION_ACTION = 0x02

FLAG_SILENT = 1 << 0
FLAG_IMPORTANT = 1 << 1
FLAG_PREEXISTING = 1 << 2
FLAG_POSITIVE_ACTION = 1 << 3
FLAG_NEGATIVE_ACTION = 1 << 4

ACTION_POSITIVE = 0x00
ACTION_NEGATIVE = 0x01

ATTRIBUTE_APP_IDENTIFIER = 0
ATTRIBUTE_TITLE = 1
ATTRIBUTE_SUBTITLE = 2
ATTRIBUTE_MESSAGE = 3
ATTRIBUTE_MESSAGE_SIZE = 4
ATTRIBUTE_DATE = 5
ATTRIBUTE_POSITIVE_ACTION_LABEL = 6
ATTRIBUTE_NEGATIVE_ACTION_LABEL = 7

_EXPECTED_ATTRIBUTE_IDS = {
    ATTRIBUTE_APP_IDENTIFIER,
    ATTRIBUTE_TITLE,
    ATTRIBUTE_MESSAGE,
}

_CATEGORY_NAMES = {
    0: "Other",
    1: "Incoming Call",
    2: "Missed Call",
    3: "Voicemail",
    4: "Social",
    5: "Schedule",
    6: "Email",
    7: "News",
    8: "Health",
    9: "Business",
    10: "Location",
    11: "Entertainment",
    12: "Active Call",
}

_APP_NAME_OVERRIDES = {
    "com.apple.MobileSMS": "Messages",
    "com.apple.mobilephone": "Phone",
    "com.apple.mobilemail": "Mail",
    "com.apple.mobilecal": "Calendar",
    "com.apple.Preferences": "Settings",
    "com.apple.reminders": "Reminders",
}

_FLAG_NAMES = (
    (FLAG_SILENT, "silent"),
    (FLAG_IMPORTANT, "important"),
    (FLAG_PREEXISTING, "preexisting"),
    (FLAG_POSITIVE_ACTION, "positive-action"),
    (FLAG_NEGATIVE_ACTION, "negative-action"),
)


@dataclass
class NotificationState:
    uid: int
    event_id: int
    event_flags: int
    category_id: int
    category_count: int
    app_identifier: str = ""
    title: str = ""
    subtitle: str = ""
    message: str = ""
    message_size: str = ""
    date: str = ""
    positive_action_label: str = ""
    negative_action_label: str = ""
    received_monotonic: float = field(default_factory=time.monotonic)

    @property
    def category_name(self) -> str:
        return _CATEGORY_NAMES.get(self.category_id, "Notification")

    @property
    def app_name(self) -> str:
        if self.app_identifier in _APP_NAME_OVERRIDES:
            return _APP_NAME_OVERRIDES[self.app_identifier]
        if not self.app_identifier:
            return self.category_name

        leaf = self.app_identifier.split(".")[-1].replace("-", " ").replace("_", " ").strip()
        return leaf.title() if leaf else self.category_name

    @property
    def headline(self) -> str:
        return self.title or self.subtitle or self.message or self.category_name

    @property
    def body(self) -> str:
        if self.message and self.message != self.title:
            return self.message
        return self.subtitle

    @property
    def date_display(self) -> str:
        if len(self.date) == 15 and self.date[8] == "T":
            return f"{self.date[0:4]}-{self.date[4:6]}-{self.date[6:8]} {self.date[9:11]}:{self.date[11:13]}:{self.date[13:15]}"
        return self.date

    @property
    def is_silent(self) -> bool:
        return bool(self.event_flags & FLAG_SILENT)

    @property
    def is_important(self) -> bool:
        return bool(self.event_flags & FLAG_IMPORTANT)

    @property
    def is_preexisting(self) -> bool:
        return bool(self.event_flags & FLAG_PREEXISTING)

    @property
    def has_positive_action(self) -> bool:
        return bool(self.event_flags & FLAG_POSITIVE_ACTION)

    @property
    def has_negative_action(self) -> bool:
        return bool(self.event_flags & FLAG_NEGATIVE_ACTION)

    @property
    def has_actions(self) -> bool:
        return self.has_positive_action or self.has_negative_action

    @property
    def flag_names(self) -> list[str]:
        return [name for bit, name in _FLAG_NAMES if self.event_flags & bit]

    @property
    def action_hint(self) -> str:
        parts = []
        if self.has_positive_action:
            parts.append(f"Press:{self.positive_action_label or 'Positive'}")
        if self.has_negative_action:
            parts.append(f"Back:{self.negative_action_label or 'Negative'}")
        return " | ".join(parts)


class ANCSClient:
    def __init__(self, on_notification=None, on_removed=None):
        self.on_notification = on_notification
        self.on_removed = on_removed
        self._client = None
        self._control_point_char = None
        self._queue = deque()
        self._queued_uids = set()
        self._pending_uid = None
        self._pending_buffer = bytearray()
        self._notifications_by_uid: dict[int, NotificationState] = {}
        self._draining = False

    async def setup(self, connection):
        self._client = getattr(connection, "gatt_client", None)
        if self._client is None:
            self._client = Client(connection)
            connection.gatt_client = self._client
        logger.info(
            "ANCS: using client id=%s on %s",
            hex(id(self._client)),
            connection.peer_address,
        )

        logger.info("ANCS: discovering services on %s", connection.peer_address)
        await self._client.discover_service(ANCS_SERVICE_UUID)
        services = self._client.get_services_by_uuid(ANCS_SERVICE_UUID)
        if not services:
            logger.warning("ANCS service not found")
            return False

        service = services[0]
        await service.discover_characteristics()
        chars = {char.uuid: char for char in service.characteristics}

        notification_source = chars.get(ANCS_NOTIFICATION_SOURCE_UUID)
        control_point = chars.get(ANCS_CONTROL_POINT_UUID)
        data_source = chars.get(ANCS_DATA_SOURCE_UUID)
        if not notification_source or not control_point or not data_source:
            logger.error("ANCS: missing characteristics (found: %s)", list(chars.keys()))
            return False

        self._control_point_char = control_point
        await data_source.subscribe(self._handle_data_source)
        await notification_source.subscribe(self._handle_notification_source)
        logger.info(
            "ANCS: subscribed data=0x%04X source=0x%04X client=%s handles=%s",
            data_source.handle,
            notification_source.handle,
            hex(id(self._client)),
            [f"0x{handle:04X}" for handle in sorted(self._client.notification_subscribers)],
        )
        return True

    def is_idle(self) -> bool:
        return self._pending_uid is None and not self._queue and not self._draining

    def _handle_notification_source(self, value):
        if len(value) < 8:
            logger.warning("ANCS notification source payload too short: %s", value.hex())
            return

        event_id = value[0]
        event_flags = value[1]
        category_id = value[2]
        category_count = value[3]
        uid = int.from_bytes(value[4:8], "little")

        logger.info(
            "ANCS source: event=%d category=%d count=%d uid=%d flags=0x%02x (%s)",
            event_id,
            category_id,
            category_count,
            uid,
            event_flags,
            ", ".join(name for name in NotificationState(
                uid=uid,
                event_id=event_id,
                event_flags=event_flags,
                category_id=category_id,
                category_count=category_count,
            ).flag_names) or "none",
        )

        if event_id == EVENT_REMOVED:
            self._notifications_by_uid.pop(uid, None)
            if self._pending_uid == uid:
                self._pending_uid = None
                self._pending_buffer.clear()
            self._queued_uids.discard(uid)
            self._queue = deque(queued_uid for queued_uid in self._queue if queued_uid != uid)
            if self.on_removed:
                self.on_removed(uid)
            return

        notification = NotificationState(
            uid=uid,
            event_id=event_id,
            event_flags=event_flags,
            category_id=category_id,
            category_count=category_count,
        )
        self._notifications_by_uid[uid] = notification
        if uid not in self._queued_uids and uid != self._pending_uid:
            self._queue.append(uid)
            self._queued_uids.add(uid)
        asyncio.create_task(self._drain_queue())

    def _handle_data_source(self, value):
        if self._pending_uid is None:
            logger.info("ANCS data source with no pending UID: %s", value.hex())
            return

        self._pending_buffer.extend(value)
        parsed = self._try_parse_pending_attributes()
        if parsed is None:
            return

        notification = self._notifications_by_uid.get(self._pending_uid)
        if notification is None:
            notification = NotificationState(
                uid=self._pending_uid,
                event_id=EVENT_ADDED,
                event_flags=0,
                category_id=0,
                category_count=0,
            )

        notification.app_identifier = parsed.get(ATTRIBUTE_APP_IDENTIFIER, "")
        notification.title = parsed.get(ATTRIBUTE_TITLE, "")
        notification.subtitle = parsed.get(ATTRIBUTE_SUBTITLE, "")
        notification.message = parsed.get(ATTRIBUTE_MESSAGE, "")
        notification.message_size = parsed.get(ATTRIBUTE_MESSAGE_SIZE, "")
        notification.date = parsed.get(ATTRIBUTE_DATE, "")
        notification.positive_action_label = parsed.get(ATTRIBUTE_POSITIVE_ACTION_LABEL, "")
        notification.negative_action_label = parsed.get(ATTRIBUTE_NEGATIVE_ACTION_LABEL, "")
        self._notifications_by_uid[notification.uid] = notification

        logger.info(
            "ANCS notification ready: app=%s app_id=%s title=%r message=%r flags=%s date=%s actions=%s",
            notification.app_name,
            notification.app_identifier or "-",
            notification.headline,
            notification.body,
            ",".join(notification.flag_names) or "none",
            notification.date_display or "-",
            notification.action_hint or "-",
        )

        self._pending_uid = None
        self._pending_buffer.clear()

        if self.on_notification:
            self.on_notification(notification)

        asyncio.create_task(self._drain_queue())

    async def _drain_queue(self):
        if self._draining:
            return

        self._draining = True
        try:
            while self._pending_uid is None and self._queue:
                uid = self._queue.popleft()
                self._queued_uids.discard(uid)
                try:
                    await self._request_notification_attributes(uid)
                except Exception as exc:
                    logger.warning("ANCS request failed for uid=%d: %s", uid, exc)
                    self._pending_uid = None
                    self._pending_buffer.clear()
        finally:
            self._draining = False

    async def _request_notification_attributes(self, uid: int):
        if self._control_point_char is None:
            raise RuntimeError("ANCS control point unavailable")

        self._pending_uid = uid
        self._pending_buffer.clear()

        request = bytearray([COMMAND_GET_NOTIFICATION_ATTRIBUTES])
        request.extend(uid.to_bytes(4, "little"))
        request.append(ATTRIBUTE_APP_IDENTIFIER)
        request.append(ATTRIBUTE_TITLE)
        request.extend((64).to_bytes(2, "little"))
        request.append(ATTRIBUTE_SUBTITLE)
        request.extend((64).to_bytes(2, "little"))
        request.append(ATTRIBUTE_MESSAGE)
        request.extend((192).to_bytes(2, "little"))
        request.append(ATTRIBUTE_MESSAGE_SIZE)
        request.append(ATTRIBUTE_DATE)
        request.append(ATTRIBUTE_POSITIVE_ACTION_LABEL)
        request.extend((48).to_bytes(2, "little"))
        request.append(ATTRIBUTE_NEGATIVE_ACTION_LABEL)
        request.extend((48).to_bytes(2, "little"))

        logger.info("ANCS request attributes for uid=%d", uid)
        await self._control_point_char.write_value(bytes(request), with_response=True)

    async def perform_notification_action(self, uid: int, action_id: int):
        if self._control_point_char is None:
            raise RuntimeError("ANCS control point unavailable")
        if action_id not in (ACTION_POSITIVE, ACTION_NEGATIVE):
            raise ValueError(f"Unsupported ANCS action id: {action_id}")

        request = bytearray([COMMAND_PERFORM_NOTIFICATION_ACTION])
        request.extend(uid.to_bytes(4, "little"))
        request.append(action_id)

        logger.info(
            "ANCS perform action: uid=%d action=%s",
            uid,
            "positive" if action_id == ACTION_POSITIVE else "negative",
        )
        await self._control_point_char.write_value(bytes(request), with_response=True)

    async def perform_positive_action(self, uid: int):
        await self.perform_notification_action(uid, ACTION_POSITIVE)

    async def perform_negative_action(self, uid: int):
        await self.perform_notification_action(uid, ACTION_NEGATIVE)

    def _try_parse_pending_attributes(self):
        if self._pending_uid is None:
            return None

        buffer = self._pending_buffer
        if len(buffer) < 5:
            return None
        if buffer[0] != 0x00:
            logger.warning("ANCS unexpected command id: 0x%02x", buffer[0])
            self._pending_uid = None
            self._pending_buffer.clear()
            return None

        uid = int.from_bytes(buffer[1:5], "little")
        if uid != self._pending_uid:
            logger.warning("ANCS UID mismatch: pending=%d payload=%d", self._pending_uid, uid)
            return None

        offset = 5
        attrs: dict[int, str] = {}
        while offset < len(buffer):
            if offset + 3 > len(buffer):
                return None
            attr_id = buffer[offset]
            attr_len = int.from_bytes(buffer[offset + 1:offset + 3], "little")
            offset += 3
            if offset + attr_len > len(buffer):
                return None
            attrs[attr_id] = buffer[offset:offset + attr_len].decode("utf-8", errors="replace")
            offset += attr_len

        if not _EXPECTED_ATTRIBUTE_IDS.issubset(attrs.keys()):
            return None
        return attrs
