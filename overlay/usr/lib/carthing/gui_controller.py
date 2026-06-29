"""Minimal Play Now GUI controller.

The GUI owns presentation and input only. Bluetooth, pairing, and microphone
transport remain in the runtime services.
"""

import logging
import os
import time

import identity_service
from app_state import AppState
from connection_journal import record_connection_event
from intents import Dispatcher
from screens import (
    AssistantScreen,
    NotificationsScreen,
    NowPlayingScreen,
    PairingModal,
    SettingsScreen,
)
from ui_anim import AnimDriver
from ui_screen import Compositor, DRMDisplayAdapter, Input
from ui_statusbar import StatusBar

logger = logging.getLogger(__name__)

HOME, SETTINGS, NOTIFICATIONS, ASSISTANT = 0, 1, 2, 3
NAVIGATION = (HOME, ASSISTANT, NOTIFICATIONS)


class GuiController:
    def __init__(
        self,
        display,
        on_command=None,
        on_pairing=None,
        on_notif_dismiss=None,
        on_toggle_notif_blink=None,
        on_set_brightness=None,
        on_power_off=None,
        on_toggle_client=None,
        **_unused,
    ):
        self.app_state = AppState()
        self._on_notif_dismiss = on_notif_dismiss or (lambda uid: None)
        self._volume_touch_ts = 0.0
        self._iphone_transport_connected = False
        self._iphone_grace_until = 0.0
        self._iphone_disconnect_at = 0.0
        self._iphone_disconnect_grace = max(
            0.0,
            float(os.environ.get("CARTHING_IPHONE_UI_GRACE_S", "3.0")),
        )

        self.dispatcher = Dispatcher(
            self.app_state,
            on_command=on_command,
            on_pairing=on_pairing,
            on_toggle_notif_blink=on_toggle_notif_blink,
            on_set_brightness=on_set_brightness,
            on_power_off=on_power_off,
            on_toggle_client=on_toggle_client,
        )
        emit = self.dispatcher.dispatch
        self.compositor = Compositor(
            DRMDisplayAdapter(display),
            [
                NowPlayingScreen(emit=emit),
                SettingsScreen(on_select=lambda key: emit("settings_select", key)),
                NotificationsScreen(emit=self._intent),
                AssistantScreen(emit=emit),
            ],
            status_bar=StatusBar(),
            anim=AnimDriver(),
            state=self.app_state,
            on_intent=self._intent,
            show_dots=True,
            nav_order=list(NAVIGATION),
            pairing_modal=PairingModal(emit=emit),
        )
        self.show_home()

    def _intent(self, intent, payload=None):
        if intent == StatusBar.INTENT_NOTIFICATIONS:
            self.show_screen(NOTIFICATIONS)
        elif intent == StatusBar.INTENT_ASSISTANT:
            self.show_screen(ASSISTANT)
        elif intent == "open_settings":
            self.show_screen(SETTINGS)
        elif intent == "notif_dismiss":
            self._on_notif_dismiss(payload)
        elif intent == "notif_select":
            self.compositor.screens[NOTIFICATIONS].select(payload)
            self.compositor.render()
        elif intent == "settings_tap":
            self.compositor.screens[SETTINGS].tap(payload)
            self.compositor.render()
        else:
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()

    def needs_fast_render(self):
        state = self.app_state
        return bool(
            self.compositor.active == ASSISTANT
            and state.assistant_live_text != state.assistant_live_target
        )

    def handle_input(self, event):
        if isinstance(event, tuple) and event:
            if event[0] == "scroll":
                if self.compositor.current.on_input(event):
                    self.compositor.render()
                return
            if event[0] in ("scroll_end", "drag", "drag_end"):
                return

        if event in (Input.ENCODER_CW, Input.ENCODER_CCW):
            up = event == Input.ENCODER_CW
            session = self.app_state.iphone
            session.volume = max(
                0.0,
                min(1.0, (session.volume or 0.0) + (0.0625 if up else -0.0625)),
            )
            self._volume_touch_ts = time.monotonic()
            self.dispatcher.dispatch("media_vol_up" if up else "media_vol_down")
            self.compositor.render()
            return

        if self.compositor.modal is not None:
            self.compositor.handle_input(event)
            return

        if event == Input.SETTINGS:
            self.show_screen(HOME if self.compositor.active == SETTINGS else SETTINGS)
            return
        if event in (Input.BACK, Input.EDGE_BOTTOM):
            self.show_home()
            return
        if event == Input.EDGE_TOP:
            return
        if event in (Input.SWIPE_LEFT, Input.SWIPE_RIGHT):
            current = self.compositor.active
            if current not in NAVIGATION:
                self.show_home()
                return
            index = NAVIGATION.index(current)
            step = 1 if event == Input.SWIPE_RIGHT else -1
            target = NAVIGATION[max(0, min(len(NAVIGATION) - 1, index + step))]
            self.show_screen(target)
            return
        self.compositor.handle_input(event)

    def apply(self, model):
        state = self.app_state
        state.advance_assistant_live()
        session = model.session
        now = time.monotonic()
        transport_connected = bool(
            session.source == "iphone" and session.connected
        )

        if transport_connected and not self._iphone_transport_connected:
            if self._iphone_disconnect_at:
                record_connection_event(
                    "gui_iphone_recovered",
                    outage_ms=round(
                        (now - self._iphone_disconnect_at) * 1000.0,
                        1,
                    ),
                    preserved=bool(now < self._iphone_grace_until),
                )
            self._iphone_transport_connected = True
            self._iphone_disconnect_at = 0.0
        elif not transport_connected and self._iphone_transport_connected:
            self._iphone_transport_connected = False
            self._iphone_disconnect_at = now
            self._iphone_grace_until = now + self._iphone_disconnect_grace
            record_connection_event(
                "gui_iphone_grace_started",
                grace_ms=round(self._iphone_disconnect_grace * 1000.0, 1),
            )

        hold_presentation = bool(
            not transport_connected
            and state.iphone.connected
            and now < self._iphone_grace_until
        )
        state.iphone.connected = bool(transport_connected or hold_presentation)

        if transport_connected:
            if session.title != state.iphone.title:
                if (
                    session.title
                    or not state.iphone.title
                    or now >= self._iphone_grace_until
                ):
                    state.iphone.liked = False
            preserve_stale_metadata = bool(
                not session.title
                and state.iphone.title
                and now < self._iphone_grace_until
            )
            if not preserve_stale_metadata:
                state.iphone.title = session.title
                state.iphone.artist = session.artist
                state.iphone.duration = session.duration
                state.iphone.position = session.elapsed
                state.iphone.playing = session.playing
                state.iphone.supported_commands = set(session.supported_commands)
                if now - self._volume_touch_ts > 0.8:
                    state.iphone.volume = session.volume
                self._iphone_grace_until = 0.0
        elif not hold_presentation:
            if state.iphone.title and self._iphone_grace_until:
                record_connection_event("gui_iphone_grace_expired")
            self._iphone_grace_until = 0.0
            state.iphone.title = ""
            state.iphone.artist = ""
            state.iphone.duration = 0.0
            state.iphone.position = 0.0
            state.iphone.playing = False
            state.iphone.supported_commands = set()

        remote_mic = dict(getattr(model, "remote_mic", {}) or {})
        state.set_remote_mic(
            bool(remote_mic.get("enabled", False)),
            state=remote_mic.get("state"),
            message=remote_mic.get("message"),
        )
        state.notifications = list(model.notifications)
        state.unread_count = len(state.notifications)
        state.clock_text = time.strftime("%H:%M")
        state.device_name = identity_service.visible_name()

    def render(self):
        try:
            self.compositor.broadcast_state(self.app_state)
        except Exception:
            logger.exception("render error")

    def set_pairing_mode(self, enabled, role=None):
        self.app_state.pairing_role = "input"
        self.app_state.pairing_mode = bool(enabled)
        self.compositor.render()

    def show_screen(self, index):
        self.compositor.active = int(index)
        self.compositor.render()

    def show_home(self):
        self.show_screen(HOME)
