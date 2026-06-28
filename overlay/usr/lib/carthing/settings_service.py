"""Persistent settings used by the minimal product."""

import logging

import state_paths


logger = logging.getLogger(__name__)

_DEFAULTS = {
    "client_enabled": False,
    "notif_blink": True,
    "screen_brightness_pct": 100,
    "sleep_on_idle": True,
    "screen_off_after_sec": 150,
    "screen_active_brightness": 100,
    "screen_dim_brightness": 12,
    "runtime_quiet_after_sec": 20,
    "render_interval_active_sec": 0.2,
    "render_interval_quiet_sec": 1.0,
    "render_interval_off_sec": 2.0,
    "publish_interval_active_sec": 1.0,
    "publish_interval_quiet_sec": 10.0,
    "publish_interval_off_sec": 30.0,
}


class SettingsService:
    def __init__(self):
        self.values = dict(_DEFAULTS)
        self.load()

    def load(self):
        try:
            stored = state_paths.read_state().get("settings", {})
            if isinstance(stored, dict):
                for key in _DEFAULTS:
                    if key in stored:
                        self.values[key] = stored[key]
        except Exception as error:
            logger.warning("settings load failed: %s", error)

    def save(self):
        try:
            state_paths.write_state({"settings": dict(self.values)})
        except Exception as error:
            logger.warning("settings save failed: %s", error)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        if key not in _DEFAULTS:
            raise KeyError(f"unsupported setting: {key}")
        self.values[key] = value
        self.save()
