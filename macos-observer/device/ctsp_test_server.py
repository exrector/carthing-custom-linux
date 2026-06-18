#!/usr/bin/env python3
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️ ВРЕМЕННЫЙ ТЕСТОВЫЙ ФАЙЛ КЛИЕНТ-СЕРВЕР (Claude, 2026-06-18).
# Эталонный device-side CTSP-сервер для проб связки клиент-сервер.
# СЛУШАЕТ TCP поверх usb0 — НЕ трогает hci0/BT (его держит carthing_runtime Codex).
# BLE L2CAP CoC — это будущая замена транспорта, не этот файл.
# Деплоится в /tmp/claude-ctsp-test/ на устройстве. Убивать после теста.
# Стандартная библиотека Python, без зависимостей. См. macos-observer/MANIFEST.md.
# ─────────────────────────────────────────────────────────────────────────────
import json
import math
import socket
import struct
import sys
import threading
import time

MAGIC = b"CTSP"
HEADER = struct.Struct(">4sBBHII")  # magic, version, type, flags, seq, len
VERSION = 1

# Типы кадров (источник истины — Sources/ProtocolCore/CTSPFrameType.swift).
T_HELLO = 0x01
T_CAPABILITIES = 0x02
T_STATUS = 0x03
T_ROUTE_STATE = 0x04
T_COMMAND = 0x05
T_AUDIO_PCM16 = 0x06
T_TELEMETRY = 0x07
T_ERROR = 0x08

SR = 16000          # sample rate
FRAME_MS = 20       # 20 мс -> 320 сэмплов
TONE_HZ = 440.0
AMP = 0.3


def encode(ftype, payload=b"", seq=0, flags=0):
    return HEADER.pack(MAGIC, VERSION, ftype, flags, seq, len(payload)) + payload


def route_state_json(mic_active, phase):
    # Ключи и значения должны совпадать с Swift SessionSnapshot (Codable).
    return json.dumps({
        "mode": "playNow",
        "activeAudioInput": "iPhone",
        "activeOutputSink": "local",
        "sessionPhase": phase,
        "transportPhase": "idle",
        "clientEnabled": True,
        "micActive": mic_active,
    }).encode()


class Conn:
    def __init__(self, sock, addr):
        self.sock = sock
        self.addr = addr
        self.buf = bytearray()
        self.seq = 0
        self.mic_stop = threading.Event()
        self.mic_thread = None

    def log(self, msg):
        print(f"[server {self.addr}] {msg}", flush=True)

    def send(self, ftype, payload=b""):
        self.seq += 1
        try:
            self.sock.sendall(encode(ftype, payload, self.seq))
        except OSError as e:
            self.log(f"send err: {e}")

    def run(self):
        self.log("клиент подключился -> capabilities + route_state")
        caps = json.dumps({
            "roles": ["audio_input", "session_peer", "remote_mic_receiver"],
            "protocol_version": VERSION,
            "device": "QN19",
        }).encode()
        self.send(T_CAPABILITIES, caps)
        self.send(T_ROUTE_STATE, route_state_json(False, "connected"))

        while True:
            try:
                chunk = self.sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            self.buf += chunk
            self._drain()
        self.stop_mic()
        self.log("клиент отключился")

    def _drain(self):
        while len(self.buf) >= HEADER.size:
            magic, ver, ftype, flags, seq, ln = HEADER.unpack(self.buf[:HEADER.size])
            if magic != MAGIC:
                self.log(f"bad magic, сброс буфера")
                self.buf.clear()
                return
            if len(self.buf) < HEADER.size + ln:
                return
            payload = bytes(self.buf[HEADER.size:HEADER.size + ln])
            del self.buf[:HEADER.size + ln]
            self.handle(ftype, payload)

    def handle(self, ftype, payload):
        if ftype == T_HELLO:
            self.send(T_HELLO, payload)  # эхо для RTT
            self.log(f"hello <- эхо ({len(payload)} б)")
        elif ftype == T_COMMAND:
            cmd = payload.decode("utf-8", "replace")
            self.log(f"команда: {cmd}")
            if cmd == "start_mic":
                self.start_mic()
            elif cmd == "stop_mic":
                self.stop_mic()
            elif cmd == "route":
                self.send(T_ROUTE_STATE, route_state_json(self.mic_thread is not None, "connected"))
            else:
                self.send(T_ERROR, f"unknown command: {cmd}".encode())

    def start_mic(self):
        self.stop_mic()
        self.mic_stop.clear()
        self.send(T_ROUTE_STATE, route_state_json(True, "streamingMic"))
        self.mic_thread = threading.Thread(target=self._mic_loop, daemon=True)
        self.mic_thread.start()
        self.log("mic стрим стартовал")

    def stop_mic(self):
        if self.mic_thread:
            self.mic_stop.set()
            self.mic_thread.join(timeout=1)
            self.mic_thread = None
            self.send(T_ROUTE_STATE, route_state_json(False, "connected"))
            self.log("mic стрим остановлен")

    def _mic_loop(self):
        samples = SR * FRAME_MS // 1000
        step = 2 * math.pi * TONE_HZ / SR
        phase = 0.0
        period = FRAME_MS / 1000.0
        while not self.mic_stop.is_set():
            pcm = bytearray()
            for _ in range(samples):
                v = math.sin(phase) * AMP
                phase += step
                if phase > 2 * math.pi:
                    phase -= 2 * math.pi
                pcm += struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767))
            self.send(T_AUDIO_PCM16, bytes(pcm))
            time.sleep(period)


def main():
    host = "0.0.0.0"
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 7777
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(1)
    print(f"[server] CTSP TCP сервер слушает {host}:{port} (usb0, БЕЗ hci0)", flush=True)
    try:
        while True:
            sock, addr = srv.accept()
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            Conn(sock, addr).run()
            sock.close()
    except KeyboardInterrupt:
        pass
    finally:
        srv.close()


if __name__ == "__main__":
    main()
