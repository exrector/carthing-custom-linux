"""
Input handler for Car Thing:
  event0 = gpio-keys (buttons)
  event1 = rotary encoder (EV_REL, REL_HWHEEL code=6)

AMS RemoteCommand values:
  0x02 = TogglePlayPause
  0x03 = NextTrack
  0x04 = PreviousTrack
  0x05 = VolumeUp
  0x06 = VolumeDown
"""
import asyncio, struct, os, logging, time

log = logging.getLogger(__name__)

# input_event on aarch64 64-bit kernel: 8+8+2+2+4 = 24 bytes
_EV_FMT = 'qqHHi'
_EV_SIZE = struct.calcsize(_EV_FMT)

EV_SYN = 0x00
EV_KEY = 0x01
EV_REL = 0x02
EV_ABS = 0x03
REL_HWHEEL = 6

# Touchscreen (event3, tlsc6x — MT protocol type B)
ABS_MT_SLOT        = 0x2f
ABS_MT_POSITION_X  = 0x35
ABS_MT_POSITION_Y  = 0x36
ABS_MT_TRACKING_ID = 0x39
BTN_TOUCH          = 0x14a
SYN_REPORT         = 0x00

KEY_DOWN = 1
KEY_UP   = 0

# gpio-keys keycodes — detected from bitmask 400001000003e
# bits 1-5 → KEY_ESC=1, KEY_1=2, KEY_2=3, KEY_3=4, KEY_4=5
# bit 28   → KEY_ENTER=28
# bit 48   → KEY_? (preset 4 button)
KEY_ESC   = 1   # back button
KEY_1     = 2   # preset 1
KEY_2     = 3   # preset 2
KEY_3     = 4   # preset 3
KEY_4     = 5   # preset 4
KEY_ENTER = 28  # encoder press
KEY_SETTINGS = 50  # settings button (верхний ряд)

# AMS RemoteCommand codes
CMD_TOGGLE    = 0x02
CMD_NEXT      = 0x03
CMD_PREV      = 0x04
CMD_VOL_UP    = 0x05
CMD_VOL_DOWN  = 0x06

# High-level UI event names — MUST match ui_screen.Input values (no PIL import
# here, so the input layer stays free of the GUI stack's dependencies).
EV_ENCODER_CW  = "encoder_cw"
EV_ENCODER_CCW = "encoder_ccw"
EV_PRESS       = "press"
EV_BACK        = "back"
EV_SETTINGS    = "settings"
EV_SWIPE_LEFT  = "swipe_left"
EV_SWIPE_RIGHT = "swipe_right"
EV_SWIPE_UP    = "swipe_up"
EV_SWIPE_DOWN  = "swipe_down"
EV_EDGE_TOP    = "edge_top"      # свайп ОТ верхнего края вниз (открыть вью)
EV_EDGE_BOTTOM = "edge_bottom"   # свайп ОТ нижнего края вверх (закрыть вью)
EV_TAP         = "tap"
EV_LONG_TAP    = "long_tap"
_KEY_TO_BTN    = {KEY_1: "btn_1", KEY_2: "btn_2", KEY_3: "btn_3", KEY_4: "btn_4"}

# Touch → landscape canvas. Panel is portrait 480x800; the screen is rotated -90,
# so canvas_x = touch_y and canvas_y = (CANVAS_H-1) - touch_x.
CANVAS_H     = 480
SWIPE_MIN_PX = 72    # deliberate but light horizontal travel to switch views
TAP_MAX_PX   = 30    # max travel to count as a tap
LONG_TAP_SEC = 0.65  # deliberate hold for destructive/test-mode activation
EDGE_PX      = 36    # узкая системная edge-зона; остальной экран ведёт себя как обычный scroll-view
DIRECTION_LOCK_PX = 14
DIRECTION_RATIO = 1.15


async def _read_events(path, callback):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
    loop = asyncio.get_event_loop()
    q = asyncio.Queue()

    def _readable():
        try:
            data = os.read(fd, _EV_SIZE * 16)
            for i in range(0, len(data) - (_EV_SIZE - 1), _EV_SIZE):
                ev = struct.unpack_from(_EV_FMT, data, i)
                asyncio.ensure_future(callback(ev))
        except BlockingIOError:
            pass

    loop.add_reader(fd, _readable)
    log.info("Input: watching %s", path)


async def start(get_ams=None, on_event=None):
    """Start reading encoder + buttons.

    Two modes:
      - on_event(name): preferred — emit high-level UI events into the GUI
        compositor, which routes them to the active screen / intents.
      - get_ams(): legacy fallback — drive AMS directly when no GUI sink is wired.
    """
    use_gui = on_event is not None

    async def on_encoder(ev):
        _, _, evtype, code, value = ev
        if evtype != EV_REL or code != REL_HWHEEL:
            return
        log.info("Encoder raw value=%+d", value)
        if use_gui:
            on_event(EV_ENCODER_CW if value > 0 else EV_ENCODER_CCW)
            return
        ams = get_ams() if get_ams else None
        if not ams:
            return
        cmd = CMD_VOL_UP if value > 0 else CMD_VOL_DOWN
        log.info("Encoder %+d → cmd 0x%02x", value, cmd)
        await ams.send_command(cmd)

    async def on_buttons(ev):
        _, _, evtype, code, value = ev
        if evtype != EV_KEY or value != KEY_DOWN:
            return
        if use_gui:
            if code == KEY_ENTER:
                on_event(EV_PRESS)
            elif code == KEY_ESC:
                on_event(EV_BACK)
            elif code == KEY_SETTINGS:
                on_event(EV_SETTINGS)
            elif code in _KEY_TO_BTN:
                on_event(_KEY_TO_BTN[code])
            return
        ams = get_ams() if get_ams else None
        if not ams:
            return
        if code == KEY_ENTER:
            log.info("Encoder press → TogglePlayPause")
            await ams.send_command(CMD_TOGGLE)
        elif code == KEY_1:
            log.info("Button 1 → PreviousTrack")
            await ams.send_command(CMD_PREV)
        elif code == KEY_2:
            log.info("Button 2 → NextTrack")
            await ams.send_command(CMD_NEXT)
        elif code in (KEY_3, KEY_4):
            log.info("Button %d → TogglePlayPause", code)
            await ams.send_command(CMD_TOGGLE)

    # Touch: a single-finger gesture → horizontal swipe (desktop switch) or tap.
    # MT type B; we track the active contact only (good enough for swipe/tap).
    EDGE_DRAG_START = 10   # как мало нужно увести палец от края, чтобы шторка начала ехать
    EDGE_SWIPE_MIN = 54
    t = {"rawx": None, "rawy": None, "down": False,
         "sx": None, "sy": None, "cx": None, "cy": None,
         "down_t": None,
         "lasty": None, "last_scroll_t": None, "velocity": 0.0,
         "vstepped": False, "zone": "mid", "dragging": False,
         "axis": None}

    def _finish_touch():
        if not t["down"]:
            return
        t["down"] = False
        if t["sx"] is None or t["cx"] is None:
            return
        dx, dy = t["cx"] - t["sx"], t["cy"] - t["sy"]
        if t["dragging"]:
            if t["zone"] == "top" and dy >= EDGE_SWIPE_MIN:
                on_event(EV_EDGE_TOP)
            elif t["zone"] == "bottom" and dy <= -EDGE_SWIPE_MIN:
                on_event(EV_EDGE_BOTTOM)
        elif (
            t["axis"] in (None, "horizontal")
            and abs(dx) >= SWIPE_MIN_PX
            and abs(dx) >= abs(dy) * DIRECTION_RATIO
        ):
            on_event(EV_SWIPE_LEFT if dx < 0 else EV_SWIPE_RIGHT)
        elif t["vstepped"]:
            on_event(("scroll_end", t["velocity"]))  # отпустили список -> единая инерция в GUI
        elif abs(dx) < TAP_MAX_PX and abs(dy) < TAP_MAX_PX:
            duration = time.monotonic() - (t["down_t"] or time.monotonic())
            event = EV_LONG_TAP if duration >= LONG_TAP_SEC else EV_TAP
            on_event((event, t["cx"], t["cy"]))  # маленькое движение = tap/long-tap
        t["sx"] = t["sy"] = t["cx"] = t["cy"] = t["lasty"] = t["last_scroll_t"] = None
        t["down_t"] = None
        t["velocity"] = 0.0
        t["vstepped"] = False
        t["zone"] = "mid"
        t["dragging"] = False
        t["axis"] = None

    async def on_touch(ev):
        if not use_gui:
            return
        _, _, evtype, code, value = ev
        if evtype == EV_ABS:
            if code == ABS_MT_POSITION_X:
                t["rawx"] = value
            elif code == ABS_MT_POSITION_Y:
                t["rawy"] = value
            elif code == ABS_MT_TRACKING_ID:
                if value == -1:
                    _finish_touch()
                else:
                    t["down"] = True
                    t["sx"] = t["sy"] = t["cx"] = t["cy"] = t["lasty"] = None
                    t["down_t"] = time.monotonic()
                    t["last_scroll_t"] = None
                    t["velocity"] = 0.0
                    t["vstepped"] = False
                    t["zone"] = "mid"
                    t["dragging"] = False
                    t["axis"] = None
        elif evtype == EV_KEY and code == BTN_TOUCH and value == 0:
            _finish_touch()
        elif evtype == EV_SYN and code == SYN_REPORT:
            if t["down"] and t["rawx"] is not None and t["rawy"] is not None:
                cx = t["rawy"]                       # canvas_x = touch_y
                cy = (CANVAS_H - 1) - t["rawx"]       # canvas_y = (H-1) - touch_x
                if t["sx"] is None:
                    t["sx"], t["sy"], t["lasty"] = cx, cy, cy
                    t["last_scroll_t"] = time.monotonic()
                    # классифицируем старт: верхний край / нижний край / середина
                    t["zone"] = ("top" if cy < EDGE_PX
                                 else "bottom" if cy > CANVAS_H - EDGE_PX
                                 else "mid")
                t["cx"], t["cy"] = cx, cy
                if t["zone"] == "mid":
                    total_dx = t["cx"] - t["sx"]
                    total_dy = t["cy"] - t["sy"]
                    if (
                        t["axis"] is None
                        and max(abs(total_dx), abs(total_dy)) >= DIRECTION_LOCK_PX
                    ):
                        if abs(total_dx) >= abs(total_dy) * DIRECTION_RATIO:
                            t["axis"] = "horizontal"
                        elif abs(total_dy) >= abs(total_dx) * DIRECTION_RATIO:
                            t["axis"] = "vertical"
                    # Only a direction-locked vertical gesture may move a list.
                    if t["axis"] == "vertical":
                        d = t["cy"] - t["lasty"]
                        if d != 0:
                            now = time.monotonic()
                            dt = max(0.001, now - (t["last_scroll_t"] or now))
                            inst = d / dt
                            t["velocity"] = (0.65 * inst) + (0.35 * t["velocity"])
                            t["last_scroll_t"] = now
                            on_event(("scroll", d)); t["lasty"] = t["cy"]; t["vstepped"] = True
                elif t["zone"] == "top":
                    if t["dragging"] or t["cy"] - t["sy"] >= EDGE_DRAG_START:
                        t["dragging"] = True
                elif t["zone"] == "bottom":
                    if t["dragging"] or t["sy"] - t["cy"] >= EDGE_DRAG_START:
                        t["dragging"] = True

    await _read_events('/dev/input/event1', on_encoder)
    await _read_events('/dev/input/event0', on_buttons)
    if use_gui:
        await _read_events('/dev/input/event3', on_touch)
