"""settings_service — persistent пользовательские/продуктовые настройки (runtime-contract §settings_service).

Хранит settings.json на persistent-разделе (state_paths). Доверенные источники/динамики —
отдельный реестр (trusted-devices.json, им владеет AppState/трекинг), здесь — скалярные
настройки: предпочитаемый view, активная сессия, политика сна.
"""

import json
import logging
import os

import state_paths

logger = logging.getLogger(__name__)

_DEFAULTS = {
    "preferred_view": "now_playing",   # стартовый view (gui-contract)
    "active_session": "remote",        # route-graph session preset
    "sleep_on_idle": True,             # сон когда нет BT-трафика (ideas-log)
    "notif_blink": True,               # [CLAUDE 2026-06-03] моргание уведомлений (раньше НЕ грузился -> сбрасывался)
    "volume": 0.5,                     # [CLAUDE 2026-06-03] последняя громкость (восстанавливается на буст)
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
        # [CLAUDE 2026-06-03] Настройки — секция "settings" ЕДИНОГО state.json (один источник
        # правды вместе с devices). Грузим ВСЕ ключи (а не только дефолты), иначе notif_blink и пр.
        # сбрасывались на ребуте.
        try:
            data = state_paths.read_state().get("settings", {})
            if isinstance(data, dict):
                if "active_session" not in data and "device_mode" in data:
                    data["active_session"] = data["device_mode"]
                self.values.update(data)
        except Exception as e:
            logger.warning("settings load failed: %s", e)

    def save(self):
        # [CLAUDE 2026-06-03] Пишем секцию settings в единый state.json (write_state делает
        # read-modify-write + atomic + сохраняет секцию devices). Полный отпечаток всех значений.
        try:
            state_paths.write_state({"settings": dict(self.values)})
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
