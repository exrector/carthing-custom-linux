"""Intent dispatcher — the only place that mutates AppState in response to UI.

Screens / status bar emit string intents; dispatch() applies them to AppState
and forwards device commands via on_command(source_key, command). on_command is
wired to the BLE layer on-device, or to a logger in the simulator.

Media routing (agreed model):
  - the transport controls AppState.control_source (active media desktop's
    source, else the last active source);
  - SINGLE AUDIO FOCUS: starting playback on one source pauses the other
    (mutual exclusion).
"""


class Dispatcher:
    def __init__(self, state, on_command=None, on_transfer_rescan=None, on_transfer_select=None,
                 on_pairing=None):
        self.state = state
        self.on_command = on_command or (lambda src, cmd: None)
        self.on_transfer_rescan = on_transfer_rescan or (lambda: None)
        self.on_transfer_select = on_transfer_select or (lambda address: None)
        self.on_pairing = on_pairing or (lambda enabled: None)

    def dispatch(self, intent, payload=None):
        if intent == "media_play_pause":
            self._media("play_pause")
        elif intent == "media_next":
            self._media("next")
        elif intent == "media_prev":
            self._media("prev")
        elif intent == "media_skip_fwd":
            self._media("skip_fwd")
        elif intent == "media_skip_back":
            self._media("skip_back")
        elif intent == "media_vol_up":
            self._media("vol_up")
        elif intent == "media_vol_down":
            self._media("vol_down")
        elif intent == "open_notifications":
            self.state.active_desktop = self.state.NOTIFICATIONS   # navigate to the list
            self.state.unread_count = 0
        elif intent == "settings_select":
            self._settings(payload)
        elif intent == "transfer_rescan":
            self.state.transfer_scanning = True
            self.on_transfer_rescan()
        elif intent == "transfer_select":
            self._transfer_select(payload)
        elif intent == "pairing_cancel":
            self.state.pairing_mode = False
            self.on_pairing(False)

    # ── media ────────────────────────────────────────────────────────────────
    def _media(self, command):
        key = self.state.control_source_key
        sess = self.state.sources[key]
        if command == "play_pause":
            start = not sess.playing
            sess.playing = start
            self.state.last_media_source = key
            if start:
                self._exclude(key)                 # single audio focus
            self.on_command(key, "play" if start else "pause")
        else:
            self.state.last_media_source = key
            self.on_command(key, command)

    def _exclude(self, active_key):
        """Pause every other source when one starts playing."""
        for k, s in self.state.sources.items():
            if k != active_key and s.playing:
                s.playing = False
                self.on_command(k, "pause")

    # ── settings ───────────────────────────────────────────────────────────────
    def _settings(self, key):
        if key == "pairing":
            self.state.pairing_mode = True
            self.on_pairing(True)
        # trusted / display / about: handled by UI navigation later

    def _transfer_select(self, key):
        address = self.state.select_default_speaker(key)
        if address:
            try:
                self.state.save_trusted()
            except Exception:
                pass
            self.on_transfer_select(address)
