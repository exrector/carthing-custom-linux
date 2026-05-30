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

import runtime_paths  # noqa: F401  (ставит sys.path)
import state_paths
import identity_service
from ble_transport import init_ble
from accessory_orchestrator import AccessoryOrchestrator
from runtime_model import RuntimeModel
from iphone_service import IPhoneService

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


def _on_command(source, command):
    if source == "iphone" and _iphone is not None:
        asyncio.ensure_future(_iphone.command(command))
    elif source == "mac" and mac is not None:
        asyncio.ensure_future(mac.command(command))


def _on_pairing(enabled):
    if orch is not None:
        asyncio.ensure_future(orch.arm_pairing(bool(enabled)))
    if gui is not None:
        gui.set_pairing_mode(bool(enabled))


def _on_transfer_rescan():
    if transfer is not None:
        asyncio.ensure_future(transfer.rescan())


def _on_transfer_select(address):
    if transfer is not None:
        asyncio.ensure_future(transfer.select(address))


async def _emit_source_intent(intent):
    """Для backchannel: команда динамика -> активный источник."""
    if _iphone is not None:
        await _iphone.command(intent)


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

    connection.on("disconnection", _disc)
    connection.on("pairing", lambda *_: asyncio.ensure_future(_start_ams("pairing")))
    connection.on("pairing_failure", lambda r: logger.error("SMP pairing failed: %s", r))
    connection.on("connection_encryption_change",
                  lambda *_: asyncio.ensure_future(_start_ams("encryption")))

    if gui is not None:
        gui.set_pairing_mode(False)   # авто-закрыть pairing-модалку на коннекте

    if getattr(connection, "is_encrypted", False):
        await _start_ams("connected-encrypted")
    else:
        logger.info("requesting pairing (link not encrypted yet)")
        try:
            connection.request_pairing()
        except Exception as e:
            logger.warning("request_pairing failed: %s", e)


async def main():
    global orch, gui, transfer, backchannel, settings, hw_caps, mac
    _verify_persistent()

    # Per-boot инвентарь возможностей + настройки.
    import hardware_inventory
    from settings_service import SettingsService
    hw_caps = hardware_inventory.probe()
    settings = SettingsService()
    logger.info("hw capabilities: %s", {k: v for k, v in hw_caps.items() if v})

    def _configure(device):
        global orch
        orch = AccessoryOrchestrator(device, on_phase_change=lambda p: logger.info("phase=%s", p))
        orch.install()  # CTKD pairing config + classic enabled (для CTKD)

    device, _transport = await init_ble(configure_device=_configure)
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
                                on_transfer_select=_on_transfer_select)
            logger.info("GUI active (modular Compositor)")
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

    # Видимость — ПОСЛЕ transfer.start(): orchestrator перегейтит classic в not-connectable
    # (никакой открытой A2DP-рекламы; directed-к-bonded / тишина по фазе).
    await orch.apply_visibility()

    # Рендер-цикл — ОТДЕЛЬНАЯ задача (не зависит от input.start, который блокирует loop).
    async def _render_loop():
        tick = 0
        while True:
            if gui is not None:
                gui.apply(model)      # RuntimeModel -> AppState (живой прогресс)
                gui.render()
            if tick % PUBLISH_EVERY == 0:
                _on_publish()         # runtime-bt.json для дирижёра/sync
            tick += 1
            await asyncio.sleep(RENDER_INTERVAL)

    asyncio.ensure_future(_render_loop())

    # Физический ввод (энкодер/кнопки/тач) -> GUI (параллельно рендеру).
    if gui is not None:
        try:
            import input_handler
            asyncio.ensure_future(input_handler.start(on_event=gui.handle_input))
        except Exception as e:
            logger.warning("input disabled: %s", e)

    logger.info("runtime up — name=%s", identity_service.visible_name())
    await asyncio.get_event_loop().create_future()   # работать вечно


if __name__ == "__main__":
    asyncio.run(main())
