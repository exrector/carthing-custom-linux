"""Runtime power policy for the Car Thing userspace.

The controller intentionally keeps transport links alive. Power saving starts
above Bluetooth/USB: backlight, render cadence, heartbeat publish cadence, and
mode-aware UI wakeups. A bonded iPhone should be connected-but-quiet, not forced
through disconnect/reconnect loops.
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
        self.quiet_after = float(self._setting("runtime_quiet_after_sec", 20))
        self.active_brightness = int(self._setting("screen_active_brightness", 100))
        self.dim_brightness = int(self._setting("screen_dim_brightness", 12))
        self.render_interval_active = float(self._setting("render_interval_active_sec", 0.2))
        self.render_interval_quiet = float(self._setting("render_interval_quiet_sec", 1.0))
        self.render_interval_off = float(self._setting("render_interval_off_sec", 2.0))
        self.publish_interval_active = float(self._setting("publish_interval_active_sec", 1.0))
        self.publish_interval_quiet = float(self._setting("publish_interval_quiet_sec", 10.0))
        self.publish_interval_off = float(self._setting("publish_interval_off_sec", 30.0))
        self._last_activity = time.monotonic()
        self._last_publish = 0.0
        self._last_content_signature = None
        self._display_state = "init"
        self._runtime_tier = "boot"
        self._active_session = "remote"
        self._pairing_armed = False
        self._transfer_active = False
        self._transfer_scanning_until = 0.0
        self._max_brightness = self._read_int("max_brightness", default=255)
        self._active_brightness = self.active_brightness
        self._active_brightness = max(1, min(self._active_brightness, self._max_brightness))

        if not self.backlight:
            logger.info("Power: no backlight sysfs; idle policy disabled")
            self.enabled = False
        elif self.enabled:
            logger.info(
                "Power: runtime policy active dim=%ss off=%ss quiet=%ss active=%s dim_level=%s",
                self.dim_after,
                self.off_after,
                self.quiet_after,
                self._active_brightness,
                self.dim_brightness,
            )
            self._set_display_state("active")

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

    def _set_display_state(self, state: str) -> None:
        if not self.enabled or state == self._display_state:
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
        self._display_state = state
        logger.info("Power: display %s", state)

    def _set_runtime_tier(self, tier: str) -> None:
        if tier == self._runtime_tier:
            return
        self._runtime_tier = tier
        logger.info("Power: runtime tier %s", tier)

    def note_activity(self, reason="activity") -> None:
        if not self.enabled:
            return
        self._last_activity = time.monotonic()
        if self._display_state != "active":
            logger.info("Power: wake by %s", reason)
        self._set_display_state("active")

    def set_pairing(self, armed: bool) -> None:
        armed = bool(armed)
        if armed == self._pairing_armed:
            return
        self._pairing_armed = armed
        self.note_activity("pairing" if armed else "pairing_done")

    def set_idle_sleep(self, on: bool) -> None:
        """[CLAUDE 2026-06-01] Рантайм-переключатель сна экрана из Settings. off -> экран ВСЕГДА
        включён на полной яркости (для отладки); при enabled=False tick/dim/_set_display_state no-op."""
        if self.backlight is None:
            self.enabled = False
            return
        on = bool(on)
        if on == self.enabled:
            return
        self.enabled = on
        if on:
            self._last_activity = time.monotonic()
            self._display_state = "init"           # форсим применение "active"
            self._set_display_state("active")
            logger.info("Power: idle sleep ENABLED (settings)")
        else:
            self._write_int("bl_power", 0)
            self._write_int("brightness", self._active_brightness)
            self._display_state = "active"
            logger.info("Power: idle sleep DISABLED (settings) — screen stays on")

    def set_off_after(self, sec) -> None:
        """[CLAUDE 2026-06-01] Рантайм-настройка тайм-аута полного гашения экрана (Settings ±)."""
        try:
            self.off_after = max(30.0, float(sec))
        except (TypeError, ValueError):
            return
        self._last_activity = time.monotonic()   # перезапустить отсчёт от изменения
        logger.info("Power: screen-off timeout -> %ss", self.off_after)

    def set_active_session(self, session: str) -> None:
        session = session or "remote"
        if session == self._active_session:
            return
        self._active_session = session
        if session != "quiet":
            self.note_activity(f"session:{session}")

    def set_device_mode(self, mode: str) -> None:
        # Legacy wrapper while callers migrate to set_active_session.
        self.set_active_session(mode)

    def note_transfer_scan(self, hold_sec: float = 20.0) -> None:
        if not self.enabled:
            return
        self._transfer_scanning_until = max(
            self._transfer_scanning_until,
            time.monotonic() + max(1.0, float(hold_sec)),
        )
        self.note_activity("transfer_scan")

    def note_model(self, model) -> None:
        """Wake briefly for meaningful content changes, not for position ticks."""
        if not self.enabled or model is None:
            return
        session = getattr(model, "session", None)
        notifications = getattr(model, "notifications", []) or []
        self._transfer_active = bool(getattr(model, "transfer_active", False))
        signature = (
            getattr(session, "source", None),
            getattr(session, "connected", None),
            getattr(session, "title", None),
            getattr(session, "artist", None),
            getattr(session, "playing", None),
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
            return self._display_state
        now = time.monotonic()
        idle = now - self._last_activity
        if self._active_session == "quiet":
            idle = max(idle, self.quiet_after)
        scanning = now < self._transfer_scanning_until

        if self._pairing_armed:
            self._set_runtime_tier("pairing")
        elif self._transfer_active or scanning:
            self._set_runtime_tier("transfer")
        elif idle >= self.off_after:
            self._set_runtime_tier("screen_off")
        elif idle >= self.quiet_after:
            self._set_runtime_tier("connected_quiet")
        else:
            self._set_runtime_tier("interactive")

        if self._pairing_armed:
            self._set_display_state("active")
        elif idle >= self.off_after:
            self._set_display_state("off")
        else:
            # [CLAUDE 2026-06-01] Стадия "dim" УБРАНА: на панели aml-bl яркость 12/255 визуально
            # не темнеет (драйвер принимает значение, но подсветка не меняется перцептивно), а
            # запись только давала «моргание» + иногда будилась "content". Теперь: active -> сразу
            # off на off_after. dim_after/dim_brightness больше не применяются (оставлены в
            # настройках на случай панели с рабочим PWM).
            self._set_display_state("active")
        return self._display_state

    @property
    def runtime_tier(self) -> str:
        return self._runtime_tier

    @property
    def render_interval(self) -> float:
        if self._display_state == "off":
            return self.render_interval_off
        if self._runtime_tier in ("connected_quiet", "screen_off") or self._display_state == "dim":
            return self.render_interval_quiet
        return self.render_interval_active

    def should_publish(self) -> bool:
        now = time.monotonic()
        if self._last_publish <= 0:
            self._last_publish = now
            return True
        if self._runtime_tier == "screen_off" or self._display_state == "off":
            interval = self.publish_interval_off
        elif self._runtime_tier == "connected_quiet":
            interval = self.publish_interval_quiet
        else:
            interval = self.publish_interval_active
        if now - self._last_publish >= interval:
            self._last_publish = now
            return True
        return False

    @property
    def display_awake(self) -> bool:
        return self._display_state != "off"
