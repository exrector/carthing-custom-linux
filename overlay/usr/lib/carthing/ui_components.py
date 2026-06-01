"""Reusable UI components over PIL — the substrate-insurance vocabulary.

Screens compose these instead of calling raw PIL, so the look stays consistent
(via ui_theme) and a future substrate swap re-implements ~these, not every
screen. Also defines InteractiveRegion + RegionSet: the touch hit-testing model
that turns a tap at (x,y) into an intent.
"""
import ui_theme as T


# ─── interactive regions (touch hit-testing) ─────────────────────────────────
class InteractiveRegion:
    """A tappable rectangle that emits an intent when hit."""

    __slots__ = ("rect", "intent", "payload")

    def __init__(self, rect, intent, payload=None):
        self.rect = rect              # (x0, y0, x1, y1)
        self.intent = intent          # str command, dispatched by the app
        self.payload = payload        # optional data (e.g. device id)

    def contains(self, x, y):
        x0, y0, x1, y1 = self.rect
        return x0 <= x <= x1 and y0 <= y <= y1


class RegionSet:
    """Collected per-frame; the compositor hit-tests taps against it.

    Later regions win (drawn on top), so append in z-order.
    """

    def __init__(self):
        self._regions = []

    def add(self, rect, intent, payload=None):
        self._regions.append(InteractiveRegion(rect, intent, payload))

    def hit(self, x, y):
        for r in reversed(self._regions):
            if r.contains(x, y):
                return r
        return None

    def clear(self):
        self._regions.clear()


# ─── text helpers ─────────────────────────────────────────────────────────────
def text_w(draw, text, fnt):
    b = draw.textbbox((0, 0), text, font=fnt)
    return b[2] - b[0]


def draw_text(draw, xy, text, fnt, color):
    draw.text(xy, text, font=fnt, fill=color)


def text_centered(draw, text, fnt, color, y, cx=T.W // 2):
    draw.text((cx - text_w(draw, text, fnt) // 2, y), text, font=fnt, fill=color)


def wrap_lines(draw, text, fnt, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if text_w(draw, test, fnt) <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def truncate(draw, text, fnt, max_w):
    if text_w(draw, text, fnt) <= max_w:
        return text
    while text and text_w(draw, text + "…", fnt) > max_w:
        text = text[:-1]
    return text + "…"


# ─── progress bar ─────────────────────────────────────────────────────────────
def progress_bar(draw, x, y, w, pct, h=3, bg=T.HAIRLINE, fg=T.FG):
    draw.rectangle([x, y, x + w, y + h], fill=bg)
    if pct > 0:
        draw.rectangle([x, y, x + int(w * min(pct, 1.0)), y + h], fill=fg)


# ─── list row (used by accordion menus & device lists) ────────────────────────
def list_row(draw, y, label, selected=False, expandable=False, expanded=False,
             indent=0):
    """Draw one row; return its rect for InteractiveRegion registration."""
    x0, x1 = 24, T.LIST_X1
    rect = (x0, y - 6, x1, y + T.ROW_H - 14)
    if selected:
        draw.rectangle(rect, fill=T.SURFACE_SEL)
    tx = 52 + indent
    draw.text((tx, y), label, font=T.font(T.SZ_BODY), fill=T.FG if selected else T.MUTED)
    if expandable:
        T.icon_chevron(draw, T.LIST_X1 - 12, y + T.SZ_BODY // 2, 9,
                       color=(T.FG if selected else T.FAINT), expanded=expanded)
    return rect
