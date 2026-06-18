"""Virtual connector routing and HCI serialization helpers."""

from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from types import SimpleNamespace

from route_graph import Capability, EndpointDirection, PlannedSession, Protocol
from virtual_socket import SocketKind, VirtualPatchBay, VirtualSocket, device_plugs


class HciOperationGate:
    """Serialize HCI-heavy operations that would otherwise contend on one loop."""

    def __init__(self):
        self._lock = asyncio.Lock()

    async def run(self, _label: str, operation):
        async with self._lock:
            return await operation()


@dataclass(slots=True)
class _RouteSocketSpec:
    socket_id: str
    kind: SocketKind
    protocols: set[Protocol]
    capabilities: set[Capability]
    label: str


class VirtualRoutePatchBay:
    """Route graph -> patch-bay connector wiring."""

    def __init__(self):
        self.patchbay = VirtualPatchBay()
        self._route_cables: list[str] = []
        self._install_default_sockets()

    def _install_default_sockets(self):
        for spec in (
            _RouteSocketSpec(
                socket_id="transfer:audio-input",
                kind=SocketKind.AUDIO_INPUT,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
                label="Transfer audio input",
            ),
            _RouteSocketSpec(
                socket_id="transfer:audio-output",
                kind=SocketKind.AUDIO_OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
                label="Transfer audio output",
            ),
            _RouteSocketSpec(
                socket_id="session:peer",
                kind=SocketKind.SESSION,
                protocols={Protocol.BLE_GATT_BOOTSTRAP, Protocol.BLE_L2CAP_COC_SESSION},
                capabilities={Capability.SESSION_PEER},
                label="Session peer",
            ),
            _RouteSocketSpec(
                socket_id="session:remote-mic",
                kind=SocketKind.REMOTE_MIC,
                protocols={Protocol.BLE_L2CAP_COC_SESSION},
                capabilities={Capability.REMOTE_MIC_RECEIVER},
                label="Remote microphone receiver",
            ),
            _RouteSocketSpec(
                socket_id="transfer:control-input",
                kind=SocketKind.CONTROL_INPUT,
                protocols={Protocol.CLASSIC_AVRCP},
                capabilities={Capability.CONTROL_INPUT},
                label="Transfer control backchannel",
            ),
            _RouteSocketSpec(
                socket_id="iphone:control-output",
                kind=SocketKind.CONTROL_OUTPUT,
                protocols={Protocol.BLE_AMS, Protocol.BLE_HID},
                capabilities={Capability.CONTROL_OUTPUT, Capability.METADATA_INPUT},
                label="iPhone control output",
            ),
            _RouteSocketSpec(
                socket_id="iphone:metadata-input",
                kind=SocketKind.METADATA_INPUT,
                protocols={Protocol.BLE_ANCS, Protocol.BLE_CTS},
                capabilities={Capability.METADATA_INPUT, Capability.NOTIFICATIONS_INPUT},
                label="iPhone metadata input",
            ),
        ):
            self.patchbay.add_socket(VirtualSocket(
                id=spec.socket_id,
                owner=spec.socket_id.split(":", 1)[0],
                kind=spec.kind,
                protocols=set(spec.protocols),
                capabilities=set(spec.capabilities),
                label=spec.label,
            ))

    async def activate(self, plan: PlannedSession, registry):
        if not plan.routes:
            await self.deactivate()
            return []
        staged = VirtualPatchBay()
        staged.sockets = copy.deepcopy(self.patchbay.sockets)
        for socket in staged.sockets.values():
            socket.occupied_by = None
        staged.plugs = copy.deepcopy(self.patchbay.plugs)
        connected = []
        for route in plan.routes:
            input_device = registry.by_id(route.input_device_id)
            output_device = registry.by_id(route.output_device_id)
            if input_device is None:
                raise RuntimeError(f"unknown route input device: {route.input_device_id}")
            if output_device is None:
                raise RuntimeError(f"unknown route output device: {route.output_device_id}")
            self._ensure_plug_exists(input_device, route.input_endpoint_id)
            self._ensure_plug_exists(output_device, route.output_endpoint_id)
            for device in (input_device, output_device):
                for plug in device_plugs(device):
                    try:
                        socket = self._socket_for_kind(plug.kind, staged)
                    except RuntimeError:
                        continue
                    staged.add_plug(plug)
                    connected.append(staged.connect(plug.id, socket.id))
        self.patchbay = staged
        self._route_cables = [cable.id for cable in connected]
        return connected

    async def deactivate(self):
        self.patchbay.disconnect_all()
        self._route_cables = []

    def current_cables(self):
        return [self.patchbay.cables[cable_id] for cable_id in self._route_cables if cable_id in self.patchbay.cables]

    @staticmethod
    def _plug_for_endpoint(device, endpoint):
        plugs = device_plugs(device)
        for plug in plugs:
            if plug.metadata.get("endpoint_id") == endpoint.id:
                return plug
        raise RuntimeError(f"device endpoint missing from plug set: {device.id}/{endpoint.id}")

    @staticmethod
    def _ensure_plug_exists(device, endpoint_id):
        VirtualRoutePatchBay._plug_for_endpoint(device, SimpleNamespace(id=endpoint_id))
        return True

    def _socket_for_kind(self, kind: SocketKind, patchbay=None) -> VirtualSocket:
        patchbay = patchbay or self.patchbay
        for socket in patchbay.sockets.values():
            if socket.kind == kind:
                return socket
        raise RuntimeError(f"missing adapter socket for kind: {kind}")
