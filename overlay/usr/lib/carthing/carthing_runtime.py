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


def _on_command(source, command):
    if source == "iphone" and _iphone is not None:
        asyncio.ensure_future(_iphone.command(command))


def _on_pairing(enabled):
    if orch is not None:
        asyncio.ensure_future(orch.arm_pairing(bool(enabled)))
    if gui is not None:
        gui.set_pairing_mode(bool(enabled))


def _verify_persistent():
    try:
        state_paths.ensure_files()
        logger.info("persistent state OK (%s)", state_paths.STATE_DIR)
    except state_paths.PersistentStateError as e:
        # degraded: не выдумываем базу на tmpfs (контракт). Работаем, но без persistent-бондов.
        logger.error("DEGRADED — %s", e)


def _on_publish():
    model.write_bt_json()


async def _on_connection(connection):
    global _iphone
    logger.info("connected: %s", getattr(connection, "peer_address", "?"))

    def _disc(*_):
        if _iphone is not None:
            _iphone.reset()
        if orch is not None:
            asyncio.ensure_future(orch.on_disconnect())

    connection.on("disconnection", _disc)
    connection.on("connection_encryption_change",
                  lambda *_: orch and asyncio.ensure_future(orch.on_bonded()))

    _iphone = IPhoneService(model, on_update=_on_publish)
    try:
        await _iphone.setup(connection)
    except Exception as e:
        logger.warning("iphone service setup failed: %s", e)


async def main():
    global orch
    _verify_persistent()

    def _configure(device):
        global orch
        orch = AccessoryOrchestrator(device, on_phase_change=lambda p: logger.info("phase=%s", p))
        orch.install()  # CTKD pairing config + classic enabled (для CTKD)

    device, _transport = await init_ble(configure_device=_configure)
    await orch.apply_identity()       # одно имя на все транспорты
    await orch.apply_visibility()     # старт: directed-к-bonded / тишина (никакой открытой рекламы)

    device.on("connection", lambda c: asyncio.ensure_future(_on_connection(c)))

    # GUI: один home-surface + views поверх DRM (если дисплей доступен).
    global gui
    try:
        from drm_display import DRMDisplay
        from gui_controller import GuiController
        gui = GuiController(DRMDisplay(), on_command=_on_command, on_pairing=_on_pairing)
        logger.info("GUI active (modular Compositor)")
    except Exception as e:
        gui = None
        logger.warning("GUI disabled (no display?): %s", e)

    # Физический ввод (энкодер/кнопки/тач) -> GUI.
    if gui is not None:
        try:
            import input_handler
            await input_handler.start(on_event=gui.handle_input)
        except Exception as e:
            logger.warning("input disabled: %s", e)

    logger.info("runtime up — name=%s", identity_service.visible_name())
    tick = 0
    while True:
        if gui is not None:
            gui.apply(model)          # RuntimeModel -> AppState (живой прогресс)
            gui.render()
        if tick % PUBLISH_EVERY == 0:
            _on_publish()             # runtime-bt.json для дирижёра/sync
        tick += 1
        await asyncio.sleep(RENDER_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
