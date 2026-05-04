"""
Minimalist Now Playing UI for Car Thing (480×800 portrait DRM display).
Black background, white title, gray artist, thin progress bar.
"""
import os
import logging
from runtime_paths import ensure_runtime_paths
ensure_runtime_paths()

from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

# ─── palette ──────────────────────────────────────────────────────────────────
BG        = (0,   0,   0)
TITLE_COL = (255, 255, 255)
ARTIST_COL= (160, 160, 160)
META_COL  = (90,  90,  90)
BAR_BG    = (30,  30,  30)
BAR_FG    = (255, 255, 255)

W, H = 800, 480  # landscape; rotated 90° before blit → framebuffer 480×800

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
        self.font_title  = _find_font(48, bold=True)
        self.font_artist = _find_font(48)
        self.font_meta   = _find_font(28)
        log.info("UI fonts loaded")

    def render(self, state):
        img  = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        LH = 56  # line height for 48pt font

        # ── title (top, wraps) ────────────────────────────────────────────
        title = state.title or '—'
        title_lines = self._wrap_lines(draw, title, self.font_title, W - 80)
        y = 24
        for line in title_lines:
            self._draw_text_centered(draw, line, self.font_title, TITLE_COL, y)
            y += LH

        # ── artist ────────────────────────────────────────────────────────
        artist = state.artist or ''
        if artist:
            y += 8
            self._draw_text_centered(draw, artist, self.font_artist, ARTIST_COL, y)
            y += LH

        # ── progress bar ──────────────────────────────────────────────────
        BAR_X, BAR_Y = 40, y + 16
        BAR_W, BAR_H = W - 80, 3
        draw.rectangle([BAR_X, BAR_Y, BAR_X + BAR_W, BAR_Y + BAR_H], fill=BAR_BG)
        if state.duration > 0:
            pct = min(state.position / state.duration, 1.0)
            draw.rectangle([BAR_X, BAR_Y, BAR_X + int(BAR_W * pct), BAR_Y + BAR_H],
                           fill=BAR_FG)

        # ── play/pause + time ─────────────────────────────────────────────
        symbol = '▶' if state.playing else '⏸'
        def fmt(s): return f"{int(s)//60}:{int(s)%60:02d}"
        if state.duration > 0:
            time_str = f"{symbol}  {fmt(state.position)}  /  {fmt(state.duration)}"
        else:
            time_str = symbol
        self._draw_text_centered(draw, time_str, self.font_meta, META_COL,
                                 y=BAR_Y + 10)

        # ── blit to display: rotate 90° landscape→portrait framebuffer ────
        img = img.rotate(-90, expand=True)  # 800×480 → 480×800
        raw = img.tobytes('raw', 'BGRX')
        self.display.blit(raw)

    def _draw_text_centered(self, draw, text, font, color, y):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=color)

    def _wrap_lines(self, draw, text, font, max_width):
        words = text.split()
        lines, cur = [], ''
        for w in words:
            test = (cur + ' ' + w).strip()
            if draw.textbbox((0, 0), test, font=font)[2] <= max_width:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines
