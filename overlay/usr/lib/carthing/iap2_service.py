"""iAP2/MFi service for the unified runtime.

This is deliberately a Bumble-native service: SDP + RFCOMM live inside the same
controller/runtime that already owns BLE, A2DP and AVRCP. Legacy системный BT-стек/D-Bus
agents in reference/ are protocol maps only, not runtime architecture.
"""

from __future__ import annotations

import asyncio
import ctypes
import fcntl
import hashlib
import logging
import os
import shlex
import struct
import subprocess
import textwrap

from bumble.core import BT_L2CAP_PROTOCOL_ID, BT_RFCOMM_PROTOCOL_ID, UUID
from bumble.rfcomm import Server as RFCOMMServer
from bumble.sdp import (
    DataElement,
    SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID,
    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_PUBLIC_BROWSE_ROOT,
    SDP_SERVICE_AVAILABILITY_ATTRIBUTE_ID,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
    SDP_SERVICE_RECORD_STATE_ATTRIBUTE_ID,
    ServiceAttribute,
)

import identity_service

logger = logging.getLogger(__name__)

IAP2_UUID = UUID("00000000-deca-fade-deca-deafdecacaff", "iAP2 Accessory")
IAP2_RFCOMM_CHANNEL = 3
SERVICE_RECORD_IAP2 = 0x10020

IAP2_CTL_SYN = 0x80
IAP2_CTL_ACK = 0x40
IAP2_CTL_EAK = 0x20
IAP2_SID_CONTROL = 0x00
IAP2_CSM_START = 0x4040

IAP2_MSG_AUTH_CERT_REQ = 0xAA00
IAP2_MSG_AUTH_CERT_RESP = 0xAA01
IAP2_MSG_AUTH_CHAL_REQ = 0xAA02
IAP2_MSG_AUTH_CHAL_RESP = 0xAA03
IAP2_MSG_AUTH_FAILED = 0xAA04
IAP2_MSG_AUTH_OK = 0xAA05
IAP2_MSG_ID_START = 0x1D00
IAP2_MSG_ID_INFO = 0x1D01
IAP2_MSG_ID_ACCEPTED = 0x1D02
IAP2_MSG_ID_REJECTED = 0x1D03
IAP2_MSG_START_NOWPLAYING = 0x40C8
IAP2_MSG_NOWPLAYING_UPDATE = 0x4800

MFI_DEV = "/dev/apple_mfi"
MFI_MAGIC = 0x77
IOC_READ = 2
IOC_WRITE = 1


def _checksum(data: bytes) -> int:
    return ((~sum(data)) + 1) & 0xFF


def _param(param_id: int, data: bytes | str | None = b"") -> bytes:
    if data is None:
        payload = b""
    elif isinstance(data, str):
        payload = data.encode("utf-8")
    else:
        payload = bytes(data)
    return struct.pack(">HH", len(payload) + 4, param_id) + payload


def _ioc(direction: int, nr: int) -> int:
    return (direction << 30) | (16 << 16) | (MFI_MAGIC << 8) | nr


class MFiAuth:
    def __init__(self, device_path: str = MFI_DEV, remote_ssh: str | None = None):
        self.device_path = device_path
        self.remote_ssh = remote_ssh or os.environ.get("CARTHING_MFI_REMOTE_SSH", "")
        self._cert: bytes | None = None

    def available(self) -> bool:
        return os.path.exists(self.device_path) or bool(self.remote_ssh)

    def _ioctl_buf(self, fd: int, direction: int, nr: int, payload: bytes) -> bytes:
        buf = ctypes.create_string_buffer(bytes(payload), len(payload))
        hdr = bytearray(struct.pack("<IIQ", len(payload), 0, ctypes.addressof(buf)))
        fcntl.ioctl(fd, _ioc(direction, nr), hdr, True)
        return bytes(buf.raw)

    def _read_ioc(self, fd: int, nr: int, size: int) -> bytes:
        return self._ioctl_buf(fd, IOC_READ, nr, b"\x00" * size)

    def _write_ioc(self, fd: int, nr: int, payload: bytes) -> None:
        self._ioctl_buf(fd, IOC_WRITE, nr, payload)

    def _local_certificate(self) -> bytes:
        fd = os.open(self.device_path, os.O_RDWR)
        try:
            version = self._read_ioc(fd, 1, 1)[0]
            cert_len_b = self._read_ioc(fd, 4, 2)
            cert_len = (cert_len_b[0] << 8) | cert_len_b[1]
            cert = self._read_ioc(fd, 5, cert_len)
            logger.info(
                "MFi local cert ready: version=0x%02x len=%d sha256=%s",
                version,
                cert_len,
                hashlib.sha256(cert).hexdigest(),
            )
            return cert
        finally:
            os.close(fd)

    def _local_sign(self, challenge: bytes) -> bytes:
        fd = os.open(self.device_path, os.O_RDWR)
        try:
            padded = bytes(challenge[:32]).ljust(32, b"\x00")
            self._write_ioc(fd, 6, padded)
            return self._read_ioc(fd, 7, 64)
        finally:
            os.close(fd)

    def _remote(self, action: str, data: bytes = b"") -> bytes:
        if not self.remote_ssh:
            raise RuntimeError("MFi remote SSH is not configured")
        script = textwrap.dedent(
            r"""
            import ctypes, fcntl, os, struct, sys
            DEV='/dev/apple_mfi'
            def ioc(direction, nr): return (direction << 30) | (16 << 16) | (0x77 << 8) | nr
            def call(fd, direction, nr, payload):
                buf = ctypes.create_string_buffer(bytes(payload), len(payload))
                hdr = bytearray(struct.pack('<IIQ', len(payload), 0, ctypes.addressof(buf)))
                fcntl.ioctl(fd, ioc(direction, nr), hdr, True)
                return bytes(buf.raw)
            fd=os.open(DEV, os.O_RDWR)
            try:
                action=sys.argv[1]
                if action == 'cert':
                    call(fd, 2, 1, b'\0')
                    clen=call(fd, 2, 4, b'\0\0')
                    n=(clen[0] << 8) | clen[1]
                    print(call(fd, 2, 5, b'\0' * n).hex())
                elif action == 'sign':
                    challenge=bytes.fromhex(sys.argv[2])[:32].ljust(32, b'\0')
                    call(fd, 1, 6, challenge)
                    print(call(fd, 2, 7, b'\0' * 64).hex())
                else:
                    raise SystemExit(2)
            finally:
                os.close(fd)
            """
        )
        remote_cmd = f"python3 -c {shlex.quote(script)} {shlex.quote(action)}"
        if data:
            remote_cmd += f" {shlex.quote(data.hex())}"
        cmd = [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            self.remote_ssh,
            remote_cmd,
        ]
        out = subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL).strip()
        return bytes.fromhex(out.splitlines()[-1])

    def certificate(self) -> bytes:
        if self._cert is not None:
            return self._cert
        if os.path.exists(self.device_path):
            self._cert = self._local_certificate()
        else:
            self._cert = self._remote("cert")
            logger.info("MFi remote cert ready: len=%d sha256=%s", len(self._cert), hashlib.sha256(self._cert).hexdigest())
        return self._cert

    def sign(self, challenge: bytes) -> bytes:
        if os.path.exists(self.device_path):
            return self._local_sign(challenge)
        return self._remote("sign", challenge)


class IAP2Session:
    def __init__(self, dlc, mfi: MFiAuth, on_now_playing=None):
        self.dlc = dlc
        self.mfi = mfi
        self.on_now_playing = on_now_playing or (lambda update: None)
        self.buffer = bytearray()
        self.tx_seq = 1
        self.last_rx_seq = 0
        self.control_sid = IAP2_SID_CONTROL
        self.last_control_key = None

    def start(self):
        self.dlc.sink = self.on_data
        logger.info("iAP2 RFCOMM DLC open: %s", self.dlc)

    def _write_packet(self, ctl: int, sid: int, seq: int, ack: int, payload: bytes = b""):
        total = 9 + len(payload) + (1 if payload else 0)
        hdr = bytearray([0xFF, 0x5A, (total >> 8) & 0xFF, total & 0xFF, ctl, seq & 0xFF, ack & 0xFF, sid & 0xFF])
        hdr.append(_checksum(hdr[:8]))
        packet = bytes(hdr)
        if payload:
            packet += payload + bytes([_checksum(payload)])
        self.dlc.write(packet)
        logger.info("iAP2 tx packet ctl=0x%02x sid=%d seq=%d ack=%d payload=%d", ctl, sid, seq, ack, len(payload))

    def _ack(self, seq: int):
        self._write_packet(IAP2_CTL_ACK, IAP2_SID_CONTROL, self.tx_seq, seq)

    def _send_control(self, msg_id: int, params: bytes = b""):
        payload = struct.pack(">HHH", IAP2_CSM_START, len(params) + 6, msg_id) + params
        self.tx_seq = (self.tx_seq + 1) & 0xFF
        if self.tx_seq == 0:
            self.tx_seq = 1
        self._write_packet(IAP2_CTL_ACK, self.control_sid, self.tx_seq, self.last_rx_seq, payload)
        logger.info("iAP2 tx msg=0x%04x params=%d sid=%d", msg_id, len(params), self.control_sid)

    def _send_raw(self, msg_id: int, params: bytes = b""):
        total = len(params) + 6
        packet = struct.pack(">BBHH", 0xFF, 0x5A, total, msg_id) + params
        self.dlc.write(packet)
        logger.info("iAP2 raw tx msg=0x%04x params=%d", msg_id, len(params))

    def on_data(self, data: bytes):
        self.buffer.extend(data)
        while True:
            if len(self.buffer) < 4:
                return
            if self.buffer[0] != 0xFF or self.buffer[1] != 0x5A:
                del self.buffer[0]
                continue
            packet_len = (self.buffer[2] << 8) | self.buffer[3]
            if packet_len < 6 or packet_len > 4096:
                logger.warning("iAP2 bad packet len=%d head=%s", packet_len, bytes(self.buffer[:12]).hex())
                self.buffer.clear()
                return
            if len(self.buffer) < packet_len:
                return
            packet = bytes(self.buffer[:packet_len])
            del self.buffer[:packet_len]
            try:
                if packet_len >= 9 and packet[4] in (IAP2_CTL_SYN, IAP2_CTL_ACK, IAP2_CTL_EAK, IAP2_CTL_SYN | IAP2_CTL_ACK, 0):
                    self._handle_link_packet(packet)
                else:
                    self._handle_raw_packet(packet)
            except Exception as exc:
                logger.warning("iAP2 packet handling failed: %s", exc)

    def _handle_raw_packet(self, packet: bytes):
        msg_id = (packet[4] << 8) | packet[5]
        params = packet[6:]
        logger.info("iAP2 raw rx msg=0x%04x params=%d", msg_id, len(params))
        self._handle_message(msg_id, params, raw=True)

    def _handle_link_packet(self, packet: bytes):
        ctl, seq, ack, sid = packet[4], packet[5], packet[6], packet[7]
        payload = packet[9:-1] if len(packet) > 9 else b""
        self.last_rx_seq = seq
        logger.info("iAP2 rx packet ctl=0x%02x seq=%d ack=%d sid=%d payload=%d", ctl, seq, ack, sid, len(payload))
        if ctl & IAP2_CTL_SYN:
            if len(payload) >= 13:
                # Link sync params: NumSessions at byte 10, first SID at byte 11.
                self.control_sid = payload[11]
                logger.info("iAP2 negotiated control sid=%d", self.control_sid)
            self._ack(seq)
            return
        if ctl & IAP2_CTL_EAK:
            self._ack(seq)
            return
        if payload and sid == self.control_sid:
            self._ack(seq)
            if len(payload) < 6 or payload[:2] != struct.pack(">H", IAP2_CSM_START):
                logger.info("iAP2 non-CSM control payload: %s", payload[:32].hex())
                return
            msg_len = (payload[2] << 8) | payload[3]
            msg_id = (payload[4] << 8) | payload[5]
            params = payload[6:msg_len]
            key = (seq, msg_id)
            if key == self.last_control_key:
                logger.info("iAP2 duplicate msg ignored: seq=%d msg=0x%04x", seq, msg_id)
                return
            self.last_control_key = key
            logger.info("iAP2 rx msg=0x%04x params=%d", msg_id, len(params))
            self._handle_message(msg_id, params, raw=False)

    def _first_param(self, params: bytes) -> bytes:
        if len(params) < 4:
            return b""
        plen = (params[0] << 8) | params[1]
        if plen < 4 or plen > len(params):
            return b""
        return params[4:plen]

    def _reply(self, raw: bool, msg_id: int, params: bytes = b""):
        if raw:
            self._send_raw(msg_id, params)
        else:
            self._send_control(msg_id, params)

    def _handle_message(self, msg_id: int, params: bytes, raw: bool):
        if msg_id == IAP2_MSG_AUTH_CERT_REQ:
            cert = self.mfi.certificate()
            self._reply(raw, IAP2_MSG_AUTH_CERT_RESP, _param(0x0000, cert))
        elif msg_id == IAP2_MSG_AUTH_CHAL_REQ:
            challenge = self._first_param(params)
            if not challenge:
                self._reply(raw, IAP2_MSG_AUTH_FAILED)
                return
            signature = self.mfi.sign(challenge)
            logger.info("iAP2 MFi challenge signed: challenge=%d sig=%d", len(challenge), len(signature))
            self._reply(raw, IAP2_MSG_AUTH_CHAL_RESP, _param(0x0000, signature))
        elif msg_id == IAP2_MSG_AUTH_OK:
            logger.info("iAP2 authentication succeeded; waiting for StartIdentification")
        elif msg_id == IAP2_MSG_ID_START:
            self._reply(raw, IAP2_MSG_ID_INFO, self._identification_params())
        elif msg_id == IAP2_MSG_ID_ACCEPTED:
            logger.info("iAP2 identification accepted; starting NowPlaying updates")
            self._reply(raw, IAP2_MSG_START_NOWPLAYING, self._nowplaying_fields())
        elif msg_id == IAP2_MSG_ID_REJECTED:
            logger.warning("iAP2 identification rejected: %s", params.hex())
        elif msg_id == IAP2_MSG_AUTH_FAILED:
            logger.warning("iAP2 authentication failed by phone")
        elif msg_id == IAP2_MSG_NOWPLAYING_UPDATE:
            logger.info("iAP2 nowplaying update: %s", params[:96].hex())
        else:
            logger.info("iAP2 unhandled msg=0x%04x params=%s", msg_id, params[:96].hex())

    def _identification_params(self) -> bytes:
        name = identity_service.visible_name()
        serial = identity_service.manufacturing_serial() or "QN19"
        local_addr = os.environ.get("CAR_THING_BD_ADDRESS", "30:E3:D6:00:5F:A4")
        mac = bytes(int(part, 16) for part in local_addr.split(":")[:6])
        bt_transport = (
            _param(0x0000, b"\x00\x01")
            + _param(0x0001, "Bluetooth\x00")
            + _param(0x0002, b"")
            + _param(0x0003, mac)
        )
        return b"".join(
            [
                _param(0x0000, name + "\x00"),
                _param(0x0001, "CarThingCustom\x00"),
                _param(0x0002, "Spotify USA Inc.\x00"),
                _param(0x0003, serial + "\x00"),
                _param(0x0004, "0.48.2\x00"),
                _param(0x0005, "1.0.0\x00"),
                _param(0x0006, b"\x40\xC8\x40\xC9"),
                _param(0x0007, b"\x48\x00"),
                _param(0x0008, b"\x00"),
                _param(0x0009, b"\x00\x64"),
                _param(0x0011, bt_transport),
                _param(0x000C, "en\x00"),
                _param(0x000D, "en\x00"),
            ]
        )

    def _nowplaying_fields(self) -> bytes:
        return b"".join(_param(0x0000, struct.pack(">H", field)) for field in (0x0001, 0x0002, 0x0003, 0x0008, 0x000F, 0x0010))


class IAP2Service:
    def __init__(self, device, on_now_playing=None):
        self.device = device
        self.on_now_playing = on_now_playing or (lambda update: None)
        self.mfi = MFiAuth()
        self.server: RFCOMMServer | None = None

    @staticmethod
    def make_sdp_record(handle: int = SERVICE_RECORD_IAP2):
        return [
            ServiceAttribute(SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID, DataElement.unsigned_integer_32(handle)),
            ServiceAttribute(SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID, DataElement.sequence([DataElement.uuid(IAP2_UUID)])),
            ServiceAttribute(SDP_SERVICE_RECORD_STATE_ATTRIBUTE_ID, DataElement.unsigned_integer_32(0)),
            ServiceAttribute(SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID, DataElement.sequence([
                DataElement.sequence([DataElement.uuid(BT_L2CAP_PROTOCOL_ID)]),
                DataElement.sequence([DataElement.uuid(BT_RFCOMM_PROTOCOL_ID), DataElement.unsigned_integer_8(IAP2_RFCOMM_CHANNEL)]),
            ])),
            ServiceAttribute(SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID, DataElement.sequence([DataElement.uuid(SDP_PUBLIC_BROWSE_ROOT)])),
            ServiceAttribute(SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID, DataElement.sequence([
                DataElement.unsigned_integer_16(0x656E),
                DataElement.unsigned_integer_16(0x006A),
                DataElement.unsigned_integer_16(0x0100),
            ])),
            ServiceAttribute(SDP_SERVICE_AVAILABILITY_ATTRIBUTE_ID, DataElement.unsigned_integer_8(0xFF)),
            ServiceAttribute(SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID, DataElement.sequence([
                DataElement.sequence([DataElement.uuid(UUID.from_16_bits(0x1101, "SerialPort")), DataElement.unsigned_integer_16(0x0100)]),
            ])),
            ServiceAttribute(0x0100, DataElement.text_string("Wireless iAP")),
        ]

    def install_sdp_record(self):
        records = dict(self.device.sdp_service_records)
        records[SERVICE_RECORD_IAP2] = self.make_sdp_record(SERVICE_RECORD_IAP2)
        self.device.sdp_service_records = records
        logger.info("iAP2 SDP installed: uuid=%s rfcomm_channel=%d", IAP2_UUID, IAP2_RFCOMM_CHANNEL)

    async def start(self):
        self.install_sdp_record()
        self.server = RFCOMMServer(self.device)
        self.server.acceptors[IAP2_RFCOMM_CHANNEL] = self._accept_dlc
        logger.info("iAP2 RFCOMM server listening on channel %d (mfi_available=%s)", IAP2_RFCOMM_CHANNEL, self.mfi.available())

    def _accept_dlc(self, dlc):
        session = IAP2Session(dlc, self.mfi, self.on_now_playing)
        session.start()
