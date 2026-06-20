#!/usr/bin/env python3
"""HFP Hands-Free lab runner for proving Car Thing as a macOS Bluetooth mic.

This is intentionally separate from the normal PlayNow runtime. HFP changes the
Classic Bluetooth identity surface (CoD + SDP) and may conflict with the A2DP
speaker identity, so the first usable proof belongs in an explicit lab process:

    CARTHING_HFP_DISCOVERABLE=1 python3 /usr/lib/carthing/hfp_handsfree_lab.py

The runner proves the layers in order:
  1. controller advertises as a headset/hands-free class,
  2. SDP exposes Hands-Free + RFCOMM,
  3. macOS opens RFCOMM and completes HFP SLC,
  4. macOS requests SCO/eSCO and the device accepts it over HCI.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import signal
import struct
import time
from typing import Any

from ble_transport import init_ble
from accessory_orchestrator import AccessoryOrchestrator
from bumble import hci
from bumble.core import (
    BT_GENERIC_AUDIO_SERVICE,
    BT_HEADSET_SERVICE,
    BT_L2CAP_PROTOCOL_ID,
    BT_PNP_INFORMATION_SERVICE,
    BT_RFCOMM_PROTOCOL_ID,
    BT_SERVICE_DISCOVERY_SERVER_SERVICE_CLASS_ID_SERVICE,
)
from bumble.hci import (
    HCI_Enhanced_Accept_Synchronous_Connection_Request_Command,
    HCI_Read_Class_Of_Device_Command,
    HCI_Write_Class_Of_Device_Command,
)
from bumble.hfp import (
    AudioCodec,
    DefaultCodecParameters,
    ESCO_PARAMETERS,
    HfConfiguration,
    HfFeature,
    HfIndicator,
    HfProtocol,
    find_ag_sdp_record,
    make_hf_sdp_records,
)
from bumble.rfcomm import Client as RFCOMMClient
from bumble.rfcomm import Server as RFCOMMServer
from bumble.sdp import (
    SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
    SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID,
    SDP_PUBLIC_BROWSE_ROOT,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
    SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
    DataElement,
    ServiceAttribute,
)

try:
    from remote_mic_sender import AlsaPcmCapture
except Exception:  # pragma: no cover - lab fallback for partial deploys
    AlsaPcmCapture = None  # type: ignore


LOG = logging.getLogger("hfp_handsfree_lab")

# Rendering + Capturing + Audio + Telephony, Audio/Video major, Wearable Headset
COD_AUDIO_HEADSET = int(os.environ.get("CARTHING_HFP_COD", "0x6C0404"), 0)
SERVICE_RECORD_HFP_HF = int(os.environ.get("CARTHING_HFP_RECORD", "0x10030"), 0)
SERVICE_RECORD_DID = int(os.environ.get("CARTHING_HFP_DID_RECORD", "0x10031"), 0)
SERVICE_RECORD_HSP_HS = int(os.environ.get("CARTHING_HSP_RECORD", "0x10032"), 0)
SERVICE_RECORD_SDS = int(os.environ.get("CARTHING_HFP_SDS_RECORD", "0x10005"), 0)
RFCOMM_CHANNEL = int(os.environ.get("CARTHING_HFP_RFCOMM_CHANNEL", "9"))
SDP_VERSION_NUMBER_LIST_ATTRIBUTE_ID = 0x0200
SDP_SERVICE_DATABASE_STATE_ATTRIBUTE_ID = 0x0201
DID_SPECIFICATION_ID_ATTRIBUTE_ID = 0x0200
DID_VENDOR_ID_ATTRIBUTE_ID = 0x0201
DID_PRODUCT_ID_ATTRIBUTE_ID = 0x0202
DID_VERSION_ATTRIBUTE_ID = 0x0203
DID_PRIMARY_RECORD_ATTRIBUTE_ID = 0x0204
DID_VENDOR_ID_SOURCE_ATTRIBUTE_ID = 0x0205
DID_VENDOR_ID = int(os.environ.get("CARTHING_HFP_DID_VENDOR_ID", "0xFFFF"), 0)
DID_PRODUCT_ID = int(os.environ.get("CARTHING_HFP_DID_PRODUCT_ID", "0x0001"), 0)
DID_VERSION = int(os.environ.get("CARTHING_HFP_DID_VERSION", "0x0001"), 0)
DID_VENDOR_ID_SOURCE = int(os.environ.get("CARTHING_HFP_DID_VENDOR_ID_SOURCE", "0x0001"), 0)

MIC_DEVICE = os.environ.get("CARTHING_HFP_MIC_DEVICE", "/dev/snd/pcmC0D1c")
MIC_RATE = int(os.environ.get("CARTHING_HFP_MIC_RATE", "16000"))
MIC_CHANNELS = int(os.environ.get("CARTHING_HFP_MIC_CHANNELS", "1"))


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _sds_records(records: dict[int, list[ServiceAttribute]]) -> list[ServiceAttribute]:
    fingerprint = hashlib.sha1()
    for handle in sorted(records):
        if handle == SERVICE_RECORD_SDS:
            continue
        for attribute in records[handle]:
            fingerprint.update(int(attribute.id).to_bytes(2, "big"))
            fingerprint.update(bytes(attribute.value))
    database_state = int.from_bytes(fingerprint.digest()[:4], "big")
    return [
        ServiceAttribute(
            SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_32(SERVICE_RECORD_SDS),
        ),
        ServiceAttribute(
            SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
            DataElement.sequence(
                [DataElement.uuid(BT_SERVICE_DISCOVERY_SERVER_SERVICE_CLASS_ID_SERVICE)]
            ),
        ),
        ServiceAttribute(
            SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
            DataElement.sequence([DataElement.uuid(SDP_PUBLIC_BROWSE_ROOT)]),
        ),
        ServiceAttribute(
            SDP_VERSION_NUMBER_LIST_ATTRIBUTE_ID,
            DataElement.sequence([DataElement.unsigned_integer_16(0x0100)]),
        ),
        ServiceAttribute(
            SDP_SERVICE_DATABASE_STATE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_32(database_state),
        ),
    ]


def _sdp_zero_handle_records(sds_record: list[ServiceAttribute]) -> list[ServiceAttribute]:
    database_state = ServiceAttribute.find_attribute_in_list(
        sds_record,
        SDP_SERVICE_DATABASE_STATE_ATTRIBUTE_ID,
    )
    if database_state is None:
        database_state = DataElement.unsigned_integer_32(0)
    return [
        ServiceAttribute(
            SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_32(0),
        ),
        ServiceAttribute(
            SDP_SERVICE_DATABASE_STATE_ATTRIBUTE_ID,
            database_state,
        ),
    ]


def _did_records() -> list[ServiceAttribute]:
    return [
        ServiceAttribute(
            SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_32(SERVICE_RECORD_DID),
        ),
        ServiceAttribute(
            SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
            DataElement.sequence([DataElement.uuid(BT_PNP_INFORMATION_SERVICE)]),
        ),
        ServiceAttribute(
            SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
            DataElement.sequence([DataElement.uuid(SDP_PUBLIC_BROWSE_ROOT)]),
        ),
        ServiceAttribute(
            DID_SPECIFICATION_ID_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(0x0103),
        ),
        ServiceAttribute(
            DID_VENDOR_ID_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(DID_VENDOR_ID),
        ),
        ServiceAttribute(
            DID_PRODUCT_ID_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(DID_PRODUCT_ID),
        ),
        ServiceAttribute(
            DID_VERSION_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(DID_VERSION),
        ),
        ServiceAttribute(
            DID_PRIMARY_RECORD_ATTRIBUTE_ID,
            DataElement.boolean(True),
        ),
        ServiceAttribute(
            DID_VENDOR_ID_SOURCE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(DID_VENDOR_ID_SOURCE),
        ),
    ]


def _hsp_headset_records() -> list[ServiceAttribute]:
    return [
        ServiceAttribute(
            SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
            DataElement.unsigned_integer_32(SERVICE_RECORD_HSP_HS),
        ),
        ServiceAttribute(
            SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
            DataElement.sequence(
                [
                    DataElement.uuid(BT_HEADSET_SERVICE),
                    DataElement.uuid(BT_GENERIC_AUDIO_SERVICE),
                ]
            ),
        ),
        ServiceAttribute(
            SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
            DataElement.sequence([DataElement.uuid(SDP_PUBLIC_BROWSE_ROOT)]),
        ),
        ServiceAttribute(
            SDP_PROTOCOL_DESCRIPTOR_LIST_ATTRIBUTE_ID,
            DataElement.sequence(
                [
                    DataElement.sequence([DataElement.uuid(BT_L2CAP_PROTOCOL_ID)]),
                    DataElement.sequence(
                        [
                            DataElement.uuid(BT_RFCOMM_PROTOCOL_ID),
                            DataElement.unsigned_integer_8(RFCOMM_CHANNEL),
                        ]
                    ),
                ]
            ),
        ),
        ServiceAttribute(
            SDP_BLUETOOTH_PROFILE_DESCRIPTOR_LIST_ATTRIBUTE_ID,
            DataElement.sequence(
                [
                    DataElement.sequence(
                        [
                            DataElement.uuid(BT_HEADSET_SERVICE),
                            DataElement.unsigned_integer_16(0x0102),
                        ]
                    )
                ]
            ),
        ),
        ServiceAttribute(
            SDP_LANGUAGE_BASE_ATTRIBUTE_ID_LIST_ATTRIBUTE_ID,
            DataElement.sequence(
                [
                    DataElement.unsigned_integer_16(0x656E),
                    DataElement.unsigned_integer_16(0x006A),
                    DataElement.unsigned_integer_16(0x0100),
                ]
            ),
        ),
        ServiceAttribute(0x0100, DataElement.text_string(b"Car Thing Headset")),
    ]


def _hfp_configuration(wideband: bool) -> HfConfiguration:
    codecs = [AudioCodec.CVSD]
    features = [
        HfFeature.REMOTE_VOLUME_CONTROL,
        HfFeature.VOICE_RECOGNITION_ACTIVATION,
    ]
    if wideband:
        codecs.append(AudioCodec.MSBC)
        features.append(HfFeature.CODEC_NEGOTIATION)
        features.append(HfFeature.ESCO_S4_SETTINGS_SUPPORTED)
    return HfConfiguration(
        supported_hf_features=features,
        supported_hf_indicators=[HfIndicator.BATTERY_LEVEL],
        supported_audio_codecs=codecs,
    )


def _esco_params_for_codec(codec: AudioCodec) -> dict[str, Any]:
    key = (
        DefaultCodecParameters.ESCO_MSBC_T2
        if codec == AudioCodec.MSBC
        else DefaultCodecParameters.ESCO_CVSD_S3
    )
    return ESCO_PARAMETERS[key].asdict()


class ScoAudioPump:
    def __init__(self, device, sco_link, codec: AudioCodec, use_mic: bool):
        self.device = device
        self.sco_link = sco_link
        self.codec = codec
        self.use_mic = use_mic
        self.running = False
        self.received_packets = 0

    def on_rx_packet(self, packet: hci.HCI_SynchronousDataPacket) -> None:
        self.received_packets += 1
        if self.received_packets <= 5 or self.received_packets % 100 == 0:
            LOG.info(
                "SCO RX packet #%d len=%d status=%s",
                self.received_packets,
                len(packet.data),
                packet.packet_status,
            )

    async def run(self) -> None:
        self.running = True
        self.sco_link.sink = self.on_rx_packet
        packet_bytes = 60 if self.codec == AudioCodec.MSBC else 48
        interval = 0.0075
        LOG.info(
            "SCO TX pump starting handle=0x%04x codec=%s mode=%s packet_bytes=%d",
            self.sco_link.handle,
            self.codec.name,
            "mic" if self.use_mic else "silence",
            packet_bytes,
        )
        cap = None
        try:
            if self.use_mic and AlsaPcmCapture is not None:
                cap = AlsaPcmCapture(MIC_DEVICE, MIC_RATE, MIC_CHANNELS)
                info = cap.open()
                LOG.info("ALSA mic opened device=%s rate=%s channels=%s info=%s", MIC_DEVICE, MIC_RATE, MIC_CHANNELS, info)
            while self.running:
                if cap is None:
                    payload = bytes(packet_bytes)
                    await asyncio.sleep(interval)
                else:
                    raw = cap.read(max(1, packet_bytes // max(2, MIC_CHANNELS * 2)))
                    payload = raw[:packet_bytes].ljust(packet_bytes, b"\x00")
                self.device.host.send_sco_sdu(self.sco_link.handle, payload)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("SCO TX pump stopped by error: %s", exc)
        finally:
            self.running = False
            if cap is not None:
                cap.close()
            LOG.info("SCO TX pump stopped rx_packets=%d", self.received_packets)


class HfpHandsFreeLab:
    def __init__(self, args):
        self.args = args
        self.device = None
        self.orchestrator = None
        self.rfcomm_server = None
        self.active_codec = AudioCodec.CVSD
        self.sco_tasks: set[asyncio.Task] = set()
        self.outgoing_tasks: set[asyncio.Task] = set()

    def configure_device(self, device) -> None:
        self.orchestrator = AccessoryOrchestrator(
            device,
            on_phase_change=lambda phase: LOG.info("orchestrator phase=%s", phase),
        )
        self.orchestrator.install()
        device.class_of_device = COD_AUDIO_HEADSET
        device.connectable = True
        device.discoverable = bool(self.args.discoverable)

    async def install_hfp_surface(self) -> None:
        assert self.device is not None
        await self.device.host.send_command(
            HCI_Write_Class_Of_Device_Command(class_of_device=COD_AUDIO_HEADSET),
            check_result=True,
        )
        response = await self.device.host.send_command(HCI_Read_Class_Of_Device_Command())
        params = getattr(response, "return_parameters", response)
        actual_cod = int(getattr(params, "class_of_device", 0))
        LOG.info("Classic CoD active: 0x%06x", actual_cod)

        config = _hfp_configuration(self.args.wideband)
        records = dict(self.device.sdp_service_records)
        records[SERVICE_RECORD_HFP_HF] = make_hf_sdp_records(
            SERVICE_RECORD_HFP_HF,
            RFCOMM_CHANNEL,
            config,
        )
        records[SERVICE_RECORD_DID] = _did_records()
        records[SERVICE_RECORD_HSP_HS] = _hsp_headset_records()
        sds_record = _sds_records(records)
        records[SERVICE_RECORD_SDS] = sds_record
        records[0] = _sdp_zero_handle_records(sds_record)
        self.device.sdp_service_records = records

        self.rfcomm_server = RFCOMMServer(self.device)
        channel = self.rfcomm_server.listen(self.accept_rfcomm, channel=RFCOMM_CHANNEL)
        if channel != RFCOMM_CHANNEL:
            raise RuntimeError(f"RFCOMM channel {RFCOMM_CHANNEL} unavailable")
        await self.device.set_connectable(True)
        await self.device.set_discoverable(bool(self.args.discoverable))
        LOG.info(
            "HFP HF SDP/RFCOMM ready: channel=%d wideband=%s discoverable=%s",
            RFCOMM_CHANNEL,
            self.args.wideband,
            self.args.discoverable,
        )
        LOG.info(
            "HFP DID SDP ready: vendor=0x%04x product=0x%04x version=0x%04x source=0x%04x",
            DID_VENDOR_ID,
            DID_PRODUCT_ID,
            DID_VERSION,
            DID_VENDOR_ID_SOURCE,
        )
        LOG.info("HSP Headset SDP ready: channel=%d", RFCOMM_CHANNEL)

    def accept_rfcomm(self, dlc) -> None:
        peer = getattr(getattr(dlc, "multiplexer", None), "connection", None)
        LOG.info("HFP RFCOMM DLC open peer=%s", getattr(peer, "peer_address", peer))
        asyncio.create_task(self.run_hfp_protocol(dlc))

    def on_acl_connection(self, connection) -> None:
        LOG.info("ACL connection: %s", connection)
        if not _bool_env("CARTHING_HFP_OUTGOING_AG", True):
            return
        task = asyncio.create_task(self.connect_to_audio_gateway(connection))
        self.outgoing_tasks.add(task)
        task.add_done_callback(self.outgoing_tasks.discard)

    async def connect_to_audio_gateway(self, connection) -> None:
        await asyncio.sleep(float(os.environ.get("CARTHING_HFP_OUTGOING_DELAY", "0.75")))
        try:
            record = await find_ag_sdp_record(connection)
            if record is None:
                LOG.info("remote AG SDP record not found on %s", connection.peer_address)
                return
            channel, version, features = record
            LOG.info(
                "remote AG SDP found peer=%s channel=%d version=%s features=%s",
                connection.peer_address,
                channel,
                version,
                features,
            )
            client = RFCOMMClient(connection)
            multiplexer = await client.start()
            dlc = await multiplexer.open_dlc(channel)
            LOG.info("outgoing HFP RFCOMM DLC open peer=%s channel=%d", connection.peer_address, channel)
            try:
                await self.run_hfp_protocol(dlc)
            finally:
                await client.shutdown()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.warning("outgoing HFP AG connect failed: %r", exc)

    async def run_hfp_protocol(self, dlc) -> None:
        config = _hfp_configuration(self.args.wideband)
        protocol = HfProtocol(dlc, config)

        def on_codec(codec: AudioCodec) -> None:
            self.active_codec = codec
            LOG.info("HFP codec negotiated: %s", codec.name)

        protocol.on(protocol.EVENT_CODEC_NEGOTIATION, on_codec)
        protocol.on(protocol.EVENT_SPEAKER_VOLUME, lambda volume: LOG.info("HFP speaker volume=%s", volume))
        protocol.on(protocol.EVENT_MICROPHONE_VOLUME, lambda volume: LOG.info("HFP microphone volume=%s", volume))
        protocol.on(protocol.EVENT_VOICE_RECOGNITION, lambda state: LOG.info("HFP voice recognition=%s", state))

        try:
            await protocol.initiate_slc()
            LOG.info("HFP SLC complete; requesting audio connection")
            if self.args.request_audio:
                await protocol.setup_audio_connection()
                LOG.info("HFP AT+BCC accepted by AG")
            while True:
                await protocol.handle_unsolicited()
        except Exception as exc:
            LOG.warning("HFP protocol ended: %r", exc)

    async def accept_sco_request(self, connection, link_type: int) -> None:
        assert self.device is not None
        LOG.info(
            "SCO request from %s link_type=%s active_codec=%s",
            connection.peer_address,
            link_type,
            self.active_codec.name,
        )
        command = HCI_Enhanced_Accept_Synchronous_Connection_Request_Command(
            bd_addr=connection.peer_address,
            **_esco_params_for_codec(self.active_codec),
        )
        await self.device.host.send_command(command, check_result=True)
        LOG.info("SCO accept command sent")

    def on_sco_connection(self, sco_link) -> None:
        LOG.info(
            "SCO connected handle=0x%04x peer=%s link_type=%s",
            sco_link.handle,
            sco_link.acl_connection.peer_address,
            sco_link.link_type,
        )
        pump = ScoAudioPump(self.device, sco_link, self.active_codec, self.args.mic)
        task = asyncio.create_task(pump.run())
        self.sco_tasks.add(task)
        task.add_done_callback(self.sco_tasks.discard)

    def on_sco_failure(self, *args) -> None:
        LOG.warning("SCO connection failed args=%s", args)

    async def run(self) -> None:
        self.device, _transport = await init_ble(configure_device=self.configure_device)
        self.device.on(self.device.EVENT_SCO_REQUEST, lambda connection, link_type: asyncio.create_task(self.accept_sco_request(connection, link_type)))
        self.device.on(self.device.EVENT_SCO_CONNECTION, self.on_sco_connection)
        self.device.on(self.device.EVENT_SCO_CONNECTION_FAILURE, self.on_sco_failure)
        self.device.on(self.device.EVENT_CONNECTION, self.on_acl_connection)
        await self.install_hfp_surface()
        stop = asyncio.Event()
        for sig in (signal.SIGINT, signal.SIGTERM):
            asyncio.get_running_loop().add_signal_handler(sig, stop.set)
        LOG.info("HFP Hands-Free lab running; waiting for macOS")
        await stop.wait()
        LOG.info("HFP Hands-Free lab stopping")
        for task in list(self.sco_tasks):
            task.cancel()
        for task in list(self.outgoing_tasks):
            task.cancel()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discoverable", action="store_true", default=_bool_env("CARTHING_HFP_DISCOVERABLE", True))
    parser.add_argument("--no-wideband", dest="wideband", action="store_false", default=_bool_env("CARTHING_HFP_WIDEBAND", True))
    parser.add_argument("--no-request-audio", dest="request_audio", action="store_false", default=_bool_env("CARTHING_HFP_REQUEST_AUDIO", True))
    parser.add_argument("--mic", action="store_true", default=_bool_env("CARTHING_HFP_MIC", False))
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, os.environ.get("CARTHING_HFP_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    LOG.info("starting HFP Hands-Free lab")
    asyncio.run(HfpHandsFreeLab(args).run())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
