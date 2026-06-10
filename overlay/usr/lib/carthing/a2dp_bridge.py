"""A2DP transfer service for the Car Thing runtime."""

import asyncio
import hashlib
import logging
import os

from bumble import a2dp, avc, avctp, avdtp, avrcp, l2cap
from bumble.core import (
    BT_BR_EDR_TRANSPORT,
    BT_SERVICE_DISCOVERY_SERVER_SERVICE_CLASS_ID_SERVICE,
    UUID,
)
from bumble.device import AdvertisingData, Device
from bumble.hci import (
    HCI_Read_Class_Of_Device_Command,
    HCI_Write_Class_Of_Device_Command,
)
from bumble.sdp import (
    SDP_BROWSE_GROUP_LIST_ATTRIBUTE_ID,
    SDP_PUBLIC_BROWSE_ROOT,
    SDP_SERVICE_CLASS_ID_LIST_ATTRIBUTE_ID,
    SDP_SERVICE_RECORD_HANDLE_ATTRIBUTE_ID,
    SDP_SUPPORTED_FEATURES_ATTRIBUTE_ID,
    DataElement,
    ServiceAttribute,
)

from app_state import normalize_address
from runtime_paths import device_name


DEFAULT_BT_NAME = ""
DEFAULT_LEGACY_LINK_KEYS_PATH = "/run/carthing-state/carthing/iap2-link-keys.txt"
# [CLAUDE 2026-06-04] 0x240414 = Audio/Video major + Loudspeaker minor + Audio/Rendering service.
# Codex: для A2DP speaker правильный CoD = loudspeaker (0x240404 = Wearable Headset, хуже).
COD_AUDIO_LOUDSPEAKER = 0x240414
SERVICE_RECORD_AUDIO_SOURCE = 0x10001
SERVICE_RECORD_AUDIO_SINK = 0x10002
SERVICE_RECORD_AVRCP_TARGET = 0x10003
SERVICE_RECORD_AVRCP_CONTROLLER = 0x10004
# C1 (Apple ADG 57.11.2): ServiceDiscoveryServer + ServiceDatabaseState —
# смена значения обязывает iOS сбросить SDP-кэш (без «Forget This Device»).
SERVICE_RECORD_SDS = 0x10005
SDP_VERSION_NUMBER_LIST_ATTRIBUTE_ID = 0x0200
SDP_SERVICE_DATABASE_STATE_ATTRIBUTE_ID = 0x0201
BT_AUDIO_SOURCE_UUID16 = 0x110A
BT_AUDIO_SINK_UUID16 = 0x110B
BT_AV_REMOTE_CONTROL_TARGET_UUID16 = 0x110C
BT_AV_REMOTE_CONTROL_UUID16 = 0x110E
BT_AV_REMOTE_CONTROL_CONTROLLER_UUID16 = 0x110F
IAP2_UUID128 = UUID("00000000-deca-fade-deca-deafdecacaff", "iAP2 Accessory")
COD_MAJOR_AUDIO_VIDEO = 0x0400
# A2DP 1.3.2, Audio Sink SupportedFeatures: bit 1 identifies a speaker.
A2DP_SINK_FEATURE_SPEAKER = 0x0002
# AVDTP delay units are 1/10 ms. Report a conservative 150 ms relay delay.
A2DP_SINK_DELAY_REPORT = 1500


def error_text(error: Exception) -> str:
    return str(error) or type(error).__name__


class AudioSinkAvrcpDelegate(avrcp.Delegate):
    """Minimal AVRCP Target state required by an A2DP audio sink."""

    def __init__(self, logger, peer="?", on_key=None, on_volume=None):
        super().__init__(supported_events=[avrcp.EventId.VOLUME_CHANGED])
        self.logger = logger
        self.volume = 64
        # Адрес пира текущей AVCTP-сессии — без него команды iPhone и колонки
        # неотличимы в логе (стоило двух ложных выводов 2026-06-10).
        self.peer = peer
        # Транспортные кнопки пира (play/pause/next/...) — наружу, в backchannel.
        self.on_key = on_key
        # Absolute volume от источника — наружу, для синхронизации на колонку.
        self.on_volume = on_volume

    async def set_absolute_volume(self, volume: int) -> None:
        await super().set_absolute_volume(volume)
        self.logger.info("AVRCP target absolute volume=%d peer=%s", volume, self.peer)
        if self.on_volume is not None:
            self.on_volume(volume, self.peer)

    async def on_key_event(self, key, pressed: bool, data: bytes) -> None:
        self.logger.info("AVRCP target key=%s pressed=%s peer=%s", key, pressed, self.peer)
        if self.on_key is not None:
            await self.on_key(key, pressed, self.peer)


def make_audio_sink_sdp_records():
    records = a2dp.make_audio_sink_service_sdp_records(SERVICE_RECORD_AUDIO_SINK)
    records.append(
        ServiceAttribute(
            SDP_SUPPORTED_FEATURES_ATTRIBUTE_ID,
            DataElement.unsigned_integer_16(A2DP_SINK_FEATURE_SPEAKER),
        )
    )
    return records


def make_aac_capabilities(max_bitrate: int = 320000):
    codec = a2dp.AacMediaCodecInformation
    return avdtp.MediaCodecCapabilities(
        avdtp.AVDTP_AUDIO_MEDIA_TYPE,
        a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
        codec(
            object_type=codec.ObjectType.MPEG_2_AAC_LC | codec.ObjectType.MPEG_4_AAC_LC,
            sampling_frequency=codec.SamplingFrequency.SF_44100
            | codec.SamplingFrequency.SF_48000,
            channels=codec.Channels.STEREO,
            vbr=1,
            bitrate=max_bitrate,
        ),
    )


def make_aac_stream_configuration(codec_info=None):
    codec = a2dp.AacMediaCodecInformation
    object_type = _first_supported(
        getattr(codec_info, "object_type", 0),
        (codec.ObjectType.MPEG_4_AAC_LC, codec.ObjectType.MPEG_2_AAC_LC),
    ) or codec.ObjectType.MPEG_4_AAC_LC
    sampling = _first_supported(
        getattr(codec_info, "sampling_frequency", 0),
        (codec.SamplingFrequency.SF_44100, codec.SamplingFrequency.SF_48000),
    ) or codec.SamplingFrequency.SF_44100
    channels = _first_supported(
        getattr(codec_info, "channels", 0),
        (codec.Channels.STEREO, codec.Channels.MONO),
    ) or codec.Channels.STEREO
    bitrate = min(int(getattr(codec_info, "bitrate", 0) or 256000), 256000)
    return [
        avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
        avdtp.MediaCodecCapabilities(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_MPEG_2_4_AAC_CODEC_TYPE,
            codec(object_type, sampling, channels, 1, bitrate),
        ),
    ]


def make_sbc_capabilities():
    codec = a2dp.SbcMediaCodecInformation
    return avdtp.MediaCodecCapabilities(
        avdtp.AVDTP_AUDIO_MEDIA_TYPE,
        a2dp.A2DP_SBC_CODEC_TYPE,
        codec(
            sampling_frequency=codec.SamplingFrequency.SF_44100
            | codec.SamplingFrequency.SF_48000,
            channel_mode=codec.ChannelMode.JOINT_STEREO | codec.ChannelMode.STEREO,
            block_length=codec.BlockLength.BL_16,
            subbands=codec.Subbands.S_8,
            allocation_method=codec.AllocationMethod.LOUDNESS,
            minimum_bitpool_value=2,
            maximum_bitpool_value=53,
        ),
    )


def make_sbc_stream_configuration(codec_info=None):
    codec = a2dp.SbcMediaCodecInformation
    sampling = _first_supported(
        getattr(codec_info, "sampling_frequency", 0),
        (codec.SamplingFrequency.SF_44100, codec.SamplingFrequency.SF_48000),
    ) or codec.SamplingFrequency.SF_44100
    channel_mode = _first_supported(
        getattr(codec_info, "channel_mode", 0),
        (codec.ChannelMode.JOINT_STEREO, codec.ChannelMode.STEREO),
    ) or codec.ChannelMode.JOINT_STEREO
    block_length = _first_supported(
        getattr(codec_info, "block_length", 0),
        (codec.BlockLength.BL_16,),
    ) or codec.BlockLength.BL_16
    subbands = _first_supported(
        getattr(codec_info, "subbands", 0),
        (codec.Subbands.S_8,),
    ) or codec.Subbands.S_8
    allocation = _first_supported(
        getattr(codec_info, "allocation_method", 0),
        (codec.AllocationMethod.LOUDNESS,),
    ) or codec.AllocationMethod.LOUDNESS
    min_bitpool = max(2, int(getattr(codec_info, "minimum_bitpool_value", 2) or 2))
    max_bitpool = min(53, int(getattr(codec_info, "maximum_bitpool_value", 53) or 53))
    return [
        avdtp.ServiceCapabilities(avdtp.AVDTP_MEDIA_TRANSPORT_SERVICE_CATEGORY),
        avdtp.MediaCodecCapabilities(
            avdtp.AVDTP_AUDIO_MEDIA_TYPE,
            a2dp.A2DP_SBC_CODEC_TYPE,
            codec(
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
        hci_gate=None,
        on_state_change=None,
        on_visibility_request=None,
        logger: logging.Logger | None = None,
    ):
        self.device = device
        self.state = state
        self.bt_name = bt_name or getattr(device, "name", "") or device_name()
        self.autoconnect = autoconnect
        self.reconnect_interval = reconnect_interval
        self.connect_timeout = connect_timeout
        self.hci_gate = hci_gate
        self.on_state_change = on_state_change or (lambda: None)
        # Callback: on_visibility_request(connectable, discoverable) -> coroutine | None
        # Если задан — bridge НЕ трогает set_connectable/set_discoverable напрямую,
        # а делегирует решение оркестратору.
        self.on_visibility_request = on_visibility_request
        self.logger = logger or logging.getLogger(__name__)

        self.listener: avdtp.Listener | None = None
        # AVRCP: СЕССИЯ НА КАЖДОГО ПИРА (finding A2 ревью 2026-06-05). Один
        # глобальный Protocol допускал ровно одну AVCTP-сессию: её занимал
        # iPhone, и колонка не могла поднять backchannel в принципе.
        self.avrcp_sessions: dict[str, avrcp.Protocol] = {}
        self._source_avrcp: avrcp.Protocol | None = None
        self._source_avrcp_addr = "?"
        # transfer_service/runtime подключают сюда TransferControlBackchannel.
        self.speaker_command_handler = None
        # Синхронизация громкости источник→колонка (SetAbsoluteVolume к колонке).
        self._pending_speaker_volume = None
        self._speaker_volume_task = None
        self._speaker_volume_unsupported: set[str] = set()
        # Единая громкость маршрута — гасит эхо iPhone↔Fosi.
        self._route_volume = None
        # Адреса колонок, чьё начальное (interim) значение громкости уже съедено.
        self._speaker_volume_seen: set[str] = set()
        self._avrcp_monitor_tasks: set[asyncio.Task] = set()
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
        # Backoff дозвона к недоступной колонке: каждый page = ~5 c радио;
        # без backoff выключенная колонка съедала эфир каждые 12 c (run10).
        self._speaker_backoff: dict[str, tuple[int, float]] = {}

    async def _gate(self, label, operation):
        if self.hci_gate is None:
            return await operation()
        return await self.hci_gate.run(label, operation)

    async def _request_visibility(self, connectable: bool, discoverable: bool):
        """Делегировать управление classic-видимостью оркестратору (если задан callback),
        иначе — вызвать device напрямую (fallback для standalone-использования)."""
        if self.on_visibility_request is not None:
            result = self.on_visibility_request(connectable, discoverable)
            if hasattr(result, "__await__"):
                await result
        else:
            await self._gate(
                f"a2dp-visibility-{connectable}-{discoverable}",
                lambda: self._set_classic_direct(connectable, discoverable),
            )

    async def _set_classic_direct(self, connectable: bool, discoverable: bool):
        await self.device.set_connectable(connectable)
        await self.device.set_discoverable(discoverable)

    def install_sdp_records(self):
        records = dict(self.device.sdp_service_records)
        records.pop(SERVICE_RECORD_AUDIO_SOURCE, None)
        records.pop(SERVICE_RECORD_SDS, None)
        records[SERVICE_RECORD_AUDIO_SINK] = make_audio_sink_sdp_records()
        records[SERVICE_RECORD_AVRCP_CONTROLLER] = avrcp.ControllerServiceSdpRecord(
            SERVICE_RECORD_AVRCP_CONTROLLER
        ).to_service_attributes()
        records[SERVICE_RECORD_AVRCP_TARGET] = avrcp.TargetServiceSdpRecord(
            SERVICE_RECORD_AVRCP_TARGET
        ).to_service_attributes()
        # ServiceDatabaseState = отпечаток содержимого всех записей: любая правка
        # SDP автоматически меняет state -> iOS обязан перечитать кэш (ADG 57.11.2).
        fingerprint = hashlib.sha1()
        for handle in sorted(records):
            for attribute in records[handle]:
                fingerprint.update(int(attribute.id).to_bytes(2, "big"))
                fingerprint.update(bytes(attribute.value))
        database_state = int.from_bytes(fingerprint.digest()[:4], "big")
        records[SERVICE_RECORD_SDS] = [
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
        self.device.sdp_service_records = records
        self.logger.info(
            "A2DP SDP records installed: AudioSink(Speaker) + AVRCP Controller/Target "
            "(CoD loudspeaker); ServiceDatabaseState=0x%08x",
            database_state,
        )

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
        await self._gate("a2dp-start", self.enable_classic_visibility)
        self.listener = avdtp.Listener(avdtp.Listener.create_registrar(self.device))
        self.listener.on("connection", self.on_avdtp_connection)
        # Свой L2CAP-сервер на AVCTP PSM вместо Protocol.listen(): на каждое
        # входящее соединение — отдельная AVRCP-сессия (iPhone и колонка живут
        # одновременно, маршрутизация по trust в _on_avrcp_session_start).
        self.device.create_l2cap_server(
            l2cap.ClassicChannelSpec(avctp.AVCTP_PSM), self._on_incoming_avctp
        )
        self.logger.info(
            "A2DP bridge started: local=%s name=%s trusted_sources=%d trusted_speakers=%d; AVCTP listening",
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
            # [CLAUDE 2026-06-03] Standby ТОЛЬКО для ЧИСТЫХ колонок (role=="speaker").
            # Устройства, которые ещё и источники (Mac/iPhone — у них есть A2DP-sink возможность,
            # role=="device"/"source"), НЕ авто-звоним как колонку — иначе HCI_AUTHENTICATION
            # failure спамом (они не в pairing-режиме приёмника). Их аудио идёт через свой маршрут.
            if speaker.get("role") != "speaker":
                continue
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
            # [CLAUDE 2026-06-02] Постоянный standby = УДЕРЖАННЫЙ A2DP-коннект (AVDTP open+start),
            # не только ACL. Без открытого медиаканала колонка (Fosi) видит «пустой» ACL, роняет его
            # и висит в режиме пары. request_receiver_connection открывает и держит A2DP-поток ->
            # колонка выходит из пары и горит «подключено». RTP не форвардится, пока нет источника —
            # канал просто живёт в фоне. Идемпотентно: если уже held на этот адрес — no-op.
            _, not_before = self._speaker_backoff.get(address, (0, 0.0))
            if asyncio.get_running_loop().time() < not_before:
                continue
            await self.request_receiver_connection(address)

    async def enable_classic_visibility(self):
        # Connectable always (bonded peers reconnect, incoming A2DP works), but
        # NOT discoverable by default — discovery is opened only in pairing mode.
        self.device.class_of_device = COD_AUDIO_LOUDSPEAKER
        await self.device.host.send_command(
            HCI_Write_Class_Of_Device_Command(class_of_device=COD_AUDIO_LOUDSPEAKER),
            check_result=True,
        )
        try:
            response = await self.device.host.send_command(HCI_Read_Class_Of_Device_Command())
            actual_cod = getattr(getattr(response, "return_parameters", response), "class_of_device", None)
            self.logger.info("A2DP classic CoD active: 0x%06x", int(actual_cod))
        except Exception as exc:
            self.logger.warning("A2DP classic CoD readback failed: %s", error_text(exc))
        inquiry_items = [
            (
                AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                BT_AUDIO_SINK_UUID16.to_bytes(2, "little")
                + BT_AV_REMOTE_CONTROL_TARGET_UUID16.to_bytes(2, "little")
                + BT_AV_REMOTE_CONTROL_UUID16.to_bytes(2, "little")
                + BT_AV_REMOTE_CONTROL_CONTROLLER_UUID16.to_bytes(2, "little"),
            ),
            (AdvertisingData.COMPLETE_LOCAL_NAME, self.bt_name.encode("utf-8")),
        ]
        if os.environ.get("CARTHING_IAP2_ENABLE") == "1":
            inquiry_items.insert(
                1,
                (
                    AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                    IAP2_UUID128.to_bytes(),
                ),
            )
        self.device.inquiry_response = bytes(AdvertisingData(inquiry_items))
        await self._request_visibility(connectable=True, discoverable=False)
        self.logger.info("A2DP classic connectable (not discoverable) enabled")

    async def enter_pairing(self):
        """Pairing mode: become classic-discoverable (so a phone can add us as an
        audio output) and scan for trusted speakers to add as transfer targets."""
        await self._request_visibility(connectable=True, discoverable=True)
        self.logger.info("A2DP classic discoverable ON (pairing)")
        if self._scan_task is None or self._scan_task.done():
            self._scan_task = asyncio.create_task(self.scan_trusted_speakers())

    async def exit_pairing(self):
        await self._request_visibility(connectable=True, discoverable=False)
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
            await self._gate(
                "a2dp-receiver-auth",
                lambda: asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout),
            )
            await self._gate(
                "a2dp-receiver-encrypt",
                lambda: asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout),
            )
            self.logger.info("A2DP receiver link ENCRYPTED ok: %s (encrypted=%s)",
                             target_address, getattr(connection, "is_encrypted", "?"))
        except Exception as exc:
            # [CLAUDE 2026-06-02] A2DP/AVDTP требует ШИФРОВАНИЯ. Если оно не встаёт — Fosi рвёт
            # коннект (reason 0x13). Раньше ошибку глушили и шли в AVDTP по открытому линку.
            # Логируем реальную причину. Частый корень: рассинхрон link-key (колонка помнит
            # старый ключ Car Thing) -> «забыть» Car Thing на самой колонке + спарить заново.
            self.logger.warning("A2DP receiver auth/encrypt FAILED: %s: %s (encrypted=%s)",
                                 target_address, error_text(exc), getattr(connection, "is_encrypted", "?"))

        # [CLAUDE 2026-06-02] ВОССТАНОВЛЕНО (регрессия Codex): доказанный путь 2026-05-21 делал
        # SDP-запрос версии AVDTP ПЕРЕД Protocol.connect и передавал version=. Без этого Fosi
        # рвал коннект (discover endpoints -> 0x13). С SDP-версией поток доходил до A2DP_STREAMING_OK.
        try:
            version = await self._gate(
                "a2dp-receiver-sdp-version",
                lambda: asyncio.wait_for(
                    avdtp.find_avdtp_service_with_connection(self.device, connection),
                    timeout=self.connect_timeout,
                ),
            )
        except Exception as exc:
            version = None
            self.logger.info("A2DP receiver SDP version lookup ignored: %s", error_text(exc))
        version = version or (1, 2)
        self.logger.info("A2DP receiver AVDTP connect: %s version=%s", target_address, version)
        protocol = await self._gate(
            "a2dp-receiver-avdtp-connect",
            lambda: asyncio.wait_for(
                avdtp.Protocol.connect(connection, version=version),
                timeout=self.connect_timeout,
            ),
        )
        self.receiver_protocol = protocol
        self.logger.info("A2DP receiver discover endpoints: %s", target_address)
        await self._gate(
            "a2dp-receiver-discover",
            lambda: asyncio.wait_for(protocol.discover_remote_endpoints(), timeout=self.connect_timeout),
        )

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
        stream = await self._gate(
            "a2dp-receiver-create-stream",
            lambda: protocol.create_stream(source, sink),
        )
        await self._gate("a2dp-receiver-open", stream.open)
        await self._gate("a2dp-receiver-start", stream.start)

        self.receiver_source = source
        self.receiver_stream = stream
        self.receiver_rtp_channel = stream.rtp_channel
        self.receiver_address = target_address
        self.receiver_connecting_address = None
        self.state.transfer_status = "connected"
        self.state.set_connected_speaker(target_address)
        self.on_state_change()
        self.logger.info("A2DP_SPEAKER_STREAM_STARTED codec=%s seid=%s", codec_name, getattr(sink, "seid", "?"))
        # Коммутатор сам поднимает AVRCP к колонке (backchannel-кнопки, volume),
        # не дожидаясь её инициативы.
        speaker_connection = self._speaker_connections.get(target_address) or self.receiver_connection
        if speaker_connection is not None:
            asyncio.create_task(self.ensure_speaker_avrcp(speaker_connection))

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

    def _find_classic_connection(self, address):
        """[CLAUDE 2026-06-02] Найти ЖИВОЙ classic (BR/EDR) коннект к адресу среди
        device.connections — чтобы переиспользовать, а не дозваниваться вторично (раса 0xB)."""
        address = normalize_address(address)
        try:
            conns = self.device.connections
            items = conns.values() if hasattr(conns, "values") else conns
            for c in items:
                if (normalize_address(getattr(c, "peer_address", "")) == address
                        and getattr(c, "transport", None) == BT_BR_EDR_TRANSPORT):
                    return c
        except Exception:
            pass
        return None

    async def ensure_speaker_connection(self, address, require_trusted=True, strict_security=False):
        address = normalize_address(address)
        connection = self._speaker_connections.get(address)
        if connection is not None:
            if strict_security:
                await self._gate(
                    "a2dp-speaker-auth",
                    lambda: asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout),
                )
                await self._gate(
                    "a2dp-speaker-encrypt",
                    lambda: asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout),
                )
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
            # [CLAUDE 2026-06-02] Идемпотентность против расы pair_speaker <-> standby-loop:
            # если classic-линк к адресу уже есть на HCI (другой путь успел) — переиспользуем,
            # иначе device.connect отдаёт HCI_CONNECTION_ALREADY_EXISTS (0xB) и «пара не завершена».
            connection = self._find_classic_connection(address)
            if connection is not None:
                self.logger.info("A2DP speaker reuse existing classic link: %s", address)
            else:
                self.logger.info("A2DP speaker standby connect: %s", address)
                try:
                    connection = await self._gate(
                        "a2dp-speaker-connect",
                        lambda: asyncio.wait_for(
                            self.device.connect(address, transport=BT_BR_EDR_TRANSPORT),
                            timeout=self.connect_timeout,
                        ),
                    )
                except Exception as exc:
                    connection = self._find_classic_connection(address)
                    if connection is None:
                        raise
                    self.logger.info("A2DP speaker connect raced (%s) -> reuse existing: %s",
                                     error_text(exc), address)
            self._speaker_connections[address] = connection
            connection.on(
                "disconnection",
                lambda reason: asyncio.ensure_future(self.on_speaker_disconnected(address, reason)),
            )
            try:
                await self._gate(
                    "a2dp-speaker-auth",
                    lambda: asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout),
                )
                await self._gate(
                    "a2dp-speaker-encrypt",
                    lambda: asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout),
                )
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
            self._speaker_backoff.pop(address, None)
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
            failures, _ = self._speaker_backoff.get(address, (0, 0.0))
            failures = min(failures + 1, 5)
            delay = min(12.0 * (2 ** failures), 300.0)
            self._speaker_backoff[address] = (
                failures,
                asyncio.get_running_loop().time() + delay,
            )
            self.logger.warning(
                "A2DP receiver connect failed: %s (retry in %.0fs)",
                error_text(exc),
                delay,
            )

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
            await self._gate("a2dp-scan-start", lambda: self.device.start_discovery(auto_restart=False))
            try:
                await asyncio.wait_for(complete, timeout=duration)
            except Exception:
                pass
        finally:
            self.device.remove_listener("inquiry_result", on_inquiry_result)
            self.device.remove_listener("inquiry_complete", on_inquiry_complete)
            try:
                await self._gate("a2dp-scan-stop", self.device.stop_discovery)
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
                name = await self._gate("a2dp-remote-name", lambda: asyncio.wait_for(
                    self.device.request_remote_name(address), timeout=5.0))
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
        # [CLAUDE 2026-06-03] НЕ чистим список между циклами — он ЛЕНИВЫЙ/накопительный.
        # Устройства не появляются/исчезают так быстро; раз увиденное остаётся в списке.
        # Полная очистка — только при ВХОДЕ в режим сопряжения (intents._settings).
        self.on_state_change()
        self.device.on("inquiry_result", on_inquiry_result)
        self.device.on("inquiry_complete", on_inquiry_complete)
        try:
            await self._gate("a2dp-pair-scan-start", lambda: self.device.start_discovery(auto_restart=False))
            try:
                await asyncio.wait_for(complete, timeout=duration)
            except Exception:
                pass
        finally:
            self.device.remove_listener("inquiry_result", on_inquiry_result)
            self.device.remove_listener("inquiry_complete", on_inquiry_complete)
            try:
                await self._gate("a2dp-pair-scan-stop", self.device.stop_discovery)
            except Exception as exc:
                self.logger.info("A2DP pairable scan stop ignored: %s", error_text(exc))
            self.state.speaker_pairing_status = "idle"
            self.on_state_change()

    async def scan_device_capabilities(self, connection):
        """[CLAUDE 2026-06-03] МОЩНЫЙ скан возможностей: запросить SDP-записи подключённого
        устройства и собрать ВСЕ service-class UUID (профили). Возвращает набор токенов
        ('110b','110a','1812'...) -> EnrollmentManager строит богатую карточку. Best-effort:
        любая ошибка не фатальна (карточка деградирует на CoD). Идёт через единый HCI-гейт."""
        from bumble.sdp import (Client as SDPClient, SDP_PUBLIC_BROWSE_ROOT,
                                SDP_ALL_ATTRIBUTES_RANGE)
        tokens = set()

        async def _do():
            async with SDPClient(connection) as sdp:
                results = await asyncio.wait_for(
                    sdp.search_attributes([SDP_PUBLIC_BROWSE_ROOT], [SDP_ALL_ATTRIBUTES_RANGE]),
                    timeout=self.connect_timeout,
                )
                self._collect_uuid_tokens(results, tokens)

        await self._gate("a2dp-sdp-scan", _do)
        return tokens

    @staticmethod
    def _collect_uuid_tokens(node, out, depth=0):
        """Рекурсивно вытащить все UUID-токены из дерева SDP DataElement (любая вложенность)."""
        from bumble.core import UUID
        if depth > 10 or node is None:
            return
        if isinstance(node, UUID):
            try:
                out.add(node.to_hex_str().lower())
            except Exception:
                out.add(str(node).lower())
            return
        val = getattr(node, "value", None)
        if val is not None and not isinstance(val, (str, bytes, int, float, bool)):
            A2DPBridge._collect_uuid_tokens(val, out, depth + 1)
        if isinstance(node, (list, tuple)):
            for e in node:
                A2DPBridge._collect_uuid_tokens(e, out, depth + 1)

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
            await self._gate("a2dp-pair-stop-discovery", self.device.stop_discovery)
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
            connection = await self.ensure_speaker_connection(address, strict_security=True)
        except Exception:
            self.state.remove_trusted(address)
            raise
        self.state.set_speaker_connected(address, True)
        # [CLAUDE 2026-06-03] МОЩНЫЙ СКАН по SDP -> богатая карточка (протоколы/возможности).
        try:
            uuids = await self.scan_device_capabilities(connection)
            cod = (candidate or {}).get("class_of_device")
            if not uuids and not cod:
                # Этот flow парит именно колонку (candidate.audio проверен выше), а
                # SDP-скан мог не пробиться через занятое радио. Без этого минимума
                # enrollment даёт role="device" → standby-цикл колонку НЕ звонит →
                # Fosi после рестарта виснет в режиме пары.
                uuids = {"audio_sink"}
            self.state.enroll_trusted_device(address, name=label,
                                             class_of_device=cod, service_uuids=uuids)
            self.logger.info("device card enriched: %s -> %s", address, sorted(uuids))
        except Exception as exc:
            self.logger.info("capability scan skipped (card stays on CoD): %s", error_text(exc))
        # [CLAUDE 2026-06-03] ACL+encrypt мало: Fosi видит «пустой» ACL и ВИСИТ В РЕЖИМЕ ПАРЫ
        # (мигает), пока нет открытого медиа-транспорта. Открываем AVDTP (open+start) сразу при
        # паре — колонка выходит из пары и держится подключённой. RTP не льётся без источника,
        # канал просто живёт в фоне. Затем поднимаем standby-петлю, чтобы держать/реконнектить
        # независимо от активации маршрута (trusted speaker «прилипает» ниже Transfer).
        try:
            await self.setup_receiver(address)
            self.logger.info("A2DP stream opened+held after pairing: %s", address)
        except Exception as exc:
            self.logger.warning("A2DP stream open after pairing failed (kept ACL): %s",
                                 error_text(exc))
        self.start_standby_loop()
        self.state.speaker_pairing_status = "done"
        self.state.pairing_message = f"{label} подключен"
        try:
            self.state.save_trusted()
        except Exception as exc:
            self.logger.warning("speaker trust save failed: %s", error_text(exc))
        self.on_state_change()

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
        connection = await self._gate(
            "a2dp-source-connect",
            lambda: asyncio.wait_for(
                self.device.connect(address, transport=BT_BR_EDR_TRANSPORT),
                timeout=self.connect_timeout,
            ),
        )
        try:
            await self._gate(
                "a2dp-source-auth",
                lambda: asyncio.wait_for(self.device.authenticate(connection), timeout=self.connect_timeout),
            )
            await self._gate(
                "a2dp-source-encrypt",
                lambda: asyncio.wait_for(self.device.encrypt(connection), timeout=self.connect_timeout),
            )
        except Exception as exc:
            self.logger.warning("A2DP source dial auth/encrypt failed: %s", error_text(exc))
            raise
        await self.handle_classic_connection(connection)
        self._source_connection = connection
        connection.on("disconnection", lambda _r: self._clear_source_connection())

        async def _enrich_source_card():
            try:
                capabilities = await self.scan_device_capabilities(connection)
                self.logger.info("A2DP source peer SDP UUIDs: %s", sorted(capabilities))
            except Exception as exc:
                self.logger.info("A2DP source peer SDP scan ignored: %s", error_text(exc))

        # Диагностический SDP-скан карточки — НЕ на горячем пути включения
        # маршрута (жалоба владельца: тумблер «вкл» тянет ~2 лишних секунды).
        # AVRCP остаётся синхронным: iOS требует его для публикации выхода.
        asyncio.create_task(_enrich_source_card())
        await self.ensure_source_avrcp(connection)
        self.logger.info("A2DP_SOURCE_CLASSIC_DIALED %s", address)
        return connection

    def _make_avrcp_session(self, address: str) -> avrcp.Protocol:
        """Отдельный AVRCP Protocol на пира; маршрутизация по trust на старте сессии."""
        delegate = AudioSinkAvrcpDelegate(
            self.logger,
            peer=address,
            on_key=self._on_avrcp_key,
            on_volume=self._on_source_volume,
        )
        protocol = avrcp.Protocol(delegate)
        self.avrcp_sessions[address] = protocol
        protocol.on(
            protocol.EVENT_START,
            lambda: self._on_avrcp_session_start(address, protocol),
        )
        protocol.on(
            protocol.EVENT_STOP,
            lambda: self._on_avrcp_session_stop(address, protocol),
        )
        return protocol

    def _on_incoming_avctp(self, l2cap_channel):
        try:
            address = normalize_address(str(l2cap_channel.connection.peer_address))
        except Exception:
            address = "?"
        self.logger.info("AVCTP incoming connection from %s", address)
        protocol = self._make_avrcp_session(address)
        l2cap_channel.on(
            l2cap_channel.EVENT_OPEN,
            lambda: protocol._on_avctp_channel_open(l2cap_channel),
        )

    def _on_avrcp_session_start(self, address, protocol):
        self.logger.info("AVRCP session started with peer=%s", address)
        if self.state.is_trusted_source(address):
            self._source_avrcp = protocol
            self._source_avrcp_addr = address
            asyncio.create_task(self._start_source_avrcp_session())
        elif self.state.is_trusted_speaker(address):
            self.logger.info("AVRCP speaker backchannel armed: %s", address)
            asyncio.create_task(self._start_speaker_avrcp_session(address, protocol))

    async def _start_speaker_avrcp_session(self, address, protocol):
        """Подписка на нотификации колонки: громкость по AVRCP идёт не кнопками,
        а EVENT_VOLUME_CHANGED от Target — Controller обязан зарегистрироваться."""
        try:
            supported_events = await asyncio.wait_for(
                protocol.get_supported_events(),
                timeout=self.connect_timeout,
            )
            self.logger.info(
                "AVRCP speaker supported events peer=%s: %s",
                address,
                [event.name for event in supported_events],
            )
        except Exception as exc:
            self.logger.info(
                "AVRCP speaker capabilities query failed (%s): %s",
                address,
                error_text(exc),
            )
            return
        monitors = (
            # VOLUME_CHANGED регистрируем ПРИНУДИТЕЛЬНО, игнорируя capabilities:
            # часть колонок не заявляет событие, но репортит его после первого
            # SetAbsoluteVolume. Отказ безвреден (монитор просто остановится).
            (avrcp.EventId.VOLUME_CHANGED, protocol.monitor_volume, "volume", True),
            (
                avrcp.EventId.PLAYBACK_STATUS_CHANGED,
                protocol.monitor_playback_status,
                "playback-status",
                False,
            ),
        )
        for event_id, monitor, label, force in monitors:
            if not force and event_id not in supported_events:
                continue
            task = asyncio.create_task(
                self._consume_speaker_avrcp_monitor(address, label, monitor())
            )
            self._avrcp_monitor_tasks.add(task)
            task.add_done_callback(self._avrcp_monitor_tasks.discard)

    def _on_speaker_volume(self, volume, address):
        """Громкость от колонки -> VOLUME_CHANGED-нотификация источнику (iPhone).

        Начальное (interim) значение при регистрации — НЕ действие пользователя,
        а сохранённое состояние колонки. Его не форвардим (иначе при коннекте
        старая громкость колонки залпом затирает громкость iPhone — наблюдалось:
        50% → 93). Источник — хозяин громкости маршрута: наоборот, выравниваем
        колонку под известную громкость маршрута.
        """
        if address not in self._speaker_volume_seen:
            self._speaker_volume_seen.add(address)
            if self._route_volume is not None and self._route_volume != volume:
                self._pending_speaker_volume = self._route_volume
                if self._speaker_volume_task is None or self._speaker_volume_task.done():
                    self._speaker_volume_task = asyncio.create_task(
                        self._push_speaker_volume(address)
                    )
            return
        if volume == self._route_volume:
            return  # эхо нашего SetAbsoluteVolume
        self._route_volume = volume
        protocol = self._source_avrcp
        if protocol is None:
            return
        try:
            delegate = getattr(protocol, "delegate", None)
            if delegate is not None:
                delegate.volume = volume
            protocol.notify_volume_changed(volume)
            self.logger.info(
                "route volume %d: speaker %s -> source notify", volume, address
            )
        except Exception as exc:
            self.logger.info("route volume notify failed: %s", error_text(exc))

    async def _consume_speaker_avrcp_monitor(self, address, label, events):
        try:
            async for value in events:
                self.logger.info(
                    "AVRCP speaker %s=%s peer=%s", label, value, address
                )
                if label == "volume":
                    try:
                        self._on_speaker_volume(int(value), address)
                    except Exception as exc:
                        self.logger.info(
                            "speaker volume route failed: %s", error_text(exc)
                        )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.info(
                "AVRCP speaker %s monitor stopped (%s): %s",
                label,
                address,
                error_text(exc),
            )

    def _on_avrcp_session_stop(self, address, protocol):
        if self.avrcp_sessions.get(address) is protocol:
            self.avrcp_sessions.pop(address, None)
        # Новая сессия колонки снова начнётся с interim-значения — съесть заново.
        self._speaker_volume_seen.discard(address)
        if self._source_avrcp is protocol:
            self._source_avrcp = None
            self._stop_source_avrcp_session()

    def _on_source_volume(self, volume, peer):
        """Absolute volume от источника -> SetAbsoluteVolume на колонку (коалесцируя)."""
        if not self.state.is_trusted_source(peer):
            return
        if volume == self._route_volume:
            return  # эхо нашей же VOLUME_CHANGED-нотификации
        self._route_volume = volume
        # Громкость идёт колонке АКТИВНОГО маршрута; default_speaker из реестра —
        # только фолбэк (там первым может стоять виртуальный выход с пустым адресом).
        speaker = normalize_address(
            self.receiver_address or self.state.default_speaker_address()
        )
        if not speaker or speaker in self._speaker_volume_unsupported:
            return
        self._pending_speaker_volume = volume
        if self._speaker_volume_task is None or self._speaker_volume_task.done():
            self._speaker_volume_task = asyncio.create_task(
                self._push_speaker_volume(speaker)
            )

    async def _push_speaker_volume(self, speaker):
        while True:
            volume = self._pending_speaker_volume
            if not await self.set_speaker_absolute_volume(speaker, volume):
                return
            await asyncio.sleep(0.2)
            if self._pending_speaker_volume == volume:
                return

    async def set_speaker_absolute_volume(self, address, volume):
        protocol = self.avrcp_sessions.get(address)
        if protocol is None or protocol.avctp_protocol is None:
            return False
        try:
            response_context = await asyncio.wait_for(
                protocol.send_avrcp_command(
                    avc.CommandFrame.CommandType.CONTROL,
                    avrcp.SetAbsoluteVolumeCommand(volume=volume),
                ),
                timeout=5.0,
            )
            # Для CONTROL-команд код успеха = ACCEPTED (Protocol._check_response
            # из Bumble ждёт IMPLEMENTED_OR_STABLE и годится только для STATUS).
            code = getattr(response_context, "response_code", None)
            response = getattr(response_context, "response", None)
            if code != avc.ResponseFrame.ResponseCode.ACCEPTED or not isinstance(
                response, avrcp.SetAbsoluteVolumeResponse
            ):
                raise RuntimeError(f"unexpected response: {response_context}")
            self.logger.info(
                "AVRCP speaker absolute volume set=%d effective=%s peer=%s",
                volume,
                response.volume,
                address,
            )
            return True
        except Exception as exc:
            self._speaker_volume_unsupported.add(address)
            self.logger.info(
                "AVRCP speaker absolute volume unsupported (%s): %s",
                address,
                error_text(exc),
            )
            return False

    async def _on_avrcp_key(self, key, pressed, peer):
        """Транспортные кнопки колонки -> backchannel -> активный источник."""
        if not pressed or self.speaker_command_handler is None:
            return
        if not self.state.is_trusted_speaker(peer):
            return
        command = getattr(key, "name", str(key)).lower()
        try:
            await self.speaker_command_handler(peer, command)
        except Exception as exc:
            self.logger.warning("speaker backchannel command failed: %s", error_text(exc))

    async def ensure_source_avrcp(self, connection):
        """Open the control profile on an existing bonded Classic ACL."""
        address = normalize_address(str(connection.peer_address))
        existing = self.avrcp_sessions.get(address)
        if existing is not None and existing.avctp_protocol is not None:
            self.logger.info("A2DP source AVCTP/AVRCP already connected: %s", address)
            return
        try:
            protocol = self._make_avrcp_session(address)
            await self._gate(
                "a2dp-source-avrcp-connect",
                lambda: asyncio.wait_for(
                    protocol.connect(connection), timeout=self.connect_timeout
                ),
            )
            self.logger.info("A2DP source AVCTP/AVRCP connected peer=%s", address)
        except Exception as exc:
            self.logger.warning("A2DP source AVCTP/AVRCP connect failed: %s", error_text(exc))

    async def ensure_speaker_avrcp(self, connection):
        """Поднять AVRCP к колонке: канал для её кнопок и будущего volume-контроля.

        Fosi открывает AVCTP сам через ~0.2 c после старта аудиоканала; встречный
        одновременный connect даёт L2CAP-коллизию (mode mismatch, run11). Даём
        пиру право первой инициативы и звоним только если он промолчал.
        """
        address = normalize_address(str(connection.peer_address))
        await asyncio.sleep(3.0)
        existing = self.avrcp_sessions.get(address)
        if existing is not None and existing.avctp_protocol is not None:
            return
        try:
            protocol = self._make_avrcp_session(address)
            await self._gate(
                "a2dp-speaker-avrcp-connect",
                lambda: asyncio.wait_for(
                    protocol.connect(connection), timeout=self.connect_timeout
                ),
            )
            self.logger.info("A2DP speaker AVCTP/AVRCP connected peer=%s", address)
        except Exception as exc:
            # У колонки может не быть AVRCP CT — это не ошибка маршрута.
            self.logger.info(
                "A2DP speaker AVRCP unavailable (%s): %s", address, error_text(exc)
            )

    async def _start_source_avrcp_session(self):
        """Register the audio sink for the source's AVRCP notifications."""
        protocol = self._source_avrcp
        if protocol is None:
            return
        self._stop_source_avrcp_session()
        try:
            supported_events = await asyncio.wait_for(
                protocol.get_supported_events(),
                timeout=self.connect_timeout,
            )
            self.logger.info(
                "AVRCP source supported events: %s",
                [event.name for event in supported_events],
            )
        except Exception as exc:
            self.logger.warning("AVRCP source capabilities query failed: %s", error_text(exc))
            return

        monitors = (
            (
                avrcp.EventId.PLAYBACK_STATUS_CHANGED,
                protocol.monitor_playback_status,
                "playback-status",
            ),
            (
                avrcp.EventId.VOLUME_CHANGED,
                protocol.monitor_volume,
                "volume",
            ),
        )
        for event_id, monitor, label in monitors:
            if event_id not in supported_events:
                continue
            task = asyncio.create_task(self._consume_avrcp_monitor(label, monitor()))
            self._avrcp_monitor_tasks.add(task)
            task.add_done_callback(self._avrcp_monitor_tasks.discard)

    async def _consume_avrcp_monitor(self, label, events):
        try:
            async for value in events:
                self.logger.info(
                    "AVRCP source %s=%s peer=%s", label, value, self._source_avrcp_addr
                )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.logger.warning("AVRCP source %s monitor stopped: %s", label, error_text(exc))

    def _stop_source_avrcp_session(self):
        for task in self._avrcp_monitor_tasks:
            task.cancel()
        self._avrcp_monitor_tasks.clear()

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
        # Сначала вежливо закрыть AVDTP-сигналинг: по спецификации это teardown
        # всех потоков, и iOS переключает звук сразу. Голый обрыв ACL iOS трактует
        # как «вышел из радиуса» и держит маршрут до своих таймаутов (жалоба
        # владельца: долгое переключение на динамик iPhone).
        protocol = getattr(self, "_source_avdtp", None)
        if protocol is not None:
            try:
                await asyncio.wait_for(protocol.l2cap_channel.disconnect(), timeout=2.0)
                self.logger.info("A2DP source AVDTP signaling closed gracefully")
                await asyncio.sleep(0.3)
            except Exception as exc:
                self.logger.info("A2DP source AVDTP close ignored: %s", error_text(exc))
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
        # Храним сигналинг источника: при disconnect_source закрываем его ПЕРВЫМ,
        # чтобы iOS мгновенно понял «поток завершён» и переключил звук без таймаутов.
        self._source_avdtp = protocol

        def _clear_source_avdtp():
            if getattr(self, "_source_avdtp", None) is protocol:
                self._source_avdtp = None

        protocol.l2cap_channel.on(
            protocol.l2cap_channel.EVENT_CLOSE, _clear_source_avdtp
        )
        # SBC-only is the mandatory A2DP interoperability baseline. Keep it as
        # an isolated lab switch so optional AAC cannot obscure route failures.
        baseline = os.environ.get("CARTHING_A2DP_SINK_BASELINE") == "1"
        if not baseline:
            self._install_source_sink(protocol, peer_address, "AAC", make_aac_capabilities())
        self._install_source_sink(protocol, peer_address, "SBC", make_sbc_capabilities())
        self.logger.info(
            "A2DP source endpoint profile=%s",
            "SBC-only baseline" if baseline else "AAC+SBC",
        )

    def _install_source_sink(self, protocol, peer_address, codec_name, capabilities):
        sink = protocol.add_sink(capabilities)
        sink.capabilities.append(
            avdtp.ServiceCapabilities(avdtp.AVDTP_DELAY_REPORTING_SERVICE_CATEGORY)
        )
        original_set_configuration = sink.on_set_configuration_command
        original_start = sink.on_start_command
        original_open = sink.on_open_command
        original_suspend = sink.on_suspend_command
        original_close = sink.on_close_command
        original_abort = sink.on_abort_command

        def on_set_configuration(configuration):
            self.logger.info("A2DP_SOURCE_SET_CONFIGURATION codec=%s %s", codec_name, configuration)
            return original_set_configuration(configuration)

        def on_open():
            self.logger.info("A2DP_SOURCE_OPEN codec=%s", codec_name)
            asyncio.create_task(self._send_source_delay_report(protocol, sink, codec_name))
            return original_open()

        def on_start():
            self.logger.info("A2DP_SOURCE_START codec=%s", codec_name)
            self.source_stream_active = True
            self.state.transfer_active = True
            self.state.transfer_source = normalize_address(peer_address)
            self.state.active_desktop = self.state.TRANSFER
            self.on_state_change()
            asyncio.create_task(self.request_receiver_for_active_source())
            return original_start()

        def on_suspend():
            self.logger.info("A2DP_SOURCE_SUSPEND codec=%s", codec_name)
            self.source_stream_active = False
            # ПАУЗА ≠ teardown маршрута (INVARIANTS п.3): канал к колонке держим
            # открытым (opened+held). Teardown на suspend ломал resume: Fosi
            # отвечал L2CAP 0x4 (no resources) на пересоздание AVDTP, труба
            # после паузы не восстанавливалась. Закрываем только на CLOSE/ABORT.
            return original_suspend()

        def on_close():
            self.logger.info("A2DP_SOURCE_CLOSE codec=%s", codec_name)
            self.source_stream_active = False
            # Поток источника закрыт -> маршрут больше не активен.
            self.state.transfer_active = False
            self.state.transfer_source = ""
            asyncio.create_task(self.stop_receiver_stream())
            return original_close()

        def on_abort():
            self.logger.info("A2DP_SOURCE_ABORT codec=%s", codec_name)
            self.source_stream_active = False
            self.state.transfer_active = False
            self.state.transfer_source = ""
            asyncio.create_task(self.stop_receiver_stream())
            return original_abort()

        sink.on_set_configuration_command = on_set_configuration
        sink.on_open_command = on_open
        sink.on_start_command = on_start
        sink.on_suspend_command = on_suspend
        sink.on_close_command = on_close
        sink.on_abort_command = on_abort
        sink.on("rtp_packet", self.forward_packet)
        sink.on(
            sink.EVENT_RTP_CHANNEL_OPEN,
            lambda: self.logger.info("A2DP_SOURCE_RTP_OPEN codec=%s", codec_name),
        )
        sink.on(
            sink.EVENT_RTP_CHANNEL_CLOSE,
            lambda: self.logger.info("A2DP_SOURCE_RTP_CLOSE codec=%s", codec_name),
        )
        self.logger.info("A2DP source sink endpoint installed: codec=%s seid=%s", codec_name, sink.seid)

    async def _send_source_delay_report(self, protocol, sink, codec_name):
        await asyncio.sleep(0.2)
        stream = getattr(sink, "stream", None)
        remote_endpoint = getattr(stream, "remote_endpoint", None)
        remote_seid = getattr(remote_endpoint, "seid", None)
        if remote_seid is None:
            self.logger.info("A2DP delay report skipped: codec=%s remote-seid unavailable", codec_name)
            return
        try:
            await asyncio.wait_for(
                protocol.send_command(
                    avdtp.DelayReport_Command(
                        acp_seid=remote_seid,
                        delay=A2DP_SINK_DELAY_REPORT,
                    )
                ),
                timeout=self.connect_timeout,
            )
            self.logger.info(
                "A2DP delay report accepted: codec=%s delay=%d",
                codec_name,
                A2DP_SINK_DELAY_REPORT,
            )
        except Exception as exc:
            # A2DP permits a Source to omit Delay Reporting support.
            self.logger.info("A2DP delay report ignored by source: %s", error_text(exc))

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
        # Свежий дисконнект = новая попытка без штрафа (колонку могли включить).
        self._speaker_backoff.pop(address, None)
        self.state.set_speaker_online(address, False)
        self.state.set_speaker_connected(address, False)
        if self.receiver_address == address:
            await self.on_receiver_disconnected(reason)
        else:
            self.on_state_change()
