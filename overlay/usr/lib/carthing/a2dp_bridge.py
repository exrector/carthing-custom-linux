"""A2DP relay for the Car Thing runtime.

The bridge accepts AAC A2DP from a phone and forwards the RTP packets to a
paired A2DP receiver.  It runs on the same Bumble Device as the BLE remote.
"""

import asyncio
import logging

from bumble import a2dp, avdtp
from bumble.core import BT_BR_EDR_TRANSPORT
from bumble.device import AdvertisingData, Device

from trusted_devices import TrustedDevices, normalize_address


DEFAULT_RECEIVER_ADDRESS = "C4:A9:B8:70:2F:E5"
DEFAULT_BT_NAME = "Car Thing Audio"

COD_AUDIO_LOUDSPEAKER = 0x240414
SERVICE_RECORD_AUDIO_SOURCE = 0x10001
SERVICE_RECORD_AUDIO_SINK = 0x10002

BT_AUDIO_SOURCE_UUID16 = 0x110A
BT_AUDIO_SINK_UUID16 = 0x110B


def error_text(error: Exception) -> str:
    text = str(error)
    return text or type(error).__name__


def make_aac_capabilities(max_bitrate: int = 320000):
    return avdtp.MediaCodecCapabilities(
        avdtp.AVDTP_AUDIO_MEDIA_TYPE,
        a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
        a2dp.AacMediaCodecInformation.from_lists(
            [a2dp.MPEG_2_AAC_LC_OBJECT_TYPE],
            [44100],
            [2],
            1,
            max_bitrate,
        ),
    )


def make_aac_stream_configuration():
    return [
        avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
        avdtp.MediaCodecCapabilities(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
            a2dp.AacMediaCodecInformation.from_discrete_values(
                a2dp.MPEG_2_AAC_LC_OBJECT_TYPE,
                44100,
                2,
                1,
                256000,
            ),
        ),
    ]


class A2DPBridge:
    def __init__(
        self,
        device: Device,
        receiver_address: str | None = None,
        bt_name: str = DEFAULT_BT_NAME,
        autoconnect: bool = True,
        reconnect_interval: float = 12.0,
        connect_timeout: float = 20.0,
        trusted_devices: TrustedDevices | None = None,
        on_source_start=None,
        logger: logging.Logger | None = None,
    ):
        self.device = device
        self.trusted_devices = trusted_devices or TrustedDevices()
        self.on_source_start = on_source_start
        self.receiver_address = (
            receiver_address
            or self.trusted_devices.first_speaker_address()
            or DEFAULT_RECEIVER_ADDRESS
        )
        self.bt_name = bt_name
        self.autoconnect = autoconnect
        self.reconnect_interval = reconnect_interval
        self.connect_timeout = connect_timeout
        self.logger = logger or logging.getLogger(__name__)

        self.listener: avdtp.Listener | None = None
        self.receiver_connection = None
        self.receiver_protocol: avdtp.Protocol | None = None
        self.receiver_source = None
        self.receiver_stream = None
        self.receiver_rtp_channel = None
        self.receiver_ready = asyncio.Event()
        self.started = False
        self.packets_forwarded = 0
        self.bytes_forwarded = 0
        self._receiver_task: asyncio.Task | None = None

    def install_sdp_records(self):
        records = dict(self.device.sdp_service_records)
        records[SERVICE_RECORD_AUDIO_SOURCE] = a2dp.make_audio_source_service_sdp_records(
            SERVICE_RECORD_AUDIO_SOURCE
        )
        records[SERVICE_RECORD_AUDIO_SINK] = a2dp.make_audio_sink_service_sdp_records(
            SERVICE_RECORD_AUDIO_SINK
        )
        self.device.sdp_service_records = records
        self.logger.info("A2DP SDP records installed: AudioSource + AudioSink")

    def install_safe_link_key_provider(self):
        async def safe_link_key_provider(address):
            if self.device.keystore is None:
                return None
            keys = await self.device.keystore.get(str(address))
            link_key = getattr(keys, "link_key", None) if keys is not None else None
            return getattr(link_key, "value", None)

        self.device.host.link_key_provider = safe_link_key_provider
        self.logger.info("A2DP safe classic link-key provider installed")

    async def start(self):
        if self.started:
            return
        self.started = True
        await self.enable_classic_visibility()
        self.listener = avdtp.Listener(avdtp.Listener.create_registrar(self.device))
        self.listener.on("connection", self.on_avdtp_connection)
        self.logger.info(
            "A2DP bridge started: local=%s receiver=%s name=%s trusted_sources=%d trusted_speakers=%d",
            self.device.public_address,
            self.receiver_address,
            self.bt_name,
            len(self.trusted_devices.sources),
            len(self.trusted_devices.speakers),
        )
        if self.autoconnect:
            self._receiver_task = asyncio.create_task(self.receiver_loop())

    async def enable_classic_visibility(self):
        self.device.class_of_device = COD_AUDIO_LOUDSPEAKER
        self.device.inquiry_response = bytes(
            AdvertisingData(
                [
                    (
                        AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                        BT_AUDIO_SOURCE_UUID16.to_bytes(2, "little")
                        + BT_AUDIO_SINK_UUID16.to_bytes(2, "little"),
                    ),
                    (AdvertisingData.COMPLETE_LOCAL_NAME, self.bt_name.encode("utf-8")),
                ]
            )
        )
        await self.device.set_connectable(True)
        await self.device.set_discoverable(True)
        self.logger.info("A2DP classic discoverable/connectable enabled")

    async def receiver_loop(self):
        while True:
            try:
                if self.receiver_rtp_channel is None:
                    await self.setup_receiver()
                await asyncio.sleep(self.reconnect_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.receiver_ready.clear()
                self.receiver_rtp_channel = None
                self.logger.warning("A2DP receiver setup failed: %s", error_text(exc))
                await asyncio.sleep(self.reconnect_interval)

    async def setup_receiver(self):
        if self.trusted_devices.has_speakers and not self.trusted_devices.is_speaker(self.receiver_address):
            raise RuntimeError(f"receiver is not trusted as speaker: {self.receiver_address}")
        self.logger.info("A2DP receiver connect: %s", self.receiver_address)
        connection = await asyncio.wait_for(
            self.device.connect(
                self.receiver_address,
                transport=BT_BR_EDR_TRANSPORT,
            ),
            timeout=self.connect_timeout,
        )
        self.receiver_connection = connection
        connection.on(
            "disconnection",
            lambda reason: asyncio.ensure_future(self.on_receiver_disconnected(reason)),
        )
        try:
            await asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout)
            await asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout)
        except Exception as exc:
            self.logger.info("A2DP receiver auth/encrypt continued: %s", exc)

        protocol = await asyncio.wait_for(
            avdtp.Protocol.connect(connection),
            timeout=self.connect_timeout,
        )
        self.receiver_protocol = protocol
        await asyncio.wait_for(
            protocol.discover_remote_endpoints(),
            timeout=self.connect_timeout,
        )
        sink = protocol.find_remote_sink_by_codec(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
        )
        if sink is None:
            raise RuntimeError("receiver has no AAC sink endpoint")

        source = protocol.add_source(make_aac_capabilities(), None)
        source.configuration = make_aac_stream_configuration()
        stream = await protocol.create_stream(source, sink)
        await stream.open()
        await stream.start()

        self.receiver_source = source
        self.receiver_stream = stream
        self.receiver_rtp_channel = stream.rtp_channel
        self.receiver_ready.set()
        self.logger.info("FOSI_STREAM_STARTED seid=%s", getattr(sink, "seid", "?"))

    def speaker_statuses(self, online_addresses=None) -> list[dict]:
        online = {normalize_address(address) for address in (online_addresses or [])}
        statuses = []
        for speaker in self.trusted_devices.speaker_list():
            item = dict(speaker)
            address = normalize_address(item.get("address", ""))
            item["address"] = address
            item["online"] = address in online
            item["connected"] = (
                self.receiver_connection is not None
                and normalize_address(self.receiver_address) == address
                and self.receiver_rtp_channel is not None
            )
            statuses.append(item)
        return statuses

    async def scan_trusted_speakers(self, duration: float = 6.0) -> list[dict]:
        found = set()
        complete = asyncio.get_running_loop().create_future()

        def on_inquiry_result(address, _class_of_device, _data, _rssi):
            if self.trusted_devices.is_speaker(address):
                normalized = normalize_address(address)
                found.add(normalized)
                self.logger.info("A2DP trusted speaker seen: %s", normalized)

        def on_inquiry_complete():
            if not complete.done():
                complete.set_result(None)

        self.device.on("inquiry_result", on_inquiry_result)
        self.device.on("inquiry_complete", on_inquiry_complete)
        try:
            await self.device.start_discovery(auto_restart=False)
            try:
                await asyncio.wait_for(complete, timeout=duration)
            except Exception:
                pass
            return self.speaker_statuses(found)
        finally:
            self.device.remove_listener("inquiry_result", on_inquiry_result)
            self.device.remove_listener("inquiry_complete", on_inquiry_complete)
            try:
                await self.device.stop_discovery()
            except Exception as exc:
                self.logger.info("A2DP speaker scan stop ignored: %s", error_text(exc))

    async def on_receiver_disconnected(self, reason):
        self.logger.warning("A2DP receiver disconnected: reason=0x%02x", reason)
        self.receiver_ready.clear()
        self.receiver_connection = None
        self.receiver_protocol = None
        self.receiver_source = None
        self.receiver_stream = None
        self.receiver_rtp_channel = None

    def on_avdtp_connection(self, protocol: avdtp.Protocol):
        peer_address = protocol.l2cap_channel.connection.peer_address
        if self.trusted_devices.has_sources and not self.trusted_devices.is_source(peer_address):
            self.logger.warning("A2DP source rejected, not trusted: %s", peer_address)
            return

        self.logger.info("A2DP incoming trusted source: %s", peer_address)
        sink = protocol.add_sink(make_aac_capabilities())

        original_set_configuration = sink.on_set_configuration_command
        original_start = sink.on_start_command
        original_open = sink.on_open_command

        def on_set_configuration(configuration):
            self.logger.info("IPHONE_SET_CONFIGURATION %s", configuration)
            return original_set_configuration(configuration)

        def on_open():
            self.logger.info("IPHONE_OPEN")
            return original_open()

        def on_start():
            self.logger.info("IPHONE_START")
            if self.on_source_start is not None:
                self.on_source_start(peer_address)
            return original_start()

        sink.on_set_configuration_command = on_set_configuration
        sink.on_open_command = on_open
        sink.on_start_command = on_start
        sink.on("rtp_packet", self.forward_packet)

    def forward_packet(self, packet):
        payload = bytes(packet)
        sent = False
        if self.receiver_rtp_channel is not None:
            self.receiver_rtp_channel.send_pdu(payload)
            sent = True
            self.packets_forwarded += 1
            self.bytes_forwarded += len(payload)

        if self.packets_forwarded < 10 or self.packets_forwarded % 250 == 0:
            self.logger.info(
                "BRIDGE_RTP n=%d bytes=%d sent_to_receiver=%s",
                self.packets_forwarded,
                len(payload),
                sent,
            )

    async def handle_classic_connection(self, connection):
        self.logger.info(
            "Classic BT connection: %s handle=%d encrypted=%s",
            connection.peer_address,
            connection.handle,
            connection.is_encrypted,
        )
