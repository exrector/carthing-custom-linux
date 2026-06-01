"""Virtual sockets/plugs/cables for the Car Thing userspace router.

Protocol adapters expose sockets. Trusted device endpoints expose plugs. The
session runner connects compatible plugs and sockets as cables. This keeps
Bumble/HCI/USB as low-level connectors instead of product-level owners.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from route_graph import Capability, Constraint, Protocol


class SocketKind(str, Enum):
    AUDIO_INPUT = "audio_input"
    AUDIO_OUTPUT = "audio_output"
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

