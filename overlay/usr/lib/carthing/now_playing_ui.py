"""
Now Playing UI for Car Thing (480×800 portrait DRM display).

Layout zones in 800×480 landscape (before rotation):
    [ clock bar 36px ]
    [ ............... now playing region ............... ]
    [ notification overlay 96px, slides in for ttl_seconds ]

Updates:
    render(state)                 — full repaint, called on AMS update or tick
    set_clock(text)               — sets top-right HH:MM string
    show_notification(...)        — pops a card overlay for ttl seconds
    tick()                        — call once a second to time out the overlay
"""
import os
import time
import logging

from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

BG          = (0,   0,   0)
TITLE_COL   = (255, 255, 255)
ARTIST_COL  = (160, 160, 160)
META_COL    = (90,  90,  90)
BAR_BG      = (30,  30,  30)
BAR_FG      = (255, 255, 255)
CLOCK_COL   = (200, 200, 200)
NOTIF_BG    = (24,  24,  28)
NOTIF_TITLE = (255, 255, 255)
NOTIF_MSG   = (170, 170, 170)
NOTIF_TAG   = (90,  140, 220)

W, H = 800, 480  # landscape; rotated 90° before blit → framebuffer 480×800

CLOCK_BAR_H = 36
NOTIF_BAR_H = 96
NOTIF_MARGIN_X = 28

_FONT_CANDIDATES = [
    os.environ.get("CARTHING_FONT_PATH", ""),
    "/usr/share/fonts/truetype/DejaVuSans.ttf",
]


def _find_font(size, bold=False):
    for candidate in _FONT_CANDIDATES:
        if not candidate:
            continue
        try:
            return ImageFont.truetype(candidate, size)
        except Exception:
            continue
    return ImageFont.load_default()


class NowPlayingUI:
    def __init__(self, display):
        self.display = display
        self.font_title  = _find_font(40, bold=True)
        self.font_artist = _find_font(36)
        self.font_meta   = _find_font(26)
        self.font_clock  = _find_font(24)
        self.font_notif_tag   = _find_font(18)
        self.font_notif_title = _find_font(26, bold=True)
        self.font_notif_msg   = _find_font(22)
        log.info("UI fonts loaded")

        self._clock_text = ""
        self._notif = None
        self._notif_until = 0.0
        self._last_state = None

    # ── public API ────────────────────────────────────────────────────────

    def set_clock(self, text: str):
        self._clock_text = text or ""

    def show_notification(self, category: str, app_id: str, title: str,
                          message: str, ttl_seconds: float = 8.0):
        self._notif = {
            "category": category or "Notification",
            "app": app_id or "",
            "title": title or "",
            "message": message or "",
        }
        self._notif_until = time.monotonic() + ttl_seconds
        log.info("UI notification: %s — %s", title, message[:60])

    def clear_notification(self):
        self._notif = None
        self._notif_until = 0.0

    def tick(self):
        """Call ~once per second to expire overlays. Returns True if repaint needed."""
        if self._notif is not None and time.monotonic() >= self._notif_until:
            self._notif = None
            return True
        return False

    def render(self, state=None):
        if state is None:
            state = self._last_state
        else:
            self._last_state = state

        img  = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        self._draw_clock_bar(draw)
        if state is not None:
            self._draw_now_playing(draw, state)
        if self._notif is not None and time.monotonic() < self._notif_until:
            self._draw_notification(draw, self._notif)

        img = img.rotate(-90, expand=True)  # 800×480 → 480×800
        raw = img.tobytes('raw', 'BGRX')
        self.display.blit(raw)

    # ── zones ─────────────────────────────────────────────────────────────

    def _draw_clock_bar(self, draw):
        # Subtle separator line at the bottom of the bar
        draw.line([(0, CLOCK_BAR_H), (W, CLOCK_BAR_H)], fill=(20, 20, 20), width=1)
        if not self._clock_text:
            return
        bbox = draw.textbbox((0, 0), self._clock_text, font=self.font_clock)
        tw = bbox[2] - bbox[0]
        x = W - tw - 20
        y = (CLOCK_BAR_H - (bbox[3] - bbox[1])) // 2 - bbox[1]
        draw.text((x, y), self._clock_text, font=self.font_clock, fill=CLOCK_COL)

    def _draw_now_playing(self, draw, state):
        has_track = bool(state.title) or bool(state.artist) or state.duration > 0
        if not has_track:
            return

        top_y = CLOCK_BAR_H + 16
        title = state.title or "—"
        title_lines = self._wrap_lines(draw, title, self.font_title, W - 80)
        y = top_y
        for line in title_lines[:2]:
            self._draw_text_centered(draw, line, self.font_title, TITLE_COL, y)
            y += 46

        artist = state.artist or ""
        if artist:
            y += 8
            self._draw_text_centered(draw, artist, self.font_artist, ARTIST_COL, y)
            y += 42

        notif_top = H - NOTIF_BAR_H if self._notif else H
        bar_y = min(y + 24, notif_top - 60)
        bar_x = 40
        bar_w = W - 80
        bar_h = 3
        draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=BAR_BG)
        if state.duration > 0:
            pct = min(state.position / max(state.duration, 1), 1.0)
            draw.rectangle([bar_x, bar_y, bar_x + int(bar_w * pct), bar_y + bar_h],
                           fill=BAR_FG)

        symbol = "▶" if state.playing else "⏸"
        def fmt(s): return f"{int(s) // 60}:{int(s) % 60:02d}"
        if state.duration > 0:
            time_str = f"{symbol}  {fmt(state.position)}  /  {fmt(state.duration)}"
        else:
            time_str = symbol
        self._draw_text_centered(draw, time_str, self.font_meta, META_COL,
                                 y=bar_y + 10)

    def _draw_notification(self, draw, n):
        top = H - NOTIF_BAR_H
        draw.rectangle([0, top, W, H], fill=NOTIF_BG)
        draw.line([(0, top), (W, top)], fill=(50, 50, 60), width=1)

        tag = n["category"]
        if n["app"]:
            tag = f"{tag} · {n['app']}"
        tag_y = top + 10
        draw.text((NOTIF_MARGIN_X, tag_y), tag, font=self.font_notif_tag, fill=NOTIF_TAG)

        title_y = tag_y + 22
        title = self._truncate(draw, n["title"], self.font_notif_title, W - 2 * NOTIF_MARGIN_X)
        draw.text((NOTIF_MARGIN_X, title_y), title, font=self.font_notif_title, fill=NOTIF_TITLE)

        msg_y = title_y + 28
        msg = self._truncate(draw, n["message"], self.font_notif_msg, W - 2 * NOTIF_MARGIN_X)
        draw.text((NOTIF_MARGIN_X, msg_y), msg, font=self.font_notif_msg, fill=NOTIF_MSG)

    # ── helpers ───────────────────────────────────────────────────────────

    def _draw_text_centered(self, draw, text, font, color, y):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=color)

    def _wrap_lines(self, draw, text, font, max_width):
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    def _truncate(self, draw, text, font, max_width):
        if not text:
            return ""
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        ellipsis = "…"
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi) // 2
            candidate = text[:mid] + ellipsis
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                lo = mid + 1
            else:
                hi = mid
        return text[: max(0, lo - 1)] + ellipsis
