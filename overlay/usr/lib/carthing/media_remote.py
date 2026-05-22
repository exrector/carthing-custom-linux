"""Main runtime for the working Car Thing BLE media remote."""

import asyncio
import logging
import os
import struct
import time
from runtime_paths import ensure_runtime_paths, device_name

ensure_runtime_paths()

from bumble.core import BT_BR_EDR_TRANSPORT, UUID
from bumble.device import AdvertisingData, AdvertisingType, Connection, Device, OwnAddressType
from bumble.gatt import Characteristic, Descriptor, Service
from bumble.smp import PairingConfig

from a2dp_bridge import A2DPBridge, COD_AUDIO_LOUDSPEAKER
from ams_client import AMSClient, MediaState
from ble_transport import init_ble
from drm_display import DRMDisplay
from input_handler import (
    start as start_input,
    CMD_TOGGLE, CMD_NEXT, CMD_PREV, CMD_VOL_UP, CMD_VOL_DOWN,
)

# Legacy single-screen UI (kept as a fallback if the modular GUI fails to import)
try:
    from now_playing_ui import NowPlayingUI
    _ui_import_error = None
except Exception as exc:
    NowPlayingUI = None
    _ui_import_error = exc

# Modular GUI stack (PIL→DRM compositor). Optional: on import failure we fall
# back to the legacy NowPlayingUI so the device never boots without a screen.
try:
    from ui_screen import Compositor, DRMDisplayAdapter
    from ui_statusbar import StatusBar
    from ui_anim import AnimDriver
    from app_state import AppState
    from intents import Dispatcher
    from screens import (
        NowPlayingScreen, MacOSScreen, TransferScreen, SettingsScreen,
        NotificationsScreen, PairingModal,
    )
    _gui_import_error = None
except Exception as exc:
    Compositor = None
    _gui_import_error = exc

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

state = MediaState()
ams: AMSClient | None = None
ui: NowPlayingUI | None = None        # legacy UI (used only if GUI import failed)
compositor = None                     # modular GUI compositor (preferred)
app_state = AppState() if Compositor is not None else None
dispatcher = None
_device: Device | None = None
_last_activity = time.monotonic()
_active_conn: Connection | None = None
_last_peer_address = None
_reconnect_fallback_task: asyncio.Task | None = None
_ams_starting: set[int] = set()
_a2dp_bridge: A2DPBridge | None = None

# Dispatcher command → AMS RemoteCommand. play/pause both map to Toggle (AMS has
# no discrete play/pause); AMS state updates re-sync the UI's notion of playing.
_AMS_CMD = {
    "play": CMD_TOGGLE, "pause": CMD_TOGGLE, "next": CMD_NEXT,
    "prev": CMD_PREV, "vol_up": CMD_VOL_UP, "vol_down": CMD_VOL_DOWN,
}


def _ble_command(source_key: str, command: str):
    """Intent dispatcher sink: forward a UI media command to the live AMS link.
    Only the iPhone source exists on this device; Mac is simulator-only."""
    if source_key != "iphone" or ams is None:
        return
    code = _AMS_CMD.get(command)
    if code is not None:
        asyncio.create_task(ams.send_command(code))


def bluetooth_name() -> str:
    # One name everywhere (BLE advertising + classic inquiry). After power_on the
    # device name is the unique id from the real controller MAC; before that we
    # fall back to the hostname/config-derived name.
    if _device is not None and getattr(_device, "name", None):
        return _device.name
    return device_name()


def is_classic_connection(connection: Connection) -> bool:
    return getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT


def _broadcast_app_state():
    if compositor is not None:
        try:
            app_state.clock_text = time.strftime("%H:%M")
            compositor.broadcast_state(app_state)
        except Exception as e:
            logger.error("GUI state broadcast error: %s", e)


def request_transfer_rescan():
    if _a2dp_bridge is None:
        return
    asyncio.create_task(_a2dp_bridge.scan_trusted_speakers())


def request_transfer_select(address):
    if _a2dp_bridge is None:
        return
    asyncio.create_task(_a2dp_bridge.request_receiver_connection(address))


def _sync_media_to_appstate(s: MediaState):
    """Project the AMS MediaState onto AppState.iphone (the GUI's source)."""
    sess = app_state.iphone
    sess.connected = _active_conn is not None
    sess.title = s.title
    sess.artist = s.artist
    sess.duration = s.duration
    sess.position = s.position
    sess.playing = s.playing
    sess.volume = s.volume
    app_state.clock_text = time.strftime("%H:%M")


def _render_ui(s: MediaState):
    """Push current media state to whichever UI is active."""
    if compositor is not None:
        try:
            _sync_media_to_appstate(s)
            compositor.broadcast_state(app_state)
        except Exception as e:
            logger.error("GUI render error: %s", e)
    elif ui is not None:
        try:
            ui.render(s)
        except Exception as e:
            logger.error("UI render error: %s", e)


def _build_compositor(display):
    """Wire the modular GUI: desktops + dispatcher + status bar over the DRM display."""
    global dispatcher
    adapter = DRMDisplayAdapter(display)
    dispatcher = Dispatcher(
        app_state,
        on_command=_ble_command,
        on_transfer_rescan=request_transfer_rescan,
        on_transfer_select=request_transfer_select,
    )
    emit = dispatcher.dispatch
    screens = [
        NowPlayingScreen(emit=emit),                                  # AppState.IPHONE = 0
        MacOSScreen(emit=emit),                                       # MAC = 1
        TransferScreen(emit=emit),                                           # TRANSFER = 2
        SettingsScreen(on_select=lambda key: emit("settings_select", key)),  # SETTINGS = 3
        NotificationsScreen(),                                               # NOTIFICATIONS = 4
    ]
    return Compositor(
        adapter, screens,
        status_bar=StatusBar(), anim=AnimDriver(),
        state=app_state, on_intent=emit,
        pairing_modal=PairingModal(emit=emit),
    )

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


def configure_runtime_device(device: Device):
    install_hid_pairing_profile(device)
    if os.environ.get("CARTHING_A2DP_BRIDGE_ENABLE", "1") == "1":
        device.classic_enabled = True
        device.classic_ssp_enabled = True
        device.classic_sc_enabled = True
        device.connectable = True
        device.discoverable = True
        device.class_of_device = COD_AUDIO_LOUDSPEAKER
        device.name = bluetooth_name()
        logger.info("Classic runtime support enabled before power_on")


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
    _render_ui(s)


async def on_connection(connection: Connection):
    global _last_activity, _last_peer_address, _reconnect_fallback_task
    _last_activity = time.monotonic()
    connection.on("disconnection", lambda reason: asyncio.ensure_future(on_disconnection(connection, reason)))

    if is_classic_connection(connection):
        logger.info(
            "Classic/A2DP peer connected: %s handle=%d encrypted=%s",
            connection.peer_address,
            connection.handle,
            connection.is_encrypted,
        )
        if _a2dp_bridge is not None:
            await _a2dp_bridge.handle_classic_connection(connection)
        return

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

    if connection.is_encrypted:
        await maybe_start_ams(connection, "connected-encrypted")
    else:
        logger.info("Requesting pairing for handle=%d", connection.handle)
        connection.request_pairing()


def on_pairing(connection: Connection, keys):
    if is_classic_connection(connection):
        return
    logger.info("SMP: bonding complete handle=%d keys=%s", connection.handle, keys)
    if _device:
        asyncio.create_task(refresh_accept_list(_device))
    if connection.is_encrypted:
        asyncio.create_task(maybe_start_ams(connection, "pairing-complete"))


def on_connection_encryption_change(connection: Connection):
    if is_classic_connection(connection):
        logger.info(
            "Classic encryption change handle=%d encrypted=%s",
            connection.handle,
            connection.is_encrypted,
        )
        return
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
            _render_ui(state)        # flip the GUI from "Lost Contact" to connected
        else:
            logger.warning("AMS не найден на этом устройстве")
    finally:
        _ams_starting.discard(connection.handle)


async def on_disconnection(connection: Connection, reason: int):
    global ams, _active_conn
    logger.warning("Отключился: %s (reason 0x%02x)", connection.peer_address, reason)
    if is_classic_connection(connection):
        logger.info("Classic/A2DP disconnection ignored by media remote state machine")
        return

    ams = None
    _active_conn = None
    state.title = "Lost Contact"
    state.artist = "Awaiting Deep Space Relay"
    state.album = ""
    state.duration = 0.0
    state.position = 0.0
    state.playing = False
    if app_state is not None:
        app_state.iphone.connected = False
    _render_ui(state)
    try:
        await asyncio.sleep(0.3)
        if _device:
            await start_reconnect_advertising(_device, connection.peer_address)
    except Exception as e:
        logger.error("Re-advertise error: %s", e)


async def start_advertising(device: Device):
    name = bluetooth_name().encode("utf-8")
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, bytes([0x06])),
                (AdvertisingData.APPEARANCE, struct.pack("<H", 0x0180)),
                (
                    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    struct.pack("<H", 0x1812),
                ),
                (AdvertisingData.COMPLETE_LOCAL_NAME, name),
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
    name = bluetooth_name().encode("utf-8")
    device.advertising_data = bytes(
        AdvertisingData(
            [
                (AdvertisingData.FLAGS, bytes([0x06])),
                (AdvertisingData.APPEARANCE, struct.pack("<H", 0x0180)),
                (
                    AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                    struct.pack("<H", 0x1812),
                ),
                (AdvertisingData.COMPLETE_LOCAL_NAME, name),
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


async def animation_loop():
    """Advance transient animations (swipe slide) + ambient pulse, then re-render.
    Idles cheaply when nothing is animating so the no-traffic policy still holds."""
    while True:
        anim = getattr(compositor, "anim", None) if compositor is not None else None
        if anim is not None and anim.needs_tick():
            anim.tick()
            try:
                compositor.render()
            except Exception as e:
                logger.error("anim render error: %s", e)
            await asyncio.sleep(1 / 30)
        else:
            await asyncio.sleep(0.08)


async def main():
    global ui, compositor, _device, _a2dp_bridge
    if app_state is not None:
        app_state.load_trusted()
    device, _transport = await init_ble(configure_device=configure_runtime_device)
    _device = device
    device.pairing_config_factory = lambda conn: PairingConfig(sc=True, mitm=False, bonding=True)
    device.on("connection", lambda conn: asyncio.ensure_future(on_connection(conn)))
    if app_state is not None and os.environ.get("CARTHING_A2DP_BRIDGE_ENABLE", "1") == "1":
        _a2dp_bridge = A2DPBridge(
            device,
            app_state,
            bt_name=bluetooth_name(),          # one unified name (BLE + classic)
            autoconnect=os.environ.get("CARTHING_A2DP_AUTOCONNECT", "1") == "1",
            on_state_change=_broadcast_app_state,
            logger=logger,
        )
        _a2dp_bridge.install_sdp_records()
        _a2dp_bridge.install_safe_link_key_provider()
        await _a2dp_bridge.start()
    await start_advertising(device)
    logger.info("Car Thing Media Remote запущен.")

    asyncio.create_task(heartbeat())

    loop = asyncio.get_event_loop()

    def _init_display():
        """Build the display + UI off the event loop (DRM open can block)."""
        display = DRMDisplay()
        if Compositor is not None:
            return ("gui", _build_compositor(display))
        if NowPlayingUI is not None:
            return ("legacy", NowPlayingUI(display))
        raise RuntimeError(
            f"No UI available (gui import: {_gui_import_error}; legacy: {_ui_import_error})"
        )

    try:
        kind, obj = await loop.run_in_executor(None, _init_display)
        if kind == "gui":
            compositor = obj
            logger.info("DRM display ready — modular GUI active")
        else:
            ui = obj
            logger.warning("DRM display ready — legacy UI (GUI import failed: %s)", _gui_import_error)
        _render_ui(state)        # paint the initial frame (idle desktops / Lost Contact)
    except Exception as e:
        logger.error("Display/UI init failed, continuing headless: %s", e)
        compositor = None
        ui = None

    # Route physical input into the GUI compositor when present; otherwise drive
    # AMS directly (legacy). handle_input is synchronous and renders in-loop.
    if compositor is not None:
        await start_input(on_event=compositor.handle_input)
        asyncio.create_task(animation_loop())
    else:
        await start_input(get_ams=lambda: ams)
    await asyncio.get_event_loop().create_future()


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлен.")


if __name__ == "__main__":
    run()
