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

MENU_LONG_PRESS_SECONDS = float(os.environ.get("CARTHING_MENU_LONG_PRESS_SECONDS", "1.0"))


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


async def start(
    get_ams,
    get_notification=None,
    on_notification_negative_action=None,
    on_notification_positive_action=None,
    is_system_menu_open=None,
    on_system_menu_open=None,
    on_system_menu_close=None,
    on_system_menu_select=None,
    on_system_menu_rotate=None,
):
    """Start reading encoder + buttons.

    get_ams() returns current AMSClient or None.
    get_notification() returns the currently displayed notification or None.
    on_notification_negative_action(notification) triggers the ANCS negative action.
    on_notification_positive_action(notification) triggers the ANCS positive action.
    """
    key_down_at = {}

    def menu_is_open():
        return bool(is_system_menu_open and is_system_menu_open())

    async def open_menu():
        if on_system_menu_open is not None:
            await on_system_menu_open()

    async def close_menu():
        if on_system_menu_close is not None:
            await on_system_menu_close()

    async def rotate_menu(delta):
        if on_system_menu_rotate is not None:
            await on_system_menu_rotate(delta)

    async def select_menu():
        if on_system_menu_select is not None:
            await on_system_menu_select()

    async def on_encoder(ev):
        _, _, evtype, code, value = ev
        if evtype == EV_REL and code == REL_HWHEEL:
            if menu_is_open():
                await rotate_menu(value)
                return
            ams = get_ams()
            if not ams:
                return
            cmd = CMD_VOL_UP if value > 0 else CMD_VOL_DOWN
            log.info("Encoder %+d → cmd 0x%02x", value, cmd)
            await ams.send_command(cmd)

    async def on_buttons(ev):
        _, _, evtype, code, value = ev
        if evtype != EV_KEY:
            return
        if value == KEY_DOWN:
            key_down_at[code] = time.monotonic()

            if menu_is_open():
                if code == KEY_ESC:
                    await close_menu()
                elif code == KEY_ENTER:
                    await select_menu()
                elif code == KEY_1:
                    await rotate_menu(-1)
                elif code == KEY_2:
                    await rotate_menu(1)
                elif code == KEY_4:
                    await close_menu()
                return

            if code == KEY_ESC:
                return

            notification = get_notification() if get_notification else None
            if (
                code == KEY_ENTER
                and notification is not None
                and notification.has_positive_action
                and on_notification_positive_action is not None
            ):
                log.info(
                    "Encoder press → ANCS positive action uid=%d app=%s",
                    notification.uid,
                    notification.app_name,
                )
                await on_notification_positive_action(notification)
                return

            ams = get_ams()
            if not ams and code == KEY_ENTER and on_system_menu_open is not None:
                log.info("Encoder press with no AMS -> open system menu")
                await open_menu()
                return
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
            return

        if value != KEY_UP:
            return

        down_at = key_down_at.pop(code, None)
        held_for = 0.0 if down_at is None else time.monotonic() - down_at
        if code == KEY_ESC and held_for >= MENU_LONG_PRESS_SECONDS:
            log.info("Back held %.1fs -> open system menu", held_for)
            await open_menu()
            return

        notification = get_notification() if get_notification else None
        if (
            code == KEY_ESC
            and notification is not None
            and notification.has_negative_action
            and on_notification_negative_action is not None
        ):
            log.info(
                "Back button → ANCS negative action uid=%d app=%s",
                notification.uid,
                notification.app_name,
            )
            await on_notification_negative_action(notification)
            return

    await _read_events(os.environ.get("CARTHING_INPUT_ROTARY", "/dev/input/event1"), on_encoder)
    await _read_events(os.environ.get("CARTHING_INPUT_BUTTONS", "/dev/input/event0"), on_buttons)
