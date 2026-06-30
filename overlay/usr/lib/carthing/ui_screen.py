"""Screen base + layered compositor + Display backends.

Compositor layers (bottom→top): active desktop · status bar · desktop dots ·
modal overlay. It hit-tests taps against the per-frame RegionSet and returns the
intent for the app to dispatch. Swipe switches desktops with a light slide.

No device-only imports → runs on macOS for PNG preview. The device injects a
real DRM display via DRMDisplayAdapter.
"""
import ctypes
import logging
import os
import asyncio
import time
from PIL import Image, ImageDraw

import ui_theme as T
from ui_components import RegionSet, text_w, truncate

log = logging.getLogger("carthing.ui")

NOTIFICATION_BLINK_PERIOD_S = 8.0
NOTIFICATION_BLINK_ON_S = 1.0


def notification_indicator_visible(unread, enabled, now=None):
    if not unread or not enabled:
        return False
    now = time.monotonic() if now is None else float(now)
    return now % NOTIFICATION_BLINK_PERIOD_S < NOTIFICATION_BLINK_ON_S


# ─── high-level input (decoupled from evdev) ──────────────────────────────────
class Input:
    ENCODER_CW = "encoder_cw"
    ENCODER_CCW = "encoder_ccw"
    PRESS = "press"
    BACK = "back"
    SETTINGS = "settings"
    BTN_1 = "btn_1"
    BTN_2 = "btn_2"
    BTN_3 = "btn_3"
    BTN_4 = "btn_4"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    SWIPE_UP = "swipe_up"
    SWIPE_DOWN = "swipe_down"
    EDGE_TOP = "edge_top"        # свайп от верхнего края вниз (открыть вью)
    EDGE_BOTTOM = "edge_bottom"  # свайп от нижнего края вверх (закрыть вью)
    # tap carries coordinates: ("tap", x, y)
    TAP = "tap"
    LONG_TAP = "long_tap"


# ─── display backends ─────────────────────────────────────────────────────────
class Display:
    def present(self, img, name=None):
        raise NotImplementedError


class DRMDisplayAdapter(Display):
    def __init__(self, drm):
        self.drm = drm
        self._native = None
        self._dst_addr = None
        self._native_failed = False
        # MacDisplay/pygame или WebDisplay/browser: no DRM mmap; present via blit() after rotate.
        self._mac_display = type(drm).__name__ in ("MacDisplay", "WebDisplay") or hasattr(drm, "set_on_event")
        if not self._mac_display:
            self._load_native_rotator()

    def _load_native_rotator(self):
        lib_path = os.path.join(os.path.dirname(__file__), "libcarthing_frame.so")
        if not os.path.exists(lib_path):
            log.info("Display: native frame rotator unavailable; using Pillow fallback")
            return
        try:
            lib = ctypes.CDLL(lib_path)
            fn = lib.carthing_rotate_rgb_to_bgrx_cw
            fn.argtypes = [
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_void_p,
                ctypes.c_int,
                ctypes.c_int,
                ctypes.c_int,
            ]
            fn.restype = ctypes.c_int
            self._native = fn
            self._dst_addr = self.drm.buffer_address()
            log.info("Display: native frame rotator active")
        except Exception:
            log.exception("Display: failed to load native frame rotator; using Pillow fallback")
            self._native = None
            self._dst_addr = None

    def present(self, img, name=None):
        if self._mac_display:
            # [CLAUDE 2026-06-03] БЕЗ rotate(-90): поворот нужен только для физически
            # повёрнутой портретной панели устройства. На мониторе Mac/в браузере показываем
            # канвас 800x480 как есть (ровно), иначе весь экран лежит на боку.
            self.drm.blit(img.convert("RGBA").tobytes())
            return
        if self._native is not None and not self._native_failed:
            try:
                src = img.tobytes("raw", "RGB")
                ret = self._native(
                    src,
                    img.width,
                    img.height,
                    ctypes.c_void_p(self._dst_addr),
                    self.drm.width,
                    self.drm.height,
                    self.drm.pitch,
                )
                if ret == 0:
                    return
                log.error("Display: native frame rotator rejected frame ret=%s", ret)
            except Exception:
                log.exception("Display: native frame rotator failed; using Pillow fallback")
            self._native_failed = True
        img = img.rotate(-90, expand=True)        # 800x480 -> 480x800
        self.drm.blit(img.tobytes("raw", "BGRX"))


class PreviewDisplay(Display):
    """Dev Mac: save the landscape PNG as a human reads it on the device."""

    def __init__(self, out_dir):
        import os
        self.out_dir = out_dir
        os.makedirs(out_dir, exist_ok=True)
        self.last_path = None

    def present(self, img, name=None):
        import os
        path = os.path.join(self.out_dir, (name or "frame") + ".png")
        img.save(path)
        self.last_path = path
        return path


# ─── screen base ──────────────────────────────────────────────────────────────
class Screen:
    name = "screen"
    title = "Screen"

    def render(self, regions=None) -> Image.Image:
        """Return a WxH landscape image. If `regions` given, register tappable
        InteractiveRegions into it (canvas coords)."""
        raise NotImplementedError

    def on_input(self, event) -> bool:
        return False

    def on_state(self, state):
        pass

    @staticmethod
    def blank():
        img = Image.new("RGB", (T.W, T.H), T.BG)
        return img, ImageDraw.Draw(img)


# ─── compositor ───────────────────────────────────────────────────────────────
class Compositor:
    """Owns desktops + status bar + modal; renders layers and routes input."""

    def __init__(self, display, screens, status_bar=None, anim=None,
                 state=None, on_intent=None, show_dots=True, pairing_modal=None,
                 nav_order=None):
        assert screens
        self.display = display
        self.screens = screens
        self.status_bar = status_bar
        self.anim = anim
        self.state = state
        self.on_intent = on_intent or (lambda intent, payload=None: None)
        self.show_dots = show_dots
        # [CLAUDE 2026-06-02] какие вью участвуют в горизонтальной навигации (точки-индикатор)
        self.nav_order = nav_order
        self._active = 0
        self.modal = None
        self._pairing_modal = pairing_modal
        self._regions = RegionSet()
        self._shade = None        # интерактивная «шторка»: {p, bg, panel} или None

    @property
    def active(self):
        # active desktop lives in AppState (unidirectional) when available
        if self.state is not None and hasattr(self.state, "active_desktop"):
            return self.state.active_desktop
        return self._active

    @active.setter
    def active(self, v):
        if self.state is not None and hasattr(self.state, "active_desktop"):
            self.state.active_desktop = v
        else:
            self._active = v

    def _sync_modal(self):
        """Derive the modal from state (unidirectional): show the pairing modal
        while AppState.pairing_mode is True."""
        if self._pairing_modal is None:
            return
        want = bool(getattr(self.state, "pairing_mode", False))
        if want and self.modal is not self._pairing_modal:
            self.modal = self._pairing_modal
        elif not want and self.modal is self._pairing_modal:
            self.modal = None

    @property
    def current(self):
        return self.screens[self.active]

    # ── input ──────────────────────────────────────────────────────────────
    def handle_input(self, event):
        self._sync_modal()
        if isinstance(event, tuple) and event and event[0] == Input.TAP:
            return self._handle_tap(event[1], event[2])
        if isinstance(event, tuple) and event and event[0] == Input.LONG_TAP:
            return self._handle_long_tap(event[1], event[2])
        if self.modal is not None:
            if self.modal.on_input(event):
                self.render()
            return True
        if event == Input.SWIPE_LEFT:
            return self._switch(+1)
        if event == Input.SWIPE_RIGHT:
            return self._switch(-1)
        if self.current.on_input(event):
            self.render()
            return True
        return False

    def _handle_tap(self, x, y):
        hit = self._regions.hit(x, y)
        if hit:
            # [CLAUDE 2026-06-11 v3] обратная связь = большое МЯГКОЕ пятно света под
            # пальцем, БЕЗ границ (v1-кольцо и v2-прямоугольник отклонены владельцем:
            # «рандомно» / «разного размера, опять границы»). Радиальный градиент,
            # вспыхнул и погас — инструментами самого экрана.
            self._tap_flash = (x, y, time.monotonic())
            self.on_intent(hit.intent, hit.payload)
            try:
                loop = asyncio.get_event_loop()
                loop.call_later(0.05, self.render)
                loop.call_later(0.28, self.render)
            except Exception:
                pass
            return True
        return False

    def _handle_long_tap(self, x, y):
        hit = self._regions.hit(x, y)
        if not hit:
            return False
        self.on_intent(hit.intent, hit.payload)
        return True

    def _switch(self, delta):
        n = len(self.screens)
        if n < 2:
            return False
        if self.anim:
            self.anim.start_transition(delta)
        self.active = (self.active + delta) % n   # setter writes state.active_desktop
        self.render()
        return True

    def animate_switch(self, target, direction):
        """[CLAUDE 2026-06-02] Анимированный переход на конкретный вью (target) со слайдом
        в направлении direction (+1 = новый въезжает справа, -1 = слева). В отличие от _switch
        не предполагает соседства индексов — исходный экран запоминается явно."""
        if target == self.active:
            return False
        if self.anim:
            self.anim.start_transition(direction, from_index=self.active)
        self.active = target
        self.render()
        return True

    def open_modal(self, modal):
        self.modal = modal
        self.render()

    def close_modal(self):
        self.modal = None
        self.render()

    def broadcast_state(self, state):
        self.state = state
        for s in self.screens:
            s.on_state(state)
        if self.modal:
            self.modal.on_state(state)
        self.render()

    # ── render ───────────────────────────────────────────────────────────────
    def render(self):
        self._sync_modal()
        if self.anim is not None:
            self.anim.tick()
        if bool(getattr(self.state, "screensaver_active", False)):
            self._regions.clear()
            img = Image.new("RGB", (T.W, T.H), (0, 0, 0))
            T.draw_clock(
                ImageDraw.Draw(img),
                getattr(self.state, "clock_text", "--:--"),
                T.W // 2,
                T.H // 2,
                size=164,
                date_text=getattr(self.state, "clock_date_text", ""),
                date_size=36,
                gap=24,
            )
            return self.display.present(
                T.postprocess(img),
                name="screensaver",
            )
        if self._shade is not None:                  # интерактивная шторка тянется/доводится
            return self._present_shade()
        self._regions.clear()
        transitioning = self.anim and self.anim.transition_active

        if transitioning:
            img = self._render_transition()      # regions skipped mid-slide
        else:
            img = self.current.render(self._regions)

        # Fullscreen views own the whole panel: no bottom bar, dots, or encoder
        # arc over settings/notifications/lists.
        fullscreen = getattr(self.current, "fullscreen", False) and not transitioning
        self._draw_overlays(img, full=fullscreen)
        self._draw_call_banner(img)
        if self.modal is not None:
            self._draw_modal(img)
            # дуга громкости остаётся видна поверх полноэкранного модала (энкодер всегда активен)
            if getattr(self.modal, "fullscreen", False):
                cs = getattr(self.state, "control_source", None) if self.state else None
                T.encoder_arc(ImageDraw.Draw(img), level=(cs.volume if cs is not None else None))

        img = self._apply_tap_flash(img)
        return self.display.present(T.postprocess(img), name=self.current.name)

    def _draw_call_banner(self, img):
        notifications = (
            list(getattr(self.state, "notifications", []) or [])
            if self.state is not None
            else []
        )
        call = next(
            (
                item
                for item in reversed(notifications)
                if str(item.get("category") or "") == "IncomingCall"
            ),
            None,
        )
        if call is None:
            return
        draw = ImageDraw.Draw(img)
        rect = (20, 18, T.ARC_SAFE_X, 148)
        draw.rectangle(rect, fill=T.SURFACE, outline=T.ACCENT, width=2)
        draw.text(
            (34, 30),
            "ВХОДЯЩИЙ ЗВОНОК",
            font=T.font(T.SZ_SMALL),
            fill=T.ACCENT,
        )
        title = str(call.get("title") or call.get("app") or "iPhone")
        draw.text(
            (34, 62),
            truncate(draw, title, T.font(T.SZ_BODY), 380),
            font=T.font(T.SZ_BODY),
            fill=T.FG,
        )
        body = str(call.get("body") or "")
        if body:
            draw.text(
                (34, 104),
                truncate(draw, body, T.font(T.SZ_SMALL), 350),
                font=T.font(T.SZ_SMALL),
                fill=T.MUTED,
            )
        uid = call.get("uid")
        if call.get("negative_action") and uid is not None:
            negative = (448, 38, 560, 126)
            label = str(call.get("negative_label") or "ОТКЛ.")
            width = text_w(draw, label, T.font(T.SZ_SMALL))
            draw.text(
                (
                    (negative[0] + negative[2] - width) // 2,
                    72,
                ),
                label,
                font=T.font(T.SZ_SMALL),
                fill=T.STATUS_OFF,
            )
            self._regions.add(
                negative,
                "notif_action",
                payload={"uid": uid, "positive": False},
            )
        if call.get("positive_action") and uid is not None:
            positive = (570, 38, 700, 126)
            label = str(call.get("positive_label") or "ПРИНЯТЬ")
            width = text_w(draw, label, T.font(T.SZ_SMALL))
            draw.text(
                (
                    (positive[0] + positive[2] - width) // 2,
                    72,
                ),
                label,
                font=T.font(T.SZ_SMALL),
                fill=T.STATUS_OK,
            )
            self._regions.add(
                positive,
                "notif_action",
                payload={"uid": uid, "positive": True},
            )

    _FLASH_R = 78           # радиус пятна вспышки (большое, как просил владелец)
    _flash_sprite = None    # кэш радиального градиента (строится один раз)

    def _apply_tap_flash(self, img):
        """[CLAUDE 2026-06-11 v3] Большое мягкое пятно света под пальцем: радиальный
        градиент (ярко в центре, плавно в ноль к краю), screen-наложение, НИКАКИХ
        контуров/рамок. Затухает за ~0.22 с (два отложенных рендера)."""
        flash = getattr(self, "_tap_flash", None)
        if flash is None:
            return img
        age = time.monotonic() - flash[2]
        if age >= 0.22:
            return img
        if Compositor._flash_sprite is None:
            from PIL import ImageFilter
            R = Compositor._FLASH_R
            mask = Image.new("L", (2 * R, 2 * R), 0)
            md = ImageDraw.Draw(mask)
            md.ellipse([R * 0.45, R * 0.45, R * 1.55, R * 1.55], fill=255)
            Compositor._flash_sprite = mask.filter(ImageFilter.GaussianBlur(R * 0.30))
        from PIL import ImageChops
        R = Compositor._FLASH_R
        fade = 1.0 - age / 0.22
        cx, cy = int(flash[0]), int(flash[1])
        x0, y0 = cx - R, cy - R
        # crop вспышки, обрезанный краями экрана
        bx0, by0 = max(0, x0), max(0, y0)
        bx1, by1 = min(img.width, x0 + 2 * R), min(img.height, y0 + 2 * R)
        if bx1 <= bx0 or by1 <= by0:
            return img
        sprite = Compositor._flash_sprite.crop((bx0 - x0, by0 - y0, bx1 - x0, by1 - y0))
        if fade < 1.0:
            sprite = sprite.point(lambda v: int(v * fade))
        glow = Image.merge("RGB", [sprite.point(lambda v, c=c: v * c // 255)
                                   for c in T.ACCENT])
        box = (bx0, by0, bx1, by1)
        img.paste(ImageChops.screen(img.crop(box), glow), box)
        return img

    def _draw_overlays(self, img, full=False):
        """[CLAUDE 2026-06-02] Дуга громкости + зона энкодера — ВСЕГДА верхний слой, на любом
        вью (физический регулятор всегда виден/активен). Статусбар и точки-индикатор — только
        на home-поверхности; полноэкранные вью держат правый отступ под дугу (LIST_X1=CONTENT_X1)."""
        draw = ImageDraw.Draw(img)
        vol = None
        if self.state is not None:
            cs = getattr(self.state, "control_source", None)
            vol = cs.volume if cs is not None else None
        unread = getattr(self.state, "unread_count", 0) if self.state else 0
        astate = getattr(self.state, "assistant_state", "idle") if self.state else "idle"
        if self.anim is not None:
            self.anim.set_pulsing(astate in ("listening", "thinking"))   # пульс орба
        blink_on = getattr(self.state, "notif_blink", True) if self.state else True
        if notification_indicator_visible(unread, blink_on):
            T.encoder_zone_glow(draw)
        T.encoder_arc(draw, level=vol)                 # ВСЕГДА — поверх любого вью
        if not full:
            if self.status_bar:
                self.status_bar.render(img, self._regions, self.anim, self.state)
            if self.show_dots:
                self._draw_dots(draw)

    # ── интерактивная «шторка» (вытягивание панели за пальцем) ─────────────────
    def _compose_full(self, index):
        """Полный кадр экрана index (со всеми overlays, если он не полноэкранный)."""
        scr = self.screens[index]
        img = scr.render(None)                       # без регистрации регионов (фон/панель)
        if not getattr(scr, "fullscreen", False):
            self._draw_overlays(img)
        return img

    def begin_shade(self, bg_index, panel_index, p):
        """Старт интерактивной шторки: фон и панель рендерим ПО РАЗУ (дальше только сдвиг)."""
        self._shade = {"p": max(0.0, min(1.0, p)),
                       "bg": self._compose_full(bg_index),
                       "panel": self._compose_full(panel_index)}

    def update_shade(self, p):
        if self._shade is not None:
            self._shade["p"] = max(0.0, min(1.0, p))

    def end_shade(self):
        self._shade = None

    @property
    def shade_active(self):
        return self._shade is not None

    def _present_shade(self):
        # «Оконная штора»: панель раскрывается СВЕРХУ вниз, её нижний край = позиция пальца.
        # Шапка/контент видны сразу (они вверху панели), фон виден ниже раскрытой части.
        s = self._shade
        base = s["bg"].copy()
        h = int(s["p"] * T.H)                        # высота раскрытой части (нижний край за пальцем)
        if h > 0:
            base.paste(s["panel"].crop((0, 0, T.W, h)), (0, 0))
        self._draw_overlays(base, full=True)
        return self.display.present(T.postprocess(base), name="shade")

    def _render_transition(self):
        p = self.anim.transition_progress
        d = self.anim.transition_dir
        off = int(T.W * p)
        cur = self.current.render(None)
        frm = getattr(self.anim, "transition_from", None)
        prev_idx = frm if frm is not None else (self.active - d) % len(self.screens)
        outgoing = self.screens[prev_idx].render(None)
        canvas = Image.new("RGB", (T.W, T.H), T.BG)
        if d > 0:   # next: outgoing slides left, current enters from right
            canvas.paste(outgoing, (-off, 0))
            canvas.paste(cur, (T.W - off, 0))
        else:       # prev: outgoing slides right, current enters from left
            canvas.paste(outgoing, (off, 0))
            canvas.paste(cur, (-T.W + off, 0))
        return canvas

    def _draw_dots(self, draw):
        order = self.nav_order if self.nav_order else list(range(len(self.screens)))
        n = len(order)
        if n <= 1:
            return
        try:
            cur = order.index(self.active) + 1
        except ValueError:
            cur = 1
        f = T.font(T.SZ_SMALL)
        label = f"< {cur}/{n} >"
        tw = int(draw.textlength(label, font=f))
        x = T.W // 2 - tw // 2
        y = T.STATUSBAR_TOP + 5   # top-left; SZ_SMALL=22 → visual center at +16
        draw.text((x, y), label, font=f, fill=T.HAIRLINE)
        x_num = x + int(draw.textlength("< ", font=f))
        draw.text((x_num, y), str(cur), font=f, fill=T.ACCENT)

    def _draw_modal(self, img):
        # полноэкранный модал сам заливает чёрный фон; иначе — затемняем подложку
        if not getattr(self.modal, "fullscreen", False):
            overlay = Image.new("RGB", (T.W, T.H), (0, 0, 0))
            img.paste(Image.blend(img, overlay, 0.55), (0, 0))
        self._regions.clear()            # modal is exclusive for hit-testing
        self.modal.render(img, self._regions)
