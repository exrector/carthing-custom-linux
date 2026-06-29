"""Sparse append-only journal for Bluetooth connection lifecycle events."""

import json
import logging
import os
import time
from pathlib import Path

import state_paths


logger = logging.getLogger(__name__)
DEFAULT_PATH = state_paths.STATE_DIR / "connection-events.jsonl"


def _boot_id():
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except Exception:
        return "unknown"


class ConnectionJournal:
    def __init__(self, path=None):
        self.path = Path(
            path
            or os.environ.get("CARTHING_CONNECTION_JOURNAL", str(DEFAULT_PATH))
        )
        self.boot_id = _boot_id()
        self._warned = False
        self._requires_persistent_mount = self.path == DEFAULT_PATH

    def append(self, event, **fields):
        if self._requires_persistent_mount and not state_paths.persistent_available():
            if not self._warned:
                logger.warning("connection journal unavailable: persistent state not mounted")
                self._warned = True
            return False

        record = {
            "schema": 1,
            "ts": time.time(),
            "monotonic_s": round(time.monotonic(), 6),
            "boot_id": self.boot_id,
            "event": str(event),
        }
        for key, value in fields.items():
            if value is not None:
                record[str(key)] = value

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        record,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    )
                    + "\n"
                )
                handle.flush()
            return True
        except Exception as error:
            if not self._warned:
                logger.warning("connection journal append failed: %s", error)
                self._warned = True
            return False


_journal = ConnectionJournal()


def record_connection_event(event, **fields):
    return _journal.append(event, **fields)
