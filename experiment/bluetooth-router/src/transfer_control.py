"""transfer_control — backchannel «команды динамика -> источник» (runtime-contract §Transfer Control Backchannel).

Доверенный динамик (напр. Fosi) с кнопками/AVRCP может управлять воспроизведением.
Его команды нормализуются и уходят НАЗАД на активный источник (iPhone) через iphone_service —
динамик НЕ получает прямой доступ к AMS/профилю iPhone и НЕ владеет GUI.

Цепочка: speaker buttons -> handle_speaker_command(raw) -> normalize -> emit_source_intent ->
iphone_service.command (AMS over BLE) -> iPhone. Три девайса в цепочке, Play на любом.
"""

import logging

logger = logging.getLogger(__name__)

# нормализация вендорных/AVRCP-команд -> канонические intents источника
_NORMALIZE = {
    "play": "play", "pause": "pause", "play_pause": "toggle", "toggle": "toggle",
    "next": "next", "forward": "next", "previous": "prev", "prev": "prev", "backward": "prev",
    "vol_up": "vol_up", "volume_up": "vol_up", "vol_down": "vol_down", "volume_down": "vol_down",
}


class TransferControlBackchannel:
    def __init__(self, emit_source_intent, model=None):
        # emit_source_intent(intent:str) -> отправляет на активный источник (iphone_service.command)
        self.emit = emit_source_intent
        self.model = model

    async def handle_speaker_command(self, speaker_id, raw_command):
        intent = _NORMALIZE.get(str(raw_command).lower().strip())
        if intent is None:
            logger.info("speaker %s: неизвестная команда %r — игнор", speaker_id, raw_command)
            return
        if self.model is not None:
            self.model.add_control_route("speaker_remote", self.model.session.source)
        logger.info("backchannel: speaker_remote(%s) -> source intent %s", speaker_id, intent)
        await self.emit(intent)
