"""The Car Thing desktops. Each composes ui_components over ui_theme; none
calls raw PIL styling or font glyphs (vector icons only). Content starts below
the status bar. Screens read duck-typed state and emit intents via callbacks.
"""
from PIL import Image, ImageDraw

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

        # Center title + artist in MAIN. Progress + play state now live on the
        # bar's top divider / transport, so nothing here reflows or scrolls off.
        lines = C.wrap_lines(draw, sess.title or "—", T.font(T.SZ_TITLE), T.CONTENT_W)
        MAXL = 4                                   # cap long podcast titles
        if len(lines) > MAXL:
            lines = lines[:MAXL]
            lines[-1] = C.truncate(draw, lines[-1] + "…", T.font(T.SZ_TITLE), T.CONTENT_W)
        # Artist ТОЖЕ переносится в CONTENT_W (иначе длинный исполнитель прёт за границы
        # MAIN через весь экран). Лимит 2 строки + многоточие.
        alines = []
        if sess.artist:
            alines = C.wrap_lines(draw, sess.artist, T.font(T.SZ_BODY), T.CONTENT_W)
            MAXA = 2
            if len(alines) > MAXA:
                alines = alines[:MAXA]
                alines[-1] = C.truncate(draw, alines[-1] + "…", T.font(T.SZ_BODY), T.CONTENT_W)
        LH, ALH = 56, 40
        block_h = len(lines) * LH + (len(alines) * ALH + 10 if alines else 0)
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_h // 2)
        for line in lines:
            C.text_centered(draw, line, T.font(T.SZ_TITLE), T.FG, y, cx=T.CONTENT_CX); y += LH
        if alines:
            y += 10
            for aline in alines:
                C.text_centered(draw, aline, T.font(T.SZ_BODY), T.MUTED, y, cx=T.CONTENT_CX); y += ALH
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


class TransferScreen(Screen):
    name = "transfer"
    title = "Audio"

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)

    def on_state(self, state):
        self.state = state

    def on_input(self, event):
        if event == Input.PRESS:
            self.emit("transfer_rescan")
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        draw.text((24, CONTENT_TOP - 8), "Audio Output", font=T.font(34), fill=T.MUTED)
        draw.line([24, CONTENT_TOP + 34, T.CONTENT_X1, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

        if not self.state or not self.state.transfer_active:
            C.text_centered(draw, "Transfer готов", T.font(T.SZ_TITLE), T.FG, T.MAIN_CY - 38, cx=T.CONTENT_CX)
            C.text_centered(draw, "Выберите Car Thing как аудиовыход на iPhone", T.font(T.SZ_META),
                            T.MUTED, T.MAIN_CY + 22, cx=T.CONTENT_CX)
            return img

        subtitle = "Сканирую доверенные динамики…" if self.state.transfer_scanning else "Доверенные динамики"
        C.text_centered(draw, subtitle, T.font(T.SZ_META), T.MUTED, CONTENT_TOP + 58, cx=T.CONTENT_CX)

        speakers = self.state.trusted_speakers
        if not speakers:
            C.text_centered(draw, "Нет доверенных динамиков", T.font(T.SZ_BODY), T.FAINT,
                            T.MAIN_CY, cx=T.CONTENT_CX)
            C.text_centered(draw, "Добавьте динамик в настройках", T.font(T.SZ_META), T.MUTED,
                            T.MAIN_CY + 46, cx=T.CONTENT_CX)
            return img

        y = CONTENT_TOP + 104
        for speaker in speakers[:5]:
            connected = bool(speaker.get("connected"))
            online = bool(speaker.get("online")) or connected
            default = bool(speaker.get("default"))
            status = "connected" if connected else ("online" if online else "offline")
            label = speaker.get("label") or speaker.get("address") or "Speaker"
            suffix = "  · default" if default else ""
            text = f"{label}{suffix}"
            color = T.FG if online else T.FAINT
            if connected:
                color = T.ACCENT
            rect = C.list_row(draw, y, text, selected=connected or (default and online), indent=0)
            draw.text((T.LIST_X0 + 26, y + 42), status, font=T.font(T.SZ_SMALL), fill=color)
            if regions is not None:
                regions.add(rect, "transfer_select", payload=speaker.get("key"))
            y += T.ROW_H
        return img


class ModesScreen(Screen):
    """Runtime mode switcher for hardware tests.

    These are product-level profiles inside one accessory, not separate
    Bluetooth identities. The screen only emits mode intents; carthing_runtime
    owns the actual transport/service changes.
    """

    name = "modes"
    title = "Режимы"

    MODES = [
        ("remote", "Remote", "iPhone media control"),
        ("transfer", "Transfer", "iPhone audio output -> speaker"),
        ("mac", "macOS", "Mac control surface"),
        ("pairing", "Pairing", "Add source or speaker"),
        ("quiet", "Quiet", "Connected, low UI activity"),
        ("service", "Service", "USB/NCM diagnostics safe state"),
    ]

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)
        self.sel = 0
        self.scroll_y = 0
        self._max_scroll = 0
        self._last_current = None

    def on_state(self, state):
        self.state = state
        current = getattr(state, "device_mode", "remote") if state else "remote"
        if current != self._last_current:
            self._last_current = current
            for i, (key, _label, _desc) in enumerate(self.MODES):
                if key == current:
                    self.sel = i
                    break

    def _activate(self, index):
        if not (0 <= index < len(self.MODES)):
            return
        key = self.MODES[index][0]
        self.sel = index
        self.emit("mode_select", key)

    def tap(self, index):
        self._activate(index)

    def on_input(self, event):
        if isinstance(event, tuple) and event and event[0] == "scroll":
            self.scroll_y = max(0, min(self._max_scroll, self.scroll_y - event[1]))
            return True
        if event == Input.SWIPE_DOWN:
            self.sel = min(len(self.MODES) - 1, self.sel + 1)
            return True
        if event == Input.SWIPE_UP:
            self.sel = max(0, self.sel - 1)
            return True
        if event == Input.PRESS:
            self._activate(self.sel)
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        draw.text((24, CONTENT_TOP - 8), "Режимы", font=T.font(34), fill=T.MUTED)
        draw.line([24, CONTENT_TOP + 34, T.LIST_X1, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

        current = getattr(self.state, "device_mode", "remote") if self.state else "remote"
        power_tier = getattr(self.state, "power_tier", "boot") if self.state else "boot"
        top = CONTENT_TOP + 52
        bottom = T.OCCLUSION_BOTTOM
        row_h = T.ROW_H + 16
        total_h = len(self.MODES) * row_h + 52
        self._max_scroll = max(0, total_h - (bottom - top))
        self.scroll_y = max(0, min(self._max_scroll, self.scroll_y))

        status_y = top - self.scroll_y
        draw.text((52, status_y), f"Power: {power_tier}", font=T.font(T.SZ_META), fill=T.FAINT)

        for i, (key, label, desc) in enumerate(self.MODES):
            y = top + 52 + i * row_h - self.scroll_y
            if y + row_h < top or y > bottom:
                continue
            active = key == current
            selected = i == self.sel
            rect = C.list_row(draw, y, label, selected=selected, indent=0)
            dot = T.ACCENT if active else T.FAINT
            T.icon_dot(draw, 40, y + T.SZ_BODY // 2, 7, color=dot)
            desc_color = T.FG if active else T.FAINT
            draw.text((52, y + 42), desc, font=T.font(T.SZ_SMALL), fill=desc_color)
            if active:
                draw.text((T.LIST_X1 - 120, y), "active", font=T.font(T.SZ_SMALL), fill=T.ACCENT)
            if regions is not None:
                rx0, ry0, rx1, ry1 = rect
                regions.add((rx0, max(top, ry0), rx1, min(bottom, ry1 + 42)),
                            "mode_select", payload=key)
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
            {"key": "modes", "label": "Режимы работы"},
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
        self.top = 0          # legacy row offset fallback; pixel scroll owns normal touch lists
        self.scroll_y = 0
        self._max_scroll = 0
        self.state = None

    def on_state(self, state):
        self.state = state

    def _children(self, it):
        if it["key"] == "trusted":      # dynamic from the trusted registry
            trusted = self.state.trusted if self.state else []
            if not trusted:
                return [("trusted_empty", "— нет устройств —")]
            rows = []
            for d in trusted:
                if d.get("connected"):
                    color = T.STATUS_OK       # зелёный
                elif d.get("online"):
                    color = T.STATUS_WARN     # жёлтый
                else:
                    color = T.STATUS_OFF      # красный
                addr = d.get("address") or "—"
                # имя + MAC; цветную статус-точку рисует render (3-й элемент = цвет)
                rows.append(("trusted:" + d["key"], f"{d['label']}   {addr}", color))
            return rows
        return it.get("children", [])

    def _visible(self):
        """Flatten to rows: (level, key, label, expandable, expanded)."""
        rows = []
        for it in self.items:
            has_children = "children" in it
            rows.append((0, it["key"], it["label"], has_children, it["key"] in self.expanded, None))
            if has_children and it["key"] in self.expanded:
                for child in self._children(it):
                    ckey, clabel = child[0], child[1]
                    color = child[2] if len(child) > 2 else None
                    rows.append((1, ckey, clabel, False, False, color))
        return rows

    def _activate(self, i):
        """Действие над строкой i: раскрыть родителя или выбрать лист (= PRESS)."""
        rows = self._visible()
        if not (0 <= i < len(rows)):
            return
        self.sel = i
        level, key, _label, expandable, expanded, _color = rows[i]
        if expandable:
            self.expanded.symmetric_difference_update({key})
        else:
            self.on_select(key)

    def tap(self, i):
        """Тап по строке экрана (touch): выбрать её и активировать."""
        self._activate(i)

    def on_input(self, event):
        rows = self._visible()
        if not rows:
            return False
        if isinstance(event, tuple) and event and event[0] == "scroll":
            self.scroll_y = max(0, min(self._max_scroll, self.scroll_y - event[1]))
            return True
        # Fallback for non-touch test paths. Normal list movement is pixel scroll by touch.
        if event == Input.ENCODER_CW or event == Input.SWIPE_DOWN:
            self.sel = (self.sel + 1) % len(rows); return True
        if event == Input.ENCODER_CCW or event == Input.SWIPE_UP:
            self.sel = (self.sel - 1) % len(rows); return True
        if event == Input.PRESS:
            self._activate(self.sel)
            return True
        return False

    def render(self, regions=None):
        img, draw = self.blank()
        draw.text((24, CONTENT_TOP - 8), "Настройки", font=T.font(34), fill=T.MUTED)
        draw.line([24, CONTENT_TOP + 34, T.LIST_X1, CONTENT_TOP + 34], fill=T.HAIRLINE, width=2)

        rows = self._visible()
        start_y = CONTENT_TOP + 52
        bottom_y = T.OCCLUSION_BOTTOM
        total_h = len(rows) * T.ROW_H
        self._max_scroll = max(0, total_h - (bottom_y - start_y))
        self.scroll_y = max(0, min(self._max_scroll, self.scroll_y))

        visible = []
        for i, row in enumerate(rows):
            y = start_y + i * T.ROW_H - self.scroll_y
            if y + T.ROW_H > start_y and y < bottom_y:
                visible.append((i, y, row))
        if visible and not any(i == self.sel for i, _y, _row in visible):
            self.sel = visible[0][0]

        for i, y, row in visible:
            level, key, label, expandable, expanded, color = rows[i]
            rect = C.list_row(draw, y, label, selected=(i == self.sel),
                              expandable=expandable, expanded=expanded,
                              indent=24 if level else 0)
            if color is not None:                              # цветная статус-точка по центру строки
                T.icon_dot(draw, 40, y + T.SZ_BODY // 2, 7, color=color)
            if regions is not None:
                rx0, ry0, rx1, ry1 = rect
                regions.add((rx0, max(start_y, ry0), rx1, min(bottom_y, ry1)),
                            "settings_tap", payload=i)         # тап -> выбрать+активировать строку i
        return img


class NotificationsScreen(Screen):
    """Зеркало уведомлений iPhone (ANCS) — ПОЛНОЭКРАННЫЙ вью (поверх бара/энкодера, весь
    экран под текст). Запись: имя приложения + содержание + вторичное. Выделение = зелёная
    полоса слева (как в Настройках), без серого фона. Энкодер/тап — выбор; свайп влево — очистить."""

    name = "notifications"
    title = "Уведомления"
    fullscreen = True            # компоситор не накладывает бар/дугу/точки поверх

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)
        self.sel = 0
        self.top = 0
        self.detail_uid = None         # None = список; иначе uid развёрнутой карточки
        self.scroll_y = 0              # пиксельный скролл «за пальцем»
        self._max_scroll = 0
        self._layout_sig = None
        self._layout_items = []
        self._layout_total = 0
        self._content_layer = None

    def on_state(self, state):
        self.state = state
        sig = self._notes_signature()
        if sig != self._layout_sig:
            self._layout_sig = None
            self._content_layer = None

    def _notes(self):
        return (self.state.notifications if self.state else []) or []

    def _notes_signature(self):
        return tuple(
            (n.get("uid"), n.get("app", ""), n.get("title", ""), n.get("body", ""))
            for n in self._notes()
        )

    def select(self, i):
        notes = self._notes()
        if notes:
            self.sel = max(0, min(i, len(notes) - 1))

    def open_detail(self, i):
        notes = self._notes()
        if 0 <= i < len(notes):
            self.sel = i
            self.detail_uid = notes[i].get("uid")

    def close_detail(self):
        self.detail_uid = None

    def on_input(self, event):
        notes = self._notes()
        if not notes:
            return False
        if isinstance(event, tuple) and event and event[0] == "scroll":
            # пиксельный скролл «за пальцем»: палец вниз (delta>0) -> к началу списка
            self.scroll_y = max(0, min(self._max_scroll, self.scroll_y - event[1]))
            return True
        if event == Input.SWIPE_LEFT:
            self.sel = max(0, min(self.sel, len(notes) - 1))
            uid = notes[self.sel].get("uid")
            if uid is not None:
                self.emit("notif_dismiss", uid)        # очистить выбранное (двусторонне)
            return True
        return False

    def _ensure_layout(self, draw, notes, maxw):
        f = T.font(T.SZ_META)                             # единый мелкий размер на все строки
        x0 = 28; tx = x0 + 24
        LH = 34; GAP = 22
        sig = (maxw, T.SZ_META, self._notes_signature())
        if sig == self._layout_sig and self._content_layer is not None:
            return

        items = []
        for n in notes:
            tl = C.wrap_lines(draw, n.get("title", "") or "—", f, maxw) or [""]
            bl = C.wrap_lines(draw, n.get("body", ""), f, maxw) if n.get("body") else []
            items.append({
                "title_lines": tl,
                "body_lines": bl,
                "height": LH + len(tl) * LH + len(bl) * LH + GAP,
                "content_h": LH + len(tl) * LH + len(bl) * LH,
            })

        total = max(1, sum(item["height"] for item in items))
        layer = Image.new("RGB", (T.W, total), T.BG)
        ldraw = ImageDraw.Draw(layer)
        y = 0
        for i, item in enumerate(items):
            yy = y
            n = notes[i]
            ldraw.text((tx, yy), n.get("app", ""), font=f, fill=T.ACCENT); yy += LH
            for ln in item["title_lines"]:
                ldraw.text((tx, yy), ln, font=f, fill=T.FG, stroke_width=1, stroke_fill=T.FG); yy += LH
            for ln in item["body_lines"]:
                ldraw.text((tx, yy), ln, font=f, fill=T.MUTED); yy += LH
            item["y"] = y
            y += item["height"]

        self._layout_sig = sig
        self._layout_items = items
        self._layout_total = total
        self._content_layer = layer

    def render(self, regions=None):
        # Текст уведомлений layout'ится один раз, а при drag мы только двигаем готовый слой.
        img, draw = self.blank()
        notes = self._notes()
        x0 = 28; tx = x0 + 24
        maxw = T.OCCLUSION_LEFT - tx - 8                  # не залезать под дугу громкости справа
        top_y = 74; bot_y = T.H - 6

        def header():
            draw.rectangle([0, 0, T.W, 62], fill=T.BG)    # маска для контента, заехавшего под шапку
            draw.text((28, 16), "Уведомления", font=T.font(34), fill=T.MUTED)
            draw.line([28, 60, T.W - 28, 60], fill=T.HAIRLINE, width=2)

        if not notes:
            header()
            C.text_centered(draw, "Нет уведомлений", T.font(T.SZ_TITLE), T.FAINT, T.H // 2, cx=T.W // 2)
            return img

        self._ensure_layout(draw, notes, maxw)
        viewport_h = bot_y - top_y
        total = self._layout_total
        self._max_scroll = max(0, total - (bot_y - top_y))
        self.scroll_y = max(0, min(self._max_scroll, self.scroll_y))

        visible = []
        for i, item in enumerate(self._layout_items):
            y = top_y + item["y"] - self.scroll_y
            if y + item["content_h"] > top_y - 2 and y < bot_y:
                visible.append((i, y, item))
        if visible and not any(i == self.sel for i, _y, _item in visible):
            self.sel = visible[0][0]

        crop_h = min(viewport_h, total - self.scroll_y)
        if crop_h > 0:
            crop = self._content_layer.crop((0, self.scroll_y, T.W, self.scroll_y + crop_h))
            img.paste(crop, (0, top_y))
        for i, y, item in visible:
            if i == self.sel:
                draw.rectangle([x0, y - 4, x0 + 7, y - 4 + item["content_h"]], fill=T.ACCENT)
            if regions is not None:
                regions.add((x0, max(top_y, y - 4), T.W - 24, min(bot_y, y - 4 + item["content_h"])),
                            "notif_select", payload=i)
        header()                                          # шапка ПОВЕРХ списка
        return img

    def _render_detail(self, n, regions=None):
        """Развёрнутая карточка одного уведомления на весь экран: источник + полный
        заголовок и тело с ПЕРЕНОСОМ. Показываем максимум доступного (ANCS-превью, не всё письмо)."""
        img, draw = self.blank()
        S = T.SZ_META
        f = T.font(S)
        x0 = 28
        maxw = T.W - 2 * x0
        draw.text((x0, 16), n.get("app", ""), font=T.font(T.SZ_BODY), fill=T.ACCENT)
        draw.line([x0, 60, T.W - x0, 60], fill=T.HAIRLINE, width=2)

        y = 78
        for line in C.wrap_lines(draw, n.get("title", ""), f, maxw)[:3]:    # заголовок жирным
            draw.text((x0, y), line, font=f, fill=T.FG, stroke_width=1, stroke_fill=T.FG)
            y += 36
        body = n.get("body", "")
        if body:
            y += 10
            lines = C.wrap_lines(draw, body, f, maxw)
            fit = max(1, (T.H - y - 16) // 34)
            if len(lines) > fit:                                            # не влезло -> многоточие
                lines = lines[:fit]
                lines[-1] = C.truncate(draw, lines[-1] + "…", f, maxw)
            for line in lines:
                draw.text((x0, y), line, font=f, fill=T.MUTED); y += 34
        if regions is not None:
            regions.add((0, 0, T.W, T.H), "notif_close")    # тап в любом месте -> назад к списку
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
        name = getattr(self.state, "device_name", "Car Thing")
        C.text_centered(draw, "Сопряжение", T.font(T.SZ_TITLE), T.FG, T.MAIN_CY - 70, cx=cx)
        C.text_centered(draw, "«" + name + "»", T.font(T.SZ_BODY), T.FG, T.MAIN_CY - 8, cx=cx)
        C.text_centered(draw, "Выберите на iPhone…", T.font(T.SZ_SMALL), T.ACCENT,
                        T.MAIN_CY + 30, cx=cx)

        # Cancel button (tappable) — also Back/Press cancels
        bw, bh = 200, 48
        bx0, by0 = cx - bw // 2, T.MAIN_CY + 84
        draw.rectangle([bx0, by0, bx0 + bw, by0 + bh], outline=T.FAINT, width=2)
        C.text_centered(draw, "Отмена", T.font(T.SZ_META), T.MUTED, by0 + 8, cx=cx)
        regions.add((bx0, by0, bx0 + bw, by0 + bh), "pairing_cancel")
