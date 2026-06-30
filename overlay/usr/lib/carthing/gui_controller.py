"""Minimal Play Now GUI controller.

The GUI owns presentation and input only. Bluetooth, pairing, and microphone
transport remain in the runtime services.
"""

import logging
import os
import threading
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
    ServerStatusScreen,
    SettingsScreen,
)
from ui_anim import AnimDriver
from ui_screen import (
    Compositor,
    DRMDisplayAdapter,
    Input,
    notification_indicator_visible,
)
from ui_statusbar import StatusBar

logger = logging.getLogger(__name__)

HOME, SETTINGS, NOTIFICATIONS, ASSISTANT, SERVER = 0, 1, 2, 3, 4
NAVIGATION = (HOME, ASSISTANT, NOTIFICATIONS, SERVER)
VIEW_BUTTONS = {
    Input.BTN_1: HOME,
    Input.BTN_2: ASSISTANT,
    Input.BTN_3: NOTIFICATIONS,
    Input.BTN_4: SERVER,
}
WEEKDAYS_RU = ("ПН", "ВТ", "СР", "ЧТ", "ПТ", "СБ", "ВС")


def _freeze_presentation(value):
    if isinstance(value, dict):
        return tuple(
            sorted((str(key), _freeze_presentation(item)) for key, item in value.items())
        )
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_presentation(item) for item in value)
    if isinstance(value, set):
        return tuple(sorted(_freeze_presentation(item) for item in value))
    if hasattr(value, "__dict__"):
        return tuple(
            sorted(
                (name, _freeze_presentation(item))
                for name, item in vars(value).items()
                if not name.startswith("_")
            )
        )
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    return str(value)


class GuiController:
    def __init__(
        self,
        display,
        on_command=None,
        on_pairing=None,
        on_notif_dismiss=None,
        on_notif_action=None,
        on_toggle_notif_blink=None,
        on_toggle_screensaver=None,
        on_set_brightness=None,
        on_set_screensaver_timeout=None,
        on_power_off=None,
        on_toggle_client=None,
        **_unused,
    ):
        self.app_state = AppState()
        self._on_notif_dismiss = on_notif_dismiss or (lambda uid: None)
        self._on_notif_action = on_notif_action or (lambda payload: None)
        self._volume_touch_ts = 0.0
        self._iphone_transport_connected = False
        self._iphone_grace_until = 0.0
        self._iphone_disconnect_at = 0.0
        self._iphone_disconnect_grace = max(
            0.0,
            float(os.environ.get("CARTHING_IPHONE_UI_GRACE_S", "3.0")),
        )
        self._render_lock = threading.Lock()
        self._render_pending = False
        self._last_presentation_key = None

        self.dispatcher = Dispatcher(
            self.app_state,
            on_command=on_command,
            on_pairing=on_pairing,
            on_toggle_notif_blink=on_toggle_notif_blink,
            on_toggle_screensaver=on_toggle_screensaver,
            on_set_brightness=on_set_brightness,
            on_set_screensaver_timeout=on_set_screensaver_timeout,
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
                ServerStatusScreen(),
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
        elif intent == "notif_action":
            self._on_notif_action(payload)
        elif intent == "notif_select":
            self.compositor.screens[NOTIFICATIONS].select(payload)
            self.render()
        elif intent == "settings_tap":
            self.compositor.screens[SETTINGS].tap(payload)
            self.render()
        else:
            self.dispatcher.dispatch(intent, payload)
            self.render()

    def needs_fast_render(self):
        state = self.app_state
        anim = getattr(self.compositor, "anim", None)
        transition_active = bool(
            anim is not None and getattr(anim, "transition_active", False)
        )
        assistant_ambient = bool(
            anim is not None
            and self.compositor.active == ASSISTANT
            and anim.needs_tick()
        )
        return bool(
            (
                self.compositor.active == ASSISTANT
                and state.assistant_live_text != state.assistant_live_target
            )
            or transition_active
            or assistant_ambient
        )

    def handle_input(self, event):
        if isinstance(event, tuple) and event:
            if event[0] == "scroll":
                if self.compositor.current.on_input(event):
                    self.render()
                return
            if event[0] in ("scroll_end", "drag", "drag_end"):
                return

        if event in VIEW_BUTTONS:
            self.show_screen(VIEW_BUTTONS[event])
            return

        if event == Input.PRESS:
            if self.compositor.active != ASSISTANT:
                self.show_screen(ASSISTANT)
                self.dispatcher.dispatch("remote_mic_set", True)
            else:
                self.dispatcher.dispatch("remote_mic_toggle")
            self.render()
            return

        if event in (Input.ENCODER_CW, Input.ENCODER_CCW):
            up = event == Input.ENCODER_CW
            session = self.app_state.iphone
            step = 0.025 if self.app_state.remote_media_active else 0.0625
            session.volume = max(
                0.0,
                min(1.0, (session.volume or 0.0) + (step if up else -step)),
            )
            self._volume_touch_ts = time.monotonic()
            self.dispatcher.dispatch("media_vol_up" if up else "media_vol_down")
            self.render()
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
            self.show_screen(NOTIFICATIONS)
            return
        if event in (Input.SWIPE_LEFT, Input.SWIPE_RIGHT):
            current = self.compositor.active
            if current not in NAVIGATION:
                self.show_home()
                return
            index = NAVIGATION.index(current)
            step = 1 if event == Input.SWIPE_LEFT else -1
            target = NAVIGATION[max(0, min(len(NAVIGATION) - 1, index + step))]
            if target == current:
                return
            if current == ASSISTANT and self.app_state.remote_mic_enabled:
                self.dispatcher.dispatch("remote_mic_set", False)
            direction = 1 if event == Input.SWIPE_LEFT else -1
            self.compositor.animate_switch(target, direction)
            return
        self.compositor.handle_input(event)

    def _presentation_key(self):
        state = self.app_state
        compositor = getattr(self, "compositor", None)
        active = (
            compositor.active if compositor is not None else state.active_desktop
        )
        modal = (
            type(compositor.modal).__name__
            if compositor is not None and compositor.modal is not None
            else None
        )
        session = state.iphone
        incoming_call = next(
            (
                item
                for item in reversed(state.notifications)
                if str(item.get("category") or "") == "IncomingCall"
            ),
            None,
        )
        visible_state = {
            "active_screen": active,
            "modal": modal,
            "encoder_volume": round(float(session.volume or 0.0), 3),
            "remote_media_active": state.remote_media_active,
            "clock_text": state.clock_text,
            "clock_date_text": state.clock_date_text,
            "screensaver_active": state.screensaver_active,
            "notification_indicator_visible": notification_indicator_visible(
                state.unread_count, state.notif_blink
            ),
            "incoming_call": incoming_call,
            "pairing_mode": state.pairing_mode,
            "pairing_message": state.pairing_message,
            "power_unplug_status": state.power_unplug_status,
            "power_unplug_message": state.power_unplug_message,
        }
        if active == HOME:
            if session.title:
                visible_state["iphone"] = {
                    "connected": session.connected,
                    "app_name": session.app_name,
                    "title": session.title,
                    "artist": session.artist,
                    "duration": round(float(session.duration or 0.0), 1),
                    "position_second": int(float(session.position or 0.0)),
                    "playing": session.playing,
                    "supported_commands": session.supported_commands,
                    "liked": session.liked,
                }
            else:
                visible_state["iphone"] = {
                    "connected": session.connected,
                }
        elif active == ASSISTANT:
            transcript = list(state.assistant_transcript or [])[-3:]
            visible_state["assistant"] = {
                "remote_mic_enabled": state.remote_mic_enabled,
                "remote_mic_state": state.remote_mic_state,
                "remote_mic_message": state.remote_mic_message,
                "status": state.assistant_status,
                "transcript": tuple(str(item)[-500:] for item in transcript),
                "live_text": str(state.assistant_live_text)[-500:],
                "live_target": str(state.assistant_live_target)[-500:],
            }
        elif active == NOTIFICATIONS:
            visible_state["notifications"] = state.notifications
        elif active == SERVER:
            visible_state["server_status"] = state.server_status
        else:
            visible_state["settings"] = {
                "iphone_connected": session.connected,
                "screen_brightness": state.screen_brightness,
                "screensaver_enabled": state.screensaver_enabled,
                "screen_off_sec": state.screen_off_sec,
                "notif_blink": state.notif_blink,
                "device_name": state.device_name,
            }
        return _freeze_presentation(visible_state)

    def apply(self, model):
        state = self.app_state
        if getattr(self, "compositor", None) is not None:
            assistant_visible = self.compositor.active == ASSISTANT
        else:
            assistant_visible = state.active_desktop == ASSISTANT
        if assistant_visible:
            state.advance_assistant_live()
        elif state.assistant_live_text != state.assistant_live_target:
            state.assistant_live_text = state.assistant_live_target
            state._assistant_typewriter_credit = 0.0
            state._assistant_typewriter_at = time.monotonic()
        session = model.session
        state.remote_media_active = bool(model.remote_media_active)
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
                state.iphone.app_name = session.app_name
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
            state.iphone.app_name = ""
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
        state.server_status = dict(getattr(model, "server_status", {}) or {})
        state.clock_text = time.strftime("%H:%M")
        local_time = time.localtime()
        state.clock_date_text = (
            f"{WEEKDAYS_RU[local_time.tm_wday]} · "
            f"{local_time.tm_mday:02d}.{local_time.tm_mon:02d}"
        )
        state.device_name = identity_service.visible_name()
        presentation_key = self._presentation_key()
        changed = presentation_key != getattr(self, "_last_presentation_key", None)
        self._last_presentation_key = presentation_key
        return changed

    def render(self):
        if not self._render_lock.acquire(blocking=False):
            self._render_pending = True
            return False
        started = time.monotonic()
        try:
            while True:
                self._render_pending = False
                self.compositor.broadcast_state(self.app_state)
                if not self._render_pending:
                    break
        except Exception:
            logger.exception("render error")
        finally:
            self._render_lock.release()
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if elapsed_ms > 50.0:
            logger.warning("slow GUI render: %.1fms screen=%s", elapsed_ms, self.compositor.active)
        return True

    def set_pairing_mode(self, enabled, role=None):
        self.app_state.pairing_role = "input"
        self.app_state.pairing_mode = bool(enabled)
        self.render()

    def show_screen(self, index):
        index = int(index)
        previous = self.compositor.active
        leaving_assistant = (
            previous == ASSISTANT and index != ASSISTANT
        )
        if leaving_assistant and self.app_state.remote_mic_enabled:
            self.dispatcher.dispatch("remote_mic_set", False)
        self.compositor.active = index
        if index != previous:
            logger.info("GUI screen -> %s", index)
        self.render()

    def show_home(self):
        self.show_screen(HOME)
