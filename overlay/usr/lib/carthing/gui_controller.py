"""gui_controller — ОДНА home-поверхность, без свайпа по «рабочим столам».

Раньше был свайп-ринг из 5 десктопов (iPhone/Mac/Transfer/Settings/Notifications) — пользователь
заколебался не понимать, куда смотреть. Теперь: ВСЕГДА видно ОДИН home (now_playing + бар +
дуга громкости + виджет ассистента). Settings — по физической кнопке (push), Notifications — по
тапу индикатора; возврат — Back. Никакого горизонтального свайпа между столами.

GUI — слой представления/intents для одного рантайма. Не владеет BT/pairing/audio; читает
RuntimeModel, шлёт intents в сервисы (инъекция колбэков из carthing_runtime).
"""

import asyncio
import logging
import time

import identity_service
import ui_theme as T
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
        self._shade_task = None        # единственный рендер-тикер шторки (~60fps)
        self._snap = None              # None = следуем за пальцем; иначе доводка
        self._last_scroll_render = 0.0

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
        if intent == "notif_select":                # тап по блоку = выбрать (для свайп-очистки)
            self.compositor.screens[NOTIF].select(payload)
            self.compositor.render()
            return
        if intent == "settings_tap":                # тап по строке Settings = выбрать+активировать
            self.compositor.screens[SETTINGS].tap(payload)
            self.compositor.render()
            return
        self.dispatcher.dispatch(intent, payload)   # медиа/transfer/pairing

    def needs_fast_render(self):
        """Рендер-циклу рантайма: пока активна шторка, экраном владеет ОТДЕЛЬНЫЙ тикер
        (_shade_loop) — основной цикл не должен рисовать (иначе двойной рендер/гонка)."""
        return self.compositor.shade_active

    # ── интерактивная шторка (game-loop: касание ТОЛЬКО двигает p, рисует тикер) ──
    def _on_drag(self, kind, finger_y):
        # НИЖНИЙ край шторки = позиция пальца по вертикали (абсолютная) -> едет ровно за пальцем
        p = max(0.0, min(1.0, finger_y / float(T.H)))
        if kind == "open":
            if self.compositor.active == NOTIF:
                return                                  # уже открыто
            if not self.compositor.shade_active:
                self.compositor.begin_shade(self.compositor.active, NOTIF, p)
        else:  # close
            if self.compositor.active != NOTIF:
                return                                  # нечего закрывать
            if not self.compositor.shade_active:
                self.compositor.begin_shade(HOME, NOTIF, p)
        self.compositor.update_shade(p)
        self._snap = None                               # следуем за пальцем (без доводки)
        self._ensure_shade_task()

    def _on_drag_end(self, kind, offset):
        if not self.compositor.shade_active:
            # быстрый флик без промежуточных кадров — мгновенно по порогу
            if offset >= 100:
                if kind == "open" and self.compositor.active != NOTIF:
                    self.compositor.active = NOTIF; self.compositor.render()
                elif kind == "close" and self.compositor.active == NOTIF:
                    self.compositor.active = HOME; self.compositor.render()
            return
        p = self.compositor._shade["p"]
        self._snap = {"start": p, "target": 1.0 if p > 0.4 else 0.0,
                      "t0": time.monotonic(), "dur": 0.14}
        self._ensure_shade_task()

    def _ensure_shade_task(self):
        if self._shade_task is None or self._shade_task.done():
            self._shade_task = asyncio.ensure_future(self._shade_loop())

    async def _shade_loop(self):
        """ЕДИНСТВЕННЫЙ рендер-тикер шторки ~60fps: рисует последнее p (за пальцем),
        а на отпускании — доводит по ease-out. Касания сюда p только ПИШУТ, не рисуют."""
        try:
            while self.compositor.shade_active:
                if self._snap is not None:                  # доводка к открытой/закрытой
                    s = self._snap
                    k = (time.monotonic() - s["t0"]) / s["dur"]
                    if k >= 1.0:
                        self.compositor.update_shade(s["target"])
                        self.compositor.render()
                        self.compositor.active = NOTIF if s["target"] >= 0.5 else HOME
                        self.compositor.end_shade()
                        self._snap = None
                        break
                    ease = 1 - (1 - k) ** 3
                    self.compositor.update_shade(s["start"] + (s["target"] - s["start"]) * ease)
                self.compositor.render()
                await asyncio.sleep(0.016)
        finally:
            # подстраховка: если вышли с активной шторкой без снапа — закрыть аккуратно
            if self.compositor.shade_active and self._snap is None:
                self.compositor.end_shade()
                self.compositor.render()

    def _on_scroll(self, delta):
        """Пиксельный скролл активного вью «за пальцем» (троттлинг рендера ~30fps)."""
        if self.compositor.current.on_input(("scroll", delta)):
            now = time.monotonic()
            if now - self._last_scroll_render >= 0.03:
                self._last_scroll_render = now
                self.compositor.render()

    def handle_input(self, event):
        if isinstance(event, tuple) and event:
            if event[0] == "drag":
                self._on_drag(event[1], event[2]); return
            if event[0] == "drag_end":
                self._on_drag_end(event[1], event[2]); return
            if event[0] == "scroll":
                self._on_scroll(event[1]); return
        # ЭНКОДЕР (вращение) = ГРОМКОСТЬ ВСЕГДА, на любом вью (физический регулятор).
        if event in (Input.ENCODER_CW, Input.ENCODER_CCW):
            up = event == Input.ENCODER_CW
            cs = self.app_state.control_source            # оптимистично двигаем дугу сразу
            if cs is not None:
                cs.volume = max(0.0, min(1.0, (cs.volume or 0.0) + (0.05 if up else -0.05)))
            self.dispatcher.dispatch("media_vol_up" if up else "media_vol_down")
            self.compositor.render()
            return
        if event == Input.SETTINGS:
            self.compositor.active = SETTINGS
            self.compositor.render()
            return
        if event == Input.BACK:
            if self._notif_step_back():             # из развёрнутой карточки -> к списку
                return
            if self.compositor.active != HOME:
                self.compositor.active = HOME
                self.compositor.render()
            return
        # Жест ОТ ВЕРХНЕГО КРАЯ вниз -> открыть уведомления (как «шторка» iOS).
        if event == Input.EDGE_TOP:
            if self.compositor.active != NOTIF:
                self.compositor.active = NOTIF
                self.compositor.render()
            return
        # Жест ОТ НИЖНЕГО КРАЯ вверх -> сначала свернуть карточку, потом закрыть вью на home.
        if event == Input.EDGE_BOTTOM:
            if self._notif_step_back():
                return
            if self.compositor.active != HOME:
                self.compositor.active = HOME
                self.compositor.render()
            return
        if event in (Input.SWIPE_LEFT, Input.SWIPE_RIGHT):
            # свайп-влево в списке уведомлений = очистить выбранное; иначе игнор.
            if event == Input.SWIPE_LEFT and self.compositor.active == NOTIF:
                if self.compositor.current.on_input(event):
                    self.compositor.render()
            return
        # Средние свайпы вверх/вниз (и энкодер) -> прокрутка активного вью.
        self.compositor.handle_input(event)

    def _notif_step_back(self):
        """Если открыта развёрнутая карточка уведомления — свернуть её к списку (True)."""
        scr = self.compositor.screens[NOTIF]
        if self.compositor.active == NOTIF and getattr(scr, "detail_uid", None) is not None:
            scr.close_detail()
            self.compositor.render()
            return True
        return False

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
