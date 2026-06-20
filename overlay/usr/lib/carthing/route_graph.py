"""Route graph primitives for the Car Thing media router.

This module is intentionally pure data. It is the contract between device
enrollment, link management, GUI route selection, and protocol adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Capability(str, Enum):
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
    SESSION_PEER = "session_peer"
    REMOTE_MIC_RECEIVER = "remote_mic_receiver"
    LOCAL_MIC_SOURCE = "local_mic_source"
    USB_PEER = "usb_peer"
    USB_SESSION = "usb_session"
    USB_AUDIO = "usb_audio"
    PLAYNOW_METADATA = "playnow_metadata"
    CONTROL_INPUT = "control_input"
    CONTROL_OUTPUT = "control_output"
    METADATA_INPUT = "metadata_input"
    METADATA_OUTPUT = "metadata_output"
    NOTIFICATIONS_INPUT = "notifications_input"
    VOLUME_CONTROL = "volume_control"
    TRANSPORT_CONTROL = "transport_control"


class EndpointDirection(str, Enum):
    """Data-flow direction.

    Direction is deliberately binary. Domain meaning lives in EndpointPlane and
    capabilities; legacy input/output/control/session strings are normalized at
    load boundaries.
    """

    SOURCE = "source"
    SINK = "sink"


class EndpointPlane(str, Enum):
    AUDIO = "audio"
    CONTROL = "control"
    METADATA = "metadata"
    SESSION = "session"
    MIC = "mic"
    USB = "usb"


class Protocol(str, Enum):
    BLE_GATT_BOOTSTRAP = "ble_gatt_bootstrap"
    BLE_L2CAP_COC_SESSION = "ble_l2cap_coc_session"
    BLE_AMS = "ble_ams"
    BLE_ANCS = "ble_ancs"
    BLE_CTS = "ble_cts"
    BLE_HID = "ble_hid"
    BLE_LE_AUDIO_SINK = "ble_le_audio_sink"
    BLE_LE_AUDIO_SOURCE = "ble_le_audio_source"
    BLE_ASHA_AUDIO = "ble_asha_audio"
    CLASSIC_A2DP_SINK = "classic_a2dp_sink"
    CLASSIC_A2DP_SOURCE = "classic_a2dp_source"
    CLASSIC_AVRCP = "classic_avrcp"
    USB_NCM_SESSION = "usb_ncm_session"
    USB_AUDIO_IN = "usb_audio_in"
    USB_AUDIO_OUT = "usb_audio_out"
    UI_CONTROL = "ui_control"
    LOCAL_MIC = "local_mic"
    PLAYNOW_UI = "playnow_ui"


class Constraint(str, Enum):
    IDLE_LINK_ALLOWED = "idle_link_allowed"
    ACTIVE_MEDIA_REQUIRES_ROUTE = "active_media_requires_route"
    REQUIRES_STOP_BEFORE_START = "requires_stop_before_start"
    FULL_DUPLEX_ALLOWED = "full_duplex_allowed"
    FULL_DUPLEX_FORBIDDEN = "full_duplex_forbidden"
    CONTROL_BACKCHANNEL_ONLY = "control_backchannel_only"
    EXCLUSIVE_HCI = "exclusive_resource:hci0"
    EXCLUSIVE_A2DP_SOURCE = "exclusive_profile:a2dp_source"
    EXCLUSIVE_A2DP_SINK = "exclusive_profile:a2dp_sink"


@dataclass(slots=True)
class Endpoint:
    id: str
    direction: EndpointDirection
    plane: EndpointPlane = EndpointPlane.AUDIO
    protocols: set[Protocol] = field(default_factory=set)
    capabilities: set[Capability] = field(default_factory=set)
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.direction = coerce_endpoint_direction(self.direction, self.capabilities)
        self.plane = coerce_endpoint_plane(self.plane, self.capabilities, self.protocols)

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities

    @property
    def ref(self) -> str:
        return str(self.metadata.get("ref") or self.id)

    @property
    def is_source(self) -> bool:
        return self.direction == EndpointDirection.SOURCE

    @property
    def is_sink(self) -> bool:
        return self.direction == EndpointDirection.SINK


@dataclass(slots=True)
class TrustedDevice:
    id: str
    address: str
    name: str
    capabilities: set[Capability] = field(default_factory=set)
    endpoints: list[Endpoint] = field(default_factory=list)
    constraints: set[Constraint | str] = field(default_factory=set)
    trusted: bool = True
    online: bool = False
    connected: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def endpoint(self, endpoint_id: str) -> Endpoint | None:
        for endpoint in self.endpoints:
            if endpoint.id == endpoint_id:
                return endpoint
        return None

    def source_endpoints(self, capability: Capability | None = None, plane: EndpointPlane | None = None) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.direction == EndpointDirection.SOURCE
            and (capability is None or endpoint.supports(capability))
            and (plane is None or endpoint.plane == plane)
        ]

    def sink_endpoints(self, capability: Capability | None = None, plane: EndpointPlane | None = None) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.direction == EndpointDirection.SINK
            and (capability is None or endpoint.supports(capability))
            and (plane is None or endpoint.plane == plane)
        ]

    def input_endpoints(self) -> list[Endpoint]:
        return self.source_endpoints(Capability.AUDIO_INPUT, EndpointPlane.AUDIO)

    def output_endpoints(self) -> list[Endpoint]:
        return self.sink_endpoints(Capability.AUDIO_OUTPUT, EndpointPlane.AUDIO)

    def control_endpoints(self) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.plane == EndpointPlane.CONTROL
        ]


@dataclass(slots=True)
class Route:
    source_device_id: str
    source_endpoint_id: str
    sink_device_id: str
    sink_endpoint_id: str
    control_backchannel: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def source_ref(self) -> str:
        return f"{self.source_device_id}:{self.source_endpoint_id}"

    @property
    def sink_ref(self) -> str:
        return f"{self.sink_device_id}:{self.sink_endpoint_id}"

    # Compatibility aliases for older runtime/UI readers.
    @property
    def input_device_id(self) -> str:
        return self.source_device_id

    @property
    def input_endpoint_id(self) -> str:
        return self.source_endpoint_id

    @property
    def output_device_id(self) -> str:
        return self.sink_device_id

    @property
    def output_endpoint_id(self) -> str:
        return self.sink_endpoint_id


@dataclass(slots=True)
class PlannedSession:
    name: str
    routes: list[Route] = field(default_factory=list)
    required_protocols: set[Protocol] = field(default_factory=set)
    constraints: set[Constraint | str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)


def coerce_endpoint_direction(value, capabilities=None) -> EndpointDirection:
    text = value.value if hasattr(value, "value") else str(value or "").strip().lower()
    if text in {"source", "src"}:
        return EndpointDirection.SOURCE
    if text in {"sink", "dst", "destination"}:
        return EndpointDirection.SINK
    if text == "input":
        return EndpointDirection.SOURCE
    if text == "output":
        return EndpointDirection.SINK
    caps = {
        item.value if hasattr(item, "value") else str(item)
        for item in (capabilities or [])
    }
    if caps & {"audio_output", "remote_mic_receiver", "control_input", "metadata_input", "playnow_metadata"}:
        return EndpointDirection.SINK
    return EndpointDirection.SOURCE


def coerce_endpoint_plane(value, capabilities=None, protocols=None) -> EndpointPlane:
    text = value.value if hasattr(value, "value") else str(value or "").strip().lower()
    if text in {item.value for item in EndpointPlane}:
        return EndpointPlane(text)
    caps = {
        item.value if hasattr(item, "value") else str(item)
        for item in (capabilities or [])
    }
    protos = {
        item.value if hasattr(item, "value") else str(item)
        for item in (protocols or [])
    }
    if caps & {"remote_mic_receiver", "local_mic_source"}:
        return EndpointPlane.MIC
    if caps & {"usb_peer", "usb_session", "usb_audio"} or any(proto.startswith("usb_") for proto in protos):
        return EndpointPlane.USB
    if caps & {"session_peer"} or "ble_l2cap_coc_session" in protos:
        return EndpointPlane.SESSION
    if caps & {"control_input", "control_output", "volume_control", "transport_control"}:
        return EndpointPlane.CONTROL
    if caps & {"metadata_input", "metadata_output", "notifications_input", "playnow_metadata"}:
        return EndpointPlane.METADATA
    return EndpointPlane.AUDIO
