"""Intent dispatcher for the minimal Play Now + Assistant product."""


class Dispatcher:
    BRIGHTNESS_PRESETS = tuple(range(10, 101, 10))

    def __init__(
        self,
        state,
        on_command=None,
        on_pairing=None,
        on_toggle_notif_blink=None,
        on_set_brightness=None,
        on_power_off=None,
        on_toggle_client=None,
        **_unused,
    ):
        self.state = state
        self.on_command = on_command or (lambda source, command: None)
        self.on_pairing = on_pairing or (lambda enabled, role="input": None)
        self.on_toggle_notif_blink = on_toggle_notif_blink or (lambda enabled: None)
        self.on_set_brightness = on_set_brightness or (lambda percent: None)
        self.on_power_off = on_power_off or (lambda: None)
        self.on_toggle_client = on_toggle_client or (lambda enabled: None)

    def dispatch(self, intent, payload=None):
        media = {
            "media_play_pause": "play_pause",
            "media_next": "next",
            "media_prev": "prev",
            "media_skip_fwd": "skip_fwd",
            "media_skip_back": "skip_back",
            "media_like": "like",
            "media_shuffle": "shuffle",
            "media_repeat": "repeat",
            "media_bookmark": "bookmark",
            "media_vol_up": "vol_up",
            "media_vol_down": "vol_down",
        }
        if intent in media:
            self._media(media[intent])
        elif intent == "settings_select":
            self._settings(str(payload or ""))
        elif intent == "pairing_cancel":
            self.state.pairing_mode = False
            self.on_pairing(False, "input")
        elif intent == "display_adjust":
            key, direction = payload
            self._display_adjust(str(key), str(direction))
        elif intent == "remote_mic_toggle":
            self._set_remote_mic(
                not bool(getattr(self.state, "remote_mic_enabled", False))
            )
        elif intent == "remote_mic_set":
            self._set_remote_mic(bool(payload))

    def _media(self, command):
        session = self.state.iphone
        if command == "play_pause":
            session.playing = not session.playing
            command = "play" if session.playing else "pause"
        elif command == "like":
            session.liked = True
        self.state.last_media_source = "iphone"
        self.on_command("iphone", command)

    def _settings(self, key):
        if key == "add_iphone":
            self.state.pairing_role = "input"
            self.state.pairing_mode = True
            self.state.pairing_message = ""
            self.on_pairing(True, "input")
        elif key == "brightness":
            self._display_adjust("brightness", "+")
        elif key == "notif_blink":
            self._display_adjust("notif_blink", "+")
        elif key == "power_off_confirm":
            self.on_power_off()

    def _display_adjust(self, key, direction):
        if key == "brightness":
            current = int(getattr(self.state, "screen_brightness", 100))
            presets = self.BRIGHTNESS_PRESETS
            index = min(
                range(len(presets)),
                key=lambda candidate: abs(presets[candidate] - current),
            )
            step = 1 if direction == "+" else -1
            index = max(0, min(len(presets) - 1, index + step))
            value = presets[index]
            self.state.screen_brightness = value
            self.on_set_brightness(value)
        elif key == "notif_blink":
            value = not bool(getattr(self.state, "notif_blink", True))
            self.state.notif_blink = value
            self.on_toggle_notif_blink(value)

    def _set_remote_mic(self, enabled):
        self.state.set_remote_mic(
            bool(enabled), state="connecting" if enabled else "off"
        )
        self.on_toggle_client(bool(enabled))
