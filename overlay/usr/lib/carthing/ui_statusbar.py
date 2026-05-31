"""Bottom bar (full-width bottom band [OCCLUSION_BOTTOM..H]).

Holds persistent, always-functional media transport (prev / play-pause / next),
a clock, a notification indicator, and a SOURCE label showing which device the
transport currently controls (resolves the multi-device routing ambiguity).
Items follow {state, optional pulse, optional tap->intent}. Calm, no banners.
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

    def render(self, draw, regions, anim, st):
        bar_top = T.STATUSBAR_TOP
        draw.rectangle([0, bar_top, T.W, T.H], fill=T.BG)

        cy = bar_top + (T.H - bar_top) // 2 + 6   # transport row (dots sit above)
        cx = T.W // 2                              # full-width bar -> true center
        f = T.font(T.SZ_BAR)

        control = getattr(st, "control_source", None)   # MediaSession the transport drives
        playing = control.playing if control else False

        # ── top divider doubles as the now-playing progress line ───────────────
        # Fixed position (never reflows with long titles); segmented in the same
        # visual language as the dial — fills left→right by track position.
        pct = 0.0
        if control is not None and getattr(control, "duration", 0):
            pct = min(control.position / control.duration, 1.0)
        T.progress_segments(draw, 0, bar_top, T.W, pct)

        # ── media transport (center) — рисуем ТОЛЬКО то, что приложение реально
        # поддерживает (AMS RemoteCommand-список). Music: prev/play/next; Podcasts:
        # skip_back/play/skip_fwd (+ может next/prev). Play/Pause — всегда. ─────────
        sup = set(getattr(control, "supported_commands", set()) or set())
        # порядок слева→направо; play/pause всегда в середине
        order = []
        if not sup or self._CMD_SKIP_BACK in sup:
            if self._CMD_SKIP_BACK in sup:
                order.append("skip_back")
        if not sup or self._CMD_PREV in sup:
            order.append("prev")
        order.append("play")
        if not sup or self._CMD_NEXT in sup:
            order.append("next")
        if self._CMD_SKIP_FWD in sup:
            order.append("skip_fwd")
        # если supported пуст (только что подключились) — дефолт prev/play/next уже собран

        gap = 120 if len(order) >= 4 else 140
        n = len(order)
        start = cx - gap * (n - 1) / 2
        for i, kind in enumerate(order):
            bx = int(start + i * gap)
            if kind == "play":
                if playing:
                    T.icon_pause(draw, bx, cy, 28, color=T.FG)
                else:
                    T.icon_play(draw, bx, cy, 28, color=T.FG)
                regions.add((bx - 42, cy - 42, bx + 42, cy + 42), self.INTENT_PLAY_PAUSE)
            elif kind == "prev":
                T.icon_prev(draw, bx, cy, 23, color=T.FG)
                regions.add((bx - 36, cy - 36, bx + 36, cy + 36), self.INTENT_PREV)
            elif kind == "next":
                T.icon_next(draw, bx, cy, 23, color=T.FG)
                regions.add((bx - 36, cy - 36, bx + 36, cy + 36), self.INTENT_NEXT)
            elif kind == "skip_back":
                T.icon_skip_back(draw, bx, cy, 22, color=T.FG)
                regions.add((bx - 36, cy - 36, bx + 36, cy + 36), self.INTENT_SKIP_BACK)
            elif kind == "skip_fwd":
                T.icon_skip_fwd(draw, bx, cy, 22, color=T.FG)
                regions.add((bx - 36, cy - 36, bx + 36, cy + 36), self.INTENT_SKIP_FWD)

        # ── clock (left) ──────────────────────────────────────────────────────
        clock = getattr(st, "clock_text", "") or "--:--"
        draw.text((T.MARGIN - 16, cy - T.SZ_BAR // 2 - 2), clock, font=f, fill=T.MUTED)

        # ── right: assistant button (ВМЕСТО подписи источника) ────────────────
        # Подпись iPhone/Mac убрана. Индикатор уведомлений — НЕ здесь, а в мини-зоне
        # под энкодером (Compositor рисует белый пульс при непрочитанном ANCS).
        x = T.W - (T.MARGIN - 16)

        # Виджет ассистента (Фаза 5): орб с состояниями. Сейчас место + состояния + тап.
        astate = getattr(st, "assistant_state", "idle")
        ar = 13
        acx, acy = x - ar, cy
        box = [acx - ar, acy - ar, acx + ar, acy + ar]
        if astate == "idle":
            draw.ellipse(box, outline=T.FAINT, width=2)
        elif astate == "responding":
            draw.ellipse(box, fill=T.ACCENT)
        else:  # listening / thinking — пульсируют
            a = anim.pulse_alpha()
            base = T.ACCENT if astate == "listening" else T.MUTED
            draw.ellipse(box, fill=tuple(int(c * a) for c in base))
        regions.add((acx - ar - 8, bar_top, x + 8, T.H), self.INTENT_ASSISTANT)
