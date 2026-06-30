"""CTSP/GATT/L2CAP remote microphone service for the paired Mac."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import struct
import time
from dataclasses import dataclass, field

from app_state import normalize_address
from bumble.core import UUID
from bumble.gatt import Characteristic, Service
from bumble import l2cap

import identity_service
from maintenance_service import MaintenanceError, MaintenanceService
from connection_journal import record_connection_event

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
T_LATENCY_PROBE = 0x0A
T_AUDIO_OPUS = 0x0B
T_MAINTENANCE = 0x0C

AUDIO_TIMING_FLAG = 1 << 8
AUDIO_RATE_16K_FLAG = 1 << 9
AUDIO_TIMING_HEADER = struct.Struct(">QQI")

try:
    from remote_mic_sender import AlsaPcmCapture, CarThingVoiceDsp
except Exception:  # pragma: no cover - device runtime fallback only
    AlsaPcmCapture = None
    CarThingVoiceDsp = None


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
    audio_seq: int = 0
    handshake_task: object | None = None


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
        on_remote_media_clear=None,
        hci_gate=None,
    ):
        self.device = device
        self.state = app_state
        self.model = model
        self.on_change = on_change or (lambda: None)
        self.on_client_toggle = on_client_toggle or (lambda enabled: None)
        self.on_disconnect = on_disconnect or (lambda address: None)
        self.on_remote_media_clear = on_remote_media_clear or (lambda: None)
        self.hci_gate = hci_gate
        self.enabled = False
        self.psm = 0
        self._server = None
        self._runtimes: dict[str, SessionRuntime] = {}
        self._status_char: Characteristic | None = None
        self._psm_char: Characteristic | None = None
        self._installed = False
        self._listening = False   # гейт микрофона: труба открыта всегда, звук течёт только при True
        self._remote_media_owner = ""
        self._plugin_owner = ""
        self._maintenance = MaintenanceService()

    async def _gate(self, label, operation):
        if self.hci_gate is None:
            return await operation()
        return await self.hci_gate.run(label, operation)

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
        # им управляет сохранённый пользовательский переключатель self._listening.
        self.enabled = bool(enabled)
        if not self.enabled:
            self.set_listening(False)
        self._sync_model()
        self._notify_status()

    def set_listening(self, on: bool):
        # Труба остаётся открытой; _mic_loop открывает/закрывает ALSA по этому
        # флагу мгновенно, без переподключения Bluetooth.
        on = bool(on)
        if self._listening == on:
            return
        self._listening = on
        logger.info("session listening -> %s", on)
        for runtime in self._runtimes.values():
            channel = runtime.connector.channel
            if on and channel is not None:
                self._start_mic(runtime, channel)
            elif not on:
                self._stop_mic(runtime)
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
        record_connection_event("session_le_attached", peer=address)
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
        connection.on(
            "disconnection",
            lambda *_, attached=connection: self._on_disconnect(address, attached),
        )
        connection.on(
            "connection_parameters_update",
            lambda: self._log_connection_parameters(connection, "updated"),
        )
        self._log_connection_parameters(connection, "negotiated")
        asyncio.create_task(self._tune_connection(connection))
        old_watchdog = runtime.connector.handshake_task
        if old_watchdog is not None and not old_watchdog.done():
            old_watchdog.cancel()
        runtime.connector.handshake_task = asyncio.create_task(
            self._handshake_watchdog(runtime, connection)
        )
        self._sync_model()
        self.on_change()
        return True

    @staticmethod
    def _log_connection_parameters(connection, stage):
        parameters = getattr(connection, "parameters", None)
        if parameters is None:
            return
        logger.info(
            "session LE parameters %s: interval=%.1fms latency=%d timeout=%.0fms",
            stage,
            float(parameters.connection_interval),
            int(parameters.peripheral_latency),
            float(parameters.supervision_timeout),
        )

    async def _handshake_watchdog(self, runtime, connection):
        try:
            await asyncio.sleep(
                float(os.environ.get("CARTHING_SESSION_HANDSHAKE_TIMEOUT_S", "6.0"))
            )
            if (
                runtime.connector.connection is not connection
                or runtime.connector.channel is not None
            ):
                return
            logger.warning(
                "session handshake timeout: peer=%s; dropping orphan LE ACL",
                runtime.address,
            )
            record_connection_event(
                "session_handshake_timeout",
                peer=runtime.address,
            )
            await self._gate(
                "session-handshake-timeout-disconnect",
                connection.disconnect,
            )
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("session handshake timeout disconnect failed: %s", exc)
            if runtime.connector.connection is connection:
                self._on_disconnect(runtime.address)
        finally:
            if runtime.connector.handshake_task is asyncio.current_task():
                runtime.connector.handshake_task = None

    async def _tune_connection(self, connection):
        # BCM20703 does not support LE 2M. CoreBluetooth is the central and
        # owns the LE parameters. A 60 ms Opus cadence reduces radio-event
        # pressure without forcing another Link Layer procedure.
        await asyncio.sleep(0.75)
        try:
            await self._gate(
                "session-set-data-length",
                lambda: connection.set_data_length(251, 2120),
            )
            logger.info("session LE data length requested: 251 octets")
        except Exception as exc:
            logger.info("session LE data length unchanged: %s", exc)

    def _on_disconnect(self, address, connection=None):
        runtime = self._runtime(address, create=False)
        if runtime is None:
            return
        if (
            connection is not None
            and runtime.connector.connection is not connection
        ):
            logger.info("stale session disconnect ignored: %s", address)
            record_connection_event(
                "session_stale_disconnect",
                peer=address,
            )
            return
        was_active = bool(
            runtime.connector.connected
            or runtime.connector.connection is not None
            or runtime.connector.channel is not None
        )
        runtime.connector.connection = None
        runtime.connector.channel = None
        watchdog = runtime.connector.handshake_task
        runtime.connector.handshake_task = None
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()
        self._stop_mic(runtime)
        runtime.connector.connected = False
        self._release_remote_media_owner(address)
        self._release_plugin_owner(address)
        record_connection_event(
            "session_disconnected",
            peer=address,
            was_active=was_active,
        )
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
            record_connection_event(
                "session_coc_rejected",
                peer=address or "?",
                reason="client_off",
            )
            asyncio.create_task(channel.disconnect())
            self._sync_model()
            return
        runtime.connector.channel = channel
        runtime.connector.connected = True
        runtime.connector.last_seen = time.time()
        runtime.connector.last_error = ""
        watchdog = runtime.connector.handshake_task
        runtime.connector.handshake_task = None
        if watchdog is not None and not watchdog.done():
            watchdog.cancel()
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
        record_connection_event(
            "session_coc_connected",
            peer=address or "?",
            psm=self.psm,
        )
        self._sync_model()
        self.on_change()
        self._write(channel, T_HELLO, self._status_bytes())
        if self._listening:
            self._start_mic(runtime, channel)

    def _on_channel_close(self, runtime, channel):
        if runtime.connector.channel is not channel:
            return
        runtime.connector.channel = None
        runtime.connector.connected = False
        self._stop_mic(runtime)
        self._release_remote_media_owner(runtime.address)
        self._release_plugin_owner(runtime.address)
        logger.info("session CoC closed: peer=%s", runtime.address)
        record_connection_event(
            "session_coc_closed",
            peer=runtime.address,
        )
        if not any(
            peer.connector.connected
            for peer in self._runtimes.values()
        ):
            self.model.set_server_disconnected()
        self._sync_model()
        self.on_change()
        self._notify_disconnect(runtime.address)
        connection = getattr(channel, "connection", None)
        if connection is not None:
            asyncio.create_task(self._disconnect_if_active(connection, 0.2))

    def send_media_control(self, command):
        payload = f"media_control:{command}".encode("ascii")
        runtime = self._runtime(self._remote_media_owner, create=False)
        if runtime is None:
            return False
        connector = runtime.connector
        channel = connector.channel
        if not connector.connected or channel is None:
            return False
        return self._write(channel, T_COMMAND, payload)

    def send_plugin_action(self, action):
        runtime = self._runtime(self._plugin_owner, create=False)
        if runtime is None or runtime.connector.channel is None:
            return False
        try:
            payload = json.dumps(
                {
                    "schema": 1,
                    "plugin_id": str(action.get("plugin_id") or "")[:128],
                    "card_id": str(action.get("card_id") or "")[:80],
                    "action_id": str(action.get("action_id") or "")[:80],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8")
        except Exception:
            return False
        if len(payload) > 2048:
            return False
        return self._write(
            runtime.connector.channel,
            T_COMMAND,
            b"plugin_action:" + payload,
        )

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
            elif payload.startswith(b"now_playing:"):
                self._apply_remote_now_playing(runtime, payload[12:])
            elif payload.startswith(b"server_status:"):
                self._apply_server_status(payload[14:])
            elif payload.startswith(b"plugin_catalog:"):
                self._apply_plugin_catalog(runtime, payload[15:])
            elif payload.startswith(b"plugin_snapshot:"):
                self._apply_plugin_snapshot(runtime, payload[16:])
            else:
                self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
        elif frame_type == T_LATENCY_PROBE:
            payload_len = struct.unpack(">I", data[12:16])[0]
            payload = data[16:16 + payload_len]
            if len(payload) >= 8:
                device_receive_ns = time.monotonic_ns()
                mac_send_ns = struct.unpack(">Q", payload[:8])[0]
                device_send_ns = time.monotonic_ns()
                self._write(
                    channel,
                    T_LATENCY_PROBE,
                    struct.pack(">QQQ", mac_send_ns, device_receive_ns, device_send_ns),
                    seq=seq,
                )
        elif frame_type == T_MAINTENANCE:
            payload_len = struct.unpack(">I", data[12:16])[0]
            payload = data[16:16 + payload_len]
            try:
                response, restart = self._maintenance.handle(payload)
                self._write(
                    channel,
                    T_MAINTENANCE,
                    response,
                    seq=seq,
                )
                if restart:
                    asyncio.get_running_loop().call_later(
                        0.75,
                        os.kill,
                        os.getpid(),
                        signal.SIGTERM,
                    )
            except MaintenanceError as exc:
                logger.warning("maintenance request rejected: %s", exc)
                self._write(
                    channel,
                    T_ERROR,
                    b"maintenance_rejected",
                    seq=seq,
                )
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

    async def disconnect_all(self):
        channels = [
            runtime.connector.channel
            for runtime in self._runtimes.values()
            if runtime.connector.channel is not None
        ]
        for channel in channels:
            await self._disconnect_peer(channel)

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
    def _write(channel, frame_type: int, payload: bytes, seq: int = 0, flags: int = 0):
        try:
            channel.write(_ctsp_frame(frame_type, payload, seq=seq, flags=flags))
            return True
        except Exception as exc:
            logger.warning("session CoC write failed: %s", exc)
            return False

    def _on_client_toggle_write(self, _connection, value):
        enabled = bool(bytes(value or b"\x00")[0])
        logger.info("session client_toggle via GATT -> %s", enabled)
        self.on_client_toggle(enabled)

    def _start_mic(self, runtime, channel):
        if not self._listening:
            return
        task = getattr(runtime.connector, "mic_task", None)
        if task is not None and not task.done():
            return
        if AlsaPcmCapture is None or CarThingVoiceDsp is None:
            runtime.connector.last_error = "mic_capture_unavailable"
            self._write(channel, T_ERROR, b"mic_capture_unavailable")
            self._sync_model()
            return
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
            s = s.strip()[:4000]
            if role == "S":
                self.state.assistant_status = s     # живой статус (Слушаю…/Думаю…)
                self._sync_model()
                self.on_change()
                return
            if role == "P":
                self.state.set_assistant_live_target(s)
                self._sync_model()
                self.on_change()
                return
            if role == "D":
                prefix_raw, separator, suffix = s.partition("|")
                if separator and prefix_raw.isdigit():
                    current = self.state.assistant_live_target
                    prefix = min(int(prefix_raw), len(current))
                    self.state.set_assistant_live_target(
                        current[:prefix] + suffix
                    )
                    self._sync_model()
                    self.on_change()
                return
            if not s:
                return
            label = "Вы" if role == "U" else ("Ассистент" if role == "A" else "")
            line = f"{label}: {s}" if label else s
            self.state.assistant_text = line
            if role == "U":
                self.state.clear_assistant_live()
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

    def _apply_server_status(self, raw):
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
            self.model.update_server_status(payload)
            self.on_change()
        except Exception as exc:
            logger.warning("server status payload rejected: %s", exc)

    def _apply_plugin_catalog(self, runtime, raw):
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
            self._plugin_owner = runtime.address
            self.model.update_plugin_catalog(payload)
            self.on_change()
        except Exception as exc:
            logger.warning("plugin catalog payload rejected: %s", exc)

    def _apply_plugin_snapshot(self, runtime, raw):
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
            self._plugin_owner = runtime.address
            self.model.update_plugin_snapshot(payload)
            self.on_change()
        except Exception as exc:
            logger.warning("plugin snapshot payload rejected: %s", exc)

    def _release_plugin_owner(self, address):
        if normalize_address(address) != self._plugin_owner:
            return False
        self._plugin_owner = ""
        self.model.clear_plugins()
        return True

    def _release_remote_media_owner(self, address):
        if normalize_address(address) != self._remote_media_owner:
            return False
        self._remote_media_owner = ""
        changed = self.model.clear_remote_media()
        if changed:
            self.on_remote_media_clear()
        return changed

    def _apply_remote_now_playing(self, runtime, raw):
        try:
            payload = json.loads(bytes(raw).decode("utf-8"))
            active = bool(payload.get("active"))
            if (
                not active
                and self._remote_media_owner
                and self._remote_media_owner != runtime.address
            ):
                return
            changed = self.model.apply_remote_media(payload)
            if changed:
                if active:
                    self._remote_media_owner = runtime.address
                else:
                    self._remote_media_owner = ""
                    self.on_remote_media_clear()
                logger.info(
                    "Mac Now Playing: %s — %s playing=%s route=%s source=%s",
                    str(payload.get("title") or "")[:80],
                    str(payload.get("artist") or "")[:60],
                    bool(payload.get("playing")),
                    str(payload.get("route") or "")[:80],
                    str(payload.get("source") or "")[:40],
                )
                self.on_change()
        except Exception as exc:
            logger.warning("Mac Now Playing payload rejected: %s", exc)

    async def _mic_loop(self, runtime, channel):
        device = os.environ.get("CARTHING_BT_MIC_PCM_DEV", "/dev/snd/pcmC0D1c")
        source_rate = int(os.environ.get("CARTHING_BT_MIC_SOURCE_RATE", "48000"))
        source_channels = int(os.environ.get("CARTHING_BT_MIC_SOURCE_CHANNELS", "4"))
        codec = os.environ.get("CARTHING_BT_MIC_CODEC", "opus").strip().lower()
        if codec not in ("opus", "ima_adpcm"):
            raise ValueError("CARTHING_BT_MIC_CODEC must be opus or ima_adpcm")
        target_rate = int(
            os.environ.get(
                "CARTHING_BT_MIC_TARGET_RATE",
                "16000" if codec == "opus" else "8000",
            )
        )
        if target_rate not in (8000, 16000):
            raise ValueError("CARTHING_BT_MIC_TARGET_RATE must be 8000 or 16000")
        frame_ms = int(os.environ.get("CARTHING_BT_MIC_FRAME_MS", "60"))
        if frame_ms not in (10, 20, 40, 60):
            raise ValueError("CARTHING_BT_MIC_FRAME_MS must be 10, 20, 40, or 60")
        default_read_frames = source_rate * frame_ms // 1000
        read_frames = int(
            os.environ.get(
                "CARTHING_BT_MIC_READ_FRAMES",
                str(default_read_frames),
            )
        )
        bitrate = int(os.environ.get("CARTHING_BT_MIC_OPUS_BITRATE", "20000"))
        gain = float(os.environ.get("CARTHING_BT_MIC_GAIN", "2.0"))
        noise_suppress_db = int(
            os.environ.get("CARTHING_BT_MIC_NOISE_SUPPRESS_DB", "-15")
        )
        cap = None
        preprocessor = None
        pending_audio = bytearray()
        process_bytes = read_frames * source_channels * 2
        audio_blocks = 0
        try:
            # Труба к Mac держится постоянно, а ALSA-захват управляется сохранённым
            # переключателем микрофона без разрыва Bluetooth-сессии.
            while getattr(runtime.connector, "channel", None) is channel:
                if not self._listening:
                    if cap is not None:
                        try:
                            cap.close()
                        except Exception:
                            pass
                        cap = None
                        if preprocessor is not None:
                            try:
                                preprocessor.close()
                            except Exception:
                                pass
                            preprocessor = None
                        pending_audio.clear()
                        logger.info("session remote mic paused (view off): peer=%s", runtime.address)
                    await asyncio.sleep(0.05)
                    continue
                if cap is None:
                    self._set_device_mic_gain()
                    cap = AlsaPcmCapture(device, source_rate, source_channels)
                    info = cap.open()
                    if CarThingVoiceDsp is not None:
                        try:
                            preprocessor = await asyncio.to_thread(
                                CarThingVoiceDsp,
                                noise_suppress_db,
                                target_rate,
                                codec,
                                bitrate,
                            )
                        except Exception:
                            if codec != "opus":
                                raise
                            logger.exception(
                                "Opus init failed; falling back to 8 kHz IMA-ADPCM"
                            )
                            codec = "ima_adpcm"
                            target_rate = 8000
                            frame_ms = 40
                            read_frames = source_rate * frame_ms // 1000
                            process_bytes = read_frames * source_channels * 2
                            preprocessor = await asyncio.to_thread(
                                CarThingVoiceDsp,
                                noise_suppress_db,
                                target_rate,
                                codec,
                                bitrate,
                            )
                    logger.info(
                        "session remote mic capture open: peer=%s device=%s rate=%s channels=%s target_rate=%s frame_ms=%s codec=%s bitrate=%s gain=%.2f denoise=%s info=%s",
                        runtime.address,
                        device,
                        source_rate,
                        source_channels,
                        target_rate,
                        frame_ms,
                        codec,
                        bitrate if codec == "opus" else 0,
                        gain,
                        preprocessor.backend,
                        info,
                    )
                raw = await asyncio.to_thread(cap.read, read_frames)
                capture_end_ns = time.monotonic_ns()
                if not raw:
                    await asyncio.sleep(0.01)
                    continue
                pending_audio.extend(raw)
                while len(pending_audio) >= process_bytes:
                    block = bytes(pending_audio[:process_bytes])
                    del pending_audio[:process_bytes]
                    if preprocessor is not None:
                        dsp_started_ns = time.monotonic_ns()
                        payload = await asyncio.to_thread(
                            preprocessor.process,
                            block,
                            source_channels,
                            gain,
                        )
                        dsp_us = (time.monotonic_ns() - dsp_started_ns) // 1000
                    else:
                        payload = b""
                        dsp_us = 0
                    if payload:
                        audio_blocks += 1
                        if audio_blocks % max(1, 5000 // frame_ms) == 0:
                            stats = dict(
                                getattr(preprocessor, "last_stats", {}) or {}
                            )
                            logger.info(
                                "mic levels: channel_rms=%s channel_peak=%s mono_pre_rms=%s mono_post_rms=%s mono_peak=%s clipped=%s",
                                stats.get("channel_rms"),
                                stats.get("channel_peak"),
                                stats.get("mono_pre_rms"),
                                stats.get("mono_post_rms"),
                                stats.get("mono_peak"),
                                stats.get("clipped_samples"),
                            )
                        send_ns = time.monotonic_ns()
                        runtime.connector.audio_seq = (
                            runtime.connector.audio_seq + 1
                        ) & 0xFFFFFFFF
                        timed_payload = AUDIO_TIMING_HEADER.pack(
                            capture_end_ns,
                            send_ns,
                            min(dsp_us, 0xFFFFFFFF),
                        ) + payload
                        self._write(
                            channel,
                            (
                                T_AUDIO_OPUS
                                if codec == "opus"
                                else T_AUDIO_IMA_ADPCM
                            ),
                            timed_payload,
                            seq=runtime.connector.audio_seq,
                            flags=(
                                AUDIO_TIMING_FLAG
                                | (
                                    AUDIO_RATE_16K_FLAG
                                    if target_rate == 16000
                                    else 0
                                )
                            ),
                        )
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
            if preprocessor is not None:
                try:
                    preprocessor.close()
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

    def _capabilities_bytes(self) -> bytes:
        return json.dumps({
            "roles": ["session_peer", "remote_mic_receiver"],
            "protocol_version": CTSP_VERSION,
            "transports": ["ble_gatt_bootstrap", "ble_l2cap_coc_session"],
            "maintenance": {
                "available": self._maintenance.available,
                "transport": "ctsp_l2cap",
                "authentication": "hmac_sha256",
                "session": self._maintenance.session_id,
            },
            "remote_mic": {
                "format": os.environ.get("CARTHING_BT_MIC_CODEC", "opus"),
                "sample_rate_hz": int(
                    os.environ.get(
                        "CARTHING_BT_MIC_TARGET_RATE",
                        "16000",
                    )
                ),
                "channels": 1,
                "mode": "on_demand",
                "frame_ms": int(
                    os.environ.get("CARTHING_BT_MIC_FRAME_MS", "60")
                ),
                "audio_timing": "capture_end_ns,send_ns,dsp_us",
                "latency_probe": True,
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
