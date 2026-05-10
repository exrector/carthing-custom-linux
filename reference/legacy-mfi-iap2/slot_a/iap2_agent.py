#!/usr/bin/env python3
"""
iap2_agent.py — Минимальный iAP2 Bluetooth агент для Car Thing

Заменяет qt-superbird-app для одной задачи: регистрация iAP2 SDP записи.
Без Qt, без Sensory, без WAMP, без вебсокета, без glib, без dbus-python.
Использует ctypes для вызова libdbus-1 напрямую.

iAP2 UUID: 00000000-deca-fade-deca-deafdecacaff
RFCOMM Channel: 1

Запуск:
    python3 /home/superbird/slot_a/iap2_agent.py
"""

import ctypes
import ctypes.util
import os
import signal
import sys
import time

# ── D-Bus константы ─────────────────────────────────────────────────────────
DBUS_BUS_SYSTEM = 1
DBUS_NAME_FLAG_REPLACE_EXISTING = 0x2
DBUS_HANDLER_RESULT_HANDLED = 1
DBUS_HANDLER_RESULT_NOT_YET_HANDLED = 2

DBUS_TYPE_OBJECT_PATH = 7   # 'o'
DBUS_TYPE_STRING = 8        # 's'
DBUS_TYPE_ARRAY = 97        # 'a'
DBUS_TYPE_DICT_ENTRY = 100  # 'e'
DBUS_TYPE_VARIANT = 118     # 'v'
DBUS_TYPE_BYTE = 121        # 'y'
DBUS_TYPE_UNIX_FD = 104     # 'h'
DBUS_TYPE_INT32 = 105       # 'i'

DBUS_TIMEOUT_INFINITE = -1

# iAP2
IAP2_UUID = "00000000-deca-fade-deca-deafdecacaff"
IAP2_RFCOMM_CHANNEL = 1
PROFILE_PATH = "/org/bluez/profile/iap2"

# ── Загрузка libdbus-1 ───────────────────────────────────────────────────────
libdbus_path = ctypes.util.find_library("dbus-1")
if not libdbus_path:
    # Пробуем явные пути
    for p in ["/usr/lib/libdbus-1.so.3", "/usr/lib/libdbus-1.so", "/lib/libdbus-1.so.3"]:
        if os.path.exists(p):
            libdbus_path = p
            break

if not libdbus_path:
    print("[iap2] ERROR: libdbus-1 not found", flush=True)
    sys.exit(1)

print(f"[iap2] Loading {libdbus_path}", flush=True)
bus = ctypes.CDLL(libdbus_path, use_errno=True)

# ── Функции libdbus ──────────────────────────────────────────────────────────
bus.dbus_bus_get.restype = ctypes.c_void_p
bus.dbus_bus_get.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)]

bus.dbus_bus_request_name.restype = ctypes.c_int
bus.dbus_bus_request_name.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p)]

bus.dbus_connection_register_object_path.restype = ctypes.c_int
bus.dbus_connection_register_object_path.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_void_p, ctypes.c_void_p]

bus.dbus_connection_read_write_dispatch.restype = ctypes.c_int
bus.dbus_connection_read_write_dispatch.argtypes = [ctypes.c_void_p, ctypes.c_int]

bus.dbus_connection_unref.restype = None
bus.dbus_connection_unref.argtypes = [ctypes.c_void_p]

bus.dbus_message_new_method_return.restype = ctypes.c_void_p
bus.dbus_message_new_method_return.argtypes = [ctypes.c_void_p]

bus.dbus_connection_send.restype = ctypes.c_int
bus.dbus_connection_send.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]

bus.dbus_connection_flush.restype = None
bus.dbus_connection_flush.argtypes = [ctypes.c_void_p]

bus.dbus_message_unref.restype = None
bus.dbus_message_unref.argtypes = [ctypes.c_void_p]

bus.dbus_message_is_method_call.restype = ctypes.c_int
bus.dbus_message_is_method_call.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]

bus.dbus_message_get_sender.restype = ctypes.c_char_p
bus.dbus_message_get_sender.argtypes = [ctypes.c_void_p]

bus.dbus_message_iter_init.restype = ctypes.c_int
bus.dbus_message_iter_init.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

bus.dbus_message_iter_get_arg_type.restype = ctypes.c_int
bus.dbus_message_iter_get_arg_type.argtypes = [ctypes.c_void_p]

bus.dbus_message_iter_get_basic.restype = None
bus.dbus_message_iter_get_basic.argtypes = [ctypes.c_void_p, ctypes.c_void_p]

bus.dbus_message_iter_next.restype = ctypes.c_int
bus.dbus_message_iter_next.argtypes = [ctypes.c_void_p]

bus.dbus_error_init.restype = None
bus.dbus_error_init.argtypes = [ctypes.c_void_p]

bus.dbus_error_is_set.restype = ctypes.c_int
bus.dbus_error_is_set.argtypes = [ctypes.c_void_p]

# ── SDP запись ───────────────────────────────────────────────────────────────
SDP_RECORD = b"""<?xml version="1.0" encoding="UTF-8" ?>
<record>
  <attribute id="0x0001">
    <sequence>
      <uuid value="00000000-deca-fade-deca-deafdecacaff"/>
    </sequence>
  </attribute>
  <attribute id="0x0004">
    <sequence>
      <sequence>
        <uuid value="0x0100"/>
        <uint16 value="0x0001"/>
      </sequence>
      <sequence>
        <uuid value="0x0003"/>
        <uint8 value="1"/>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0009">
    <sequence>
      <sequence>
        <uuid value="00000000-deca-fade-deca-deafdecacaff"/>
        <uint16 value="0x0002"/>
      </sequence>
    </sequence>
  </attribute>
  <attribute id="0x0100">
    <text value="iAP2"/>
  </attribute>
</record>"""

# ── Message handler ──────────────────────────────────────────────────────────

@ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
def profile_handler(conn, msg, user_data):
    """Обрабатывает входящие D-Bus сообщения для Profile1."""
    iface = b"org.bluez.Profile1"

    if bus.dbus_message_is_method_call(msg, iface, b"NewConnection"):
        sender = bus.dbus_message_get_sender(msg)
        print(f"[iap2] NewConnection from {sender.decode() if sender else '?'}", flush=True)
        reply = bus.dbus_message_new_method_return(msg)
        if reply:
            bus.dbus_connection_send(conn, reply, None)
            bus.dbus_connection_flush(conn)
            bus.dbus_message_unref(reply)

    elif bus.dbus_message_is_method_call(msg, iface, b"RequestDisconnection"):
        print("[iap2] RequestDisconnection", flush=True)
        reply = bus.dbus_message_new_method_return(msg)
        if reply:
            bus.dbus_connection_send(conn, reply, None)
            bus.dbus_connection_flush(conn)
            bus.dbus_message_unref(reply)

    elif bus.dbus_message_is_method_call(msg, iface, b"Release"):
        print("[iap2] Release", flush=True)
        reply = bus.dbus_message_new_method_return(msg)
        if reply:
            bus.dbus_connection_send(conn, reply, None)
            bus.dbus_connection_flush(conn)
            bus.dbus_message_unref(reply)

    else:
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED

    return DBUS_HANDLER_RESULT_HANDLED


# ── VTable ───────────────────────────────────────────────────────────────────

class DBusObjectPathVTable(ctypes.Structure):
    _fields_ = [
        ("unregister_function", ctypes.c_void_p),
        ("message_function", ctypes.c_void_p),
        ("dbus_internal_pad1", ctypes.c_void_p),
        ("dbus_internal_pad2", ctypes.c_void_p),
        ("dbus_internal_pad3", ctypes.c_void_p),
        ("dbus_internal_pad4", ctypes.c_void_p),
    ]

vtable = DBusObjectPathVTable(
    unregister_function=ctypes.cast(None, ctypes.c_void_p).value,
    message_function=ctypes.cast(profile_handler, ctypes.c_void_p).value,
    dbus_internal_pad1=ctypes.cast(None, ctypes.c_void_p).value,
    dbus_internal_pad2=ctypes.cast(None, ctypes.c_void_p).value,
    dbus_internal_pad3=ctypes.cast(None, ctypes.c_void_p).value,
    dbus_internal_pad4=ctypes.cast(None, ctypes.c_void_p).value,
)

# ── Helper: D-Bus call через bus.call_blocking ──────────────────────────────

def dbus_call_blocking(conn, destination, path, interface, method, signature, *args):
    """Вызов D-Bus метода через python-dbus... но dbus нет. Используем subprocess."""
    import subprocess
    cmd = ["dbus-send", "--system", "--print-reply",
           "--dest=" + destination, path,
           interface + "." + method]
    for sig, val in zip(signature, args):
        cmd.append(f"{sig}:{val}")
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return result.returncode == 0, result.stdout + result.stderr
    except Exception as e:
        return False, str(e)


# ── Main ─────────────────────────────────────────────────────────────────────

running = True

def sigint_handler(sig, frame):
    global running
    running = False
    print("[iap2] Shutting down", flush=True)

signal.signal(signal.SIGINT, sigint_handler)
signal.signal(signal.SIGTERM, sigint_handler)


def main():
    global running

    print("[iap2] iAP2 Agent v1.0 (ctypes libdbus-1)", flush=True)
    print(f"[iap2] UUID: {IAP2_UUID}", flush=True)
    print(f"[iap2] RFCOMM channel: {IAP2_RFCOMM_CHANNEL}", flush=True)

    # Подключаемся к system bus
    err = ctypes.c_void_p()
    bus.dbus_error_init(ctypes.byref(err))
    conn = bus.dbus_bus_get(DBUS_BUS_SYSTEM, ctypes.byref(err))
    if not conn:
        print(f"[iap2] Failed to connect to system bus", flush=True)
        sys.exit(1)

    print("[iap2] Connected to system bus", flush=True)

    # Регистрируем D-Bus объект
    bus.dbus_connection_register_object_path(
        conn,
        PROFILE_PATH.encode(),
        ctypes.byref(vtable),
        None
    )
    print(f"[iap2] D-Bus object registered at {PROFILE_PATH}", flush=True)

    # Регистрируем профиль через ProfileManager1
    ok, output = dbus_call_blocking(
        conn,
        "org.bluez",
        "/org/bluez",
        "org.bluez.ProfileManager1",
        "RegisterProfile",
        "o", PROFILE_PATH,
        "s", IAP2_UUID,
    )

    if not ok:
        print(f"[iap2] RegisterProfile failed: {output.strip()}", flush=True)
        bus.dbus_connection_unref(conn)
        sys.exit(1)

    print(f"[iap2] ✓ iAP2 profile registered", flush=True)
    print(f"[iap2] Running. Press Ctrl+C to stop.", flush=True)

    # Main loop
    while running:
        if not bus.dbus_connection_read_write_dispatch(conn, 1000):
            print("[iap2] Connection lost, exiting", flush=True)
            break

    bus.dbus_connection_unref(conn)


if __name__ == "__main__":
    main()
