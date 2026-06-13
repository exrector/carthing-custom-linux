"""Мягкое выключение Car Thing — без жёсткого обрыва питания.

Идея владельца 2026-06-13: нужна кнопка выключения, которая ЛАСКОВО гасит всё —
останавливает потоки, закрывает BT, сбрасывает буферы файловой системы и только
потом halt. Прямая профилактика повреждения state.json: именно жёсткий обрыв
питания посреди записи убил vfat-раздел (см. carthing-debug-log 2026-06-13).
Теперь раздел ext4+journal, но мягкое гашение — правильный «выключатель ОС».

Порядок (важен — от звука к питанию):
  1. остановить аудиопоток к колонке (suspend receiver) — тишина без щелчка;
  2. опустить classic-трубу источника (disconnect_source) — чисто отпускаем iPhone;
  3. остановить standby-петлю — больше не пейджим;
  4. погасить экран (bl_power) — визуально «выключились»;
  5. sync + unmount персистентного раздела — гарантия, что state.json/keys.json
     дописаны на диск ДО снятия питания;
  6. poweroff (или halt). Если poweroff недоступен — хотя бы оставляем ФС в
     согласованном состоянии (шаги 1-5 уже защитили данные).

[CLAUDE 2026-06-13] новый модуль. Вызывается из интента power_off (GUI-кнопка).
"""
from __future__ import annotations

import asyncio
import logging
import os

logger = logging.getLogger("carthing.power")

STATE_MOUNT = os.environ.get("CARTHING_STATE_MOUNT", "/run/carthing-state")


async def graceful_shutdown(transfer=None, power=None, halt: bool = True) -> None:
    """Ласково погасить устройство. halt=False — только мягкая остановка без
    poweroff (для теста последовательности без реального выключения)."""
    logger.info("graceful shutdown: begin")

    # 1-3. Тихо разобрать аудиотракт и отпустить источник.
    bridge = getattr(transfer, "bridge", None) if transfer is not None else None
    if bridge is not None:
        for step, coro_name in (("stop receiver", "stop_receiver_stream"),
                                 ("disconnect source", "disconnect_source")):
            fn = getattr(bridge, coro_name, None)
            if fn is None:
                continue
            try:
                await asyncio.wait_for(fn(), timeout=5)
                logger.info("graceful shutdown: %s ok", step)
            except Exception as e:
                logger.warning("graceful shutdown: %s ignored: %s", step, e)
        # остановить standby-таск, чтобы не пейджил во время гашения
        task = getattr(bridge, "_standby_task", None)
        if task is not None and not task.done():
            task.cancel()

    # 4. Погасить экран.
    if power is not None:
        try:
            power.blank_for_shutdown()
        except Exception as e:
            logger.info("graceful shutdown: blank ignored: %s", e)

    # 5. Сбросить буферы и отмонтировать персистентный раздел — данные на диск.
    try:
        os.sync()
    except Exception:
        pass
    if halt:
        # umount именно state-раздела (там state.json/keys.json) — критично для
        # целостности. Остальное синкнуто os.sync выше.
        os.system(f"umount {STATE_MOUNT} 2>/dev/null")
        os.sync()

    logger.info("graceful shutdown: filesystems flushed%s", "" if halt else " (no-halt test)")

    # 6. Питание.
    if halt:
        logger.info("graceful shutdown: poweroff")
        # poweroff -> если нет, halt -> если нет, sysrq. Любой даёт чистое снятие.
        rc = os.system("poweroff 2>/dev/null")
        if rc != 0:
            os.system("halt -f 2>/dev/null") or os.system(
                "echo o > /proc/sysrq-trigger 2>/dev/null")
