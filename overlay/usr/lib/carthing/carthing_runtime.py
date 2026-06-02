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
from link_manager import LinkAdapter, LinkManager
from route_graph import Protocol
from route_planner import RoutePlanError, RoutePlanner
from session_runner import AdapterConnector, SessionRunner
from trusted_device_registry import TrustedDeviceRegistry
from virtual_connectors import HciOperationGate, VirtualRoutePatchBay

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
link_manager = None      # LinkManager
hci_gate = None          # HciOperationGate
route_patchbay = None    # VirtualRoutePatchBay



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


class TransferRouteConnector(AdapterConnector):
    """SessionRunner-owned bridge between route protocols and TransferService."""

    def __init__(self, protocol, service):
        self.protocol = protocol
        self.service = service

    async def start(self):
        return

    async def stop(self):
        return

    async def attach_session(self, session):
        if self.service is None:
            return
        attached = int(getattr(self.service, "_route_connector_refcount", 0))
        if attached == 0:
            await self.service.activate()
        setattr(self.service, "_route_connector_refcount", attached + 1)

    async def detach_session(self, session):
        if self.service is None:
            return
        attached = max(0, int(getattr(self.service, "_route_connector_refcount", 0)) - 1)
        setattr(self.service, "_route_connector_refcount", attached)
        if attached == 0:
            await self.service.deactivate()


class AppStateLinkAdapter(LinkAdapter):
    """Reflect trusted-device online/connected hints from AppState into LinkManager."""

    def __init__(self, app_state):
        super().__init__(name="app-state")
        self.app_state = app_state

    def _row(self, device):
        if self.app_state is None:
            return None
        addr = str(getattr(device, "address", "") or "").upper()
        key = str(getattr(device, "id", "") or "")
        for row in getattr(self.app_state, "trusted", []) or []:
            row_addr = str(row.get("address") or "").upper()
            row_key = str(row.get("key") or "")
            if (addr and row_addr == addr) or (key and row_key == key):
                return row
        return None

    async def probe(self, device):
        row = self._row(device)
        if row is None:
            return False
        return bool(row.get("online") or row.get("connected"))

    async def connect_idle(self, device):
        row = self._row(device)
        return bool(row and row.get("connected"))


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
        async def _run_device_pairing():
            if enabled:
                if orch is not None:
                    await orch.arm_pairing(True, disconnect_current=False)
                if transfer is not None:
                    asyncio.create_task(transfer.start_speaker_enrollment())
            else:
                if transfer is not None:
                    await transfer.stop_speaker_enrollment()
                if orch is not None:
                    await orch.arm_pairing(False)
        asyncio.ensure_future(_run_device_pairing())
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


async def _activate_route():
    """[CLAUDE 2026-06-02] РЕЖИМЫ УДАЛЕНЫ. Единственная активируемая сущность — ребро
    input->output. Нет глобального mode/session, меняющего поведение коннектов. Присутствие
    (BLE-control + A2DP listener) живёт всегда; classic/A2DP открывается ТОЛЬКО здесь, при
    наличии выбранного маршрута. Это убирает баг «выбран transfer -> connect iPhone лезет classic»."""
    if session_runner is None or gui is None:
        return
    app_state = gui.app_state
    route_input = str(getattr(app_state, "route_input", "") or "").strip()
    route_output = str(getattr(app_state, "route_output", "") or "").strip()
    if not route_input or not route_output:
        if route_patchbay is not None:
            await route_patchbay.deactivate()
        await session_runner.stop_current()
        model.clear_route_plan()
        model.audio_sink = "builtin"
        _on_publish()
        return
    registry = TrustedDeviceRegistry(getattr(app_state, "trusted_path", None)).load()
    planner = RoutePlanner(registry)
    try:
        routed = planner.plan_simple_route(route_input, route_output, name="route")
    except RoutePlanError as exc:
        logger.warning("route rejected: %s -> %s: %s", route_input, route_output, exc)
        _on_publish()
        return
    if route_patchbay is not None:
        try:
            await route_patchbay.activate(routed, registry)
        except Exception as exc:
            logger.warning("route patch-bay wiring failed: %s", exc)
            return
    await session_runner.start(routed)
    model.set_route_plan(routed, cables=(route_patchbay.current_cables() if route_patchbay is not None else []))
    model.audio_sink = "speaker"
    if _iphone is not None:
        _iphone.activate_source()
    logger.info("route active: %s -> %s", route_input, route_output)
    _on_publish()


def _on_session_select(session):
    pass  # [CLAUDE 2026-06-02] режимы удалены — выбор режима больше ничего не делает


def _on_route_input_select(key):
    if power is not None:
        power.note_activity("route_input_select")
    if gui is not None:
        selected = gui.app_state.select_route_input(key)
        gui.app_state.save_trusted()
    model.clear_route_plan()
    logger.info("route input selected: %s", key)
    asyncio.ensure_future(_activate_route())
    _on_publish()


def _on_route_output_select(key):
    if power is not None:
        power.note_activity("route_output_select")
    if gui is not None:
        selected = gui.app_state.select_route_output(key)
        gui.app_state.save_trusted()
    model.clear_route_plan()
    logger.info("route output selected: %s", key)
    asyncio.ensure_future(_activate_route())
    _on_publish()


def _on_toggle_sleep(on):
    # [CLAUDE 2026-06-01] тумблер «Сон экрана» из Settings: применяем к power + персистим.
    if power is not None:
        power.set_idle_sleep(bool(on))
    if settings is not None:
        settings.set("sleep_on_idle", bool(on))


def _on_toggle_notif_blink(on):
    # [CLAUDE 2026-06-02] тумблер «Моргание уведомлений»: state уже выставлен в Dispatcher
    # (render читает app_state.notif_blink сразу); здесь только персистим в settings.
    if settings is not None:
        settings.set("notif_blink", bool(on))


def _on_set_off_timeout(sec):
    # [CLAUDE 2026-06-01] ±тайм-аут полного гашения из Settings: применяем к power + персистим.
    sec = int(sec)
    if power is not None:
        power.set_off_after(sec)
    if settings is not None:
        settings.set("screen_off_after_sec", sec)


# [CLAUDE 2026-06-02] _build_session_plan / _apply_session УДАЛЕНЫ (режимы вырезаны, stage 2).
# Активация маршрута — теперь только _activate_route() выше. Паринг — через свой интент, не режим.


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

    _iphone = IPhoneService(model, on_update=_on_publish, hci_gate=hci_gate)
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
        transfer_busy = bool(
            getattr(model, "active_session", "") == "router"
            or getattr(model, "transfer_active", False)
            or (
                transfer is not None
                and bool(getattr(getattr(transfer, "bridge", None), "source_stream_active", False))
            )
        )
        if transfer_busy:
            logger.error("SMP pairing failed during active transfer/router: %s — keeping bonds", reason)
            return

        logger.error("SMP pairing failed: %s — auto-forget stale source bond + resolving", reason)
        dev = orch.device if orch is not None else None
        if dev is None:
            return
        try:
            if dev.keystore is not None:
                source_addresses = {str(getattr(connection, "peer_address", "") or "")}
                if gui is not None:
                    try:
                        source_addresses.update(
                            str(row.get("address") or "")
                            for row in gui.app_state.trusted_sources
                        )
                    except Exception:
                        pass
                from app_state import normalize_address
                for address in source_addresses:
                    normalized = normalize_address(address)
                    for candidate in dict.fromkeys([normalized, f"{normalized}/P", str(address)]):
                        if candidate:
                            try:
                                await dev.keystore.delete(candidate)
                                logger.info("Auto-forget: dropped stale source bond %s", candidate)
                            except Exception:
                                pass
            from bumble.hci import (HCI_LE_Set_Address_Resolution_Enable_Command,
                                    HCI_LE_Clear_Resolving_List_Command)
            await dev.send_command(HCI_LE_Set_Address_Resolution_Enable_Command(
                address_resolution_enable=0))
            await dev.send_command(HCI_LE_Clear_Resolving_List_Command())
            logger.info("Auto-forget: cleared resolving (clean source re-pair on retry)")
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
    global orch, gui, transfer, backchannel, settings, hw_caps, mac, power, session_runner, link_manager, hci_gate, route_patchbay
    _verify_persistent()

    # Per-boot инвентарь возможностей + настройки.
    import hardware_inventory
    from settings_service import SettingsService
    hw_caps = hardware_inventory.probe()
    settings = SettingsService()
    session_runner = SessionRunner()
    hci_gate = HciOperationGate()
    route_patchbay = VirtualRoutePatchBay()
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
                                on_session_select=_on_session_select,
                                on_route_input_select=_on_route_input_select,
                                on_route_output_select=_on_route_output_select,
                                on_toggle_sleep=_on_toggle_sleep,
                                on_set_off_timeout=_on_set_off_timeout,
                                on_toggle_notif_blink=_on_toggle_notif_blink)
            logger.info("GUI active (modular Compositor)")
            from power_policy import IdlePowerController
            power = IdlePowerController(settings)
            # [CLAUDE] начальные значения для Settings = реальные из power
            gui.app_state.sleep_on_idle = bool(getattr(power, "enabled", True))
            gui.app_state.screen_off_sec = int(getattr(power, "off_after", 150))
            gui.app_state.notif_blink = bool(settings.get("notif_blink", True))  # [CLAUDE] персист моргания
        except Exception as e:
            gui = None
            logger.warning("GUI disabled: %s", e)

    # Transfer: A2DP relay + backchannel (внутри единого рантайма).
    try:
        from transfer_service import TransferService
        from transfer_control import TransferControlBackchannel
        app_state = gui.app_state if gui is not None else None
        transfer = TransferService(device, app_state, orch, model, on_change=_on_publish, hci_gate=hci_gate)
        backchannel = TransferControlBackchannel(_emit_source_intent, model=model)
        await transfer.start()        # SDP + AVDTP listener (видимость ещё перегейтим)
        for protocol in (
            Protocol.CLASSIC_A2DP_SINK,
            Protocol.CLASSIC_A2DP_SOURCE,
            Protocol.CLASSIC_AVRCP,
        ):
            session_runner.register(TransferRouteConnector(protocol, transfer))
    except Exception as e:
        transfer = None
        logger.warning("transfer disabled: %s", e)

    # macOS-источник (Фаза 4, каркас).
    from mac_service import MacService
    mac = MacService(model, on_update=_on_publish)
    trusted_path = getattr(gui.app_state, "trusted_path", None) if gui is not None else None
    trusted_registry = TrustedDeviceRegistry(trusted_path).load()
    link_manager = LinkManager(trusted_registry, interval=15.0)
    if gui is not None:
        link_manager.register(AppStateLinkAdapter(gui.app_state))
        link_manager.start()
    # [CLAUDE 2026-06-02] Без режимов: на boot поднимаем присутствие, активного маршрута нет.
    if gui is not None:
        gui.show_home()

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
