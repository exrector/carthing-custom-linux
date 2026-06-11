#!/usr/bin/env python3
"""HCI TCP proxy — run on Car Thing, connect from macOS.

Usage on device:
    python3 /tmp/hci_proxy.py            # default port 6402, adapter 0
    python3 /tmp/hci_proxy.py 6402 0

Usage on macOS (carthing_runtime.py):
    CAR_THING_TRANSPORT=tcp-client:172.16.42.77:6402 python3 carthing_runtime.py

One client at a time. Restart proxy to reconnect.
"""
import asyncio
import ctypes
import os
import socket
import struct
import sys

PORT    = int(sys.argv[1]) if len(sys.argv) > 1 else 6402
ADAPTER = int(sys.argv[2]) if len(sys.argv) > 2 else 0

AF_BLUETOOTH     = getattr(socket, 'AF_BLUETOOTH', 31)
BTPROTO_HCI      = getattr(socket, 'BTPROTO_HCI', 1)
HCI_CHANNEL_USER = 1


def _quarantined() -> bool:
    """Block accidental HCI ownership by old Bumble test tooling."""
    return (
        os.environ.get("CARTHING_BUMBLE_QUARANTINE", "1") != "0"
        or os.environ.get("CARTHING_ALLOW_BUMBLE_RUN", "0") != "1"
    )


def _open_hci(adapter: int) -> socket.socket:
    s = socket.socket(AF_BLUETOOTH, socket.SOCK_RAW | socket.SOCK_NONBLOCK, BTPROTO_HCI)
    # Python's socket.bind() doesn't support the HCI sockaddr layout — use libc directly
    libc = ctypes.CDLL('libc.so.6', use_errno=True)
    libc.bind.argtypes = (ctypes.c_int, ctypes.POINTER(ctypes.c_char), ctypes.c_int)
    libc.bind.restype  = ctypes.c_int
    addr = struct.pack('<HHH', AF_BLUETOOTH, adapter, HCI_CHANNEL_USER)
    if libc.bind(s.fileno(), ctypes.create_string_buffer(addr), len(addr)) != 0:
        raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
    return s


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter,
                  hci: socket.socket, loop: asyncio.AbstractEventLoop) -> None:
    print(f"[hci_proxy] client {writer.get_extra_info('peername')}")

    async def hci_to_tcp():
        while True:
            data = await loop.sock_recv(hci, 4096)
            if not data:
                break
            writer.write(data)
            await writer.drain()

    async def tcp_to_hci():
        while True:
            data = await reader.read(4096)
            if not data:
                break
            await loop.sock_sendall(hci, data)

    try:
        await asyncio.gather(hci_to_tcp(), tcp_to_hci())
    except Exception as e:
        print(f"[hci_proxy] closed: {e}")
    finally:
        writer.close()


async def main():
    if _quarantined():
        print("[hci_proxy] Bumble/HCI proxy quarantined; set CARTHING_BUMBLE_QUARANTINE=0 CARTHING_ALLOW_BUMBLE_RUN=1 for a manual lab run")
        return
    hci  = _open_hci(ADAPTER)
    loop = asyncio.get_running_loop()
    print(f"[hci_proxy] hci{ADAPTER} open, listening on :{PORT}")
    server = await asyncio.start_server(
        lambda r, w: _handle(r, w, hci, loop), '0.0.0.0', PORT)
    async with server:
        await server.serve_forever()


asyncio.run(main())
