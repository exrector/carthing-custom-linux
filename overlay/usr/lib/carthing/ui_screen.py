"""Screen base + layered compositor + Display backends.

Compositor layers (bottom→top): active desktop · status bar · desktop dots ·
modal overlay. It hit-tests taps against the per-frame RegionSet and returns the
intent for the app to dispatch. Swipe switches desktops with a light slide.

No device-only imports → runs on macOS for PNG preview. The device injects a
real DRM display via DRMDisplayAdapter.
"""
from PIL import Image, ImageDraw

import ui_theme as T
from ui_components import RegionSet


# ─── high-level input (decoupled from evdev) ──────────────────────────────────
class Input:
    ENCODER_CW = "encoder_cw"
    ENCODER_CCW = "encoder_ccw"
    PRESS = "press"
    BACK = "back"
    BTN_1 = "btn_1"
    BTN_2 = "btn_2"
    BTN_3 = "btn_3"
    BTN_4 = "btn_4"
    SWIPE_LEFT = "swipe_left"
    SWIPE_RIGHT = "swipe_right"
    # tap carries coordinates: ("tap", x, y)
    TAP = "tap"


# ─── display backends ─────────────────────────────────────────────────────────
class Display:
    def present(self, img, name=None):
        raise NotImplementedError


class DRMDisplayAdapter(Display):
    def __init__(self, drm):
        self.drm = drm

    def present(self, img, name=None):
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
                 state=None, on_intent=None, show_dots=True, pairing_modal=None):
        assert screens
        self.display = display
        self.screens = screens
        self.status_bar = status_bar
        self.anim = anim
        self.state = state
        self.on_intent = on_intent or (lambda intent, payload=None: None)
        self.show_dots = show_dots
        self.active = 0
        self.modal = None
        self._pairing_modal = pairing_modal
        self._regions = RegionSet()

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
            self.on_intent(hit.intent, hit.payload)
            return True
        return False

    def _switch(self, delta):
        n = len(self.screens)
        if n < 2:
            return False
        if self.anim:
            self.anim.start_transition(delta)
        self.active = (self.active + delta) % n
        if self.state is not None and hasattr(self.state, "active_desktop"):
            self.state.active_desktop = self.active   # control_source follows the desktop
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
        self._regions.clear()
        transitioning = self.anim and self.anim.transition_active

        if transitioning:
            img = self._render_transition()      # regions skipped mid-slide
        else:
            img = self.current.render(self._regions)

        draw = ImageDraw.Draw(img)
        T.encoder_arc(draw)        # right-edge outline of the physical rotary dial
        if self.status_bar:
            self.status_bar.render(draw, self._regions, self.anim, self.state)
        if self.show_dots and len(self.screens) > 1:
            self._draw_dots(draw)
        if self.modal is not None:
            self._draw_modal(img)

        return self.display.present(img, name=self.current.name)

    def _render_transition(self):
        p = self.anim.transition_progress
        d = self.anim.transition_dir
        off = int(T.W * p)
        cur = self.current.render(None)
        prev_idx = (self.active - d) % len(self.screens)
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
        # along the top of the bottom bar (transport sits below them)
        n = len(self.screens)
        gap = 22
        x0 = T.W // 2 - (n - 1) * gap // 2
        y = T.STATUSBAR_TOP + 16
        for i in range(n):
            col = T.ACCENT if i == self.active else T.FAINT
            T.icon_dot(draw, x0 + i * gap, y, 4, color=col)

    def _draw_modal(self, img):
        # dim the backdrop, then let the modal draw itself
        overlay = Image.new("RGB", (T.W, T.H), (0, 0, 0))
        img.paste(Image.blend(img, overlay, 0.55), (0, 0))
        self._regions.clear()            # modal is exclusive for hit-testing
        self.modal.render(img, self._regions)
