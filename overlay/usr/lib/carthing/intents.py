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
                 on_pairing=None, on_speaker_pair_select=None, on_trusted_remove=None,
                 on_session_select=None, on_route_input_select=None,
                 on_route_output_select=None, on_route_activate=None, on_toggle_sleep=None,
                 on_set_off_timeout=None, on_toggle_notif_blink=None,
                 on_set_brightness=None):
        self.state = state
        self.on_command = on_command or (lambda src, cmd: None)
        self.on_transfer_rescan = on_transfer_rescan or (lambda: None)
        self.on_transfer_select = on_transfer_select or (lambda address: None)
        self.on_pairing = on_pairing or (lambda enabled, role="source": None)
        self.on_speaker_pair_select = on_speaker_pair_select or (lambda address: None)
        self.on_trusted_remove = on_trusted_remove or (lambda key: None)
        self.on_session_select = on_session_select or (lambda session: None)
        self.on_route_input_select = on_route_input_select or (lambda key: None)
        self.on_route_output_select = on_route_output_select or (lambda key: None)
        self.on_route_activate = on_route_activate or (lambda: None)
        self.on_toggle_sleep = on_toggle_sleep or (lambda on: None)   # [CLAUDE] сон экрана
        self.on_set_off_timeout = on_set_off_timeout or (lambda sec: None)  # [CLAUDE] тайм-аут гашения
        self.on_toggle_notif_blink = on_toggle_notif_blink
        self.on_set_brightness = on_set_brightness or (lambda pct: None) or (lambda on: None)  # [CLAUDE] моргание уведомлений

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
        elif intent == "media_like":
            self._like_add()
        elif intent == "media_shuffle":
            self._media("shuffle")
        elif intent == "media_repeat":
            self._media("repeat")
        elif intent == "media_bookmark":
            self._media("bookmark")
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
            role = getattr(self.state, "pairing_role", "source")
            self.on_pairing(False, role)
        elif intent == "speaker_pair_select":
            self._speaker_pair_select(payload)
        elif intent == "trusted_remove":
            self._trusted_remove(payload)
        elif intent == "route_input_select":
            self._route_input_select(payload)
        elif intent == "route_output_select":
            self._route_output_select(payload)
        elif intent == "route_activate":
            self.on_route_activate()
        elif intent == "screen_off_adjust":      # [CLAUDE] ±тайм-аут гашения экрана
            self._adjust_off_timeout(payload)

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

    def _like_add(self):
        """Сердце = ТОЛЬКО добавить в избранное (Like 11). Тумблера НЕТ намеренно: AMS не
        сообщает реальное состояние, и снятие лайка могло бы случайно выкинуть песню из
        избранного. Поэтому тап всегда лайкает; если песня уже там — тап безвреден (no-op).
        Снять лайк нельзя — это сознательная страховка."""
        key = self.state.control_source_key
        sess = self.state.sources[key]
        sess.liked = True
        self.state.last_media_source = key
        self.on_command(key, "like")

    def _exclude(self, active_key):
        """Pause every other source when one starts playing."""
        for k, s in self.state.sources.items():
            if k != active_key and s.playing:
                s.playing = False
                self.on_command(k, "pause")

    # ── settings ───────────────────────────────────────────────────────────────
    def _settings(self, key):
        if key == "pairing_device":
            self.state.pairing_role = "device"
            self.state.pairing_mode = True
            self.state.speaker_pairing_status = "scan"
            self.state.pairing_message = ""
            self.state.clear_speaker_candidates()
            self.on_pairing(True, "device")
        elif key in ("sessions", "modes", "routes"):
            # [CLAUDE 2026-06-02] режимы удалены — пункт ведёт на маршрутный экран (ВХОД/ВЫХОД)
            self.state.active_desktop = self.state.ROUTER
        elif key == "toggle_sleep":            # [CLAUDE] тумблер сна экрана
            new = not bool(getattr(self.state, "sleep_on_idle", True))
            self.state.sleep_on_idle = new     # оптимистично для UI
            self.on_toggle_sleep(new)          # runtime: power.set_idle_sleep + settings.set
        elif key == "brightness":              # [CLAUDE 2026-06-10] цикл яркости 25→50→75→100
            self._cycle_brightness()
        elif key == "toggle_notif_blink":      # [CLAUDE] тумблер моргания уведомлений
            new = not bool(getattr(self.state, "notif_blink", True))
            self.state.notif_blink = new       # оптимистично для UI (render читает сразу)
            self.on_toggle_notif_blink(new)    # runtime: settings.set (персист)
        # trusted / display / about: handled by UI navigation later

    def _speaker_pair_select(self, address):
        if not address:
            return
        self.state.speaker_pairing_status = "connect"
        self.state.pairing_message = ""
        self.on_speaker_pair_select(address)

    def _trusted_remove(self, key):
        target = next(
            (device for device in self.state.trusted
             if device.get("key") == key or device.get("address") == key),
            None,
        )
        address = (target or {}).get("address") or key
        if self.state.remove_trusted(key):
            try:
                self.state.save_trusted()
            except Exception:
                pass
            self.on_trusted_remove(address)

    def _transfer_select(self, key):
        address = self.state.select_default_speaker(key)
        if address:
            try:
                self.state.save_trusted()
            except Exception:
                pass
            self.on_transfer_select(address)


    def _route_input_select(self, key):
        selected = self.state.select_route_input(key)
        if selected:
            try:
                self.state.save_trusted()
            except Exception:
                pass
            self.on_route_input_select(selected)

    def _route_output_select(self, key):
        selected = self.state.select_route_output(key)
        if selected:
            try:
                self.state.save_trusted()
            except Exception:
                pass
            self.on_route_output_select(selected)

    # [CLAUDE 2026-06-01] ±тайм-аут полного гашения экрана (шаг 30с, 30с..10мин)
    SCREEN_OFF_STEP = 30
    SCREEN_OFF_MIN = 30
    SCREEN_OFF_MAX = 600

    BRIGHTNESS_PRESETS = (25, 50, 75, 100)

    def _cycle_brightness(self):
        cur = int(getattr(self.state, "screen_brightness", 100))
        presets = list(self.BRIGHTNESS_PRESETS)
        nxt = presets[(presets.index(cur) + 1) % len(presets)] if cur in presets else 100
        self.state.screen_brightness = nxt   # оптимистично для UI
        self.on_set_brightness(nxt)          # runtime: power + settings.set

    def _adjust_off_timeout(self, direction):
        cur = int(getattr(self.state, "screen_off_sec", 150))
        new = cur + (self.SCREEN_OFF_STEP if direction == "+" else -self.SCREEN_OFF_STEP)
        new = max(self.SCREEN_OFF_MIN, min(self.SCREEN_OFF_MAX, new))
        if new == cur:
            return
        self.state.screen_off_sec = new      # оптимистично для UI
        self.on_set_off_timeout(new)         # runtime: power.set_off_after + settings.set
