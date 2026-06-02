"""Unified trusted-device registry.

Legacy userspace stored `sources` and `speakers` as separate lists. The new
router architecture stores one device list with capabilities, endpoints, and
constraints. This module can read both shapes so migration can be incremental.
"""

from __future__ import annotations

import json
from pathlib import Path

from app_state import DEFAULT_TRUSTED_DEVICES_PATH, normalize_address
from route_graph import (
    Capability,
    Constraint,
    Endpoint,
    EndpointDirection,
    Protocol,
    TrustedDevice,
)


SCHEMA_VERSION = 2


def _enum_set(enum_cls, values):
    result = set()
    for value in values or []:
        try:
            result.add(enum_cls(value))
        except ValueError:
            result.add(value)
    return result


def _endpoint_from_json(row):
    return Endpoint(
        id=str(row.get("id") or row.get("direction") or "endpoint"),
        direction=EndpointDirection(row.get("direction")),
        protocols=_enum_set(Protocol, row.get("protocols")),
        capabilities=_enum_set(Capability, row.get("capabilities")),
        label=str(row.get("label") or ""),
        metadata=dict(row.get("metadata") or {}),
    )


def _endpoint_to_json(endpoint: Endpoint):
    return {
        "id": endpoint.id,
        "direction": endpoint.direction.value,
        "protocols": sorted(str(value.value if hasattr(value, "value") else value)
                            for value in endpoint.protocols),
        "capabilities": sorted(str(value.value if hasattr(value, "value") else value)
                               for value in endpoint.capabilities),
        "label": endpoint.label,
        "metadata": endpoint.metadata,
    }


def _device_from_json(row):
    address = normalize_address(row.get("address"))
    device_id = str(row.get("id") or address or row.get("name") or "device")
    capabilities = _enum_set(Capability, row.get("capabilities"))
    endpoints = [_endpoint_from_json(endpoint) for endpoint in row.get("endpoints", [])]
    directions = {endpoint.direction for endpoint in endpoints}
    if Capability.AUDIO_INPUT in capabilities and EndpointDirection.INPUT not in directions:
        endpoints.append(Endpoint(
            id="audio-input",
            direction=EndpointDirection.INPUT,
            protocols={Protocol.CLASSIC_A2DP_SINK},
            capabilities={Capability.AUDIO_INPUT},
            label="Bluetooth audio input",
        ))
    if Capability.AUDIO_OUTPUT in capabilities and EndpointDirection.OUTPUT not in directions:
        endpoints.append(Endpoint(
            id="audio-output",
            direction=EndpointDirection.OUTPUT,
            protocols={Protocol.CLASSIC_A2DP_SOURCE},
            capabilities={Capability.AUDIO_OUTPUT},
            label="Bluetooth audio output",
        ))
    return TrustedDevice(
        id=device_id,
        address=address,
        name=str(row.get("name") or row.get("label") or address or device_id),
        capabilities=capabilities,
        endpoints=endpoints,
        constraints=_enum_set(Constraint, row.get("constraints")),
        trusted=bool(row.get("trusted", True)),
        online=bool(row.get("online", False)),
        connected=bool(row.get("connected", False)),
        metadata=dict(row.get("metadata") or {}),
    )


def _device_to_json(device: TrustedDevice):
    return {
        "id": device.id,
        "address": device.address,
        "name": device.name,
        "trusted": device.trusted,
        "online": device.online,
        "connected": device.connected,
        "capabilities": sorted(str(value.value if hasattr(value, "value") else value)
                               for value in device.capabilities),
        "constraints": sorted(str(value.value if hasattr(value, "value") else value)
                              for value in device.constraints),
        "endpoints": [_endpoint_to_json(endpoint) for endpoint in device.endpoints],
        "metadata": device.metadata,
    }


def _legacy_source(row):
    address = normalize_address(row.get("address"))
    name = str(row.get("name") or row.get("label") or "Source")
    return TrustedDevice(
        id=address or name,
        address=address,
        name=name,
        capabilities={
            Capability.AUDIO_INPUT,
            Capability.CONTROL_OUTPUT,
            Capability.METADATA_INPUT,
        },
        endpoints=[
            Endpoint(
                id="media-control",
                direction=EndpointDirection.CONTROL,
                protocols={Protocol.BLE_AMS, Protocol.BLE_HID},
                capabilities={Capability.CONTROL_OUTPUT, Capability.METADATA_INPUT},
                label="Media control",
            ),
            Endpoint(
                id="audio-source",
                direction=EndpointDirection.INPUT,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
                label="Bluetooth audio source",
            ),
        ],
        constraints={
            Constraint.IDLE_LINK_ALLOWED,
            Constraint.ACTIVE_MEDIA_REQUIRES_ROUTE,
        },
        metadata={"legacy_role": "source", **dict(row)},
    )


def _legacy_speaker(row):
    address = normalize_address(row.get("address"))
    name = str(row.get("name") or row.get("label") or "Speaker")
    return TrustedDevice(
        id=address or name,
        address=address,
        name=name,
        capabilities={
            Capability.AUDIO_OUTPUT,
            Capability.CONTROL_INPUT,
            Capability.VOLUME_CONTROL,
            Capability.TRANSPORT_CONTROL,
        },
        endpoints=[
            Endpoint(
                id="audio-output",
                direction=EndpointDirection.OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
                label="Bluetooth speaker",
            ),
            Endpoint(
                id="speaker-remote",
                direction=EndpointDirection.CONTROL,
                protocols={Protocol.CLASSIC_AVRCP},
                capabilities={
                    Capability.CONTROL_INPUT,
                    Capability.VOLUME_CONTROL,
                    Capability.TRANSPORT_CONTROL,
                },
                label="Speaker remote",
            ),
        ],
        constraints={
            Constraint.IDLE_LINK_ALLOWED,
            Constraint.CONTROL_BACKCHANNEL_ONLY,
            Constraint.ACTIVE_MEDIA_REQUIRES_ROUTE,
        },
        metadata={"legacy_role": "speaker", **dict(row)},
    )


class TrustedDeviceRegistry:
    def __init__(self, path=None):
        self.path = Path(path or DEFAULT_TRUSTED_DEVICES_PATH)
        self.devices: list[TrustedDevice] = []

    def load(self):
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            data = {}
        except Exception:
            data = {}

        self.devices = []
        if isinstance(data, dict) and data.get("schema") == SCHEMA_VERSION:
            for row in data.get("devices", []):
                if isinstance(row, dict):
                    self.devices.append(_device_from_json(row))
            return self

        if isinstance(data, list):
            data = {"speakers": data}
        if not isinstance(data, dict):
            return self

        for row in data.get("sources", []):
            if isinstance(row, dict):
                self.devices.append(_legacy_source(row))
        for row in data.get("speakers", []):
            if isinstance(row, dict):
                self.devices.append(_legacy_speaker(row))
        return self

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        doc = {
            "schema": SCHEMA_VERSION,
            "devices": [_device_to_json(device) for device in self.devices],
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
        tmp.replace(self.path)

    def by_id(self, device_id):
        for device in self.devices:
            if device.id == device_id or device.address == normalize_address(device_id):
                return device
        return None

    def inputs(self):
        return [
            device for device in self.devices
            if device.input_endpoints()
        ]

    def outputs(self):
        return [
            device for device in self.devices
            if device.output_endpoints()
        ]

    def migrate_legacy_in_place(self):
        """Read any supported old shape and write schema=2.

        This is intentionally explicit. Runtime code may read legacy files, but
        migration should happen as a controlled action so old agents do not
        silently fight the new registry model.
        """
        self.load()
        self.save()
        return self
