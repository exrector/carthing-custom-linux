"""gui_controller — один home-surface + views поверх проверенного Compositor-субстрата.

gui-contract.md / architecture.md §GUI Contract. GUI — слой представления и intents для
ОДНОГО рантайма. Views (now_playing/routes/devices/notifications/system) НЕ меняют BT-роль,
маршрут, сопряжение или источник — переключение view это только смена представления.
GUI НЕ владеет BT/scanner/pairing/audio — лишь читает RuntimeModel и шлёт intents в сервисы.

Это тонкий координатор: строит Compositor (порт _build_compositor), мостит RuntimeModel→AppState
(живой прогресс на каждый тик), роутит ввод. Колбэки intents инъектируются (carthing_runtime
подключает их к accessory_orchestrator / iphone_service / transfer_service).
"""

import logging
import time

import identity_service
from app_state import AppState
from intents import Dispatcher
from ui_screen import Compositor, DRMDisplayAdapter
from ui_statusbar import StatusBar
from ui_anim import AnimDriver
from screens import (
    NowPlayingScreen, MacOSScreen, TransferScreen, SettingsScreen,
    NotificationsScreen, PairingModal,
)

logger = logging.getLogger(__name__)


class GuiController:
    def __init__(self, display, on_command=None, on_pairing=None,
                 on_transfer_rescan=None, on_transfer_select=None):
        self.app_state = AppState()
        self.dispatcher = Dispatcher(
            self.app_state,
            on_command=on_command or (lambda *a, **k: None),
            on_transfer_rescan=on_transfer_rescan or (lambda *a, **k: None),
            on_transfer_select=on_transfer_select or (lambda *a, **k: None),
            on_pairing=on_pairing or (lambda *a, **k: None),
        )
        emit = self.dispatcher.dispatch
        screens = [
            NowPlayingScreen(emit=emit),                                          # 0 now_playing
            MacOSScreen(emit=emit),                                               # 1 (mac source)
            TransferScreen(emit=emit),                                            # 2 routes
            SettingsScreen(on_select=lambda key: emit("settings_select", key)),   # 3 devices/system
            NotificationsScreen(),                                                # 4 notifications
        ]
        self.compositor = Compositor(
            DRMDisplayAdapter(display), screens,
            status_bar=StatusBar(), anim=AnimDriver(),
            state=self.app_state, on_intent=emit,
            pairing_modal=PairingModal(emit=emit),
        )

    # ── RuntimeModel -> AppState (вызывать каждый рендер-тик: живой прогресс) ──
    def apply(self, model):
        a = self.app_state
        s = model.session
        a.iphone.connected = (s.source == "iphone" and s.connected)
        if a.iphone.connected:
            a.iphone.title = s.title
            a.iphone.artist = s.artist
            a.iphone.duration = s.duration
            a.iphone.position = s.elapsed      # ЖИВОЙ (экстраполяция в runtime_model)
            a.iphone.playing = s.playing
            a.iphone.volume = s.volume
        else:
            a.iphone.title = a.iphone.artist = ""
            a.iphone.duration = a.iphone.position = 0.0
            a.iphone.playing = False
        a.unread_count = model.notif_count
        a.notifications = (
            [{"app": "iPhone", "title": model.notif_last, "message": ""}]
            if model.notif_last else []
        )
        a.transfer_active = model.transfer_active
        a.transfer_source = model.speaker_name or ""
        a.clock_text = time.strftime("%H:%M")
        a.device_name = identity_service.visible_name()

    def render(self):
        try:
            self.compositor.render()
        except Exception as e:
            logger.error("render error: %s", e)

    def handle_input(self, event):
        self.compositor.handle_input(event)

    def set_pairing_mode(self, on: bool):
        self.app_state.pairing_mode = bool(on)
