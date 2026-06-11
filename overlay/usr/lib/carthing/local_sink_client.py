"""Клиент локального аудио-приёмника для runtime/a2dp_bridge (этаж 4, сторона моста).

Назначение: ультра-дешёвая неблокирующая отправка BT-кадров в sink-ПРОЦЕСС
(audio_local_sink.py serve). Вызывается из forward_packet — самого горячего
пути системы, поэтому правила жёсткие:
  • НИКАКИХ блокировок: сокет non-blocking, EAGAIN = дроп кадра (live!);
  • НИКАКИХ исключений наружу: любой сбой = кадр потерян + ленивый реконнект;
  • процесс-демон поднимается лениво при первом use и переживает наш рестарт
    (он самостоятелен; двойной запуск исключён — bind сокета у живого упадёт).

[CLAUDE 2026-06-12] Codex: интерфейс стабилен — enabled (флаг), send(codec, payload),
stop(). Менять протокол кадра синхронно с audio_local_sink.CODEC_IDS.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import time

logger = logging.getLogger("carthing.local_sink_client")

SINK_SOCKET = "/run/carthing/local-sink.sock"
_CODEC_TO_ID = {"pcm": 0, "aac": 1, "sbc": 2}
_RECONNECT_EVERY_SEC = 2.0


class LocalSinkClient:
    def __init__(self):
        self._sock: socket.socket | None = None
        self._last_attempt = 0.0
        self._daemon: subprocess.Popen | None = None
        self.frames_sent = 0
        self.frames_lost = 0

    # ── жизненный цикл ────────────────────────────────────────────────────────
    def _ensure_daemon(self) -> None:
        """Ленивый старт процесса-демона. Если демон уже жив (наш или чужой) —
        bind у нового упадёт и он тихо умрёт; нам важен только сокет."""
        if self._daemon is not None and self._daemon.poll() is None:
            return
        if os.path.exists(SINK_SOCKET):
            return  # кто-то уже слушает (пережил наш рестарт) — отлично
        try:
            self._daemon = subprocess.Popen(
                ["python3", os.path.join(os.path.dirname(__file__), "audio_local_sink.py"), "serve"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            logger.info("local sink daemon spawned pid=%s", self._daemon.pid)
        except Exception as e:
            logger.warning("local sink daemon spawn failed: %s", e)

    def _connect(self) -> None:
        now = time.monotonic()
        if now - self._last_attempt < _RECONNECT_EVERY_SEC:
            return
        self._last_attempt = now
        self._ensure_daemon()
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
            s.setblocking(False)
            s.connect(SINK_SOCKET)
            self._sock = s
            logger.info("local sink connected")
        except Exception:
            self._sock = None   # демон ещё поднимается — попробуем через 2с

    def stop(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    # ── горячий путь (из forward_packet) ─────────────────────────────────────
    def send(self, codec: str, payload: bytes) -> bool:
        """True = кадр ушёл. False = потерян (демон не готов/задохнулся) —
        вызывающий НЕ должен ретраить, это live-аудио."""
        if self._sock is None:
            self._connect()
            if self._sock is None:
                self.frames_lost += 1
                return False
        try:
            self._sock.send(bytes([_CODEC_TO_ID.get(codec, 255)]) + payload)
            self.frames_sent += 1
            return True
        except BlockingIOError:
            self.frames_lost += 1          # очередь сокета полна — дроп, не ждём
            return False
        except Exception:
            self.stop()                     # разрыв — ленивый реконнект потом
            self.frames_lost += 1
            return False
