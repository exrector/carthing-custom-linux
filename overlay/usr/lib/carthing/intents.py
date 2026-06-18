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
                 on_set_brightness=None, on_set_theme=None,
                 on_power_off=None, on_set_mode=None, on_toggle_client=None):
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
        self.on_set_brightness = on_set_brightness or (lambda pct: None)  # [CLAUDE 2026-06-10] яркость
        self.on_set_theme = on_set_theme or (lambda name: None)  # [CLAUDE 2026-06-11] тема UI
        self.on_power_off = on_power_off or (lambda: None)      # [CLAUDE 2026-06-13] мягкое выключение
        self.on_set_mode = on_set_mode or (lambda mode: None)   # [CLAUDE 2026-06-13] выбор режима
        self.on_toggle_client = on_toggle_client or (lambda on: None)

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
        elif intent == "speaker_pair_confirm":
            self._speaker_pair_confirm(payload)
        elif intent == "trusted_remove":
            self._trusted_remove(payload)
        elif intent == "route_input_select":
            self._route_input_select(payload)
        elif intent == "route_output_select":
            self._route_output_select(payload)
        elif intent == "route_activate":
            self.on_route_activate()
        elif intent == "screen_off_adjust":      # [CLAUDE] ±тайм-аут гашения экрана (legacy)
            self._adjust_off_timeout(payload)
        elif intent == "display_adjust":         # [CLAUDE 2026-06-11] единый −/+ под-настроек
            key, direction = payload
            self._display_adjust(key, direction)

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
        if key in ("pairing_input", "pairing_source"):
            self.state.pairing_role = "input"
            self.state.pairing_mode = True
            self.state.speaker_pairing_status = "advertise"
            self.state.pairing_message = ""
            self.state.clear_speaker_candidates()
            self.on_pairing(True, "input")
        elif key in ("pairing_output", "pairing_speaker", "pairing_device"):
            self.state.pairing_role = "output"
            self.state.pairing_mode = True
            self.state.speaker_pairing_status = "scan"
            self.state.pairing_message = ""
            self.state.clear_speaker_candidates()
            self.on_pairing(True, "output")
        elif key in ("sessions", "modes", "routes"):
            # [CLAUDE 2026-06-02] режимы удалены — пункт ведёт на маршрутный экран (ВХОД/ВЫХОД)
            self.state.active_desktop = self.state.ROUTER
        elif key in ("brightness", "sleep", "off_timeout", "notif_blink"):
            # [CLAUDE 2026-06-11] press энкодера по строке = шаг "+" (единый паттерн −/+)
            self._display_adjust(key, "+")
        elif key == "client_toggle":
            new = not bool(getattr(self.state, "client_enabled", False))
            self.state.client_enabled = new
            self.on_toggle_client(new)
        elif key == "power_off_confirm":          # [CLAUDE 2026-06-13] подтверждённое мягкое выключение
            self.on_power_off()
            return
        elif key in ("power_off_noop", "power_off_status"):
            return
        elif key.startswith("set_mode:"):         # [CLAUDE 2026-06-13] выбор конкретного режима
            self.on_set_mode(key.split(":", 1)[1])
            return
        # trusted / display / about: handled by UI navigation later

    def _speaker_pair_select(self, address):
        if not address:
            return
        self.state.select_speaker_candidate(address)

    def _speaker_pair_confirm(self, address=None):
        if getattr(self.state, "speaker_pairing_status", "") in ("connect", "done"):
            return
        address = address or getattr(self.state, "selected_speaker_candidate", "")
        if not address:
            return
        candidate = self.state.select_speaker_candidate(address)
        if candidate is None:
            return
        if candidate.get("trusted_output"):
            self.state.speaker_pairing_status = "done"
            self.state.pairing_message = (candidate.get("label") or address) + " уже добавлен"
            return
        self.state.speaker_pairing_status = "connect"
        self.state.pairing_message = (candidate.get("label") or address) + " подключается"
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
        address = self.state.select_route_speaker(key)
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

    BRIGHTNESS_PRESETS = tuple(range(10, 101, 10))   # [CLAUDE 2026-06-11] шаг 10%, без 0 (чёрный экран бессмыслен)
    # Сон: Выкл, 1..10 мин по одной, дальше десятками (решение владельца).
    SLEEP_STEPS_MIN = (0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 20, 30, 40, 50, 60)

    def _display_adjust(self, key, direction):
        """[CLAUDE 2026-06-11] ЕДИНЫЙ паттерн −/+ для всех под-настроек дисплея
        (решение владельца: «визуально должен понимать, что есть выбор»).
        Двухпозиционные (тема/сон/моргание) листаются в обе стороны одинаково."""
        if key == "off_timeout":
            self._adjust_off_timeout(direction)
        elif key == "brightness":
            cur = int(getattr(self.state, "screen_brightness", 100))
            presets = list(self.BRIGHTNESS_PRESETS)
            # ближайший пресет + шаг С УПОРАМИ (заворот 100→10 ощущался как поломка)
            i = min(range(len(presets)), key=lambda j: abs(presets[j] - cur))
            i = max(0, min(len(presets) - 1, i + (1 if direction == "+" else -1)))
            self.state.screen_brightness = presets[i]   # оптимистично для UI
            self.on_set_brightness(presets[i])          # runtime: power + персист
        elif key == "sleep":
            # [CLAUDE 2026-06-11] ЕДИНАЯ шкала сна: Выкл → 1..10 мин → 20..60 мин.
            # Объединяет бывшие «Сон Вкл/Выкл» + «Гашение N с» (слово отклонено владельцем).
            steps = list(self.SLEEP_STEPS_MIN)
            on = bool(getattr(self.state, "sleep_on_idle", True))
            cur_min = max(1, round(int(getattr(self.state, "screen_off_sec", 60)) / 60.0)) if on else 0
            i = min(range(len(steps)), key=lambda j: abs(steps[j] - cur_min))
            i = max(0, min(len(steps) - 1, i + (1 if direction == "+" else -1)))
            minutes = steps[i]
            if minutes == 0:
                self.state.sleep_on_idle = False
                self.on_toggle_sleep(False)
            else:
                if not on:
                    self.state.sleep_on_idle = True
                    self.on_toggle_sleep(True)
                self.state.screen_off_sec = minutes * 60
                self.on_set_off_timeout(minutes * 60)
        elif key == "notif_blink":
            new = not bool(getattr(self.state, "notif_blink", True))
            self.state.notif_blink = new
            self.on_toggle_notif_blink(new)

    def _adjust_off_timeout(self, direction):
        cur = int(getattr(self.state, "screen_off_sec", 150))
        new = cur + (self.SCREEN_OFF_STEP if direction == "+" else -self.SCREEN_OFF_STEP)
        new = max(self.SCREEN_OFF_MIN, min(self.SCREEN_OFF_MAX, new))
        if new == cur:
            return
        self.state.screen_off_sec = new      # оптимистично для UI
        self.on_set_off_timeout(new)         # runtime: power.set_off_after + settings.set
