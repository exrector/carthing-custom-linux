"""Device enrollment for the route-graph architecture.

Enrollment is the heavy one-time step. It turns scan/pairing evidence into a
trusted device with capabilities, endpoints, and constraints. Protocol-specific
code should feed evidence into this manager instead of writing ad hoc source or
speaker rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app_state import normalize_address
from route_graph import Capability, Constraint, Endpoint, EndpointDirection, Protocol, TrustedDevice


COD_MAJOR_AUDIO_VIDEO = 0x0400


@dataclass(slots=True)
class EnrollmentEvidence:
    address: str
    name: str = ""
    class_of_device: int | None = None
    service_uuids: set[int | str] = field(default_factory=set)
    ble_services: set[int | str] = field(default_factory=set)
    capabilities: set[Capability | str] = field(default_factory=set)
    endpoints: list[Endpoint] = field(default_factory=list)
    constraints: set[Constraint | str] = field(default_factory=set)
    missing_capabilities: set[Capability | str] = field(default_factory=set)
    metadata: dict[str, Any] = field(default_factory=dict)


class EnrollmentManager:
    def __init__(self, registry):
        self.registry = registry

    def build_device(self, evidence: EnrollmentEvidence) -> TrustedDevice:
        address = normalize_address(evidence.address)
        name = evidence.name or address or "Bluetooth Device"
        capabilities: set[Capability] = set()
        endpoints: list[Endpoint] = []
        constraints: set[Constraint | str] = {
            Constraint.IDLE_LINK_ALLOWED,
            Constraint.ACTIVE_MEDIA_REQUIRES_ROUTE,
        }

        if self._looks_like_audio_output(evidence):
            capabilities.update({
                Capability.AUDIO_OUTPUT,
                Capability.CONTROL_INPUT,
                Capability.VOLUME_CONTROL,
                Capability.TRANSPORT_CONTROL,
            })
            endpoints.append(Endpoint(
                id="audio-output",
                direction=EndpointDirection.OUTPUT,
                protocols={Protocol.CLASSIC_A2DP_SOURCE},
                capabilities={Capability.AUDIO_OUTPUT},
                label="Bluetooth audio output",
            ))
            endpoints.append(Endpoint(
                id="remote-control",
                direction=EndpointDirection.CONTROL,
                protocols={Protocol.CLASSIC_AVRCP},
                capabilities={
                    Capability.CONTROL_INPUT,
                    Capability.VOLUME_CONTROL,
                    Capability.TRANSPORT_CONTROL,
                },
                label="Remote control backchannel",
            ))
            constraints.add(Constraint.CONTROL_BACKCHANNEL_ONLY)

        if self._looks_like_media_source(evidence):
            capabilities.update({
                Capability.AUDIO_INPUT,
                Capability.CONTROL_OUTPUT,
                Capability.METADATA_INPUT,
            })
            endpoints.append(Endpoint(
                id="audio-input",
                direction=EndpointDirection.INPUT,
                protocols={Protocol.CLASSIC_A2DP_SINK},
                capabilities={Capability.AUDIO_INPUT},
                label="Bluetooth audio input",
            ))
            endpoints.append(Endpoint(
                id="media-control",
                direction=EndpointDirection.CONTROL,
                protocols={Protocol.BLE_AMS, Protocol.BLE_HID},
                capabilities={Capability.CONTROL_OUTPUT, Capability.METADATA_INPUT},
                label="Media control",
            ))

        if self._has_ancs(evidence):
            capabilities.add(Capability.NOTIFICATIONS_INPUT)
            endpoints.append(Endpoint(
                id="notifications",
                direction=EndpointDirection.METADATA,
                protocols={Protocol.BLE_ANCS},
                capabilities={Capability.NOTIFICATIONS_INPUT},
                label="Notifications",
            ))

        capabilities.update(self._enum_set(Capability, evidence.capabilities))
        constraints.update(self._enum_set(Constraint, evidence.constraints))
        if evidence.endpoints:
            endpoints = self._merge_endpoints(endpoints, evidence.endpoints)

        missing_caps = self._enum_set(Capability, evidence.missing_capabilities)
        if missing_caps:
            for capability in sorted(str(self._enum_value(value)) for value in missing_caps):
                constraints.add(f"missing_capability:{capability}")

        degraded = bool(missing_caps or not endpoints or not capabilities)
        if degraded:
            constraints.add(Constraint.REQUIRES_STOP_BEFORE_START)

        enrollment_state = "degraded" if degraded else "ready"
        return TrustedDevice(
            id=address or name,
            address=address,
            name=name,
            capabilities=capabilities,
            endpoints=endpoints,
            constraints=constraints,
            metadata={
                "enrollment_evidence": {
                    "class_of_device": evidence.class_of_device,
                    "service_uuids": sorted(str(value) for value in evidence.service_uuids),
                    "ble_services": sorted(str(value) for value in evidence.ble_services),
                    "missing_capabilities": sorted(
                        str(self._enum_value(value)) for value in missing_caps
                    ),
                    "enrollment_state": enrollment_state,
                    **evidence.metadata,
                }
            },
        )

    def enroll(self, evidence: EnrollmentEvidence) -> TrustedDevice:
        device = self.build_device(evidence)
        existing = self.registry.by_id(device.id)
        if existing is None:
            self.registry.devices.append(device)
        else:
            existing.name = device.name
            existing.capabilities = device.capabilities
            existing.endpoints = device.endpoints
            existing.constraints = device.constraints
            existing.metadata.update(device.metadata)
            device = existing
        return device

    @staticmethod
    def _looks_like_audio_output(evidence: EnrollmentEvidence) -> bool:
        services = {str(value).lower() for value in evidence.service_uuids}
        if "110b" in services or "0x110b" in services or "audio_sink" in services:
            return True
        if evidence.class_of_device is None:
            return False
        return (int(evidence.class_of_device) & 0x1F00) == COD_MAJOR_AUDIO_VIDEO

    @staticmethod
    def _looks_like_media_source(evidence: EnrollmentEvidence) -> bool:
        services = {str(value).lower() for value in evidence.service_uuids}
        ble = {str(value).lower() for value in evidence.ble_services}
        return bool({
            "110a", "0x110a", "audio_source", "ams", "1812", "0x1812",
        } & (services | ble))

    @staticmethod
    def _has_ancs(evidence: EnrollmentEvidence) -> bool:
        ble = {str(value).lower() for value in evidence.ble_services}
        return "ancs" in ble or "7905f431-b5ce-4e99-a40f-4b1e122d00d0" in ble

    @staticmethod
    def _enum_value(value):
        return value.value if hasattr(value, "value") else value

    @classmethod
    def _enum_set(cls, enum_cls, values):
        result = set()
        for value in values or []:
            if isinstance(value, enum_cls):
                result.add(value)
                continue
            try:
                result.add(enum_cls(str(value)))
            except Exception:
                result.add(str(value))
        return result

    @staticmethod
    def _merge_endpoints(base: list[Endpoint], extra: list[Endpoint]) -> list[Endpoint]:
        by_id = {endpoint.id: endpoint for endpoint in base}
        result = list(base)
        for endpoint in extra:
            existing = by_id.get(endpoint.id)
            if existing is None:
                result.append(endpoint)
                by_id[endpoint.id] = endpoint
                continue
            existing.protocols.update(endpoint.protocols)
            existing.capabilities.update(endpoint.capabilities)
            if endpoint.label:
                existing.label = endpoint.label
            existing.metadata.update(endpoint.metadata or {})
        return result
