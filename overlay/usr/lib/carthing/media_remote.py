"""Main runtime for the working Car Thing BLE media remote."""

import asyncio
import logging
import struct
import time
from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.device import AdvertisingData, AdvertisingType, Connection, Device, OwnAddressType
from bumble.gatt import Characteristic, Descriptor, Service
from bumble.smp import PairingConfig

from ams_client import AMSClient, MediaState
from ancs_client import ANCSClient, NotificationState
from ble_transport import init_ble
from drm_display import DRMDisplay
from input_handler import start as start_input

try:
    from now_playing_ui import NowPlayingUI
    _ui_import_error = None
except Exception as exc:
    NowPlayingUI = None
    _ui_import_error = exc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

state = MediaState()
ams: AMSClient | None = None
ancs: ANCSClient | None = None
ui: NowPlayingUI | None = None
_device: Device | None = None
_last_activity = time.monotonic()
_active_conn: Connection | None = None
_active_notification: NotificationState | None = None
_last_peer_address = None
_reconnect_fallback_task: asyncio.Task | None = None
_notification_clear_task: asyncio.Task | None = None
_ams_starting: set[int] = set()
_ancs_starting: set[int] = set()

GATT_SERVICE_UUID = UUID.from_16_bits(0x1801)
BATTERY_SERVICE_UUID = UUID.from_16_bits(0x180F)
HID_SERVICE_UUID = UUID.from_16_bits(0x1812)

BATTERY_LEVEL_UUID = UUID.from_16_bits(0x2A19)
HID_INFORMATION_UUID = UUID.from_16_bits(0x2A4A)
REPORT_MAP_UUID = UUID.from_16_bits(0x2A4B)
HID_CONTROL_POINT_UUID = UUID.from_16_bits(0x2A4C)
REPORT_UUID = UUID.from_16_bits(0x2A4D)
PROTOCOL_MODE_UUID = UUID.from_16_bits(0x2A4E)

CCCD_UUID = UUID.from_16_bits(0x2902)
REPORT_REFERENCE_UUID = UUID.from_16_bits(0x2908)

HID_REPORT_MAP = bytes(
    [
        0x05, 0x0C,
        0x09, 0x01,
        0xA1, 0x01,
        0x85, 0x01,
        0x15, 0x00,
        0x25, 0x01,
        0x75, 0x01,
        0x95, 0x05,
        0x09, 0xCD,
        0x09, 0xB5,
        0x09, 0xB6,
        0x09, 0xE9,
        0x09, 0xEA,
        0x81, 0x02,
        0x95, 0x03,
        0x81, 0x03,
        0xC0,
    ]
)
HID_INFORMATION = struct.pack("<HBB", 0x0111, 0x00, 0x03)


def install_hid_pairing_profile(device: Device):
    report_char = Characteristic(
        REPORT_UUID,
        Characteristic.READ | Characteristic.NOTIFY,
        Characteristic.READABLE,
        bytes([0x00]),
        descriptors=[
            Descriptor(CCCD_UUID, Descriptor.READABLE | Descriptor.WRITEABLE, bytes([0x00, 0x00])),
            Descriptor(REPORT_REFERENCE_UUID, Descriptor.READABLE, bytes([0x01, 0x01])),
        ],
    )

    device.add_service(
        Service(
            GATT_SERVICE_UUID,
            [],
        )
    )
    device.add_service(
        Service(
            BATTERY_SERVICE_UUID,
            [
                Characteristic(
                    BATTERY_LEVEL_UUID,
                    Characteristic.READ | Characteristic.NOTIFY,
                    Characteristic.READABLE,
                    bytes([100]),
                )
            ],
        )
    )
    device.add_service(
        Service(
            HID_SERVICE_UUID,
            [
                Characteristic(
                    HID_INFORMATION_UUID,
                    Characteristic.READ,
                    Characteristic.READABLE,
                    HID_INFORMATION,
                ),
                Characteristic(
                    REPORT_MAP_UUID,
                    Characteristic.READ,
                    Characteristic.READABLE,
                    HID_REPORT_MAP,
                ),
                Characteristic(
                    PROTOCOL_MODE_UUID,
                    Characteristic.READ | Characteristic.WRITE_WITHOUT_RESPONSE,
                    Characteristic.READABLE | Characteristic.WRITEABLE,
                    bytes([0x01]),
                ),
                report_char,
                Characteristic(
                    HID_CONTROL_POINT_UUID,
                    Characteristic.WRITE_WITHOUT_RESPONSE,
                    Characteristic.WRITEABLE,
                    bytes([0x00]),
                ),
            ],
        )
    )
    logger.info("HID pairing profile installed")


def on_state_update(s: MediaState):
    global _last_activity
    _last_activity = time.monotonic()
    logger.info(
        "State: %s %s — %s [%s/%ss] vol=%d%%",
        "▶" if s.playing else "⏸",
        s.title,
        s.artist,
        int(s.position),
        int(s.duration),
        int(s.volume * 100),
    )
    _render_ui()


def on_notification_update(notification: NotificationState):
    global _active_notification, _last_activity
    _last_activity = time.monotonic()
    _active_notification = notification
    logger.info(
        "ANCS display: app=%s title=%r message=%r",
        notification.app_name,
        notification.headline,
        notification.body,
    )
    _render_ui()
    _schedule_notification_clear(notification.uid)


def on_notification_removed(uid: int):
    global _active_notification
    if _active_notification and _active_notification.uid == uid:
        logger.info("ANCS remove active notification uid=%d", uid)
        _active_notification = None
        _cancel_notification_clear()
        _render_ui()


def _render_ui():
    if not ui:
        return
    try:
        if _active_notification:
            ui.render_notification(_active_notification, state)
        else:
            ui.render(state)
    except Exception as e:
        logger.error("UI render error: %s", e)


def _cancel_notification_clear():
    global _notification_clear_task
    if _notification_clear_task is not None:
        _notification_clear_task.cancel()
        _notification_clear_task = None


def _schedule_notification_clear(uid: int, delay: float = 8.0):
    global _notification_clear_task
    _cancel_notification_clear()

    async def clear_later():
        global _active_notification, _notification_clear_task
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if _active_notification and _active_notification.uid == uid:
            _active_notification = None
            _render_ui()
        _notification_clear_task = None

    _notification_clear_task = asyncio.create_task(clear_later())


async def on_connection(connection: Connection):
    global _last_activity, _last_peer_address, _reconnect_fallback_task
    _last_activity = time.monotonic()
    _last_peer_address = connection.peer_address
    if _reconnect_fallback_task is not None:
        _reconnect_fallback_task.cancel()
        _reconnect_fallback_task = None
    logger.info(
        "iPhone подключился: %s handle=%d encrypted=%s",
        connection.peer_address,
        connection.handle,
        connection.is_encrypted,
    )
    connection.on("pairing_start", lambda: logger.info("SMP: pairing started handle=%d", connection.handle))
    connection.on("pairing", lambda keys: on_pairing(connection, keys))
    connection.on("pairing_failure", lambda reason: logger.error("SMP: pairing failed handle=%d reason=%s", connection.handle, reason))
    connection.on("connection_encryption_change", lambda: on_connection_encryption_change(connection))
    connection.on("disconnection", lambda reason: asyncio.ensure_future(on_disconnection(connection, reason)))

    if connection.is_encrypted:
        await maybe_start_ancs(connection, "connected-encrypted")
        await maybe_start_ams(connection, "connected-encrypted")
    else:
        logger.info("Requesting pairing for handle=%d", connection.handle)
        connection.request_pairing()


def on_pairing(connection: Connection, keys):
    logger.info("SMP: bonding complete handle=%d keys=%s", connection.handle, keys)
    if _device:
        asyncio.create_task(refresh_accept_list(_device))
    if connection.is_encrypted:
        asyncio.create_task(maybe_start_ancs(connection, "pairing-complete"))
        asyncio.create_task(maybe_start_ams(connection, "pairing-complete"))


def on_connection_encryption_change(connection: Connection):
    logger.info(
        "Encryption change handle=%d encrypted=%s",
        connection.handle,
        connection.is_encrypted,
    )
    if connection.is_encrypted:
        asyncio.create_task(maybe_start_ancs(connection, "link-encrypted"))
        asyncio.create_task(maybe_start_ams(connection, "link-encrypted"))


async def maybe_start_ams(connection: Connection, reason: str):
    global ams, _active_conn
    if not connection.is_encrypted:
        logger.info("AMS wait for encryption: handle=%d reason=%s", connection.handle, reason)
        return
    if _active_conn is connection and ams is not None:
        return
    if connection.handle in _ams_starting:
        return

    _ams_starting.add(connection.handle)
    try:
        logger.info("AMS setup start: handle=%d reason=%s", connection.handle, reason)
        candidate = AMSClient(state, on_update=on_state_update)
        ok = await candidate.setup(connection)
        if ok:
            _active_conn = connection
            ams = candidate
            logger.info("AMS готов — жду метаданные")
        else:
            logger.warning("AMS не найден на этом устройстве")
    finally:
        _ams_starting.discard(connection.handle)


async def maybe_start_ancs(connection: Connection, reason: str):
    global ancs, _active_conn
    if not connection.is_encrypted:
        logger.info("ANCS wait for encryption: handle=%d reason=%s", connection.handle, reason)
        return
    if _active_conn is connection and ancs is not None:
        return
    if connection.handle in _ancs_starting:
        return

    _ancs_starting.add(connection.handle)
    try:
        logger.info("ANCS setup start: handle=%d reason=%s", connection.handle, reason)
        candidate = ANCSClient(
            on_notification=on_notification_update,
            on_removed=on_notification_removed,
        )
        ok = await candidate.setup(connection)
        if ok:
            _active_conn = connection
            ancs = candidate
            logger.info("ANCS готов — жду уведомления")
        else:
            logger.warning("ANCS не найден на этом устройстве")
    finally:
        _ancs_starting.discard(connection.handle)


async def on_disconnection(connection: Connection, reason: int):
    global ams, ancs, _active_conn, _active_notification
    logger.warning("Отключился: %s (reason 0x%02x)", connection.peer_address, reason)
    ams = None
    ancs = None
    _active_conn = None
    _active_notification = None
    _cancel_notification_clear()
    state.title = "Lost Contact"
    state.artist = "Awaiting Deep Space Relay"
    state.album = ""
    state.duration = 0.0
    state.position = 0.0
    state.playing = False
    _render_ui()
    try:
        await asyncio.sleep(0.3)
        if _device:
            await start_reconnect_advertising(_device, connection.peer_address)
    except Exception as e:
        logger.error("Re-advertise error: %s", e)


async def start_advertising(device: Device):
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, bytes([0x06])),
                (AdvertisingData.APPEARANCE, struct.pack("<H", 0x0180)),
                (
                    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    struct.pack("<H", 0x1812),
                ),
                (AdvertisingData.COMPLETE_LOCAL_NAME, b"CarThing"),
            ]
        )
    )
    await device.start_advertising(
        own_address_type=OwnAddressType.PUBLIC,
        auto_restart=True,
    )
    logger.info("Реклама запущена")


async def refresh_accept_list(device: Device):
    try:
        await device.refresh_filter_accept_list()
        logger.info("Filter accept list refreshed from bonded keys")
    except Exception as e:
        logger.warning("Filter accept list refresh failed: %s", e)


async def start_bonded_only_advertising(device: Device):
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, bytes([0x06])),
                (AdvertisingData.APPEARANCE, struct.pack("<H", 0x0180)),
                (
                    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    struct.pack("<H", 0x1812),
                ),
                (AdvertisingData.COMPLETE_LOCAL_NAME, b"CarThing"),
            ]
        )
    )
    await refresh_accept_list(device)
    await device.start_advertising(
        own_address_type=OwnAddressType.RESOLVABLE_OR_PUBLIC,
        auto_restart=True,
        advertising_filter_policy=0x03,
    )
    logger.info("Bonded-only HID advertising started")


async def start_reconnect_advertising(device: Device, target):
    global _reconnect_fallback_task
    if _reconnect_fallback_task is not None:
        _reconnect_fallback_task.cancel()
        _reconnect_fallback_task = None

    async def reconnect_sequence():
        try:
            logger.info("Directed reconnect advertising to bonded peer: %s", target)
            await device.start_advertising(
                advertising_type=AdvertisingType.DIRECTED_CONNECTABLE_HIGH_DUTY,
                target=target,
                own_address_type=OwnAddressType.RESOLVABLE_OR_PUBLIC,
                auto_restart=False,
            )
            await asyncio.sleep(1.6)
            if _device and len(_device.connections) > 0:
                return

            logger.info("Directed reconnect window ended -> bonded-only HID advertising")
            await start_bonded_only_advertising(device)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning("Directed reconnect advertising failed: %s", e)
        finally:
            global _reconnect_fallback_task
            _reconnect_fallback_task = None

    _reconnect_fallback_task = asyncio.create_task(reconnect_sequence())


async def gatt_ping(connection: Connection) -> bool:
    """Read GAP Device Name from the iPhone to detect zombie connections."""
    try:
        client = connection.gatt_client
        if client is None:
            return False

        gap_uuid = UUID.from_16_bits(0x1800)
        await client.discover_service(gap_uuid)
        services = client.get_services_by_uuid(gap_uuid)
        if not services:
            logger.info("PING: GAP service не найден (странно), но коннект отвечает")
            return True

        svc = services[0]
        await svc.discover_characteristics()
        for ch in svc.characteristics:
            if ch.uuid == UUID.from_16_bits(0x2A00):
                await asyncio.wait_for(ch.read_value(), timeout=8.0)
                return True
        return True
    except asyncio.TimeoutError:
        logger.warning("PING: TIMEOUT (коннект зомби)")
        return False
    except Exception as e:
        logger.warning("PING: error %s", e)
        return False


async def heartbeat():
    last_ping = time.monotonic()
    while True:
        await asyncio.sleep(10)
        try:
            n_conn = len(_device.connections) if _device else 0
            silent_for = int(time.monotonic() - _last_activity)
            adv = getattr(_device, "is_advertising", None)
            logger.info("HB: connections=%d advertising=%s silent=%ds", n_conn, adv, silent_for)

            if n_conn == 0 and adv is False:
                logger.warning("HB: 0 conn + no adv — restart reconnect advertising")
                try:
                    if _last_peer_address is not None:
                        await start_reconnect_advertising(_device, _last_peer_address)
                    else:
                        await start_advertising(_device)
                except Exception as e:
                    logger.error("HB advertising restart failed: %s", e)
                continue

            now = time.monotonic()
            if n_conn >= 1 and _active_conn is not None and silent_for > 30 and (now - last_ping) > 60:
                last_ping = now
                logger.info("HB: GATT ping...")
                ok = await gatt_ping(_active_conn)
                if ok:
                    logger.info("HB: ping OK — коннект жив")
                    _last_activity_bump()
                else:
                    logger.warning("HB: ping FAIL — force disconnect и реклама")
                    try:
                        await _active_conn.disconnect()
                    except Exception as e:
                        logger.error("HB force disconnect error: %s", e)
        except Exception as e:
            logger.error("HB error: %s", e)


def _last_activity_bump():
    global _last_activity
    _last_activity = time.monotonic()


async def main():
    global ui, _device
    device, _transport = await init_ble(configure_device=install_hid_pairing_profile)
    _device = device
    device.pairing_config_factory = lambda conn: PairingConfig(sc=True, mitm=False, bonding=True)
    device.on("connection", lambda conn: asyncio.ensure_future(on_connection(conn)))
    await start_advertising(device)
    logger.info("Car Thing Media Remote запущен.")

    asyncio.create_task(heartbeat())

    loop = asyncio.get_event_loop()

    def _init_display():
        display = DRMDisplay()
        if NowPlayingUI is None:
            raise RuntimeError(f"UI import failed: {_ui_import_error}")
        return NowPlayingUI(display)

    try:
        ui = await loop.run_in_executor(None, _init_display)
        logger.info("DRM display ready")
        if state.title or state.artist:
            _render_ui()
    except Exception as e:
        logger.error("Display/UI init failed, continuing headless: %s", e)
        ui = None

    await start_input(lambda: ams)
    await asyncio.get_event_loop().create_future()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен.")


if __name__ == "__main__":
    run()
