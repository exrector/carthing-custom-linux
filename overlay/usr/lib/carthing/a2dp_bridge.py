"""A2DP transfer service for the Car Thing runtime."""

import asyncio
import logging
import os

from bumble import a2dp, avdtp
from bumble.core import BT_BR_EDR_TRANSPORT
from bumble.device import AdvertisingData, Device

from app_state import normalize_address
from runtime_paths import device_name


DEFAULT_BT_NAME = ""
DEFAULT_LEGACY_LINK_KEYS_PATH = "/run/carthing-state/carthing/iap2-link-keys.txt"
COD_AUDIO_LOUDSPEAKER = 0x240414
SERVICE_RECORD_AUDIO_SOURCE = 0x10001
SERVICE_RECORD_AUDIO_SINK = 0x10002
BT_AUDIO_SOURCE_UUID16 = 0x110A
BT_AUDIO_SINK_UUID16 = 0x110B
COD_MAJOR_AUDIO_VIDEO = 0x0400


def error_text(error: Exception) -> str:
    return str(error) or type(error).__name__


def make_aac_capabilities(max_bitrate: int = 320000):
    return avdtp.MediaCodecCapabilities(
        avdtp.AVDTP_AUDIO_MEDIA_TYPE,
        a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
        a2dp.AacMediaCodecInformation.from_lists(
            [a2dp.MPEG_2_AAC_LC_OBJECT_TYPE, a2dp.MPEG_4_AAC_LC_OBJECT_TYPE],
            [44100, 48000],
            [2],
            1,
            max_bitrate,
        ),
    )


def make_aac_stream_configuration(codec_info=None):
    object_type = _first_supported(
        getattr(codec_info, "object_type", 0),
        (
            a2dp.AacMediaCodecInformation.OBJECT_TYPE_BITS[a2dp.MPEG_4_AAC_LC_OBJECT_TYPE],
            a2dp.AacMediaCodecInformation.OBJECT_TYPE_BITS[a2dp.MPEG_2_AAC_LC_OBJECT_TYPE],
        ),
    ) or a2dp.AacMediaCodecInformation.OBJECT_TYPE_BITS[a2dp.MPEG_4_AAC_LC_OBJECT_TYPE]
    sampling = _first_supported(
        getattr(codec_info, "sampling_frequency", 0),
        (
            a2dp.AacMediaCodecInformation.SAMPLING_FREQUENCY_BITS[44100],
            a2dp.AacMediaCodecInformation.SAMPLING_FREQUENCY_BITS[48000],
        ),
    ) or a2dp.AacMediaCodecInformation.SAMPLING_FREQUENCY_BITS[44100]
    channels = _first_supported(
        getattr(codec_info, "channels", 0),
        (
            a2dp.AacMediaCodecInformation.CHANNELS_BITS[2],
            a2dp.AacMediaCodecInformation.CHANNELS_BITS[1],
        ),
    ) or a2dp.AacMediaCodecInformation.CHANNELS_BITS[2]
    bitrate = min(int(getattr(codec_info, "bitrate", 0) or 256000), 256000)
    return [
        avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
        avdtp.MediaCodecCapabilities(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
            a2dp.AacMediaCodecInformation(object_type, sampling, channels, 1, bitrate),
        ),
    ]


def make_sbc_capabilities():
    return avdtp.MediaCodecCapabilities(
        avdtp.AVDTP_AUDIO_MEDIA_TYPE,
        a2dp.A2DP_SBC_CODEC_TYPE,
        a2dp.SbcMediaCodecInformation.from_lists(
            [44100, 48000],
            [a2dp.SBC_JOINT_STEREO_CHANNEL_MODE, a2dp.SBC_STEREO_CHANNEL_MODE],
            [16],
            [8],
            [a2dp.SBC_LOUDNESS_ALLOCATION_METHOD],
            2,
            53,
        ),
    )


def make_sbc_stream_configuration(codec_info=None):
    sampling = _first_supported(
        getattr(codec_info, "sampling_frequency", 0),
        (
            a2dp.SbcMediaCodecInformation.SAMPLING_FREQUENCY_BITS[44100],
            a2dp.SbcMediaCodecInformation.SAMPLING_FREQUENCY_BITS[48000],
        ),
    ) or a2dp.SbcMediaCodecInformation.SAMPLING_FREQUENCY_BITS[44100]
    channel_mode = _first_supported(
        getattr(codec_info, "channel_mode", 0),
        (
            a2dp.SbcMediaCodecInformation.CHANNEL_MODE_BITS[a2dp.SBC_JOINT_STEREO_CHANNEL_MODE],
            a2dp.SbcMediaCodecInformation.CHANNEL_MODE_BITS[a2dp.SBC_STEREO_CHANNEL_MODE],
        ),
    ) or a2dp.SbcMediaCodecInformation.CHANNEL_MODE_BITS[a2dp.SBC_JOINT_STEREO_CHANNEL_MODE]
    block_length = _first_supported(
        getattr(codec_info, "block_length", 0),
        (a2dp.SbcMediaCodecInformation.BLOCK_LENGTH_BITS[16],),
    ) or a2dp.SbcMediaCodecInformation.BLOCK_LENGTH_BITS[16]
    subbands = _first_supported(
        getattr(codec_info, "subbands", 0),
        (a2dp.SbcMediaCodecInformation.SUBBANDS_BITS[8],),
    ) or a2dp.SbcMediaCodecInformation.SUBBANDS_BITS[8]
    allocation = _first_supported(
        getattr(codec_info, "allocation_method", 0),
        (a2dp.SbcMediaCodecInformation.ALLOCATION_METHOD_BITS[a2dp.SBC_LOUDNESS_ALLOCATION_METHOD],),
    ) or a2dp.SbcMediaCodecInformation.ALLOCATION_METHOD_BITS[a2dp.SBC_LOUDNESS_ALLOCATION_METHOD]
    min_bitpool = max(2, int(getattr(codec_info, "minimum_bitpool_value", 2) or 2))
    max_bitpool = min(53, int(getattr(codec_info, "maximum_bitpool_value", 53) or 53))
    return [
        avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
        avdtp.MediaCodecCapabilities(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_SBC_CODEC_TYPE,
            a2dp.SbcMediaCodecInformation(
                sampling,
                channel_mode,
                block_length,
                subbands,
                allocation,
                min_bitpool,
                max_bitpool,
            ),
        ),
    ]


def _first_supported(mask, preferences):
    for value in preferences:
        if mask & value:
            return value
    return None


def _eir_name(data):
    for key in (AdvertisingData.COMPLETE_LOCAL_NAME, AdvertisingData.SHORTENED_LOCAL_NAME):
        try:
            value = data.get(key, raw=True)
        except Exception:
            value = None
        if value:
            try:
                return value.decode("utf-8", errors="replace").strip()
            except Exception:
                return str(value).strip()
    return ""


def _is_audio_video_class(class_of_device):
    try:
        return (int(class_of_device) & 0x1F00) == COD_MAJOR_AUDIO_VIDEO
    except Exception:
        return False


def _endpoint_codec_capability(endpoint, codec_type):
    for capability in getattr(endpoint, "capabilities", []):
        if (
            capability.service_category == avdtp.AVDTP_MEDIA_CODEC_SERVICE_CATEGORY
            and capability.media_type == avdtp.AVDTP_AUDIO_MEDIA_TYPE
            and capability.media_codec_type == codec_type
        ):
            return capability
    return None


def _endpoint_has_media_transport(endpoint):
    return any(
        capability.service_category == avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY
        for capability in getattr(endpoint, "capabilities", [])
    )


class A2DPBridge:
    def __init__(
        self,
        device: Device,
        state,
        bt_name: str = DEFAULT_BT_NAME,
        autoconnect: bool = True,
        reconnect_interval: float = 12.0,
        connect_timeout: float = 20.0,
        on_state_change=None,
        logger: logging.Logger | None = None,
    ):
        self.device = device
        self.state = state
        self.bt_name = bt_name or getattr(device, "name", "") or device_name()
        self.autoconnect = autoconnect
        self.reconnect_interval = reconnect_interval
        self.connect_timeout = connect_timeout
        self.on_state_change = on_state_change or (lambda: None)
        self.logger = logger or logging.getLogger(__name__)

        self.listener: avdtp.Listener | None = None
        self.receiver_connection = None
        self.receiver_protocol: avdtp.Protocol | None = None
        self.receiver_source = None
        self.receiver_stream = None
        self.receiver_rtp_channel = None
        self.receiver_address = None
        self.receiver_connecting_address = None
        self.receiver_last_error = ""
        self.source_stream_active = False
        self._source_connection = None      # [CLAUDE 2026-06-02] classic-ACL источника (iPhone) для CarThing-инициируемого teardown
        self.started = False
        self.packets_forwarded = 0
        self.packets_dropped = 0
        self.bytes_forwarded = 0
        self._receiver_task: asyncio.Task | None = None
        self._standby_task: asyncio.Task | None = None
        self._scan_task: asyncio.Task | None = None
        self._enroll_task: asyncio.Task | None = None
        self._connect_task: asyncio.Task | None = None
        self._receiver_retry_task: asyncio.Task | None = None
        self._standby_connecting = set()
        self._speaker_connections = {}
        self._stale_link_key_addresses = set()

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
        def legacy_link_key(address):
            path = os.environ.get("CARTHING_CLASSIC_LINK_KEYS", DEFAULT_LEGACY_LINK_KEYS_PATH)
            normalized = normalize_address(address)
            try:
                with open(path, "r") as keys_file:
                    for line in keys_file:
                        parts = line.strip().split()
                        if len(parts) >= 2 and normalize_address(parts[0]) == normalized:
                            return bytes.fromhex(parts[1])
            except FileNotFoundError:
                return None
            except Exception as exc:
                self.logger.info("A2DP legacy link-key lookup ignored: %s", error_text(exc))
            return None

        async def safe_link_key_provider(address):
            normalized = normalize_address(address)
            if normalized in self._stale_link_key_addresses:
                self.logger.info("A2DP classic link-key suppressed after auth failure: %s", normalized)
                return None
            value = legacy_link_key(address)
            if value is not None:
                self.logger.info("A2DP classic legacy link-key found for %s", normalized)
                return value
            if self.device.keystore is None:
                return None
            candidates = [str(address), normalized, f"{normalized}/P"]
            for candidate in dict.fromkeys(candidates):
                keys = await self.device.keystore.get(candidate)
                link_key = getattr(keys, "link_key", None) if keys is not None else None
                value = getattr(link_key, "value", None)
                if value is not None:
                    self.logger.info("A2DP classic link-key found for %s", candidate)
                    return value
            self.logger.info("A2DP classic link-key missing for %s", address)
            return None

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
            "A2DP bridge started: local=%s name=%s trusted_sources=%d trusted_speakers=%d",
            self.device.public_address,
            self.bt_name,
            len(self.state.trusted_sources),
            len(self.state.trusted_speakers),
        )
        if self.autoconnect and self.state.trusted_speakers:
            self._receiver_task = asyncio.create_task(self.receiver_loop())

    def start_standby_loop(self):
        if self._standby_task is None or self._standby_task.done():
            self._standby_task = asyncio.create_task(self.speaker_standby_loop())

    async def speaker_standby_loop(self):
        """Keep trusted speakers in a bonded Classic standby connection.

        This is deliberately below Transfer. A trusted speaker should stick to
        the device when available; Transfer only decides whether that existing
        connection is used as the audio route.
        """
        while True:
            try:
                await self.ensure_trusted_speakers_connected()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.info("A2DP speaker standby ignored: %s", error_text(exc))
            await asyncio.sleep(self.reconnect_interval)

    async def ensure_trusted_speakers_connected(self):
        for speaker in list(self.state.trusted_speakers):
            address = normalize_address(speaker.get("address"))
            if not address or address in self._speaker_connections:
                continue
            if address in self._standby_connecting:
                continue
            if not await self._has_link_key(address):
                # [CLAUDE 2026-06-02] НЕ ломиться в неспаренную колонку. Динамик без
                # link-key никогда не парился штатно — standby-loop НЕ должен его звонить
                # (иначе «постоянно ломится в неподключённый Fosi, добавляет в доверенные,
                # а он остаётся не в спаренном режиме»). Он остаётся в списке как offline-
                # статус; реальное (пере)сопряжение — только явным flow добавления динамика.
                # online/offline здесь — статус, а не триггер автозвонка.
                self.logger.info("A2DP speaker standby skipped (not paired, no link-key): %s", address)
                continue
            await self.ensure_speaker_connection(address)

    async def enable_classic_visibility(self):
        # Connectable always (bonded peers reconnect, incoming A2DP works), but
        # NOT discoverable by default — discovery is opened only in pairing mode.
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
        await self.device.set_discoverable(False)
        self.logger.info("A2DP classic connectable (not discoverable) enabled")

    async def enter_pairing(self):
        """Pairing mode: become classic-discoverable (so a phone can add us as an
        audio output) and scan for trusted speakers to add as transfer targets."""
        await self.device.set_discoverable(True)
        self.logger.info("A2DP classic discoverable ON (pairing)")
        if self._scan_task is None or self._scan_task.done():
            self._scan_task = asyncio.create_task(self.scan_trusted_speakers())

    async def exit_pairing(self):
        await self.device.set_discoverable(False)
        self.logger.info("A2DP classic discoverable OFF")

    async def receiver_loop(self):
        while True:
            try:
                if self.receiver_rtp_channel is None:
                    await self.setup_receiver()
                await asyncio.sleep(self.reconnect_interval)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.receiver_rtp_channel = None
                self.logger.warning("A2DP receiver setup failed: %s", error_text(exc))
                await asyncio.sleep(self.reconnect_interval)

    async def setup_receiver(self, address=None, connection=None):
        address = address or self.state.default_speaker_address()
        if not address:
            raise RuntimeError("no trusted speaker configured")
        if not self.state.is_trusted_speaker(address):
            raise RuntimeError(f"receiver is not trusted as speaker: {address}")

        target_address = normalize_address(address)
        self.receiver_connecting_address = target_address
        self.receiver_last_error = ""
        self.state.transfer_status = "connecting"
        self.on_state_change()

        connection = connection or await self.ensure_speaker_connection(target_address)
        self.logger.info("A2DP receiver ACL ready: %s", target_address)
        self.receiver_connection = connection
        connection.on(
            "disconnection",
            lambda reason: asyncio.ensure_future(self.on_receiver_disconnected(reason)),
        )
        try:
            await asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout)
            await asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout)
        except Exception as exc:
            self.logger.info("A2DP receiver auth/encrypt continued: %s", error_text(exc))

        self.logger.info("A2DP receiver AVDTP connect: %s", target_address)
        protocol = await asyncio.wait_for(
            avdtp.Protocol.connect(connection),
            timeout=self.connect_timeout,
        )
        self.receiver_protocol = protocol
        self.logger.info("A2DP receiver discover endpoints: %s", target_address)
        await asyncio.wait_for(protocol.discover_remote_endpoints(), timeout=self.connect_timeout)

        for endpoint in protocol.remote_endpoints.values():
            caps = "; ".join(str(capability) for capability in getattr(endpoint, "capabilities", []))
            self.logger.info(
                "A2DP receiver endpoint: address=%s seid=%s in_use=%s media=%s tsep=%s caps=%s",
                target_address,
                getattr(endpoint, "seid", "?"),
                getattr(endpoint, "in_use", "?"),
                getattr(endpoint, "media_type", "?"),
                getattr(endpoint, "tsep", "?"),
                caps,
            )

        sink, source_capability, source_configuration, codec_name = self._select_receiver_codec(protocol)
        if sink is None:
            raise RuntimeError("receiver has no compatible audio sink endpoint")

        self.logger.info(
            "A2DP receiver sink selected: address=%s codec=%s seid=%s",
            target_address,
            codec_name,
            getattr(sink, "seid", "?"),
        )
        source = protocol.add_source(source_capability, None)
        source.configuration = source_configuration
        stream = await protocol.create_stream(source, sink)
        await stream.open()
        await stream.start()

        self.receiver_source = source
        self.receiver_stream = stream
        self.receiver_rtp_channel = stream.rtp_channel
        self.receiver_address = target_address
        self.receiver_connecting_address = None
        self.state.transfer_status = "connected"
        self.state.set_connected_speaker(target_address)
        self.on_state_change()
        self.logger.info("A2DP_SPEAKER_STREAM_STARTED codec=%s seid=%s", codec_name, getattr(sink, "seid", "?"))

    def _select_receiver_codec(self, protocol):
        for codec_type, codec_name, capability_factory, configuration_factory in (
            (a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE, "AAC", make_aac_capabilities, make_aac_stream_configuration),
            (a2dp.A2DP_SBC_CODEC_TYPE, "SBC", make_sbc_capabilities, make_sbc_stream_configuration),
        ):
            for endpoint in protocol.remote_endpoints.values():
                if (
                    getattr(endpoint, "in_use", False)
                    or getattr(endpoint, "media_type", None) != avdtp.AVDTP_AUDIO_MEDIA_TYPE
                    or getattr(endpoint, "tsep", None) != avdtp.AVDTP_TSEP_SNK
                    or not _endpoint_has_media_transport(endpoint)
                ):
                    continue
                codec_capability = _endpoint_codec_capability(endpoint, codec_type)
                if codec_capability is None:
                    continue
                return (
                    endpoint,
                    capability_factory(),
                    configuration_factory(codec_capability.media_codec_information),
                    codec_name,
                )
        return None, None, None, None

    async def ensure_speaker_connection(self, address, require_trusted=True, strict_security=False):
        address = normalize_address(address)
        connection = self._speaker_connections.get(address)
        if connection is not None:
            if strict_security:
                await asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout)
                await asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout)
            self.state.set_speaker_connected(address, True)
            self.on_state_change()
            return connection
        if not address:
            raise RuntimeError("no speaker address")
        if require_trusted and not self.state.is_trusted_speaker(address):
            raise RuntimeError(f"speaker is not trusted: {address}")
        deadline = asyncio.get_running_loop().time() + self.connect_timeout
        while address in self._standby_connecting:
            await asyncio.sleep(0.1)
            connection = self._speaker_connections.get(address)
            if connection is not None:
                self.state.set_speaker_connected(address, True)
                self.on_state_change()
                return connection
            if asyncio.get_running_loop().time() >= deadline:
                raise RuntimeError(f"speaker connect already in progress: {address}")

        self._standby_connecting.add(address)
        try:
            self.logger.info("A2DP speaker standby connect: %s", address)
            connection = await asyncio.wait_for(
                self.device.connect(address, transport=BT_BR_EDR_TRANSPORT),
                timeout=self.connect_timeout,
            )
            self._speaker_connections[address] = connection
            connection.on(
                "disconnection",
                lambda reason: asyncio.ensure_future(self.on_speaker_disconnected(address, reason)),
            )
            try:
                await asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout)
                await asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout)
            except Exception as exc:
                if strict_security:
                    raise
                self.logger.info("A2DP speaker standby auth/encrypt continued: %s", error_text(exc))
            self.state.set_speaker_connected(address, True)
            self.on_state_change()
            self.logger.info("A2DP_SPEAKER_STANDBY_CONNECTED %s", address)
            return connection
        finally:
            self._standby_connecting.discard(address)

    async def request_receiver_connection(self, address=None, require_online=False):
        address = normalize_address(address or self.state.default_speaker_address())
        if not address:
            self.logger.info("A2DP receiver not requested: no trusted speaker")
            return
        if require_online:
            speakers = [speaker for speaker in self.state.trusted_speakers if speaker.get("address") == address]
            if not speakers or not (speakers[0].get("online") or speakers[0].get("connected")):
                self.logger.info("A2DP receiver wait: default speaker not seen online: %s", address)
                return
        if self.receiver_rtp_channel is not None and self.receiver_address == address:
            self.logger.info("A2DP receiver already ready: %s", address)
            return
        if self._connect_task is not None and not self._connect_task.done():
            self.logger.info("A2DP receiver connect already in progress")
            return
        self._connect_task = asyncio.create_task(self._connect_receiver(address))

    async def request_receiver_for_active_source(self, address=None):
        if not self.source_stream_active:
            self.logger.info("A2DP receiver not requested: no active source stream")
            return
        await self.request_receiver_connection(address)

    def schedule_receiver_retry(self, delay: float = 1.0):
        if not self.source_stream_active or not getattr(self.state, "transfer_active", False):
            return
        # [CLAUDE 2026-06-02] Если доверенная колонка не выбрана — ретраить НЕЧЕМ: она не
        # появится от повторов. Без этой проверки forward_packet дёргал retry на КАЖДЫЙ
        # дропнутый RTP-пакет → request_receiver_connection спамил «no trusted speaker»
        # ~4 раза/сек и заливал лог (видели dropped=27500). Колонка выбрана → ретрай имеет
        # смысл (например, classic-link дропнул и надо переподнять).
        if not normalize_address(self.state.default_speaker_address()):
            return
        if self.receiver_rtp_channel is not None:
            return
        if self._connect_task is not None and not self._connect_task.done():
            return
        if self._receiver_retry_task is not None and not self._receiver_retry_task.done():
            return

        async def _retry():
            try:
                await asyncio.sleep(delay)
                await self.request_receiver_for_active_source()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.logger.warning("A2DP receiver retry failed: %s", error_text(exc))

        self._receiver_retry_task = asyncio.create_task(_retry())

    async def _connect_receiver(self, address):
        try:
            await self.setup_receiver(address=address)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.receiver_address = None
            self.receiver_connecting_address = None
            self.receiver_rtp_channel = None
            self.receiver_last_error = error_text(exc)
            self.state.transfer_status = "failed"
            self.state.transfer_error = self.receiver_last_error
            if address in self._speaker_connections:
                self.state.set_speaker_connected(address, True)
            self.on_state_change()
            self.logger.warning("A2DP receiver connect failed: %s", error_text(exc))

    async def scan_trusted_speakers(self, duration: float = 6.0):
        found = set()
        complete = asyncio.get_running_loop().create_future()

        def on_inquiry_result(address, _class_of_device, _data, _rssi):
            if self.state.is_trusted_speaker(address):
                normalized = normalize_address(address)
                found.add(normalized)
                self.state.set_speaker_online(normalized, True)
                self.on_state_change()
                self.logger.info("A2DP trusted speaker seen: %s", normalized)

        def on_inquiry_complete():
            if not complete.done():
                complete.set_result(None)

        self.state.transfer_scanning = True
        self.state.clear_speaker_online()
        self.on_state_change()
        self.device.on("inquiry_result", on_inquiry_result)
        self.device.on("inquiry_complete", on_inquiry_complete)
        try:
            await self.device.start_discovery(auto_restart=False)
            try:
                await asyncio.wait_for(complete, timeout=duration)
            except Exception:
                pass
        finally:
            self.device.remove_listener("inquiry_result", on_inquiry_result)
            self.device.remove_listener("inquiry_complete", on_inquiry_complete)
            try:
                await self.device.stop_discovery()
            except Exception as exc:
                self.logger.info("A2DP speaker scan stop ignored: %s", error_text(exc))
            self.state.transfer_scanning = False
            self.on_state_change()
            if self.state.transfer_active and self.source_stream_active:
                await self.request_receiver_connection(require_online=True)
            else:
                await self.ensure_trusted_speakers_connected()

    async def scan_pairable_speakers(self, duration: float = 10.0):
        """Classic inquiry for new speaker enrollment.

        This does not make Car Thing discoverable and does not create another
        registry. Found devices are temporary candidates; the selected row is
        persisted as a trusted speaker by pair_speaker().
        """
        complete = asyncio.get_running_loop().create_future()
        pending_names = set()

        async def update_name(address):
            normalized = normalize_address(address)
            if not normalized or normalized in pending_names:
                return
            pending_names.add(normalized)
            try:
                name = await asyncio.wait_for(self.device.request_remote_name(address), timeout=5.0)
            except Exception:
                return
            finally:
                pending_names.discard(normalized)
            self.state.upsert_speaker_candidate(normalized, name=name)
            self.on_state_change()
            self.logger.info("A2DP pairable speaker name: %s %s", normalized, name)

        def on_inquiry_result(address, class_of_device, data, rssi):
            name = _eir_name(data)
            audio_like = _is_audio_video_class(class_of_device)
            # Keep non-audio devices visible too: many cheap speakers report a
            # weak COD. Audio-like devices are simply shown first by insertion.
            self.state.upsert_speaker_candidate(
                address,
                name=name,
                class_of_device=int(class_of_device) if class_of_device is not None else None,
                rssi=rssi,
                audio=audio_like,
            )
            self.on_state_change()
            self.logger.info(
                "A2DP pairable candidate: %s name=%s cod=%s audio=%s rssi=%s",
                normalize_address(address), name or "-", class_of_device, audio_like, rssi,
            )
            if not name:
                asyncio.create_task(update_name(address))

        def on_inquiry_complete():
            if not complete.done():
                complete.set_result(None)

        self.state.speaker_pairing_status = "scan"
        self.state.clear_speaker_candidates()
        self.on_state_change()
        self.device.on("inquiry_result", on_inquiry_result)
        self.device.on("inquiry_complete", on_inquiry_complete)
        try:
            await self.device.start_discovery(auto_restart=False)
            try:
                await asyncio.wait_for(complete, timeout=duration)
            except Exception:
                pass
        finally:
            self.device.remove_listener("inquiry_result", on_inquiry_result)
            self.device.remove_listener("inquiry_complete", on_inquiry_complete)
            try:
                await self.device.stop_discovery()
            except Exception as exc:
                self.logger.info("A2DP pairable scan stop ignored: %s", error_text(exc))
            self.state.speaker_pairing_status = "idle"
            self.on_state_change()

    async def pair_speaker(self, address):
        address = normalize_address(address)
        if not address:
            return
        candidate = next((c for c in self.state.speaker_candidates
                          if c.get("address") == address), None)
        if candidate is None or not candidate.get("audio"):
            self.state.speaker_pairing_status = "error"
            self.state.pairing_message = "Это не Bluetooth-динамик"
            self.on_state_change()
            return
        label = (candidate or {}).get("label") or address
        self.state.speaker_pairing_status = "connect"
        self.state.pairing_message = ""
        self.on_state_change()
        try:
            await self.device.stop_discovery()
        except Exception:
            pass
        await self._bond_speaker(address)
        if not await self._has_link_key(address):
            raise RuntimeError(f"classic link key not stored for {address}")
        speaker = self.state.trust_speaker(address, label)
        if speaker is None:
            raise RuntimeError(f"refused to trust non-speaker {address}")
        self.state.select_default_speaker(address)
        try:
            await self.ensure_speaker_connection(address, strict_security=True)
        except Exception:
            self.state.remove_trusted(address)
            raise
        self.state.set_speaker_connected(address, True)
        self.state.speaker_pairing_status = "done"
        self.state.pairing_message = f"{label} подключен"
        try:
            self.state.save_trusted()
        except Exception as exc:
            self.logger.warning("speaker trust save failed: %s", error_text(exc))
        self.on_state_change()
        if self.state.transfer_active:
            await self.request_receiver_connection(address)
        else:
            await self.ensure_speaker_connection(address)

    async def _bond_speaker(self, address):
        await self.ensure_speaker_connection(address, require_trusted=False, strict_security=True)

    async def connect_source(self, address):
        """[CLAUDE 2026-06-02] CarThing САМ звонит уже-BLE-бондед айфону по classic
        (исходящий BR/EDR page) — по действию из меню. Авторизуется сохранённым link-key
        (CTKD/safe_link_key_provider), шифрует. Айфон, как доверенный bonded аудио-выход,
        МОЛЧА принимает и начинает стримить A2DP -> AVDTP-listener ловит поток. Это и есть
        «мы инициируем classic из меню, айфон просто подхватывает». BLE остаётся
        единственным транспортом, который инициирует САМ айфон; classic — всегда от нас.
        НЕ делает устройство discoverable/connectable — только исходящий звонок."""
        address = normalize_address(address)
        if not address:
            raise RuntimeError("no bonded source address to dial")
        self.logger.info("A2DP source classic dial (CarThing-initiated): %s", address)
        connection = await asyncio.wait_for(
            self.device.connect(address, transport=BT_BR_EDR_TRANSPORT),
            timeout=self.connect_timeout,
        )
        try:
            await asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout)
            await asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout)
        except Exception as exc:
            self.logger.warning("A2DP source dial auth/encrypt failed: %s", error_text(exc))
            raise
        await self.handle_classic_connection(connection)
        self._source_connection = connection
        connection.on("disconnection", lambda _r: self._clear_source_connection())
        self.logger.info("A2DP_SOURCE_CLASSIC_DIALED %s", address)
        return connection

    def _clear_source_connection(self):
        self._source_connection = None

    async def disconnect_source(self):
        """[CLAUDE 2026-06-02] CarThing-инициируемый возврат «на BLE»: рвём classic-ACL
        источника (iPhone). BLE-линк (AMS/ANCS/CTS) НЕ трогаем — он независимый транспорт
        и живёт постоянно. Симметрично connect_source: весь тумблер classic держит CarThing."""
        connection = self._source_connection
        self._source_connection = None
        if connection is None:
            return
        try:
            await connection.disconnect()
            self.logger.info("A2DP source classic ACL disconnected (back to BLE-only)")
        except Exception as exc:
            self.logger.info("A2DP source classic disconnect ignored: %s", error_text(exc))

    async def _has_link_key(self, address):
        if self.device.keystore is None:
            return False
        candidates = [normalize_address(address), f"{normalize_address(address)}/P", str(address)]
        for candidate in dict.fromkeys(candidates):
            try:
                keys = await self.device.keystore.get(candidate)
            except Exception:
                keys = None
            if keys is not None and getattr(keys, "link_key", None) is not None:
                return True
        return False

    async def forget_peer_key(self, address):
        if self.device.keystore is None:
            return
        normalized = normalize_address(address)
        for candidate in dict.fromkeys([normalized, f"{normalized}/P", str(address)]):
            try:
                await self.device.keystore.delete(candidate)
                self.logger.info("A2DP removed key for %s", candidate)
            except Exception:
                pass

    async def on_receiver_disconnected(self, reason):
        self.logger.warning("A2DP receiver disconnected: reason=0x%02x", reason)
        self.receiver_connection = None
        self.receiver_protocol = None
        self.receiver_source = None
        self.receiver_stream = None
        self.receiver_rtp_channel = None
        self.receiver_address = None
        self.receiver_connecting_address = None
        self.receiver_last_error = f"disconnected 0x{reason:02x}"
        self.state.transfer_status = "failed"
        self.state.transfer_error = self.receiver_last_error
        self.on_state_change()
        self.schedule_receiver_retry(delay=1.5)

    async def stop_receiver_stream(self):
        stream = self.receiver_stream
        if stream is not None:
            try:
                await stream.stop()
            except Exception as exc:
                self.logger.info("A2DP receiver stream stop ignored: %s", error_text(exc))
            try:
                await stream.close()
            except Exception as exc:
                self.logger.info("A2DP receiver stream close ignored: %s", error_text(exc))
        self.receiver_protocol = None
        self.receiver_source = None
        self.receiver_stream = None
        self.receiver_rtp_channel = None
        self.receiver_address = None
        self.receiver_connecting_address = None
        self.state.transfer_status = "standby"
        self.on_state_change()

    def on_avdtp_connection(self, protocol: avdtp.Protocol):
        peer_address = protocol.l2cap_channel.connection.peer_address
        if self.state.trusted_sources and not self.state.is_trusted_source(peer_address):
            self.logger.warning("A2DP source rejected, not trusted: %s", peer_address)
            return

        self.logger.info("A2DP incoming trusted source: %s", peer_address)
        sink = protocol.add_sink(make_aac_capabilities())

        original_set_configuration = sink.on_set_configuration_command
        original_start = sink.on_start_command
        original_open = sink.on_open_command
        original_suspend = sink.on_suspend_command
        original_close = sink.on_close_command
        original_abort = sink.on_abort_command

        def on_set_configuration(configuration):
            self.logger.info("A2DP_SOURCE_SET_CONFIGURATION %s", configuration)
            return original_set_configuration(configuration)

        def on_open():
            self.logger.info("A2DP_SOURCE_OPEN")
            return original_open()

        def on_start():
            self.logger.info("A2DP_SOURCE_START")
            self.source_stream_active = True
            self.state.transfer_active = True
            self.state.transfer_source = normalize_address(peer_address)
            self.state.active_desktop = self.state.TRANSFER
            self.on_state_change()
            asyncio.create_task(self.request_receiver_for_active_source())
            return original_start()

        def on_suspend():
            self.logger.info("A2DP_SOURCE_SUSPEND")
            self.source_stream_active = False
            asyncio.create_task(self.stop_receiver_stream())
            return original_suspend()

        def on_close():
            self.logger.info("A2DP_SOURCE_CLOSE")
            self.source_stream_active = False
            asyncio.create_task(self.stop_receiver_stream())
            return original_close()

        def on_abort():
            self.logger.info("A2DP_SOURCE_ABORT")
            self.source_stream_active = False
            asyncio.create_task(self.stop_receiver_stream())
            return original_abort()

        sink.on_set_configuration_command = on_set_configuration
        sink.on_open_command = on_open
        sink.on_start_command = on_start
        sink.on_suspend_command = on_suspend
        sink.on_close_command = on_close
        sink.on_abort_command = on_abort
        sink.on("rtp_packet", self.forward_packet)

    def forward_packet(self, packet):
        payload = bytes(packet)
        sent = False
        if self.receiver_rtp_channel is not None:
            self.receiver_rtp_channel.send_pdu(payload)
            sent = True
            self.packets_forwarded += 1
            self.bytes_forwarded += len(payload)
        elif self.source_stream_active and getattr(self.state, "transfer_active", False):
            self.packets_dropped += 1
            self.schedule_receiver_retry(delay=0.2)

        count = self.packets_forwarded if sent else self.packets_dropped
        if count < 10 or count % 250 == 0:
            self.logger.info(
                "A2DP_BRIDGE_RTP forwarded=%d dropped=%d bytes=%d sent_to_speaker=%s",
                self.packets_forwarded,
                self.packets_dropped,
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
        peer_address = normalize_address(connection.peer_address)
        connection.on(
            "connection_authentication_failure",
            lambda _error: self.on_classic_authentication_failure(peer_address),
        )
        if self.state.is_trusted_speaker(peer_address):
            self._speaker_connections[peer_address] = connection
            self.state.set_speaker_connected(peer_address, True)
            self.on_state_change()
            connection.on(
                "disconnection",
                lambda reason: asyncio.ensure_future(self.on_speaker_disconnected(peer_address, reason)),
            )
            if self.state.transfer_active and self.source_stream_active:
                await self.request_receiver_for_active_source(peer_address)
        elif self.state.is_trusted_source(peer_address):
            # [CLAUDE 2026-06-02] Входящий classic от доверенного источника (айфон сам
            # подключился). Храним ACL, чтобы CarThing мог инициировать teardown (disconnect_source).
            self._source_connection = connection
            connection.on("disconnection", lambda _r: self._clear_source_connection())
        elif self.state.trusted_sources and not self.state.is_trusted_source(peer_address):
            self.logger.warning("Classic BT peer is not trusted for transfer: %s", peer_address)

    def on_classic_authentication_failure(self, address):
        address = normalize_address(address)
        if self.state.is_trusted_source(address):
            self._stale_link_key_addresses.add(address)
            self.logger.warning("A2DP source classic link-key marked stale: %s", address)

    async def on_speaker_disconnected(self, address, reason):
        address = normalize_address(address)
        self._speaker_connections.pop(address, None)
        self.state.set_speaker_online(address, False)
        self.state.set_speaker_connected(address, False)
        if self.receiver_address == address:
            await self.on_receiver_disconnected(reason)
        else:
            self.on_state_change()
