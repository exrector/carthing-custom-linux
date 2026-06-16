"""Bottom bar (full-width bottom band [OCCLUSION_BOTTOM..H]).

ВСЯ ширина бара отдана под медиа-транспорт (решение пользователя 2026-05-31): часы и
кнопка ассистента убраны, чтобы кнопки, приходящие с iPhone (AMS supported-список),
раскладывались по слотам во всю ширину. Сверху — линия-делитель = прогресс трека.

Значки рисуются ВЫСОКОКАЧЕСТВЕННЫМИ глифами (super-sampling 4×, ui_theme.paste_glyph) —
без «лесенки». Набор сокращён по решению пользователя: перемотка ±, треки, play и ОДНО
сердце-тумблер (избранное). Shuffle/Repeat/Bookmark/отдельный Dislike убраны.
"""
from PIL import ImageDraw

import ui_components as C
import ui_theme as T


class StatusBar:
    INTENT_NOTIFICATIONS = "open_notifications"
    INTENT_PLAY_PAUSE = "media_play_pause"
    INTENT_ASSISTANT = "assistant"

    # Порядок слева→направо: (kind, AMS cmd id, intent). Громкость (5/6) НЕ здесь — энкодер.
    # play — всегда (центр). like = ТОЛЬКО добавить в избранное (без снятия): контур = ещё не
    # лайкал в этой сессии, залит = лайкнул. Тап всегда лайкает (если уже в избранном — безвреден).
    _LAYOUT = [
        ("skip_back", 10, "media_skip_back"),
        ("prev",       4, "media_prev"),
        ("play",       2, "media_play_pause"),
        ("next",       3, "media_next"),
        ("skip_fwd",   9, "media_skip_fwd"),
        ("like",      11, "media_like"),
    ]

    def render(self, img, regions, anim, st):
        draw = ImageDraw.Draw(img)
        bar_top = T.STATUSBAR_TOP
        draw.rectangle([0, bar_top, T.W, T.H], fill=T.BG)
        cy = bar_top + (T.H - bar_top) // 2 + 6   # вертикальный центр транспорта

        control = getattr(st, "control_source", None)   # MediaSession the transport drives
        playing = control.playing if control else False
        liked = bool(getattr(control, "liked", False)) if control else False

        # ── верхний делитель = линия прогресса трека (на всю ширину) ───────────
        pct = 0.0
        if control is not None and getattr(control, "duration", 0):
            pct = min(control.position / control.duration, 1.0)
        T.progress_segments(draw, 0, bar_top, T.W, pct)

        # [CLAUDE 2026-06-02] pill «Роутер: idle» удалён из главного бара — реликт прошлых
        # сессий. Маршрут теперь живёт в собственном вью (свайп вправо), дублировать его
        # статус в баре Play Now не нужно.

        # ── заявленные приложением кнопки -> в бар (capability-driven) ──────────
        sup = set(getattr(control, "supported_commands", set()) or set())
        order = []
        for kind, cmd, intent in self._LAYOUT:
            if kind == "play":
                order.append((kind, intent)); continue
            if sup:
                if cmd in sup:
                    order.append((kind, intent))
            elif kind in ("prev", "next"):          # дефолт без supported
                order.append((kind, intent))

        # ── равномерная раскладка по слотам; размер значка масштабируется ───────
        n = len(order)
        usable = T.W - 2 * T.MARGIN
        slot = usable / n
        size = int(max(28, min(56, slot * 0.62)))     # пиксельный размер глифа
        half = int(min(slot / 2 - 3, 80))             # тап-зона (с запасом, без нахлёста)
        # [CLAUDE 2026-06-11] Терминальная тема: ТРЁХБУКВЕННЫЕ подписи вместо глифов
        # (идея владельца: старые терминалы не знали значков — только сокращения).
        # Активное действие (play/pause) — полный фосфор, остальные — dim.
        TERM_LABELS = {"skip_back": "RWD", "prev": "PRV", "next": "NXT",
                       "skip_fwd": "FWD", "like": "FAV"}
        for i, (kind, intent) in enumerate(order):
            bx = int(T.MARGIN + slot * (i + 0.5))
            if T.THEME == "terminal":
                if kind == "play":
                    label, col = ("PSE" if playing else "PLY"), T.FG
                elif kind == "like":
                    label, col = "FAV", (T.STATUS_OFF if liked else T.MUTED)
                else:
                    label, col = TERM_LABELS[kind], T.MUTED
                f = T.font(T.SZ_BAR)
                tw = draw.textlength(label, font=f)
                draw.text((bx - tw / 2, cy - T.SZ_BAR // 2 - 2), label, font=f, fill=col)
            elif kind == "play":
                T.paste_glyph(img, T.glyph_pause if playing else T.glyph_play,
                              bx, cy, size + 6, T.FG)
            elif kind == "skip_back":
                T.paste_glyph(img, T.glyph_skip_fwd, bx, cy, size, T.FG, mirror=True)
            elif kind == "skip_fwd":
                T.paste_glyph(img, T.glyph_skip_fwd, bx, cy, size, T.FG)
            elif kind == "prev":
                T.paste_glyph(img, T.glyph_prev, bx, cy, size, T.FG)
            elif kind == "next":
                T.paste_glyph(img, T.glyph_next, bx, cy, size, T.FG)
            elif kind == "like":
                if liked:
                    T.paste_glyph(img, T.glyph_heart_filled, bx, cy, size, T.STATUS_OFF)
                else:
                    T.paste_glyph(img, T.glyph_heart, bx, cy, size, T.FG)
            regions.add((bx - half, cy - half, bx + half, cy + half), intent)
