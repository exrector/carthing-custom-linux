"""gui_controller — ОДНА home-поверхность, без свайпа по «рабочим столам».

Раньше был свайп-ринг из 5 десктопов (iPhone/Mac/Transfer/Settings/Notifications) — пользователь
заколебался не понимать, куда смотреть. Теперь: ВСЕГДА видно ОДИН home (now_playing + бар +
дуга громкости + виджет ассистента). Settings — по физической кнопке (push), Notifications — по
тапу индикатора; возврат — Back. Никакого горизонтального свайпа между столами.

GUI — слой представления/intents для одного рантайма. Не владеет BT/pairing/audio; читает
RuntimeModel, шлёт intents в сервисы (инъекция колбэков из carthing_runtime).
"""

import logging
import time

import identity_service
from app_state import AppState
from intents import Dispatcher
from ui_screen import Compositor, DRMDisplayAdapter, Input
from ui_statusbar import StatusBar
from ui_anim import AnimDriver
from screens import NowPlayingScreen, SettingsScreen, NotificationsScreen, PairingModal

logger = logging.getLogger(__name__)

HOME, SETTINGS, NOTIF = 0, 1, 2   # индексы экранов (home всегда базовый)


class GuiController:
    def __init__(self, display, on_command=None, on_pairing=None,
                 on_transfer_rescan=None, on_transfer_select=None, on_notif_dismiss=None):
        self.app_state = AppState()
        self._on_notif_dismiss = on_notif_dismiss or (lambda uid: None)
        self.dispatcher = Dispatcher(
            self.app_state,
            on_command=on_command or (lambda *a, **k: None),
            on_transfer_rescan=on_transfer_rescan or (lambda *a, **k: None),
            on_transfer_select=on_transfer_select or (lambda *a, **k: None),
            on_pairing=on_pairing or (lambda *a, **k: None),
        )
        emit = self.dispatcher.dispatch
        screens = [
            NowPlayingScreen(emit=emit),                                          # 0 HOME
            SettingsScreen(on_select=lambda key: emit("settings_select", key)),   # 1 (по кнопке)
            NotificationsScreen(emit=self._nav_intent),                           # 2 (свайп вниз)
        ]
        self.compositor = Compositor(
            DRMDisplayAdapter(display), screens,
            status_bar=StatusBar(), anim=AnimDriver(),
            state=self.app_state, on_intent=self._nav_intent,
            show_dots=False,                       # без точек-десктопов: один home
            pairing_modal=PairingModal(emit=emit),
        )
        self.app_state.active_desktop = HOME
        self._prev_iphone_connected = False

    # ── навигация: один home + push Settings/Notifications, без свайпа ────────
    def _nav_intent(self, intent, payload=None):
        if intent == StatusBar.INTENT_NOTIFICATIONS:
            self.compositor.active = NOTIF
            self.compositor.render()
            return
        if intent == StatusBar.INTENT_ASSISTANT:
            logger.info("assistant tap (Фаза 5 — логика позже)")
            return
        if intent == "notif_dismiss":
            self._on_notif_dismiss(payload)         # payload = uid; очистить и на iPhone
            return
        if intent == "notif_select":                # тап по строке уведомления = выбрать её
            self.compositor.screens[NOTIF].select(payload)
            self.compositor.render()
            return
        if intent == "settings_tap":                # тап по строке Settings = выбрать+активировать
            self.compositor.screens[SETTINGS].tap(payload)
            self.compositor.render()
            return
        self.dispatcher.dispatch(intent, payload)   # медиа/transfer/pairing

    def handle_input(self, event):
        if event == Input.SETTINGS:
            self.compositor.active = SETTINGS
            self.compositor.render()
            return
        if event == Input.BACK:
            if self.compositor.active != HOME:
                self.compositor.active = HOME
                self.compositor.render()
            return
        if event in (Input.SWIPE_LEFT, Input.SWIPE_RIGHT):
            # свайп-влево в списке уведомлений = очистить выбранное (прямо в экран, минуя
            # переключение столов, которого больше нет); иначе игнор.
            if event == Input.SWIPE_LEFT and self.compositor.active == NOTIF:
                if self.compositor.current.on_input(event):
                    self.compositor.render()
            return
        # Свайп вниз на home -> уведомления (как «шторка» iOS); вверх в уведомлениях -> назад.
        if event == Input.SWIPE_DOWN and self.compositor.active == HOME:
            self.compositor.active = NOTIF
            self.compositor.render()
            return
        if event == Input.SWIPE_UP and self.compositor.active == NOTIF:
            self.compositor.active = HOME
            self.compositor.render()
            return
        self.compositor.handle_input(event)

    # ── RuntimeModel -> AppState (каждый рендер-тик: живой прогресс) ──────────
    def apply(self, model):
        a = self.app_state
        s = model.session
        a.iphone.connected = (s.source == "iphone" and s.connected)
        if a.iphone.connected and not self._prev_iphone_connected:
            a.active_desktop = HOME                 # подключился iPhone -> на home
        self._prev_iphone_connected = a.iphone.connected
        if a.iphone.connected:
            if s.title != a.iphone.title:          # смена трека -> сбросить локальный «лайк»
                a.iphone.liked = False
            a.iphone.title = s.title
            a.iphone.artist = s.artist
            a.iphone.duration = s.duration
            a.iphone.position = s.elapsed
            a.iphone.playing = s.playing
            a.iphone.volume = s.volume
            a.iphone.supported_commands = set(s.supported_commands)
        else:
            a.iphone.title = a.iphone.artist = ""
            a.iphone.duration = a.iphone.position = 0.0
            a.iphone.playing = False
            a.iphone.supported_commands = set()
        a.notifications = list(model.notifications)   # [{uid, app, text}] — без iPhone/заголовков
        a.unread_count = len(a.notifications)
        # Зарегистрировать iPhone как доверенный ИСТОЧНИК (чтобы он попал в Settings→Доверенные).
        self._sync_trusted_iphone(a, a.iphone.connected, model.session.peer)
        a.transfer_active = model.transfer_active
        a.transfer_source = model.speaker_name or ""
        a.clock_text = time.strftime("%H:%M")
        a.device_name = identity_service.visible_name()

    def _sync_trusted_iphone(self, a, connected, peer=None):
        """iPhone (BLE-bonded источник) -> в список доверенных как role=source.
        In-memory: переисточается при подключении, BLE-бонд персистентен сам по себе."""
        entry = next((d for d in a.trusted if d.get("key") == "iphone"), None)
        if entry is None:
            if connected:
                a.trusted.append({"key": "iphone", "label": "iPhone", "type": "iPhone",
                                  "role": "source", "online": True, "connected": True,
                                  "address": peer or ""})
        else:
            entry["connected"] = bool(connected)
            # У источника нет сигнала «онлайн, но не подключён» -> online == connected
            # (отключён = offline = красный, не залипает жёлтым). Жёлтый — только для динамиков.
            entry["online"] = bool(connected)
            if connected and peer:
                entry["address"] = peer

    def render(self):
        try:
            self.compositor.broadcast_state(self.app_state)
        except Exception as e:
            logger.error("render error: %s", e)

    def set_pairing_mode(self, on: bool):
        self.app_state.pairing_mode = bool(on)
