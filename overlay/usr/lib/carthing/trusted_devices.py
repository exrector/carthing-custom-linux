"""Trusted Bluetooth peers grouped by runtime role."""

import json
import os
from pathlib import Path


DEFAULT_TRUSTED_DEVICES_PATH = "/run/carthing-state/carthing/trusted-devices.json"


def trusted_devices_path() -> Path:
    return Path(os.environ.get("CARTHING_TRUSTED_DEVICES", DEFAULT_TRUSTED_DEVICES_PATH))


def normalize_address(address) -> str:
    text = str(address).strip().upper()
    return text.split("/", 1)[0]


class TrustedDevices:
    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path is not None else trusted_devices_path()
        self.sources: dict[str, dict] = {}
        self.speakers: dict[str, dict] = {}
        self.reload()

    def reload(self):
        self.sources = {}
        self.speakers = {}
        try:
            data = json.loads(self.path.read_text())
        except FileNotFoundError:
            return
        except Exception:
            return

        for role in ("sources", "speakers"):
            peers = data.get(role, [])
            if isinstance(peers, dict):
                peers = [{"address": address, **details} for address, details in peers.items()]
            for peer in peers:
                address = peer.get("address") if isinstance(peer, dict) else peer
                if not address:
                    continue
                target = self.sources if role == "sources" else self.speakers
                target[normalize_address(address)] = dict(peer) if isinstance(peer, dict) else {"address": address}

    @property
    def has_sources(self) -> bool:
        return bool(self.sources)

    @property
    def has_speakers(self) -> bool:
        return bool(self.speakers)

    def is_source(self, address) -> bool:
        return normalize_address(address) in self.sources

    def is_speaker(self, address) -> bool:
        return normalize_address(address) in self.speakers

    def first_speaker_address(self) -> str | None:
        for address in self.speakers:
            return address
        return None

    def speaker_list(self) -> list[dict]:
        return list(self.speakers.values())
