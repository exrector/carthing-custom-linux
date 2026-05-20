"""Persistent top status bar — a compositor layer drawn over every desktop.

Items follow one pattern: {state, optional pulse, optional tap->intent}. Today:
clock, iPhone/Mac connection dots, and a pulsing notification indicator that is
tappable (tap -> intent "open_notifications"). Calm/ambient by design: a message
pulses quietly here instead of throwing a banner.
"""
import ui_theme as T


class StatusBar:
    INTENT_NOTIFICATIONS = "open_notifications"

    def render(self, draw, regions, anim, st):
        # background strip + hairline
        draw.rectangle([0, 0, T.W, T.STATUSBAR_H], fill=T.BG)
        draw.line([0, T.STATUSBAR_H, T.W, T.STATUSBAR_H], fill=T.HAIRLINE, width=1)

        cy = T.STATUSBAR_H // 2
        f = T.font(T.SZ_SMALL)

        # left: clock
        clock = getattr(st, "clock_text", "") or "--:--"
        draw.text((T.MARGIN - 16, cy - T.SZ_SMALL // 2 - 2), clock, font=f, fill=T.MUTED)

        # right cluster, laid out right-to-left
        x = T.W - (T.MARGIN - 16)

        # notification indicator (pulses when unread)
        unread = getattr(st, "unread_count", 0) or 0
        if unread > 0:
            a = anim.pulse_alpha()
            col = tuple(int(c * a) for c in T.ACCENT)
            r = 7
            T.icon_dot(draw, x - r, cy, r, color=col)
            # generous tap target around the dot
            regions.add((x - r - 16, 0, x + 8, T.STATUSBAR_H),
                        self.INTENT_NOTIFICATIONS)
            if unread > 1:
                draw.text((x - r - 14 - 18, cy - T.SZ_SMALL // 2 - 2),
                          str(unread), font=f, fill=T.MUTED)
                x -= 24
            x -= (2 * r + 22)

        # connection dots: iPhone, Mac
        for label, connected in (("M", getattr(st, "mac_connected", False)),
                                 ("i", getattr(st, "iphone_connected", False))):
            col = T.ACCENT if connected else T.FAINT
            T.icon_dot(draw, x - 5, cy, 5, color=col)
            draw.text((x - 5 - 6, cy - T.SZ_SMALL // 2 - 2), "", font=f, fill=col)
            x -= 26
