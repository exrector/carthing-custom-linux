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
    MAX_TILES = 9
    GRID_COLUMNS = 3

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

    def _tiles(self):
        catalog = list(getattr(self.state, "plugin_catalog", []) or [])
        snapshots = dict(getattr(self.state, "plugin_snapshots", {}) or {})
        action_tiles = []
        information_tiles = []
        for record in catalog:
            manifest = dict(record.get("manifest") or {})
            plugin_id = str(manifest.get("id") or "")
            snapshot = snapshots.get(plugin_id)
            if (
                not plugin_id
                or not bool(record.get("enabled"))
                or not isinstance(snapshot, dict)
            ):
                continue
            for card in (snapshot.get("cards") or [])[:8]:
                if not isinstance(card, dict):
                    continue
                card_id = str(card.get("id") or "")
                actions = [
                    dict(action)
                    for action in (card.get("actions") or [])[:4]
                    if isinstance(action, dict)
                    and bool(action.get("enabled", True))
                ]
                for action in actions:
                    action_tiles.append({
                        "kind": "action",
                        "plugin_id": plugin_id,
                        "card_id": card_id,
                        "action_id": str(action.get("id") or ""),
                        "title": str(action.get("label") or "Действие"),
                        "detail": str(card.get("title") or manifest.get("name") or ""),
                        "style": str(action.get("style") or "normal"),
                        "accent": card.get("accent"),
                    })
                if not actions:
                    information_tiles.append({
                        "kind": "information",
                        "title": str(card.get("title") or manifest.get("name") or ""),
                        "detail": str(card.get("subtitle") or ""),
                        "status": str(card.get("status") or ""),
                        "rows": [
                            dict(row)
                            for row in (card.get("rows") or [])[:2]
                            if isinstance(row, dict)
                        ],
                        "accent": card.get("accent"),
                    })
        return (action_tiles + information_tiles)[:self.MAX_TILES]

    @staticmethod
    def _tile_rect(index):
        gap = 8
        left = 24
        top = 12
        right = T.ARC_SAFE_X
        bottom = T.H - 12
        width = (right - left - gap * 2) // 3
        height = (bottom - top - gap * 2) // 3
        column = index % PluginDashboardScreen.GRID_COLUMNS
        row = index // PluginDashboardScreen.GRID_COLUMNS
        x0 = left + column * (width + gap)
        y0 = top + row * (height + gap)
        return (x0, y0, x0 + width, y0 + height)

    def _draw_action_tile(self, draw, rect, tile, regions):
        accent = self._accent(tile.get("accent"))
        primary = tile.get("style") == "primary"
        destructive = tile.get("style") == "destructive"
        fill = (
            T.STATUS_OFF
            if destructive
            else (T.SURFACE_SEL if primary else T.SURFACE)
        )
        foreground = T.BG if primary or destructive else accent
        draw.rectangle(rect, fill=fill, outline=T.HAIRLINE, width=2)
        label = C.truncate(
            draw,
            tile["title"],
            T.font(24),
            rect[2] - rect[0] - 24,
        )
        C.text_centered(
            draw,
            label,
            T.font(24),
            foreground,
            rect[1] + 31,
            cx=(rect[0] + rect[2]) // 2,
        )
        if regions is not None and tile.get("action_id"):
            regions.add(
                rect,
                "plugin_action",
                payload={
                    "plugin_id": tile["plugin_id"],
                    "card_id": tile["card_id"],
                    "action_id": tile["action_id"],
                },
            )

    def _draw_information_tile(self, draw, rect, tile):
        accent = self._accent(tile.get("accent"))
        draw.rectangle(rect, fill=T.SURFACE, outline=T.HAIRLINE, width=2)
        title = C.truncate(
            draw,
            tile["title"],
            T.font(16),
            rect[2] - rect[0] - 20,
        )
        draw.text(
            (rect[0] + 12, rect[1] + 10),
            title,
            font=T.font(16),
            fill=accent,
        )
        rows = tile.get("rows") or []
        if rows:
            row_height = 25 if len(rows) > 1 else 32
            start_y = rect[1] + 31
            for index, row in enumerate(rows):
                y = start_y + index * row_height
                label = C.truncate(
                    draw,
                    str(row.get("label") or ""),
                    T.font(14),
                    52,
                )
                value = C.truncate(
                    draw,
                    str(row.get("value") or ""),
                    T.font(23 if len(rows) == 1 else 18),
                    rect[2] - rect[0] - 68,
                )
                if label:
                    draw.text(
                        (rect[0] + 12, y + 5),
                        label,
                        font=T.font(14),
                        fill=T.FAINT,
                    )
                draw.text(
                    (rect[0] + (60 if label else 12), y),
                    value,
                    font=T.font(23 if len(rows) == 1 else 18),
                    fill=T.MUTED,
                )
        footer = tile.get("status") or ""
        if footer:
            footer = C.truncate(
                draw,
                footer,
                T.font(14),
                rect[2] - rect[0] - 20,
            )
            draw.text(
                (rect[0] + 12, rect[3] - 23),
                footer,
                font=T.font(14),
                fill=T.FAINT,
            )

    def render(self, regions=None):
        img, draw = self.blank()
        tiles = self._tiles()
        if not tiles:
            C.text_centered(
                draw,
                "МОДУЛИ ВЫБИРАЮТСЯ НА MAC",
                T.font(T.SZ_BODY),
                T.FAINT,
                T.MAIN_CY - 18,
                cx=T.ARC_SAFE_X // 2,
            )
            return img
        for index, tile in enumerate(tiles):
            rect = self._tile_rect(index)
            if tile["kind"] == "action":
                self._draw_action_tile(draw, rect, tile, regions)
            else:
                self._draw_information_tile(draw, rect, tile)
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
