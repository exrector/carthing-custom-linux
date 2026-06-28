"""Prepare Car Thing for safe physical USB power removal."""

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


def _set_status(state, status, message):
    if state is None:
        return
    state.power_unplug_status = status
    state.power_unplug_message = message


def _launch_finalizer(reason):
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
    except Exception as error:
        logger.critical("safe unplug finalizer failed: %s", error)
        os.sync()
    os._exit(0)


async def prepare_for_usb_unplug(power=None, state=None):
    _set_status(state, "preparing", "Готовим...")
    if power is not None:
        try:
            power.blank_for_shutdown()
        except Exception:
            pass
    os.sync()
    _set_status(state, "ready_to_unplug", "Можно выдернуть питание")
    _launch_finalizer("normal-safe-unplug")
