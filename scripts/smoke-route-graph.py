#!/usr/bin/env python3
"""Smoke checks for the Car Thing route-graph userspace."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIB = ROOT / "overlay" / "usr" / "lib" / "carthing"
sys.path.insert(0, str(LIB))

from app_state import AppState  # noqa: E402
from enrollment_manager import EnrollmentEvidence, EnrollmentManager  # noqa: E402
from route_graph import Protocol  # noqa: E402
from route_planner import RoutePlanner  # noqa: E402
from session_presets import build_preset_session, normalize_preset  # noqa: E402
from session_runner import AdapterConnector, SessionRunner  # noqa: E402
from trusted_device_registry import TrustedDeviceRegistry  # noqa: E402
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


async def check_runner():
    runner = SessionRunner()
    connectors = []
    for protocol in Protocol:
        connector = DummyConnector(protocol)
        connectors.append(connector)
        runner.register(connector)
    await runner.start(build_preset_session("remote"))
    await runner.start(build_preset_session("router"))
    assert runner.current is not None
    assert runner.current.plan.name == "router"
    assert any("detach:remote" in connector.events for connector in connectors)


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


def main():
    assert normalize_preset("transfer") == "router"
    check_registry_and_planner()
    check_enrollment()
    check_patchbay()
    asyncio.run(check_runner())
    print("ROUTE GRAPH SMOKE OK")


if __name__ == "__main__":
    main()
