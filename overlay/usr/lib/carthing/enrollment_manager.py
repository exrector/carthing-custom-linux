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
from route_graph import Capability, Constraint, Endpoint, EndpointDirection, EndpointPlane, Protocol, TrustedDevice


COD_MAJOR_AUDIO_VIDEO = 0x0400
LE_AUDIO_OUTPUT_SERVICES = {
    "184e", "0x184e",  # Audio Stream Control Service
    "1850", "0x1850",  # Published Audio Capabilities Service
    "1851", "0x1851",  # Basic Audio Announcement
    "1852", "0x1852",  # Broadcast Audio Announcement
    "1853", "0x1853",  # Common Audio Service
    "1855", "0x1855",  # Telephony and Media Audio Service
    "1858", "0x1858",  # Gaming Audio Service
    "fdf0", "0xfdf0",  # ASHA
}
LE_AUDIO_INPUT_SERVICES = {
    "1843", "0x1843",  # Audio Input Control Service
    "184e", "0x184e",  # ASCS can expose source ASEs too
    "1850", "0x1850",  # PACS can expose source capabilities too
}


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

        output_protocols = self._audio_output_protocols(evidence)
        if output_protocols:
            capabilities.update({
                Capability.AUDIO_OUTPUT,
                Capability.CONTROL_INPUT,
                Capability.VOLUME_CONTROL,
                Capability.TRANSPORT_CONTROL,
            })
            endpoints.append(Endpoint(
                id="audio-sink",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.AUDIO,
                protocols=output_protocols,
                capabilities={Capability.AUDIO_OUTPUT},
                label="Bluetooth audio sink",
                metadata={
                    "transport_adapter": "a2dp"
                    if Protocol.CLASSIC_A2DP_SOURCE in output_protocols
                    else "pending"
                },
            ))
            if Protocol.CLASSIC_A2DP_SOURCE in output_protocols:
                endpoints.append(Endpoint(
                    id="remote-control",
                    direction=EndpointDirection.SOURCE,
                    plane=EndpointPlane.CONTROL,
                    protocols={Protocol.CLASSIC_AVRCP},
                    capabilities={
                        Capability.CONTROL_INPUT,
                        Capability.VOLUME_CONTROL,
                        Capability.TRANSPORT_CONTROL,
                    },
                    label="Remote control backchannel",
                ))
            constraints.add(Constraint.CONTROL_BACKCHANNEL_ONLY)

        input_protocols = self._audio_input_protocols(evidence)
        if input_protocols:
            capabilities.update({
                Capability.AUDIO_INPUT,
                Capability.CONTROL_OUTPUT,
                Capability.METADATA_INPUT,
            })
            endpoints.append(Endpoint(
                id="audio-source",
                direction=EndpointDirection.SOURCE,
                plane=EndpointPlane.AUDIO,
                protocols=input_protocols,
                capabilities={Capability.AUDIO_INPUT},
                label="Bluetooth audio source",
            ))
            endpoints.append(Endpoint(
                id="media-control",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.CONTROL,
                protocols={Protocol.BLE_AMS, Protocol.BLE_HID},
                capabilities={Capability.CONTROL_OUTPUT, Capability.METADATA_INPUT},
                label="Media control",
            ))

        explicit_capabilities = self._enum_set(Capability, evidence.capabilities)
        if (
            Capability.SESSION_PEER in explicit_capabilities
            or Capability.REMOTE_MIC_RECEIVER in explicit_capabilities
        ):
            capabilities.add(Capability.SESSION_PEER)
            endpoints.append(Endpoint(
                id="session-source",
                direction=EndpointDirection.SOURCE,
                plane=EndpointPlane.SESSION,
                protocols={
                    Protocol.BLE_GATT_BOOTSTRAP,
                    Protocol.BLE_L2CAP_COC_SESSION,
                },
                capabilities={Capability.SESSION_PEER},
                label="Session source",
                metadata={"transport_adapter": "ctsp", "duplex_peer": "session-sink"},
            ))
            endpoints.append(Endpoint(
                id="session-sink",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.SESSION,
                protocols={
                    Protocol.BLE_GATT_BOOTSTRAP,
                    Protocol.BLE_L2CAP_COC_SESSION,
                },
                capabilities={Capability.SESSION_PEER},
                label="Session sink",
                metadata={"transport_adapter": "ctsp", "duplex_peer": "session-source"},
            ))
        if Capability.REMOTE_MIC_RECEIVER in explicit_capabilities:
            capabilities.add(Capability.REMOTE_MIC_RECEIVER)
            endpoints.append(Endpoint(
                id="remote-mic-sink",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.MIC,
                protocols={Protocol.BLE_L2CAP_COC_SESSION},
                capabilities={Capability.REMOTE_MIC_RECEIVER},
                label="Remote microphone receiver",
                metadata={
                    "audio_format": "pcm_s16le",
                    "sample_rate_hz": 16000,
                    "channels": 1,
                    "on_demand": True,
                },
            ))

        if (
            Capability.USB_PEER in explicit_capabilities
            or Capability.USB_SESSION in explicit_capabilities
        ):
            capabilities.update({Capability.USB_PEER, Capability.USB_SESSION})
            constraints.add(Constraint.FULL_DUPLEX_ALLOWED)
            endpoints.append(Endpoint(
                id="usb-session-source",
                direction=EndpointDirection.SOURCE,
                plane=EndpointPlane.USB,
                protocols={Protocol.USB_NCM_SESSION},
                capabilities={Capability.USB_PEER, Capability.USB_SESSION},
                label="USB session source",
                metadata={"transport_adapter": "usb_ncm", "duplex_peer": "usb-session-sink"},
            ))
            endpoints.append(Endpoint(
                id="usb-session-sink",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.USB,
                protocols={Protocol.USB_NCM_SESSION},
                capabilities={Capability.USB_PEER, Capability.USB_SESSION},
                label="USB session sink",
                metadata={"transport_adapter": "usb_ncm", "duplex_peer": "usb-session-source"},
            ))

        if self._has_ancs(evidence):
            capabilities.add(Capability.NOTIFICATIONS_INPUT)
            endpoints.append(Endpoint(
                id="notifications-sink",
                direction=EndpointDirection.SINK,
                plane=EndpointPlane.METADATA,
                protocols={Protocol.BLE_ANCS},
                capabilities={Capability.NOTIFICATIONS_INPUT},
                label="Notifications",
            ))

        capabilities.update(explicit_capabilities)
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
        endpoint_protocols = {
            str(self._enum_value(protocol))
            for endpoint in endpoints
            for protocol in endpoint.protocols
        }
        evidence_sources = []
        if evidence.class_of_device is not None:
            evidence_sources.append("classic_cod")
        if evidence.service_uuids:
            evidence_sources.append("classic_sdp")
        if evidence.ble_services:
            evidence_sources.append("ble_gatt")
        if evidence.capabilities:
            evidence_sources.append("explicit_capabilities")
        if evidence.endpoints:
            evidence_sources.append("explicit_endpoints")
        unknowns = []
        if not evidence.service_uuids:
            unknowns.append("classic_sdp")
        if not evidence.ble_services:
            unknowns.append("ble_gatt")
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
                },
                "capability_profile": {
                    "probe_status": enrollment_state,
                    "evidence_sources": sorted(evidence_sources),
                    "verified_capabilities": sorted(str(self._enum_value(value)) for value in capabilities),
                    "protocols": sorted(endpoint_protocols),
                    "usage_hints": self._usage_hints(capabilities, endpoints),
                    "unknowns": sorted(unknowns),
                },
            },
        )

    def enroll(self, evidence: EnrollmentEvidence) -> TrustedDevice:
        device = self.build_device(evidence)
        existing = self.registry.by_id(device.id)
        if existing is None:
            self.registry.devices.append(device)
        else:
            existing.name = device.name
            existing.capabilities.update(device.capabilities)
            existing.endpoints = self._merge_endpoints(existing.endpoints, device.endpoints)
            existing.constraints.update(device.constraints)
            existing.metadata = self._merge_metadata(existing.metadata, device.metadata)
            device = existing
        return device

    @staticmethod
    def _has_classic_audio_output(evidence: EnrollmentEvidence) -> bool:
        services = {str(value).lower() for value in evidence.service_uuids}
        if "110b" in services or "0x110b" in services or "audio_sink" in services:
            return True
        if evidence.class_of_device is None:
            return False
        return (int(evidence.class_of_device) & 0x1F00) == COD_MAJOR_AUDIO_VIDEO

    @staticmethod
    def _has_le_audio_output(evidence: EnrollmentEvidence) -> bool:
        ble = {str(value).lower() for value in evidence.ble_services}
        return bool(LE_AUDIO_OUTPUT_SERVICES & ble)

    @classmethod
    def _audio_output_protocols(cls, evidence: EnrollmentEvidence) -> set[Protocol]:
        protocols: set[Protocol] = set()
        ble = {str(value).lower() for value in evidence.ble_services}
        if cls._has_classic_audio_output(evidence):
            protocols.add(Protocol.CLASSIC_A2DP_SOURCE)
        if cls._has_le_audio_output(evidence):
            if "fdf0" in ble or "0xfdf0" in ble:
                protocols.add(Protocol.BLE_ASHA_AUDIO)
            else:
                protocols.add(Protocol.BLE_LE_AUDIO_SINK)
        return protocols

    @staticmethod
    def _has_classic_media_source(evidence: EnrollmentEvidence) -> bool:
        services = {str(value).lower() for value in evidence.service_uuids}
        ble = {str(value).lower() for value in evidence.ble_services}
        return bool({
            "110a", "0x110a", "audio_source", "ams", "1812", "0x1812",
        } & (services | ble))

    @staticmethod
    def _has_le_audio_input(evidence: EnrollmentEvidence) -> bool:
        ble = {str(value).lower() for value in evidence.ble_services}
        return bool(LE_AUDIO_INPUT_SERVICES & ble)

    @classmethod
    def _audio_input_protocols(cls, evidence: EnrollmentEvidence) -> set[Protocol]:
        protocols: set[Protocol] = set()
        if cls._has_classic_media_source(evidence):
            protocols.add(Protocol.CLASSIC_A2DP_SINK)
        if cls._has_le_audio_input(evidence):
            protocols.add(Protocol.BLE_LE_AUDIO_SOURCE)
        return protocols

    @staticmethod
    def _has_ancs(evidence: EnrollmentEvidence) -> bool:
        ble = {str(value).lower() for value in evidence.ble_services}
        return "ancs" in ble or "7905f431-b5ce-4e99-a40f-4b1e122d00d0" in ble

    @staticmethod
    def _usage_hints(capabilities: set[Capability], endpoints: list[Endpoint]) -> list[str]:
        hints = set()
        if Capability.AUDIO_INPUT in capabilities:
            hints.add("audio_source")
        if Capability.AUDIO_OUTPUT in capabilities:
            hints.add("audio_sink")
        if Capability.SESSION_PEER in capabilities:
            hints.add("session_peer")
        if Capability.LOCAL_MIC_SOURCE in capabilities:
            hints.add("mic_source")
        if Capability.REMOTE_MIC_RECEIVER in capabilities:
            hints.add("mic_sink")
        if Capability.USB_PEER in capabilities or Capability.USB_SESSION in capabilities:
            hints.add("usb_peer")
        if Capability.PLAYNOW_METADATA in capabilities:
            hints.add("playnow_surface")
        for endpoint in endpoints:
            if endpoint.plane == EndpointPlane.AUDIO and endpoint.direction == EndpointDirection.SOURCE:
                hints.add("audio_source")
            elif endpoint.plane == EndpointPlane.AUDIO and endpoint.direction == EndpointDirection.SINK:
                hints.add("audio_sink")
            elif endpoint.plane == EndpointPlane.SESSION:
                hints.add("session_peer")
            elif endpoint.plane == EndpointPlane.MIC and endpoint.direction == EndpointDirection.SOURCE:
                hints.add("mic_source")
            elif endpoint.plane == EndpointPlane.MIC and endpoint.direction == EndpointDirection.SINK:
                hints.add("mic_sink")
            elif endpoint.plane == EndpointPlane.USB:
                hints.add("usb_peer")
            elif endpoint.plane == EndpointPlane.METADATA:
                hints.add("metadata_surface")
        return sorted(hints)

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

    @staticmethod
    def _merge_metadata(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        merged = dict(base or {})
        for key, value in (extra or {}).items():
            if key == "capability_profile" and isinstance(value, dict):
                current = dict(merged.get(key) or {})
                for list_key in ("evidence_sources", "verified_capabilities", "protocols", "usage_hints"):
                    current[list_key] = sorted(set(current.get(list_key) or []) | set(value.get(list_key) or []))
                unknowns = set(current.get("unknowns") or []) | set(value.get("unknowns") or [])
                evidence_sources = set(current.get("evidence_sources") or [])
                if "classic_sdp" in evidence_sources:
                    unknowns.discard("classic_sdp")
                if "ble_gatt" in evidence_sources:
                    unknowns.discard("ble_gatt")
                current["unknowns"] = sorted(unknowns)
                current["probe_status"] = value.get("probe_status") or current.get("probe_status")
                merged[key] = current
            elif key == "enrollment_evidence" and isinstance(value, dict):
                current = dict(merged.get(key) or {})
                for list_key in ("service_uuids", "ble_services", "missing_capabilities"):
                    current[list_key] = sorted(set(current.get(list_key) or []) | set(value.get(list_key) or []))
                for scalar_key, scalar_value in value.items():
                    if scalar_key not in ("service_uuids", "ble_services", "missing_capabilities"):
                        current[scalar_key] = scalar_value
                merged[key] = current
            else:
                merged[key] = value
        return merged
