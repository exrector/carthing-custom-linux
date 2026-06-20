"""Trusted peer presence lifecycle.

This module centralizes the "sticky" live-state contract for every trusted
device. It does not discover devices, enroll devices, or build routes. It only
records live evidence from transports that already exist: classic attach,
session attach, USB seen, standby held, route active, disconnect, and timeout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any


PRESENT_STATES = {"seen", "attached", "present_unrouted", "standby", "route_active"}
CONNECTED_STATES = {"attached", "present_unrouted", "standby", "route_active"}
MISSING_STATES = {"missing", "unreachable"}

EVENT_STATE = {
    "bond_seen": "seen",
    "usb_seen": "present_unrouted",
    "session_seen": "present_unrouted",
    "incoming_attach": "present_unrouted",
    "outgoing_attach": "attached",
    "standby_held": "standby",
    "route_active": "route_active",
    "disconnect": "missing",
    "timeout": "missing",
    "unreachable": "unreachable",
}


def normalize_address(address) -> str:
    text = str(address or "").strip().upper()
    return text.split("/", 1)[0]


@dataclass(slots=True)
class PresenceRecord:
    key: str
    address: str = ""
    state: str = "known"
    transports: set[str] = field(default_factory=set)
    planes: set[str] = field(default_factory=set)
    last_event: str = ""
    last_detail: str = ""
    last_seen: float = 0.0
    checked_at: float = 0.0

    @property
    def online(self) -> bool:
        return self.state in PRESENT_STATES

    @property
    def connected(self) -> bool:
        return self.state in CONNECTED_STATES

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "address": self.address,
            "state": self.state,
            "online": self.online,
            "connected": self.connected,
            "transports": sorted(self.transports),
            "planes": sorted(self.planes),
            "last_event": self.last_event,
            "last_detail": self.last_detail,
            "last_seen": self.last_seen,
            "checked_at": self.checked_at,
        }


class TrustedPeerPresence:
    """Central live presence state for trusted devices.

    AppState owns persistent device cards. This object owns the ephemeral "is
    this trusted peer around right now?" layer.
    """

    def __init__(self, app_state):
        self.app_state = app_state
        self.records: dict[str, PresenceRecord] = {}

    def key_for(self, *, key="", address="") -> str:
        address = normalize_address(address)
        return address or str(key or "").strip()

    def note(self, *, key="", address="", event="seen", plane="", transport="", detail="") -> PresenceRecord | None:
        presence_key = self.key_for(key=key, address=address)
        if not presence_key:
            return None
        row = self._find_row(presence_key, address)
        if row is None:
            return None
        address = normalize_address(address or row.get("address"))
        record = self.records.get(presence_key)
        if record is None:
            record = PresenceRecord(key=presence_key, address=address)
            self.records[presence_key] = record
        record.address = address or record.address
        record.last_event = str(event or "seen")
        record.last_detail = str(detail or "")
        record.checked_at = time.time()
        if plane:
            record.planes.add(str(plane))
        if transport:
            record.transports.add(str(transport))
        state = EVENT_STATE.get(record.last_event, "seen")
        record.state = state
        if state in PRESENT_STATES:
            record.last_seen = record.checked_at
        row["online"] = record.online
        row["connected"] = record.connected
        row["presence_state"] = record.state
        row["presence_transports"] = sorted(record.transports)
        row["presence_planes"] = sorted(record.planes)
        return record

    def snapshot(self, devices=None) -> list[dict[str, Any]]:
        rows = list(devices if devices is not None else getattr(self.app_state, "trusted", []) or [])
        out = []
        for row in rows:
            key = self.key_for(key=row.get("key"), address=row.get("address"))
            record = self.records.get(key)
            if record is None:
                record = PresenceRecord(
                    key=key,
                    address=normalize_address(row.get("address")),
                    state="seen" if row.get("online") else "known",
                )
            item = record.as_dict()
            item["device_key"] = row.get("key") or key
            item["label"] = row.get("label") or row.get("address") or key
            item["capabilities"] = list(row.get("capabilities") or [])
            item["endpoints"] = list(row.get("endpoints") or [])
            out.append(item)
        return out

    def _find_row(self, key, address=""):
        address = normalize_address(address or key)
        for row in getattr(self.app_state, "trusted", []) or []:
            row_key = str(row.get("key") or "")
            row_addr = normalize_address(row.get("address"))
            if row_key == key or (address and row_addr == address):
                return row
        return None
