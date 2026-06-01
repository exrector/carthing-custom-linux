"""settings_service — persistent пользовательские/продуктовые настройки (runtime-contract §settings_service).

Хранит settings.json на persistent-разделе (state_paths). Доверенные источники/динамики —
отдельный реестр (trusted-devices.json, им владеет AppState/трекинг), здесь — скалярные
настройки: предпочитаемый view, динамик по умолчанию, политика сна.
"""

import json
import logging

import state_paths

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "preferred_view": "now_playing",   # стартовый view (gui-contract)
    "active_session": "remote",        # route-graph session preset
    "default_speaker": None,           # адрес динамика по умолчанию для Transfer
    "sleep_on_idle": True,             # сон когда нет BT-трафика (ideas-log)
    "screen_dim_after_sec": 45,         # сначала только подсветка, без BT/suspend
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
            if state_paths.SETTINGS_PATH.exists():
                data = json.loads(state_paths.SETTINGS_PATH.read_text() or "{}")
                self.values.update({k: data[k] for k in _DEFAULTS if k in data})
                if "active_session" not in data and "device_mode" in data:
                    self.values["active_session"] = data["device_mode"]
        except Exception as e:
            logger.warning("settings load failed: %s", e)

    def save(self):
        try:
            state_paths.require_persistent()
            data = {k: v for k, v in self.values.items() if _DEFAULTS.get(k) != v}
            state_paths.SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False))
        except Exception as e:
            logger.warning("settings save failed (degraded?): %s", e)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        if key == "device_mode":
            # Legacy write path from older callers: map to active_session.
            key = "active_session"
        self.values[key] = value
        self.save()
