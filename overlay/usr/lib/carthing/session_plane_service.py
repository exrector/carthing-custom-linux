"""Session-plane adapter for Mac/computer peers.

This is the input/session counterpart of the output-side SpeakerRuntime model:
AppState owns the persistent device card, while this module owns the volatile
CTSP/GATT/L2CAP footprint for each trusted session-capable card.

Client ON/OFF gates only this plane. It must not select an audio input, switch
Play Now/Commutator, or disconnect an already attached media source.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import time
from dataclasses import dataclass

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
T_ROUTE_STATE = 0x04
T_COMMAND = 0x05
T_ERROR = 0x08


@dataclass
class SessionConnector:
    address: str
    connection: object | None = None
    channel: object | None = None
    connected: bool = False
    last_seen: float = 0.0
    last_error: str = ""


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
    def __init__(self, device, app_state, model, on_change=None, on_client_toggle=None):
        self.device = device
        self.state = app_state
        self.model = model
        self.on_change = on_change or (lambda: None)
        self.on_client_toggle = on_client_toggle or (lambda enabled: None)
        self.enabled = False
        self.psm = 0
        self._server = None
        self._runtimes: dict[str, SessionRuntime] = {}
        self._status_char: Characteristic | None = None
        self._psm_char: Characteristic | None = None
        self._installed = False

    def install(self):
        if self._installed:
            return
        self._server = self.device.create_l2cap_server(
            spec=l2cap.LeCreditBasedChannelSpec(psm=0, max_credits=32),
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
        self.enabled = bool(enabled)
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
        address = normalize_address(address)
        return bool(address and any(normalize_address(row.get("address")) == address for row in self._session_rows()))

    def on_connection(self, connection) -> bool:
        address = normalize_address(getattr(connection, "peer_address", ""))
        if not self.is_session_peer(address):
            return False
        runtime = self._runtime(address)
        runtime.connector.connection = connection
        runtime.connector.connected = True
        runtime.connector.last_seen = time.time()
        logger.info("session peer LE attached: %s", address)
        connection.on("disconnection", lambda *_: self._on_disconnect(address))
        self._sync_model()
        self.on_change()
        return True

    def _on_disconnect(self, address):
        runtime = self._runtime(address, create=False)
        if runtime is None:
            return
        runtime.connector.connection = None
        runtime.connector.channel = None
        runtime.connector.connected = False
        self._sync_model()
        self.on_change()

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
        channel.sink = lambda data: self._on_channel_data(runtime, channel, data)
        logger.info("session CoC connected: peer=%s psm=%d", address or "?", self.psm)
        self._sync_model()
        self.on_change()
        self._write(channel, T_HELLO, self._status_bytes())

    def _on_channel_data(self, runtime, channel, data: bytes):
        runtime.connector.last_seen = time.time()
        if not data.startswith(CTSP_MAGIC) or len(data) < 16:
            runtime.connector.last_error = "bad_ctsp_frame"
            self._write(channel, T_ERROR, b"bad_ctsp_frame")
            self._sync_model()
            return
        frame_type = data[5]
        seq = struct.unpack(">I", data[8:12])[0]
        if frame_type == T_HELLO:
            self._write(channel, T_HELLO, self._status_bytes(), seq=seq)
        elif frame_type == T_CAPABILITIES:
            self._write(channel, T_CAPABILITIES, self._capabilities_bytes(), seq=seq)
        elif frame_type == T_STATUS:
            self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
        elif frame_type == T_ROUTE_STATE:
            self._write(channel, T_ROUTE_STATE, self._route_state_bytes(), seq=seq)
        elif frame_type == T_COMMAND:
            payload_len = struct.unpack(">I", data[12:16])[0]
            payload = data[16:16 + payload_len]
            logger.info("session command from %s: %r", runtime.address, payload[:80])
            self._write(channel, T_STATUS, self._status_bytes(), seq=seq)
        else:
            self._write(channel, T_ERROR, b"unsupported_frame_type", seq=seq)

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

    def _capabilities_bytes(self) -> bytes:
        return json.dumps({
            "roles": ["session_peer", "remote_mic_receiver"],
            "protocol_version": CTSP_VERSION,
            "transports": ["ble_gatt_bootstrap", "ble_l2cap_coc_session"],
            "remote_mic": {
                "format": "pcm_s16le",
                "sample_rate_hz": 16000,
                "channels": 1,
                "mode": "on_demand",
            },
        }, separators=(",", ":")).encode("utf-8")

    def _status_bytes(self) -> bytes:
        connected = [
            runtime.address for runtime in self._runtimes.values()
            if runtime.connector.connected or runtime.connector.channel is not None
        ]
        return json.dumps({
            "client_enabled": bool(self.enabled),
            "psm": int(self.psm),
            "connected": connected,
        }, separators=(",", ":")).encode("utf-8")

    def _route_state_bytes(self) -> bytes:
        return json.dumps({
            "mode": getattr(self.model, "operation_mode", ""),
            "input": getattr(self.model, "route_input", ""),
            "output": getattr(self.model, "route_output", ""),
            "client_enabled": bool(self.enabled),
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
        peers = []
        for row in self._session_rows():
            address = normalize_address(row.get("address"))
            runtime = self._runtime(address, create=False)
            connector = runtime.connector if runtime is not None else None
            peers.append({
                "key": row.get("key") or address,
                "address": address,
                "label": row.get("label") or address,
                "enabled": bool(self.enabled),
                "connected": bool(connector and (connector.connected or connector.channel is not None)),
                "status": (
                    "connected" if connector and connector.channel is not None else
                    "idle" if self.enabled else "off"
                ),
                "psm": int(self.psm),
                "last_error": (connector.last_error if connector is not None else ""),
            })
        self.model.session_peers = peers
