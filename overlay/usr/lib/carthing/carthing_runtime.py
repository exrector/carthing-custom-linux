#!/usr/bin/env python3
"""Minimal Car Thing runtime: Play Now, iPhone control, and remote microphone."""

import asyncio
import logging
import os
import time


os.environ.setdefault("TZ", os.environ.get("CARTHING_TZ", "MSK-3"))
try:
    time.tzset()
except Exception:
    pass

import runtime_paths  # noqa: F401
import identity_service
import state_paths
from connection_journal import record_connection_event
from hci_operation_gate import HciOperationGate
from runtime_model import RuntimeModel


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("carthing_runtime")

RENDER_INTERVAL = 0.2
PUBLISH_EVERY = 5

model = RuntimeModel()
orch = None
iphone = None
iphone_connection = None
gui = None
settings = None
power = None
session_plane = None
hci_gate = HciOperationGate()
hardware = {}


def _uptime():
    try:
        with open("/proc/uptime", "r", encoding="ascii") as handle:
            return float(handle.read().split()[0])
    except Exception:
        return None


def _milestone(name, **fields):
    parts = [f"BOOT_PROFILE milestone={name}"]
    uptime = _uptime()
    if uptime is not None:
        parts.append(f"proc_uptime_s={uptime:.3f}")
    parts.extend(
        f"{key}={str(value).replace(' ', '_')}"
        for key, value in fields.items()
    )
    logger.info(" ".join(parts))


def _publish():
    model.write_bt_json()


def _on_command(source, command):
    if source == "iphone" and iphone is not None:
        hid_command = {
            "toggle": "play_pause",
            "play": "play_pause",
            "pause": "play_pause",
            "next": "next",
            "prev": "prev",
            "previous": "prev",
            "vol_up": "vol_up",
            "vol_down": "vol_down",
        }.get(command)
        if command in ("vol_up", "vol_down"):
            if (
                model.remote_media_active
                and session_plane is not None
                and session_plane.send_media_control(command)
            ):
                logger.info("volume command -> AirPlay bridge: %s", command)
            else:
                logger.info("volume command -> AMS: %s", command)
                asyncio.create_task(iphone.command(command))
        elif model.remote_media_active and hid_command is not None:
            from hid_remote_service import send_consumer_usage

            asyncio.create_task(send_consumer_usage(hid_command))
        else:
            asyncio.create_task(iphone.command(command))


def _on_pairing(enabled, role="input"):
    if role not in ("input", "source"):
        return
    enabled = bool(enabled)
    if power is not None:
        power.set_pairing(enabled)
    if orch is not None:
        asyncio.create_task(
            orch.arm_pairing(
                enabled,
                disconnect_current=enabled,
                classic_discoverable=False,
            )
        )
    if gui is not None:
        gui.set_pairing_mode(enabled, role="input")


def _on_notification_dismiss(uid):
    if iphone is not None:
        asyncio.create_task(iphone.dismiss(uid))


def _on_toggle_notifications(enabled):
    if settings is not None:
        settings.set("notif_blink", bool(enabled))


def _on_set_brightness(percent):
    percent = int(percent)
    if power is not None:
        power.set_active_brightness_percent(percent)
    if settings is not None:
        settings.set("screen_brightness_pct", percent)


def _on_toggle_client(enabled):
    enabled = bool(enabled)
    if settings is not None:
        settings.set("client_enabled", enabled)
    if session_plane is not None:
        session_plane.set_listening(enabled)
    else:
        model.set_remote_mic(
            enabled,
            state="unavailable" if enabled else "off",
            message=(
                "Bluetooth-сессия недоступна"
                if enabled
                else "Микрофон выключен"
            ),
            transport="none",
        )
    if enabled and orch is not None and not orch.session_connected:
        asyncio.create_task(orch.start_session_bootstrap())
    logger.info("remote mic -> %s", "on" if enabled else "off")
    _publish()


def _on_session_transport_toggle(enabled):
    """The Mac owns its CTSP link, never the physical microphone capture."""
    enabled = bool(enabled)
    logger.info("session transport request -> %s", "on" if enabled else "off")
    if session_plane is None:
        return
    if enabled:
        session_plane.set_enabled(True)
    else:
        asyncio.create_task(session_plane.disconnect_all())
    _publish()


async def _on_session_disconnect(_address):
    if orch is None:
        return
    if settings is not None and bool(settings.get("client_enabled", False)):
        await orch.on_session_disconnect()
        return
    orch.session_connected = False
    orch.session_bootstrap_active = False
    await orch.apply_visibility()


def _on_remote_media_clear():
    if iphone is not None:
        iphone.activate_source()
    else:
        _publish()


def _on_power_off():
    import power_control

    state = gui.app_state if gui is not None else None
    if state is not None:
        state.power_unplug_status = "preparing"
        state.power_unplug_message = "Готовим..."
    asyncio.create_task(
        power_control.prepare_for_usb_unplug(
            power=power,
            state=state,
        )
    )


def _verify_persistent_state():
    try:
        state_paths.ensure_files()
        logger.info("persistent state OK (%s)", state_paths.STATE_DIR)
    except state_paths.PersistentStateError as error:
        logger.error("persistent state degraded: %s", error)


def _is_classic(connection):
    try:
        from bumble.core import BT_BR_EDR_TRANSPORT

        return getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT
    except Exception:
        return False


async def _forget_stale_source_bond(connection, reason):
    logger.error("SMP pairing failed: %s; clearing stale iPhone bond", reason)
    device = orch.device if orch is not None else None
    if device is None:
        return
    addresses = {str(getattr(connection, "peer_address", "") or "")}
    if gui is not None:
        addresses.update(
            str(row.get("address") or "")
            for row in gui.app_state.trusted_sources
        )
    try:
        if device.keystore is not None:
            from app_state import normalize_address

            for raw_address in addresses:
                address = normalize_address(raw_address)
                for candidate in dict.fromkeys(
                    [address, f"{address}/P", raw_address]
                ):
                    if not candidate:
                        continue
                    try:
                        await device.keystore.delete(candidate)
                    except Exception:
                        pass
        from bumble.hci import (
            HCI_LE_Clear_Resolving_List_Command,
            HCI_LE_Set_Address_Resolution_Enable_Command,
        )

        await device.send_command(
            HCI_LE_Set_Address_Resolution_Enable_Command(
                address_resolution_enable=0
            )
        )
        await device.send_command(HCI_LE_Clear_Resolving_List_Command())
    except Exception as error:
        logger.warning("stale iPhone bond cleanup failed: %s", error)


async def _sync_trusted_iphone(connection):
    if gui is None:
        return
    state = gui.app_state
    try:
        state.load_trusted()
        if state.trusted_sources:
            source = state.trusted_sources[0]
            source["label"] = "iPhone"
            source["type"] = "Источник"
            source["role"] = "source"
            source.setdefault("metadata", {}).update(
                {
                    "enrolled_from": "ble_source_connection",
                    "input_enrolled": True,
                    "probe_stage": "ams_ancs_ready",
                }
            )
        else:
            state.enroll_trusted_device(
                str(getattr(connection, "peer_address", "")),
                name="iPhone",
                ble_services={"ams", "ancs", "1812"},
                metadata={
                    "enrolled_from": "ble_source_connection",
                    "input_enrolled": True,
                    "probe_stage": "ams_ancs_ready",
                },
            )
        state.save_trusted()
        logger.info(
            "trusted iPhone synced: %s",
            state.trusted_sources[0].get("address")
            if state.trusted_sources
            else "unknown",
        )
    except Exception as error:
        logger.warning("trusted iPhone sync failed: %s", error)


def _is_trusted_iphone_peer(peer):
    if gui is None:
        return False
    try:
        from app_state import normalize_address

        address = normalize_address(peer)
        return any(
            normalize_address(source.get("address")) == address
            for source in gui.app_state.trusted_sources
        )
    except Exception:
        return False


def _connection_is_active(connection):
    if connection is None or orch is None:
        return False
    try:
        return orch.device.connections.get(connection.handle) is connection
    except Exception:
        return False


async def _on_connection(connection):
    global iphone, iphone_connection

    peer = getattr(connection, "peer_address", "?")
    if _is_classic(connection):
        logger.warning("unexpected Classic connection rejected: %s", peer)
        record_connection_event("classic_connection_rejected", peer=str(peer))
        try:
            await connection.disconnect()
        except Exception:
            pass
        return

    logger.info(
        "LE connected: %s encrypted=%s",
        peer,
        getattr(connection, "is_encrypted", False),
    )
    record_connection_event(
        "le_connected",
        peer=str(peer),
        encrypted=bool(getattr(connection, "is_encrypted", False)),
    )

    if (
        orch is not None
        and session_plane is not None
        and orch.is_session_connection()
        and not _is_trusted_iphone_peer(peer)
        and session_plane.on_connection(connection)
    ):
        await orch.on_session_connection_started()
        return

    if (
        iphone_connection is not None
        and iphone_connection is not connection
        and _connection_is_active(iphone_connection)
    ):
        logger.warning("duplicate iPhone connection rejected: %s", peer)
        record_connection_event(
            "iphone_duplicate_rejected",
            peer=str(peer),
        )
        try:
            await connection.disconnect()
        except Exception:
            pass
        return

    iphone_connection = connection
    await orch.on_le_connection_started()

    from iphone_service import IPhoneService

    iphone = IPhoneService(model, on_update=_publish, hci_gate=hci_gate)
    started = False

    async def start_iphone_services(reason):
        nonlocal started
        if (
            started
            or iphone_connection is not connection
            or not _connection_is_active(connection)
            or not getattr(connection, "is_encrypted", False)
        ):
            return
        started = True
        logger.info("iPhone services start (%s)", reason)
        record_connection_event(
            "iphone_services_start",
            peer=str(peer),
            trigger=str(reason),
        )
        try:
            await iphone.setup(connection)
        except Exception as error:
            started = False
            logger.warning("iPhone services failed: %s", error)
            record_connection_event(
                "iphone_services_failed",
                peer=str(peer),
                error=str(error),
            )
            return
        if iphone_connection is not connection or not _connection_is_active(connection):
            return
        await _sync_trusted_iphone(connection)
        await orch.on_bonded()
        await orch.start_session_bootstrap()
        record_connection_event(
            "iphone_services_ready",
            peer=str(peer),
        )

    def disconnected(reason=None, *_args):
        global iphone, iphone_connection
        if iphone_connection is not connection:
            logger.info("stale iPhone disconnect ignored: %s reason=%s", peer, reason)
            record_connection_event(
                "iphone_stale_disconnect",
                peer=str(peer),
                reason=reason,
            )
            return
        logger.info("iPhone disconnected: %s reason=%s", peer, reason)
        record_connection_event(
            "iphone_disconnected",
            peer=str(peer),
            reason=reason,
        )
        iphone_connection = None
        if iphone is not None:
            iphone.reset()
            iphone = None
        if orch is not None:
            asyncio.create_task(orch.on_disconnect())

    connection.on("disconnection", disconnected)
    connection.on(
        "pairing",
        lambda *_: asyncio.create_task(start_iphone_services("pairing")),
    )
    connection.on(
        "pairing_failure",
        lambda reason: asyncio.create_task(
            _forget_stale_source_bond(connection, reason)
        ),
    )
    connection.on(
        "connection_encryption_change",
        lambda *_: asyncio.create_task(start_iphone_services("encryption")),
    )

    if gui is not None:
        gui.set_pairing_mode(False)
    if power is not None:
        power.set_pairing(False)

    if getattr(connection, "is_encrypted", False):
        await start_iphone_services("connected-encrypted")
    else:
        logger.info("requesting iPhone pairing")
        try:
            connection.request_pairing()
        except Exception as error:
            logger.warning("request_pairing failed: %s", error)


def _init_gui():
    global gui, power

    gui_enabled = os.environ.get("CARTHING_GUI_ENABLE", "1") != "0"
    web_display = os.environ.get("CAR_THING_WEB_DISPLAY") == "1"
    mac_display = os.environ.get("CAR_THING_MAC_DISPLAY") == "1"
    if not gui_enabled:
        logger.info("GUI disabled by CARTHING_GUI_ENABLE=0")
        return
    if not (web_display or mac_display or hardware.get("display_drm")):
        logger.info("GUI disabled: no display")
        return

    try:
        if web_display:
            from web_display import WebDisplay

            display = WebDisplay()
        elif mac_display:
            from mac_display import MacDisplay, _instance

            display = _instance or MacDisplay()
        else:
            from drm_display import DRMDisplay

            display = DRMDisplay()

        from gui_controller import GuiController

        gui = GuiController(
            display,
            on_command=_on_command,
            on_pairing=_on_pairing,
            on_notif_dismiss=_on_notification_dismiss,
            on_toggle_notif_blink=_on_toggle_notifications,
            on_set_brightness=_on_set_brightness,
            on_power_off=_on_power_off,
            on_toggle_client=_on_toggle_client,
        )
        from power_policy import IdlePowerController

        power = IdlePowerController(settings)
        gui.app_state.sleep_on_idle = bool(getattr(power, "enabled", True))
        gui.app_state.screen_off_sec = int(getattr(power, "off_after", 150))
        gui.app_state.notif_blink = bool(settings.get("notif_blink", True))
        gui.app_state.screen_brightness = int(
            settings.get("screen_brightness_pct", 100)
        )
        mic_enabled = bool(settings.get("client_enabled", False))
        gui.app_state.set_remote_mic(
            mic_enabled,
            state="connecting" if mic_enabled else "off",
        )
        gui.show_home()

        if (web_display or mac_display) and hasattr(display, "set_on_event"):
            loop = asyncio.get_event_loop()

            def dispatch_input(event):
                if power is not None:
                    power.note_activity("input")
                gui.handle_input(event)

            display.set_on_event(
                lambda event: loop.call_soon_threadsafe(dispatch_input, event)
            )
        logger.info("minimal GUI active")
        _milestone("gui.ready")
    except Exception as error:
        gui = None
        logger.exception("GUI disabled: %s", error)


async def _render_loop():
    tick = 0
    render_inflight = False
    render_requested = True
    loop = asyncio.get_running_loop()

    def render_complete():
        nonlocal render_inflight
        render_inflight = False

    def render():
        try:
            gui.render()
        except Exception:
            logger.exception("render failed")
        finally:
            loop.call_soon_threadsafe(render_complete)

    while True:
        try:
            if power is not None:
                power.note_model(model)
                power.tick()
                model.power_tier = power.runtime_tier
            if gui is not None:
                changed = gui.apply(model)
                if changed:
                    render_requested = True
                if (
                    render_requested
                    and (power is None or power.display_awake)
                    and not render_inflight
                ):
                    render_requested = False
                    render_inflight = True
                    loop.run_in_executor(None, render)
            publish_due = (
                tick % PUBLISH_EVERY == 0
                if power is None
                else power.should_publish()
            )
            if publish_due:
                _publish()
            tick += 1
            interval = (
                RENDER_INTERVAL
                if power is None
                else power.render_interval
            )
            if gui is not None and gui.needs_fast_render():
                interval = min(interval, 0.05)
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("render loop failed")
            await asyncio.sleep(1.0)


async def _session_reconnect_loop():
    await asyncio.sleep(8.0)
    while True:
        if orch is not None and not orch.session_connected:
            await orch.start_session_bootstrap()
        await asyncio.sleep(30.0)


async def _start_input():
    if gui is None:
        return
    try:
        import input_handler

        def on_input(event):
            if power is not None:
                power.note_activity("input")
            gui.handle_input(event)

        asyncio.create_task(input_handler.start(on_event=on_input))
        _milestone("input.scheduled")
    except Exception as error:
        logger.warning("input disabled: %s", error)


async def main():
    global orch, settings, session_plane, hardware

    _milestone("runtime.main_start")
    _verify_persistent_state()
    record_connection_event(
        "runtime_start",
        pid=os.getpid(),
        version=os.environ.get("CARTHING_RUNTIME_VERSION", "unknown"),
    )

    import hardware_inventory
    from settings_service import SettingsService

    hardware = hardware_inventory.probe()
    settings = SettingsService()
    if bool(settings.get("client_enabled", False)):
        settings.set("client_enabled", False)
        logger.info("remote mic reset to off at runtime start")
    settings.save()
    logger.info(
        "hardware capabilities: %s",
        {key: value for key, value in hardware.items() if value},
    )
    _init_gui()

    def configure(device):
        global orch, session_plane

        from accessory_orchestrator import AccessoryOrchestrator
        from app_state import AppState
        from hid_remote_service import install_hid_remote_profile
        from session_plane_service import SessionPlaneService

        orch = AccessoryOrchestrator(
            device,
            on_phase_change=lambda phase: logger.info("phase=%s", phase),
            hci_gate=hci_gate,
        )
        orch.install()
        install_hid_remote_profile(device)
        state = gui.app_state if gui is not None else AppState()
        session_plane = SessionPlaneService(
            device,
            state,
            model,
            on_change=_publish,
            on_client_toggle=_on_session_transport_toggle,
            on_disconnect=_on_session_disconnect,
            on_remote_media_clear=_on_remote_media_clear,
            hci_gate=hci_gate,
        )
        session_plane.install()
        session_plane.set_enabled(True)
        session_plane.set_listening(
            bool(settings.get("client_enabled", False))
        )

    from ble_transport import init_ble

    device = None
    for attempt in range(8):
        try:
            device, _transport = await init_ble(configure_device=configure)
            _milestone("ble.init_ready", attempt=attempt + 1)
            break
        except OSError as error:
            logger.warning(
                "init_ble attempt %d failed: %s", attempt + 1, error
            )
            await asyncio.sleep(3.0)
    if device is None:
        logger.error("init_ble failed after retries")
        return

    await orch.apply_identity()
    device.on(
        "connection",
        lambda connection: asyncio.create_task(_on_connection(connection)),
    )
    await orch.apply_visibility()
    asyncio.create_task(orch.kick_reconnect())
    asyncio.create_task(_session_reconnect_loop())
    asyncio.create_task(_render_loop())
    await _start_input()

    _milestone("minimal_services.ready")
    _milestone("runtime.ready")
    logger.info("runtime up: %s", identity_service.visible_name())
    await asyncio.get_running_loop().create_future()


if __name__ == "__main__":
    if os.environ.get("CAR_THING_MAC_DISPLAY") == "1":
        from mac_display import MacDisplay, run_with_display

        MacDisplay()
        run_with_display(main)
    else:
        asyncio.run(main())
