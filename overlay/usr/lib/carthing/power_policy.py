"""Idle power policy for the Car Thing userspace.

Stage 1 is deliberately conservative: only the LCD backlight is dimmed/off.
USB, Bluetooth, SSH, and recovery paths stay alive.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


class IdlePowerController:
    def __init__(self, settings=None, backlight_root="/sys/class/backlight"):
        self.settings = settings
        self.backlight = self._find_backlight(Path(backlight_root))
        self.enabled = self._setting("sleep_on_idle", True)
        self.dim_after = float(self._setting("screen_dim_after_sec", 45))
        self.off_after = float(self._setting("screen_off_after_sec", 150))
        self.active_brightness = int(self._setting("screen_active_brightness", 100))
        self.dim_brightness = int(self._setting("screen_dim_brightness", 12))
        self._last_activity = time.monotonic()
        self._last_content_signature = None
        self._state = "init"
        self._max_brightness = self._read_int("max_brightness", default=255)
        self._active_brightness = self.active_brightness
        self._active_brightness = max(1, min(self._active_brightness, self._max_brightness))

        if not self.backlight:
            logger.info("Power: no backlight sysfs; idle policy disabled")
            self.enabled = False
        elif self.enabled:
            logger.info(
                "Power: idle backlight policy active dim=%ss off=%ss active=%s dim_level=%s",
                self.dim_after,
                self.off_after,
                self._active_brightness,
                self.dim_brightness,
            )
            self._set_state("active")

    @staticmethod
    def _find_backlight(root: Path) -> Path | None:
        try:
            for path in sorted(root.iterdir()):
                if (path / "brightness").exists():
                    return path
        except Exception:
            return None
        return None

    def _setting(self, key, default):
        if self.settings is None:
            return default
        try:
            return self.settings.get(key, default)
        except Exception:
            return default

    def _path(self, name: str) -> Path | None:
        return self.backlight / name if self.backlight else None

    def _read_int(self, name: str, default: int) -> int:
        path = self._path(name)
        if path is None:
            return default
        try:
            return int(path.read_text().strip())
        except Exception:
            return default

    def _write_int(self, name: str, value: int) -> None:
        path = self._path(name)
        if path is None:
            return
        try:
            path.write_text(f"{int(value)}\n")
        except Exception as e:
            logger.debug("Power: write %s failed: %s", path, e)

    def _set_state(self, state: str) -> None:
        if not self.enabled or state == self._state:
            return
        if state == "active":
            self._write_int("bl_power", 0)
            self._write_int("brightness", self._active_brightness)
        elif state == "dim":
            self._write_int("bl_power", 0)
            self._write_int("brightness", max(1, min(self.dim_brightness, self._max_brightness)))
        elif state == "off":
            # bl_power is the real panel blanking switch; brightness is kept low
            # so a partially supported driver still dims visibly.
            self._write_int("brightness", 0)
            self._write_int("bl_power", 4)
        else:
            return
        self._state = state
        logger.info("Power: display %s", state)

    def note_activity(self, reason="activity") -> None:
        if not self.enabled:
            return
        self._last_activity = time.monotonic()
        if self._state != "active":
            logger.info("Power: wake by %s", reason)
        self._set_state("active")

    def note_model(self, model) -> None:
        """Wake briefly for meaningful content changes, not for position ticks."""
        if not self.enabled or model is None:
            return
        session = getattr(model, "session", None)
        notifications = getattr(model, "notifications", []) or []
        signature = (
            getattr(session, "connected", None),
            getattr(session, "title", None),
            getattr(session, "artist", None),
            tuple(n.get("uid") for n in notifications if isinstance(n, dict)),
        )
        if self._last_content_signature is None:
            self._last_content_signature = signature
            return
        if signature != self._last_content_signature:
            self._last_content_signature = signature
            self.note_activity("content")

    def tick(self) -> str:
        if not self.enabled:
            return self._state
        idle = time.monotonic() - self._last_activity
        if idle >= self.off_after:
            self._set_state("off")
        elif idle >= self.dim_after:
            self._set_state("dim")
        else:
            self._set_state("active")
        return self._state

    @property
    def display_awake(self) -> bool:
        return self._state != "off"
