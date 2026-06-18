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
    USB_PEER = "usb_peer"
    CONTROL_INPUT = "control_input"
    CONTROL_OUTPUT = "control_output"
    METADATA_INPUT = "metadata_input"
    NOTIFICATIONS_INPUT = "notifications_input"
    VOLUME_CONTROL = "volume_control"
    TRANSPORT_CONTROL = "transport_control"


class EndpointDirection(str, Enum):
    INPUT = "input"
    OUTPUT = "output"
    SESSION = "session"
    CONTROL = "control"
    METADATA = "metadata"


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
    protocols: set[Protocol] = field(default_factory=set)
    capabilities: set[Capability] = field(default_factory=set)
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def supports(self, capability: Capability) -> bool:
        return capability in self.capabilities


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

    def input_endpoints(self) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.direction == EndpointDirection.INPUT
        ]

    def output_endpoints(self) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.direction == EndpointDirection.OUTPUT
        ]

    def control_endpoints(self) -> list[Endpoint]:
        return [
            endpoint for endpoint in self.endpoints
            if endpoint.direction == EndpointDirection.CONTROL
        ]


@dataclass(slots=True)
class Route:
    input_device_id: str
    input_endpoint_id: str
    output_device_id: str
    output_endpoint_id: str
    control_backchannel: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PlannedSession:
    name: str
    routes: list[Route] = field(default_factory=list)
    required_protocols: set[Protocol] = field(default_factory=set)
    constraints: set[Constraint | str] = field(default_factory=set)
    warnings: list[str] = field(default_factory=list)
