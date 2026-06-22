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
import subprocess
import time

# Часы: CTS синкает системное время в UTC -> выставляем локальную зону для strftime.
os.environ.setdefault("TZ", os.environ.get("CARTHING_TZ", "MSK-3"))  # Москва UTC+3, без DST
try:
    time.tzset()
except Exception:
    pass

_BOOT_PROFILE_ENABLED = os.environ.get("CARTHING_BOOT_PROFILE", "1") != "0"
_BOOT_PROFILE_T0 = time.monotonic()
_BOOT_IMPORT_EVENTS = []


def _record_import(label: str, start: float) -> None:
    if _BOOT_PROFILE_ENABLED:
        _BOOT_IMPORT_EVENTS.append(
            (label, time.monotonic() - start, time.monotonic() - _BOOT_PROFILE_T0)
        )

_t_import = time.monotonic()
import runtime_paths  # noqa: F401  (ставит sys.path)
_record_import("runtime_paths", _t_import)

_t_import = time.monotonic()
import state_paths
_record_import("state_paths", _t_import)

_t_import = time.monotonic()
import identity_service
_record_import("identity_service", _t_import)

_t_import = time.monotonic()
import operation_mode
_record_import("operation_mode", _t_import)

_t_import = time.monotonic()
from runtime_model import RuntimeModel
_record_import("runtime_model", _t_import)

_t_import = time.monotonic()
from link_manager import LinkAdapter, LinkManager
_record_import("link_manager", _t_import)

_t_import = time.monotonic()
from route_graph import Protocol
_record_import("route_graph", _t_import)

_t_import = time.monotonic()
from route_planner import RoutePlanError, RoutePlanner
_record_import("route_planner", _t_import)

_t_import = time.monotonic()
from session_runner import AdapterConnector, SessionRunner
_record_import("session_runner", _t_import)

_t_import = time.monotonic()
from trusted_device_registry import TrustedDeviceRegistry
_record_import("trusted_device_registry", _t_import)

_t_import = time.monotonic()
from virtual_connectors import HciOperationGate, VirtualRoutePatchBay
_record_import("virtual_connectors", _t_import)
del _t_import

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("carthing_runtime")


def _boot_profile_uptime() -> float | None:
    try:
        with open("/proc/uptime", "r", encoding="ascii") as fh:
            return float(fh.read().split()[0])
    except Exception:
        return None


def _boot_milestone(milestone: str, **fields) -> None:
    if not _BOOT_PROFILE_ENABLED:
        return
    uptime = _boot_profile_uptime()
    parts = [f"BOOT_PROFILE milestone={milestone}"]
    if uptime is not None:
        parts.append(f"proc_uptime_s={uptime:.3f}")
    parts.append(f"runtime_s={time.monotonic() - _BOOT_PROFILE_T0:.3f}")
    for key, value in fields.items():
        safe = str(value).replace(" ", "_")
        parts.append(f"{key}={safe}")
    logger.info(" ".join(parts))


def _boot_import_milestones() -> None:
    if not _BOOT_PROFILE_ENABLED:
        return
    uptime = _boot_profile_uptime()
    for module, duration, runtime_at_end in _BOOT_IMPORT_EVENTS:
        parts = [
            f"BOOT_PROFILE_IMPORT module={module}",
            f"duration_s={duration:.3f}",
            f"runtime_s={runtime_at_end:.3f}",
        ]
        if uptime is not None:
            parts.insert(1, f"proc_uptime_s={uptime:.3f}")
        logger.info(" ".join(parts))


_boot_import_milestones()
_boot_milestone("runtime.module_loaded")

RENDER_INTERVAL = 0.2   # с: рендер-тик (живой прогресс на экране)
PUBLISH_EVERY = 5       # каждые N тиков писать runtime-bt.json (~1 с)

orch = None                 # AccessoryOrchestrator
model = RuntimeModel()
_boot_milestone("runtime.model_ready")
_iphone = None              # IPhoneService
gui = None
transfer = None          # TransferService
backchannel = None       # TransferControlBackchannel
iap2 = None              # IAP2Service
settings = None          # SettingsService
hw_caps = {}             # hardware_inventory.probe()
resource_policy = None   # RuntimeResourcePolicy
mac = None               # MacService
session_plane = None     # SessionPlaneService: per-peer CTSP/GATT/L2CAP runtime cells
power = None             # IdlePowerController
session_runner = None    # SessionRunner
link_manager = None      # LinkManager
hci_gate = None          # HciOperationGate
route_patchbay = None    # VirtualRoutePatchBay
remote_mic_process = None
_classic_probe_done = set()
ACTIVE_ROUTE_PROTOCOLS = {
    Protocol.CLASSIC_A2DP_SINK,
    Protocol.CLASSIC_A2DP_SOURCE,
    Protocol.CLASSIC_AVRCP,
}



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
            for row in app_state.trusted_sources:
                address = row.get("address")
                if address:
                    return address
        except Exception:
            pass
    try:
        from app_state import _bonded_source_rows
        for row in _bonded_source_rows():
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
    if role in ("input", "source"):
        async def _run_input_pairing():
            if enabled:
                if transfer is not None:
                    await transfer.stop_speaker_enrollment()
                if orch is not None:
                    # Add Device/Input must stay visible even while the Play
                    # Now phone keeps the LE control link. This controller
                    # rejects legacy BLE advertising in that state, so the safe
                    # no-disconnect surface is BR/EDR discoverable with the
                    # same runtime identity name.
                    await orch.arm_pairing(True, classic_discoverable=True)
            else:
                if transfer is not None:
                    await transfer.stop_speaker_enrollment()
                if orch is not None:
                    await orch.arm_pairing(False)
        asyncio.ensure_future(_run_input_pairing())
    elif role in ("output", "speaker", "device"):
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
        if gui is not None:
            try:
                gui.app_state.remove_trusted(address)
                gui.app_state.save_trusted()
                _recompute_route_compat()
            except Exception as exc:
                logger.warning("trusted registry remove failed: %s", exc)
        try:
            from app_state import normalize_address
            if normalize_address(getattr(model, "speaker_name", "")) == normalize_address(address):
                model.speaker_name = None
                model.speaker_connected = False
                model.audio_sink = "builtin"
                model.mode_status = "standby"
                _on_publish()
        except Exception:
            pass
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


def _bind_bridge_app_state():
    if gui is None or transfer is None or getattr(transfer, "bridge", None) is None:
        return
    if transfer.bridge.state is not gui.app_state:
        transfer.bridge.state = gui.app_state


def _select_boot_play_now(app_state):
    try:
        self_key = getattr(app_state, "SELF_OUTPUT_KEY", "carthing")
        app_state.select_route_output(self_key)
        app_state.select_active_route_output(self_key)
    except Exception as exc:
        logger.warning("boot Play Now selection failed: %s", exc)


def _mode_resource_snapshot(mode=None):
    mode = operation_mode.normalize(mode or getattr(model, "operation_mode", operation_mode.DEFAULT))
    resources = operation_mode.resources(mode).as_dict()
    if transfer is not None and hasattr(transfer, "resource_state"):
        try:
            resources.update(transfer.resource_state())
        except Exception as exc:
            logger.info("mode resource snapshot ignored transfer state: %s", exc)
    if route_patchbay is not None:
        try:
            resources["actual_route_patchbay"] = bool(route_patchbay.current_cables())
        except Exception:
            resources["actual_route_patchbay"] = False
    return resources


def _apply_resource_policy(mode=None, reason=""):
    if resource_policy is None:
        return
    try:
        policy = resource_policy.apply(
            mode or getattr(model, "operation_mode", operation_mode.DEFAULT),
            tier=getattr(model, "power_tier", ""),
            reason=reason,
        )
        model.set_resource_policy(policy)
    except Exception as exc:
        logger.info("resource policy apply ignored: %s", exc)


async def _apply_operation_mode(mode, persist=False, reason=""):
    mode = operation_mode.normalize(mode)
    if gui is not None:
        try:
            gui.app_state.operation_mode = mode
        except Exception:
            pass
    if settings is not None and persist:
        settings.set("operation_mode", mode)
    if transfer is not None and hasattr(transfer, "apply_operation_mode"):
        await transfer.apply_operation_mode(mode, reason=reason)
    else:
        model.set_operation_mode(mode, operation_mode.resources(mode).as_dict())
    if mode != operation_mode.COMMUTATOR:
        if route_patchbay is not None:
            try:
                await route_patchbay.deactivate()
            except Exception as exc:
                logger.warning("mode teardown: patchbay deactivate failed: %s", exc)
        if session_runner is not None:
            try:
                await session_runner.stop_current()
            except Exception as exc:
                logger.warning("mode teardown: session stop failed: %s", exc)
        model.clear_route_plan()
    resources = _mode_resource_snapshot(mode)
    model.set_operation_mode(mode, resources)
    _apply_resource_policy(mode, reason=reason or "operation_mode")
    _boot_milestone("mode.applied", mode=mode, reason=reason or "-")
    logger.info("operation mode applied: mode=%s reason=%s resources=%s", mode, reason or "-", resources)
    _on_publish()


def _unsupported_route_protocols(plan):
    return [
        protocol for protocol in plan.required_protocols
        if protocol not in ACTIVE_ROUTE_PROTOCOLS
    ]


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
        await _apply_operation_mode(operation_mode.PLAYNOW, persist=True, reason="route_empty")
        model.audio_sink = "builtin"
        _on_publish()
        return

    # 3) Выход = сам Car Thing -> Play Now (control по BLE), без A2DP/patchbay.
    if route_output == getattr(app_state, "SELF_OUTPUT_KEY", "carthing"):
        await _apply_operation_mode(operation_mode.PLAYNOW, persist=True, reason="route_playnow")
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
    unsupported = _unsupported_route_protocols(routed)
    if unsupported:
        readable = ", ".join(str(item.value if hasattr(item, "value") else item) for item in unsupported)
        logger.warning("route rejected: transport adapter not implemented for %s", readable)
        _on_publish()
        return
    await _apply_operation_mode(operation_mode.COMMUTATOR, persist=True, reason="route_external")
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
        plan = RoutePlanner(registry).plan_simple_route(ri, ro, name="probe")
        unsupported = _unsupported_route_protocols(plan)
        if unsupported:
            raise RoutePlanError(
                "transport adapter not implemented for "
                + ", ".join(str(item.value if hasattr(item, "value") else item) for item in unsupported)
            )
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
    _bind_bridge_app_state()
    self_key = getattr(gui.app_state, "SELF_OUTPUT_KEY", "carthing")
    lineout_key = getattr(gui.app_state, "LINEOUT_OUTPUT_KEY", "carthing-lineout")
    if key == lineout_key:
        if os.environ.get("CARTHING_EXPERIMENTAL_LINEOUT_ENABLE") != "1":
            gui.app_state.select_active_route_output(self_key)
            transfer.bridge.state.select_active_route_output(self_key)
            await transfer.bridge.stop_receiver_stream()
            transfer.bridge.local_sink_enabled = False
            model.audio_sink = "builtin"
            logger.warning("route output line-out ignored: local T9015 audio is disabled for release")
            _on_publish()
            return
        # Experimental lab path only: local T9015 sink is not a release output
        # on this hardware build because the analog line-out is not populated.
        gui.app_state.select_active_route_output(lineout_key)
        transfer.bridge.state.select_active_route_output(lineout_key)
        await transfer.bridge.stop_receiver_stream()
        transfer.bridge.local_sink_enabled = True
        model.audio_sink = "lineout"
        logger.info("ТРУБА: выход = experimental Car Thing line-out (T9015)")
        await transfer.bridge.ensure_source_codec_matches_route()
        _on_publish()
        return
    transfer.bridge.local_sink_enabled = False
    if key and key != self_key:
        if operation_mode.normalize(getattr(model, "operation_mode", operation_mode.DEFAULT)) != operation_mode.COMMUTATOR:
            await _apply_operation_mode(operation_mode.COMMUTATOR, persist=True, reason="route_output")
        try:
            gui.app_state.select_active_route_output(key)
            transfer.bridge.state.select_active_route_output(key)
            transfer.bridge.allow_standby_address(key, reason="route-output")
        except Exception as e:
            logger.warning("select speaker %s failed: %s", key, e)
        # [CLAUDE 2026-06-11] НЕ обзваниваем ВСЕ колонки на [LNK]: page выключенной
        # занимает контроллер ~5 c, и следующий за ним connect_source(iPhone)
        # отлетает с HCI 0x12 (один page за раз) -> «маршрут не переключается».
        # Целевую колонку поднимает request_receiver_connection; остальными
        # занимается standby-петля по своему расписанию.
        await transfer.bridge.request_receiver_connection(key, force=True)
        await transfer.bridge.ensure_source_codec_matches_route()
        model.audio_sink = "speaker"
        logger.info("ТРУБА: выход = %s (динамик) — поток льётся туда", key)
    else:
        if operation_mode.normalize(getattr(model, "operation_mode", operation_mode.DEFAULT)) != operation_mode.PLAYNOW:
            await _apply_operation_mode(operation_mode.PLAYNOW, persist=True, reason="route_output")
        try:
            gui.app_state.select_active_route_output(self_key)
            transfer.bridge.state.select_active_route_output(self_key)
        except Exception as e:
            logger.warning("select Play Now failed: %s", e)
        await transfer.bridge.stop_receiver_stream()
        model.audio_sink = "builtin"
        logger.info("ТРУБА: выход = Play Now — поток на динамик НЕ льётся")
    _on_publish()


def _on_route_output_select(key):
    # [CLAUDE 2026-06-11] Тап по выходу = ТОЛЬКО выбор (пассивный). Раньше выбор
    # сразу применял маршрут (_apply_route_output) -> «иногда ткнёшь на выход и он
    # включается, на другой ждёшь [LNK]» (бардак, слова владельца). Применяет
    # ТОЛЬКО [LNK] (route_activate). Желаемое != фактическое (см. RUNBOOK №5).
    if power is not None:
        power.note_activity("route_output_select")
    if gui is not None:
        gui.app_state.select_route_output(key)
        gui.app_state.save_trusted()
        _recompute_route_compat()
        _on_publish()
    logger.info("route output selected (passive): %s", key)


def _selected_route_row(rows, key):
    from app_state import normalize_address
    key = str(key or "").strip()
    needle = key.split(":", 1)[1] if key.startswith("source:") else key
    needle = normalize_address(needle)
    for row in rows or []:
        row_key = str(row.get("key") or row.get("address") or "").strip()
        route_device_key = str(row.get("route_device_key") or row.get("device_key") or "").strip()
        row_addr = normalize_address(row.get("address") or "")
        if key and (row_key == key or route_device_key == key or row_addr == needle or f"source:{row_addr}" == key):
            return row
    return None


def _route_selected_source_present(app_state):
    row = _selected_route_row(getattr(app_state, "route_inputs", []), getattr(app_state, "route_input", ""))
    if row is None:
        return False
    return bool(row.get("connected") or row.get("online") or row.get("presence_state") in {"seen", "attached", "present_unrouted", "standby", "route_active"})


def _route_selected_sink_present(app_state):
    ro = str(getattr(app_state, "route_output", "") or "").strip()
    if not ro:
        return False
    if ro == getattr(app_state, "SELF_OUTPUT_KEY", "carthing"):
        return True
    row = _selected_route_row(getattr(app_state, "route_outputs", []), ro)
    if row is None:
        return False
    return bool(row.get("connected") or row.get("online") or row.get("presence_state") in {"seen", "attached", "present_unrouted", "standby", "route_active"})


def _on_route_view_open():
    if power is not None:
        power.note_activity("route_view_open")
    asyncio.ensure_future(_refresh_route_availability(reason="view_open", selected_only=False))


def _on_route_check():
    if power is not None:
        power.note_activity("route_check")
    asyncio.ensure_future(_refresh_route_availability(reason="route_check", selected_only=True))
    return None


async def _refresh_route_availability(reason="route_check", selected_only=True):
    if gui is None:
        return
    app_state = gui.app_state
    if reason == "route_check":
        app_state.begin_route_check()
    try:
        ro = str(getattr(app_state, "route_output", "") or "").strip()
        self_key = getattr(app_state, "SELF_OUTPUT_KEY", "carthing")
        external_output = bool(ro and ro != self_key)
        external_audio_output = bool(app_state.route_speaker_address())
        if transfer is not None and getattr(transfer, "bridge", None) is not None:
            bridge = transfer.bridge
            if selected_only and external_output and external_audio_output:
                bridge.allow_standby_address(ro, reason=reason)
                try:
                    await bridge.request_receiver_connection(ro, force=True)
                except Exception as exc:
                    logger.info("route check receiver probe failed: %s", exc)
            else:
                try:
                    await bridge.refresh_standby_snapshot(duration=3.0)
                except Exception as exc:
                    logger.info("route availability snapshot ignored: %s", exc)
        _recompute_route_compat()
        if reason == "route_check":
            source_ok = _route_selected_source_present(app_state)
            sink_ok = _route_selected_sink_present(app_state)
            compat_ok = getattr(app_state, "route_compatible", None) is not False
            ok = bool(source_ok and sink_ok and compat_ok)
            if ok:
                message = "Маршрут готов"
            elif not compat_ok:
                message = "Для этого пути ещё нет активного adapter"
            elif not source_ok:
                message = "Источник сейчас не на связи"
            elif not sink_ok:
                message = "Назначение сейчас не на связи"
            else:
                message = "Маршрут недоступен"
            app_state.finish_route_check(ok=ok, message=message)
            logger.info(
                "route check result: ok=%s source=%s sink=%s compat=%s route=%s->%s",
                ok,
                source_ok,
                sink_ok,
                compat_ok,
                getattr(app_state, "route_input", ""),
                getattr(app_state, "route_output", ""),
            )
        _on_publish()
        if gui is not None:
            gui.render()
    except Exception as exc:
        logger.warning("route availability refresh failed: %s", exc)
        if reason == "route_check":
            app_state.finish_route_check(ok=False, message="Проверка маршрута сорвалась")
        _on_publish()


def _on_route_activate():
    # [CLAUDE 2026-06-11 v2] Кнопка [LNK] — НЕ toggle (решение владельца): она ТОЛЬКО
    # включает ВЫБРАННЫЙ маршрут. Гашение старого — фоновая обязанность системы:
    #   выход = колонка   -> применить выход + поднять classic-трубу (если не стоит)
    #   выход = Play Now  -> закрыть поток к колонке + опустить classic-трубу
    # Так смена маршрута = выбрал вход/выход -> [LNK]; никаких подвешенных состояний
    # от «случайного выключения» повторным тапом.
    if power is not None:
        power.note_activity("route_activate")
    asyncio.ensure_future(_activate_selected_route_output())


async def _activate_selected_route_output():
    if gui is None or transfer is None or getattr(transfer, "bridge", None) is None:
        return
    ro = str(getattr(gui.app_state, "route_output", "") or "").strip()
    self_key = getattr(gui.app_state, "SELF_OUTPUT_KEY", "carthing")
    lineout_key = getattr(gui.app_state, "LINEOUT_OUTPUT_KEY", "carthing-lineout")
    lineout_enabled = os.environ.get("CARTHING_EXPERIMENTAL_LINEOUT_ENABLE") == "1"
    external_output = bool(ro and ro != self_key and (ro != lineout_key or lineout_enabled))
    if external_output and ro != lineout_key and not gui.app_state.route_speaker_address():
        gui.app_state.finish_route_check(ok=False, message="Для этого назначения ещё нет audio adapter")
        logger.warning("route activate rejected: selected destination has no active audio adapter: %s", ro)
        _on_publish()
        if gui is not None:
            gui.render()
        return
    await _apply_operation_mode(
        operation_mode.COMMUTATOR if external_output else operation_mode.PLAYNOW,
        persist=True,
        reason="route_activate",
    )
    await _apply_route_output(ro)
    # [CLAUDE 2026-06-11] СЕРИАЛИЗАЦИЯ page: если колонка ещё дозванивается,
    # ждём её таск — контроллер делает только один page за раз, параллельный
    # connect_source отлетает с HCI 0x12.
    task_getter = getattr(transfer.bridge, "_selected_receiver_connect_task", None)
    task = task_getter() if callable(task_getter) else None
    if task is not None and not task.done():
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=20)
        except Exception:
            pass
    source_up = getattr(transfer.bridge, "_source_connection", None) is not None
    if external_output:
        if not source_up:
            await _apply_route_command("connect")
    else:
        if source_up:
            await _apply_route_command("disconnect")


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


def _remote_mic_sender_args():
    script = os.environ.get("CARTHING_REMOTE_MIC_SENDER", "/usr/lib/carthing/remote_mic_sender.py")
    host = os.environ.get("CARTHING_MIC_HOST", "172.16.42.1")
    port = os.environ.get("CARTHING_MIC_PORT", "49321")
    device = os.environ.get("CARTHING_MIC_PCM_DEV", "/dev/snd/pcmC0D1c")
    rate = os.environ.get("CARTHING_MIC_RATE", "48000")
    channels = os.environ.get("CARTHING_MIC_CHANNELS", "2")
    return [
        "python3",
        script,
        "--host", host,
        "--port", port,
        "--device", device,
        "--rate", rate,
        "--channels", channels,
    ]


def _remote_mic_sender_running():
    return remote_mic_process is not None and remote_mic_process.poll() is None


def _remote_mic_transport(enabled):
    return "usb_ncm_tcp" if enabled and _remote_mic_sender_running() else "none"


async def _remote_mic_sender_monitor(process):
    global remote_mic_process
    while True:
        await asyncio.sleep(1.0)
        if process is not remote_mic_process:
            return
        if process.poll() is not None:
            break
    still_enabled = bool(
        (gui is not None and getattr(gui.app_state, "remote_mic_enabled", False))
        or (settings is not None and settings.get("client_enabled", False))
    )
    if process is remote_mic_process:
        remote_mic_process = None
    if gui is not None and still_enabled:
        gui.app_state.set_remote_mic(
            True,
            state="reconnecting",
            message="Переподключаю Mac mic",
        )
    model.set_remote_mic(
        True,
        state="reconnecting" if still_enabled else "unavailable",
        message=f"remote mic sender exited rc={process.returncode}",
        transport="none",
    )
    logger.warning("remote mic sender exited early: rc=%s", process.returncode)
    _on_publish()
    if still_enabled:
        retry_sec = float(os.environ.get("CARTHING_MIC_RETRY_SEC", "2.0"))
        asyncio.get_event_loop().call_later(retry_sec, _start_remote_mic_sender)


def _start_remote_mic_sender():
    global remote_mic_process
    if _remote_mic_sender_running():
        return True
    args = _remote_mic_sender_args()
    try:
        remote_mic_process = subprocess.Popen(
            args,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except Exception as exc:
        logger.warning("remote mic sender start failed: %s", exc)
        remote_mic_process = None
        return False
    logger.info("remote mic sender started pid=%s args=%s", remote_mic_process.pid, " ".join(args))
    asyncio.ensure_future(_remote_mic_sender_monitor(remote_mic_process))
    return True


def _stop_remote_mic_sender():
    global remote_mic_process
    process = remote_mic_process
    remote_mic_process = None
    if process is None or process.poll() is not None:
        return
    logger.info("remote mic sender stopping pid=%s", process.pid)
    try:
        process.terminate()
    except Exception:
        return

    async def _finish_stop():
        await asyncio.sleep(0.8)
        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
    asyncio.ensure_future(_finish_stop())


def _on_toggle_client(on):
    # Minimal PlayNow branch: the old CTSP client toggle is now the user-visible
    # "Mac microphone" switch. It must default to the Bluetooth session plane,
    # not to the USB/NCM fallback; the fallback is a lab escape hatch only.
    enabled = bool(on)
    usb_fallback = os.environ.get("CARTHING_USB_REMOTE_MIC_ENABLE", "0") == "1"
    sender_ok = _start_remote_mic_sender() if enabled and usb_fallback else True
    if not enabled or not usb_fallback:
        _stop_remote_mic_sender()
    state = "listening" if enabled and sender_ok else ("unavailable" if enabled else "off")
    ui_message = (
        ("USB/NCM fallback -> Mac" if usb_fallback else "Bluetooth mic session")
        if enabled and sender_ok else
        ("Mac agent недоступен" if enabled else "Микрофон Mac выключен")
    )
    if gui is not None:
        gui.app_state.set_remote_mic(
            enabled,
            state=state,
            message=ui_message,
        )
    model.set_remote_mic(
        enabled,
        state=state,
        message=ui_message,
        transport=_remote_mic_transport(enabled) if usb_fallback else ("ble_l2cap_coc" if enabled else "none"),
    )
    if session_plane is not None:
        session_plane.set_enabled(enabled)
    if orch is not None:
        asyncio.ensure_future(orch.set_session_advertising(enabled))
    if settings is not None:
        settings.set("client_enabled", enabled)
    logger.info("remote mic/session plane -> %s sender=%s", "on" if enabled else "off", sender_ok)
    _on_publish()


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


def _on_power_off():
    # Product power action: prepare state for physical USB removal.
    # Do not use Linux poweroff/halt/sysrq on this hardware.
    import power_control
    app_state = gui.app_state if gui is not None else None
    if getattr(app_state, "power_unplug_status", "") == "preparing":
        logger.warning("safe unplug already preparing")
        return
    if app_state is not None:
        app_state.power_unplug_status = "preparing"
        app_state.power_unplug_message = "Готовим..."
    logger.warning("safe unplug requested")
    async def _run():
        try:
            await _apply_operation_mode(operation_mode.PLAYNOW, persist=True, reason="safe_unplug")
        except Exception as exc:
            logger.warning("safe unplug mode teardown ignored: %s", exc)
        await power_control.prepare_for_usb_unplug(
            transfer=transfer,
            power=power,
            state=app_state,
        )
    asyncio.ensure_future(_run())


def _on_set_mode(new):
    # Выбрать конкретный product-mode из настроек.
    # Все ресурсные эффекты идут через единый apply-путь, чтобы boot/routes/settings
    # не расходились между собой.
    if new not in operation_mode.ALL:
        return
    logger.info("operation mode request -> %s", new)
    asyncio.ensure_future(_apply_operation_mode(new, persist=True, reason="settings"))


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


def _sync_model_route_selection():
    if gui is None:
        return
    try:
        app_state = gui.app_state
        model.route_input = str(getattr(app_state, "route_input", "") or "")
        model.route_output = str(getattr(app_state, "active_route_output", "") or "")
        mic_enabled = bool(getattr(app_state, "remote_mic_enabled", getattr(app_state, "client_enabled", False)))
        model.set_remote_mic(
            mic_enabled,
            state=getattr(app_state, "remote_mic_state", None),
            message=getattr(app_state, "remote_mic_message", None),
            transport=_remote_mic_transport(mic_enabled),
        )
        model.route_builder = _route_builder_snapshot(app_state)
    except Exception:
        pass


def _route_builder_row(row):
    endpoints = row.get("endpoints") or []
    protocols = set(str(value) for value in (row.get("protocols") or []))
    capabilities = set(str(value) for value in (row.get("capabilities") or []))
    for endpoint in endpoints:
        protocols.update(str(value) for value in (endpoint.get("protocols") or []))
        capabilities.update(str(value) for value in (endpoint.get("capabilities") or []))
    return {
        "key": row.get("key") or row.get("address") or "",
        "route_device_key": row.get("route_device_key") or row.get("device_key") or "",
        "address": row.get("address") or "",
        "label": row.get("label") or row.get("name") or row.get("address") or "",
        "type": row.get("type") or "",
        "endpoint_id": row.get("endpoint_id") or "",
        "endpoint_label": row.get("endpoint_label") or "",
        "endpoint_direction": row.get("endpoint_direction") or row.get("direction") or "",
        "endpoint_plane": row.get("endpoint_plane") or row.get("plane") or "",
        "protocols": sorted(protocols),
        "capabilities": sorted(capabilities),
        "online": bool(row.get("online")),
        "connected": bool(row.get("connected")),
        "presence_state": row.get("presence_state") or "",
    }


def _route_builder_snapshot(app_state):
    return {
        "step": str(getattr(app_state, "route_builder_step", "source") or "source"),
        "transport": str(getattr(app_state, "route_transport", "auto") or "auto"),
        "check_state": str(getattr(app_state, "route_check_state", "idle") or "idle"),
        "check_message": str(getattr(app_state, "route_check_message", "") or ""),
        "compatible": getattr(app_state, "route_compatible", None),
        "selected_source": str(getattr(app_state, "route_input", "") or ""),
        "selected_sink": str(getattr(app_state, "route_output", "") or ""),
        "active_sink": str(getattr(app_state, "active_route_output", "") or ""),
        "sources": [_route_builder_row(row) for row in getattr(app_state, "route_inputs", [])],
        "sinks": [_route_builder_row(row) for row in getattr(app_state, "route_outputs", [])],
        "availability": list(getattr(app_state, "route_availability_snapshot", lambda: [])()),
    }


def _on_publish():
    _sync_model_route_selection()
    try:
        model.set_operation_mode(
            getattr(model, "operation_mode", operation_mode.DEFAULT),
            _mode_resource_snapshot(getattr(model, "operation_mode", operation_mode.DEFAULT)),
        )
    except Exception:
        pass
    if resource_policy is not None:
        try:
            model.set_resource_policy(resource_policy.snapshot(
                mode=getattr(model, "operation_mode", operation_mode.DEFAULT),
                tier=getattr(model, "power_tier", ""),
                reason="publish",
            ))
        except Exception:
            pass
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
        peer_addr = None
        try:
            from app_state import normalize_address as _norm
            peer_addr = _norm(str(connection.peer_address))
            if gui is not None and peer_addr and gui.app_state.is_trusted_device(peer_addr):
                gui.app_state.note_peer_presence(
                    address=peer_addr,
                    event="incoming_attach",
                    plane="audio",
                    transport="classic",
                    detail="classic_connection",
                )
        except Exception:
            pass
        if transfer is not None:
            await transfer.on_incoming_classic(connection)
        if (
            os.environ.get("CARTHING_PAIRING_PRIMARY", "").lower() == "classic"
            and getattr(orch, "pairing_armed", False)
        ):
            # CTKD — только для НОВЫХ источников. Доверенная колонка, переподключившаяся
            # в окно пары, в SMP не умеет (цикл 4 A3: SMP-запрос улетал в Fosi).
            try:
                from app_state import normalize_address as _norm
                peer_addr = peer_addr or _norm(str(connection.peer_address))
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

    if session_plane is not None and session_plane.on_connection(connection):
        if gui is not None:
            gui.set_pairing_mode(False)
        if power is not None:
            power.set_pairing(False)
        _on_publish()
        return

    from iphone_service import IPhoneService
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
                    # AMS/ANCS evidence belongs only to the current encrypted LE
                    # peer. Updating every trusted source made a bonded Mac look
                    # like an iPhone after reboot.
                    from app_state import normalize_address
                    peer = normalize_address(getattr(connection, "peer_address", ""))
                    target = next(
                        (
                            row for row in gui.app_state.trusted_sources
                            if normalize_address(row.get("address")) == peer
                        ),
                        None,
                    )
                    if target is not None and peer:
                        target["label"] = "iPhone"
                        target["type"] = target.get("type") or "Источник"
                        gui.app_state.enroll_trusted_device(
                            peer,
                            name="iPhone",
                            service_uuids={"110a", "audio_source"},
                            ble_services={"ams", "ancs", "1812"},
                            metadata={
                                "enrolled_from": "ble_source_connection",
                                "input_enrolled": True,
                                "probe_stage": "ams_ancs_ready",
                            },
                        )
                        gui.app_state.note_peer_presence(
                            address=peer,
                            event="incoming_attach",
                            plane="audio",
                            transport="ble_gatt",
                            detail="ams_ancs_ready",
                        )
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
    _bind_bridge_app_state()
    try:
        if cmd == "status":
            bridge = transfer.bridge
            selected = None
            try:
                selected = bridge._selected_speaker_connector()
            except Exception:
                selected = None
            logger.info(
                "route status: output=%s pending=%s speaker=%s receiver=%s receiver_codec=%s source_active=%s source_codec=%s "
                "selected=%s selected_codec=%s selected_rtp=%s forwarded=%s dropped=%s transcode_payloads=%s",
                getattr(bridge.state, "active_route_output", ""),
                getattr(bridge.state, "route_output", ""),
                bridge.state.active_route_speaker_address(),
                getattr(bridge, "receiver_address", None),
                getattr(bridge, "receiver_codec_name", None),
                getattr(bridge, "source_stream_active", None),
                getattr(bridge, "source_codec_name", None),
                getattr(selected, "address", None),
                getattr(selected, "codec_name", None),
                bool(getattr(selected, "rtp_channel", None)) if selected is not None else False,
                getattr(bridge, "packets_forwarded", None),
                getattr(bridge, "packets_dropped", None),
                getattr(bridge, "_transcode_payloads_sent", None),
            )
            try:
                tasks = ",".join(
                    runtime.address
                    for runtime in getattr(bridge, "_speaker_runtimes", {}).values()
                    if getattr(runtime, "connect_task", None) is not None and not runtime.connect_task.done()
                ) or "-"
                connectors = []
                for address, runtime in getattr(bridge, "_speaker_runtimes", {}).items():
                    connector = getattr(runtime, "connector", None)
                    if connector is None:
                        continue
                    connectors.append(
                        "%s:acl=%s proto=%s stream=%s rtp=%s codec=%s connecting=%s backoff=%.1f err=%s"
                        % (
                            address,
                            bool(getattr(connector, "connection", None)),
                            bool(getattr(connector, "protocol", None)),
                            bool(getattr(connector, "stream", None)),
                            bool(getattr(connector, "rtp_channel", None)),
                            getattr(connector, "codec_name", "") or "-",
                            bool(getattr(connector, "connecting", False)),
                            max(0.0, getattr(runtime, "backoff_not_before", 0.0) - __import__("time").monotonic()),
                            getattr(connector, "last_error", "") or "-",
                        )
                    )
                logger.info("route connectors: tasks=%s %s", tasks, " | ".join(connectors) or "-")
            except Exception as exc:
                logger.info("route connectors unavailable: %s", exc)
            return
        if cmd.startswith("select "):
            key = cmd.split(None, 1)[1].strip()
            if not key or gui is None:
                logger.warning("route select command ignored: key=%r gui=%s", key, bool(gui))
                return
            selected = gui.app_state.select_route_output(key)
            gui.app_state.save_trusted()
            if not selected:
                logger.warning("route select command unknown output: %s", key)
                return
            _recompute_route_compat()
            _on_publish()
            logger.info("route select command selected pending output: %s", selected)
            return
        if cmd in ("activate", "lnk"):
            await _activate_selected_route_output()
            return
        if cmd.startswith("output "):
            key = cmd.split(None, 1)[1].strip()
            if not key or gui is None:
                logger.warning("route output command ignored: key=%r gui=%s", key, bool(gui))
                return
            selected = gui.app_state.select_route_output(key)
            gui.app_state.save_trusted()
            if not selected:
                logger.warning("route output command unknown output: %s", key)
                return
            logger.info("route output command selected: %s", selected)
            await _apply_route_output(selected)
            task_getter = getattr(transfer.bridge, "_selected_receiver_connect_task", None)
            task = task_getter() if callable(task_getter) else None
            if task is not None and not task.done():
                try:
                    await asyncio.wait_for(asyncio.shield(task), timeout=45)
                except Exception as e:
                    logger.info("route output command receiver wait ended: %s", e)
            self_key = getattr(gui.app_state, "SELF_OUTPUT_KEY", "carthing")
            logger.info(
                "route output command source gate: selected=%s self=%s source_active=%s source_conn=%s",
                selected,
                self_key,
                bool(getattr(transfer.bridge, "source_stream_active", False)),
                bool(getattr(transfer.bridge, "_source_connection", None)),
            )
            if selected != self_key and not getattr(transfer.bridge, "source_stream_active", False):
                receiver_ready = False
                try:
                    connector = transfer.bridge._selected_speaker_connector()
                    receiver_ready = bool(getattr(connector, "rtp_channel", None))
                except Exception:
                    receiver_ready = bool(getattr(transfer.bridge, "receiver_rtp_channel", None))
                logger.info("route output command source gate receiver_ready=%s", receiver_ready)
                if not receiver_ready:
                    logger.warning("route output command source connect deferred: selected receiver not ready")
                    return
                if getattr(transfer.bridge, "_source_connection", None) is not None:
                    logger.info("route output command refreshing stale source leg before connect")
                    await transfer.bridge.disconnect_source()
                await _apply_route_command("connect")
            return
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
            # [CLAUDE 2026-06-12] авто-ретрай (задача №3 ранбука): спящий iPhone
            # отвечает на первый page PAGE_TIMEOUT — будится и со 2-3-й попытки
            # принимает. Паттерн пауз 3/8 c (как ретраи 3/8/15 в fc2cb5e).
            last_exc = None
            for attempt, delay in ((1, 0), (2, 3), (3, 8)):
                if delay:
                    logger.info("route toggle: retry connect in %ds (attempt %d)", delay, attempt)
                    await asyncio.sleep(delay)
                try:
                    logger.info("route toggle: connect_source %s", address)
                    await transfer.bridge.connect_source(address)
                    last_exc = None
                    break
                except Exception as e:
                    last_exc = e
                    text = str(e)
                    if "PAGE_TIMEOUT" not in text and "0x04" not in text.lower():
                        raise            # не «спит» — настоящая ошибка, не маскируем
            if last_exc is not None:
                raise last_exc
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
    """Файловый транспорт:
    `echo connect|disconnect > /run/carthing/route-cmd`
    `echo select AA:BB:CC:DD:EE:FF > /run/carthing/route-cmd`
    `echo output AA:BB:CC:DD:EE:FF > /run/carthing/route-cmd`
    `echo status > /run/carthing/route-cmd`."""
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


def _init_gui_surface():
    global gui, power

    # GUI: один home-surface + views поверх DRM (если дисплей доступен).
    # На macOS: WebDisplay через браузер (env CAR_THING_WEB_DISPLAY=1, рекомендуется)
    #           MacDisplay через pygame (env CAR_THING_MAC_DISPLAY=1)
    _gui_enabled = os.environ.get("CARTHING_GUI_ENABLE", "1") != "0"
    _use_web_display = os.environ.get("CAR_THING_WEB_DISPLAY") == "1"
    _use_mac_display = os.environ.get("CAR_THING_MAC_DISPLAY") == "1"
    if _gui_enabled and (_use_web_display or _use_mac_display or hw_caps.get("display_drm")):
        try:
            if _use_web_display:
                _display_kind = "web"
            elif _use_mac_display:
                _display_kind = "mac"
            else:
                _display_kind = "drm"
            _boot_milestone("gui.display_start", kind=_display_kind)
            if _use_web_display:
                from web_display import WebDisplay
                _display = WebDisplay()
            elif _use_mac_display:
                from mac_display import MacDisplay, _instance as _mac_instance
                _display = _mac_instance or MacDisplay()
            else:
                from drm_display import DRMDisplay
                _display = DRMDisplay()
            _boot_milestone("gui.display_ready", kind=_display_kind)
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
                                on_route_check=_on_route_check,
                                on_route_view_open=_on_route_view_open,
                                on_toggle_sleep=_on_toggle_sleep,
                                on_set_off_timeout=_on_set_off_timeout,
                                on_toggle_notif_blink=_on_toggle_notif_blink,
                                on_set_brightness=_on_set_brightness,
                                on_set_theme=_on_set_theme,
                                on_power_off=_on_power_off,
                                on_set_mode=_on_set_mode,
                                on_toggle_client=_on_toggle_client)
            _boot_milestone("gui.controller_ready")
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
            gui.app_state.client_enabled = bool(settings.get("client_enabled", False))
            gui.app_state.set_remote_mic(
                gui.app_state.client_enabled,
                state="ready" if gui.app_state.client_enabled else "off",
                message="Mac ждёт голосовой канал" if gui.app_state.client_enabled else "Микрофон Mac выключен",
            )
            model.set_remote_mic(
                gui.app_state.client_enabled,
                state="ready" if gui.app_state.client_enabled else "off",
                transport="none",
            )
            import ui_theme as _T
            gui.app_state.ui_theme = _T.THEME      # фактическая активная тема (после импорта)
            _select_boot_play_now(gui.app_state)
            gui.show_home()
            _boot_milestone("gui.ready")
        except Exception as e:
            gui = None
            _boot_milestone("gui.disabled", error=type(e).__name__)
            logger.warning("GUI disabled: %s", e)
    elif not _gui_enabled:
        _boot_milestone("gui.disabled", reason="env")
        logger.info("GUI disabled by CARTHING_GUI_ENABLE=0")


async def main():
    global orch, gui, transfer, backchannel, iap2, settings, hw_caps, resource_policy, mac, session_plane, power, session_runner, link_manager, hci_gate, route_patchbay
    _boot_milestone("runtime.main_start")
    _verify_persistent()
    _boot_milestone("runtime.persistent_verified")

    # Per-boot инвентарь возможностей + настройки.
    import hardware_inventory
    from settings_service import SettingsService
    _boot_milestone("hardware_inventory.start")
    hw_caps = hardware_inventory.probe()
    _boot_milestone("hardware_inventory.ready", enabled_caps=sum(1 for v in hw_caps.values() if v))
    settings = SettingsService()
    _remote_mic_boot_enabled = bool(settings.get("client_enabled", False))
    model.set_remote_mic(
        _remote_mic_boot_enabled,
        state="ready" if _remote_mic_boot_enabled else "off",
        transport="none",
    )
    from resource_policy import RuntimeResourcePolicy
    resource_policy = RuntimeResourcePolicy(settings=settings, hw_caps=hw_caps)
    _apply_resource_policy(operation_mode.current(settings), reason="boot")
    session_runner = SessionRunner()
    hci_gate = HciOperationGate()
    route_patchbay = VirtualRoutePatchBay()
    for protocol in Protocol:
        session_runner.register(CompatibilityConnector(protocol))
    logger.info("hw capabilities: %s", {k: v for k, v in hw_caps.items() if v})
    _init_gui_surface()

    input_scheduled = False

    def _schedule_gui_input(phase="runtime"):
        nonlocal input_scheduled
        if input_scheduled or gui is None:
            return
        try:
            import input_handler

            def _on_input(event):
                if power is not None:
                    power.note_activity("input")
                gui.handle_input(event)

            asyncio.ensure_future(input_handler.start(on_event=_on_input))
            input_scheduled = True
            _boot_milestone("input.scheduled", mode="gui", phase=phase)
        except Exception as e:
            _boot_milestone("input.disabled", error=type(e).__name__, phase=phase)
            logger.warning("input disabled: %s", e)

    # Touch/buttons must not wait for Bluetooth. BLE init can block/retry while
    # the display is already alive, so schedule physical input as soon as GUI exists.
    _schedule_gui_input("early")

    def _configure(device):
        global orch
        _boot_milestone("accessory_orchestrator.import_start")
        from accessory_orchestrator import AccessoryOrchestrator
        _boot_milestone("accessory_orchestrator.import_ready")
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
    _boot_milestone("ble.init_start")
    from ble_transport import init_ble
    _boot_milestone("ble.transport_imported")
    for attempt in range(8):
        try:
            device, _transport = await init_ble(configure_device=_configure)
            _boot_milestone("ble.init_ready", attempt=attempt + 1)
            break
        except OSError as e:
            _boot_milestone("ble.init_retry", attempt=attempt + 1, error=type(e).__name__)
            logger.warning("init_ble attempt %d failed (HCI busy?): %s", attempt + 1, e)
            await asyncio.sleep(3)
    if device is None:
        _boot_milestone("ble.init_failed")
        logger.error("init_ble failed after retries — exiting (supervisor restart)")
        return
    await orch.apply_identity()       # одно имя на все транспорты
    _boot_milestone("identity.applied")

    device.on("connection", lambda c: asyncio.ensure_future(_on_connection(c)))

    # Transfer: A2DP relay + backchannel (внутри единого рантайма).
    #
    # Clean Bumble lab uses CARTHING_TRANSFER_ENABLE=0 to prove the BLE/Bumble
    # pairing surface without installing any Classic A2DP/AVRCP SDP records.
    # Production path stays enabled unless this explicit lab switch is used.
    app_state_for_runtime = gui.app_state if gui is not None else None
    if os.environ.get("CARTHING_TRANSFER_ENABLE", "1") == "1":
        try:
            _boot_milestone("transfer.start")
            from transfer_service import TransferService
            from transfer_control import TransferControlBackchannel
            if gui is not None:
                app_state = gui.app_state
            else:
                from app_state import AppState
                app_state = AppState()
                _select_boot_play_now(app_state)
            app_state_for_runtime = app_state
            app_state.operation_mode = operation_mode.current(settings)  # режим из settings ДО старта циклов
            app_state.client_enabled = bool(settings.get("client_enabled", False))
            app_state.set_remote_mic(
                app_state.client_enabled,
                state="ready" if app_state.client_enabled else "off",
            )
            model.set_remote_mic(
                app_state.client_enabled,
                state="ready" if app_state.client_enabled else "off",
                transport="none",
            )
            model.set_operation_mode(
                app_state.operation_mode,
                operation_mode.resources(app_state.operation_mode).as_dict(),
            )
            logger.info("operation mode: %s", app_state.operation_mode)
            transfer = TransferService(device, app_state, orch, model, on_change=_on_publish, hci_gate=hci_gate)
            backchannel = TransferControlBackchannel(_emit_source_intent, model=model)
            # Кнопки колонки -> backchannel -> активный источник (finding A2:
            # раньше handler не был подключён, команды умирали в логе моста).
            transfer.bridge.speaker_command_handler = backchannel.handle_speaker_command
            await transfer.start()        # SDP + AVDTP listener (видимость ещё перегейтим)
            await _apply_operation_mode(app_state.operation_mode, persist=False, reason="boot")
            for protocol in (
                Protocol.CLASSIC_A2DP_SINK,
                Protocol.CLASSIC_A2DP_SOURCE,
                Protocol.CLASSIC_AVRCP,
            ):
                session_runner.register(TransferRouteConnector(protocol, transfer))
            _boot_milestone("transfer.ready")
        except Exception as e:
            transfer = None
            _boot_milestone("transfer.disabled", error=type(e).__name__)
            logger.warning("transfer disabled: %s", e)
    else:
        transfer = None
        _boot_milestone("transfer.disabled", reason="env")
        logger.info("transfer disabled by CARTHING_TRANSFER_ENABLE=0 for clean Bumble lab")

    # iAP2/MFi: Apple accessory слой поверх того же Bumble runtime.
    #
    # Keep it opt-in during dual-mode audio pairing tests. Exposing an iAP2
    # RFCOMM/SDP surface too early can show up on iOS as a generic "Accessory"
    # row and pollute the first-pair experiment.
    if os.environ.get("CARTHING_IAP2_ENABLE") == "1":
        try:
            _boot_milestone("iap2.start")
            from iap2_service import IAP2Service
            iap2 = IAP2Service(device)
            await iap2.start()
            _boot_milestone("iap2.ready")
        except Exception as e:
            iap2 = None
            _boot_milestone("iap2.disabled", error=type(e).__name__)
            logger.warning("iAP2 disabled: %s", e)
    else:
        _boot_milestone("iap2.disabled", reason="env")
        logger.info("iAP2 disabled by lab switch for clean dual-mode audio pairing")

    # macOS-источник (Фаза 4, каркас).
    _boot_milestone("mac_service.start")
    from mac_service import MacService
    mac = MacService(model, on_update=_on_publish)
    if app_state_for_runtime is None:
        from app_state import AppState
        app_state_for_runtime = AppState()
        _select_boot_play_now(app_state_for_runtime)
    try:
        _boot_milestone("session_plane.start")
        from session_plane_service import SessionPlaneService
        session_plane = SessionPlaneService(
            device,
            app_state_for_runtime,
            model,
            on_change=_on_publish,
            on_client_toggle=_on_toggle_client,
        )
        session_plane.install()
        _boot_remote_mic_enabled = bool(settings.get("client_enabled", False))
        if _boot_remote_mic_enabled:
            _on_toggle_client(True)
        else:
            session_plane.set_enabled(False)
            await orch.set_session_advertising(False)
        _boot_milestone("session_plane.ready", enabled=_boot_remote_mic_enabled)
    except Exception as e:
        session_plane = None
        _boot_milestone("session_plane.disabled", error=type(e).__name__)
        logger.warning("session plane disabled: %s", e)
    trusted_path = getattr(gui.app_state, "trusted_path", None) if gui is not None else None
    trusted_registry = TrustedDeviceRegistry(trusted_path).load()
    link_manager = LinkManager(trusted_registry, interval=15.0)
    if gui is not None:
        link_manager.register(AppStateLinkAdapter(gui.app_state))
        # 2026-06-18 owner decision: trusted-device status is sampled on explicit
        # events, not by a periodic background loop. The current adapter only
        # reflects local AppState flags, but keeping a 15s manager running made
        # the architecture look polling-driven and invited heavier probes later.
        try:
            await link_manager.tick()
        except Exception as exc:
            logger.info("link manager boot tick ignored: %s", exc)
        logger.info("link manager periodic polling disabled; boot tick only")
    # [CLAUDE 2026-06-02] Без режимов: на boot поднимаем присутствие, активного маршрута нет.
    if gui is not None:
        gui.show_home()
    _boot_milestone("mac_service.ready")

    # Видимость — ПОСЛЕ transfer.start(): orchestrator перегейтит classic в not-connectable
    # (никакой открытой A2DP-рекламы; directed-к-bonded / тишина по фазе).
    await orch.apply_visibility()
    _boot_milestone("visibility.applied")
    logger.info("apply_visibility done")
    asyncio.create_task(_resume_bonded_classic_audio())
    asyncio.create_task(_pair_speaker_once())
    asyncio.create_task(_route_command_watcher())
    if os.environ.get("CAR_THING_AUTO_PAIRING") == "1":
        if gui is not None:
            gui.set_pairing_mode(True, role="source")
        if power is not None:
            power.set_pairing(True)
        await orch.arm_pairing(True, classic_discoverable=False)
        logger.info("auto pairing armed (CAR_THING_AUTO_PAIRING=1)")
    asyncio.ensure_future(orch.kick_reconnect())
    _boot_milestone("reconnect.scheduled")
    logger.info("kick_reconnect scheduled")

    # Рендер-цикл — ОТДЕЛЬНАЯ задача (не зависит от input.start, который блокирует loop).
    # [CLAUDE 2026-06-12] GC-тюнинг: рендер порождает горы PIL-объектов; авто-gen2
    # коллекции дают непредсказуемые паузы цикла. Замораживаем стартовую кучу
    # (бессмертные объекты вне обхода) и поднимаем пороги — коллекции реже.
    import gc as _gc
    _gc.collect()
    _gc.freeze()
    _gc.set_threshold(50000, 50, 50)

    _render_inflight = [False]

    def _render_in_thread():
        try:
            _t0 = time.monotonic()
            gui.render()
            _dt = (time.monotonic() - _t0) * 1000.0
            if _dt > 250:
                logger.warning("render slow (thread): %.0f ms", _dt)
        except Exception as e:
            logger.error("render thread error: %s", e)
        finally:
            _render_inflight[0] = False

    async def _render_loop():
        tick = 0
        last_policy_tier = None
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
                    if model.power_tier != last_policy_tier:
                        last_policy_tier = model.power_tier
                        _apply_resource_policy(reason="power_tier")
                if gui is not None and not shade:
                    gui.apply(model)      # RuntimeModel -> AppState (живой прогресс)
                    if power is None or power.display_awake:
                        # [CLAUDE 2026-06-11] ДОКАЗАНО зондами: кадр = 77 мс × 4-5/с в
                        # ТОМ ЖЕ event-loop, что RTP-пересылка -> дыры 130-180 мс во
                        # входе -> заикание (буфер Fosi 150 мс). Периодический рендер
                        # уходит в поток (executor); цикл BT кадров больше НЕ ждёт.
                        # Кадр ещё рисуется -> тик пропускаем (коалесинг), очередь
                        # кадров не копим. Торн-рид AppState из потока = максимум
                        # косметика на один кадр (read-only отрисовка).
                        if not _render_inflight[0]:
                            _render_inflight[0] = True
                            asyncio.get_event_loop().run_in_executor(None, _render_in_thread)
                publish_due = (tick % PUBLISH_EVERY == 0) if power is None else power.should_publish()
                if not shade and publish_due:
                    _on_publish()         # runtime-bt.json для дирижёра/sync
                tick += 1
                interval = RENDER_INTERVAL if power is None else power.render_interval
                # [CLAUDE 2026-06-12] GIL: рендер-поток всё равно держит интерпретатор
                # на Python-участках кадра. Пока труба льёт звук — кадры не чаще 2/с
                # (прогресс-бар не страдает, зато GIL-укусы вдвое реже).
                if transfer is not None and getattr(transfer, "bridge", None) is not None                         and getattr(transfer.bridge, "source_stream_active", False):
                    interval = max(interval, 0.5)
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("_render_loop error: %s", e, exc_info=True)
                await asyncio.sleep(1.0)

    asyncio.ensure_future(_render_loop())
    _boot_milestone("render_loop.scheduled")

    # Физический ввод (энкодер/кнопки/тач) -> GUI (параллельно рендеру).
    if gui is not None:
        _schedule_gui_input("late")
    else:
        # Headless: пресет-кнопка 1 = тумблер маршрута (решение владельца 2026-06-10).
        try:
            import input_handler

            def _on_headless_input(event):
                if event == "btn_1":
                    logger.info("route toggle: button 1 pressed")
                    asyncio.create_task(_route_toggle_flip())

            asyncio.ensure_future(input_handler.start(on_event=_on_headless_input))
            _boot_milestone("input.scheduled", mode="headless")
            logger.info("headless input: button 1 = route toggle")
        except Exception as e:
            _boot_milestone("input.disabled", error=type(e).__name__)
            logger.warning("headless input disabled: %s", e)

    _boot_milestone("runtime.ready")
    logger.info("runtime up — name=%s", identity_service.visible_name())
    await asyncio.get_event_loop().create_future()   # работать вечно


if __name__ == "__main__":
    if os.environ.get("CAR_THING_MAC_DISPLAY") == "1":
        from mac_display import MacDisplay, run_with_display
        MacDisplay()
        run_with_display(main)
    else:
        asyncio.run(main())
