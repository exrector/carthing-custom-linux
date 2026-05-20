"""Design tokens for the Car Thing GUI — the ONE place visual style lives.

Palette, spacing, type scale, and vector icon drawing. Screens/components never
hardcode colours or sizes; they read from here. Changing the look = editing this
file, never the logic. Vectors (not font glyphs) are used for symbols so the
look is font-independent and emoji-free.
"""
from PIL import ImageFont
import os

# ─── canvas (landscape; device rotates -90 to the 480x800 panel) ──────────────
W, H = 800, 480

# ─── palette ──────────────────────────────────────────────────────────────────
BG       = (0, 0, 0)
SURFACE  = (22, 22, 22)        # raised row / card
SURFACE_SEL = (22, 36, 30)     # selected row
FG       = (255, 255, 255)
MUTED    = (165, 165, 165)
FAINT    = (95, 95, 95)
HAIRLINE = (40, 40, 40)
ACCENT   = (0, 200, 120)
WARN     = (220, 90, 60)

# ─── spacing / layout tokens ──────────────────────────────────────────────────
MARGIN     = 40          # outer side margin
GUTTER     = 16          # gap between elements
ROW_H      = 64          # list row height
RADIUS     = 8

# ── Clean 3-part screen partition (tiles the panel with no gaps/corners) ──────
#   MAIN (top-left)           : [0, OCCLUSION_LEFT] x [0, OCCLUSION_BOTTOM]
#   ENCODER column (occluded) : [OCCLUSION_LEFT, W] x [0, OCCLUSION_BOTTOM]
#   BOTTOM BAR (full width)   : [0, W] x [OCCLUSION_BOTTOM, H]
# The physical rotary dial / top-right button occlude the encoder column.
# Provisional from on-Mac calibration; refine on-device.
SAFE_RIGHT       = 60
OCCLUSION_LEFT   = W - SAFE_RIGHT     # 740 — vertical divider in the top band
OCCLUSION_BOTTOM = 345                # horizontal divider: top band / bottom bar
OCCLUSION = (OCCLUSION_LEFT, 0, W, OCCLUSION_BOTTOM)

# MAIN region geometry — content centers here
CONTENT_X0 = MARGIN                   # 40
CONTENT_X1 = OCCLUSION_LEFT           # 740 — right boundary; nothing draws past
CONTENT_CX = OCCLUSION_LEFT // 2      # 370 — main horizontal center (left edge..zone)
CONTENT_W  = 2 * (CONTENT_CX - CONTENT_X0)   # 660
MAIN_CY    = OCCLUSION_BOTTOM // 2    # 172 — main vertical center
CONTENT_TOP = 24                      # top-aligned content (lists) start

# BOTTOM BAR fills the bottom band exactly (top aligned with occlusion bottom)
STATUSBAR_TOP = OCCLUSION_BOTTOM      # 345
STATUSBAR_H   = H - OCCLUSION_BOTTOM  # 135

# ─── type scale ───────────────────────────────────────────────────────────────
SZ_TITLE = 48
SZ_BODY  = 32
SZ_META  = 28
SZ_SMALL = 22

_FONT_CANDIDATES = [
    os.environ.get("CARTHING_FONT_PATH", ""),
    "/usr/share/fonts/truetype/DejaVuSans.ttf",        # device (Buildroot)
    "/System/Library/Fonts/Supplemental/Arial.ttf",    # dev Mac
    "/System/Library/Fonts/Helvetica.ttc",
]

_font_cache = {}


def font(size):
    if size in _font_cache:
        return _font_cache[size]
    f = None
    for cand in _FONT_CANDIDATES:
        if not cand:
            continue
        try:
            f = ImageFont.truetype(cand, size)
            break
        except Exception:
            continue
    if f is None:
        f = ImageFont.load_default()
    _font_cache[size] = f
    return f


# ─── vector icons (no font glyphs / no emoji) ─────────────────────────────────
def icon_play(draw, cx, cy, r, color=FG):
    draw.polygon([(cx - r * 0.6, cy - r), (cx - r * 0.6, cy + r), (cx + r, cy)], fill=color)


def icon_pause(draw, cx, cy, r, color=FG):
    w = r * 0.5
    draw.rectangle([cx - r * 0.7, cy - r, cx - r * 0.7 + w, cy + r], fill=color)
    draw.rectangle([cx + r * 0.2, cy - r, cx + r * 0.2 + w, cy + r], fill=color)


def icon_dot(draw, cx, cy, r, color=FG):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=color)


def icon_prev(draw, cx, cy, r, color=FG):
    draw.rectangle([cx - r, cy - r, cx - r + r * 0.35, cy + r], fill=color)
    draw.polygon([(cx + r, cy - r), (cx + r, cy + r), (cx - r * 0.35, cy)], fill=color)


def icon_next(draw, cx, cy, r, color=FG):
    draw.rectangle([cx + r - r * 0.35, cy - r, cx + r, cy + r], fill=color)
    draw.polygon([(cx - r, cy - r), (cx - r, cy + r), (cx + r * 0.35, cy)], fill=color)


def icon_ring(draw, cx, cy, r, color=FG, width=2):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=width)


def encoder_arc(draw, color=FAINT, width=2):
    """Outline of the physical rotary dial: a large circle centered off-screen to
    the right (its 'square' completed rightward from the occlusion zone), so only
    its left arc bulges onto the screen edge. Diameter ~= occlusion zone height."""
    R = OCCLUSION_BOTTOM // 2
    cy = OCCLUSION_BOTTOM // 2
    cx = CONTENT_X1 + R                       # leftmost point sits at CONTENT_X1
    bbox = [cx - R, cy - R, cx + R, cy + R]
    draw.arc(bbox, start=131, end=229, fill=color, width=width)   # visible left arc


def icon_chevron(draw, cx, cy, r, color=MUTED, expanded=False, width=3):
    # accordion indicator: ▸ collapsed / ▾ expanded
    if expanded:
        draw.line([(cx - r, cy - r * 0.4), (cx, cy + r * 0.5)], fill=color, width=width)
        draw.line([(cx, cy + r * 0.5), (cx + r, cy - r * 0.4)], fill=color, width=width)
    else:
        draw.line([(cx - r * 0.4, cy - r), (cx + r * 0.5, cy)], fill=color, width=width)
        draw.line([(cx + r * 0.5, cy), (cx - r * 0.4, cy + r)], fill=color, width=width)
