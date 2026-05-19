"""Helpers for sending HID Keyboard reports via the GATT Report characteristic.

Boot-protocol keyboard report layout (8 bytes):
    byte 0: modifier bitmask (Ctrl/Shift/Alt/GUI, L+R)
    byte 1: reserved (must be 0)
    bytes 2..7: up to 6 key usage codes (HID Usage Page 0x07 — Keyboard)

The host treats a key code as "pressed" while it appears in any report and
"released" once it stops appearing. We always send a paired "release" report
so a single press never turns into a stuck modifier.
"""

import asyncio
import logging

logger = logging.getLogger(__name__)

MOD_NONE  = 0x00
MOD_LCTRL = 0x01
MOD_LSHFT = 0x02
MOD_LALT  = 0x04
MOD_LGUI  = 0x08
MOD_RCTRL = 0x10
MOD_RSHFT = 0x20
MOD_RALT  = 0x40
MOD_RGUI  = 0x80

# Frequently used HID Usage IDs (page 0x07). Add more as needed.
KEY_A = 0x04; KEY_B = 0x05; KEY_C = 0x06; KEY_D = 0x07; KEY_E = 0x08
KEY_F = 0x09; KEY_G = 0x0A; KEY_H = 0x0B; KEY_I = 0x0C; KEY_J = 0x0D
KEY_K = 0x0E; KEY_L = 0x0F; KEY_M = 0x10; KEY_N = 0x11; KEY_O = 0x12
KEY_P = 0x13; KEY_Q = 0x14; KEY_R = 0x15; KEY_S = 0x16; KEY_T = 0x17
KEY_U = 0x18; KEY_V = 0x19; KEY_W = 0x1A; KEY_X = 0x1B; KEY_Y = 0x1C
KEY_Z = 0x1D
KEY_1 = 0x1E; KEY_2 = 0x1F; KEY_3 = 0x20; KEY_4 = 0x21; KEY_5 = 0x22
KEY_6 = 0x23; KEY_7 = 0x24; KEY_8 = 0x25; KEY_9 = 0x26; KEY_0 = 0x27

KEY_ENTER   = 0x28
KEY_ESC     = 0x29
KEY_BSP     = 0x2A
KEY_TAB     = 0x2B
KEY_SPACE   = 0x2C
KEY_F1      = 0x3A
KEY_F2      = 0x3B
KEY_F3      = 0x3C
KEY_F4      = 0x3D
KEY_F5      = 0x3E
KEY_F6      = 0x3F
KEY_F7      = 0x40
KEY_F8      = 0x41
KEY_F9      = 0x42
KEY_F10     = 0x43
KEY_F11     = 0x44
KEY_F12     = 0x45
KEY_RIGHT   = 0x4F
KEY_LEFT    = 0x50
KEY_DOWN    = 0x51
KEY_UP      = 0x52


def build_report(modifiers: int = 0, keys: tuple[int, ...] = ()) -> bytes:
    keys = tuple(keys)[:6]
    pad = (0,) * (6 - len(keys))
    return bytes([modifiers & 0xFF, 0x00, *keys, *pad])


async def send_keys(device, modifiers: int, *keys: int, hold_ms: int = 15):
    """Send a key-down then key-up report through the keyboard characteristic."""
    char = getattr(device, "kbd_report_char", None)
    if char is None:
        logger.warning("keyboard_hid: kbd_report_char missing on device")
        return

    pressed = build_report(modifiers, keys)
    released = build_report(0, ())

    try:
        char.value = pressed
        await device.notify_subscribers(char, pressed)
        await asyncio.sleep(hold_ms / 1000)
        char.value = released
        await device.notify_subscribers(char, released)
    except Exception as exc:
        logger.warning("keyboard_hid send_keys error: %s", exc)


async def tap(device, key: int, modifiers: int = 0):
    await send_keys(device, modifiers, key)


async def type_string(device, text: str, inter_ms: int = 15):
    """Type plain ASCII letters/digits/space — for quick smoke tests, not full unicode."""
    for ch in text:
        if ch == " ":
            await tap(device, KEY_SPACE)
        elif ch == "\n":
            await tap(device, KEY_ENTER)
        elif "a" <= ch <= "z":
            await tap(device, KEY_A + (ord(ch) - ord("a")))
        elif "A" <= ch <= "Z":
            await tap(device, KEY_A + (ord(ch) - ord("A")), modifiers=MOD_LSHFT)
        elif "1" <= ch <= "9":
            await tap(device, KEY_1 + (ord(ch) - ord("1")))
        elif ch == "0":
            await tap(device, KEY_0)
        else:
            logger.info("keyboard_hid type_string: skipping unsupported char %r", ch)
            continue
        await asyncio.sleep(inter_ms / 1000)
