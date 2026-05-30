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
    "default_speaker": None,           # адрес динамика по умолчанию для Transfer
    "sleep_on_idle": True,             # сон когда нет BT-трафика (ideas-log)
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
        except Exception as e:
            logger.warning("settings load failed: %s", e)

    def save(self):
        try:
            state_paths.require_persistent()
            state_paths.SETTINGS_PATH.write_text(json.dumps(self.values, ensure_ascii=False))
        except Exception as e:
            logger.warning("settings save failed (degraded?): %s", e)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value
        self.save()
