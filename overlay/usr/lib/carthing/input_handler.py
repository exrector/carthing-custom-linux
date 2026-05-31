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
import asyncio, struct, os, logging

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
_KEY_TO_BTN    = {KEY_1: "btn_1", KEY_2: "btn_2", KEY_3: "btn_3", KEY_4: "btn_4"}

# Touch → landscape canvas. Panel is portrait 480x800; the screen is rotated -90,
# so canvas_x = touch_y and canvas_y = (CANVAS_H-1) - touch_x.
CANVAS_H     = 480
SWIPE_MIN_PX = 100   # min horizontal canvas travel to switch desktops
TAP_MAX_PX   = 30    # max travel to count as a tap
EDGE_PX      = 70    # зона «края» по вертикали: старт свайпа здесь = жест открыть/закрыть


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
    # DRAG_STEP_PX: пока тянешь палец, каждые столько px вертикали = один шаг прокрутки
    # (непрерывное листание «за пальцем», а не один резкий свайп на отпускании).
    DRAG_STEP_PX = 50
    EDGE_DRAG_START = 10   # как мало нужно увести палец от края, чтобы шторка начала ехать
    t = {"rawx": None, "rawy": None, "down": False,
         "sx": None, "sy": None, "cx": None, "cy": None,
         "stepy": None, "vstepped": False, "zone": "mid", "dragging": False}

    def _finish_touch():
        if not t["down"]:
            return
        t["down"] = False
        if t["sx"] is None or t["cx"] is None:
            return
        dx, dy = t["cx"] - t["sx"], t["cy"] - t["sy"]
        if t["dragging"]:                         # начатый edge-drag -> доводка (по позиции пальца)
            kind = "open" if t["zone"] == "top" else "close"
            on_event(("drag_end", kind, t["cy"]))
        elif abs(dx) < TAP_MAX_PX and abs(dy) < TAP_MAX_PX:
            on_event((EV_TAP, t["cx"], t["cy"]))  # маленькое движение в любом месте = тап
        elif abs(dx) >= SWIPE_MIN_PX and abs(dx) > abs(dy):
            on_event(EV_SWIPE_LEFT if dx < 0 else EV_SWIPE_RIGHT)
        elif t["vstepped"]:
            pass                                  # середина: вертикаль уже проскроллена шагами
        elif abs(dy) >= SWIPE_MIN_PX and abs(dy) > abs(dx):
            on_event(EV_SWIPE_UP if dy < 0 else EV_SWIPE_DOWN)
        t["sx"] = t["sy"] = t["cx"] = t["cy"] = t["stepy"] = None
        t["vstepped"] = False
        t["zone"] = "mid"

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
                    t["sx"] = t["sy"] = t["stepy"] = None
                    t["vstepped"] = False
                    t["zone"] = "mid"
                    t["dragging"] = False
        elif evtype == EV_KEY and code == BTN_TOUCH and value == 0:
            _finish_touch()
        elif evtype == EV_SYN and code == SYN_REPORT:
            if t["down"] and t["rawx"] is not None and t["rawy"] is not None:
                cx = t["rawy"]                       # canvas_x = touch_y
                cy = (CANVAS_H - 1) - t["rawx"]       # canvas_y = (H-1) - touch_x
                if t["sx"] is None:
                    t["sx"], t["sy"], t["stepy"] = cx, cy, cy
                    # классифицируем старт: верхний край / нижний край / середина
                    t["zone"] = ("top" if cy < EDGE_PX
                                 else "bottom" if cy > CANVAS_H - EDGE_PX
                                 else "mid")
                t["cx"], t["cy"] = cx, cy
                if t["zone"] == "mid":
                    # середина: непрерывное листание шагами
                    while t["cy"] - t["stepy"] >= DRAG_STEP_PX:
                        on_event(EV_SWIPE_DOWN); t["stepy"] += DRAG_STEP_PX; t["vstepped"] = True
                    while t["stepy"] - t["cy"] >= DRAG_STEP_PX:
                        on_event(EV_SWIPE_UP); t["stepy"] -= DRAG_STEP_PX; t["vstepped"] = True
                elif t["zone"] == "top":
                    # от верхнего края: НИЖНИЙ край шторки = позиция пальца (cy), едет за ним
                    if t["dragging"] or t["cy"] - t["sy"] >= EDGE_DRAG_START:
                        t["dragging"] = True
                        on_event(("drag", "open", t["cy"]))
                elif t["zone"] == "bottom":
                    if t["dragging"] or t["sy"] - t["cy"] >= EDGE_DRAG_START:
                        t["dragging"] = True
                        on_event(("drag", "close", t["cy"]))

    await _read_events('/dev/input/event1', on_encoder)
    await _read_events('/dev/input/event0', on_buttons)
    if use_gui:
        await _read_events('/dev/input/event3', on_touch)
