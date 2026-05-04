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

EV_KEY = 0x01
EV_REL = 0x02
REL_HWHEEL = 6

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

# AMS RemoteCommand codes
CMD_TOGGLE    = 0x02
CMD_NEXT      = 0x03
CMD_PREV      = 0x04
CMD_VOL_UP    = 0x05
CMD_VOL_DOWN  = 0x06


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


async def start(get_ams):
    """Start reading encoder + buttons. get_ams() returns current AMSClient or None."""

    async def on_encoder(ev):
        _, _, evtype, code, value = ev
        if evtype == EV_REL and code == REL_HWHEEL:
            ams = get_ams()
            if not ams:
                return
            cmd = CMD_VOL_UP if value > 0 else CMD_VOL_DOWN
            log.info("Encoder %+d → cmd 0x%02x", value, cmd)
            await ams.send_command(cmd)

    async def on_buttons(ev):
        _, _, evtype, code, value = ev
        if evtype != EV_KEY or value != KEY_DOWN:
            return
        ams = get_ams()
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

    await _read_events('/dev/input/event1', on_encoder)
    await _read_events('/dev/input/event0', on_buttons)
