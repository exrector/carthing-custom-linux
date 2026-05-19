#!/usr/bin/env python3
"""Car Thing input device discovery.

Two modes:

    key_probe.py scan        — for each /dev/input/event*, print device
                               name and the full list of supported key
                               codes via EVIOCGBIT. No button presses
                               required.

    key_probe.py monitor     — open every /dev/input/event* and stream
                               EV_KEY / EV_REL events in real time with
                               human-readable code names and timestamps.
                               Press each physical control once; the log
                               becomes the canonical button → code map.

Default (no args): monitor.

Self-contained: stdlib only, ~150 LOC, runs on the target. Copy with:
    scp tools/key_probe.py root@<device>:/tmp/key_probe.py
    ssh root@<device> 'python3 /tmp/key_probe.py monitor'
"""

import fcntl
import glob
import os
import struct
import select
import sys
import time
from datetime import datetime

# Subset of Linux/include/uapi/linux/input-event-codes.h that covers
# every code we are realistically going to see on Car Thing's gpio-keys.
KEY_NAMES = {
    1: "KEY_ESC",
    2: "KEY_1",
    3: "KEY_2",
    4: "KEY_3",
    5: "KEY_4",
    6: "KEY_5",
    7: "KEY_6",
    14: "KEY_BACKSPACE",
    15: "KEY_TAB",
    28: "KEY_ENTER",
    29: "KEY_LEFTCTRL",
    42: "KEY_LEFTSHIFT",
    56: "KEY_LEFTALT",
    57: "KEY_SPACE",
    102: "KEY_HOME",
    103: "KEY_UP",
    105: "KEY_LEFT",
    106: "KEY_RIGHT",
    108: "KEY_DOWN",
    113: "KEY_MUTE",
    114: "KEY_VOLUMEDOWN",
    115: "KEY_VOLUMEUP",
    116: "KEY_POWER",
    119: "KEY_PAUSE",
    127: "KEY_COMPOSE",
    139: "KEY_MENU",
    158: "KEY_BACK",
    163: "KEY_NEXTSONG",
    164: "KEY_PLAYPAUSE",
    165: "KEY_PREVIOUSSONG",
    166: "KEY_STOPCD",
    172: "KEY_HOMEPAGE",
    207: "KEY_PLAY",
    208: "KEY_FASTFORWARD",
    213: "KEY_FRAMEFORWARD",
    214: "KEY_CONTEXT_MENU",
    217: "KEY_SEARCH",
    231: "KEY_CONNECT",
    240: "KEY_UNKNOWN",
    256: "BTN_0",
    257: "BTN_1",
    258: "BTN_2",
    259: "BTN_3",
    272: "BTN_LEFT",
    273: "BTN_RIGHT",
    274: "BTN_MIDDLE",
    288: "BTN_TRIGGER",
    304: "BTN_SOUTH",
    305: "BTN_EAST",
    306: "BTN_C",
    307: "BTN_NORTH",
    308: "BTN_WEST",
    309: "BTN_Z",
    310: "BTN_TL",
    311: "BTN_TR",
}

REL_NAMES = {
    0: "REL_X",
    1: "REL_Y",
    2: "REL_Z",
    6: "REL_HWHEEL",
    7: "REL_DIAL",
    8: "REL_WHEEL",
    11: "REL_WHEEL_HI_RES",
    12: "REL_HWHEEL_HI_RES",
}

ABS_NAMES = {
    0x00: "ABS_X",
    0x01: "ABS_Y",
    0x02: "ABS_Z",
    0x18: "ABS_PRESSURE",
    0x19: "ABS_DISTANCE",
    0x1A: "ABS_TILT_X",
    0x1B: "ABS_TILT_Y",
    0x1C: "ABS_TOOL_WIDTH",
    0x20: "ABS_VOLUME",
    0x2F: "ABS_MT_SLOT",
    0x30: "ABS_MT_TOUCH_MAJOR",
    0x31: "ABS_MT_TOUCH_MINOR",
    0x32: "ABS_MT_WIDTH_MAJOR",
    0x33: "ABS_MT_WIDTH_MINOR",
    0x34: "ABS_MT_ORIENTATION",
    0x35: "ABS_MT_POSITION_X",
    0x36: "ABS_MT_POSITION_Y",
    0x37: "ABS_MT_TOOL_TYPE",
    0x38: "ABS_MT_BLOB_ID",
    0x39: "ABS_MT_TRACKING_ID",
    0x3A: "ABS_MT_PRESSURE",
    0x3B: "ABS_MT_DISTANCE",
    0x3C: "ABS_MT_TOOL_X",
    0x3D: "ABS_MT_TOOL_Y",
}
ABS_MAX = 0x3F
ABS_CNT = ABS_MAX + 1
INPUT_ABSINFO_SIZE = 24  # 6 × s32

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
EV_NAMES = {EV_SYN: "EV_SYN", EV_KEY: "EV_KEY", EV_REL: "EV_REL", EV_ABS: "EV_ABS"}

KEY_MAX = 0x2FF        # 767 — enough for all keyboard/button codes
KEY_CNT = KEY_MAX + 1
EVIOCGNAME_MAX = 256

# ioctl numbers derived from <linux/input.h>:
#   _IOR('E', 0x06, char[256])   = EVIOCGNAME(len)
#   _IOC(2, 'E', 0x20+ev, len)   = EVIOCGBIT(ev, len)
# _IOC(dir,type,nr,size): dir<<30 | size<<16 | type<<8 | nr
def _iow_dir(direction, type_byte, nr, size):
    return (direction << 30) | (size << 16) | (type_byte << 8) | nr

def EVIOCGNAME(length):
    return _iow_dir(2, ord('E'), 0x06, length)

def EVIOCGBIT(ev_type, length):
    return _iow_dir(2, ord('E'), 0x20 + ev_type, length)

def EVIOCGABS(axis):
    return _iow_dir(2, ord('E'), 0x40 + axis, INPUT_ABSINFO_SIZE)


def get_device_name(fd) -> str:
    buf = bytearray(EVIOCGNAME_MAX)
    try:
        fcntl.ioctl(fd, EVIOCGNAME(EVIOCGNAME_MAX), buf, True)
    except OSError as exc:
        return f"<EVIOCGNAME failed: {exc}>"
    return buf.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def get_supported_codes(fd, ev_type, max_code) -> list:
    nbytes = (max_code + 7) // 8
    buf = bytearray(nbytes)
    try:
        fcntl.ioctl(fd, EVIOCGBIT(ev_type, nbytes), buf, True)
    except OSError as exc:
        return [f"<EVIOCGBIT failed: {exc}>"]
    codes = []
    for byte_idx, byte_val in enumerate(buf):
        for bit_idx in range(8):
            if byte_val & (1 << bit_idx):
                codes.append(byte_idx * 8 + bit_idx)
    return codes


def fmt_code(table, code):
    return f"{table.get(code, 'UNKNOWN')}({code})"


def get_abs_info(fd, axis):
    buf = bytearray(INPUT_ABSINFO_SIZE)
    try:
        fcntl.ioctl(fd, EVIOCGABS(axis), buf, True)
    except OSError:
        return None
    value, minimum, maximum, fuzz, flat, resolution = struct.unpack("<6i", buf)
    return {
        "value": value, "min": minimum, "max": maximum,
        "fuzz": fuzz, "flat": flat, "resolution": resolution,
    }


def scan_devices():
    paths = sorted(glob.glob("/dev/input/event*"))
    if not paths:
        print("No /dev/input/event* devices found.")
        return
    for path in paths:
        print(f"=== {path} ===")
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            print(f"  cannot open: {exc}")
            continue
        try:
            print(f"  name: {get_device_name(fd)!r}")
            keys = get_supported_codes(fd, EV_KEY, KEY_MAX)
            rels = get_supported_codes(fd, EV_REL, 0x20)
            abses = get_supported_codes(fd, EV_ABS, ABS_MAX)
            if keys:
                print(f"  keys ({len(keys)}): " +
                      ", ".join(fmt_code(KEY_NAMES, c) for c in keys))
            if rels:
                print(f"  rels ({len(rels)}): " +
                      ", ".join(fmt_code(REL_NAMES, c) for c in rels))
            if abses:
                print(f"  abs  ({len(abses)}):")
                for axis in abses:
                    info = get_abs_info(fd, axis)
                    name = fmt_code(ABS_NAMES, axis)
                    if info is None:
                        print(f"    {name}: (EVIOCGABS unavailable)")
                    else:
                        print(f"    {name}: min={info['min']} max={info['max']} "
                              f"fuzz={info['fuzz']} flat={info['flat']} "
                              f"res={info['resolution']}")
        finally:
            os.close(fd)
        print()


def monitor():
    paths = sorted(glob.glob("/dev/input/event*"))
    if not paths:
        print("No /dev/input/event* devices found.")
        return

    fds = {}
    for path in paths:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        except OSError as exc:
            print(f"skip {path}: {exc}")
            continue
        fds[fd] = path
        print(f"watching {path}  ({get_device_name(fd)!r})")
    print()
    print("Press each control once. Ctrl-C to stop.")
    print()

    EV_FMT = "qqHHi"
    EV_SIZE = struct.calcsize(EV_FMT)
    SYN_REPORT = 0

    poll = select.poll()
    for fd in fds:
        poll.register(fd, select.POLLIN)

    # Per-device multitouch state (Protocol B with slots).
    # state[fd]["slots"][slot_id] = {"x":..., "y":..., "p":..., "id":..., "active":bool}
    state = {fd: {"current_slot": 0, "slots": {}, "pending": []} for fd in fds}

    def fmt_slots(slots):
        active = [(sid, s) for sid, s in sorted(slots.items()) if s.get("active")]
        if not active:
            return "(none)"
        parts = []
        for sid, s in active:
            x = s.get("x", "?")
            y = s.get("y", "?")
            p = s.get("p")
            id_ = s.get("id")
            tag = f"slot{sid}"
            if id_ is not None:
                tag += f"#{id_}"
            parts.append(f"{tag}=({x},{y}" + (f",p={p}" if p is not None else "") + ")")
        return " ".join(parts)

    try:
        while True:
            for fd, _ in poll.poll(1000):
                try:
                    data = os.read(fd, EV_SIZE * 64)
                except BlockingIOError:
                    continue
                path = fds[fd]
                st = state[fd]
                for off in range(0, len(data) - (EV_SIZE - 1), EV_SIZE):
                    _, _, evtype, code, value = struct.unpack_from(EV_FMT, data, off)
                    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

                    if evtype == EV_KEY:
                        action = {0: "UP", 1: "DOWN", 2: "REPEAT"}.get(value, f"V={value}")
                        print(f"{stamp}  {path:22s}  EV_KEY  "
                              f"{fmt_code(KEY_NAMES, code):28s}  {action}")
                        sys.stdout.flush()
                    elif evtype == EV_REL:
                        sign = "+" if value > 0 else ""
                        print(f"{stamp}  {path:22s}  EV_REL  "
                              f"{fmt_code(REL_NAMES, code):28s}  {sign}{value}")
                        sys.stdout.flush()
                    elif evtype == EV_ABS:
                        if code == 0x2F:  # ABS_MT_SLOT
                            st["current_slot"] = value
                        else:
                            slot_id = st["current_slot"]
                            slot = st["slots"].setdefault(slot_id, {})
                            if code == 0x39:  # ABS_MT_TRACKING_ID
                                if value == -1:
                                    slot["active"] = False
                                else:
                                    slot["active"] = True
                                    slot["id"] = value
                            elif code == 0x35:  # ABS_MT_POSITION_X
                                slot["x"] = value
                            elif code == 0x36:  # ABS_MT_POSITION_Y
                                slot["y"] = value
                            elif code == 0x3A:  # ABS_MT_PRESSURE
                                slot["p"] = value
                            elif code == 0x00:  # ABS_X (single-touch fallback)
                                slot.setdefault("id", 0)
                                slot["active"] = True
                                slot["x"] = value
                            elif code == 0x01:  # ABS_Y
                                slot["y"] = value
                            else:
                                # Other axes — record but don't reformat
                                st["pending"].append((code, value))
                    elif evtype == EV_SYN and code == SYN_REPORT:
                        # Emit a snapshot per frame, but only for touchscreen
                        # devices (those that emit any ABS events).
                        if st["slots"] or st["pending"]:
                            print(f"{stamp}  {path:22s}  TOUCH   "
                                  f"{fmt_slots(st['slots'])}")
                            sys.stdout.flush()
                            st["pending"].clear()
                    else:
                        if evtype != EV_SYN:
                            print(f"{stamp}  {path:22s}  "
                                  f"{EV_NAMES.get(evtype, f'EV_{evtype}'):6s}  "
                                  f"code={code} value={value}")
                            sys.stdout.flush()
    except KeyboardInterrupt:
        print("\nstopped.")
    finally:
        for fd in fds:
            os.close(fd)


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "monitor"
    if mode == "scan":
        scan_devices()
    elif mode == "monitor":
        monitor()
    else:
        print(f"usage: {sys.argv[0]} [scan|monitor]")
        sys.exit(1)


if __name__ == "__main__":
    main()
