#!/usr/bin/env python3
"""Smoke checks for the Car Thing route-graph userspace."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "lib" / "carthing"
VENDOR = LIB / "vendor"
os.environ.setdefault("CAR_THING_LIB", str(VENDOR))
sys.path.insert(0, str(LIB))
sys.path.insert(0, str(VENDOR))

from app_state import AppState  # noqa: E402
from enrollment_manager import EnrollmentEvidence, EnrollmentManager  # noqa: E402
from link_manager import LinkAdapter, LinkManager  # noqa: E402
from intents import Dispatcher  # noqa: E402
from route_graph import Capability, Constraint, Endpoint, EndpointDirection, PlannedSession, Protocol, TrustedDevice  # noqa: E402
from route_planner import RoutePlanError, RoutePlanner  # noqa: E402
from session_runner import AdapterConnector, SessionRunner  # noqa: E402
from trusted_device_registry import TrustedDeviceRegistry  # noqa: E402
from virtual_connectors import HciOperationGate, VirtualRoutePatchBay  # noqa: E402
from virtual_socket import SocketKind, VirtualPatchBay, VirtualPlug, VirtualSocket  # noqa: E402


class DummyConnector(AdapterConnector):
    def __init__(self, protocol):
        self.protocol = protocol
        self.events = []

    async def start(self):
        self.events.append("start")

    async def stop(self):
        self.events.append("stop")

    async def attach_session(self, session):
        self.events.append(f"attach:{session.name}")

    async def detach_session(self, session):
        self.events.append(f"detach:{session.name}")


def _session(name):
    return PlannedSession(name=name, required_protocols={Protocol.CLASSIC_A2DP_SINK, Protocol.CLASSIC_A2DP_SOURCE})


async def check_runner():
    runner = SessionRunner()
    connectors = []
    for protocol in Protocol:
        connector = DummyConnector(protocol)
        connectors.append(connector)
        runner.register(connector)
    await runner.start(_session("remote"))
    await runner.start(_session("router"))
    assert runner.current is not None
    assert runner.current.plan.name == "router"
    assert any("detach:remote" in connector.events for connector in connectors)


async def check_transfer_route_connector_refcount():
    from carthing_runtime import TransferRouteConnector

    logging.getLogger("session_runner").setLevel(logging.WARNING)

    class Service:
        def __init__(self):
            self.activated = 0
            self.deactivated = 0

        async def activate(self):
            self.activated += 1

        async def deactivate(self):
            self.deactivated += 1

    service = Service()
    runner = SessionRunner()
    for protocol in (Protocol.CLASSIC_A2DP_SINK, Protocol.CLASSIC_A2DP_SOURCE):
        runner.register(TransferRouteConnector(protocol, service))
    await runner.start(PlannedSession(
        name="router",
        required_protocols={Protocol.CLASSIC_A2DP_SINK, Protocol.CLASSIC_A2DP_SOURCE},
    ))
    await runner.stop_current()
    assert service.activated == 1
    assert service.deactivated == 1


def check_registry_and_planner():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        trusted_path.write_text(json.dumps({
            "sources": [{"name": "iPhone", "address": "10:A2:D3:83:82:50"}],
            "speakers": [{"name": "Fosi Audio ZD3", "address": "C4:A9:B8:70:2F:E5"}],
        }))
        registry = TrustedDeviceRegistry(trusted_path).load()
        assert [device.name for device in registry.inputs()] == ["iPhone"]
        assert [device.name for device in registry.outputs()] == ["Fosi Audio ZD3"]
        plan = RoutePlanner(registry).plan_simple_route(
            "10:A2:D3:83:82:50",
            "C4:A9:B8:70:2F:E5",
            name="smoke",
        )
        assert plan.name == "smoke"
        assert plan.routes

        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        app_state = AppState()
        assert app_state.route_inputs
        assert app_state.route_outputs


def check_planner_constraints():
    blocked_peer = TrustedDevice(
        id="peer-blocked",
        address="AA:AA:AA:AA:AA:AA",
        name="Blocked Peer",
        endpoints=[
            Endpoint(
                id="in",
                direction=EndpointDirection.INPUT,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
            ),
            Endpoint(
                id="out",
                direction=EndpointDirection.OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
            ),
        ],
        constraints={Constraint.FULL_DUPLEX_FORBIDDEN},
    )

    class _Registry:
        def __init__(self, devices):
            self.devices = {device.id: device for device in devices}

        def by_id(self, device_id):
            return self.devices.get(device_id)

    planner = RoutePlanner(_Registry([blocked_peer]))
    try:
        planner.plan_simple_route("peer-blocked", "peer-blocked", name="blocked")
        raise AssertionError("planner accepted full-duplex-forbidden route")
    except RoutePlanError:
        pass


def check_planner_exclusive_conflicts():
    src_hci = TrustedDevice(
        id="src-hci",
        address="AA:AA:AA:AA:AA:10",
        name="Source HCI Exclusive",
        endpoints=[
            Endpoint(
                id="in",
                direction=EndpointDirection.INPUT,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
            ),
        ],
        constraints={Constraint.EXCLUSIVE_HCI},
    )
    out_hci = TrustedDevice(
        id="out-hci",
        address="AA:AA:AA:AA:AA:11",
        name="Output HCI Exclusive",
        endpoints=[
            Endpoint(
                id="out",
                direction=EndpointDirection.OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
            ),
        ],
        constraints={Constraint.EXCLUSIVE_HCI},
    )
    stop_before = TrustedDevice(
        id="stop-before",
        address="AA:AA:AA:AA:AA:12",
        name="Stop-before-start output",
        endpoints=[
            Endpoint(
                id="out",
                direction=EndpointDirection.OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
            ),
        ],
        constraints={Constraint.REQUIRES_STOP_BEFORE_START},
    )

    class _Registry:
        def __init__(self, devices):
            self.devices = {device.id: device for device in devices}

        def by_id(self, device_id):
            return self.devices.get(device_id)

    planner = RoutePlanner(_Registry([src_hci, out_hci, stop_before]))
    try:
        planner.plan_simple_route("src-hci", "out-hci", name="hci-conflict")
        raise AssertionError("planner accepted exclusive hci conflict")
    except RoutePlanError:
        pass

    planned = planner.plan_simple_route("src-hci", "stop-before", name="warn-stop-before")
    warnings = planned.warnings
    assert any("stop-before-start" in warning for warning in warnings)


def check_enrollment():
    registry = TrustedDeviceRegistry("/tmp/nonexistent-carthing-trusted.json").load()
    manager = EnrollmentManager(registry)
    fosi = manager.enroll(EnrollmentEvidence(
        "C4:A9:B8:70:2F:E5",
        "Fosi",
        class_of_device=0x240414,
        service_uuids={"110b"},
    ))
    iphone = manager.enroll(EnrollmentEvidence(
        "10:A2:D3:83:82:50",
        "iPhone",
        service_uuids={"110a"},
        ble_services={"ams", "ancs", "1812"},
    ))
    assert fosi.output_endpoints()
    assert fosi.control_endpoints()
    assert iphone.input_endpoints()


def check_degraded_enrollment():
    registry = TrustedDeviceRegistry("/tmp/nonexistent-carthing-trusted.json").load()
    manager = EnrollmentManager(registry)
    degraded = manager.enroll(EnrollmentEvidence(
        "22:33:44:55:66:77",
        "Unknown Peer",
        missing_capabilities={Capability.AUDIO_OUTPUT},
    ))
    constraints = {str(value.value if hasattr(value, "value") else value) for value in degraded.constraints}
    assert "requires_stop_before_start" in constraints
    assert "missing_capability:audio_output" in constraints
    evidence = degraded.metadata.get("enrollment_evidence") or {}
    assert evidence.get("enrollment_state") == "degraded"
    assert "audio_output" in set(evidence.get("missing_capabilities") or [])


def check_multirole_app_state():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        os.environ["CAR_THING_KEYSTORE"] = str(Path(tmp) / "keys.json")
        app_state = AppState()
        app_state.enroll_trusted_device(
            "AA:BB:CC:DD:EE:FF",
            name="Multi Peer",
            service_uuids={"110a"},
            ble_services={"ams"},
        )
        app_state.upsert_speaker_candidate(
            "AA:BB:CC:DD:EE:FF",
            name="Multi Peer",
            class_of_device=0x240414,
            audio=True,
        )
        device = app_state.trust_speaker("AA:BB:CC:DD:EE:FF", "Multi Peer")
        assert device is not None
        assert device["role"] == "device"
        assert any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_inputs)
        assert any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_outputs)


def check_route_activation_intent():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        trusted_path.write_text(json.dumps({
            "schema": 2,
            "devices": [
                {
                    "id": "iphone",
                    "address": "10:A2:D3:83:82:50",
                    "name": "iPhone",
                    "role": "source",
                    "trusted": True,
                    "capabilities": ["audio_input"],
                    "endpoints": [{"id": "audio-input", "direction": "input", "capabilities": ["audio_input"]}],
                },
                {
                    "id": "fosi",
                    "address": "C4:A9:B8:70:2F:E5",
                    "name": "Fosi Audio ZD3",
                    "role": "speaker",
                    "trusted": True,
                    "capabilities": ["audio_output"],
                    "endpoints": [{"id": "audio-output", "direction": "output", "capabilities": ["audio_output"]}],
                },
            ],
        }))
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        app_state = AppState()
        events = []

        dispatcher = Dispatcher(
            app_state,
            on_route_input_select=lambda key: events.append(("input", key)),
            on_route_output_select=lambda key: events.append(("output", key)),
            on_route_activate=lambda: events.append(("activate", None)),
        )
        dispatcher.dispatch("route_input_select", "iphone")
        dispatcher.dispatch("route_output_select", "fosi")
        assert events == [("input", "iphone"), ("output", "fosi")]
        assert app_state.route_input == "iphone"
        assert app_state.route_output == "fosi"
        assert app_state.route_active is False
        dispatcher.dispatch("route_activate")
        assert events[-1] == ("activate", None)


def check_runtime_route_state():
    from runtime_model import RuntimeModel

    model = RuntimeModel()
    plan = PlannedSession(
        name="route",
        required_protocols={Protocol.CLASSIC_A2DP_SINK, Protocol.CLASSIC_AVRCP},
        warnings=["route requires stop-before-start transition"],
    )
    plan.routes.append(type("Route", (), {
        "input_device_id": "iphone",
        "output_device_id": "speaker",
    })())
    cables = [type("Cable", (), {"id": "iphone:audio-input->transfer:audio-input"})()]
    model.set_route_plan(plan, cables)
    bt = model.bt_block()
    assert bt["route"]["active"] is True
    assert bt["route"]["name"] == "route"
    assert bt["route"]["input"] == "iphone"
    assert bt["route"]["output"] == "speaker"
    assert "classic_a2dp_sink" in bt["route"]["protocols"]
    assert bt["route"]["cables"] == ["iphone:audio-input->transfer:audio-input"]
    model.clear_route_plan()
    bt = model.bt_block()
    assert bt["route"]["active"] is False
    assert bt["route"]["name"] == ""


def check_patchbay():
    bay = VirtualPatchBay()
    bay.add_plug(VirtualPlug(
        "iphone:a2dp-out",
        "iphone",
        SocketKind.AUDIO_INPUT,
        {Protocol.CLASSIC_A2DP_SINK},
    ))
    bay.add_socket(VirtualSocket(
        "carthing:a2dp-in",
        "carthing",
        SocketKind.AUDIO_INPUT,
        {Protocol.CLASSIC_A2DP_SINK},
    ))
    cable = bay.connect("iphone:a2dp-out", "carthing:a2dp-in")
    assert cable.active
    bay.disconnect_all()
    assert not bay.cables


async def check_route_patchbay_router():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        trusted_path.write_text(json.dumps({
            "schema": 2,
            "devices": [
                {
                    "id": "iphone",
                    "address": "10:A2:D3:83:82:50",
                    "name": "iPhone",
                    "trusted": True,
                    "online": True,
                    "connected": False,
                    "capabilities": ["audio_input", "control_output", "metadata_input"],
                    "constraints": [],
                    "endpoints": [
                        {
                            "id": "audio-input",
                            "direction": "input",
                            "protocols": ["classic_a2dp_sink"],
                            "capabilities": ["audio_input"],
                        },
                        {
                            "id": "media-control",
                            "direction": "control",
                            "protocols": ["ble_ams", "ble_hid"],
                            "capabilities": ["control_output", "metadata_input"],
                        },
                    ],
                },
                {
                    "id": "speaker",
                    "address": "C4:A9:B8:70:2F:E5",
                    "name": "Fosi Audio ZD3",
                    "trusted": True,
                    "online": True,
                    "connected": True,
                    "capabilities": ["audio_output", "control_input"],
                    "constraints": [],
                    "endpoints": [
                        {
                            "id": "audio-output",
                            "direction": "output",
                            "protocols": ["classic_a2dp_source"],
                            "capabilities": ["audio_output"],
                        },
                        {
                            "id": "speaker-remote",
                            "direction": "control",
                            "protocols": ["classic_avrcp"],
                            "capabilities": ["control_input"],
                        },
                    ],
                },
            ],
        }))
        registry = TrustedDeviceRegistry(trusted_path).load()
        planner = RoutePlanner(registry)
        plan = planner.plan_simple_route("iphone", "speaker", name="route")
        router = VirtualRoutePatchBay()
        cables = await router.activate(plan, registry)
        assert len(cables) >= 2
        assert any("audio-input" in cable.id for cable in cables)
        assert any("audio-output" in cable.id for cable in cables)
        await router.deactivate()
        assert not router.patchbay.cables


async def check_hci_gate():
    gate = HciOperationGate()
    order = []

    async def worker(name):
        async def op():
            order.append(f"{name}:start")
            await asyncio.sleep(0.05)
            order.append(f"{name}:end")
        await gate.run(name, op)

    await asyncio.gather(worker("a"), worker("b"))
    assert order in (["a:start", "a:end", "b:start", "b:end"], ["b:start", "b:end", "a:start", "a:end"])


async def check_link_manager():
    class _Registry:
        def __init__(self, devices):
            self.devices = list(devices)

    class _Adapter(LinkAdapter):
        def __init__(self):
            super().__init__(name="smoke")
            self.probe_result = True
            self.disconnect_calls = 0

        async def probe(self, device):
            return self.probe_result

        async def connect_idle(self, device):
            return True

        async def disconnect_idle(self, device):
            self.disconnect_calls += 1

    device = TrustedDevice(
        id="idle-peer",
        address="AA:AA:AA:AA:AA:AA",
        name="Idle Peer",
        constraints={Constraint.IDLE_LINK_ALLOWED},
    )
    manager = LinkManager(_Registry([device]))
    adapter = _Adapter()
    manager.register(adapter)

    await manager.tick()
    assert device.online is True
    assert device.connected is True

    adapter.probe_result = False
    await manager.tick()
    assert device.online is False
    assert device.connected is False
    assert adapter.disconnect_calls == 1


def main():
    check_registry_and_planner()
    check_planner_constraints()
    check_planner_exclusive_conflicts()
    check_enrollment()
    check_degraded_enrollment()
    check_multirole_app_state()
    check_route_activation_intent()
    check_runtime_route_state()
    check_patchbay()
    asyncio.run(check_route_patchbay_router())
    asyncio.run(check_hci_gate())
    asyncio.run(check_link_manager())
    asyncio.run(check_runner())
    asyncio.run(check_transfer_route_connector_refcount())
    print("ROUTE GRAPH SMOKE OK")


if __name__ == "__main__":
    main()
