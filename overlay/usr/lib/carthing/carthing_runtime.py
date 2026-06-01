#!/usr/bin/env python3
"""carthing_runtime — release entrypoint (runtime-contract.md §Entrypoint).

Проверяет persistent-state, поднимает ОДИН логический аксессуар и сводит сервисы.
Супервизор (S50/дирижёр) может рестартовать этот процесс, но НЕ владеет BT/GUI/pairing —
этим владеют сервисы здесь. Никаких заплаток: advertising/видимость — только через
accessory_orchestrator; идентичность — только через identity_service; bt-состояние —
только через runtime_model.

Текущий объём: спайн (state + identity + accessory + model) + источник iPhone.
Адаптеры GUI/Transfer подключаются к этим же точкам (gui_controller/transfer_service).
"""

import asyncio
import logging
import os
import time

# Часы: CTS синкает системное время в UTC -> выставляем локальную зону для strftime.
os.environ.setdefault("TZ", os.environ.get("CARTHING_TZ", "MSK-3"))  # Москва UTC+3, без DST
try:
    time.tzset()
except Exception:
    pass

import runtime_paths  # noqa: F401  (ставит sys.path)
import state_paths
import identity_service
from ble_transport import init_ble
from accessory_orchestrator import AccessoryOrchestrator
from runtime_model import RuntimeModel
from iphone_service import IPhoneService
from route_graph import Protocol
from route_planner import RoutePlanError, RoutePlanner
from session_presets import build_preset_session, normalize_preset
from session_runner import AdapterConnector, SessionRunner
from trusted_device_registry import TrustedDeviceRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("carthing_runtime")

RENDER_INTERVAL = 0.2   # с: рендер-тик (живой прогресс на экране)
PUBLISH_EVERY = 5       # каждые N тиков писать runtime-bt.json (~1 с)

orch: AccessoryOrchestrator | None = None
model = RuntimeModel()
_iphone: IPhoneService | None = None
gui = None
transfer = None          # TransferService
backchannel = None       # TransferControlBackchannel
settings = None          # SettingsService
hw_caps = {}             # hardware_inventory.probe()
mac = None               # MacService
power = None             # IdlePowerController
session_runner = None    # SessionRunner

VALID_SESSIONS = {"remote", "router", "mac", "pairing", "quiet", "service"}


class CompatibilityConnector(AdapterConnector):
    """Lifecycle placeholder while old protocol services are being wrapped.

    This lets SessionRunner become the single top-level owner now. The existing
    services still do the real protocol work below it until each connector is
    replaced with a concrete BLE/A2DP/USB adapter.
    """

    def __init__(self, protocol):
        self.protocol = protocol

    async def start(self):
        logger.info("session connector start: %s", self.protocol)

    async def stop(self):
        logger.info("session connector stop: %s", self.protocol)

    async def attach_session(self, session):
        logger.info("session connector attach: %s -> %s", self.protocol, session.name)

    async def detach_session(self, session):
        logger.info("session connector detach: %s -> %s", self.protocol, session.name)


def _on_command(source, command):
    if source == "iphone" and _iphone is not None:
        asyncio.ensure_future(_iphone.command(command))
    elif source == "mac" and mac is not None:
        asyncio.ensure_future(mac.command(command))


def _on_pairing(enabled, role="source"):
    role = role or "source"
    if power is not None:
        power.set_pairing(bool(enabled))
    if role == "device":
        if orch is not None:
            asyncio.ensure_future(orch.arm_pairing(bool(enabled)))
        if transfer is not None:
            if enabled:
                asyncio.ensure_future(transfer.start_speaker_enrollment())
            else:
                asyncio.ensure_future(transfer.stop_speaker_enrollment())
    elif role == "speaker":
        if orch is not None:
            asyncio.ensure_future(orch.arm_pairing(False))
        if transfer is not None:
            if enabled:
                asyncio.ensure_future(transfer.start_speaker_enrollment())
            else:
                asyncio.ensure_future(transfer.stop_speaker_enrollment())
    elif orch is not None:
        asyncio.ensure_future(orch.arm_pairing(bool(enabled)))
    if gui is not None:
        gui.set_pairing_mode(bool(enabled), role=role)


def _on_transfer_rescan():
    if power is not None:
        power.note_transfer_scan()
    if transfer is not None:
        asyncio.ensure_future(transfer.rescan())


def _on_transfer_select(address):
    if power is not None:
        power.note_activity("transfer_select")
    if transfer is not None:
        asyncio.ensure_future(transfer.select(address))


def _on_speaker_pair_select(address):
    if power is not None:
        power.note_activity("speaker_pair_select")
    if transfer is not None:
        async def _run():
            await transfer.pair_speaker(address)
            if gui is not None and not getattr(gui.app_state, "pairing_mode", False):
                gui.set_pairing_mode(False, role="speaker")
            if power is not None and not getattr(gui.app_state, "pairing_mode", False):
                power.set_pairing(False)
        asyncio.ensure_future(_run())


def _on_trusted_remove(key):
    async def _run():
        address = key
        if gui is not None:
            for device in gui.app_state.trusted:
                if device.get("key") == key:
                    address = device.get("address") or key
                    break
        if transfer is not None:
            await transfer.forget_trusted(address)
        dev = orch.device if orch is not None else None
        if dev is not None and getattr(dev, "keystore", None) is not None:
            from app_state import normalize_address
            normalized = normalize_address(address)
            for candidate in dict.fromkeys([normalized, f"{normalized}/P", str(address)]):
                try:
                    await dev.keystore.delete(candidate)
                    logger.info("trusted key removed: %s", candidate)
                except Exception:
                    pass
    asyncio.ensure_future(_run())


def _on_mode_select(mode):
    asyncio.ensure_future(_apply_session(mode))


def _on_session_select(session):
    asyncio.ensure_future(_apply_session(session))


def _on_route_input_select(key):
    if power is not None:
        power.note_activity("route_input_select")
    if gui is not None:
        selected = gui.app_state.select_route_input(key)
        if selected:
            gui.app_state.route_input = selected
        gui.app_state.save_trusted()
    logger.info("route input selected: %s", key)
    if model.active_session == "router":
        asyncio.ensure_future(_apply_session("router", persist=False))
    _on_publish()


def _on_route_output_select(key):
    if power is not None:
        power.note_activity("route_output_select")
    if gui is not None:
        selected = gui.app_state.select_route_output(key)
        if selected:
            gui.app_state.route_output = selected
        gui.app_state.save_trusted()
    logger.info("route output selected: %s", key)
    # Compatibility bridge: current lower layer still names output selection
    # "transfer_select". The route graph owns the product model above it.
    _on_transfer_select(key)
    if model.active_session == "router":
        asyncio.ensure_future(_apply_session("router", persist=False))
    _on_publish()


def _on_toggle_sleep(on):
    # [CLAUDE 2026-06-01] тумблер «Сон экрана» из Settings: применяем к power + персистим.
    if power is not None:
        power.set_idle_sleep(bool(on))
    if settings is not None:
        settings.set("sleep_on_idle", bool(on))


def _on_set_off_timeout(sec):
    # [CLAUDE 2026-06-01] ±тайм-аут полного гашения из Settings: применяем к power + персистим.
    sec = int(sec)
    if power is not None:
        power.set_off_after(sec)
    if settings is not None:
        settings.set("screen_off_after_sec", sec)


def _build_session_plan(session):
    plan = build_preset_session(session)
    if session != "router":
        return plan
    if gui is None or getattr(gui, "app_state", None) is None:
        return plan

    app_state = gui.app_state
    route_input = str(getattr(app_state, "route_input", "") or "").strip()
    route_output = str(getattr(app_state, "route_output", "") or "").strip()
    if not route_input or not route_output:
        return plan

    registry = TrustedDeviceRegistry(getattr(app_state, "trusted_path", None)).load()
    planner = RoutePlanner(registry)
    try:
        routed = planner.plan_simple_route(route_input, route_output, name="router")
    except RoutePlanError as exc:
        logger.warning("router plan rejected: %s", exc)
        plan.warnings.append(str(exc))
        return plan
    routed.constraints.update(plan.constraints)
    return routed


async def _apply_session(session, persist=True):
    session = normalize_preset(session)
    if session not in VALID_SESSIONS:
        session = "remote"
    model.active_session = session
    model.mode_status = "applying"
    if session_runner is not None:
        await session_runner.start(_build_session_plan(session))
    if settings is not None and persist and session != "pairing":
        settings.set("active_session", session)
    if power is not None:
        power.set_device_mode(session)

    if session != "pairing":
        if power is not None:
            power.set_pairing(False)
        if gui is not None:
            gui.set_pairing_mode(False)
        if orch is not None:
            await orch.arm_pairing(False)

    if session in ("remote", "quiet", "service", "mac", "pairing") and transfer is not None:
        await transfer.deactivate()

    if session == "remote":
        model.audio_sink = "builtin"
        model.mode_status = "iPhone remote"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_home()
    elif session == "router":
        model.audio_sink = "speaker"
        model.mode_status = "router ready"
        if _iphone is not None:
            _iphone.activate_source()
        if transfer is not None:
            await transfer.activate()
            asyncio.ensure_future(transfer.rescan())
        if power is not None:
            power.note_transfer_scan(hold_sec=15.0)
        if gui is not None:
            gui.show_transfer_screen()
    elif session == "mac":
        model.audio_sink = "builtin"
        model.mode_status = "macOS control"
        if mac is not None:
            mac.attach()
        if gui is not None:
            gui.show_mac_screen()
    elif session == "pairing":
        model.audio_sink = "builtin"
        model.mode_status = "pairing window"
        if gui is not None:
            gui.show_mode_screen()
        _on_pairing(True, "source")
    elif session == "quiet":
        model.audio_sink = "builtin"
        model.mode_status = "connected quiet"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_mode_screen()
    elif session == "service":
        model.audio_sink = "builtin"
        model.mode_status = "service safe"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_mode_screen()

    logger.info("active session: %s (%s)", session, model.mode_status)
    _on_publish()


async def _apply_device_mode(mode, persist=True):
    # Legacy wrapper. Old callers may still say "transfer"; new architecture
    # calls it "router".
    await _apply_session(mode, persist=persist)


async def _emit_source_intent(intent):
    """Для backchannel: команда динамика -> активный источник."""
    if _iphone is not None:
        await _iphone.command(intent)


def _on_notif_dismiss(uid):
    """Свайп-влево на уведомлении -> очистить и на iPhone (ANCS negative)."""
    if _iphone is not None:
        asyncio.ensure_future(_iphone.dismiss(uid))


def _verify_persistent():
    try:
        state_paths.ensure_files()
        logger.info("persistent state OK (%s)", state_paths.STATE_DIR)
    except state_paths.PersistentStateError as e:
        # degraded: не выдумываем базу на tmpfs (контракт). Работаем, но без persistent-бондов.
        logger.error("DEGRADED — %s", e)


def _on_publish():
    model.write_bt_json()


def _is_classic(connection) -> bool:
    try:
        from bumble.core import BT_BR_EDR_TRANSPORT
        return getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT
    except Exception:
        return False


async def _on_connection(connection):
    global _iphone
    classic = _is_classic(connection)
    logger.info("connected: %s classic=%s encrypted=%s",
                getattr(connection, "peer_address", "?"), classic,
                getattr(connection, "is_encrypted", False))

    # Входящий classic A2DP (iPhone выбрал Car Thing аудиовыходом) -> Transfer-маршрут.
    if classic:
        if transfer is not None:
            await transfer.on_incoming_classic(connection)
        return

    _iphone = IPhoneService(model, on_update=_on_publish)
    started = {"v": False}

    async def _start_ams(why):
        # AMS-характеристики требуют ШИФРОВАНИЯ — поднимаем только когда encrypted.
        if started["v"] or not getattr(connection, "is_encrypted", False):
            return
        started["v"] = True
        logger.info("AMS start (%s)", why)
        try:
            await _iphone.setup(connection)
        except Exception as e:
            started["v"] = False
            logger.warning("iphone setup failed: %s", e)
        if orch is not None:
            await orch.on_bonded()

    def _disc(*_):
        if _iphone is not None:
            _iphone.reset()
        if orch is not None:
            asyncio.ensure_future(orch.on_disconnect())

    async def _on_pairing_failure(reason):
        # [CLAUDE 2026-06-01] АВТО-«ЗАБЫТЬ» при сбое пары.
        # Симптом: iPhone «забыл» устройство и парится заново, а device держит СТАРЫЙ бонд +
        # включён address-resolution (загружен на power_on). Контроллер резолвит RPA телефона в
        # старую identity -> в SC-крипто device использует identity-адрес, iPhone — свой RPA ->
        # DHKey check НЕ сходится -> SMP_DHKEY_CHECK_FAILED, пара не создаётся (нужна ручная чистка).
        # Фикс: на сбое пары авто-сбрасываем старый бонд + резолвинг -> СЛЕДУЮЩИЙ ретрай iPhone
        # (он реконнектит сам) идёт без резолвинга -> on-air RPA с обеих сторон -> DHKey сходится ->
        # свежая пара создаётся автоматически, без ручного rm keys.json.
        # Codex: это закрывает "forget на iPhone -> не пере-парится". Долгосрочно лучше дроп бонда
        # на СТАРТЕ пары (pairing request), но reactive-на-failure надёжно (iPhone сам ретраит).
        logger.error("SMP pairing failed: %s — auto-forget stale bond + resolving", reason)
        dev = orch.device if orch is not None else None
        if dev is None:
            return
        try:
            if dev.keystore is not None:
                await dev.keystore.delete_all()
            from bumble.hci import (HCI_LE_Set_Address_Resolution_Enable_Command,
                                    HCI_LE_Clear_Resolving_List_Command)
            await dev.send_command(HCI_LE_Set_Address_Resolution_Enable_Command(
                address_resolution_enable=0))
            await dev.send_command(HCI_LE_Clear_Resolving_List_Command())
            logger.info("Auto-forget: dropped stale bond + cleared resolving (clean re-pair on retry)")
        except Exception as e:
            logger.warning("auto-forget failed: %s", e)

    connection.on("disconnection", _disc)
    connection.on("pairing", lambda *_: asyncio.ensure_future(_start_ams("pairing")))
    connection.on("pairing_failure", lambda r: asyncio.ensure_future(_on_pairing_failure(r)))
    connection.on("connection_encryption_change",
                  lambda *_: asyncio.ensure_future(_start_ams("encryption")))

    if gui is not None:
        gui.set_pairing_mode(False)   # авто-закрыть pairing-модалку на коннекте
    if power is not None:
        power.set_pairing(False)

    if getattr(connection, "is_encrypted", False):
        await _start_ams("connected-encrypted")
    else:
        logger.info("requesting pairing (link not encrypted yet)")
        try:
            connection.request_pairing()
        except Exception as e:
            logger.warning("request_pairing failed: %s", e)


async def main():
    global orch, gui, transfer, backchannel, settings, hw_caps, mac, power, session_runner
    _verify_persistent()

    # Per-boot инвентарь возможностей + настройки.
    import hardware_inventory
    from settings_service import SettingsService
    hw_caps = hardware_inventory.probe()
    settings = SettingsService()
    session_runner = SessionRunner()
    for protocol in Protocol:
        session_runner.register(CompatibilityConnector(protocol))
    logger.info("hw capabilities: %s", {k: v for k, v in hw_caps.items() if v})

    def _configure(device):
        global orch
        orch = AccessoryOrchestrator(device, on_phase_change=lambda p: logger.info("phase=%s", p))
        orch.install()  # CTKD pairing config + classic enabled (для CTKD)

    # Cold-boot: hci0 (btattach) может быть ещё не готов -> Errno 16 busy. Терпеливый retry.
    device = None
    for attempt in range(8):
        try:
            device, _transport = await init_ble(configure_device=_configure)
            break
        except OSError as e:
            logger.warning("init_ble attempt %d failed (HCI busy?): %s", attempt + 1, e)
            await asyncio.sleep(3)
    if device is None:
        logger.error("init_ble failed after retries — exiting (supervisor restart)")
        return
    await orch.apply_identity()       # одно имя на все транспорты

    device.on("connection", lambda c: asyncio.ensure_future(_on_connection(c)))

    # GUI: один home-surface + views поверх DRM (если дисплей доступен).
    if hw_caps.get("display_drm"):
        try:
            from drm_display import DRMDisplay
            from gui_controller import GuiController
            gui = GuiController(DRMDisplay(),
                                on_command=_on_command, on_pairing=_on_pairing,
                                on_transfer_rescan=_on_transfer_rescan,
                                on_transfer_select=_on_transfer_select,
                                on_speaker_pair_select=_on_speaker_pair_select,
                                on_trusted_remove=_on_trusted_remove,
                                on_notif_dismiss=_on_notif_dismiss,
                                on_mode_select=_on_mode_select,
                                on_session_select=_on_session_select,
                                on_route_input_select=_on_route_input_select,
                                on_route_output_select=_on_route_output_select,
                                on_toggle_sleep=_on_toggle_sleep,
                                on_set_off_timeout=_on_set_off_timeout)
            logger.info("GUI active (modular Compositor)")
            from power_policy import IdlePowerController
            power = IdlePowerController(settings)
            # [CLAUDE] начальные значения для Settings = реальные из power
            gui.app_state.sleep_on_idle = bool(getattr(power, "enabled", True))
            gui.app_state.screen_off_sec = int(getattr(power, "off_after", 150))
        except Exception as e:
            gui = None
            logger.warning("GUI disabled: %s", e)

    # Transfer: A2DP relay + backchannel (внутри единого рантайма).
    try:
        from transfer_service import TransferService
        from transfer_control import TransferControlBackchannel
        app_state = gui.app_state if gui is not None else None
        transfer = TransferService(device, app_state, orch, model, on_change=_on_publish)
        backchannel = TransferControlBackchannel(_emit_source_intent, model=model)
        await transfer.start()        # SDP + AVDTP listener (видимость ещё перегейтим)
    except Exception as e:
        transfer = None
        logger.warning("transfer disabled: %s", e)

    # macOS-источник (Фаза 4, каркас).
    from mac_service import MacService
    mac = MacService(model, on_update=_on_publish)
    await _apply_session(settings.get("active_session", settings.get("device_mode", "remote")), persist=False)

    # Видимость — ПОСЛЕ transfer.start(): orchestrator перегейтит classic в not-connectable
    # (никакой открытой A2DP-рекламы; directed-к-bonded / тишина по фазе).
    await orch.apply_visibility()
    # Старт с существующим бондом -> активно прилипнуть (high-duty directed burst).
    asyncio.ensure_future(orch.kick_reconnect())

    # Рендер-цикл — ОТДЕЛЬНАЯ задача (не зависит от input.start, который блокирует loop).
    async def _render_loop():
        tick = 0
        while True:
            # Во время шторки экраном владеет отдельный тикер (_shade_loop) — основной
            # цикл молчит, чтобы не было двойного рендера/гонки за дисплей.
            shade = gui is not None and gui.needs_fast_render()
            if power is not None:
                power.note_model(model)
                power.tick()
                model.power_tier = power.runtime_tier
            if gui is not None and not shade:
                gui.apply(model)      # RuntimeModel -> AppState (живой прогресс)
                if power is None or power.display_awake:
                    gui.render()
            publish_due = (tick % PUBLISH_EVERY == 0) if power is None else power.should_publish()
            if not shade and publish_due:
                _on_publish()         # runtime-bt.json для дирижёра/sync
            tick += 1
            interval = RENDER_INTERVAL if power is None else power.render_interval
            await asyncio.sleep(interval)

    asyncio.ensure_future(_render_loop())

    # Физический ввод (энкодер/кнопки/тач) -> GUI (параллельно рендеру).
    if gui is not None:
        try:
            import input_handler
            def _on_input(event):
                if power is not None:
                    power.note_activity("input")
                gui.handle_input(event)
            asyncio.ensure_future(input_handler.start(on_event=_on_input))
        except Exception as e:
            logger.warning("input disabled: %s", e)

    logger.info("runtime up — name=%s", identity_service.visible_name())
    await asyncio.get_event_loop().create_future()   # работать вечно


if __name__ == "__main__":
    asyncio.run(main())
