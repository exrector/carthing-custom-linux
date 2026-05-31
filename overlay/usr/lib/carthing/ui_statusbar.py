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
    INTENT_ASSISTANT = "assistant"

    # Полный набор кнопок, которые может отдать iPhone (AMS RemoteCommandID), В ПОРЯДКЕ
    # слева→направо. Громкость (5/6) НЕ здесь — это энкодер/дуга. play/pause — всегда (центр).
    # kind -> (AMS cmd id, icon_fn, intent). order: режимы | перемотка | play | перемотка | реакции
    _LAYOUT = [
        ("shuffle",   8,  "icon_shuffle",   "media_shuffle"),
        ("repeat",    7,  "icon_repeat",    "media_repeat"),
        ("skip_back", 10, "icon_skip_back", "media_skip_back"),
        ("prev",      4,  "icon_prev",      "media_prev"),
        ("play",      2,  None,             "media_play_pause"),     # всегда
        ("next",      3,  "icon_next",      "media_next"),
        ("skip_fwd",  9,  "icon_skip_fwd",  "media_skip_fwd"),
        ("like",      11, "icon_heart",     "media_like"),
        ("dislike",   12, "icon_dislike",   "media_dislike"),
        ("bookmark",  13, "icon_bookmark",  "media_bookmark"),
    ]

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

        # ── ВСЕ заявленные приложением кнопки -> в бар (capability-driven) ──────
        # Рисуем каждую команду из _LAYOUT, которую приложение заявило в AMS supported.
        # play — всегда. Если supported пуст (только подключились) — дефолт prev/play/next.
        sup = set(getattr(control, "supported_commands", set()) or set())
        order = []
        for kind, cmd, icon_name, intent in self._LAYOUT:
            if kind == "play":
                order.append((kind, icon_name, intent)); continue
            if sup:
                if cmd in sup:
                    order.append((kind, icon_name, intent))
            elif kind in ("prev", "next"):          # дефолт без supported
                order.append((kind, icon_name, intent))

        # ── динамический размер: чем больше кнопок, тем меньше значки ───────────
        n = len(order)
        usable = T.W - 2 * T.MARGIN
        slot = usable / n
        r = max(11, min(26, int(slot * 0.30)))       # радиус значка масштабируется со слотом
        half = int(min(slot / 2 - 3, 80))            # тап-зона (с запасом, без нахлёста)
        for i, (kind, icon_name, intent) in enumerate(order):
            bx = int(T.MARGIN + slot * (i + 0.5))
            if kind == "play":
                (T.icon_pause if playing else T.icon_play)(draw, bx, cy, r + 3, color=T.FG)
            else:
                getattr(T, icon_name)(draw, bx, cy, r, color=T.FG)
            regions.add((bx - half, cy - half, bx + half, cy + half), intent)
