"""Safe USB unplug preparation for Car Thing.

The user-facing power action is not Linux poweroff. On this hardware the
Amlogic PSCI poweroff path can enter USB burn mode. The safe product behavior
is: stop active routes, flush state, remount persistent state read-only, then
enter suspend-to-RAM so the user can physically remove USB power.

If suspend ever resumes, remount state read-write and leave Linux alive.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys

logger = logging.getLogger("carthing.power")

STATE_MOUNT = os.environ.get("CARTHING_STATE_MOUNT", "/run/carthing-state")
BOOT_MOUNT = os.environ.get("CARTHING_BOOT_MOUNT", "/run/carthing-boot")
SUSPEND_STATE = os.environ.get("CARTHING_SUSPEND_STATE", "/sys/power/state")
SAFE_UNPLUG_HELPER = os.environ.get(
    "CARTHING_SAFE_UNPLUG_HELPER",
    "/usr/lib/carthing/safe_unplug_helper.py",
)


def _state_mount_is_read_only() -> bool:
    try:
        with open("/proc/mounts", "r", encoding="ascii", errors="replace") as fp:
            for line in fp:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == STATE_MOUNT:
                    return "ro" in parts[3].split(",")
    except Exception as exc:
        logger.warning("safe unplug: mount-state check failed: %s", exc)
    return False


def _set_unplug_status(state, status: str, message: str = "") -> None:
    if state is None:
        return
    try:
        state.power_unplug_status = status
        state.power_unplug_message = message
    except Exception as exc:
        logger.debug("safe unplug: status update ignored: %s", exc)


def _launch_finalizer(reason: str) -> None:
    logger.critical("safe unplug: escalating to finalizer: %s", reason)
    try:
        subprocess.Popen(
            [
                sys.executable or "python3",
                SAFE_UNPLUG_HELPER,
                "--state-mount",
                STATE_MOUNT,
                "--boot-mount",
                BOOT_MOUNT,
                "--suspend-state",
                SUSPEND_STATE,
                "--reason",
                reason,
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
    except Exception as exc:
        logger.critical("safe unplug: finalizer launch failed: %s", exc)
        try:
            os.sync()
        except Exception:
            pass
        for mode in ("mem", "freeze"):
            try:
                with open(SUSPEND_STATE, "w", encoding="ascii") as fp:
                    fp.write(mode + "\n")
            except Exception as suspend_exc:
                logger.critical("safe unplug: direct %s failed: %s", mode, suspend_exc)
    os._exit(0)


async def graceful_shutdown(transfer=None, power=None, halt: bool = True) -> None:
    """Ласково погасить устройство. halt=False — только мягкая остановка без
    poweroff (для теста последовательности без реального выключения)."""
    if halt and os.environ.get("CARTHING_ALLOW_LINUX_POWEROFF") != "1":
        logger.warning(
            "graceful shutdown: Linux poweroff is quarantined on Car Thing; "
            "using no-halt screen/route idle"
        )
        halt = False

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


async def prepare_for_usb_unplug(transfer=None, power=None, state=None) -> None:
    """Flush state and enter suspend so physical USB removal is safe.

    This is intentionally not a wakeable "sleep" feature yet: current hardware
    testing showed `mem` makes the display/buttons go dark, but rotary wake did
    not resume the device. The product contract is "safe to unplug USB".
    """
    logger.warning("safe unplug: begin")
    _set_unplug_status(state, "preparing", "Готовим...")
    _set_unplug_status(state, "stopping_routes", "Останавливаем маршруты...")
    await graceful_shutdown(transfer=transfer, power=None, halt=False)
    bridge = getattr(transfer, "bridge", None) if transfer is not None else None
    bridge_state = getattr(bridge, "state", None) if bridge is not None else None
    save_trusted = getattr(bridge_state, "save_trusted", None)
    if save_trusted is not None:
        try:
            save_trusted()
            logger.info("safe unplug: trusted state saved")
        except Exception as exc:
            logger.warning("safe unplug: trusted state save failed: %s", exc)
    try:
        os.sync()
    except Exception:
        pass
    _set_unplug_status(state, "syncing", "Закрываем запись...")
    try:
        os.sync()
    except Exception:
        pass
    _set_unplug_status(state, "ready_to_unplug", "Можно выдернуть питание")
    _launch_finalizer("normal-safe-unplug")
