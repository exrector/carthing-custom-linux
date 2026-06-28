"""Minimal Car Thing product screens.

The device exposes only Play Now, Assistant, Notifications, Settings, and the
iPhone pairing modal. Transport and route-builder surfaces do not belong here.
"""

import time

from PIL import Image, ImageDraw

import ui_components as C
import ui_theme as T
from ui_screen import Input, Screen


def _title(draw, text):
    draw.text((28, 16), text, font=T.font(34), fill=T.MUTED)
    draw.line((28, 62, T.ARC_SAFE_X, 62), fill=T.HAIRLINE, width=2)


class NowPlayingScreen(Screen):
    name = "playnow"
    title = "Play Now"

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.PRESS, Input.BTN_4):
            self.emit("media_play_pause")
            return True
        if event == Input.BTN_2:
            self.emit("media_next")
            return True
        if event == Input.BTN_3:
            self.emit("media_prev")
            return True
        return False

    def _artist(self, img, draw, text, y):
        text = str(text or "").strip()
        if not text:
            return
        font = T.font(T.SZ_BODY)
        if C.text_w(draw, text, font) <= T.CONTENT_W:
            C.text_centered(draw, text, font, T.MUTED, y, cx=T.CONTENT_CX)
            return
        layer = Image.new("RGBA", (T.CONTENT_W, 44), (0, 0, 0, 0))
        layer_draw = ImageDraw.Draw(layer)
        width = C.text_w(layer_draw, text, font)
        gap = 96
        cycle = 1.4 + (width + gap) / 28.0
        phase = time.monotonic() % cycle
        offset = 0 if phase < 1.4 else int((phase - 1.4) * 28.0)
        layer_draw.text((-offset, 0), text, font=font, fill=T.MUTED)
        layer_draw.text((width + gap - offset, 0), text, font=font, fill=T.MUTED)
        img.paste(layer.convert("RGB"), (T.CONTENT_CX - T.CONTENT_W // 2, y), layer)

    def render(self, regions=None):
        img, draw = self.blank()
        session = self.state.iphone if self.state else None
        if session is None or not session.connected:
            C.text_centered(
                draw, "-", T.font(56), T.FAINT, T.MAIN_CY - 20, cx=T.CONTENT_CX
            )
            return img

        lines = C.wrap_lines(
            draw, session.title or "-", T.font(T.SZ_TITLE), T.CONTENT_W
        )
        lines = lines[:4]
        if len(lines) == 4:
            lines[-1] = C.truncate(
                draw, lines[-1], T.font(T.SZ_TITLE), T.CONTENT_W
            )
        artist = str(session.artist or "").strip()
        block_height = len(lines) * 56 + (50 if artist else 0)
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_height // 2)
        for line in lines:
            C.text_centered(
                draw, line, T.font(T.SZ_TITLE), T.FG, y, cx=T.CONTENT_CX
            )
            y += 56
        if artist:
            self._artist(img, draw, artist, y + 6)
        return img


class AssistantScreen(Screen):
    name = "assistant"
    title = "Ассистент"
    fullscreen = True

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event in (Input.PRESS, Input.BTN_4):
            self.emit("remote_mic_toggle")
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        right = T.ARC_SAFE_X
        enabled = bool(getattr(self.state, "remote_mic_enabled", False))
        state = str(getattr(self.state, "remote_mic_state", "off") or "off")
        _title(draw, "Ассистент")

        button = (right - 178, 10, right - 10, 54)
        draw.rectangle(button, fill=T.STATUS_OK if enabled else T.SURFACE_SEL)
        C.text_centered(
            draw,
            "МИКРОФОН ВКЛ" if enabled else "МИКРОФОН ВЫКЛ",
            T.font(T.SZ_SMALL),
            T.BG if enabled else T.FG,
            23,
            cx=(button[0] + button[2]) // 2,
        )
        if regions is not None:
            regions.add(button, "remote_mic_toggle")

        status = {
            "off": "Микрофон выключен",
            "connecting": "Подключение к Mac",
            "ready": "Готов",
            "listening": "Слушаю",
            "unavailable": "Mac недоступен",
        }.get(state, state)
        live = str(getattr(self.state, "assistant_status", "") or "")
        draw.text(
            (28, 82),
            live or status,
            font=T.font(T.SZ_META),
            fill=T.ACCENT if enabled else T.FAINT,
        )

        transcript = list(getattr(self.state, "assistant_transcript", []) or [])
        live_text = str(getattr(self.state, "assistant_live_text", "") or "").strip()
        live_target = str(
            getattr(self.state, "assistant_live_target", "") or ""
        ).strip()
        font = T.font(T.SZ_BODY)
        lines = []
        for utterance in transcript:
            lines.extend(
                C.wrap_lines(draw, str(utterance), font, right - 64)
                or [str(utterance)]
            )
        committed_line_count = len(lines)
        if live_text:
            cursor = "_" if live_target else ""
            lines.extend(
                C.wrap_lines(draw, f"Вы: {live_text}{cursor}", font, right - 64)
                or [f"Вы: {live_text}{cursor}"]
            )
        top = 128
        bottom = T.H - 18
        line_height = 40
        visible = lines[-max(1, (bottom - top) // line_height):]
        y = bottom - len(visible) * line_height
        for index, line in enumerate(visible):
            absolute_index = len(lines) - len(visible) + index
            is_live = live_text and absolute_index >= committed_line_count
            draw.text(
                (28, y),
                line,
                font=font,
                fill=T.ACCENT if is_live else (
                    T.FG if index == len(visible) - 1 else T.MUTED
                ),
            )
            y += line_height
        return img


class SettingsScreen(Screen):
    name = "settings"
    title = "Настройки"
    fullscreen = True
    ROW_HEIGHT = 70

    def __init__(self, on_select=None):
        self.state = None
        self.on_select = on_select or (lambda key: None)
        self.rows = (
            ("add_iphone", "Добавить iPhone"),
            ("brightness", "Яркость"),
            ("notif_blink", "Индикатор уведомлений"),
            ("power_off_confirm", "Подготовить отключение USB"),
            ("about", "О системе"),
        )

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        return False

    def tap(self, index):
        if 0 <= int(index) < len(self.rows):
            self.on_select(self.rows[int(index)][0])

    def back(self):
        return False

    def _value(self, key):
        if key == "brightness":
            return f"{int(getattr(self.state, 'screen_brightness', 100))}%"
        if key == "notif_blink":
            return "Вкл" if bool(getattr(self.state, "notif_blink", True)) else "Выкл"
        if key == "add_iphone":
            return "Подключён" if bool(getattr(self.state.iphone, "connected", False)) else ""
        if key == "about":
            return str(getattr(self.state, "device_name", "") or "")
        return ""

    def render(self, regions=None):
        img, draw = self.blank()
        _title(draw, "Настройки")
        right = T.ARC_SAFE_X
        y = 76
        for index, (key, label) in enumerate(self.rows):
            rect = (28, y, right, y + self.ROW_HEIGHT - 8)
            draw.line((28, rect[3], right, rect[3]), fill=T.HAIRLINE, width=1)
            draw.text((40, y + 14), label, font=T.font(T.SZ_BODY), fill=T.FG)
            value = self._value(key)
            if value:
                font = T.font(T.SZ_META)
                width = C.text_w(draw, value, font)
                draw.text((right - width - 12, y + 18), value, font=font, fill=T.MUTED)
            if regions is not None:
                regions.add(rect, "settings_tap", payload=index)
            y += self.ROW_HEIGHT
        return img


class NotificationsScreen(Screen):
    name = "notifications"
    title = "Уведомления"
    fullscreen = True
    ROW_HEIGHT = 112

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)
        self.sel = 0
        self.scroll_y = 0.0
        self._max_scroll = 0.0
        self.detail_uid = None

    def on_state(self, state):
        self.state = state

    def _notes(self):
        return list(getattr(self.state, "notifications", []) or [])

    def select(self, index):
        notes = self._notes()
        if notes:
            self.sel = max(0, min(int(index), len(notes) - 1))

    def close_detail(self):
        self.detail_uid = None

    def on_input(self, event):
        notes = self._notes()
        if isinstance(event, tuple) and event and event[0] == "scroll":
            before = self.scroll_y
            self.scroll_y = max(
                0.0, min(self._max_scroll, self.scroll_y - float(event[1]))
            )
            return abs(before - self.scroll_y) >= 0.01
        if event == Input.SWIPE_LEFT and notes:
            uid = notes[self.sel].get("uid")
            if uid is not None:
                self.emit("notif_dismiss", uid)
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        _title(draw, "Уведомления")
        notes = self._notes()
        right = T.ARC_SAFE_X
        if not notes:
            C.text_centered(
                draw, "-", T.font(56), T.FAINT, T.MAIN_CY - 20, cx=right // 2
            )
            return img

        viewport_top = 76
        viewport_bottom = T.H - 8
        total = len(notes) * self.ROW_HEIGHT
        self._max_scroll = max(0.0, total - (viewport_bottom - viewport_top))
        self.scroll_y = max(0.0, min(self._max_scroll, self.scroll_y))
        y = viewport_top - int(self.scroll_y)
        for index, note in enumerate(notes):
            row = (28, y, right, y + self.ROW_HEIGHT - 8)
            if row[3] >= viewport_top and row[1] <= viewport_bottom:
                if index == self.sel:
                    draw.rectangle(row, outline=T.SURFACE_SEL, width=2)
                app = str(note.get("app", "") or "")
                title = str(note.get("title", "") or note.get("text", "") or "-")
                body = str(note.get("body", "") or "")
                draw.text((42, y + 8), app, font=T.font(T.SZ_META), fill=T.ACCENT)
                draw.text(
                    (42, y + 40),
                    C.truncate(draw, title, T.font(T.SZ_BODY), right - 64),
                    font=T.font(T.SZ_BODY),
                    fill=T.FG,
                )
                if body:
                    draw.text(
                        (42, y + 75),
                        C.truncate(draw, body, T.font(T.SZ_META), right - 64),
                        font=T.font(T.SZ_META),
                        fill=T.MUTED,
                    )
                if regions is not None:
                    regions.add(row, "notif_select", payload=index)
            y += self.ROW_HEIGHT
        return img


class PairingModal:
    fullscreen = True

    def __init__(self, emit=None):
        self.emit = emit or (lambda intent, payload=None: None)
        self.state = None
        self.scroll_y = 0.0

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event == Input.BACK:
            self.emit("pairing_cancel")
            return True
        return False

    def render(self, img, regions):
        draw = ImageDraw.Draw(img)
        draw.rectangle((0, 0, T.W, T.H), fill=T.BG)
        _title(draw, "Добавление iPhone")
        center = T.ARC_SAFE_X // 2
        phase = int(time.monotonic() * 4) % 5
        for index in range(5):
            T.icon_dot(
                draw,
                center - 52 + index * 26,
                T.MAIN_CY,
                7 if index == phase else 4,
                color=T.ACCENT if index == phase else T.HAIRLINE,
            )
        C.text_centered(
            draw,
            "Ожидание подключения",
            T.font(T.SZ_BODY),
            T.MUTED,
            T.MAIN_CY + 46,
            cx=center,
        )
