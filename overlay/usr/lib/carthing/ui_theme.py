"""Design tokens for the Car Thing GUI — the ONE place visual style lives.

Palette, spacing, type scale, and vector icon drawing. Screens/components never
hardcode colours or sizes; they read from here. Changing the look = editing this
file, never the logic. Vectors (not font glyphs) are used for symbols so the
look is font-independent and emoji-free.
"""
from PIL import ImageFont, Image, ImageDraw
import math
import os

# ─── canvas (landscape; device rotates -90 to the 480x800 panel) ──────────────
W, H = 800, 480

# ─── palette ──────────────────────────────────────────────────────────────────
BG       = (0, 0, 0)
SURFACE  = (22, 22, 22)        # raised row / card
SURFACE_SEL = (34, 34, 34)     # selected row, neutral highlight
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
# [CLAUDE 2026-06-02] Дуга стоит левым краем на CONTENT_X1=740, НО зелёные сегменты громкости
# выпирают наружу (R+7 => до x≈733). Поэтому контент ВЕРХНЕЙ полосы (списки/колонки) должен
# кончаться с запасом, чтобы не лезть под штрихи. Нижний бар (y>=OCCLUSION_BOTTOM) — под дугой
# пусто, он на всю ширину W.
ARC_SAFE_X  = CONTENT_X1 - 24         # 716 — правая граница контента в верхней полосе
LIST_X1     = ARC_SAFE_X              # full-width rows в fullscreen-вью держат зазор от дуги

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

# ─── themes ───────────────────────────────────────────────────────────────────
# Тема выбирается ОДИН РАЗ при импорте (= старте runtime): icon_* захватывают
# цвета в default-аргументах, живая подмена палитры невозможна. Смена темы в
# Настройках персистит settings.ui_theme и перезапускает runtime (супервизор).
#
# "terminal" — ретро-терминал в палитре exrector.com (--p/--p-dim/--p-faint/--bg):
# иерархия яркости как на сайте — основной текст dim, полный фосфор только у
# ключевых элементов. Идея владельца 2026-06-11 (мейнфреймы 60–70-х).

def _settings_theme():
    name = os.environ.get("CARTHING_UI_THEME", "")
    if name:
        return name
    import json
    state_file = os.path.join(
        os.environ.get("CARTHING_STATE_ROOT", "/run/carthing-state"),
        "carthing", "state.json")
    try:
        with open(state_file) as fh:
            return json.load(fh).get("settings", {}).get("ui_theme", "dark")
    except Exception:
        return "dark"


THEME = _settings_theme()

_MONO_CANDIDATES = [
    "/usr/share/fonts/truetype/IBMPlexMono-Regular.ttf",   # device (как на сайте)
    os.path.join(os.path.dirname(__file__), "..", "..", "share",
                 "fonts", "truetype", "IBMPlexMono-Regular.ttf"),  # dev Mac (overlay)
    "/System/Library/Fonts/Menlo.ttc",                      # dev Mac fallback
]

if THEME == "terminal":
    BG          = (3, 9, 6)        # --bg: не чёрный, зелёный подтон
    SURFACE     = (7, 22, 13)
    SURFACE_SEL = (26, 138, 71)    # inverse-video: выделение заливкой фосфора
    FG          = (51, 255, 136)   # --p
    MUTED       = (26, 138, 71)    # --p-dim — ОСНОВНАЯ масса текста
    FAINT       = (13, 61, 32)     # --p-faint
    HAIRLINE    = (13, 61, 32)
    ACCENT      = (51, 255, 136)
    WARN        = (255, 102, 68)   # .err сайта
    STATUS_OK   = (51, 255, 136)
    STATUS_WARN = (255, 170, 0)    # янтарь сайта
    STATUS_OFF  = (255, 68, 68)
    _FONT_CANDIDATES[1:1] = _MONO_CANDIDATES

# CRT-постэффекты (сканлайны + виньетка) — только terminal, выключаются env.
_POSTFX = THEME == "terminal" and os.environ.get("CARTHING_CRT_FX", "1") != "0"
_fx_mask = None


def _build_fx_mask(size):
    """Маска CRT строится один раз: сканлайны (каждая 4-я строка, как opacity
    0.22 на сайте) * виньетка по углам. Применение — одна C-операция multiply."""
    from PIL import ImageFilter
    w, h = size
    mask = Image.new("L", size, 255)
    md = ImageDraw.Draw(mask)
    for y in range(0, h, 4):
        md.line([0, y, w, y], fill=200)
    vig = Image.new("L", size, 0)
    vd = ImageDraw.Draw(vig)
    vd.ellipse([-w * 0.35, -h * 0.5, w * 1.35, h * 1.5], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(60)).point(lambda v: 140 + v * 115 // 255)
    from PIL import ImageChops
    return ImageChops.multiply(mask.convert("RGB"), vig.convert("RGB"))


def postprocess(img):
    """Финальный кадр через CRT-маску. Для темы dark — no-op."""
    global _fx_mask
    if not _POSTFX:
        return img
    if _fx_mask is None or _fx_mask.size != img.size:
        _fx_mask = _build_fx_mask(img.size)
    from PIL import ImageChops
    return ImageChops.multiply(img, _fx_mask)


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


def icon_route(draw, cx, cy, r, color=FG, width=3):
    """[CLAUDE 2026-06-11] Маршрут/коннект: два узла, соединённые линией (patchbay).
    Заменяет ▶ на кнопке активации маршрута (решение владельца: play там неуместен)."""
    nr = max(3, int(r * 0.30))                      # радиус узлов
    x0, y0 = cx - r * 0.62, cy + r * 0.55           # вход (низ-лево)
    x1, y1 = cx + r * 0.62, cy - r * 0.55           # выход (верх-право)
    draw.line([(x0, y0), (x1, y1)], fill=color, width=width)
    draw.ellipse([x0 - nr, y0 - nr, x0 + nr, y0 + nr], fill=color)
    draw.ellipse([x1 - nr, y1 - nr, x1 + nr, y1 + nr], fill=color)


def icon_plus(draw, cx, cy, r, color=FG, width=3):
    """[CLAUDE 2026-06-03] Плюс (добавить/сопряжение)."""
    draw.line([(cx - r, cy), (cx + r, cy)], fill=color, width=width)
    draw.line([(cx, cy - r), (cx, cy + r)], fill=color, width=width)


def icon_gear(draw, cx, cy, r, color=FG, width=2):
    """[CLAUDE 2026-06-03] Простая шестерёнка (настройки): спицы + два кольца."""
    n = 8
    for i in range(n):
        a = (math.pi * 2) * i / n
        draw.line([(cx + r * 0.62 * math.cos(a), cy + r * 0.62 * math.sin(a)),
                   (cx + r * math.cos(a), cy + r * math.sin(a))], fill=color, width=width)
    draw.ellipse([cx - r * 0.62, cy - r * 0.62, cx + r * 0.62, cy + r * 0.62], outline=color, width=width)
    draw.ellipse([cx - r * 0.24, cy - r * 0.24, cx + r * 0.24, cy + r * 0.24], outline=color, width=width)


def dashed_line(draw, x0, y0, x1, y1, color=HAIRLINE, dash=8, gap=6, width=2):
    """[CLAUDE 2026-06-02] Штриховая линия — визуальный язык дуги/сегментов (вместо сплошных
    «секционных» делителей)."""
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy)
    if length <= 0:
        return
    ux, uy = dx / length, dy / length
    pos = 0.0
    while pos < length:
        e = min(pos + dash, length)
        draw.line([(x0 + ux * pos, y0 + uy * pos), (x0 + ux * e, y0 + uy * e)],
                  fill=color, width=width)
        pos += dash + gap


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


def icon_heart(draw, cx, cy, r, color=FG, filled=False, width=3):
    """Сердце (параметрическая кривая). filled=False -> контур («нажми, чтобы в избранное»);
    состояние «уже лайкнуто» AMS не сообщает, поэтому по умолчанию контур, не заливка."""
    import math
    pts = []
    for i in range(0, 360, 10):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((cx + x * r / 16.0, cy - y * r / 16.0))
    if filled:
        draw.polygon(pts, fill=color)
    else:
        draw.line(pts + [pts[0]], fill=color, width=width)


def icon_dislike(draw, cx, cy, r, color=FG, width=3):
    """Дизлайк / убрать из избранного: сердце-контур, перечёркнутое диагональю."""
    icon_heart(draw, cx, cy, r, color=color, filled=False, width=width)
    draw.line([(cx - r, cy - r), (cx + r, cy + r)], fill=color, width=width)


def icon_shuffle(draw, cx, cy, r, color=FG, width=3):
    """Перемешать: две пересекающиеся стрелки вправо."""
    draw.line([(cx - r, cy + r * 0.6), (cx + r * 0.5, cy - r * 0.6)], fill=color, width=width)
    _arrowhead(draw, cx + r * 0.5, cy - r * 0.6, 1.0, -0.5, r * 0.5, color)
    draw.line([(cx - r, cy - r * 0.6), (cx + r * 0.5, cy + r * 0.6)], fill=color, width=width)
    _arrowhead(draw, cx + r * 0.5, cy + r * 0.6, 1.0, 0.5, r * 0.5, color)


def icon_repeat(draw, cx, cy, r, color=FG, width=3):
    """Повтор: замкнутая петля (овал) со стрелкой — отличается от skip (у того разрыв)."""
    draw.arc([cx - r, cy - r * 0.72, cx + r, cy + r * 0.72], start=0, end=360,
             fill=color, width=width)
    _arrowhead(draw, cx + r, cy, 0.0, 1.0, r * 0.5, color)


def icon_bookmark(draw, cx, cy, r, color=FG, width=3, filled=False):
    """Закладка: прямоугольник с вырезом-«ласточкой» снизу."""
    pts = [(cx - r * 0.6, cy - r), (cx + r * 0.6, cy - r),
           (cx + r * 0.6, cy + r), (cx, cy + r * 0.4), (cx - r * 0.6, cy + r)]
    if filled:
        draw.polygon(pts, fill=color)
    else:
        draw.line(pts + [pts[0]], fill=color, width=width)


def icon_chevron(draw, cx, cy, r, color=MUTED, expanded=False, width=3):
    # accordion indicator: ▸ collapsed / ▾ expanded
    if expanded:
        draw.line([(cx - r, cy - r * 0.4), (cx, cy + r * 0.5)], fill=color, width=width)
        draw.line([(cx, cy + r * 0.5), (cx + r, cy - r * 0.4)], fill=color, width=width)
    else:
        draw.line([(cx - r * 0.4, cy - r), (cx + r * 0.5, cy)], fill=color, width=width)
        draw.line([(cx + r * 0.5, cy), (cx - r * 0.4, cy + r)], fill=color, width=width)


# ─── ВЫСОКОКАЧЕСТВЕННЫЕ ГЛИФЫ (супер-сэмплинг 4× + LANCZOS = без «лесенки») ────
# Рисуем в квадрате [0..S] на прозрачном тайле в 4× размере, потом даунскейл с
# LANCZOS и вставляем с альфой. Так значки в баре получаются гладкими. Каждый
# glyph_*(d, S, color) рисует в боксе стороной S, центр (S/2, S/2).
_GLYPH_SS = 4
_GLYPH_RESAMPLE = getattr(Image, "LANCZOS", Image.BICUBIC)


def paste_glyph(base_img, glyph_fn, cx, cy, size, color, mirror=False):
    """Отрисовать glyph_fn в 4× тайл, сгладить и вставить в base_img по центру (cx,cy)."""
    size = int(size)
    if size < 2:
        return
    S = size * _GLYPH_SS
    tile = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(tile)
    glyph_fn(d, S, color)
    if mirror:
        from PIL import ImageOps
        tile = ImageOps.mirror(tile)
    tile = tile.resize((size, size), _GLYPH_RESAMPLE)
    base_img.paste(tile, (int(cx - size / 2), int(cy - size / 2)), tile)


def _arrow_tri(d, x, y, ang, size, color):
    """Залитый равнобедренный наконечник: вершина в (x,y), указывает в направлении ang."""
    a1 = ang + math.radians(148)
    a2 = ang - math.radians(148)
    d.polygon([(x, y),
               (x + size * math.cos(a1), y + size * math.sin(a1)),
               (x + size * math.cos(a2), y + size * math.sin(a2))], fill=color)


def glyph_play(d, S, color):
    c = S / 2; R = S * 0.34
    d.polygon([(c - R * 0.82, c - R), (c - R * 0.82, c + R), (c + R * 1.04, c)], fill=color)


def glyph_pause(d, S, color):
    c = S / 2; R = S * 0.34; w = R * 0.58; gap = R * 0.30; rad = w * 0.40
    d.rounded_rectangle([c - gap - w, c - R, c - gap, c + R], radius=rad, fill=color)
    d.rounded_rectangle([c + gap, c - R, c + gap + w, c + R], radius=rad, fill=color)


def glyph_prev(d, S, color):
    c = S / 2; R = S * 0.33; w = R * 0.40; rad = w * 0.40
    d.rounded_rectangle([c - R, c - R, c - R + w, c + R], radius=rad, fill=color)
    d.polygon([(c + R, c - R), (c + R, c + R), (c - R * 0.02, c)], fill=color)


def glyph_next(d, S, color):
    c = S / 2; R = S * 0.33; w = R * 0.40; rad = w * 0.40
    d.rounded_rectangle([c + R - w, c - R, c + R, c + R], radius=rad, fill=color)
    d.polygon([(c - R, c - R), (c - R, c + R), (c + R * 0.02, c)], fill=color)


def glyph_skip_fwd(d, S, color):
    """Перемотка вперёд: круговая стрелка по часовой, разрыв и наконечник сверху."""
    c = S / 2; R = S * 0.32; w = max(2, int(S * 0.085))
    # дуга по часовой с разрывом сверху (≈270°); рисуем от 300° на 250° вперёд
    start, span = 305, 250
    d.arc([c - R, c - R, c + R, c + R], start=start, end=start + span, fill=color, width=w)
    # наконечник на ведущем конце (start), касательная по часовой = ang - 90°
    a = math.radians(start)
    ex, ey = c + R * math.cos(a), c + R * math.sin(a)
    _arrow_tri(d, ex, ey, a - math.radians(90), R * 0.62, color)


def glyph_skip_back(d, S, color):
    """Перемотка назад = зеркало skip_fwd (идеально симметрично)."""
    glyph_skip_fwd(d, S, color)   # реальное зеркало делает paste_glyph(mirror=True)


def glyph_heart(d, S, color, filled=False):
    c = S / 2; R = S * 0.34; w = max(2, int(S * 0.10))
    pts = []
    for i in range(0, 360, 6):
        t = math.radians(i)
        x = 16 * math.sin(t) ** 3
        y = 13 * math.cos(t) - 5 * math.cos(2 * t) - 2 * math.cos(3 * t) - math.cos(4 * t)
        pts.append((c + x * R / 16.0, c - y * R / 16.0 - R * 0.08))
    if filled:
        d.polygon(pts, fill=color)
    else:
        d.line(pts + [pts[0]], fill=color, width=w, joint="curve")


def glyph_heart_filled(d, S, color):
    glyph_heart(d, S, color, filled=True)
