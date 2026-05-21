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

        # ── media transport (center) ──────────────────────────────────────────
        gap = 140
        T.icon_prev(draw, cx - gap, cy, 23, color=T.FG)
        regions.add((cx - gap - 36, cy - 36, cx - gap + 36, cy + 36), self.INTENT_PREV)

        if playing:
            T.icon_pause(draw, cx, cy, 28, color=T.FG)
        else:
            T.icon_play(draw, cx, cy, 28, color=T.FG)
        regions.add((cx - 42, cy - 42, cx + 42, cy + 42), self.INTENT_PLAY_PAUSE)

        T.icon_next(draw, cx + gap, cy, 23, color=T.FG)
        regions.add((cx + gap - 36, cy - 36, cx + gap + 36, cy + 36), self.INTENT_NEXT)

        # ── clock (left) ──────────────────────────────────────────────────────
        clock = getattr(st, "clock_text", "") or "--:--"
        draw.text((T.MARGIN - 16, cy - T.SZ_BAR // 2 - 2), clock, font=f, fill=T.MUTED)

        # ── right: source label + notification ───────────────────────────────
        x = T.W - (T.MARGIN - 16)
        unread = getattr(st, "unread_count", 0) or 0
        if unread > 0:
            a = anim.pulse_alpha()
            col = tuple(int(c * a) for c in T.ACCENT)
            T.icon_dot(draw, x - 7, cy, 7, color=col)
            regions.add((x - 7 - 18, bar_top, x + 10, T.H), self.INTENT_NOTIFICATIONS)
            x -= 30

        # source the transport controls (e.g. "iPhone" / "Mac")
        label = control.label if control else ""
        if label:
            b = draw.textbbox((0, 0), label, font=f)
            draw.text((x - (b[2] - b[0]), cy - T.SZ_BAR // 2 - 2), label, font=f, fill=T.FAINT)
