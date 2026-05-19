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
            if keys:
                print(f"  keys ({len(keys)}): " +
                      ", ".join(fmt_code(KEY_NAMES, c) for c in keys))
            if rels:
                print(f"  rels ({len(rels)}): " +
                      ", ".join(fmt_code(REL_NAMES, c) for c in rels))
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

    poll = select.poll()
    for fd in fds:
        poll.register(fd, select.POLLIN)

    try:
        while True:
            for fd, _ in poll.poll(1000):
                try:
                    data = os.read(fd, EV_SIZE * 32)
                except BlockingIOError:
                    continue
                path = fds[fd]
                for off in range(0, len(data) - (EV_SIZE - 1), EV_SIZE):
                    tv_sec, tv_usec, evtype, code, value = struct.unpack_from(EV_FMT, data, off)
                    if evtype == EV_SYN:
                        continue
                    stamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                    if evtype == EV_KEY:
                        action = {0: "UP", 1: "DOWN", 2: "REPEAT"}.get(value, f"V={value}")
                        print(f"{stamp}  {path:22s}  EV_KEY  "
                              f"{fmt_code(KEY_NAMES, code):28s}  {action}")
                    elif evtype == EV_REL:
                        sign = "+" if value > 0 else ""
                        print(f"{stamp}  {path:22s}  EV_REL  "
                              f"{fmt_code(REL_NAMES, code):28s}  {sign}{value}")
                    else:
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
