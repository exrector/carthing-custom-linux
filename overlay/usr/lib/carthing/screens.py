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
    TITLE_SIZE = 40
    TITLE_LINE_HEIGHT = 48

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
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
            T.draw_clock(
                draw,
                getattr(self.state, "clock_text", "--:--"),
                T.CONTENT_CX,
                T.MAIN_CY,
                size=108,
                date_text=getattr(self.state, "clock_date_text", ""),
                date_size=28,
            )
            return img

        if not session.title:
            T.draw_clock(
                draw,
                getattr(self.state, "clock_text", "--:--"),
                T.CONTENT_CX,
                T.MAIN_CY,
                size=108,
                date_text=getattr(self.state, "clock_date_text", ""),
                date_size=28,
            )
            return img

        display_title = session.title or "-"
        title_font = T.font(self.TITLE_SIZE)
        lines = C.wrap_lines(draw, display_title, title_font, T.CONTENT_W)
        lines = lines[:3]
        if len(lines) == 3:
            lines[-1] = C.truncate(
                draw, lines[-1], title_font, T.CONTENT_W
            )
        app_label = (
            str(session.app_name or "").strip()
            if session.title
            else ""
        )
        artist = str(session.artist or "").strip()
        block_height = (
            len(lines) * self.TITLE_LINE_HEIGHT
            + (34 if app_label else 0)
            + (50 if artist else 0)
        )
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_height // 2)
        if app_label:
            C.text_centered(
                draw,
                C.truncate(
                    draw, app_label, T.font(T.SZ_SMALL), T.CONTENT_W
                ),
                T.font(T.SZ_SMALL),
                T.MUTED,
                y,
                cx=T.CONTENT_CX,
            )
            y += 34
        for line in lines:
            C.text_centered(
                draw, line, title_font, T.FG, y, cx=T.CONTENT_CX
            )
            y += self.TITLE_LINE_HEIGHT
        if artist:
            self._artist(img, draw, artist, y + 6)
        if regions is not None:
            regions.add(
                (
                    T.CONTENT_X0,
                    T.CONTENT_TOP,
                    T.ARC_SAFE_X,
                    T.OCCLUSION_BOTTOM,
                ),
                "media_play_pause",
            )
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
        return False

    @staticmethod
    def _visible_tail(text, limit=440):
        text = str(text or "").strip()
        if len(text) <= limit:
            return text
        tail = text[-limit:]
        separator = tail.find(" ")
        if separator >= 0:
            tail = tail[separator + 1 :]
        return f"...{tail}"

    def render(self, regions=None):
        img, draw = self.blank()
        right = T.ARC_SAFE_X
        enabled = bool(getattr(self.state, "remote_mic_enabled", False))
        state = str(getattr(self.state, "remote_mic_state", "off") or "off")
        _title(draw, "Ассистент")

        button = (right - 250, 8, right - 10, 60)
        draw.rectangle(button, fill=T.STATUS_OK if enabled else T.SURFACE_SEL)
        C.text_centered(
            draw,
            "МИКРОФОН ВКЛ" if enabled else "МИКРОФОН ВЫКЛ",
            T.font(20),
            T.BG if enabled else T.FG,
            24,
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
            fill=T.ROLE_STATUS if enabled else T.FAINT,
        )

        transcript = list(getattr(self.state, "assistant_transcript", []) or [])
        live_text = str(getattr(self.state, "assistant_live_text", "") or "").strip()
        live_target = str(
            getattr(self.state, "assistant_live_target", "") or ""
        ).strip()
        font = T.font(T.SZ_BODY)
        top = 128
        bottom = T.H - 18
        line_height = 40
        max_lines = max(1, (bottom - top) // line_height)
        live_rows = []
        if live_text:
            cursor = "_" if live_text != live_target else ""
            display_text = f"Вы: {self._visible_tail(live_text)}{cursor}"
            live_rows = [
                (line, "user")
                for line in (
                    C.wrap_lines(draw, display_text, font, right - 64)
                    or [display_text]
                )[-max_lines:]
            ]

        history_rows = []
        remaining = max(0, max_lines - len(live_rows))
        for utterance in reversed(transcript):
            if remaining <= 0:
                break
            display_text = self._visible_tail(utterance)
            role = (
                "user"
                if display_text.startswith("Вы:")
                else (
                    "assistant"
                    if display_text.startswith("Ассистент:")
                    else "status"
                )
            )
            wrapped = (
                C.wrap_lines(draw, display_text, font, right - 64)
                or [display_text]
            )
            selected = wrapped[-remaining:]
            history_rows[0:0] = [(line, role) for line in selected]
            remaining -= len(selected)

        visible = (history_rows + live_rows)[-max_lines:]
        y = bottom - len(visible) * line_height
        colors = {
            "user": T.ROLE_USER,
            "assistant": T.ROLE_ASSISTANT,
            "status": T.MUTED,
        }
        for line, role in visible:
            draw.text(
                (28, y),
                line,
                font=font,
                fill=colors.get(role, T.MUTED),
            )
            y += line_height
        return img


class SettingsScreen(Screen):
    name = "settings"
    title = "Настройки"
    fullscreen = True
    ROW_HEIGHT = 64

    def __init__(self, on_select=None):
        self.state = None
        self.on_select = on_select or (lambda key: None)
        self.rows = (
            ("add_iphone", "Добавить iPhone"),
            ("brightness", "Яркость"),
            ("screensaver", "Заставка"),
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
        if key == "screensaver":
            if not bool(getattr(self.state, "screensaver_enabled", True)):
                return "Выкл"
            seconds = int(getattr(self.state, "screen_off_sec", 60))
            if seconds < 60:
                return f"{seconds} с"
            return f"{seconds // 60} мин"
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
            adjustable = key in ("brightness", "screensaver")
            if adjustable:
                minus = (right - 224, y + 4, right - 174, y + 52)
                plus = (right - 58, y + 4, right - 8, y + 52)
                T.icon_minus(
                    draw,
                    (minus[0] + minus[2]) // 2,
                    (minus[1] + minus[3]) // 2,
                    10,
                    color=T.MUTED,
                    width=3,
                )
                T.icon_plus(
                    draw,
                    (plus[0] + plus[2]) // 2,
                    (plus[1] + plus[3]) // 2,
                    10,
                    color=T.MUTED,
                    width=3,
                )
                font = T.font(T.SZ_META)
                width = C.text_w(draw, value, font)
                draw.text(
                    (right - 116 - width // 2, y + 18),
                    value,
                    font=font,
                    fill=T.FG,
                )
            elif value:
                font = T.font(T.SZ_META)
                width = C.text_w(draw, value, font)
                draw.text((right - width - 12, y + 18), value, font=font, fill=T.MUTED)
            if regions is not None:
                regions.add(rect, "settings_tap", payload=index)
                if adjustable:
                    regions.add(
                        minus,
                        "display_adjust",
                        payload=(key, "-"),
                    )
                    regions.add(
                        plus,
                        "display_adjust",
                        payload=(key, "+"),
                    )
            y += self.ROW_HEIGHT
        return img


class PluginDashboardScreen(Screen):
    name = "plugins"
    title = "Модули"
    fullscreen = True

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    @staticmethod
    def _accent(value):
        value = str(value or "").lstrip("#")
        if len(value) != 6:
            return T.FG
        try:
            return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
        except ValueError:
            return T.FG

    def render(self, regions=None):
        img, draw = self.blank()
        _title(draw, "Модули")
        catalog = list(getattr(self.state, "plugin_catalog", []) or [])
        snapshots = dict(getattr(self.state, "plugin_snapshots", {}) or {})
        modules = []
        for record in catalog:
            manifest = dict(record.get("manifest") or {})
            plugin_id = str(manifest.get("id") or "")
            snapshot = snapshots.get(plugin_id)
            if (
                plugin_id
                and bool(record.get("enabled"))
                and isinstance(snapshot, dict)
                and snapshot.get("cards")
            ):
                modules.append((plugin_id, manifest, snapshot))
        if not modules:
            C.text_centered(
                draw,
                "МОДУЛИ ВЫБИРАЮТСЯ НА MAC",
                T.font(T.SZ_BODY),
                T.FAINT,
                T.MAIN_CY - 18,
                cx=T.ARC_SAFE_X // 2,
            )
            return img

        selected = str(
            getattr(self.state, "plugin_selected_id", "") or ""
        )
        if selected not in {item[0] for item in modules}:
            selected = modules[0][0]
            self.state.plugin_selected_id = selected

        visible_modules = modules
        show_next = len(modules) > 4
        if show_next:
            selected_index = next(
                index
                for index, item in enumerate(modules)
                if item[0] == selected
            )
            page_start = (selected_index // 4) * 4
            visible_modules = modules[page_start:page_start + 4]
        tab_area_right = T.ARC_SAFE_X - (54 if show_next else 0)
        tab_width = min(
            164,
            max(108, (tab_area_right - 28) // len(visible_modules)),
        )
        for index, (plugin_id, manifest, _snapshot) in enumerate(visible_modules):
            rect = (
                28 + index * tab_width,
                72,
                24 + (index + 1) * tab_width,
                108,
            )
            active = plugin_id == selected
            if active:
                draw.rectangle(rect, fill=T.SURFACE_SEL)
            label = C.truncate(
                draw,
                str(manifest.get("name") or plugin_id),
                T.font(18),
                rect[2] - rect[0] - 12,
            )
            C.text_centered(
                draw,
                label,
                T.font(18),
                T.BG if active else T.MUTED,
                80,
                cx=(rect[0] + rect[2]) // 2,
            )
            if regions is not None:
                regions.add(rect, "plugin_select", payload=plugin_id)
        if show_next:
            next_rect = (T.ARC_SAFE_X - 46, 72, T.ARC_SAFE_X, 108)
            draw.rectangle(next_rect, outline=T.HAIRLINE, width=2)
            C.text_centered(
                draw,
                ">",
                T.font(22),
                T.FG,
                76,
                cx=(next_rect[0] + next_rect[2]) // 2,
            )
            if regions is not None:
                regions.add(next_rect, "plugin_next")

        plugin_id, _manifest, snapshot = next(
            item for item in modules if item[0] == selected
        )
        card = dict(snapshot.get("cards")[0] or {})
        accent = self._accent(card.get("accent"))
        title = C.truncate(
            draw,
            str(card.get("title") or "Модуль"),
            T.font(34),
            450,
        )
        draw.text((28, 120), title, font=T.font(34), fill=accent)
        status = str(card.get("status") or "")
        if status:
            status = C.truncate(draw, status, T.font(20), 190)
            draw.text((520, 130), status, font=T.font(20), fill=T.MUTED)
        subtitle = str(card.get("subtitle") or "")
        if subtitle:
            subtitle = C.truncate(
                draw, subtitle, T.font(T.SZ_SMALL), T.ARC_SAFE_X - 56
            )
            draw.text((28, 164), subtitle, font=T.font(T.SZ_SMALL), fill=T.FAINT)

        actions = [
            dict(action)
            for action in (card.get("actions") or [])[:3]
            if isinstance(action, dict) and bool(action.get("enabled", True))
        ]
        rows = [
            dict(row)
            for row in (card.get("rows") or [])[:(4 if actions else 6)]
            if isinstance(row, dict)
        ]
        for index, row in enumerate(rows):
            column = index % 2
            line = index // 2
            x = 28 + column * 344
            y = 202 + line * 52
            label = C.truncate(
                draw,
                str(row.get("label") or ""),
                T.font(18),
                130,
            )
            value = C.truncate(
                draw,
                str(row.get("value") or ""),
                T.font(T.SZ_SMALL),
                180,
            )
            draw.text((x, y), label, font=T.font(18), fill=T.FAINT)
            draw.text((x + 138, y - 2), value, font=T.font(T.SZ_SMALL), fill=T.MUTED)

        if actions:
            button_width = min(210, (T.ARC_SAFE_X - 56) // len(actions) - 10)
            y0 = 278
            for index, action in enumerate(actions):
                x0 = 28 + index * (button_width + 10)
                rect = (x0, y0, x0 + button_width, 316)
                primary = action.get("style") == "primary"
                destructive = action.get("style") == "destructive"
                fill = (
                    T.STATUS_OFF
                    if destructive
                    else (T.SURFACE_SEL if primary else T.SURFACE)
                )
                draw.rectangle(rect, fill=fill, outline=T.HAIRLINE, width=2)
                label = C.truncate(
                    draw,
                    str(action.get("label") or "Действие"),
                    T.font(18),
                    button_width - 14,
                )
                C.text_centered(
                    draw,
                    label,
                    T.font(18),
                    T.BG if primary or destructive else T.FG,
                    y0 + 8,
                    cx=x0 + button_width // 2,
                )
                if regions is not None:
                    regions.add(
                        rect,
                        "plugin_action",
                        payload={
                            "plugin_id": plugin_id,
                            "card_id": str(card.get("id") or ""),
                            "action_id": str(action.get("id") or ""),
                        },
                    )
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
