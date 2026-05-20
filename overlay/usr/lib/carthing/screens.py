"""The Car Thing desktops. Each composes ui_components over ui_theme; none
calls raw PIL styling or font glyphs (vector icons only). Content starts below
the status bar. Screens read duck-typed state and emit intents via callbacks.
"""
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

    def _visible(self):
        """Flatten to rows: (level, key, label, expandable, expanded)."""
        rows = []
        for it in self.items:
            has_children = "children" in it
            rows.append((0, it["key"], it["label"], has_children, it["key"] in self.expanded))
            if has_children and it["key"] in self.expanded:
                for ckey, clabel in it["children"]:
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
        draw.line([24, CONTENT_TOP + 34, T.W - 24, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

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
