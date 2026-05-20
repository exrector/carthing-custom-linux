"""The Car Thing desktops. Each composes ui_components over ui_theme; none
calls raw PIL styling or font glyphs (vector icons only). Content starts below
the status bar. Screens read duck-typed state and emit intents via callbacks.
"""
import ui_theme as T
import ui_components as C
from ui_screen import Screen, Input

CONTENT_TOP = T.STATUSBAR_H + 16


def _fmt(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


class NowPlayingScreen(Screen):
    name = "nowplaying"
    title = "iPhone"

    def __init__(self, state=None, on_command=None):
        self.state = state
        self.on_command = on_command or (lambda c: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.PRESS, Input.BTN_4):
            self.on_command("play_pause"); return True
        if event == Input.ENCODER_CW:
            self.on_command("vol_up"); return True
        if event == Input.ENCODER_CCW:
            self.on_command("vol_down"); return True
        if event == Input.BTN_2:
            self.on_command("next"); return True
        if event == Input.BTN_3:
            self.on_command("prev"); return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        st = self.state
        connected = getattr(st, "iphone_connected", True) if st else False

        if not connected or st is None:
            C.text_centered(draw, "Lost Contact", T.font(T.SZ_TITLE), T.WARN, T.H // 2 - 60)
            C.text_centered(draw, "Awaiting iPhone", T.font(T.SZ_BODY), T.MUTED, T.H // 2 + 6)
            return img

        y = CONTENT_TOP
        for line in C.wrap_lines(draw, getattr(st, "title", "") or "—",
                                 T.font(T.SZ_TITLE), T.W - 2 * T.MARGIN):
            C.text_centered(draw, line, T.font(T.SZ_TITLE), T.FG, y); y += 56

        artist = getattr(st, "artist", "") or ""
        if artist:
            y += 6
            C.text_centered(draw, artist, T.font(T.SZ_BODY), T.MUTED, y); y += 50

        bar_y = y + 18
        dur = getattr(st, "duration", 0) or 0
        pos = getattr(st, "position", 0) or 0
        C.progress_bar(draw, T.MARGIN, bar_y, T.W - 2 * T.MARGIN,
                       (pos / dur) if dur else 0)

        # meta row: vector play/pause icon + time, centered as a group
        time_str = f"{_fmt(pos)}  /  {_fmt(dur)}" if dur else ""
        f = T.font(T.SZ_META)
        tw = C.text_w(draw, time_str, f)
        r = 9
        group = (2 * r + 16 + tw) if time_str else 2 * r
        gx = (T.W - group) // 2
        gy = bar_y + 26
        if getattr(st, "playing", False):
            T.icon_play(draw, gx + r, gy, r, color=T.FAINT)
        else:
            T.icon_pause(draw, gx + r, gy, r, color=T.FAINT)
        if time_str:
            draw.text((gx + 2 * r + 16, gy - T.SZ_META // 2), time_str, font=f, fill=T.FAINT)
        return img


class MacOSScreen(Screen):
    name = "macos"
    title = "macOS"

    def __init__(self, state=None):
        self.state = state

    def on_state(self, state):
        self.state = state

    def render(self, regions=None):
        img, draw = self.blank()
        C.text_centered(draw, "macOS", T.font(T.SZ_TITLE), T.FG, CONTENT_TOP)
        connected = getattr(self.state, "mac_connected", False) if self.state else False
        if not connected:
            C.text_centered(draw, "Нет связи", T.font(T.SZ_BODY), T.MUTED, T.H // 2 - 12)
            C.text_centered(draw, "Подключите Mac в настройках", T.font(T.SZ_META),
                            T.FAINT, T.H // 2 + 30)
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
            rect = C.list_row(draw, y, label, selected=(i == self.sel),
                              expandable=expandable, expanded=expanded,
                              indent=24 if level else 0)
            if regions is not None:
                regions.add(rect, "settings_select", payload=key)
            y += T.ROW_H
        return img
