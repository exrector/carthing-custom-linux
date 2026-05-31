"""Bottom bar (full-width bottom band [OCCLUSION_BOTTOM..H]).

ВСЯ ширина бара отдана под медиа-транспорт (решение пользователя 2026-05-31): часы и
кнопка ассистента убраны, чтобы все приходящие с iPhone кнопки (AMS supported-список)
помещались и раскладывались динамически по слотам во всю ширину. Сверху — линия-делитель,
она же прогресс трека. Часы/ассистент переедут в другое место (Фаза 5).
"""
import ui_theme as T


class StatusBar:
    INTENT_NOTIFICATIONS = "open_notifications"
    INTENT_PLAY_PAUSE = "media_play_pause"
    INTENT_PREV = "media_prev"
    INTENT_NEXT = "media_next"
    INTENT_SKIP_BACK = "media_skip_back"
    INTENT_SKIP_FWD = "media_skip_fwd"
    INTENT_ASSISTANT = "assistant"

    # AMS RemoteCommandID (дублируем как простые int, чтобы UI-слой не тянул ams_client).
    _CMD_NEXT, _CMD_PREV, _CMD_SKIP_FWD, _CMD_SKIP_BACK = 3, 4, 9, 10

    # рисовалки кнопок: kind -> (функция-иконка, intent, радиус)
    def _buttons(self):
        return {
            "skip_back": (T.icon_skip_back, self.INTENT_SKIP_BACK, 23),
            "prev":      (T.icon_prev,      self.INTENT_PREV,      24),
            "next":      (T.icon_next,      self.INTENT_NEXT,      24),
            "skip_fwd":  (T.icon_skip_fwd,  self.INTENT_SKIP_FWD,  23),
        }

    def render(self, draw, regions, anim, st):
        bar_top = T.STATUSBAR_TOP
        draw.rectangle([0, bar_top, T.W, T.H], fill=T.BG)

        cy = bar_top + (T.H - bar_top) // 2 + 6   # вертикальный центр транспорта

        control = getattr(st, "control_source", None)   # MediaSession the transport drives
        playing = control.playing if control else False

        # ── верхний делитель = линия прогресса трека (на всю ширину) ───────────
        pct = 0.0
        if control is not None and getattr(control, "duration", 0):
            pct = min(control.position / control.duration, 1.0)
        T.progress_segments(draw, 0, bar_top, T.W, pct)

        # ── динамический набор кнопок из AMS supported-списка ───────────────────
        # Порядок слева→направо: skip_back, prev, [play], next, skip_fwd. Рисуем только
        # заявленные приложением; play/pause всегда. Раскладка — равномерно по слотам
        # ВО ВСЮ ШИРИНУ бара (часы/ассистент убраны, чтобы влезали все 5 знаков).
        sup = set(getattr(control, "supported_commands", set()) or set())
        order = []
        if self._CMD_SKIP_BACK in sup:
            order.append("skip_back")
        if (not sup) or self._CMD_PREV in sup:
            order.append("prev")
        order.append("play")
        if (not sup) or self._CMD_NEXT in sup:
            order.append("next")
        if self._CMD_SKIP_FWD in sup:
            order.append("skip_fwd")

        n = len(order)
        usable = T.W - 2 * T.MARGIN
        slot = usable / n
        half = int(min(slot / 2 - 4, 80))            # ширина тап-зоны (с запасом, но не нахлёст)
        btns = self._buttons()
        for i, kind in enumerate(order):
            bx = int(T.MARGIN + slot * (i + 0.5))
            if kind == "play":
                (T.icon_pause if playing else T.icon_play)(draw, bx, cy, 30, color=T.FG)
                regions.add((bx - half, cy - half, bx + half, cy + half), self.INTENT_PLAY_PAUSE)
            else:
                icon_fn, intent, r = btns[kind]
                icon_fn(draw, bx, cy, r, color=T.FG)
                regions.add((bx - half, cy - half, bx + half, cy + half), intent)
