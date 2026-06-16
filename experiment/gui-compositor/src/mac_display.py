"""MacDisplay — drop-in замена DRMDisplay для macOS через pygame.

macOS требует что SDL/AppKit event loop работал в MAIN THREAD.
Поэтому: asyncio (carthing_runtime) запускается в отдельном потоке,
а pygame event loop крутится в main thread через MacDisplay.run_event_loop().

Использование в ct_run_pairing.py / запускалке:
    from mac_display import MacDisplay, run_with_display
    asyncio.run(run_with_display(your_async_main))
"""
import asyncio
import logging
import os
import threading
import time

log = logging.getLogger(__name__)

# [CLAUDE 2026-06-03] Канвас GUI — ЛАНДШАФТ 800x480 (как пользователь видит Car Thing).
# present() для Mac НЕ поворачивает кадр, поэтому окно и буфер тоже ландшафтные. Поворот -90
# существует только для физической портретной панели устройства, на мониторе он не нужен.
DEVICE_W = 800
DEVICE_H = 480

EV_TAP         = "tap"
EV_LONG_TAP    = "long_tap"
EV_SWIPE_LEFT  = "swipe_left"
EV_SWIPE_RIGHT = "swipe_right"
EV_SWIPE_UP    = "swipe_up"
EV_SWIPE_DOWN  = "swipe_down"
EV_ENCODER_CW  = "encoder_cw"
EV_ENCODER_CCW = "encoder_ccw"
EV_PRESS       = "press"
EV_BACK        = "back"
EV_SETTINGS    = "settings"

LONG_TAP_SEC = 0.65
TAP_MAX_PX   = 30
SWIPE_MIN_PX = 80

_instance: "MacDisplay | None" = None


class MacDisplay:
    """DRMDisplay-совместимый дисплей для macOS. blit() потокобезопасен."""

    def __init__(self, scale: float | None = None):
        global _instance
        import pygame
        self._pygame = pygame
        # НЕ инициализируем pygame здесь — только в main thread через _init_in_main_thread()
        self._scale = scale
        self.width  = DEVICE_W
        self.height = DEVICE_H
        self._screen = None
        self._surface = None
        self._on_event = None
        self._pending_frame: bytes | None = None
        self._lock = threading.Lock()
        self._down = False
        self._sx = self._sy = 0
        self._last_cy = 0
        self._scrolling = False
        self._down_t = 0.0
        self._win_w = DEVICE_W
        self._win_h = DEVICE_H
        _instance = self

    def _init_in_main_thread(self):
        pygame = self._pygame
        pygame.init()
        if self._scale is None:
            info = pygame.display.Info()
            self._scale = min(1.0, (info.current_h * 0.8) / DEVICE_H)
        self._win_w = int(DEVICE_W * self._scale)
        self._win_h = int(DEVICE_H * self._scale)
        self._screen = pygame.display.set_mode((self._win_w, self._win_h))
        self._surface = pygame.Surface((DEVICE_W, DEVICE_H))
        pygame.display.set_caption("Car Thing")
        log.info("MacDisplay init: scale=%.2f %dx%d", self._scale, self._win_w, self._win_h)

    def set_on_event(self, on_event):
        self._on_event = on_event

    def blit(self, img_bytes: bytes):
        """Потокобезопасно: сохраняем кадр, main thread отрисует его."""
        with self._lock:
            self._pending_frame = img_bytes

    def _present_pending(self):
        with self._lock:
            frame = self._pending_frame
            self._pending_frame = None
        if frame is None or self._screen is None:
            return
        # [CLAUDE 2026-06-03] НЕ логируем каждый кадр (флудит лог ~5/с, диагностика тонет).
        pygame = self._pygame
        try:
            surf = pygame.image.frombytes(frame, (DEVICE_W, DEVICE_H), "RGBA")
            self._surface.blit(surf, (0, 0))
            if self._scale != 1.0:
                scaled = pygame.transform.smoothscale(
                    self._surface, (self._win_w, self._win_h))
                self._screen.blit(scaled, (0, 0))
            else:
                self._screen.blit(self._surface, (0, 0))
            pygame.display.flip()
        except Exception as e:
            log.warning("MacDisplay.blit: %s", e)

    def _to_canvas(self, wx, wy):
        """[CLAUDE 2026-06-03] Окно ландшафтное 800x480 и present() НЕ поворачивает кадр,
        значит координаты мыши = координаты канваса напрямую (только снять scale)."""
        return int(wx / self._scale), int(wy / self._scale)

    def _emit(self, event):
        if self._on_event:
            try:
                self._on_event(event)
            except Exception as e:
                log.warning("MacDisplay on_event: %s", e)

    def _mouse_down(self, wx, wy):
        self._down = True
        self._sx, self._sy = self._to_canvas(wx, wy)
        self._last_cy = self._sy            # [CLAUDE 2026-06-03] для непрерывного скролла
        self._scrolling = False
        self._down_t = time.monotonic()

    def _mouse_motion(self, wx, wy):
        # [CLAUDE 2026-06-03] Вертикальное перетаскивание мышью = непрерывный скролл списков
        # (как тач на железе). Иначе в симуляторе нечем листать. Горизонталь -> swipe (на отпускании).
        if not self._down:
            return
        cx, cy = self._to_canvas(wx, wy)
        dx, dy = cx - self._sx, cy - self._sy
        if not self._scrolling and abs(dy) > 8 and abs(dy) >= abs(dx):
            self._scrolling = True
        if self._scrolling:
            inc = cy - self._last_cy
            if inc:
                self._emit(("scroll", inc))
                self._last_cy = cy

    def _mouse_up(self, wx, wy):
        if not self._down:
            return
        self._down = False
        if self._scrolling:                 # это была прокрутка — не swipe/tap
            self._scrolling = False
            self._emit(("scroll_end", 0.0))
            return
        cx, cy = self._to_canvas(wx, wy)
        dx, dy = cx - self._sx, cy - self._sy
        duration = time.monotonic() - self._down_t
        if abs(dx) >= SWIPE_MIN_PX and abs(dx) >= abs(dy) * 1.5:
            self._emit(EV_SWIPE_LEFT if dx < 0 else EV_SWIPE_RIGHT)
        elif abs(dy) >= SWIPE_MIN_PX and abs(dy) >= abs(dx) * 1.5:
            self._emit(EV_SWIPE_UP if dy < 0 else EV_SWIPE_DOWN)
        elif abs(dx) < TAP_MAX_PX and abs(dy) < TAP_MAX_PX:
            ev = EV_LONG_TAP if duration >= LONG_TAP_SEC else EV_TAP
            self._emit((ev, self._sx, self._sy))

    def pump(self):
        """Вызывается из main thread ~60fps."""
        self._present_pending()
        pygame = self._pygame
        for event in pygame.event.get():
            t = event.type
            if t == pygame.QUIT:
                os._exit(0)
            elif t == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self._mouse_down(*event.pos)
            elif t == pygame.MOUSEBUTTONUP and event.button == 1:
                self._mouse_up(*event.pos)
            elif t == pygame.MOUSEMOTION:
                self._mouse_motion(*event.pos)
            elif t == pygame.MOUSEWHEEL:
                self._emit(EV_ENCODER_CW if event.y > 0 else EV_ENCODER_CCW)
            elif t == pygame.KEYDOWN:
                self._handle_key(event.key)

    def _handle_key(self, key):
        pygame = self._pygame
        m = {
            pygame.K_UP:     EV_ENCODER_CW,
            pygame.K_DOWN:   EV_ENCODER_CCW,
            pygame.K_RETURN: EV_PRESS,
            pygame.K_ESCAPE: EV_BACK,
            pygame.K_s:      EV_SETTINGS,
        }
        ev = m.get(key)
        if ev:
            self._emit(ev)

    def close(self):
        try:
            self._pygame.quit()
        except Exception:
            pass


def run_with_display(async_main):
    """Запустить async_main в отдельном потоке, pygame event loop — в main thread."""
    display = _instance
    if display is None:
        raise RuntimeError("MacDisplay не создан")

    display._init_in_main_thread()

    # asyncio в фоновом потоке
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=lambda: loop.run_until_complete(async_main()), daemon=True)
    t.start()

    import pygame
    clock = pygame.time.Clock()
    while t.is_alive():
        display.pump()
        clock.tick(60)
