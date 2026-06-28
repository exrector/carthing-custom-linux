"""CTSP/GATT/L2CAP remote microphone service for the paired Mac."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import struct
import time
from dataclasses import dataclass, field

from app_state import normalize_address
from bumble.core import UUID
from bumble.gatt import Characteristic, Service
from bumble import l2cap

import identity_service

logger = logging.getLogger(__name__)

SESSION_SERVICE_UUID = UUID("C7C50000-0000-4000-8000-00C7C7C7C7C7")
PROTOCOL_VERSION_UUID = UUID("C7C50001-0000-4000-8000-00C7C7C7C7C7")
CAPABILITIES_UUID = UUID("C7C50002-0000-4000-8000-00C7C7C7C7C7")
ENDPOINT_ID_UUID = UUID("C7C50003-0000-4000-8000-00C7C7C7C7C7")
CURRENT_PSM_UUID = UUID("C7C50004-0000-4000-8000-00C7C7C7C7C7")
CLIENT_TOGGLE_UUID = UUID("C7C50005-0000-4000-8000-00C7C7C7C7C7")
STATUS_UUID = UUID("C7C50006-0000-4000-8000-00C7C7C7C7C7")

CTSP_MAGIC = b"CTSP"
CTSP_VERSION = 1
T_HELLO = 0x01
T_CAPABILITIES = 0x02
T_STATUS = 0x03
T_COMMAND = 0x05
T_AUDIO_PCM16 = 0x06
T_ERROR = 0x08
T_AUDIO_IMA_ADPCM = 0x09

IMA_INDEX_TABLE = (-1, -1, -1, -1, 2, 4, 6, 8) * 2
IMA_STEP_TABLE = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
    34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130,
    143, 157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449,
    494, 544, 598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411,
    1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026,
    4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442,
    11487, 12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623,
    27086, 29794, 32767,
)

try:
    from remote_mic_sender import AlsaPcmCapture
except Exception:  # pragma: no cover - device runtime fallback only
    AlsaPcmCapture = None


@dataclass
class SessionConnector:
    address: str
    connection: object | None = None
    channel: object | None = None
    mic_task: object | None = None
    connected: bool = False
    last_seen: float = 0.0
    last_error: str = ""
    rx_buffer: bytearray = field(default_factory=bytearray)
    adpcm_predictor: int = 0
    adpcm_index: int = 0


@dataclass
class SessionRuntime:
    address: str
    connector: SessionConnector


def _ctsp_frame(frame_type: int, payload: bytes = b"", seq: int = 0, flags: int = 0) -> bytes:
    return (
        CTSP_MAGIC
        + bytes([CTSP_VERSION, frame_type & 0xFF])
        + struct.pack(">HII", flags & 0xFFFF, seq & 0xFFFFFFFF, len(payload))
        + payload
    )


class SessionPlaneService:
    def __init__(
        self,
        device,
        app_state,
        model,
        on_change=None,
        on_client_toggle=None,
        on_disconnect=None,
    ):
        self.device = device
        self.state = app_state
        self.model = model
        self.on_change = on_change or (lambda: None)
        self.on_client_toggle = on_client_toggle or (lambda enabled: None)
        self.on_disconnect = on_disconnect or (lambda address: None)
        self.enabled = False
        self.psm = 0
        self._server = None
        self._runtimes: dict[str, SessionRuntime] = {}
        self._status_char: Characteristic | None = None
        self._psm_char: Characteristic | None = None
        self._installed = False
        self._listening = False   # гейт микрофона: труба открыта всегда, звук течёт только при True

    def install(self):
        if self._installed:
            return
        self._server = self.device.create_l2cap_server(
            spec=l2cap.LeCreditBasedChannelSpec(psm=0, max_credits=256),
            handler=self._on_l2cap_channel,
        )
        self.psm = int(self._server.psm)
        self._psm_char = Characteristic(
            CURRENT_PSM_UUID,
            Characteristic.READ | Characteristic.NOTIFY,
            Characteristic.READABLE,
            struct.pack("<H", self.psm),
        )
        self._status_char = Characteristic(
            STATUS_UUID,
            Characteristic.READ | Characteristic.NOTIFY,
            Characteristic.READABLE,
            self._status_bytes(),
        )
        toggle_char = Characteristic(
            CLIENT_TOGGLE_UUID,
            Characteristic.WRITE | Characteristic.WRITE_WITHOUT_RESPONSE,
            Characteristic.WRITEABLE,
            bytes(),
        )
        toggle_char.on("write", self._on_client_toggle_write)
        self.device.add_service(Service(SESSION_SERVICE_UUID, [
            Characteristic(
                PROTOCOL_VERSION_UUID,
                Characteristic.READ,
                Characteristic.READABLE,
                bytes([CTSP_VERSION]),
            ),
            Characteristic(
                CAPABILITIES_UUID,
                Characteristic.READ,
                Characteristic.READABLE,
                self._capabilities_bytes(),
            ),
            Characteristic(
                ENDPOINT_ID_UUID,
                Characteristic.READ,
                Characteristic.READABLE,
                identity_service.visible_name().encode("utf-8"),
            ),
            self._psm_char,
            toggle_char,
            self._status_char,
        ]))
        self._installed = True
        logger.info("session plane GATT/CoC installed: psm=%d", self.psm)

    def set_enabled(self, enabled: bool):
        # enabled = линк/сессия активна (труба открыта). Сам микрофон НЕ стартуется здесь —
        # им управляет self._listening (показ экрана «Ассистент»).
        self.enabled = bool(enabled)
        if not self.enabled:
            self.set_listening(False)
        self._sync_model()
        self._notify_status()

    def set_listening(self, on: bool):
        # Гейт микрофона от состояния активного view. Труба остаётся открытой; работающий
        # _mic_loop сам открывает/закрывает ALSA по этому флагу (мгновенно, без реконнекта).
        on = bool(on)
        if self._listening == on:
            return
        self._listening = on
        logger.info("session listening -> %s", on)
        self._sync_model()
        self._notify_status()

    def _session_rows(self):
        return list(getattr(self.state, "session_peers", []) or [])

    def _runtime(self, address, create=True):
        address = normalize_address(address)
        if not address:
            return None
        runtime = self._runtimes.get(address)
        if runtime is None and create:
            runtime = SessionRuntime(address=address, connector=SessionConnector(address=address))
            self._runtimes[address] = runtime
        return runtime

    def is_session_peer(self, address) -> bool:
        # The runtime calls on_connection() only while the dedicated CTSP
        # advertising window is active. That transport fact is stronger than a
        # persisted central address: macOS commonly rotates its LE address.
        return bool(normalize_address(address))

    def on_connection(self, connection) -> bool:
        address = normalize_address(getattr(connection, "peer_address", ""))
        if not self.is_session_peer(address):
            return False
        runtime = self._runtime(address)
        runtime.connector.connection = connection
        runtime.connector.connected = True
        runtime.connector.last_seen = time.time()
        logger.info("session peer LE attached: %s", address)
        try:
            self.state.note_peer_presence(
                address=address,
                event="incoming_attach",
                plane="session",
                transport="ble_gatt",
                detail="session_peer_le_attached",
            )
        except Exception:
            pass
        connection.on("disconnection", lambda *_: self._on_disconnect(address))
        asyncio.create_task(self._tune_connection(connection))
        self._sync_model()
        self.on_change()
        return True

    async def _tune_connection(self, connection):
        try:
            from bumble.hci import Phy
            await connection.set_phy([Phy.LE_2M], [Phy.LE_2M])
            logger.info("session LE 2M PHY requested")
        except Exception as exc:
            logger.info("session LE PHY unchanged: %s", exc)
        try:
            await connection.update_parameters(
                connection_interval_min=15.0,
                connection_interval_max=15.0,
                max_latency=0,
                supervision_timeout=6000.0,
                use_l2cap=True,
            )
            logger.info("session LE interval requested: 15ms")
        except Exception as exc:
            logger.info("session LE interval unchanged: %s", exc)
        await asyncio.sleep(0.75)
        try:
            await connection.set_data_length(251, 2120)
            logger.info("session LE data length requested: 251 octets")
        except Exception as exc:
            logger.info("session LE data length unchanged: %s", exc)

    def _on_disconnect(self, address):
        runtime = self._runtime(address, create=False)
        if runtime is None:
            return
        was_active = bool(
            runtime.connector.connected
            or runtime.connector.connection is not None
            or runtime.connector.channel is not None
        )
        runtime.connector.connection = None
        runtime.connector.channel = None
        self._stop_mic(runtime)
        runtime.connector.connected = False
        try:
            self.state.note_peer_presence(
                address=address,
                event="disconnect",
                plane="session",
                transport="ble_gatt",
                detail="session_peer_disconnected",
            )
        except Exception:
            pass
        self._sync_model()
        self.on_change()
        if was_active:
            self._notify_disconnect(address)

    def _notify_disconnect(self, address):
        try:
            result = self.on_disconnect(address)
            if asyncio.iscoroutine(result):
                asyncio.create_task(result)
        except Exception as exc:
            logger.warning("session disconnect callback failed: %s", exc)

    def _on_l2cap_channel(self, channel):
        address = normalize_address(getattr(getattr(channel, "connection", None), "peer_address", ""))
        runtime = self._runtime(address)
        if not self.enabled:
            runtime.connector.last_error = "client_off"
            logger.info("session CoC rejected while Client OFF: %s", address or "?")
            asyncio.create_task(channel.disconnect())
            self._sync_model()
            return
        runtime.connector.channel = channel
        runtime.connector.connected = True
        runtime.connector.last_seen = time.time()
        runtime.connector.last_error = ""
        try:
            self.state.note_peer_presence(
                address=address,
                event="session_seen",
                plane="session",
                transport="ble_l2cap_coc",
                detail="ctsp_channel_connected",
            )
        except Exception:
            pass
        channel.sink = lambda data: self._on_channel_data(runtime, channel, data)
        channel.on(
            "close",
            lambda *_: self._on_channel_close(runtime, channel),
        )
        logger.info("session CoC connected: peer=%s psm=%d", address or "?", self.psm)
        self._sync_model()
        self.on_change()
        self._write(channel, T_HELLO, self._status_bytes())

    def _on_channel_close(self, runtime, channel):
        if runtime.connector.channel is not channel:
            return
        runtime.connector.channel = None
        runtime.connector.connected = False
        self._stop_mic(runtime)
        logger.info("session CoC closed: peer=%s", runtime.address)
        self._sync_model()
        self.on_change()
        self._notify_disconnect(runtime.address)
        connection = getattr(channel, "connection", None)
        if connection is not None:
            asyncio.create_task(self._disconnect_if_active(connection, 0.2))

    def _on_channel_data(self, runtime, channel, data: bytes):
        runtime.connector.last_seen = time.time()
        runtime.connector.rx_buffer.extend(data)
        while runtime.connector.rx_buffer:
            buffer = runtime.connector.rx_buffer
            magic_at = buffer.find(CTSP_MAGIC)
            if magic_at < 0:
                buffer.clear()
                runtime.connector.last_error = "bad_ctsp_frame"
                self._write(channel, T_ERROR, b"bad_ctsp_frame")
                self._sync_model()
                return
            if magic_at > 0:
                del buffer[:magic_at]
            if len(buffer) < 16:
                return
            payload_len = struct.unpack(">I", buffer[12:16])[0]
            frame_len = 16 + payload_len
            if payload_len > 65536:
                buffer.clear()
                runtime.connector.last_error = "ctsp_frame_too_large"
                self._write(channel, T_ERROR, b"ctsp_frame_too_large")
                self._sync_model()
                return
            if len(buffer) < frame_len:
                return
            frame = bytes(buffer[:frame_len])
            del buffer[:frame_len]
            self._handle_frame(runtime, channel, frame)

    def _handle_frame(self, runtime, channel, data: bytes):
        frame_type = data[5]
        seq = struct.unpack(">I", data[8:12])[0]
        if frame_type == T_HELLO:
            self._write(channel, T_HELLO, self._status_bytes(), seq=seq)
        elif frame_type == T_CAPABILITIES:
            self._write(channel, T_CAPABILITIES, self._capabilities_bytes(), seq=seq)
        elif frame_type == T_STATUS:
            self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
        elif frame_type == T_COMMAND:
            payload_len = struct.unpack(">I", data[12:16])[0]
            payload = data[16:16 + payload_len].strip()
            logger.info("session command from %s: %r", runtime.address, payload[:80])
            if payload == b"start_mic":
                self._start_mic(runtime, channel)
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
            elif payload == b"stop_mic":
                self._stop_mic(runtime)
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
            elif payload == b"disconnect":
                self._stop_mic(runtime)
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
                asyncio.create_task(self._disconnect_peer(channel))
            elif payload.startswith(b"text:"):
                self._show_screen_text(payload[5:])
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
            else:
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
        else:
            self._write(channel, T_ERROR, b"unsupported_frame_type", seq=seq)

    async def _disconnect_peer(self, channel):
        connection = getattr(channel, "connection", None)
        if connection is not None:
            await self._disconnect_if_active(connection, 0.05)
            return
        try:
            await channel.disconnect()
        except Exception:
            pass

    async def _disconnect_if_active(self, connection, delay):
        await asyncio.sleep(delay)
        try:
            current = self.device.connections.get(connection.handle)
        except Exception:
            current = None
        if current is not connection:
            return
        try:
            await connection.disconnect()
        except Exception as exc:
            logger.info("session ACL already closing: %s", exc)

    @staticmethod
    def _write(channel, frame_type: int, payload: bytes, seq: int = 0):
        try:
            channel.write(_ctsp_frame(frame_type, payload, seq=seq))
        except Exception as exc:
            logger.warning("session CoC write failed: %s", exc)

    def _on_client_toggle_write(self, _connection, value):
        enabled = bool(bytes(value or b"\x00")[0])
        logger.info("session client_toggle via GATT -> %s", enabled)
        self.on_client_toggle(enabled)

    def _start_mic(self, runtime, channel):
        self._stop_mic(runtime)
        if AlsaPcmCapture is None:
            runtime.connector.last_error = "mic_capture_unavailable"
            self._write(channel, T_ERROR, b"mic_capture_unavailable")
            self._sync_model()
            return
        runtime.connector.adpcm_predictor = 0
        runtime.connector.adpcm_index = 0
        runtime.connector.mic_task = asyncio.create_task(self._mic_loop(runtime, channel))
        logger.info("session remote mic started: peer=%s", runtime.address)
        self._sync_model()

    def _stop_mic(self, runtime):
        task = getattr(runtime.connector, "mic_task", None)
        runtime.connector.mic_task = None
        if task is not None and not task.done():
            task.cancel()

    def _show_screen_text(self, raw):
        # Формат payload: "<R>|<text>", R = U(я)/A(ассистент)/S(статус). Без префикса —
        # просто строка (обратная совместимость).
        try:
            s = bytes(raw).decode("utf-8", "replace")
            role = ""
            if len(s) >= 2 and s[1] == "|":
                role = s[0]
                s = s[2:]
            s = s.strip()[:300]
            if role == "S":
                self.state.assistant_status = s     # живой статус (Слушаю…/Думаю…)
                self._sync_model()
                self.on_change()
                return
            if not s:
                return
            label = "Вы" if role == "U" else ("Ассистент" if role == "A" else "")
            line = f"{label}: {s}" if label else s
            self.state.assistant_text = line
            tr = getattr(self.state, "assistant_transcript", None)
            if not isinstance(tr, list):
                tr = []
                self.state.assistant_transcript = tr
            tr.append(line)
            del tr[:-40]
            if role == "A":
                self.state.assistant_status = ""    # ответ пришёл — статус снят
            self._sync_model()
            self.on_change()
            logger.info("session screen text [%s]: %r", role or "?", s[:60])
        except Exception as exc:
            logger.warning("session screen text failed: %s", exc)

    async def _mic_loop(self, runtime, channel):
        device = os.environ.get("CARTHING_BT_MIC_PCM_DEV", "/dev/snd/pcmC0D1c")
        source_rate = int(os.environ.get("CARTHING_BT_MIC_SOURCE_RATE", "48000"))
        source_channels = int(os.environ.get("CARTHING_BT_MIC_SOURCE_CHANNELS", "4"))
        target_rate = 8000
        read_frames = int(os.environ.get("CARTHING_BT_MIC_READ_FRAMES", "4800"))
        gain = float(os.environ.get("CARTHING_BT_MIC_GAIN", "2.0"))
        mix_mode = os.environ.get("CARTHING_BT_MIC_MIX", "avg").strip().lower()
        cap = None
        try:
            # Труба к Mac держится постоянно (задача жива весь коннект), но ALSA-захват
            # включается ТОЛЬКО когда self._listening (показан экран «Ассистент»). Вход на
            # view = звук мгновенно, без реконнекта; уход = ALSA освобождается.
            while getattr(runtime.connector, "channel", None) is channel:
                if not self._listening:
                    if cap is not None:
                        try:
                            cap.close()
                        except Exception:
                            pass
                        cap = None
                        logger.info("session remote mic paused (view off): peer=%s", runtime.address)
                    await asyncio.sleep(0.05)
                    continue
                if cap is None:
                    self._set_device_mic_gain()
                    cap = AlsaPcmCapture(device, source_rate, source_channels)
                    info = cap.open()
                    logger.info(
                        "session remote mic capture open: peer=%s device=%s rate=%s channels=%s gain=%.2f info=%s",
                        runtime.address, device, source_rate, source_channels, gain, info,
                    )
                raw = await asyncio.to_thread(cap.read, read_frames)
                if not raw:
                    await asyncio.sleep(0.01)
                    continue
                pcm16 = self._downmix_resample_16k(raw, source_rate, source_channels, target_rate, gain, mix_mode)
                if pcm16:
                    payload, predictor, index = self._ima_adpcm_encode(
                        pcm16,
                        runtime.connector.adpcm_predictor,
                        runtime.connector.adpcm_index,
                    )
                    runtime.connector.adpcm_predictor = predictor
                    runtime.connector.adpcm_index = index
                    self._write(channel, T_AUDIO_IMA_ADPCM, payload)
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            runtime.connector.last_error = f"mic_capture_error:{type(exc).__name__}"
            logger.warning("session remote mic failed: peer=%s error=%s", runtime.address, exc)
            try:
                self._write(channel, T_ERROR, runtime.connector.last_error.encode("utf-8"))
            except Exception:
                pass
            self._sync_model()
        finally:
            if cap is not None:
                try:
                    cap.close()
                except Exception:
                    pass
            if getattr(runtime.connector, "mic_task", None) is asyncio.current_task():
                runtime.connector.mic_task = None
            logger.info("session remote mic stopped: peer=%s", runtime.address)

    @staticmethod
    def _set_device_mic_gain():
        # Железное усиление PDM-миков = ALSA-контрол "PDM HCIC shift gain" в SoC, index 1 = +16 дБ.
        # НЕ tlv320adc3101 lr_gain — того чипа на плате НЕТ (доказано: I2C-скан, привязка драйверов,
        # инвентарь, T9015-capture=тишина). См. docs/MIC-PDM-AUDIO-CHAIN-INVESTIGATION-2026-06-24.md.
        import ctypes
        import fcntl
        target = int(os.environ.get("CARTHING_BT_MIC_HCIC_GAIN", "1"))

        class _Id(ctypes.Structure):
            _fields_ = [("numid", ctypes.c_uint), ("iface", ctypes.c_int), ("device", ctypes.c_uint),
                        ("subdevice", ctypes.c_uint), ("name", ctypes.c_char * 44), ("index", ctypes.c_uint)]

        class _List(ctypes.Structure):
            _fields_ = [("offset", ctypes.c_uint), ("space", ctypes.c_uint), ("used", ctypes.c_uint),
                        ("count", ctypes.c_uint), ("pids", ctypes.c_void_p), ("reserved", ctypes.c_ubyte * 50)]

        class _Val(ctypes.Structure):
            _fields_ = [("id", _Id), ("indirect", ctypes.c_uint),
                        ("value", ctypes.c_long * 128), ("reserved", ctypes.c_ubyte * 128)]

        def _ioc(nr, size):
            return (3 << 30) | (size << 16) | (ord("U") << 8) | nr

        LIST = _ioc(0x10, ctypes.sizeof(_List))
        WRITE = _ioc(0x13, ctypes.sizeof(_Val))
        try:
            fd = os.open("/dev/snd/controlC0", os.O_RDWR)
        except OSError as exc:
            logger.warning("mic HCIC gain: open controlC0 failed: %s", exc)
            return
        try:
            el = _List(); fcntl.ioctl(fd, LIST, el)
            arr = (_Id * el.count)()
            el2 = _List(); el2.space = el.count; el2.pids = ctypes.cast(arr, ctypes.c_void_p)
            fcntl.ioctl(fd, LIST, el2)
            numid = None
            for i in range(el2.used):
                nm = arr[i].name.decode("ascii", "replace").lower()
                if "hcic" in nm and "gain" in nm:
                    numid = arr[i].numid
                    break
            if numid is None:
                logger.warning("mic HCIC gain: control not found")
                return
            ev = _Val(); ev.id.numid = numid; ev.value[0] = target
            fcntl.ioctl(fd, WRITE, ev)
            logger.info("mic HCIC gain set: numid=%d value=%d", numid, target)
        except Exception as exc:
            logger.warning("mic HCIC gain ignored: %s", exc)
        finally:
            os.close(fd)

    @staticmethod
    def _downmix_resample_16k(
        raw: bytes,
        source_rate: int,
        channels: int,
        target_rate: int,
        gain: float = 1.0,
        mix_mode: str = "avg",
    ) -> bytes:
        if channels <= 0 or source_rate <= 0:
            return b""
        bytes_per_frame = channels * 2
        frame_count = len(raw) // bytes_per_frame
        if frame_count <= 0:
            return b""
        step = max(1, int(round(source_rate / target_rate)))
        gain = max(0.1, min(float(gain), 12.0))
        # 1) downmix всех каналов -> моно @source_rate СРЕДНИМ (не maxabs: maxabs
        #    сшивает куски разных миков и плодит широкополосный треск).
        unpack = struct.unpack_from
        inv_ch = 1.0 / channels
        mono = [0.0] * frame_count
        for f in range(frame_count):
            base = f * bytes_per_frame
            s = 0
            for ch in range(channels):
                s += unpack("<h", raw, base + ch * 2)[0]
            mono[f] = s * inv_ch
        # 2) box-FIR анти-алиас окном 2*step (нуль АЧХ на целевом Nyquist) + хоп step.
        #    Без него дециммация "каждый 3-й" заворачивает 8-24кГц в речь как шипящий
        #    пол -> эндпоинтер/Whisper принимают паузу за голос.
        win = max(1, step * 2)
        inv_win = 1.0 / win
        out = bytearray()
        i = 0
        limit = frame_count - win
        while i <= limit:
            acc = 0.0
            for k in range(win):
                acc += mono[i + k]
            sample = int(acc * inv_win * gain)
            if sample > 32767:
                sample = 32767
            elif sample < -32768:
                sample = -32768
            out += struct.pack("<h", sample)
            i += step
        return bytes(out)

    @staticmethod
    def _ima_adpcm_encode(pcm16: bytes, predictor: int = 0, index: int = 0):
        count = len(pcm16) // 2
        if count <= 0:
            return b"", predictor, index
        samples = struct.unpack("<%dh" % count, pcm16[:count * 2])
        if predictor == 0 and index == 0:
            predictor = int(samples[0])
        start_predictor = predictor
        start_index = max(0, min(88, int(index)))
        nibbles = []
        for sample in samples:
            step = IMA_STEP_TABLE[index]
            diff = int(sample) - predictor
            code = 0
            if diff < 0:
                code = 8
                diff = -diff
            delta = step >> 3
            if diff >= step:
                code |= 4
                diff -= step
                delta += step
            if diff >= (step >> 1):
                code |= 2
                diff -= step >> 1
                delta += step >> 1
            if diff >= (step >> 2):
                code |= 1
                delta += step >> 2
            predictor += -delta if code & 8 else delta
            predictor = max(-32768, min(32767, predictor))
            index = max(0, min(88, index + IMA_INDEX_TABLE[code]))
            nibbles.append(code)
        packed = bytearray()
        for offset in range(0, len(nibbles), 2):
            low = nibbles[offset]
            high = nibbles[offset + 1] if offset + 1 < len(nibbles) else 0
            packed.append(low | (high << 4))
        return struct.pack("<hBB", start_predictor, start_index, 0) + bytes(packed), predictor, index

    def _capabilities_bytes(self) -> bytes:
        return json.dumps({
            "roles": ["session_peer", "remote_mic_receiver"],
            "protocol_version": CTSP_VERSION,
            "transports": ["ble_gatt_bootstrap", "ble_l2cap_coc_session"],
            "remote_mic": {
                "format": "ima_adpcm",
                "sample_rate_hz": 8000,
                "channels": 1,
                "mode": "on_demand",
            },
        }, separators=(",", ":")).encode("utf-8")

    def _status_bytes(self) -> bytes:
        connected = [
            runtime.address for runtime in self._runtimes.values()
            if runtime.connector.connected or runtime.connector.channel is not None
        ]
        streaming = [
            runtime.address for runtime in self._runtimes.values()
            if self._listening and runtime.connector.mic_task is not None
        ]
        return json.dumps({
            "client_enabled": bool(self.enabled),
            "psm": int(self.psm),
            "connected": connected,
            "streaming_mic": streaming,
        }, separators=(",", ":")).encode("utf-8")

    def _notify_status(self):
        if self._status_char is None:
            return
        payload = self._status_bytes()
        self._status_char.value = payload
        try:
            asyncio.create_task(self.device.notify_subscribers(self._status_char, payload))
        except Exception:
            pass

    def _sync_model(self):
        connectors = [runtime.connector for runtime in self._runtimes.values()]
        connected = any(connector.channel is not None for connector in connectors)
        if not self._listening:
            state = "off"
            message = "Микрофон выключен"
        elif connected:
            state = "listening"
            message = "Слушаю"
        else:
            state = "connecting"
            message = "Подключение к Mac"
        self.model.set_remote_mic(
            self._listening,
            state=state,
            message=message,
            transport="ble_l2cap_coc" if connected else "none",
        )
