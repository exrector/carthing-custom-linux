"""The Car Thing desktops. Each composes ui_components over ui_theme; none
calls raw PIL styling or font glyphs (vector icons only). Content starts below
the status bar. Screens read duck-typed state and emit intents via callbacks.
"""
import time

from PIL import Image, ImageDraw

import ui_theme as T
import ui_components as C
from ui_screen import Screen, Input

CONTENT_TOP = T.CONTENT_TOP


def _fmt(s):
    s = int(s or 0)
    return f"{s // 60}:{s % 60:02d}"


def _fmt_sleep(st):
    """[CLAUDE 2026-06-11] значение шкалы «Сон»: Выкл или N мин."""
    if st is None or not bool(getattr(st, "sleep_on_idle", True)):
        return "Выкл"
    return f"{max(1, round(int(getattr(st, 'screen_off_sec', 60)) / 60.0))} мин"


def _fmt_off(sec):
    """[CLAUDE] тайм-аут гашения для отображения: '30 с' / '2 мин' / '2.5 мин'."""
    sec = int(sec)
    if sec < 60:
        return f"{sec} с"
    m = sec / 60.0
    return f"{int(m)} мин" if m == int(m) else f"{m:.1f} мин"


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

    def _draw_artist_line(self, img, draw, text, y):
        fnt = T.font(T.SZ_BODY)
        color = T.MUTED
        max_w = T.CONTENT_W
        text = str(text or "").strip()
        if not text:
            return
        if C.text_w(draw, text, fnt) <= max_w:
            C.text_centered(draw, text, fnt, color, y, cx=T.CONTENT_CX)
            return

        x = T.CONTENT_CX - max_w // 2
        text_w = C.text_w(draw, text, fnt)
        gap = 96
        speed = 28.0
        pause = 1.4
        cycle = pause + (text_w + gap) / speed
        t = time.monotonic() % cycle
        offset = 0 if t < pause else int((t - pause) * speed)

        layer_h = 44
        layer = Image.new("RGBA", (max_w, layer_h), (0, 0, 0, 0))
        ld = ImageDraw.Draw(layer)
        fill = color + (255,) if len(color) == 3 else color
        ld.text((-offset, 0), text, font=fnt, fill=fill)
        ld.text((text_w + gap - offset, 0), text, font=fnt, fill=fill)
        img.paste(layer.convert("RGB"), (x, y), layer)

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
        LH, ALH = 56, 40
        artist = (sess.artist or "").strip()
        block_h = len(lines) * LH + (ALH + 10 if artist else 0)
        y = max(T.CONTENT_TOP, T.MAIN_CY - block_h // 2)
        for line in lines:
            C.text_centered(draw, line, T.font(T.SZ_TITLE), T.FG, y, cx=T.CONTENT_CX); y += LH
        if artist:
            y += 10
            self._draw_artist_line(img, draw, artist, y)
        return img


class MacOSScreen(Screen):
    name = "macos"
    title = "macOS"
    fullscreen = True

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


class RouteBuilderScreen(Screen):
    name = "router"
    title = "Маршрут"
    fullscreen = True

    # [CLAUDE 2026-06-02] Patchbay GUI: ВХОД (слева) | ВЫХОД (справа), обе колонки СКРОЛЛЯТСЯ.
    # Строка устройства = две строки: имя (SZ_SMALL) + MAC-адрес (мелкий, FAINT).
    # верхняя полоса держит зазор от дуги (R1 = ARC_SAFE_X), нижний бар — на всю ширину
    L0, L1 = 36, 352            # левая колонка (входы)
    COLX = 368                  # вертикальный штриховой разделитель колонок
    R0, R1 = 384, T.ARC_SAFE_X  # правая колонка (выходы), не лезет под дугу/штрихи громкости
    HEAD_Y = 18                 # заголовки колонок
    COL_TOP = 70                # верх области скролла строк
    COL_BOTTOM = T.STATUSBAR_TOP - 6   # низ области скролла (над баром)
    ROW_H2 = 56                 # высота двухстрочной строки
    MAC_FONT = 16               # мелкий шрифт MAC-адреса (16: вторая строка не выпадает из rect)

    def __init__(self, emit=None):
        self.state = None
        self.emit = emit or (lambda intent, payload=None: None)
        self._scroll = {"input": 0.0, "output": 0.0}
        self._max_scroll = {"input": 0, "output": 0}

    def on_state(self, state):
        self.state = state

    @property
    def focus(self):
        # активная колонка = последняя, по которой кликнули (для скролла/подсветки)
        return getattr(self.state, "route_focus", "input") if self.state else "input"

    # scroll-плумбинг рантайма читает/пишет scroll_y; маппим его на активную колонку
    @property
    def scroll_y(self):
        return self._scroll.get(self.focus, 0.0)

    @scroll_y.setter
    def scroll_y(self, value):
        side = self.focus
        self._scroll[side] = max(0.0, min(float(self._max_scroll.get(side, 0)), float(value)))

    def _devices(self, side):
        if not self.state:
            return []
        return list(self.state.route_inputs if side == "input" else self.state.route_outputs)

    def on_input(self, event):
        # свайп влево/вправо — глобальная навигация вьюх (в gui_controller), не здесь.
        # Энкодер = громкость (глобально), сюда не доходит.
        if isinstance(event, tuple) and event and event[0] == "scroll":
            self.scroll_y = self.scroll_y - event[1]
            return True
        if event == Input.PRESS:
            ri = getattr(self.state, "route_input", "") if self.state else ""
            ro = getattr(self.state, "route_output", "") if self.state else ""
            if ri and ro and getattr(self.state, "route_compatible", None) is True:
                self.emit("route_activate")
            return True
        return False

    def _dot(self, draw, x, y, dev, dim=False):
        connected = bool(dev.get("connected"))
        online = bool(dev.get("online")) or connected
        color = T.FAINT if dim else (T.STATUS_OK if connected else (T.MUTED if online else T.FAINT))
        draw.ellipse((x - 6, y - 6, x + 6, y + 6), fill=color)

    def _device_subline(self, dev):
        protos = sorted({
            str(proto)
            for endpoint in (dev.get("endpoints") or [])
            for proto in (endpoint.get("protocols") or [])
        })
        labels = []
        if "classic_a2dp_sink" in protos:
            labels.append("A2DP in")
        if "classic_a2dp_source" in protos:
            labels.append("A2DP out")
        if "classic_avrcp" in protos:
            labels.append("AVRCP")
        if "ble_gatt_bootstrap" in protos:
            labels.append("GATT")
        if "ble_l2cap_coc_session" in protos:
            labels.append("CTSP")
        if "ble_ams" in protos:
            labels.append("AMS")
        if "ble_ancs" in protos:
            labels.append("ANCS")
        profile = ((dev.get("metadata") or {}).get("capability_profile") or {})
        status = str(profile.get("probe_status") or "").strip()
        if status and status not in ("ready", "ok"):
            labels.append(status)
        unknowns = profile.get("unknowns") or []
        if unknowns:
            labels.append("?" + ",".join(str(v).replace("_", "-") for v in unknowns[:2]))
        if labels:
            return " / ".join(labels)
        return str(dev.get("address") or dev.get("type") or "")

    def _column(self, draw, regions, side, x0, x1, title, sel_key, intent):
        focused = self.focus == side
        draw.text((x0 + 12, self.HEAD_Y), title, font=T.font(28),
                  fill=T.ACCENT if focused else T.MUTED)
        rows = {}
        devs = self._devices(side)
        # границы скролла
        view_h = self.COL_BOTTOM - self.COL_TOP
        self._max_scroll[side] = max(0, len(devs) * self.ROW_H2 - view_h)
        self._scroll[side] = max(0.0, min(float(self._max_scroll[side]), self._scroll[side]))
        scroll = self._scroll[side]
        if not devs:
            draw.text((x0 + 12, self.COL_TOP + 6), "нет устройств",
                      font=T.font(T.SZ_SMALL), fill=T.FAINT)
            return rows
        for idx, dev in enumerate(devs):
            y = self.COL_TOP + idx * self.ROW_H2 - scroll
            if y + self.ROW_H2 <= self.COL_TOP or y >= self.COL_BOTTOM:
                continue                                    # вне видимой области — клип
            key = dev.get("key") or dev.get("address")
            selected = (key == sel_key) or bool(dev.get("route_" + side))
            connected = bool(dev.get("connected"))
            mode = str(getattr(self.state, "operation_mode", "playnow") or "playnow")
            self_key = getattr(self.state, "SELF_OUTPUT_KEY", "carthing")
            dim_output = side == "output" and mode != "commutator" and key != self_key
            # ЗЕЛЁНЫЙ = реально подключён сейчас; выбранный, но не подключён — акцент; иначе обычный
            name_col = T.FAINT if dim_output else (T.STATUS_OK if connected else (T.ACCENT if selected else T.FG))
            rect = (x0, int(y), x1, int(y + self.ROW_H2 - 8))
            if selected:
                # 2026-06-18 owner GUI rule: Play Now is a quiet mode.  External
                # outputs remain selectable, but they must not look active until
                # Commutator owns the route graph and radio work.
                draw.rectangle(
                    rect,
                    fill=(T.BG if dim_output else T.SURFACE_SEL),
                    outline=(T.FAINT if dim_output else (T.STATUS_OK if connected else T.ACCENT)),
                    width=2,
                )
            name = dev.get("label") or dev.get("address") or "Device"
            name = C.truncate(draw, name, T.font(T.SZ_SMALL), (x1 - x0) - 44)
            draw.text((x0 + 12, int(y) + 4), name, font=T.font(T.SZ_SMALL), fill=name_col)
            # [CLAUDE 2026-06-11] вторая строка ВНУТРИ рамки (раньше MAC на y+30
            # шрифтом 18 выпадал за низ rect y+48 — «явно некрасиво»). У self-выхода
            # (Car Thing) адреса нет — показываем тип (Play Now), а не тире-подчёркивание.
            sub = self._device_subline(dev)
            sub = C.truncate(draw, sub, T.font(self.MAC_FONT), (x1 - x0) - 44)
            draw.text((x0 + 12, int(y) + 28), sub, font=T.font(self.MAC_FONT), fill=T.FAINT)
            self._dot(draw, x1 - 16, int(y) + self.ROW_H2 // 2 - 4, dev, dim=dim_output)
            if regions is not None:
                regions.add(rect, intent, payload=key)
            rows[key] = int(y) + self.ROW_H2 // 2 - 4
        return rows

    def render(self, regions=None):
        img, draw = self.blank()
        if not self.state:
            return img
        ri = getattr(self.state, "route_input", "")
        ro = getattr(self.state, "route_output", "")
        active = bool(getattr(self.state, "route_active", False))
        compat = getattr(self.state, "route_compatible", None)
        ready = bool(ri and ro)

        # штриховые делители (визуальный язык дуги/сегментов, не сплошные «секции»)
        T.dashed_line(draw, self.L0, self.COL_TOP - 6, self.R1, self.COL_TOP - 6)
        T.dashed_line(draw, self.COLX, self.COL_TOP, self.COLX, self.COL_BOTTOM)

        in_rows = self._column(draw, regions, "input", self.L0, self.L1, "ВХОД", ri, "route_input_select")
        out_rows = self._column(draw, regions, "output", self.R0, self.R1, "ВЫХОД", ro, "route_output_select")

        # соединительный «кабель»: ЗЕЛЁНЫЙ только когда оба конца реально подключены;
        # несовместимо -> красный; иначе (выбрано, но не подключено) -> акцент.
        def _conn(devs, k):
            return any(bool(d.get("connected")) for d in devs
                       if (d.get("key") or d.get("address")) == k)
        both_connected = _conn(self.state.route_inputs, ri) and _conn(self.state.route_outputs, ro)
        if ri in in_rows and ro in out_rows:
            iy, oy = in_rows[ri], out_rows[ro]
            cable = (T.STATUS_OK if both_connected else
                     (T.WARN if compat is False else T.ACCENT))
            draw.line([(self.L1, iy), (self.COLX, iy), (self.COLX, oy), (self.R0, oy)],
                      fill=cable, width=3)

        # ── нижний бар: ТОЛЬКО круглые одинаковые кнопки-иконки по центру, БЕЗ текста.
        bar_top = T.STATUSBAR_TOP
        draw.rectangle([0, bar_top, T.W, T.H], fill=T.BG)
        T.progress_segments(draw, 0, bar_top, T.W, 0.0)     # сегментный делитель во всю ширину
        cy = bar_top + (T.H - bar_top) // 2 + 4
        R = 30                                              # одинаковый радиус всех кнопок

        # Состояние «Активировать»: цвет кодирует статус (текста нет).
        self_out = ro == getattr(self.state, "SELF_OUTPUT_KEY", "carthing")
        transfer_on = bool(getattr(self.state, "transfer_active", False))
        if self_out and not transfer_on:
            act_col, act_intent = T.MUTED, None            # Play Now по умолчанию — не CTA
        elif self_out and transfer_on:
            act_col, act_intent = T.ACCENT, "route_activate"
        elif active:
            act_col, act_intent = T.STATUS_OK, "route_activate"
        elif not ready:
            act_col, act_intent = T.FAINT, None
        elif compat is False:
            act_col, act_intent = T.WARN, None             # красный = несовместимо
        else:
            act_col, act_intent = T.STATUS_OK, "route_activate"

        # [настройки · LNK · add-in · add-out · ассистент] — по центру.
        # Add In is passive advertising for sources. Add Out is active inquiry
        # for speakers/receivers; the transport route still changes only via LNK.
        btns = [
            ("gear", T.MUTED, "open_settings", None),
            ("route", act_col, act_intent, None),
            ("add_in", T.MUTED, "settings_select", "pairing_input"),
            ("add_out", T.MUTED, "settings_select", "pairing_output"),
            ("orb",  T.MUTED, "assistant", None),
        ]
        n = len(btns)
        gap = 36
        if T.THEME == "terminal":
            # [CLAUDE 2026-06-11] терминальная тема: софт-кнопки [XXX] вместо кружков
            # (идея владельца: сокращения как на старых терминалах, без значков)
            TERM = {"gear": "SET", "route": "LNK", "add_in": "IN+", "add_out": "OUT+", "orb": "AST"}
            f = T.font(T.SZ_BODY)
            labels = ["[" + TERM[k] + "]" for k, _c, _i, _p in btns]
            widths = [int(draw.textlength(l, font=f)) for l in labels]
            total = sum(widths) + (n - 1) * gap
            x = (T.W - total) // 2
            for (kind, col, intent, payload), label, w in zip(btns, labels, widths):
                draw.text((x, cy - T.SZ_BODY // 2 - 2), label, font=f, fill=col)
                if regions is not None and intent is not None:
                    regions.add((x - 10, cy - R, x + w + 10, cy + R), intent, payload=payload)
                x += w + gap
            # 2026-06-18 owner GUI correction:
            # This line is the user's feedback channel for explicit/manual route
            # work.  A bare "ROUTE: -" looked like missing data while Play Now was
            # intentionally quiet.  Show the product mode and the current action
            # instead; if Play Now still sees an external output footprint, make
            # that mismatch visible instead of hiding it behind the selected mode.
            src_conn = getattr(self.state, "actual_source_connected", False)
            src_stream = getattr(self.state, "actual_source_streaming", False)
            recv_addr = getattr(self.state, "actual_receiver_addr", "")
            mode = str(getattr(self.state, "operation_mode", "playnow") or "playnow")
            status = str(getattr(self.state, "transfer_status", "") or "").lower()
            self_key = getattr(self.state, "SELF_OUTPUT_KEY", "carthing")
            external_connected = [
                d for d in (getattr(self.state, "route_outputs", []) or [])
                if (d.get("key") or d.get("address")) != self_key and d.get("connected")
            ]
            if mode == "commutator":
                if getattr(self.state, "transfer_scanning", False) or "scanning" in status:
                    route_text, route_col = "MODE: COMM SCAN", T.STATUS_WARN
                elif recv_addr and src_conn:
                    route_text = "MODE: COMM LINK" + (" PLAY" if src_stream else " WAIT")
                    route_col = T.STATUS_OK if src_stream else T.ACCENT
                elif external_connected:
                    route_text = f"MODE: COMM HOLD {len(external_connected)}"
                    route_col = T.STATUS_OK
                elif "no outputs" in status:
                    route_text, route_col = "MODE: COMM NO OUT", T.WARN
                else:
                    route_text, route_col = "MODE: COMM READY", T.ACCENT
            elif recv_addr or external_connected:
                route_text = "MODE: PLAY NOW EXT"
                route_col = T.WARN
            else:
                route_text = "MODE: PLAY NOW"
                route_col = T.STATUS_OK
            fs = T.font(T.SZ_SMALL)
            rtw = int(draw.textlength(route_text, font=fs))
            draw.text((T.W // 2 - rtw // 2, bar_top + 8), route_text, font=fs, fill=route_col)
            return img
        total = n * 2 * R + (n - 1) * gap
        x = (T.W - total) // 2 + R
        for kind, col, intent, payload in btns:
            draw.ellipse([x - R, cy - R, x + R, cy + R], outline=col, width=3)
            if kind == "gear":
                T.icon_gear(draw, x, cy, R - 12, color=col, width=2)
            elif kind == "route":
                T.icon_route(draw, x, cy, R - 10, color=col, width=3)
            elif kind == "add_in":
                T.icon_plus(draw, x, cy, R - 14, color=col, width=3)
                draw.arc([x - R + 14, cy - R + 14, x + R - 14, cy + R - 14],
                         start=140, end=250, fill=col, width=3)
                draw.polygon([(x - 8, cy + R - 18), (x - 20, cy + R - 14), (x - 12, cy + R - 6)],
                             fill=col)
            elif kind == "add_out":
                T.icon_plus(draw, x, cy, R - 14, color=col, width=3)
                draw.arc([x - R + 14, cy - R + 14, x + R - 14, cy + R - 14],
                         start=320, end=70, fill=col, width=3)
                draw.polygon([(x + 8, cy - R + 18), (x + 20, cy - R + 14), (x + 12, cy - R + 6)],
                             fill=col)
            elif kind == "orb":
                T.icon_ring(draw, x, cy, R - 12, color=col, width=3)
            if regions is not None and intent is not None:
                regions.add((x - R, cy - R, x + R, cy + R), intent, payload=payload)
            x += 2 * R + gap
        return img


# Compatibility aliases for old imports while the userspace is being rebuilt.
TransferScreen = RouteBuilderScreen


class SettingsScreen(Screen):
    """Accordion menu: parents expand inline to reveal children. Encoder moves
    selection over the visible (flattened) list; press toggles a parent or
    emits a leaf's intent."""

    name = "settings"
    title = "Настройки"
    fullscreen = True

    def __init__(self, on_select=None):
        self.on_select = on_select or (lambda key: None)
        self.items = [
            # [CLAUDE 2026-06-03] «Добавить устройство» убрано — сопряжение запускается
            # отдельной кнопкой [Сопряжение] в баре Routes, дублировать в настройках не нужно.
            {"key": "trusted", "label": "Доверенные устройства", "children": []},
            {"key": "display", "label": "Дисплей и яркость", "children": [
                # статическая заглушка: живой render-путь display строит единые
                # строки «− значение +» (DISPLAY_ADJUST ниже)
                ("brightness", "Яркость"),
            ]},
            {"key": "mode", "label": "Режим", "children": []},
            {"key": "client_toggle", "label": "Клиент"},
            {"key": "power_off", "label": "Отключение USB", "children": []},
            {"key": "about", "label": "О системе"},
        ]
        self.expanded = set()
        self.expanded_stack = []
        self.sel = 0
        self.top = 0          # legacy row offset fallback; pixel scroll owns normal touch lists
        self.scroll_y = 0
        self._max_scroll = 0
        self.state = None

    CARD_LINE_H = 30          # [CLAUDE 2026-06-03] компактный шаг для строк карточки устройства

    # [CLAUDE 2026-06-11] ЕДИНЫЙ паттерн под-настроек: «Имя   −  значение  +».
    # Решение владельца: у каждой регулируемой настройки видимые −/+, чтобы выбор
    # был очевиден. value-функции читают state при каждом рендере.
    # Подписи КОРОТКИЕ: моноширинный IBM Plex Mono шире прежнего шрифта,
    # длинные лезут под кнопку «−» (следить при добавлении новых).
    DISPLAY_ADJUST = {
        "brightness":  ("Яркость",   lambda st: f"{int(getattr(st, 'screen_brightness', 100)) if st else 100}%"),
        # «(рестарт)» — честное предупреждение: тема применяется рестартом runtime
        # («перезагрузка» полностью не влезает — Plex Mono наезжает на «−»)
        # «Сон» = единая шкала: Выкл / 1..10 мин / 20..60 мин (бывшие Сон+Гашение)
        "sleep":       ("Сон",       lambda st: _fmt_sleep(st)),
        # «Индикатор» уведомлений (слово «моргание» отклонено владельцем)
        "notif_blink": ("Индикатор", lambda st: "Вкл" if (bool(getattr(st, 'notif_blink', True)) if st else True) else "Выкл"),
    }

    def _viewport(self):
        start_y = CONTENT_TOP + 52
        bottom_y = T.H - 24
        return start_y, bottom_y

    def _row_h(self, row):
        """Высота строки: компактная для строк карточки (2-й уровень), иначе ROW_H (под палец)."""
        if row[0] >= 2 or str(row[1]).endswith("|cap"):
            return self.CARD_LINE_H
        return T.ROW_H

    def _row_offsets(self, rows):
        """Кумулятивные верхние координаты строк (переменная высота) + полная высота."""
        tops, y = [], 0
        for r in rows:
            tops.append(y)
            y += self._row_h(r)
        return tops, y

    def _update_scroll_bounds(self, rows=None):
        rows = rows if rows is not None else self._visible()
        start_y, bottom_y = self._viewport()
        _, total_h = self._row_offsets(rows)
        self._max_scroll = max(0, total_h - (bottom_y - start_y))
        self.scroll_y = max(0, min(self._max_scroll, self.scroll_y))
        return start_y, bottom_y

    def _ensure_row_visible(self, index, rows=None):
        if index is None:
            return
        rows = rows if rows is not None else self._visible()
        if not (0 <= index < len(rows)):
            return
        start_y, bottom_y = self._update_scroll_bounds(rows)
        tops, _ = self._row_offsets(rows)
        row_top = start_y + tops[index]
        row_bottom = row_top + self._row_h(rows[index])
        if row_top - self.scroll_y < start_y:
            self.scroll_y = row_top - start_y
        elif row_bottom - self.scroll_y > bottom_y:
            self.scroll_y = row_bottom - bottom_y
        self.scroll_y = max(0, min(self._max_scroll, self.scroll_y))

    def _last_child_index(self, rows, parent_index):
        last = parent_index
        for index in range(parent_index + 1, len(rows)):
            level = rows[index][0]
            if level == 0:
                break
            last = index
        return last

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
        if it["key"] == "display":      # [CLAUDE 2026-06-11] ВСЕ под-настройки = единый «− значение +»
            return [(k, spec[0]) for k, spec in self.DISPLAY_ADJUST.items()]
        if it["key"] == "mode":         # [CLAUDE 2026-06-13] выбор режима: подпункты с отметкой текущего
            import operation_mode as _om
            cur = getattr(self.state, "operation_mode", _om.DEFAULT) if self.state else _om.DEFAULT
            rows = []
            for m in _om.ALL:
                mark = "● " if m == cur else "○ "
                rows.append(("set_mode:" + m, mark + _om.label(m)))
            return rows
        if it["key"] == "power_off":    # Safe unplug: sync + read-only state + suspend.
            status = getattr(self.state, "power_unplug_status", "idle") if self.state else "idle"
            message = getattr(self.state, "power_unplug_message", "") if self.state else ""
            rows = []
            if status == "preparing":
                rows.append(("power_off_status", message or "Готовим...", T.STATUS_WARN))
                rows.append(("power_off_confirm", "⏻ Ждать"))
                return rows
            if status == "ready":
                rows.append(("power_off_status", message or "Готово", T.STATUS_OK))
            elif status == "error":
                rows.append(("power_off_status", message or "Ошибка подготовки", T.WARN))
                rows.append(("power_off_confirm", "⏻ Повторить"))
                return rows
            rows.append(("power_off_confirm", "⏻ Подготовить"))
            return rows
        return it.get("children", [])

    def _visible(self):
        """Flatten to rows: (level, key, label, expandable, expanded)."""
        import operation_mode as _om
        cur_mode = getattr(self.state, "operation_mode", _om.DEFAULT) if self.state else _om.DEFAULT
        rows = []
        for it in self.items:
            has_children = "children" in it
            plabel = it["label"]
            if it["key"] == "mode":          # [CLAUDE 2026-06-13] показываем активный режим на самом пункте
                plabel = f'{it["label"]}: {_om.label(cur_mode)}'
            elif it["key"] == "client_toggle":
                on = bool(getattr(self.state, "client_enabled", False)) if self.state else False
                plabel = f'{it["label"]}: {"Вкл" if on else "Выкл"}'
            rows.append((0, it["key"], plabel, has_children, it["key"] in self.expanded, None))
            if has_children and it["key"] in self.expanded:
                for child in self._children(it):
                    ckey, clabel = child[0], child[1]
                    color = child[2] if len(child) > 2 else None
                    # [CLAUDE 2026-06-03] Доверенное устройство — РАСКРЫВАЕМЫЙ узел: тап
                    # разворачивает карточку (тип/протоколы/возможности).
                    is_dev = ckey.startswith("trusted:")
                    rows.append((1, ckey, clabel, is_dev, ckey in self.expanded, color))
                    if is_dev and ckey in self.expanded:
                        for cap in self._device_caps(ckey):
                            rows.append((2, ckey + "|cap", cap, False, False, None))
        return rows

    def _device_caps(self, ckey):
        """[CLAUDE 2026-06-03] Карточка устройства: тип, протоколы, возможности — строками."""
        key = ckey.split("trusted:", 1)[1]
        devs = self.state.trusted if self.state else []
        dev = next((d for d in devs if d.get("key") == key or d.get("address") == key), None)
        if not dev:
            return ["— нет данных —"]
        protos = []
        for ep in dev.get("endpoints") or []:
            protos += ep.get("protocols") or []
        protos = sorted(set(str(p) for p in protos))
        caps = sorted(set(str(c) for c in dev.get("capabilities") or []))
        full = []
        t = dev.get("type") or dev.get("role")
        if t:
            full.append("Тип: " + str(t))
        if protos:
            full.append("Протоколы: " + ", ".join(protos))
        if caps:
            full.append("Возможности: " + ", ".join(caps))
        if not full:
            full.append("— нет данных (пересканировать) —")
        # [CLAUDE 2026-06-03] Переносим ПОЛНЫЙ текст по словам (не обрезаем) — каждую строку
        # карточки в несколько коротких. Рендерятся компактным шагом (CARD_LINE_H).
        out = []
        for s in full:
            out += self._wrap_chars(s, 46)
        return out

    @staticmethod
    def _wrap_chars(s, n):
        words, lines, cur = s.split(), [], ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > n:
                lines.append(cur); cur = w
            else:
                cur = (cur + " " + w) if cur else w
        if cur:
            lines.append(cur)
        return lines or [s]

    def _activate(self, i):
        """Действие над строкой i: раскрыть родителя или выбрать лист (= PRESS)."""
        rows = self._visible()
        if not (0 <= i < len(rows)):
            return
        self.sel = i
        level, key, _label, expandable, expanded, _color = rows[i]
        if expandable:
            if key in self.expanded:
                self.expanded.remove(key)
                self.expanded_stack = [item for item in self.expanded_stack if item != key]
            else:
                # [CLAUDE 2026-06-13] single-open: раскрытие пункта верхнего уровня
                # закрывает остальные top-level (лента не растягивается бесконечно).
                if level == 0:
                    top_keys = {it["key"] for it in self.items if "children" in it}
                    self.expanded -= top_keys
                    self.expanded_stack = [k for k in self.expanded_stack if k not in top_keys]
                self.expanded.add(key)
                self.expanded_stack = [item for item in self.expanded_stack if item != key]
                self.expanded_stack.append(key)
            rows_after = self._visible()
            if key in self.expanded:
                self._ensure_row_visible(self._last_child_index(rows_after, i), rows_after)
            else:
                self._ensure_row_visible(i, rows_after)
        else:
            self.on_select(key)

    def back(self):
        """Back inside Settings closes the last opened section before leaving Settings."""
        while self.expanded_stack and self.expanded_stack[-1] not in self.expanded:
            self.expanded_stack.pop()
        if not self.expanded_stack:
            return False
        key = self.expanded_stack.pop()
        self.expanded.discard(key)
        rows = self._visible()
        for index, row in enumerate(rows):
            if row[1] == key:
                self.sel = index
                self._ensure_row_visible(index, rows)
                break
        return True

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
        start_y, bottom_y = self._update_scroll_bounds(rows)
        tops, _ = self._row_offsets(rows)

        visible = []
        for i, row in enumerate(rows):
            y = start_y + tops[i] - self.scroll_y
            h = self._row_h(row)
            if y + h > start_y and y < bottom_y:
                visible.append((i, y, row))
        if visible and not any(i == self.sel for i, _y, _row in visible):
            self.sel = visible[0][0]

        for i, y, row in visible:
            level, key, label, expandable, expanded, color = rows[i]
            # [CLAUDE 2026-06-03] строка КАРТОЧКИ устройства (2-й уровень): полный текст (уже
            # перенесён по словам), компактный шаг, БЕЗ обрезки.
            if level >= 2 or key.endswith("|cap"):
                draw.text((56, y + 4), label, font=T.font(T.SZ_SMALL), fill=T.MUTED)
                continue
            # [CLAUDE 2026-06-11] единая строка под-настройки: «Имя  −  значение  +»
            if key in self.DISPLAY_ADJUST:
                name, value_fn = self.DISPLAY_ADJUST[key]
                rect = C.list_row(draw, y, name, selected=(i == self.sel),
                                  indent=24 if level else 0)
                rx0, ry0, rx1, ry1 = rect
                fbig = T.font(T.SZ_TITLE)
                draw.text((430, y - 6), "−", font=fbig, fill=T.FG)
                C.text_centered(draw, value_fn(self.state), T.font(T.SZ_META), T.ACCENT, y + 2, cx=545)
                draw.text((645, y - 6), "+", font=fbig, fill=T.FG)
                if regions is not None:
                    ra, rb = max(start_y, ry0), min(bottom_y, ry1)
                    regions.add((405, ra, 510, rb), "display_adjust", payload=(key, "-"))
                    regions.add((610, ra, 700, rb), "display_adjust", payload=(key, "+"))
                continue
            if key.startswith("trusted:"):
                remove_rect = (T.LIST_X1 - 46, y + 3, T.LIST_X1 - 8, y + 41)
                label_w = remove_rect[0] - 80
                shown = C.truncate(draw, label, T.font(T.SZ_BODY), label_w - 76)
                rect = C.list_row(draw, y, shown, selected=(i == self.sel),
                                  indent=24 if level else 0)
                if color is not None:
                    T.icon_dot(draw, 40, y + T.SZ_BODY // 2, 7, color=color)
                x0, y0, x1, y1 = remove_rect
                draw.line([x0 + 10, y0 + 10, x1 - 10, y1 - 10], fill=T.WARN, width=3)
                draw.line([x1 - 10, y0 + 10, x0 + 10, y1 - 10], fill=T.WARN, width=3)
                if regions is not None:
                    rx0, ry0, rx1, ry1 = rect
                    regions.add((rx0, max(start_y, ry0), rx1, min(bottom_y, ry1)),
                                "settings_tap", payload=i)
                    regions.add((remove_rect[0], max(start_y, remove_rect[1]),
                                 remove_rect[2], min(bottom_y, remove_rect[3])),
                                "trusted_remove", payload=key.split("trusted:", 1)[1])
                continue
            rect = C.list_row(draw, y, label, selected=(i == self.sel),
                              expandable=expandable, expanded=expanded,
                              indent=24 if level else 0)
            if color is not None:                              # цветная статус-точка по центру строки
                T.icon_dot(draw, 40, y + T.SZ_BODY // 2, 7, color=color)
            if regions is not None:
                rx0, ry0, rx1, ry1 = rect
                regions.add((rx0, max(start_y, ry0), rx1, min(bottom_y, ry1)),
                            "settings_tap", payload=i)         # тап -> выбрать+активировать строку i

        # [CLAUDE 2026-06-11] индикаторы прокрутки (решение владельца: явно показать,
        # что выше/ниже есть ещё меню): стрелки слева у краёв вьюпорта.
        if self.scroll_y > 4:
            C.scroll_arrow(draw, 12, start_y + 10, up=True)
        if self.scroll_y < self._max_scroll - 4:
            C.scroll_arrow(draw, 12, bottom_y - 10, up=False)
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
        # [CLAUDE 2026-06-03] Правый край = ARC_SAFE_X (716), как в Routes: НЕ лезть под дугу
        # громкости и под её зелёные чёрточки (они выпирают до ~733). Раньше было OCCLUSION_LEFT(740).
        right = T.ARC_SAFE_X
        maxw = right - tx - 8
        top_y = 74; bot_y = T.H - 6

        def header():
            draw.rectangle([0, 0, T.W, 62], fill=T.BG)    # маска для контента, заехавшего под шапку
            draw.text((28, 16), "Уведомления", font=T.font(34), fill=T.MUTED)
            draw.line([28, 60, right, 60], fill=T.HAIRLINE, width=2)

        if not notes:
            header()
            C.text_centered(draw, "Нет уведомлений", T.font(T.SZ_TITLE), T.FAINT, T.H // 2, cx=right // 2)
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
                draw.rectangle([x0, y - 4, right, y - 4 + item["content_h"]],
                               outline=T.SURFACE_SEL, width=2)
            if regions is not None:
                regions.add((x0, max(top_y, y - 4), right, min(bot_y, y - 4 + item["content_h"])),
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
        right = T.ARC_SAFE_X                              # [CLAUDE 2026-06-03] не лезть под дугу/чёрточки
        maxw = right - x0 - 8
        draw.text((x0, 16), n.get("app", ""), font=T.font(T.SZ_BODY), fill=T.ACCENT)
        draw.line([x0, 60, right, 60], fill=T.HAIRLINE, width=2)

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
    """[CLAUDE 2026-06-02] Полноэкранный сканер сопряжения на чёрном фоне, в общем стиле.
    Показывается пока AppState.pairing_mode=True. Кнопки отмены НЕТ — закрывает физический Back
    (мы везде используем Back). Дугу громкости рисует поверх Compositor, она остаётся видимой."""

    fullscreen = True
    X0 = 36
    X1 = T.ARC_SAFE_X            # держим зазор от дуги
    ROW_H2 = 56
    CONFIRM_H = 54
    STATUS_H = 34

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
        if event == Input.PRESS:
            status = getattr(self.state, "speaker_pairing_status", "") if self.state else ""
            if status in ("connect", "done"):
                return True
            selected = getattr(self.state, "selected_speaker_candidate", "") if self.state else ""
            if selected:
                self.emit("speaker_pair_confirm", selected)
            return True
        if isinstance(event, tuple) and event and event[0] == "scroll":
            candidates = self._visible_candidates()
            max_y = max(0, len(candidates) * self.ROW_H2 - (self._list_bottom() - 72))
            before = self.scroll_y
            self.scroll_y = max(0.0, min(float(max_y), self.scroll_y + float(event[1])))
            return abs(self.scroll_y - before) >= 0.01
        return False

    def _list_bottom(self):
        return T.H - self.CONFIRM_H - self.STATUS_H - 16

    def _visible_candidates(self):
        candidates = [
            cand for cand in (getattr(self.state, "speaker_candidates", []) or [])
            if bool(cand.get("audio")) or bool(cand.get("trusted_output"))
        ]
        return sorted(
            candidates,
            key=lambda c: (
                not bool(c.get("audio")),
                0 - int(c.get("rssi") or -999),
                str(c.get("label") or c.get("address") or ""),
                str(c.get("address") or ""),
            ),
        )

    def _scan_indicator(self, draw, cx, y):
        """[CLAUDE 2026-06-03] Единственный элемент-«живость»: бегущий ряд точек, пока
        сканер открыт. Никаких подписей."""
        n, gap = 5, 26
        t = int(time.monotonic() * 4) % n
        x0 = cx - (n - 1) * gap // 2
        for i in range(n):
            T.icon_dot(draw, x0 + i * gap, y, 6 if i == t else 4,
                       color=T.ACCENT if i == t else T.HAIRLINE)

    def _candidate_for(self, address):
        return next(
            (cand for cand in self._visible_candidates() if cand.get("address") == address),
            None,
        )

    def _status_line(self, selected, candidate):
        status = getattr(self.state, "speaker_pairing_status", "") if self.state else ""
        message = str(getattr(self.state, "pairing_message", "") or "").strip()
        if status == "done":
            return (message or "ADDED", T.STATUS_OK)
        if status == "connect":
            return (message or "CONNECTING", T.ACCENT)
        if status == "error":
            return (message or "ERROR", T.WARN)
        if candidate and candidate.get("trusted_output"):
            return ("ADDED", T.STATUS_OK)
        if selected and candidate:
            return (candidate.get("label") or selected, T.MUTED)
        return ("", T.FAINT)

    def _center_text(self, draw, rect, label, font, fill):
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = rect[0] + (rect[2] - rect[0] - text_w) // 2 - bbox[0]
        y = rect[1] + (rect[3] - rect[1] - text_h) // 2 - bbox[1]
        draw.text((x, y), label, font=font, fill=fill)

    def _render_input_instructions(self, draw, x0, x1):
        """Universal input-pairing copy for any second device.

        This modal is not a macOS-specific surface: the next input may be an
        iPad, another phone, a desktop computer, or a future transport peer.
        Keep the copy about the user's action and the advertised local name,
        not about one OS. 2026-06-18: added after live test showed that an
        empty ADD IN screen made pairing/debug state ambiguous.
        """
        device_name = str(getattr(self.state, "device_name", "") or "Car Thing").strip()
        title = "ADD DEVICE"
        title_f = T.font(T.SZ_TITLE)
        body_f = T.font(T.SZ_META)
        small_f = T.font(T.SZ_SMALL)
        max_w = x1 - x0

        tw = int(draw.textlength(title, font=title_f))
        draw.text(((x0 + x1 - tw) // 2, 104), title, font=title_f, fill=T.MUTED)

        y = 178
        body_lines = [
            "На втором устройстве:",
            "Settings / Bluetooth",
            "или Настройки / Bluetooth",
            "выбери это имя:",
        ]
        for line in body_lines:
            text = C.truncate(draw, line, body_f, max_w)
            tw = int(draw.textlength(text, font=body_f))
            draw.text(((x0 + x1 - tw) // 2, y), text, font=body_f, fill=T.FG)
            y += 34

        y += 10
        for line in C.wrap_lines(draw, device_name, body_f, max_w)[:2]:
            text = C.truncate(draw, line, body_f, max_w)
            tw = int(draw.textlength(text, font=body_f))
            draw.text(((x0 + x1 - tw) // 2, y), text, font=body_f, fill=T.ACCENT)
            y += 36

        hint = "Back = cancel"
        tw = int(draw.textlength(hint, font=small_f))
        draw.text(((x0 + x1 - tw) // 2, T.H - 64), hint, font=small_f, fill=T.FAINT)

    def render(self, img, regions):
        # Add In is a passive pairing surface: no inquiry rows, just a live
        # indicator that Car Thing is advertising/connectable for the source.
        # Add Out is the active scanner and shows selectable output candidates.
        draw = ImageDraw.Draw(img)
        X0, X1 = self.X0, self.X1
        w = X1 - X0
        draw.rectangle([0, 0, T.W, T.H], fill=T.BG)            # чёрный фон
        self._scan_indicator(draw, (X0 + X1) // 2, 32)         # «шевелится» = скан активен
        if getattr(self.state, "pairing_role", "") == "input":
            self._render_input_instructions(draw, X0, X1)
            return

        candidates = self._visible_candidates()
        list_bottom = self._list_bottom()
        max_y = max(0, len(candidates) * self.ROW_H2 - (list_bottom - 72))
        self.scroll_y = max(0.0, min(float(max_y), self.scroll_y))
        selected = getattr(self.state, "selected_speaker_candidate", "") or ""
        selected_candidate = self._candidate_for(selected)
        status = getattr(self.state, "speaker_pairing_status", "")
        pairing_busy = status in ("connect", "done")
        y = 72 - int(self.scroll_y)
        for cand in candidates:
            if y >= list_bottom:
                break
            if y + self.ROW_H2 < 72:
                y += self.ROW_H2
                continue
            name = cand.get("label") or cand.get("address") or "Device"
            addr = cand.get("address") or "—"
            trusted = bool(cand.get("trusted"))
            rect = (X0, y, X1, y + self.ROW_H2 - 8)
            if addr == selected:
                draw.rounded_rectangle(rect, radius=8, outline=T.ACCENT, width=2)
            draw.text((X0 + 12, y + 4), C.truncate(draw, name, T.font(T.SZ_BODY), w - 24),
                      font=T.font(T.SZ_BODY), fill=(T.STATUS_OK if trusted else T.FG))
            draw.text((X0 + 12, y + 34), C.truncate(draw, addr, T.font(18), w - 24),
                      font=T.font(18), fill=T.FAINT)
            regions.add(rect, "speaker_pair_select", payload=cand.get("address"))
            y += self.ROW_H2

        button = (X0, T.H - self.CONFIRM_H, X1, T.H - 10)
        status_text, status_color = self._status_line(selected, selected_candidate)
        if status_text:
            status_font = T.font(T.SZ_SMALL)
            C.text_centered(
                draw,
                C.truncate(draw, status_text, status_font, w - 24),
                status_font,
                status_color,
                button[1] - self.STATUS_H + 2,
                cx=(X0 + X1) // 2,
            )

        active = bool(selected) and not pairing_busy and not (
            selected_candidate and selected_candidate.get("trusted_output")
        )
        outline = T.ACCENT if active else T.HAIRLINE
        fill = T.SURFACE_SEL if active else T.BG
        draw.rounded_rectangle(button, radius=8, fill=fill, outline=outline, width=2)
        label = "ADDED" if (status == "done" or (
            selected_candidate and selected_candidate.get("trusted_output")
        )) else "LNK"
        f = T.font(T.SZ_BODY)
        self._center_text(draw, button, label, f, (T.FG if active else T.FAINT))
        if regions is not None and active:
            regions.add(button, "speaker_pair_confirm", payload=selected)
