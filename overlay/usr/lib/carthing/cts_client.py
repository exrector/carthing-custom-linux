"""CTS (Current Time Service) GATT client.

Reads the iPhone's current time once after encryption is established
and subscribes for ticks/edits if the characteristic supports notify.
The Car Thing has no battery-backed RTC, so this is the canonical
time source for the running session.
"""

import logging
import struct
import time
from dataclasses import dataclass

from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.gatt_client import Client

logger = logging.getLogger(__name__)

CTS_SERVICE_UUID       = UUID.from_16_bits(0x1805)
CURRENT_TIME_UUID      = UUID.from_16_bits(0x2A2B)
LOCAL_TIME_INFO_UUID   = UUID.from_16_bits(0x2A0F)


@dataclass
class CurrentTime:
    year: int
    month: int
    day: int
    hour: int
    minute: int
    second: int
    weekday: int
    fractions256: int
    adjust_reason: int
    timezone_quarters: int | None = None  # signed
    dst_offset_quarters: int | None = None

    def __repr__(self) -> str:
        return (
            f"{self.year:04d}-{self.month:02d}-{self.day:02d} "
            f"{self.hour:02d}:{self.minute:02d}:{self.second:02d}"
        )

    def to_unix(self) -> float:
        import calendar
        try:
            ts = calendar.timegm((self.year, self.month, self.day,
                                  self.hour, self.minute, self.second, 0, 0, 0))
        except (ValueError, OverflowError):
            return 0.0
        if self.timezone_quarters is not None:
            ts -= self.timezone_quarters * 15 * 60
        if self.dst_offset_quarters is not None:
            ts -= self.dst_offset_quarters * 15 * 60
        return ts + self.fractions256 / 256.0


class CTSClient:
    """Reads current time + optionally subscribes for updates."""

    def __init__(self, on_update=None, sync_system_clock: bool = True):
        self.on_update = on_update
        self.sync_system_clock = sync_system_clock
        self._client = None
        self._current_time_char = None
        self._local_info_char = None
        self._last: CurrentTime | None = None

    async def setup(self, connection) -> bool:
        client = connection.gatt_client
        if client is None:
            client = Client(connection)
            connection.gatt_client = client
        self._client = client

        logger.info("CTS: discovering service on %s", connection.peer_address)
        await client.discover_service(CTS_SERVICE_UUID)
        services = client.get_services_by_uuid(CTS_SERVICE_UUID)
        if not services:
            logger.warning("CTS service not found")
            return False

        svc = services[0]
        await svc.discover_characteristics()
        chars = {c.uuid: c for c in svc.characteristics}
        logger.info("CTS: characteristics: %s", [str(u) for u in chars.keys()])

        ct = chars.get(CURRENT_TIME_UUID)
        if ct is None:
            logger.error("CTS: Current Time characteristic missing")
            return False
        self._current_time_char = ct
        self._local_info_char = chars.get(LOCAL_TIME_INFO_UUID)

        await self._read_once()

        try:
            await ct.subscribe(self._handle_current_time)
            logger.info("CTS: subscribed for time updates")
        except Exception as exc:
            logger.info("CTS: notify not supported (%s) — read-once mode", exc)

        return True

    async def _read_once(self):
        try:
            ct_bytes = await self._current_time_char.read_value()
            tz_quarters = None
            dst_quarters = None
            if self._local_info_char is not None:
                try:
                    li = await self._local_info_char.read_value()
                    if li and len(li) >= 2:
                        tz_quarters = struct.unpack("<b", li[0:1])[0]
                        dst_quarters = li[1]
                except Exception as exc:
                    logger.info("CTS: Local Time Info read failed: %s", exc)
            self._parse_and_dispatch(bytes(ct_bytes), tz_quarters, dst_quarters)
        except Exception as exc:
            logger.warning("CTS: initial read failed: %s", exc)

    def _handle_current_time(self, value: bytes):
        self._parse_and_dispatch(bytes(value), None, None)

    def _parse_and_dispatch(self, raw: bytes, tz_quarters, dst_quarters):
        if len(raw) < 10:
            logger.warning("CTS: short Current Time %s", raw.hex())
            return
        year = struct.unpack("<H", raw[0:2])[0]
        month, day, hour, minute, second = raw[2], raw[3], raw[4], raw[5], raw[6]
        weekday = raw[7]
        fractions = raw[8]
        adjust = raw[9]

        previous_tz = self._last.timezone_quarters if self._last else None
        previous_dst = self._last.dst_offset_quarters if self._last else None
        current = CurrentTime(
            year=year, month=month, day=day,
            hour=hour, minute=minute, second=second,
            weekday=weekday, fractions256=fractions, adjust_reason=adjust,
            timezone_quarters=tz_quarters if tz_quarters is not None else previous_tz,
            dst_offset_quarters=dst_quarters if dst_quarters is not None else previous_dst,
        )
        self._last = current
        logger.info("CTS: %s (adjust=0x%02x)", current, adjust)

        if self.sync_system_clock:
            self._sync_clock(current)

        if self.on_update:
            try:
                self.on_update(current)
            except Exception as exc:
                logger.exception("CTS on_update failed: %s", exc)

    def _sync_clock(self, ct: CurrentTime):
        ts = ct.to_unix()
        if ts <= 0:
            return
        try:
            import ctypes
            libc = ctypes.CDLL("libc.so.6", use_errno=True)
            class _Timeval(ctypes.Structure):
                _fields_ = [("tv_sec", ctypes.c_long), ("tv_usec", ctypes.c_long)]
            tv = _Timeval(int(ts), int((ts - int(ts)) * 1_000_000))
            rc = libc.settimeofday(ctypes.byref(tv), None)
            if rc != 0:
                err = ctypes.get_errno()
                logger.info("CTS: settimeofday rc=%d errno=%d", rc, err)
            else:
                logger.info("CTS: system clock set to %s", time.ctime(ts))
        except Exception as exc:
            logger.info("CTS: settimeofday unavailable (%s)", exc)

    @property
    def last(self) -> CurrentTime | None:
        return self._last
