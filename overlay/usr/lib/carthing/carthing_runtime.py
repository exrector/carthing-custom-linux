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

PUBLISH_INTERVAL = 1.0  # с: ритм публикации bt-части (живой прогресс для GUI/дирижёра)

orch: AccessoryOrchestrator | None = None
model = RuntimeModel()
_iphone: IPhoneService | None = None


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

    logger.info("runtime up — name=%s", identity_service.visible_name())
    while True:
        _on_publish()
        await asyncio.sleep(PUBLISH_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
