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
iap2 = None              # IAP2Service
settings = None          # SettingsService
hw_caps = {}             # hardware_inventory.probe()
mac = None               # MacService
power = None             # IdlePowerController
session_runner = None    # SessionRunner
link_manager = None      # LinkManager
hci_gate = None          # HciOperationGate
route_patchbay = None    # VirtualRoutePatchBay
_classic_probe_done = set()



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


def _best_bonded_source_address():
    states = []
    if gui is not None:
        states.append(gui.app_state)
    bridge_state = getattr(getattr(transfer, "bridge", None), "state", None)
    if bridge_state is not None and bridge_state not in states:
        states.append(bridge_state)
    for app_state in states:
        try:
            app_state.load_trusted()
            for row in app_state.trusted_sources:
                address = row.get("address")
                if address:
                    return address
        except Exception:
            pass
    return None


async def _post_pair_classic_probe(address, reason="post-pair"):
    """Quiet BR/EDR nudge after a successful BLE/CTKD bond.

    This does not make the accessory classic-discoverable and does not create a
    second pairing surface. It only tries to open a BR/EDR ACL to the already
    bonded source using the CTKD-derived link key so iOS has a reason to browse
    our Classic SDP/A2DP surface.
    """
    if os.environ.get("CARTHING_POST_PAIR_CLASSIC_PROBE") != "1":
        return
    if transfer is None or getattr(transfer, "bridge", None) is None:
        return
    from app_state import normalize_address
    address = normalize_address(address)
    if not address or address in _classic_probe_done:
        return
    _classic_probe_done.add(address)
    await asyncio.sleep(1.0)
    try:
        logger.info("post-pair classic probe: dialing %s (%s)", address, reason)
        await transfer.bridge.connect_source(address)
        logger.info("post-pair classic probe OK: %s", address)
    except Exception as e:
        logger.warning("post-pair classic probe failed for %s: %s", address, e)


def _on_pairing(enabled, role="source"):
    role = role or "source"
    if power is not None:
        power.set_pairing(bool(enabled))
    if role == "device":
        async def _run_device_pairing():
            if enabled:
                if orch is not None:
                    await orch.arm_pairing(True, disconnect_current=False,
                                           classic_discoverable=False)
                # Сканер для источников = тот же инквайри что и для колонок.
                # transfer_service.start_speaker_enrollment() восстанавливает BLE-рекламу
                # через orch.apply_visibility() после каждого цикла инквайри — радио не теряется.
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
        asyncio.ensure_future(orch.arm_pairing(
            bool(enabled),
            classic_discoverable=False,
        ))
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
        # [CLAUDE 2026-06-04] Разрываем активное соединение ДО удаления ключа.
        # Иначе: iPhone переподключается по BLE пока keys.json ещё содержит его бонд,
        # _bonded_source_rows снова добавляет его в trusted — удаление «не работает».
        dev = orch.device if orch is not None else None
        if dev is not None:
            from app_state import normalize_address
            norm = normalize_address(address)
            for conn in list(getattr(dev, "connections", {}).values()):
                try:
                    peer = normalize_address(str(getattr(conn, "peer_address", "")))
                    if peer and peer == norm:
                        await conn.disconnect()
                except Exception:
                    pass
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


async def _teardown_current_route():
    """[CLAUDE 2026-06-03] ЖЁСТКИЙ переход (#12a): ПОЛНОСТЬЮ снести текущий маршрут перед любым
    новым. Закрываем A2DP-поток + рвём classic-источник (transfer.deactivate), снимаем patchbay,
    останавливаем session_runner. Так новый маршрут не тащит за собой старые коннекты и не
    занимает интерфейс (HCI/Bumble освобождаются; HCI — единый владелец). Порядок: сверху вниз."""
    logger.info("ROUTE TEARDOWN >>> закрываю текущий маршрут (transfer -> patchbay -> session)")
    if transfer is not None:
        try:
            await transfer.deactivate()      # stop_receiver_stream + disconnect_source
            logger.info("ROUTE TEARDOWN: transfer.deactivate ok (A2DP-поток закрыт, источник отключён)")
        except Exception as exc:
            logger.warning("teardown: transfer.deactivate failed: %s", exc)
    if route_patchbay is not None:
        try:
            await route_patchbay.deactivate()
            logger.info("ROUTE TEARDOWN: patchbay.deactivate ok")
        except Exception as exc:
            logger.warning("teardown: patchbay.deactivate failed: %s", exc)
    if session_runner is not None:
        try:
            await session_runner.stop_current()
            logger.info("ROUTE TEARDOWN: session_runner.stop_current ok")
        except Exception as exc:
            logger.warning("teardown: session stop failed: %s", exc)
    model.clear_route_plan()
    try:
        gui.app_state.transfer_active = False
    except Exception:
        pass
    logger.info("ROUTE TEARDOWN <<< интерфейс свободен (HCI/Bumble), можно поднимать новый маршрут")


async def _activate_route():
    """[CLAUDE 2026-06-02/06-03] Единственная активируемая сущность — ребро input->output.
    ЖЁСТКИЙ переход: всегда сначала полный teardown текущего маршрута, потом новый. Присутствие
    (BLE-control + A2DP listener) живёт всегда; classic/A2DP открывается ТОЛЬКО здесь."""
    if session_runner is None or gui is None:
        return
    app_state = gui.app_state
    route_input = str(getattr(app_state, "route_input", "") or "").strip()
    route_output = str(getattr(app_state, "route_output", "") or "").strip()
    logger.info("ROUTE ACTIVATE запрошен: %s -> %s", route_input or "—", route_output or "—")

    # 1) ВСЕГДА сначала полностью снести текущий маршрут (жёсткий переход).
    await _teardown_current_route()

    # 2) Маршрут не выбран целиком -> остаёмся выключенными (звук на встроенном).
    if not route_input or not route_output:
        model.audio_sink = "builtin"
        _on_publish()
        return

    # 3) Выход = сам Car Thing -> Play Now (control по BLE), без A2DP/patchbay.
    if route_output == getattr(app_state, "SELF_OUTPUT_KEY", "carthing"):
        model.audio_sink = "builtin"
        logger.info("route active: %s -> Car Thing (Play Now / BLE control)", route_input)
        _on_publish()
        return

    # 4) Аудио-маршрут (вход -> внешний выход). Старый уже снят -> поднимаем новый.
    # [CLAUDE 2026-06-04] Из памяти app_state.trusted, а не с диска (см. _recompute_route_compat).
    registry = TrustedDeviceRegistry.from_trusted_list(
        getattr(app_state, "trusted", [])
    )
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


def _recompute_route_compat():
    """[CLAUDE 2026-06-02] Быстрая проверка «может ли быть такое сочетание вход→выход».
    Гоняет планировщик всухую (без подключения): успех -> route_compatible=True (зелёный),
    RoutePlanError -> False (красный). Если выбран не весь маршрут -> None."""
    if gui is None:
        return
    app_state = gui.app_state
    ri = str(getattr(app_state, "route_input", "") or "").strip()
    ro = str(getattr(app_state, "route_output", "") or "").strip()
    if not ri or not ro:
        app_state.route_compatible = None
        return
    # [CLAUDE 2026-06-03] Выход = сам Car Thing (Play Now / control) — это НЕ A2DP-маршрут,
    # а BLE-control, который всегда доступен. Совместимо без планировщика.
    if ro == getattr(app_state, "SELF_OUTPUT_KEY", "carthing"):
        app_state.route_compatible = True
        return
    try:
        # [CLAUDE 2026-06-04] Читаем из app_state.trusted (память), а не с диска.
        # state.json может содержать устаревшие данные (RPA-адрес / пустые endpoints),
        # тогда как app_state.trusted уже слит с _bonded_source_rows из keystore.
        registry = TrustedDeviceRegistry.from_trusted_list(
            getattr(app_state, "trusted", [])
        )
        RoutePlanner(registry).plan_simple_route(ri, ro, name="probe")
        app_state.route_compatible = True
    except RoutePlanError as exc:
        app_state.route_compatible = False
        logger.info("route incompatible: %s -> %s: %s", ri, ro, exc)
    except Exception as exc:
        app_state.route_compatible = False
        logger.warning("route compat probe failed: %s", exc)


def _on_session_select(session):
    pass  # [CLAUDE 2026-06-02] режимы удалены — выбор режима больше ничего не делает


def _on_route_input_select(key):
    if power is not None:
        power.note_activity("route_input_select")
    if gui is not None:
        selected = gui.app_state.select_route_input(key)
        gui.app_state.save_trusted()
        _recompute_route_compat()
    model.clear_route_plan()
    logger.info("route input selected: %s", key)
    _on_publish()


async def _apply_route_output(key):
    """[CLAUDE 2026-06-04] ТРУБА: единственное действие — куда лить A2DP-поток iPhone.
      • выбран динамик (Fosi) → держим его в standby, forward_packet сам льёт туда
      • Play Now (сам Car Thing) / не выбран → закрываем канал, поток никуда → Play Now
    Источник (iPhone) не выбирается — труба ретранслирует что бы iPhone ни прислал."""
    if transfer is None or gui is None:
        return
    self_key = getattr(gui.app_state, "SELF_OUTPUT_KEY", "carthing")
    if key and key != self_key:
        try:
            gui.app_state.select_default_speaker(key)
            transfer.bridge.state.select_default_speaker(key)
            gui.app_state.save_trusted()
        except Exception as e:
            logger.warning("select speaker %s failed: %s", key, e)
        await transfer.bridge.ensure_trusted_speakers_connected()
        await transfer.bridge.request_receiver_connection(key, force=True)
        await transfer.bridge.ensure_source_codec_matches_route()
        model.audio_sink = "speaker"
        logger.info("ТРУБА: выход = %s (динамик) — поток льётся туда", key)
    else:
        await transfer.bridge.stop_receiver_stream()
        model.audio_sink = "builtin"
        logger.info("ТРУБА: выход = Play Now — поток на динамик НЕ льётся")
    _on_publish()


def _on_route_output_select(key):
    if power is not None:
        power.note_activity("route_output_select")
    if gui is not None:
        gui.app_state.select_route_output(key)
        gui.app_state.save_trusted()
    logger.info("route output selected: %s", key)
    asyncio.ensure_future(_apply_route_output(key))


def _on_route_activate():
    # [CLAUDE 2026-06-11 v2] Кнопка [LNK] — НЕ toggle (решение владельца): она ТОЛЬКО
    # включает ВЫБРАННЫЙ маршрут. Гашение старого — фоновая обязанность системы:
    #   выход = колонка   -> применить выход + поднять classic-трубу (если не стоит)
    #   выход = Play Now  -> закрыть поток к колонке + опустить classic-трубу
    # Так смена маршрута = выбрал вход/выход -> [LNK]; никаких подвешенных состояний
    # от «случайного выключения» повторным тапом.
    if power is not None:
        power.note_activity("route_activate")

    async def _activate():
        if gui is None or transfer is None or getattr(transfer, "bridge", None) is None:
            return
        ro = str(getattr(gui.app_state, "route_output", "") or "").strip()
        self_key = getattr(gui.app_state, "SELF_OUTPUT_KEY", "carthing")
        await _apply_route_output(ro)
        source_up = getattr(transfer.bridge, "_source_connection", None) is not None
        if ro and ro != self_key:
            if not source_up:
                await _apply_route_command("connect")
        else:
            if source_up:
                await _apply_route_command("disconnect")

    asyncio.ensure_future(_activate())


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


def _on_set_theme(name):
    # [CLAUDE 2026-06-11] Тема применяется при ИМПОРТЕ ui_theme (icon-defaults
    # захватывают цвета) -> персист + чистый выход; супервизор поднимет нас с
    # новой темой через ~4 с. Это осознанный рестарт по команде пользователя.
    if settings is not None:
        settings.set("ui_theme", name)
    logger.info("ui theme -> %s; restarting runtime to apply", name)
    asyncio.get_event_loop().call_later(0.4, lambda: os._exit(0))


def _on_set_brightness(pct):
    # [CLAUDE 2026-06-10] яркость из Settings: применяем к power + персистим (UserDefaults-принцип).
    pct = int(pct)
    if power is not None:
        power.set_active_brightness_percent(pct)
    if settings is not None:
        settings.set("screen_brightness_pct", pct)


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
        if (
            os.environ.get("CARTHING_PAIRING_PRIMARY", "").lower() == "classic"
            and getattr(orch, "pairing_armed", False)
        ):
            # CTKD — только для НОВЫХ источников. Доверенная колонка, переподключившаяся
            # в окно пары, в SMP не умеет (цикл 4 A3: SMP-запрос улетал в Fosi).
            peer_addr = None
            try:
                from app_state import normalize_address as _norm
                peer_addr = _norm(str(connection.peer_address))
            except Exception:
                pass
            if (
                transfer is not None
                and peer_addr
                and transfer.bridge.state.is_trusted_speaker(peer_addr)
            ):
                logger.info("classic-first CTKD skipped for trusted speaker %s", peer_addr)
            else:
                asyncio.create_task(_complete_classic_first_ctkd(connection))
        return

    if orch is not None:
        # A connected central should be the only visible iPhone surface. Stop
        # pairing advertising immediately; if pairing fails and disconnects,
        # on_disconnect/kick_reconnect will re-apply the proper visibility.
        await orch.on_le_connection_started()

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
            return
        peer = None
        if gui is not None:
            try:
                gui.app_state.load_trusted()
                try:
                    # iOS connects over an RPA; the persisted source row is keyed by
                    # the identity address from the keystore. Label AMS-capable sources
                    # as iPhone instead of leaving the generic "Bluetooth Source".
                    for row in gui.app_state.trusted_sources:
                        if row.get("label") == "Bluetooth Source":
                            row["label"] = "iPhone"
                            row["type"] = row.get("type") or "Источник"
                            peer = row.get("address") or peer
                    gui.app_state.save_trusted()
                finally:
                    logger.info("trusted sources synced after AMS: %s", peer or "ok")
            except Exception as e:
                logger.warning("trusted source sync after AMS failed: %s", e)
        if orch is not None:
            await orch.on_bonded()
        probe_address = peer or _best_bonded_source_address()
        if probe_address:
            asyncio.create_task(_post_pair_classic_probe(probe_address, reason=why))

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
        # [CLAUDE 2026-06-04] Блокируем авто-forget ТОЛЬКО при РЕАЛЬНОЙ передаче звука
        # (source_stream_active). РАНЬШЕ сюда входил transfer_active/active_session==router —
        # но с «трубой» transfer_active=True ПОСТОЯННО, из-за чего авто-forget НИКОГДА не
        # срабатывал → битый BLE-бонд (DHKEY_CHECK_FAILED) не чистился → iPhone вечно
        # откатывался на classic-only. Открытая труба ≠ идёт поток. (INVARIANTS п.1 и п.3)
        streaming_now = bool(
            transfer is not None
            and getattr(getattr(transfer, "bridge", None), "source_stream_active", False)
        )
        if streaming_now:
            logger.error("SMP pairing failed во время РЕАЛЬНОГО потока: %s — keeping bonds", reason)
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


async def _complete_classic_first_ctkd(connection):
    """Finish one audio-first pairing by deriving the LE bond over BR/EDR SMP."""
    peer = getattr(connection, "peer_address", "?")

    async def _on_ctkd_complete():
        logger.info("classic-first CTKD complete: one Classic pair derived LE bond for %s", peer)
        if orch is not None:
            await orch.on_bonded()
        if transfer is not None and getattr(transfer, "bridge", None) is not None:
            await transfer.bridge.ensure_source_avrcp(connection)

    connection.on(
        "pairing",
        lambda *_: asyncio.create_task(_on_ctkd_complete()),
    )
    connection.on(
        "pairing_failure",
        lambda reason: logger.warning("classic-first SMP pairing failed for %s: %s", peer, reason),
    )
    try:
        logger.info("classic-first CTKD: authenticate %s", peer)
        if not getattr(connection, "authenticated", False):
            await connection.authenticate()
        if not getattr(connection, "is_encrypted", False):
            await connection.encrypt()
        logger.info("classic-first CTKD: encrypted, requesting SMP over BR/EDR for %s", peer)
        # A3 (ревью 2026-06-05): Link Key сохраняется в keystore АСИНХРОННО после
        # encrypt, а SMP-CTKD читает его сразу и падает
        # CROSS_TRANSPORT_KEY_DERIVATION_NOT_ALLOWED. Ждём появления ключа.
        device = getattr(connection, "device", None)
        if device is not None:
            for _ in range(50):  # до ~5 c
                try:
                    if await device.get_link_key(connection.peer_address) is not None:
                        logger.info("classic-first CTKD: link key persisted for %s", peer)
                        break
                except Exception:
                    pass
                await asyncio.sleep(0.1)
            else:
                logger.warning(
                    "classic-first CTKD: link key not persisted in time for %s", peer
                )
        connection.request_pairing()
    except Exception as e:
        logger.warning("classic-first CTKD failed for %s: %s", peer, e)


async def _apply_route_command(cmd):
    """Тумблер маршрута (модель владельца): Play Now — дефолт, выход Car Thing
    в Control Center появляется ТОЛЬКО по явной активации classic с устройства.
    Транспорты команды: файл route-cmd, физкнопка (пресет 1), позже GUI."""
    if transfer is None or getattr(transfer, "bridge", None) is None:
        return
    try:
        if cmd in ("connect", "on", "1"):
            address = _best_bonded_source_address()
            if not address:
                for candidate, keys in reversed(
                    await transfer.bridge.device.keystore.get_all()
                ):
                    if (
                        getattr(keys, "link_key", None) is not None
                        and getattr(keys, "ltk", None) is not None
                    ):
                        address = candidate
                        break
            if not address:
                logger.warning("route toggle: no dual-mode bond to connect")
                return
            logger.info("route toggle: connect_source %s", address)
            await transfer.bridge.connect_source(address)
            logger.info("route toggle: classic audio up %s", address)
        elif cmd in ("disconnect", "off", "0"):
            logger.info("route toggle: disconnect_source")
            await transfer.bridge.disconnect_source()
            logger.info("route toggle: classic audio down")
        else:
            logger.warning("route toggle: unknown command %r", cmd)
    except Exception as e:
        logger.warning("route toggle %r failed: %s", cmd, e)


async def _route_toggle_flip():
    """Кнопка: один тумблер — connect, если маршрута нет, иначе disconnect."""
    if transfer is None or getattr(transfer, "bridge", None) is None:
        return
    active = getattr(transfer.bridge, "_source_connection", None) is not None
    await _apply_route_command("disconnect" if active else "connect")


async def _route_command_watcher():
    """Файловый транспорт тумблера: `echo connect|disconnect > /run/carthing/route-cmd`."""
    path = "/run/carthing/route-cmd"
    while True:
        await asyncio.sleep(1.0)
        try:
            with open(path) as f:
                cmd = f.read().strip().lower()
            os.unlink(path)
        except FileNotFoundError:
            continue
        except Exception:
            continue
        await _apply_route_command(cmd)


_speaker_enroll_done = None


def _speaker_enroll_gate():
    """Гейт порядка старта (INVARIANTS п.3): канал к колонке — ДО потока iPhone.

    Если задан CARTHING_PAIR_SPEAKER, classic-дозвон iPhone ждёт исхода enroll
    колонки: иначе iOS переоткрывает A2DP (выбор в Control Center липкий),
    радио занимается потоком и page до колонки даёт PAGE_TIMEOUT.
    """
    global _speaker_enroll_done
    if _speaker_enroll_done is None:
        _speaker_enroll_done = asyncio.Event()
        if not os.environ.get("CARTHING_PAIR_SPEAKER", "").strip():
            _speaker_enroll_done.set()
    return _speaker_enroll_done


async def _resume_bonded_classic_audio():
    """Reconnect the Classic audio/control profile without starting pairing."""
    if os.environ.get("CARTHING_CLASSIC_AUDIO_RECONNECT") != "1":
        return
    if transfer is None or getattr(transfer, "bridge", None) is None:
        return
    try:
        await asyncio.wait_for(_speaker_enroll_gate().wait(), timeout=90.0)
    except asyncio.TimeoutError:
        logger.warning("classic audio reconnect: speaker enroll gate timed out")
    address = _best_bonded_source_address()
    if not address:
        try:
            for candidate, keys in reversed(await transfer.bridge.device.keystore.get_all()):
                if getattr(keys, "link_key", None) is not None and getattr(keys, "ltk", None) is not None:
                    address = candidate
                    break
        except Exception as e:
            logger.warning("classic audio reconnect bond lookup failed: %s", e)
    if not address:
        logger.info("classic audio reconnect skipped: no dual-mode bond")
        return
    # Page при активном BLE-линке (один радиочип) часто даёт PAGE_TIMEOUT —
    # даём BLE-реконнекту устаканиться и ретраим с нарастающей паузой.
    delays = (3.0, 8.0, 15.0)
    for attempt, delay in enumerate(delays, start=1):
        await asyncio.sleep(delay)
        try:
            logger.info("classic audio reconnect: dialing %s (attempt %d/%d)",
                        address, attempt, len(delays))
            await transfer.bridge.connect_source(address)
            logger.info("classic audio reconnect ready: %s", address)
            return
        except Exception as e:
            logger.warning("classic audio reconnect attempt %d failed for %s: %s",
                           attempt, address, e)


async def _pair_speaker_once():
    """Однократный headless-enroll динамика по известному адресу (lab/тесты).

    Колонка должна быть в режиме сопряжения. Инквайри не нужен: адрес задаётся
    через CARTHING_PAIR_SPEAKER, пара идёт сразу transfer.pair_speaker().
    """
    gate = _speaker_enroll_gate()
    address = os.environ.get("CARTHING_PAIR_SPEAKER", "").strip()
    if not address or transfer is None:
        gate.set()
        return
    # Колонка парится ПЕРВОЙ (гейт держит classic-дозвон iPhone), но BLE-реконнект
    # iPhone идёт сам — даём ему короткую фору и ретраим page с паузами.
    try:
        delays = (4.0, 10.0, 20.0)
        for attempt, delay in enumerate(delays, start=1):
            await asyncio.sleep(delay)
            try:
                logger.info("speaker enroll: pairing %s (attempt %d/%d)",
                            address, attempt, len(delays))
                await transfer.pair_speaker(address)
                status = getattr(transfer.bridge.state, "speaker_pairing_status", "")
                logger.info("speaker enroll finished: %s status=%s", address, status)
                if status != "error":
                    return
            except Exception as e:
                logger.warning("speaker enroll attempt %d failed for %s: %s",
                               attempt, address, e)
    finally:
        gate.set()


async def main():
    global orch, gui, transfer, backchannel, iap2, settings, hw_caps, mac, power, session_runner, link_manager, hci_gate, route_patchbay
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
        orch = AccessoryOrchestrator(device, on_phase_change=lambda p: logger.info("phase=%s", p),
                                     hci_gate=hci_gate)
        orch.install()  # CTKD pairing config + classic enabled (для CTKD)
        # [CLAUDE 2026-06-04] CoD до power_on() — iOS запоминает CoD при ПЕРВОМ сопряжении.
        # Если CoD=0 в момент pairing, iPhone не поймёт что это аудиоустройство и не покажет
        # в списке аудиовыходов. 0x240414 = Audio/Video Major + Loudspeaker minor + Audio service.
        from a2dp_bridge import COD_AUDIO_LOUDSPEAKER
        device.class_of_device = COD_AUDIO_LOUDSPEAKER

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
    # На macOS: WebDisplay через браузер (env CAR_THING_WEB_DISPLAY=1, рекомендуется)
    #           MacDisplay через pygame (env CAR_THING_MAC_DISPLAY=1)
    _gui_enabled = os.environ.get("CARTHING_GUI_ENABLE", "1") != "0"
    _use_web_display = os.environ.get("CAR_THING_WEB_DISPLAY") == "1"
    _use_mac_display = os.environ.get("CAR_THING_MAC_DISPLAY") == "1"
    if _gui_enabled and (_use_web_display or _use_mac_display or hw_caps.get("display_drm")):
        try:
            if _use_web_display:
                from web_display import WebDisplay
                _display = WebDisplay()
            elif _use_mac_display:
                from mac_display import MacDisplay, _instance as _mac_instance
                _display = _mac_instance or MacDisplay()
            else:
                from drm_display import DRMDisplay
                _display = DRMDisplay()
            from gui_controller import GuiController
            gui = GuiController(_display,
                                on_command=_on_command, on_pairing=_on_pairing,
                                on_transfer_rescan=_on_transfer_rescan,
                                on_transfer_select=_on_transfer_select,
                                on_speaker_pair_select=_on_speaker_pair_select,
                                on_trusted_remove=_on_trusted_remove,
                                on_notif_dismiss=_on_notif_dismiss,
                                on_session_select=_on_session_select,
                                on_route_input_select=_on_route_input_select,
                                on_route_output_select=_on_route_output_select,
                                on_route_activate=_on_route_activate,
                                on_toggle_sleep=_on_toggle_sleep,
                                on_set_off_timeout=_on_set_off_timeout,
                                on_toggle_notif_blink=_on_toggle_notif_blink,
                                on_set_brightness=_on_set_brightness,
                                on_set_theme=_on_set_theme)
            logger.info("GUI active (modular Compositor)")
            # MacDisplay / WebDisplay: events приходят из ЧУЖОГО потока (pygame main-thread /
            # WS-loop), а gui.handle_input делает asyncio.ensure_future -> маршалим в loop рантайма
            # через call_soon_threadsafe, иначе клики/свайпы падают «attached to a different loop».
            if (_use_mac_display or _use_web_display) and hasattr(_display, "set_on_event"):
                _rt_loop = asyncio.get_event_loop()
                def _gui_input(event):
                    if power is not None:
                        power.note_activity("input")
                    gui.handle_input(event)
                def _on_input(event):
                    _rt_loop.call_soon_threadsafe(_gui_input, event)
                _display.set_on_event(_on_input)
            from power_policy import IdlePowerController
            power = IdlePowerController(settings)
            # [CLAUDE] начальные значения для Settings = реальные из power
            gui.app_state.sleep_on_idle = bool(getattr(power, "enabled", True))
            gui.app_state.screen_off_sec = int(getattr(power, "off_after", 150))
            gui.app_state.notif_blink = bool(settings.get("notif_blink", True))  # [CLAUDE] персист моргания
            gui.app_state.screen_brightness = int(settings.get("screen_brightness_pct", 100))
            import ui_theme as _T
            gui.app_state.ui_theme = _T.THEME      # фактическая активная тема (после импорта)
        except Exception as e:
            gui = None
            logger.warning("GUI disabled: %s", e)
    elif not _gui_enabled:
        logger.info("GUI disabled by CARTHING_GUI_ENABLE=0")

    # Transfer: A2DP relay + backchannel (внутри единого рантайма).
    #
    # Clean Bumble lab uses CARTHING_TRANSFER_ENABLE=0 to prove the BLE/Bumble
    # pairing surface without installing any Classic A2DP/AVRCP SDP records.
    # Production/default stays enabled unless this explicit lab switch is used.
    if os.environ.get("CARTHING_TRANSFER_ENABLE", "1") == "1":
        try:
            from transfer_service import TransferService
            from transfer_control import TransferControlBackchannel
            if gui is not None:
                app_state = gui.app_state
            else:
                from app_state import AppState
                app_state = AppState()
            transfer = TransferService(device, app_state, orch, model, on_change=_on_publish, hci_gate=hci_gate)
            backchannel = TransferControlBackchannel(_emit_source_intent, model=model)
            # Кнопки колонки -> backchannel -> активный источник (finding A2:
            # раньше handler не был подключён, команды умирали в логе моста).
            transfer.bridge.speaker_command_handler = backchannel.handle_speaker_command
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
    else:
        transfer = None
        logger.info("transfer disabled by CARTHING_TRANSFER_ENABLE=0 for clean Bumble lab")

    # iAP2/MFi: Apple accessory слой поверх того же Bumble runtime.
    #
    # Keep it opt-in during dual-mode audio pairing tests. Exposing an iAP2
    # RFCOMM/SDP surface too early can show up on iOS as a generic "Accessory"
    # row and pollute the first-pair experiment.
    if os.environ.get("CARTHING_IAP2_ENABLE") == "1":
        try:
            from iap2_service import IAP2Service
            iap2 = IAP2Service(device)
            await iap2.start()
        except Exception as e:
            iap2 = None
            logger.warning("iAP2 disabled: %s", e)
    else:
        logger.info("iAP2 disabled by default for clean dual-mode audio pairing")

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
    logger.info("apply_visibility done")
    asyncio.create_task(_resume_bonded_classic_audio())
    asyncio.create_task(_pair_speaker_once())
    asyncio.create_task(_route_command_watcher())
    if os.environ.get("CAR_THING_AUTO_PAIRING") == "1":
        if gui is not None:
            gui.set_pairing_mode(True, role="source")
        if power is not None:
            power.set_pairing(True)
        await orch.arm_pairing(True, disconnect_current=False,
                               classic_discoverable=False)
        logger.info("auto pairing armed (CAR_THING_AUTO_PAIRING=1)")
    asyncio.ensure_future(orch.kick_reconnect())
    logger.info("kick_reconnect scheduled")

    # Рендер-цикл — ОТДЕЛЬНАЯ задача (не зависит от input.start, который блокирует loop).
    async def _render_loop():
        tick = 0
        logger.info("_render_loop started, gui=%s power=%s", gui, power)
        while True:
            try:
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
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("_render_loop error: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

    asyncio.ensure_future(_render_loop())

    # Физический ввод (энкодер/кнопки/тач) -> GUI (параллельно рендеру).
    if gui is not None:
        try:
            import input_handler
            def _on_input(event):
                if power is not None:
                    power.note_activity("input")
                # [CLAUDE 2026-06-11] кнопка 1 ОСВОБОЖДЕНА: тумблер маршрута переехал
                # на экранную кнопку (route_activate в нижнем баре Routes).
                # Headless-режим ниже сохраняет btn_1 (там экрана нет).
                gui.handle_input(event)
            asyncio.ensure_future(input_handler.start(on_event=_on_input))
        except Exception as e:
            logger.warning("input disabled: %s", e)
    else:
        # Headless: пресет-кнопка 1 = тумблер маршрута (решение владельца 2026-06-10).
        try:
            import input_handler

            def _on_headless_input(event):
                if event == "btn_1":
                    logger.info("route toggle: button 1 pressed")
                    asyncio.create_task(_route_toggle_flip())

            asyncio.ensure_future(input_handler.start(on_event=_on_headless_input))
            logger.info("headless input: button 1 = route toggle")
        except Exception as e:
            logger.warning("headless input disabled: %s", e)

    logger.info("runtime up — name=%s", identity_service.visible_name())
    await asyncio.get_event_loop().create_future()   # работать вечно


if __name__ == "__main__":
    if os.environ.get("CAR_THING_MAC_DISPLAY") == "1":
        from mac_display import MacDisplay, run_with_display
        MacDisplay()
        run_with_display(main)
    else:
        asyncio.run(main())
