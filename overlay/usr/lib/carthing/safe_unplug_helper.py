#!/usr/bin/env python3
"""Last-resort safe-unplug finalizer.

This helper is started outside the GUI/runtime process. Its job is to make the
device quiescent even when the normal in-process read-only remount path is
blocked by the runtime itself or by another userspace holder.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import signal
import subprocess
import time


LOG_PATH = "/run/carthing/safe-unplug.log"
SUPERVISOR_PID = "/run/carthing/media-remote-supervisor.pid"
BACKLIGHT_GLOBS = (
    "/sys/class/backlight/*/brightness",
    "/sys/class/backlight/*/bl_power",
)


def log(message: str) -> None:
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as fp:
            fp.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")
    except Exception:
        pass


def run(cmd: list[str]) -> int:
    try:
        return subprocess.call(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as exc:
        log(f"run failed {cmd}: {exc}")
        return 127


def read_int(path: str) -> int | None:
    try:
        with open(path, "r", encoding="ascii", errors="replace") as fp:
            return int(fp.read().strip() or "0")
    except Exception:
        return None


def kill_pid(pid: int, sig: int) -> None:
    if pid <= 1 or pid == os.getpid():
        return
    try:
        os.kill(pid, sig)
        log(f"sent {sig} to pid {pid}")
    except ProcessLookupError:
        pass
    except Exception as exc:
        log(f"kill {pid} failed: {exc}")


def stop_supervisor() -> None:
    pid = read_int(SUPERVISOR_PID)
    if pid:
        kill_pid(pid, signal.SIGTERM)
        time.sleep(0.2)
        kill_pid(pid, signal.SIGKILL)


def processes_holding_path(root: str) -> set[int]:
    holders: set[int] = set()
    root = os.path.realpath(root)
    for proc in glob.glob("/proc/[0-9]*"):
        try:
            pid = int(os.path.basename(proc))
        except ValueError:
            continue
        if pid <= 1 or pid == os.getpid():
            continue
        paths = [os.path.join(proc, "cwd"), os.path.join(proc, "root")]
        paths.extend(glob.glob(os.path.join(proc, "fd", "*")))
        for path in paths:
            try:
                target = os.path.realpath(os.readlink(path))
            except Exception:
                continue
            if target == root or target.startswith(root + "/"):
                holders.add(pid)
                break
    return holders


def state_is_ro(state_mount: str) -> bool:
    try:
        with open("/proc/mounts", "r", encoding="ascii", errors="replace") as fp:
            for line in fp:
                parts = line.split()
                if len(parts) >= 4 and parts[1] == state_mount:
                    return "ro" in parts[3].split(",")
    except Exception as exc:
        log(f"mount check failed: {exc}")
    return False


def state_is_mounted(state_mount: str) -> bool:
    try:
        with open("/proc/mounts", "r", encoding="ascii", errors="replace") as fp:
            return any(line.split()[1:2] == [state_mount] for line in fp)
    except Exception as exc:
        log(f"mount presence check failed: {exc}")
    return True


def clean_unmount(state_mount: str) -> bool:
    os.sync()
    rc = run(["umount", state_mount])
    ok = rc == 0 or not state_is_mounted(state_mount)
    log(f"clean umount rc={rc} ok={ok}")
    return ok


def remount_ro(state_mount: str) -> bool:
    os.sync()
    rc = run(["mount", "-o", "remount,ro", state_mount])
    ok = rc == 0 and state_is_ro(state_mount)
    log(f"remount ro rc={rc} ok={ok}")
    return ok


def force_quiesce_state(state_mount: str) -> bool:
    if clean_unmount(state_mount):
        return True

    holders = processes_holding_path(state_mount)
    if holders:
        log(f"state holders term={sorted(holders)}")
        for pid in holders:
            kill_pid(pid, signal.SIGTERM)
        time.sleep(0.8)
    if clean_unmount(state_mount):
        return True

    holders = processes_holding_path(state_mount)
    if holders:
        log(f"state holders kill={sorted(holders)}")
        for pid in holders:
            kill_pid(pid, signal.SIGKILL)
        time.sleep(0.5)
    if clean_unmount(state_mount):
        return True

    if remount_ro(state_mount):
        return True

    os.sync()
    rc = run(["umount", "-l", state_mount])
    log(f"lazy umount fallback rc={rc}")
    os.sync()
    return rc == 0


def blank_screen() -> None:
    for path in glob.glob("/sys/class/backlight/*/brightness"):
        try:
            with open(path, "w", encoding="ascii") as fp:
                fp.write("0\n")
        except Exception:
            pass
    for path in glob.glob("/sys/class/backlight/*/bl_power"):
        try:
            with open(path, "w", encoding="ascii") as fp:
                fp.write("4\n")
        except Exception:
            pass


def enter_suspend(suspend_state: str) -> None:
    for mode in ("mem", "freeze"):
        try:
            with open(suspend_state, "w", encoding="ascii") as fp:
                fp.write(mode + "\n")
            log(f"entered {mode}; resumed")
        except Exception as exc:
            log(f"{mode} failed: {exc}")


def verify_environment(state_mount: str, suspend_state: str) -> dict:
    try:
        suspend_modes = open(
            suspend_state,
            "r",
            encoding="ascii",
            errors="replace",
        ).read().split()
    except Exception:
        suspend_modes = []
    return {
        "state_mounted": state_is_mounted(state_mount),
        "state_read_only": state_is_ro(state_mount),
        "state_holders": sorted(processes_holding_path(state_mount)),
        "suspend_modes": suspend_modes,
        "supervisor_pid": read_int(SUPERVISOR_PID),
        "ready": (
            state_is_mounted(state_mount)
            and bool({"mem", "freeze"}.intersection(suspend_modes))
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-mount", default="/run/carthing-state")
    parser.add_argument("--boot-mount", default="/run/carthing-boot")
    parser.add_argument("--suspend-state", default="/sys/power/state")
    parser.add_argument("--reason", default="unspecified")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()

    if args.verify_only:
        print(
            json.dumps(
                verify_environment(args.state_mount, args.suspend_state),
                sort_keys=True,
            )
        )
        return 0

    log(f"finalizer begin reason={args.reason}")
    time.sleep(0.35)
    stop_supervisor()
    ok = force_quiesce_state(args.state_mount)
    if not ok:
        log("state could not be fully proven read-only; suspending after sync fallback")
    if args.boot_mount:
        run(["umount", args.boot_mount])
    blank_screen()
    os.sync()
    enter_suspend(args.suspend_state)
    log("finalizer exhausted suspend attempts")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
