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
ACCENT_COL = (0, 170, 255)

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
        self.font_notif_app = _find_font(28, bold=True)
        self.font_notif_title = _find_font(42, bold=True)
        self.font_notif_body = _find_font(32)
        self.font_transfer_title = _find_font(44, bold=True)
        self.font_transfer_body = _find_font(30)
        self.font_menu_title = _find_font(40, bold=True)
        self.font_menu_item = _find_font(30)
        self.font_menu_detail = _find_font(23)
        log.info("UI fonts loaded")

    def render_idle(self, status_lines=None):
        img = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        self._draw_text_centered(draw, "Car Thing", self.font_menu_title, TITLE_COL, 54)
        self._draw_text_centered(draw, "Ready", self.font_transfer_title, ARTIST_COL, 122)

        y = 214
        for line in (status_lines or [])[:4]:
            text = self._fit_text(draw, line, self.font_menu_detail, W - 120)
            self._draw_text_centered(draw, text, self.font_menu_detail, META_COL, y)
            y += 30

        self._draw_text_centered(draw, "Hold Back for system menu", self.font_meta, META_COL, H - 78)
        self._blit(img)

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
        self._blit(img)

    def render_transfer_mode(self, speakers, scanning=False):
        img = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        draw.rectangle([32, 24, W - 32, H - 24], outline=BAR_BG, width=2)
        draw.rectangle([48, 48, W - 48, 88], fill=ACCENT_COL)
        self._draw_text_centered(draw, "Audio Output", self.font_notif_app, BG, 54)

        y = 126
        for line in self._wrap_lines(draw, "Transfer mode is on", self.font_transfer_title, W - 120, max_lines=2):
            self._draw_text_centered(draw, line, self.font_transfer_title, TITLE_COL, y)
            y += 52

        y += 14
        body = "Scanning trusted speakers..." if scanning else "Choose a trusted speaker"
        if not speakers:
            body = "No trusted speakers yet"
        for line in self._wrap_lines(draw, body, self.font_transfer_body, W - 120, max_lines=2):
            self._draw_text_centered(draw, line, self.font_transfer_body, ARTIST_COL, y)
            y += 38

        y += 24
        if speakers:
            for index, speaker in enumerate(speakers[:4], start=1):
                name = speaker.get("name") or speaker.get("address") or "Speaker"
                connected = bool(speaker.get("connected"))
                online = bool(speaker.get("online")) or connected
                color = TITLE_COL if online else META_COL
                prefix = ">" if connected else ("*" if online else "-")
                suffix = " connected" if connected else (" online" if online else " offline")
                line = f"{prefix} {name}{suffix}"
                for wrapped in self._wrap_lines(draw, line, self.font_transfer_body, W - 140, max_lines=1):
                    self._draw_text_centered(draw, wrapped, self.font_transfer_body, color, y)
                    y += 40
        else:
            footer = "Open Speakers to add one"
            self._draw_text_centered(draw, footer, self.font_meta, META_COL, H - 86)

        self._blit(img)

    def render_mode_menu(self, menu):
        img = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        draw.rectangle([28, 22, W - 28, H - 22], outline=BAR_BG, width=2)
        self._draw_text_centered(draw, "System Menu", self.font_menu_title, TITLE_COL, 44)

        status = "   ".join((menu.get("status") or [])[:3])
        if status:
            status = self._fit_text(draw, status, self.font_menu_detail, W - 96)
            self._draw_text_centered(draw, status, self.font_menu_detail, META_COL, 96)

        items = menu.get("items") or []
        selected = int(menu.get("index") or 0)
        start = max(0, min(selected - 2, max(0, len(items) - 5)))
        visible = items[start:start + 5]

        y = 134
        for offset, item in enumerate(visible):
            item_index = start + offset
            active = item_index == selected
            row_top = y - 7
            row_bottom = y + 56
            if active:
                draw.rectangle([54, row_top, W - 54, row_bottom], fill=(18, 42, 54))
                draw.rectangle([54, row_top, 62, row_bottom], fill=ACCENT_COL)
            label = self._fit_text(draw, item.get("label") or "", self.font_menu_item, W - 150)
            detail = self._fit_text(draw, item.get("detail") or "", self.font_menu_detail, W - 150)
            color = TITLE_COL if active else ARTIST_COL
            self._draw_text_left(draw, label, self.font_menu_item, color, 84, y)
            self._draw_text_left(draw, detail, self.font_menu_detail, META_COL, 84, y + 34)
            y += 66

        message = menu.get("message") or ""
        if message:
            color = ACCENT_COL if menu.get("message_ok", True) else (255, 90, 90)
            text = self._fit_text(draw, message, self.font_menu_detail, W - 96)
            self._draw_text_centered(draw, text, self.font_menu_detail, color, H - 70)
        else:
            self._draw_text_centered(draw, "Rotate to choose. Press knob to apply.", self.font_menu_detail, META_COL, H - 70)

        self._blit(img)

    def render_notification(self, notification, media_state=None):
        img = Image.new('RGB', (W, H), BG)
        draw = ImageDraw.Draw(img)

        draw.rectangle([32, 24, W - 32, H - 24], outline=BAR_BG, width=2)
        draw.rectangle([48, 48, W - 48, 86], fill=ACCENT_COL)

        app_name = notification.app_name or notification.category_name or "Notification"
        self._draw_text_centered(draw, app_name, self.font_notif_app, BG, 52)

        y = 118
        headline = notification.headline or "New notification"
        for line in self._wrap_lines(draw, headline, self.font_notif_title, W - 120, max_lines=3):
            self._draw_text_centered(draw, line, self.font_notif_title, TITLE_COL, y)
            y += 50

        body = notification.body
        if body:
            y += 18
            for line in self._wrap_lines(draw, body, self.font_notif_body, W - 120, max_lines=5):
                self._draw_text_centered(draw, line, self.font_notif_body, ARTIST_COL, y)
                y += 38

        footer_parts = [notification.category_name]
        if notification.date_display:
            footer_parts.append(notification.date_display)
        if notification.action_hint:
            footer_parts.append(notification.action_hint)
        if media_state and (media_state.title or media_state.artist):
            track = " - ".join(part for part in (media_state.title, media_state.artist) if part)
            if track:
                footer_parts.append(track)
        footer = " | ".join(part for part in footer_parts if part)
        footer_lines = self._wrap_lines(draw, footer, self.font_meta, W - 120, max_lines=2)
        footer_y = H - 92 - max(0, len(footer_lines) - 1) * 28
        for line in footer_lines:
            self._draw_text_centered(draw, line, self.font_meta, META_COL, footer_y)
            footer_y += 28

        self._blit(img)

    def _blit(self, img):
        img = img.rotate(-90, expand=True)  # 800×480 → 480×800
        raw = img.tobytes('raw', 'BGRX')
        self.display.blit(raw)

    def _draw_text_centered(self, draw, text, font, color, y):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=color)

    def _draw_text_left(self, draw, text, font, color, x, y):
        draw.text((x, y), text, font=font, fill=color)

    def _fit_text(self, draw, text, font, max_width):
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return text
        suffix = "..."
        while text:
            candidate = text.rstrip() + suffix
            if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                return candidate
            text = text[:-1]
        return suffix

    def _wrap_lines(self, draw, text, font, max_width, max_lines=None):
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
        if max_lines is not None and len(lines) > max_lines:
            lines = lines[:max_lines]
            while lines:
                candidate = lines[-1].rstrip(". ") + "..."
                if draw.textbbox((0, 0), candidate, font=font)[2] <= max_width:
                    lines[-1] = candidate
                    break
                trimmed = lines[-1].rsplit(" ", 1)[0].strip()
                if not trimmed:
                    lines[-1] = candidate
                    break
                lines[-1] = trimmed
        return lines
