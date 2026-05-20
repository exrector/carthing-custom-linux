"""Main runtime for the working Car Thing BLE media remote."""

import asyncio
import logging
import struct
import time
from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.device import AdvertisingData, Connection, Device, OwnAddressType
from bumble.gatt import Characteristic, Descriptor, Service
from bumble.smp import PairingConfig

from ams_client import AMSClient, MediaState
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
ui: NowPlayingUI | None = None
_device: Device | None = None
_last_activity = time.monotonic()
_active_conn: Connection | None = None
_ams_starting: set[int] = set()

GATT_SERVICE_UUID = UUID.from_16_bits(0x1801)
BATTERY_SERVICE_UUID = UUID.from_16_bits(0x180F)
HID_SERVICE_UUID = UUID.from_16_bits(0x1812)

# Apple Notification Center Service (ANCS) UUID. Advertised as a 128-bit
# *service solicitation* (not service class) so iOS re-initiates the connection
# to this bonded accessory after a Bluetooth toggle / out-of-range / reboot.
# See: Apple Bluetooth Accessory Design Guidelines, "Advertising" — an accessory
# that solicits ANCS/AMS prompts the iOS Central to connect back to it.
ANCS_SOLICITATION_UUID = UUID("7905F431-B5CE-4E99-A40F-4B1E122D00D0")

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
    if ui:
        try:
            ui.render(s)
        except Exception as e:
            logger.error("UI render error: %s", e)


async def on_connection(connection: Connection):
    global _last_activity
    _last_activity = time.monotonic()
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

    if connection.is_encrypted:
        await maybe_start_ams(connection, "connected-encrypted")
    else:
        logger.info("Requesting pairing for handle=%d", connection.handle)
        connection.request_pairing()


def on_pairing(connection: Connection, keys):
    logger.info("SMP: bonding complete handle=%d keys=%s", connection.handle, keys)
    if connection.is_encrypted:
        asyncio.create_task(maybe_start_ams(connection, "pairing-complete"))


def on_connection_encryption_change(connection: Connection):
    logger.info(
        "Encryption change handle=%d encrypted=%s",
        connection.handle,
        connection.is_encrypted,
    )
    if connection.is_encrypted:
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


async def on_disconnection(connection: Connection, reason: int):
    global ams, _active_conn
    logger.warning("Отключился: %s (reason 0x%02x)", connection.peer_address, reason)
    ams = None
    _active_conn = None
    # Disconnect placeholder: without this the DRM display keeps the last
    # rendered track frozen on screen even though BLE is gone and no more AMS
    # updates arrive (ui.render is only driven by on_state_update). Mutate the
    # shared MediaState to the placeholder and repaint once.
    state.title = "Lost Contact"
    state.artist = "Awaiting Deep Space Relay"
    state.album = ""
    state.duration = 0.0
    state.position = 0.0
    state.playing = False
    if ui:
        try:
            ui.render(state)
        except Exception as e:
            logger.error("UI disconnect render error: %s", e)
    try:
        await asyncio.sleep(0.3)
        if _device and not _device.is_advertising:
            logger.info("Re-advertising после disconnect")
            await start_advertising(_device)
    except Exception as e:
        logger.error("Re-advertise error: %s", e)


async def start_advertising(device: Device):
    # 31-byte advertising PDU budget forces a split between the primary
    # advertising data and the scan response:
    #
    #   adv data       = FLAGS (3) + 128-bit ANCS solicitation (18) = 21 bytes
    #   scan response  = APPEARANCE (4) + HID 16-bit UUID (4) + name (10) = 18 bytes
    #
    # The ANCS solicitation MUST live in the primary adv data (not the scan
    # response) because iOS acts on solicitation seen during passive scan to
    # decide whether to connect back. A 128-bit solicitation alone (18B) plus
    # FLAGS (3B) does not leave room for the name/appearance/HID UUID, hence the
    # split. bytes(UUID) yields the little-endian (Bluetooth byte order) form.
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, bytes([0x06])),
                (
                    AdvertisingData.LIST_OF_128_BIT_SERVICE_SOLICITATION_UUIDS,
                    bytes(ANCS_SOLICITATION_UUID),
                ),
            ]
        )
    )
    device.scan_response_data = bytes(
        AdvertisingData(
            [
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
    logger.info("Реклама запущена (adv=FLAGS+ANCS-solicit, scan_rsp=name+HID)")


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
                logger.warning("HB: 0 conn + no adv — start_advertising")
                try:
                    await start_advertising(_device)
                except Exception as e:
                    logger.error("HB start_advertising failed: %s", e)
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
    device.on("disconnection", lambda conn, reason: asyncio.ensure_future(on_disconnection(conn, reason)))

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
            ui.render(state)
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
