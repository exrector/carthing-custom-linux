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
from types import SimpleNamespace

from PIL import Image

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
from ui_components import RegionSet  # noqa: E402
from route_graph import Capability, Constraint, Endpoint, EndpointDirection, EndpointPlane, PlannedSession, Protocol, TrustedDevice  # noqa: E402
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
                direction=EndpointDirection.SOURCE,
                plane=EndpointPlane.AUDIO,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
            ),
            Endpoint(
                id="out",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.AUDIO,
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
                direction=EndpointDirection.SOURCE,
                plane=EndpointPlane.AUDIO,
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
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.AUDIO,
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
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.AUDIO,
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
    fosi_profile = fosi.metadata.get("capability_profile") or {}
    iphone_profile = iphone.metadata.get("capability_profile") or {}
    assert "classic_sdp" in set(fosi_profile.get("evidence_sources") or [])
    assert "ble_gatt" in set(iphone_profile.get("evidence_sources") or [])
    assert "audio_output" in set(fosi_profile.get("verified_capabilities") or [])
    assert "audio_input" in set(iphone_profile.get("verified_capabilities") or [])
    le_speaker = manager.enroll(EnrollmentEvidence(
        "22:33:44:55:66:88",
        "LE Speaker",
        ble_services={"184e", "1850"},
    ))
    assert le_speaker.output_endpoints()
    le_protocols = set().union(*(endpoint.protocols for endpoint in le_speaker.output_endpoints()))
    assert Protocol.BLE_LE_AUDIO_SINK in le_protocols
    assert Protocol.CLASSIC_A2DP_SOURCE not in le_protocols
    airfly = manager.enroll(EnrollmentEvidence(
        "AA:BB:CC:DD:EE:FF",
        "AirFly",
        service_uuids={"110b"},
    ))
    assert "ble_gatt" in set((airfly.metadata.get("capability_profile") or {}).get("unknowns") or [])
    airfly = manager.enroll(EnrollmentEvidence(
        "AA:BB:CC:DD:EE:FF",
        "AirFly",
        service_uuids={"110a"},
        ble_services={"ams"},
    ))
    assert airfly.input_endpoints()
    assert airfly.output_endpoints()
    profile = airfly.metadata.get("capability_profile") or {}
    assert {"classic_sdp", "ble_gatt"} <= set(profile.get("evidence_sources") or [])
    assert "ble_gatt" not in set(profile.get("unknowns") or [])


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
        assert device["metadata"].get("output_enrolled") is True
        assert any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_inputs)
        assert any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_outputs)
        assert app_state.revoke_speaker_role("AA:BB:CC:DD:EE:FF") is True
        assert any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_inputs)
        assert not any(d.get("address") == "AA:BB:CC:DD:EE:FF" for d in app_state.route_outputs)


def check_unified_device_intake():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        os.environ["CAR_THING_KEYSTORE"] = str(Path(tmp) / "keys.json")
        app_state = AppState()
        address = "66:55:44:33:22:11"
        device = app_state.enroll_peer(
            address=address,
            name="MacBook",
            service_uuids={"110a"},
            ble_services={"ams"},
            capabilities={"session_peer", "remote_mic_receiver", "usb_peer"},
            metadata={
                "classic_remote_name": "MacBook",
                "sdp_probe": "complete",
                "gatt_probe": "complete",
                "ctsp_probe": "advertised",
                "usb_identity": "ncm",
            },
            intake_source="smoke:full_intake",
        )
        assert len([row for row in app_state.trusted if row.get("address") == address]) == 1
        assert device["metadata"]["enrollment_evidence"]["intake_pipeline"] == "unified_device_intake"
        endpoint_ids = {endpoint["id"] for endpoint in device["endpoints"]}
        assert {
            "audio-source",
            "media-control",
            "session-source",
            "session-sink",
            "remote-mic-sink",
            "usb-session-source",
            "usb-session-sink",
        } <= endpoint_ids
        usage = set((device["metadata"].get("capability_profile") or {}).get("usage_hints") or [])
        assert {"audio_source", "session_peer", "mic_sink", "usb_peer"} <= usage

        app_state.upsert_speaker_candidate(
            address,
            name="MacBook",
            class_of_device=0x240414,
            audio=True,
        )
        device = app_state.trust_speaker(address, "MacBook")
        assert len([row for row in app_state.trusted if row.get("address") == address]) == 1
        assert device["role"] == "device"
        usage = set((device["metadata"].get("capability_profile") or {}).get("usage_hints") or [])
        assert {"audio_source", "audio_sink", "session_peer", "mic_sink", "usb_peer"} <= usage
        nodes = [node for node in app_state.route_nodes if node["device_key"] == device["key"]]
        node_planes = {(node["direction"], node["plane"]) for node in nodes}
        assert ("source", "audio") in node_planes
        assert ("sink", "audio") in node_planes
        assert ("source", "session") in node_planes
        assert ("sink", "session") in node_planes
        assert ("sink", "mic") in node_planes
        assert ("source", "usb") in node_planes
        assert ("sink", "usb") in node_planes

        app_state.trusted.append({
            "key": "endpoint-only",
            "address": "12:34:56:78:90:AB",
            "label": "Endpoint Only",
            "role": "device",
            "capabilities": [],
            "endpoints": [{
                "id": "audio-source",
                "direction": "source",
                "plane": "audio",
                "capabilities": ["audio_input"],
            }],
            "constraints": [],
            "metadata": {},
        })
        assert any(row.get("key") == "endpoint-only" for row in app_state.trusted_sources)


def check_trusted_peer_presence():
    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        os.environ["CAR_THING_KEYSTORE"] = str(Path(tmp) / "keys.json")
        app_state = AppState()
        app_state.enroll_peer(
            address="C4:A9:B8:70:2F:E5",
            name="Fosi",
            service_uuids={"110b"},
            intake_source="smoke:presence",
        )
        app_state.enroll_peer(
            address="66:55:44:33:22:11",
            name="MacBook",
            service_uuids={"110a"},
            capabilities={"session_peer", "usb_peer"},
            intake_source="smoke:presence",
        )

        app_state.note_peer_presence(
            address="66:55:44:33:22:11",
            event="session_seen",
            plane="session",
            transport="ble_l2cap_coc",
            detail="smoke",
        )
        mac = next(row for row in app_state.trusted if row.get("address") == "66:55:44:33:22:11")
        assert mac["online"] is True
        assert mac["connected"] is True
        assert mac["presence_state"] == "present_unrouted"
        assert "session" in set(mac.get("presence_planes") or [])

        app_state.set_speaker_connected("C4:A9:B8:70:2F:E5", True)
        fosi = next(row for row in app_state.trusted if row.get("address") == "C4:A9:B8:70:2F:E5")
        assert fosi["online"] is True
        assert fosi["connected"] is True
        assert fosi["presence_state"] == "standby"
        snapshot = {item["address"]: item for item in app_state.route_availability_snapshot()}
        assert snapshot["C4:A9:B8:70:2F:E5"]["state"] == "standby"
        assert snapshot["66:55:44:33:22:11"]["state"] == "present_unrouted"

        app_state.set_speaker_connected("C4:A9:B8:70:2F:E5", False)
        assert fosi["online"] is False
        assert fosi["connected"] is False
        assert fosi["presence_state"] == "missing"


def check_self_endpoint_matrix_width():
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(Path(tmp) / "trusted-devices.json")
        os.environ["CAR_THING_KEYSTORE"] = str(Path(tmp) / "keys.json")
        app_state = AppState()
        nodes = app_state.route_nodes
        by_id = {node["id"]: node for node in nodes}
        required = {
            "carthing:playnow-metadata-sink": ("sink", "metadata"),
            "carthing:playnow-control-source": ("source", "control"),
            "carthing:ctsp-session-source": ("source", "session"),
            "carthing:ctsp-session-sink": ("sink", "session"),
            "carthing:local-mic-source": ("source", "mic"),
            "carthing:remote-mic-sink": ("sink", "mic"),
            "carthing:usb-session-source": ("source", "usb"),
            "carthing:usb-session-sink": ("sink", "usb"),
        }
        for node_id, (direction, plane) in required.items():
            assert node_id in by_id, f"missing self matrix node: {node_id}"
            assert by_id[node_id]["direction"] == direction
            assert by_id[node_id]["plane"] == plane


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
                    "endpoints": [{"id": "audio-input", "direction": "source", "plane": "audio", "capabilities": ["audio_input"]}],
                },
                {
                    "id": "fosi",
                    "address": "C4:A9:B8:70:2F:E5",
                    "name": "Fosi Audio ZD3",
                    "role": "speaker",
                    "trusted": True,
                    "capabilities": ["audio_output"],
                    "endpoints": [{"id": "audio-output", "direction": "sink", "plane": "audio", "capabilities": ["audio_output"]}],
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
        # Source rows may still accept legacy UI selectors (`source:<MAC>`), but
        # AppState stores the planner-facing device id/address.
        dispatcher.dispatch("route_input_select", "source:10:A2:D3:83:82:50")
        dispatcher.dispatch("route_output_select", "fosi")
        assert events == [("input", "iphone"), ("output", "fosi")]
        assert app_state.route_input == "iphone"
        assert app_state.route_output == "fosi"
        assert app_state.route_active is False
        dispatcher.dispatch("route_activate")
        assert events[-1] == ("activate", None)


def check_route_wizard_destinations_and_check_callback():
    from app_state import AppState
    from intents import Dispatcher

    with tempfile.TemporaryDirectory() as tmp:
        trusted_path = Path(tmp) / "trusted-devices.json"
        trusted_path.write_text(json.dumps({"schema": 2, "devices": []}))
        os.environ["CARTHING_TRUSTED_DEVICES"] = str(trusted_path)
        app_state = AppState()
        app_state.trusted = []
        app_state.enroll_peer(
            address="10:A2:D3:83:82:50",
            name="iPhone 15 Pro",
            service_uuids={"110a"},
            ble_services={"ams", "ancs"},
            intake_source="smoke",
        )
        app_state.enroll_peer(
            address="5C:E9:1E:8B:66:EE",
            name="MacBook Pro",
            service_uuids={"110a"},
            ble_services={"ams"},
            capabilities={"session_peer", "remote_mic_receiver"},
            intake_source="smoke",
        )
        app_state.enroll_peer(
            address="C4:A9:B8:70:2F:E5",
            name="Fosi Audio ZD3",
            service_uuids={"110b"},
            class_of_device=0x240414,
            intake_source="smoke",
        )
        labels = [row.get("label") for row in app_state.route_outputs]
        assert "iPhone 15 Pro" not in labels
        assert "MacBook Pro" in labels
        assert "Fosi Audio ZD3" in labels
        mac_sinks = [row for row in app_state.route_outputs if row.get("label") == "MacBook Pro"]
        assert {row.get("endpoint_plane") for row in mac_sinks} >= {"usb", "session", "mic"}
        assert any(row.get("label") == "Fosi Audio ZD3" and row.get("endpoint_plane") == "audio" for row in app_state.route_outputs)
        mac_sources = [row for row in app_state.route_inputs if row.get("label") == "MacBook Pro"]
        assert {row.get("endpoint_plane") for row in mac_sources} >= {"audio", "usb", "session"}

        calls = []
        dispatcher = Dispatcher(
            app_state,
            on_route_view_open=lambda: calls.append("open"),
            on_route_check=lambda: calls.append("check") or None,
        )
        dispatcher.dispatch("route_view_open")
        dispatcher.dispatch("route_input_select", "source:10:A2:D3:83:82:50")
        dispatcher.dispatch("route_output_select", "C4:A9:B8:70:2F:E5")
        dispatcher.dispatch("route_check")
        assert calls == ["open", "check"]
        assert app_state.route_check_state == "checking"


def check_runtime_route_state():
    from runtime_model import RuntimeModel

    model = RuntimeModel()
    plan = PlannedSession(
        name="route",
        required_protocols={Protocol.CLASSIC_A2DP_SINK, Protocol.CLASSIC_AVRCP},
        warnings=["route requires stop-before-start transition"],
    )
    plan.routes.append(type("Route", (), {
        "source_device_id": "iphone",
        "source_endpoint_id": "audio-input",
        "sink_device_id": "speaker",
        "sink_endpoint_id": "audio-output",
        "source_ref": "iphone:audio-input",
        "sink_ref": "speaker:audio-output",
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


def check_statusbar_has_no_legacy_route_chip():
    from ui_statusbar import StatusBar
    import ui_theme as T

    img = Image.new("RGB", (800, 480), (0, 0, 0))
    regions = RegionSet()
    state = SimpleNamespace(
        control_source=None,
        route_name="",
        route_input="iphone",
        route_output="speaker",
        route_active=False,
    )
    StatusBar().render(img, regions=regions, anim=None, st=state)
    assert img.getpixel((60, 330)) == T.BG


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
                            "direction": "source",
                            "plane": "audio",
                            "protocols": ["classic_a2dp_sink"],
                            "capabilities": ["audio_input"],
                        },
                        {
                            "id": "media-control",
                            "direction": "sink",
                            "plane": "control",
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
                            "direction": "sink",
                            "plane": "audio",
                            "protocols": ["classic_a2dp_source"],
                            "capabilities": ["audio_output"],
                        },
                        {
                            "id": "speaker-remote",
                            "direction": "source",
                            "plane": "control",
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
    check_unified_device_intake()
    check_trusted_peer_presence()
    check_self_endpoint_matrix_width()
    check_route_activation_intent()
    check_route_wizard_destinations_and_check_callback()
    check_runtime_route_state()
    check_statusbar_has_no_legacy_route_chip()
    check_patchbay()
    asyncio.run(check_route_patchbay_router())
    asyncio.run(check_hci_gate())
    asyncio.run(check_link_manager())
    asyncio.run(check_runner())
    asyncio.run(check_transfer_route_connector_refcount())
    print("ROUTE GRAPH SMOKE OK")


if __name__ == "__main__":
    main()
