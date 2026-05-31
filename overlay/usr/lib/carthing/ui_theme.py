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
STATUS_OK   = (40, 200, 90)    # connected — зелёный
STATUS_WARN = (235, 195, 40)   # online — жёлтый
STATUS_OFF  = (220, 70, 60)    # offline — красный

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
OCCLUSION_BOTTOM = 318                # horizontal divider: top band / bottom bar (raised → taller bar)
OCCLUSION = (OCCLUSION_LEFT, 0, W, OCCLUSION_BOTTOM)

# MAIN region geometry — content centers here
CONTENT_X0 = MARGIN                   # 40
CONTENT_X1 = OCCLUSION_LEFT           # 740 — right boundary; nothing draws past
CONTENT_CX = OCCLUSION_LEFT // 2      # 370 — main horizontal center (left edge..zone)
CONTENT_W  = 2 * (CONTENT_CX - CONTENT_X0)   # 660
MAIN_CY    = OCCLUSION_BOTTOM // 2    # 172 — main vertical center
CONTENT_TOP = 24                      # top-aligned content (lists) start
LIST_X1     = OCCLUSION_LEFT - 72     # 668 — right edge for list rows; keeps them clear of the dial arc

# BOTTOM BAR fills the bottom band exactly (top aligned with occlusion bottom)
STATUSBAR_TOP = OCCLUSION_BOTTOM      # 318
STATUSBAR_H   = H - OCCLUSION_BOTTOM  # 162

# Encoder dial arc — kept independent of the occlusion divider so it can be
# nudged without resizing the bottom bar. Diameter preserved from the original
# calibration; centre lifted slightly to better trace the physical dial.
ENCODER_ARC_R  = 162                  # radius — diameter trimmed to match the physical dial (was 172)
ENCODER_ARC_CY = 147                  # vertical centre (172 -> 150 -> 144 -> 147)

# ─── type scale ───────────────────────────────────────────────────────────────
SZ_TITLE = 48
SZ_BODY  = 32
SZ_META  = 28
SZ_SMALL = 22
SZ_BAR   = 26   # bottom-bar text (clock, source label) — a touch larger for the taller bar

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


def _arrowhead(draw, x, y, dx, dy, size, color):
    """Маленький треугольник-наконечник в точке (x,y), указывающий в (dx,dy)."""
    import math
    ang = math.atan2(dy, dx)
    a1 = ang + math.radians(140)
    a2 = ang - math.radians(140)
    p1 = (x + size * math.cos(a1), y + size * math.sin(a1))
    p2 = (x + size * math.cos(a2), y + size * math.sin(a2))
    draw.polygon([(x, y), p1, p2], fill=color)


def icon_skip_back(draw, cx, cy, r, color=FG, width=3):
    """Перемотка назад на интервал: круговая стрелка против часовой (петля с разрывом
    сверху, наконечник вверху-слева). Интервал задаёт само приложение (не рисуем число)."""
    import math
    bbox = [cx - r, cy - r, cx + r, cy + r]
    draw.arc(bbox, start=300, end=210, fill=color, width=width)   # разрыв сверху
    # наконечник в точке конца дуги (angle=300°), касательная против часовой
    a = math.radians(300)
    ex, ey = cx + r * math.cos(a), cy + r * math.sin(a)
    _arrowhead(draw, ex, ey, math.cos(a - math.radians(90)), math.sin(a - math.radians(90)),
               r * 0.55, color)


def icon_skip_fwd(draw, cx, cy, r, color=FG, width=3):
    """Перемотка вперёд: круговая стрелка по часовой (петля с разрывом сверху,
    наконечник вверху-справа)."""
    import math
    bbox = [cx - r, cy - r, cx + r, cy + r]
    draw.arc(bbox, start=330, end=240, fill=color, width=width)
    a = math.radians(240)
    ex, ey = cx + r * math.cos(a), cy + r * math.sin(a)
    _arrowhead(draw, ex, ey, math.cos(a + math.radians(90)), math.sin(a + math.radians(90)),
               r * 0.55, color)


ENCODER_ARC_A0 = 131                  # visible arc span: bottom-left …
ENCODER_ARC_A1 = 229                  # … to top-left (traces the physical dial edge)


ENCODER_ZONE_GAP = 6                  # минимальный зазор от дуги (только чтоб не слиплось)


def encoder_zone_glow(draw):
    """Индикатор ANCS: РЕЗКИЙ белый блик ВСЕЙ зоны под энкодером (сегмент диска справа
    от дуги). Без полутонов — чистый белый; «выкл» = не рисуем (виден фон экрана).
    Резкое моргание белый↔BG делает вызывающая сторона (square-wave по времени)."""
    cy = ENCODER_ARC_CY
    cx = CONTENT_X1 + ENCODER_ARC_R                  # центр тот же, что у дуги (off-screen)
    R = ENCODER_ARC_R - ENCODER_ZONE_GAP             # минимальный зазор от дуги
    bbox = [cx - R, cy - R, cx + R, cy + R]
    draw.pieslice(bbox, start=ENCODER_ARC_A0, end=ENCODER_ARC_A1, fill=(255, 255, 255))


def encoder_arc(draw, level=None, color=FAINT, width=2):
    """Outline of the physical rotary dial: a large circle centered off-screen to
    the right, so only its left arc bulges onto the screen edge.

    level=None → plain faint outline. level in 0..1 → volume indicator: the span
    is split into segments and filled from the bottom up; filled segments are
    bright and bulge outward (larger radius), empty ones stay thin and faint."""
    R = ENCODER_ARC_R
    cy = ENCODER_ARC_CY
    cx = CONTENT_X1 + R                       # leftmost point sits at CONTENT_X1
    a0, a1 = ENCODER_ARC_A0, ENCODER_ARC_A1

    if level is None:
        bbox = [cx - R, cy - R, cx + R, cy + R]
        draw.arc(bbox, start=a0, end=a1, fill=color, width=width)   # visible left arc
        return

    level = max(0.0, min(1.0, level))
    N = 14
    gap_deg = 2.2                              # spacing between segments
    span = a1 - a0
    seg = (span - gap_deg * (N - 1)) / N
    filled = round(level * N)
    for i in range(N):
        s = a0 + i * (seg + gap_deg)
        on = i < filled
        rr = R + 7 if on else R                # filled segments bulge outward
        col = ACCENT if on else HAIRLINE
        w = 8 if on else 3
        bbox = [cx - rr, cy - rr, cx + rr, cy + rr]
        draw.arc(bbox, start=s, end=s + seg, fill=col, width=w)


def progress_segments(draw, x0, y, w, level, n=32, gap=4):
    """Horizontal segmented progress in the dial's visual language: filled
    segments are bright (ACCENT) and thicker (bulge), empty ones thin + faint.
    Centred on `y` so it reads as the divider line filling up left→right."""
    level = max(0.0, min(1.0, level))
    seg_w = (w - gap * (n - 1)) / n
    filled = round(level * n)
    for i in range(n):
        x = x0 + i * (seg_w + gap)
        on = i < filled
        col = ACCENT if on else HAIRLINE
        h = 3 if on else 1                     # filled segments bulge thicker
        draw.rectangle([x, y - h, x + seg_w, y + h], fill=col)


def icon_chevron(draw, cx, cy, r, color=MUTED, expanded=False, width=3):
    # accordion indicator: ▸ collapsed / ▾ expanded
    if expanded:
        draw.line([(cx - r, cy - r * 0.4), (cx, cy + r * 0.5)], fill=color, width=width)
        draw.line([(cx, cy + r * 0.5), (cx + r, cy - r * 0.4)], fill=color, width=width)
    else:
        draw.line([(cx - r * 0.4, cy - r), (cx + r * 0.5, cy)], fill=color, width=width)
        draw.line([(cx + r * 0.5, cy), (cx - r * 0.4, cy + r)], fill=color, width=width)
