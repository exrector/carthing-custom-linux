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

