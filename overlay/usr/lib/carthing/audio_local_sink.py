"""Локальный аудио-приёмник: BT-кадры -> декодер -> T9015 DAC.

ЭТАЖ 2 «работы над чипом» (этаж 1 — audio_out_t9015.py, движок ЦАП).

АРХИТЕКТУРА (Codex, это твоя карта):

  a2dp_bridge.forward_packet()                # ЕДИНСТВЕННАЯ точка врезки!
      │  if активный выход == LOCAL_SINK:
      │      local_sink.feed_rtp(codec, payload)   # неблокирующе, только put в очередь
      ▼
  AudioLocalSink (этот модуль)
      ├─ deque кадров (bounded, drop-oldest — отставать нельзя, это live)
      ├─ ПОТОК-плеер (НЕ asyncio! write() в ALSA блокируется по темпу железа —
      │   это наш генератор темпа, но он смертелен для BT event-loop:
      │   тот же урок, что с рендером, см. carthing-debug-log 2026-06-12)
      ├─ decoder: AudioDecoder (гнездо ниже) -> PCM S16_LE 48k stereo
      └─ T9015AudioOutput.write(pcm)

  ДЕКОДЕР — следующий этаж (НЕ написан, гнездо готово):
    • вариант А (приоритет): /dev/audiodsp0 — аппаратный декодер Amlogic
      (ресёрч = задача B ранбука; ioctl-интерфейс в драйвере ядра 4.9
      drivers/amlogic/audiodsp/). Кормим AAC/ADTS — забираем PCM.
    • вариант Б: программный SBC-декодер (SBC прост; для AAC софт нереален
      на A53 в Python — только через DSP или нативную либу).
    Какой бы ни был — он реализует AudioDecoder.decode() и ВСЁ.

  РЕГИСТРАЦИЯ В МАРШРУТАХ (этаж 3, только когда декодер заработает):
    честный endpoint «Car Thing line-out» в route_outputs (app_state):
    capabilities=[audio_output], protocols=[local_t9015]. До рабочего
    декодера endpoint НЕ показывать — мы только что воевали с нечестным GUI
    (boot-честность, RUNBOOK §дизайн №5): выход, который не звучит, в списке
    появляться не должен.

ПРОВЕРКА БЕЗ ДЕКОДЕРА (уже можно): PassthroughPcmDecoder принимает СЫРОЙ PCM
(для тестов: feed_rtp("pcm", raw_s16le)) — путь очередь->поток->ЦАП гоняется
без BT вообще:  python3 audio_local_sink.py selftest

[CLAUDE 2026-06-12] этаж 2 по слову владельца: «главное, чтобы ЦАП работал
в наших маршрутах». Каждый шов подписан.
"""
from __future__ import annotations

import collections
import logging
import os
import threading
import time

from audio_out_t9015 import T9015AudioOutput

logger = logging.getLogger("carthing.local_sink")

# ключ будущего endpoint'а в route_outputs (этаж 3)
LOCAL_SINK_KEY = "carthing-lineout"


class AudioDecoder:
    """Гнездо декодера. Контракт:
    decode(codec, payload) -> bytes PCM S16_LE 48000 Hz stereo (может вернуть
    b"" — кадр проглочен, напр. заголовок). payload = RTP payload БЕЗ RTP-шапки
    (forward_packet отдаёт уже payload). Реализации обязаны быть thread-safe
    или использоваться только из потока-плеера (наш случай)."""

    def decode(self, codec: str, payload: bytes) -> bytes:
        raise NotImplementedError


class PassthroughPcmDecoder(AudioDecoder):
    """Для тестов тракта: вход уже PCM (codec=="pcm")."""

    def decode(self, codec: str, payload: bytes) -> bytes:
        if codec != "pcm":
            raise ValueError(f"PassthroughPcmDecoder не умеет {codec}; нужен DSP-декодер (задача B)")
        return payload


class AudioLocalSink:
    """Очередь + поток-плеер. Жизненный цикл:
        sink = AudioLocalSink(decoder)
        sink.start()                  # открывает ЦАП, поднимает поток
        sink.feed_rtp(codec, bytes)   # из forward_packet, неблокирующе
        sink.stop()                   # дренаж и закрытие
    Codex: start/stop дёргать из route-логики (этаж 3), НЕ из __init__ runtime —
    ЦАП держим открытым только пока локальный выход активен."""

    MAX_FRAMES = 256          # ~ несколько секунд кадров; дальше drop-oldest

    def __init__(self, decoder: AudioDecoder):
        self.decoder = decoder
        self._frames: collections.deque = collections.deque(maxlen=self.MAX_FRAMES)
        self._wake = threading.Event()
        self._run = False
        self._thread: threading.Thread | None = None
        self._out: T9015AudioOutput | None = None
        self.frames_in = 0
        self.frames_played = 0
        self.frames_dropped = 0    # вытеснены из полной очереди (live, отставать нельзя)
        self.decode_errors = 0

    # ── интерфейс для a2dp_bridge (единственная точка врезки) ────────────────
    def feed_rtp(self, codec: str, payload: bytes) -> None:
        if not self._run:
            return
        if len(self._frames) == self._frames.maxlen:
            self.frames_dropped += 1
        self._frames.append((codec, payload))
        self.frames_in += 1
        self._wake.set()

    # ── жизненный цикл ────────────────────────────────────────────────────────
    def start(self) -> None:
        if self._run:
            return
        self._out = T9015AudioOutput()
        info = self._out.open()
        logger.info("local sink: T9015 open %s", info)
        self._run = True
        self._thread = threading.Thread(target=self._player, name="t9015-player", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._run = False
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        if self._out is not None:
            self._out.close()
            self._out = None
        logger.info("local sink: stopped in=%d played=%d dropped=%d decode_errors=%d",
                    self.frames_in, self.frames_played, self.frames_dropped, self.decode_errors)

    # ── поток-плеер (владеет декодером и ЦАПом; темп задаёт ALSA write) ──────
    def _player(self) -> None:
        while self._run:
            try:
                codec, payload = self._frames.popleft()
            except IndexError:
                self._wake.clear()
                self._wake.wait(timeout=0.5)
                continue
            try:
                pcm = self.decoder.decode(codec, payload)
            except Exception as e:
                self.decode_errors += 1
                if self.decode_errors <= 3 or self.decode_errors % 250 == 0:
                    logger.warning("local sink decode error #%d: %s", self.decode_errors, e)
                continue
            if pcm and self._out is not None:
                self._out.write(pcm)     # блокируется по темпу железа — и хорошо
                self.frames_played += 1


# ── процессный режим (этаж 2.5): sink как ОТДЕЛЬНЫЙ процесс ──────────────────
# Зачем процесс, а не поток: GIL. Декодер (этаж 3) — чистый CPU; в потоке он
# кусал бы BT-интерпретатор так же, как рендер (см. carthing-debug-log
# 2026-06-12). Отдельный процесс = своё ядро A53, runtime не трогаем вообще.
# Протокол: AF_UNIX SOCK_SEQPACKET (границы кадров хранит ядро),
# кадр = 1 байт codec_id + payload. Подключение = старт ЦАП, разрыв = стоп.
SINK_SOCKET = "/run/carthing/local-sink.sock"
CODEC_IDS = {0: "pcm", 1: "aac", 2: "sbc"}


def _serve() -> int:
    import socket as _socket
    logging.basicConfig(level=logging.INFO)
    try:
        os.unlink(SINK_SOCKET)
    except FileNotFoundError:
        pass
    srv = _socket.socket(_socket.AF_UNIX, _socket.SOCK_SEQPACKET)
    srv.bind(SINK_SOCKET)
    srv.listen(1)
    logger.info("local sink daemon: listening %s", SINK_SOCKET)
    while True:
        conn, _ = srv.accept()
        # декодер выбирается на подключение; пока есть только passthrough-PCM.
        # Codex (этаж 3): сюда встаёт DspDecoder (audiodsp_decoder.py), выбор по
        # codec_id кадра — см. AudioDecoder.decode(codec, payload).
        sink = AudioLocalSink(PassthroughPcmDecoder())
        try:
            sink.start()
            logger.info("local sink daemon: client connected, DAC open")
            while True:
                frame = conn.recv(65536)
                if not frame:
                    break
                codec = CODEC_IDS.get(frame[0], "?")
                sink.feed_rtp(codec, frame[1:])
        except Exception as e:
            logger.warning("local sink daemon: client error: %s", e)
        finally:
            sink.stop()
            conn.close()
            logger.info("local sink daemon: client gone, DAC closed")


def _selftest() -> int:
    """Тракт очередь->поток->ЦАП без BT: секунды синуса кусками по 20 мс."""
    import math, struct
    logging.basicConfig(level=logging.INFO)
    sink = AudioLocalSink(PassthroughPcmDecoder())
    sink.start()
    chunk = 960  # 20 мс @ 48k
    for i in range(150):                       # 3 секунды
        pcm = bytearray()
        for j in range(chunk):
            t = (i * chunk + j) / 48000.0
            v = int(12000 * math.sin(2 * math.pi * 440 * t))
            pcm += struct.pack("<hh", v, v)
        sink.feed_rtp("pcm", bytes(pcm))
        time.sleep(0.02)                       # имитация live-темпа
    time.sleep(0.5)
    sink.stop()
    ok = sink.frames_played >= 140 and sink.decode_errors == 0
    print(f"selftest: played={sink.frames_played}/150 dropped={sink.frames_dropped} -> {'OK' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    import os as _os
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        sys.exit(_serve())
    sys.exit(_selftest())
