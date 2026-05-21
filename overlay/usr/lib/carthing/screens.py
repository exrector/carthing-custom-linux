"""The Car Thing desktops. Each composes ui_components over ui_theme; none
calls raw PIL styling or font glyphs (vector icons only). Content starts below
the status bar. Screens read duck-typed state and emit intents via callbacks.
"""
from PIL import ImageDraw

import ui_theme as T
import ui_components as C
from ui_screen import Screen, Input

CONTENT_TOP = T.CONTENT_TOP


def _fmt(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


class NowPlayingScreen(Screen):
    name = "nowplaying"
    title = "iPhone"

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.PRESS, Input.BTN_4):
            self.emit("media_play_pause"); return True
        if event == Input.ENCODER_CW:
            self.emit("media_vol_up"); return True
        if event == Input.ENCODER_CCW:
            self.emit("media_vol_down"); return True
        if event == Input.BTN_2:
            self.emit("media_next"); return True
        if event == Input.BTN_3:
            self.emit("media_prev"); return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        sess = self.state.iphone if self.state else None

        if sess is None or not sess.connected:
            C.text_centered(draw, "Lost Contact", T.font(T.SZ_TITLE), T.WARN, T.MAIN_CY - 30, cx=T.CONTENT_CX)
            C.text_centered(draw, "Awaiting iPhone", T.font(T.SZ_BODY), T.MUTED, T.MAIN_CY + 30, cx=T.CONTENT_CX)
            return img

        # vertically center the now-playing block in the MAIN region
        lines = C.wrap_lines(draw, sess.title or "—", T.font(T.SZ_TITLE), T.CONTENT_W)
        artist = sess.artist or ""
        LH = 56
        block_h = len(lines) * LH + (56 if artist else 0) + 18 + 3 + 30
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_h // 2)
        for line in lines:
            C.text_centered(draw, line, T.font(T.SZ_TITLE), T.FG, y, cx=T.CONTENT_CX); y += LH
        if artist:
            y += 6
            C.text_centered(draw, artist, T.font(T.SZ_BODY), T.MUTED, y, cx=T.CONTENT_CX); y += 50

        bar_y = y + 18
        C.progress_bar(draw, T.CONTENT_X0, bar_y, T.CONTENT_W,
                       (sess.position / sess.duration) if sess.duration else 0)

        time_str = f"{_fmt(sess.position)}  /  {_fmt(sess.duration)}" if sess.duration else ""
        f = T.font(T.SZ_META)
        r = 9
        group = (2 * r + 16 + C.text_w(draw, time_str, f)) if time_str else 2 * r
        gx = T.CONTENT_CX - group // 2
        gy = bar_y + 26
        (T.icon_pause if sess.playing else T.icon_play)(draw, gx + r, gy, r, color=T.FAINT)
        if time_str:
            draw.text((gx + 2 * r + 16, gy - T.SZ_META // 2), time_str, font=f, fill=T.FAINT)
        return img


class MacOSScreen(Screen):
    name = "macos"
    title = "macOS"

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.PRESS, Input.BTN_4):
            self.emit("media_play_pause"); return True
        if event == Input.BTN_2:
            self.emit("media_next"); return True
        if event == Input.BTN_3:
            self.emit("media_prev"); return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        sess = self.state.mac if self.state else None

        if sess is None or not sess.connected:
            C.text_centered(draw, "macOS", T.font(T.SZ_TITLE), T.FG, T.MAIN_CY - 74, cx=T.CONTENT_CX)
            C.text_centered(draw, "Нет связи", T.font(T.SZ_BODY), T.MUTED, T.MAIN_CY - 6, cx=T.CONTENT_CX)
            C.text_centered(draw, "Подключите Mac в настройках", T.font(T.SZ_META),
                            T.FAINT, T.MAIN_CY + 34, cx=T.CONTENT_CX)
            return img

        if not sess.title:
            C.text_centered(draw, "macOS", T.font(T.SZ_TITLE), T.FG, T.MAIN_CY - 30, cx=T.CONTENT_CX)
            C.text_centered(draw, "Готов к воспроизведению", T.font(T.SZ_META), T.FAINT,
                            T.MAIN_CY + 24, cx=T.CONTENT_CX)
            return img

        lines = C.wrap_lines(draw, sess.title, T.font(T.SZ_TITLE), T.CONTENT_W)
        block_h = len(lines) * 56 + (56 if sess.artist else 0) + 20
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_h // 2)
        for line in lines:
            C.text_centered(draw, line, T.font(T.SZ_TITLE), T.FG, y, cx=T.CONTENT_CX); y += 56
        if sess.artist:
            y += 6
            C.text_centered(draw, sess.artist, T.font(T.SZ_BODY), T.MUTED, y, cx=T.CONTENT_CX)
        return img


class SettingsScreen(Screen):
    """Accordion menu: parents expand inline to reveal children. Encoder moves
    selection over the visible (flattened) list; press toggles a parent or
    emits a leaf's intent."""

    name = "settings"
    title = "Настройки"

    def __init__(self, on_select=None):
        self.on_select = on_select or (lambda key: None)
        self.items = [
            {"key": "pairing", "label": "Режим сопряжения"},
            {"key": "trusted", "label": "Доверенные устройства", "children": []},
            {"key": "display", "label": "Дисплей и яркость", "children": [
                ("brightness", "Яркость"),
                ("sleep", "Тайм-аут сна"),
            ]},
            {"key": "about", "label": "О системе"},
        ]
        self.expanded = set()
        self.sel = 0
        self.state = None

    def on_state(self, state):
        self.state = state

    def _children(self, it):
        if it["key"] == "trusted":      # dynamic from the trusted registry
            trusted = self.state.trusted if self.state else []
            if not trusted:
                return [("trusted_empty", "— нет устройств —")]
            return [("trusted:" + d["key"], d["label"] + "  ·  " + d["type"]) for d in trusted]
        return it.get("children", [])

    def _visible(self):
        """Flatten to rows: (level, key, label, expandable, expanded)."""
        rows = []
        for it in self.items:
            has_children = "children" in it
            rows.append((0, it["key"], it["label"], has_children, it["key"] in self.expanded))
            if has_children and it["key"] in self.expanded:
                for ckey, clabel in self._children(it):
                    rows.append((1, ckey, clabel, False, False))
        return rows

    def on_input(self, event):
        rows = self._visible()
        if event == Input.ENCODER_CW:
            self.sel = (self.sel + 1) % len(rows); return True
        if event == Input.ENCODER_CCW:
            self.sel = (self.sel - 1) % len(rows); return True
        if event == Input.PRESS:
            level, key, _label, expandable, expanded = rows[self.sel]
            if expandable:
                self.expanded.symmetric_difference_update({key})
            else:
                self.on_select(key)
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        draw.text((24, CONTENT_TOP - 8), "Настройки", font=T.font(34), fill=T.MUTED)
        draw.line([24, CONTENT_TOP + 34, T.CONTENT_X1, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

        y = CONTENT_TOP + 52
        for i, (level, key, label, expandable, expanded) in enumerate(self._visible()):
            if y + T.ROW_H - 14 > T.OCCLUSION_BOTTOM:    # stay within MAIN band (TODO: scroll)
                break
            rect = C.list_row(draw, y, label, selected=(i == self.sel),
                              expandable=expandable, expanded=expanded,
                              indent=24 if level else 0)
            if regions is not None:
                regions.add(rect, "settings_select", payload=key)
            y += T.ROW_H
        return img


class NotificationsScreen(Screen):
    """Desktop 4 — mirror of iPhone notifications (ANCS). Reached by swipe or by
    tapping the pulsing status-bar indicator."""

    name = "notifications"
    title = "Уведомления"

    def __init__(self):
        self.state = None

    def on_state(self, state):
        self.state = state

    def render(self, regions=None):
        img, draw = self.blank()
        draw.text((24, CONTENT_TOP - 8), "Уведомления", font=T.font(34), fill=T.MUTED)
        draw.line([24, CONTENT_TOP + 34, T.CONTENT_X1, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

        notes = self.state.notifications if self.state else []
        if not notes:
            C.text_centered(draw, "Нет уведомлений", T.font(T.SZ_BODY), T.FAINT, T.MAIN_CY, cx=T.CONTENT_CX)
            return img

        y = CONTENT_TOP + 52
        maxw = T.CONTENT_W - 16
        for n in notes:
            if y + 90 > T.OCCLUSION_BOTTOM:
                break
            draw.text((40, y), n.get("app", ""), font=T.font(T.SZ_SMALL), fill=T.ACCENT)
            draw.text((40, y + 24), C.truncate(draw, n.get("title", ""), T.font(T.SZ_BODY), maxw),
                      font=T.font(T.SZ_BODY), fill=T.FG)
            draw.text((40, y + 58), C.truncate(draw, n.get("message", ""), T.font(T.SZ_META), maxw),
                      font=T.font(T.SZ_META), fill=T.MUTED)
            y += 100
            draw.line([40, y - 14, T.CONTENT_X1, y - 14], fill=T.HAIRLINE, width=1)
        return img


class PairingModal:
    """Live-action overlay: makes the device discoverable and waits for a new
    device to connect from its side. Drawn over the dimmed active desktop.
    Shown while AppState.pairing_mode is True. Emits 'pairing_cancel' to close.
    """

    def __init__(self, emit=None):
        self.emit = emit or (lambda intent, payload=None: None)
        self.state = None

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.BACK, Input.PRESS):
            self.emit("pairing_cancel")
            return True
        return False

    def render(self, img, regions):
        draw = ImageDraw.Draw(img)
        cx = T.CONTENT_CX
        # card background for legibility over the dimmed desktop
        cw, ch = 580, 300
        draw.rounded_rectangle([cx - cw // 2, T.MAIN_CY - ch // 2, cx + cw // 2, T.MAIN_CY + ch // 2],
                               radius=T.RADIUS, fill=T.SURFACE, outline=T.HAIRLINE, width=1)
        C.text_centered(draw, "Режим сопряжения", T.font(T.SZ_TITLE), T.FG, T.MAIN_CY - 92, cx=cx)
        C.text_centered(draw, "Откройте Bluetooth на iPhone или Mac", T.font(T.SZ_META), T.MUTED,
                        T.MAIN_CY - 30, cx=cx)
        C.text_centered(draw, "и выберите «CarThing»", T.font(T.SZ_META), T.MUTED,
                        T.MAIN_CY + 2, cx=cx)
        C.text_centered(draw, "Ожидание подключения…", T.font(T.SZ_SMALL), T.ACCENT,
                        T.MAIN_CY + 44, cx=cx)

        # Cancel button (tappable) — also Back/Press cancels
        bw, bh = 200, 48
        bx0, by0 = cx - bw // 2, T.MAIN_CY + 84
        draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], outline=T.FAINT, width=2)
        C.text_centered(draw, "Отмена", T.font(T.SZ_META), T.MUTED, by0 + 8, cx=cx)
        regions.add((bx0, by0, bx0 + bw, by0 + bh), "pairing_cancel")
