"""Named session presets over the route graph.

These names replace the old product-level "modes". A preset is only a saved
graph recipe; the SessionRunner owns start/stop and adapters own protocols.
"""

from __future__ import annotations

from dataclasses import dataclass

from route_graph import Capability, Constraint, PlannedSession, Protocol, Route


@dataclass(frozen=True, slots=True)
class SessionPreset:
    key: str
    label: str
    description: str
    default: bool = False


PRESETS = [
    SessionPreset("remote", "Remote", "Media control and notifications", default=True),
    SessionPreset("router", "Router", "Choose input and output"),
    SessionPreset("mac", "Mac", "Mac media/control surface"),
    SessionPreset("pairing", "Pairing", "Enroll trusted devices"),
    SessionPreset("quiet", "Quiet", "Idle links, no active media route"),
    SessionPreset("service", "Service", "Diagnostics and USB/NCM safe state"),
]


PRESET_KEYS = {preset.key for preset in PRESETS}
DEFAULT_PRESET = next(preset.key for preset in PRESETS if preset.default)


def normalize_preset(key):
    key = str(key or "").strip()
    if key == "transfer":
        return "router"
    return key if key in PRESET_KEYS else DEFAULT_PRESET


def preset_by_key(key):
    key = normalize_preset(key)
    return next(preset for preset in PRESETS if preset.key == key)


def build_remote_session(source="iphone"):
    return PlannedSession(
        name="remote",
        required_protocols={Protocol.BLE_AMS, Protocol.BLE_ANCS, Protocol.BLE_CTS, Protocol.BLE_HID},
        constraints={Constraint.IDLE_LINK_ALLOWED},
        warnings=[] if source else ["remote session has no selected source"],
    )


def build_quiet_session():
    return PlannedSession(
        name="quiet",
        required_protocols=set(),
        constraints={Constraint.IDLE_LINK_ALLOWED, Constraint.ACTIVE_MEDIA_REQUIRES_ROUTE},
    )


def build_service_session():
    return PlannedSession(
        name="service",
        required_protocols=set(),
        constraints={Constraint.REQUIRES_STOP_BEFORE_START},
    )


def build_mac_session():
    return PlannedSession(
        name="mac",
        required_protocols={Protocol.UI_CONTROL},
        constraints={Constraint.IDLE_LINK_ALLOWED},
    )


def build_router_session(route=None):
    session = PlannedSession(
        name="router",
        required_protocols=set(),
        constraints={Constraint.IDLE_LINK_ALLOWED, Constraint.ACTIVE_MEDIA_REQUIRES_ROUTE},
    )
    if route is not None:
        session.routes.append(route)
    else:
        session.warnings.append("router session has no selected input/output route")
    return session


def build_pairing_session():
    return PlannedSession(
        name="pairing",
        required_protocols=set(),
        constraints={Constraint.REQUIRES_STOP_BEFORE_START},
    )


def build_preset_session(key):
    key = normalize_preset(key)
    if key == "remote":
        return build_remote_session()
    if key == "router":
        return build_router_session()
    if key == "mac":
        return build_mac_session()
    if key == "pairing":
        return build_pairing_session()
    if key == "quiet":
        return build_quiet_session()
    if key == "service":
        return build_service_session()
    return build_remote_session()


def capability_for_preset(key):
    key = normalize_preset(key)
    if key == "remote":
        return Capability.CONTROL_OUTPUT
    if key == "router":
        return Capability.AUDIO_INPUT
    if key == "mac":
        return Capability.METADATA_INPUT
    return None
