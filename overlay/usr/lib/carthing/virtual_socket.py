"""Virtual sockets/plugs/cables for the Car Thing userspace router.

Protocol adapters expose sockets. Trusted device endpoints expose plugs. The
session runner connects compatible plugs and sockets as cables. This keeps
Bumble/HCI/USB as low-level connectors instead of product-level owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from route_graph import Capability, Constraint, Endpoint, EndpointDirection, Protocol, TrustedDevice


class SocketKind(str, Enum):
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
    SESSION = "session"
    REMOTE_MIC = "remote_mic"
    CONTROL_INPUT = "control_input"
    CONTROL_OUTPUT = "control_output"
    METADATA_INPUT = "metadata_input"
    NOTIFICATION_INPUT = "notification_input"


@dataclass(slots=True)
class VirtualSocket:
    id: str
    owner: str
    kind: SocketKind
    protocols: set[Protocol] = field(default_factory=set)
    capabilities: set[Capability] = field(default_factory=set)
    constraints: set[Constraint | str] = field(default_factory=set)
    occupied_by: str | None = None
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def available(self) -> bool:
        return self.occupied_by is None

    def accepts(self, plug: "VirtualPlug") -> bool:
        if not self.available:
            return False
        if self.protocols and plug.protocols and not (self.protocols & plug.protocols):
            return False
        if self.capabilities and plug.capabilities and not (self.capabilities & plug.capabilities):
            return False
        return True


@dataclass(slots=True)
class VirtualPlug:
    id: str
    device_id: str
    kind: SocketKind
    protocols: set[Protocol] = field(default_factory=set)
    capabilities: set[Capability] = field(default_factory=set)
    constraints: set[Constraint | str] = field(default_factory=set)
    label: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Cable:
    id: str
    plug_id: str
    socket_id: str
    protocols: set[Protocol] = field(default_factory=set)
    active: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class VirtualPatchBay:
    def __init__(self):
        self.sockets: dict[str, VirtualSocket] = {}
        self.plugs: dict[str, VirtualPlug] = {}
        self.cables: dict[str, Cable] = {}

    def add_socket(self, socket: VirtualSocket):
        self.sockets[socket.id] = socket

    def add_plug(self, plug: VirtualPlug):
        self.plugs[plug.id] = plug

    def connect(self, plug_id: str, socket_id: str) -> Cable:
        plug = self.plugs[plug_id]
        socket = self.sockets[socket_id]
        if plug.kind != socket.kind:
            raise ValueError(f"plug/socket kind mismatch: {plug.kind} -> {socket.kind}")
        if not socket.accepts(plug):
            raise ValueError(f"socket does not accept plug: {plug_id} -> {socket_id}")
        previous_cable = self.cables.get(socket.occupied_by) if socket.occupied_by else None
        if previous_cable is not None:
            self.disconnect(previous_cable.id)
        for cable_id, cable in list(self.cables.items()):
            if cable.plug_id == plug_id:
                self.disconnect(cable_id)
        cable_id = f"{plug_id}->{socket_id}"
        cable = Cable(
            id=cable_id,
            plug_id=plug_id,
            socket_id=socket_id,
            protocols=plug.protocols & socket.protocols if socket.protocols else set(plug.protocols),
            active=True,
        )
        socket.occupied_by = cable_id
        self.cables[cable_id] = cable
        return cable

    def disconnect(self, cable_id: str):
        cable = self.cables.pop(cable_id, None)
        if cable is None:
            return
        socket = self.sockets.get(cable.socket_id)
        if socket is not None and socket.occupied_by == cable_id:
            socket.occupied_by = None
        cable.active = False

    def disconnect_all(self):
        for cable_id in list(self.cables):
            self.disconnect(cable_id)


def _socket_kind_for_endpoint(endpoint: Endpoint) -> SocketKind:
    capabilities = set(endpoint.capabilities)
    protocols = set(endpoint.protocols)
    if Capability.REMOTE_MIC_RECEIVER in capabilities:
        return SocketKind.REMOTE_MIC
    if Capability.SESSION_PEER in capabilities or (
        endpoint.direction == EndpointDirection.SESSION
        and Protocol.BLE_L2CAP_COC_SESSION in protocols
    ):
        return SocketKind.SESSION
    if Capability.AUDIO_INPUT in capabilities or (
        endpoint.direction == EndpointDirection.INPUT and Protocol.CLASSIC_A2DP_SINK in protocols
    ):
        return SocketKind.AUDIO_INPUT
    if Capability.AUDIO_OUTPUT in capabilities or (
        endpoint.direction == EndpointDirection.OUTPUT and Protocol.CLASSIC_A2DP_SOURCE in protocols
    ):
        return SocketKind.AUDIO_OUTPUT
    if Capability.CONTROL_OUTPUT in capabilities:
        return SocketKind.CONTROL_OUTPUT
    if Capability.CONTROL_INPUT in capabilities:
        return SocketKind.CONTROL_INPUT
    if Capability.NOTIFICATIONS_INPUT in capabilities:
        return SocketKind.NOTIFICATION_INPUT
    return SocketKind.METADATA_INPUT


def device_plugs(device: TrustedDevice) -> list[VirtualPlug]:
    plugs: list[VirtualPlug] = []
    for endpoint in device.endpoints:
        plugs.append(VirtualPlug(
            id=f"{device.id}:{endpoint.id}",
            device_id=device.id,
            kind=_socket_kind_for_endpoint(endpoint),
            protocols=set(endpoint.protocols),
            capabilities=set(endpoint.capabilities),
            label=endpoint.label or device.name,
            metadata={
                "device_name": device.name,
                "endpoint_id": endpoint.id,
                "endpoint_direction": endpoint.direction.value,
            },
        ))
    return plugs
