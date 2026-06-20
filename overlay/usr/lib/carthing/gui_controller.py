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
from screens import (
    MacOSScreen,
    NowPlayingScreen,
    SettingsScreen,
    RouteBuilderScreen,
    NotificationsScreen,
    PairingModal,
)

logger = logging.getLogger(__name__)

HOME, SETTINGS, NOTIF, SESSIONS, ROUTER, MAC = 0, 1, 2, 3, 4, 5
MODES = SESSIONS      # compatibility alias
TRANSFER = ROUTER    # compatibility alias


class GuiController:
    def __init__(self, display, on_command=None, on_pairing=None,
                 on_transfer_rescan=None, on_transfer_select=None, on_speaker_pair_select=None,
                 on_trusted_remove=None, on_notif_dismiss=None,
                 on_session_select=None, on_route_input_select=None,
                 on_route_output_select=None, on_route_activate=None, on_route_check=None,
                 on_route_view_open=None, on_toggle_sleep=None, on_set_off_timeout=None,
                 on_toggle_notif_blink=None, on_set_brightness=None, on_set_theme=None,
                 on_power_off=None, on_set_mode=None, on_toggle_client=None):
        self.app_state = AppState()
        self._on_notif_dismiss = on_notif_dismiss or (lambda uid: None)
        self.dispatcher = Dispatcher(
            self.app_state,
            on_command=on_command or (lambda *a, **k: None),
            on_transfer_rescan=on_transfer_rescan or (lambda *a, **k: None),
            on_transfer_select=on_transfer_select or (lambda *a, **k: None),
            on_speaker_pair_select=on_speaker_pair_select or (lambda *a, **k: None),
            on_trusted_remove=on_trusted_remove or (lambda *a, **k: None),
            on_pairing=on_pairing or (lambda *a, **k: None),
            on_session_select=on_session_select,
            on_route_input_select=on_route_input_select,
            on_route_output_select=on_route_output_select,
            on_route_activate=on_route_activate,
            on_route_check=on_route_check,
            on_route_view_open=on_route_view_open,
            on_toggle_sleep=on_toggle_sleep or (lambda *a, **k: None),   # [CLAUDE] сон экрана
            on_set_off_timeout=on_set_off_timeout or (lambda *a, **k: None),  # [CLAUDE] ±тайм-аут
            on_toggle_notif_blink=on_toggle_notif_blink or (lambda *a, **k: None),  # [CLAUDE] моргание уведомл.
            on_set_brightness=on_set_brightness or (lambda pct: None),  # [CLAUDE 2026-06-10] яркость
            on_set_theme=on_set_theme or (lambda name: None),  # [CLAUDE 2026-06-11] тема UI
            on_power_off=on_power_off or (lambda: None),
            on_set_mode=on_set_mode or (lambda mode: None),
            on_toggle_client=on_toggle_client or (lambda on: None),
        )
        emit = self.dispatcher.dispatch
        screens = [
            NowPlayingScreen(emit=emit),                                          # 0 HOME
            SettingsScreen(on_select=lambda key: emit("settings_select", key)),   # 1 (по кнопке)
            NotificationsScreen(emit=self._nav_intent),                           # 2 (свайп вниз)
            RouteBuilderScreen(emit=emit),                                         # 3 (был SessionsScreen — режимы удалены; слот сохранён, чтобы не сдвигать индексы)
            RouteBuilderScreen(emit=emit),                                         # 4
            MacOSScreen(emit=emit),                                                # 5 (режим macOS)
        ]
        self.compositor = Compositor(
            DRMDisplayAdapter(display), screens,
            status_bar=StatusBar(), anim=AnimDriver(),
            state=self.app_state, on_intent=self._nav_intent,
            show_dots=True,                        # [CLAUDE] 3 точки-индикатора: ‹Маршруты · Play Now · Уведомления›
            nav_order=[ROUTER, HOME, NOTIF],        # [CLAUDE 2026-06-03] слева-направо: Маршруты | Play Now | Уведомления
            pairing_modal=PairingModal(emit=emit),
        )
        self.app_state.active_desktop = HOME
        self._prev_iphone_connected = False
        self._prev_pairing_mode = False             # [CLAUDE] для возврата на Routes после пары
        self._shade_task = None        # единственный рендер-тикер шторки (~60fps)
        self._anim_task = None         # [CLAUDE] тикер слайда вью (~60fps)
        self._snap = None              # None = следуем за пальцем; иначе доводка
        self._scroll_task = None       # единый scroll render/inertia ticker для всех экранов
        self._scroll_velocity = 0.0
        self._scroll_dirty = False
        self._last_scroll_render = 0.0
        self._view_stack = []

    def _enter_route_view(self):
        self.dispatcher.dispatch("route_view_open")

    # ── навигация: один home + push Settings/Notifications, без свайпа ────────
    def _nav_intent(self, intent, payload=None):
        if intent == StatusBar.INTENT_NOTIFICATIONS:
            self._push_view(self.compositor.active)
            self.compositor.active = NOTIF
            self.compositor.render()
            return
        if intent == "open_settings":               # [CLAUDE 2026-06-03] круглая кнопка в Routes -> Настройки
            if self.compositor.active == SETTINGS:      # [CLAUDE 2026-06-11] повторно = закрыть
                self._handle_back()
                return
            self._push_view(self.compositor.active)
            self.compositor.active = SETTINGS
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
            old_active = self.compositor.active
            self.compositor.screens[SETTINGS].tap(payload)
            new_active = self.compositor.active
            if old_active == SETTINGS and new_active != SETTINGS:
                self._push_view(SETTINGS)
            self.compositor.render()
            return
        if intent in ("screen_off_adjust", "display_adjust"):   # [CLAUDE 2026-06-11] единые −/+
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()
            return
        if intent == "speaker_pair_select":
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()
            return
        if intent == "trusted_remove":
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()
            return
        if intent in (
            "route_input_select", "route_output_select", "route_step",
            "route_transport_select", "route_next", "route_back", "route_check",
        ):
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()
            return
        if intent == "route_activate":
            self.dispatcher.dispatch(intent, payload)
            self.compositor.render()
            return
        self.dispatcher.dispatch(intent, payload)   # медиа/transfer/pairing

    def needs_fast_render(self):
        """Рендер-циклу рантайма: пока активна шторка, экраном владеет ОТДЕЛЬНЫЙ тикер
        (_shade_loop) — основной цикл не должен рисовать (иначе двойной рендер/гонка).
        Также во время слайда вью экраном владеет _anim_loop."""
        anim = getattr(self.compositor, "anim", None)
        return self.compositor.shade_active or bool(anim and anim.transition_active)

    def _ensure_anim_task(self):
        if getattr(self, "_anim_task", None) is None or self._anim_task.done():
            self._anim_task = asyncio.ensure_future(self._anim_loop())

    async def _anim_loop(self):
        """[CLAUDE 2026-06-02] Тикер слайда вью ~60fps: двигает transition_progress и рисует
        кадры, пока переход активен. Завершается финальным кадром без transition."""
        anim = getattr(self.compositor, "anim", None)
        try:
            while anim is not None and anim.transition_active:
                anim.tick()
                self.compositor.render()
                await asyncio.sleep(0.016)
        finally:
            self.compositor.render()

    # ── интерактивная шторка (game-loop: касание ТОЛЬКО двигает p, рисует тикер) ──
    def _on_drag(self, kind, finger_y):
        # [CLAUDE 2026-06-03] Верхняя шторка убрана: открытие drag-ом сверху игнорируем
        # (уведомления — отдельный свайп-вью справа).
        if kind == "open":
            return
        # НИЖНИЙ край шторки = позиция пальца по вертикали (абсолютная) -> едет ровно за пальцем
        p = max(0.0, min(1.0, finger_y / float(T.H)))
        if False:
            pass
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
                if kind == "open":
                    return                              # [CLAUDE 2026-06-03] верхняя шторка убрана
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

    def _scrollable_screen(self):
        if self.compositor.modal is not None:
            return self.compositor.modal
        return self.compositor.current

    def _apply_scroll_delta(self, delta):
        screen = self._scrollable_screen()
        before = getattr(screen, "scroll_y", None)
        handled = screen.on_input(("scroll", delta))
        after = getattr(screen, "scroll_y", None)
        if not handled:
            return False
        changed = before is None or after is None or abs(after - before) >= 0.01
        if changed:
            self._scroll_dirty = True
        return changed

    def _ensure_scroll_task(self):
        if self._scroll_task is None or self._scroll_task.done():
            self._scroll_task = asyncio.ensure_future(self._scroll_loop())

    def _cancel_scroll_inertia(self):
        self._scroll_velocity = 0.0
        if self._scroll_task is not None and not self._scroll_task.done():
            self._scroll_task.cancel()
        self._scroll_dirty = False

    def _on_scroll(self, delta):
        """Пиксельный скролл активного вью «за пальцем»."""
        self._scroll_velocity = 0.0                         # новый палец отменяет старую инерцию
        if self._apply_scroll_delta(delta):
            self._ensure_scroll_task()

    def _on_scroll_end(self, velocity):
        """Единая инерция scroll-view после отпускания пальца."""
        # [CLAUDE 2026-06-11] мягче: порог ниже (инерция чаще подхватывает),
        # потолок ниже (без «улёта» списка)
        if abs(velocity) < 120:
            return
        self._scroll_velocity = max(-2000.0, min(2000.0, float(velocity)))
        self._ensure_scroll_task()

    async def _scroll_loop(self):
        last = time.monotonic()
        try:
            while self._scroll_dirty or abs(self._scroll_velocity) >= 20:
                now = time.monotonic()
                dt = min(0.04, max(0.001, now - last))
                last = now
                if abs(self._scroll_velocity) >= 20:
                    delta = self._scroll_velocity * dt
                    if not self._apply_scroll_delta(delta):
                        self._scroll_velocity = 0.0
                    else:
                        self._scroll_velocity *= 0.94 ** (dt / 0.016)  # [CLAUDE 2026-06-11] плавнее затухание
                if self._scroll_dirty:
                    self._last_scroll_render = now
                    self._scroll_dirty = False
                    self.compositor.render()
                await asyncio.sleep(0.016)
        finally:
            self._scroll_velocity = 0.0
            self._scroll_dirty = False

    def handle_input(self, event):
        if isinstance(event, tuple) and event:
            if event[0] == "drag":
                self._cancel_scroll_inertia()
                self._on_drag(event[1], event[2]); return
            if event[0] == "drag_end":
                self._on_drag_end(event[1], event[2]); return
            if event[0] == "scroll":
                self._on_scroll(event[1]); return
            if event[0] == "scroll_end":
                self._on_scroll_end(event[1]); return
        # ЭНКОДЕР (вращение) = ГРОМКОСТЬ ВСЕГДА, на любом вью (физический регулятор).
        if event in (Input.ENCODER_CW, Input.ENCODER_CCW):
            up = event == Input.ENCODER_CW
            cs = self.app_state.control_source            # оптимистично двигаем дугу сразу
            if cs is not None:
                # Шаг = 1/16 (нативный шаг громкости iOS) — меньше дрейф при сверке с AMS.
                cs.volume = max(0.0, min(1.0, (cs.volume or 0.0) + (0.0625 if up else -0.0625)))
            # Окно подавления: пока крутят — AMS-подтверждения НЕ затирают дугу
            # (запоздавшие vol% откатывали её назад = «дребезг насечек», 2026-06-10).
            self._volume_touch_ts = time.monotonic()
            self.dispatcher.dispatch("media_vol_up" if up else "media_vol_down")
            self.compositor.render()
            return
        # [CLAUDE 2026-06-02] Если открыт модал (полноэкранный сканер сопряжения) — ВСЕ события
        # (Back/Press/Tap) идут в него, а не в навигацию вьюх. Иначе из сканера было не выйти:
        # _handle_back перехватывал Back до модала. Энкодер (выше) остаётся громкостью.
        if self.compositor.modal is not None:
            self.compositor.handle_input(event)
            return
        if event == Input.SETTINGS:
            self._cancel_scroll_inertia()
            if self.compositor.active == SETTINGS:
                # [CLAUDE 2026-06-11] повторное нажатие кнопки настроек = закрыть их
                self._handle_back()
                return
            self._push_view(self.compositor.active)
            self.compositor.active = SETTINGS
            self.compositor.render()
            return
        if event == Input.BACK:
            self._cancel_scroll_inertia()
            if self._handle_back():
                return
            return
        # [CLAUDE 2026-06-03] Верхняя «шторка» уведомлений УБРАНА — уведомления теперь
        # отдельный свайп-вью (справа). EDGE_TOP игнорируем.
        if event == Input.EDGE_TOP:
            return
        # Жест ОТ НИЖНЕГО КРАЯ вверх -> сначала свернуть карточку, потом закрыть вью на home.
        if event == Input.EDGE_BOTTOM:
            self._cancel_scroll_inertia()
            self._handle_back()
            return
        if event in (Input.SWIPE_LEFT, Input.SWIPE_RIGHT):
            # [CLAUDE 2026-06-03] Горизонталь: [Маршруты] <- Play Now -> [Уведомления].
            # Настройки больше НЕ свайп-вью — вход по круглой кнопке в Routes (intent open_settings).
            order = [ROUTER, HOME, NOTIF]
            if self.compositor.active in order:
                i = order.index(self.compositor.active)
                j = max(0, min(len(order) - 1, i + (1 if event == Input.SWIPE_RIGHT else -1)))
                target = order[j]
                if target != self.compositor.active:
                    # слайд СЛЕДУЕТ ЗА ПАЛЬЦЕМ: свайп вправо -> контент едет вправо
                    # (новый въезжает слева, текущий уходит вправо) = direction -1.
                    direction = -1 if event == Input.SWIPE_RIGHT else 1
                    self.compositor.animate_switch(target, direction)
                    if target == ROUTER:
                        self._enter_route_view()
                    self._ensure_anim_task()
            return
        # Средние свайпы вверх/вниз (и энкодер) -> прокрутка активного вью.
        self.compositor.handle_input(event)

    def _push_view(self, index):
        if index is None or index == NOTIF:
            return
        if self._view_stack and self._view_stack[-1] == index:
            return
        self._view_stack.append(index)

    def _handle_back(self):
        if self._notif_step_back():             # из развёрнутой карточки -> к списку
            return True
        if self.compositor.active == SETTINGS:
            settings = self.compositor.screens[SETTINGS]
            if hasattr(settings, "back") and settings.back():
                self.compositor.render()
                return True
        if self._view_stack:
            self.compositor.active = self._view_stack.pop()
            self.compositor.render()
            return True
        if self.compositor.active != HOME:
            self.compositor.active = HOME
            self.compositor.render()
            return True
        return True

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
        # [CLAUDE 2026-06-03] После создания пары (сканер закрылся: pairing_mode True->False)
        # возвращаемся на view Входы/Выходы (Routes), а НЕ на главный. Ставится ПОСЛЕ iPhone-флипа,
        # чтобы перебить «подключился iPhone -> HOME», случившийся во время сопряжения.
        pm = bool(getattr(a, "pairing_mode", False))
        if self._prev_pairing_mode and not pm:
            a.active_desktop = ROUTER
        self._prev_pairing_mode = pm
        if a.iphone.connected:
            if s.title != a.iphone.title:          # смена трека -> сбросить локальный «лайк»
                a.iphone.liked = False
            a.iphone.title = s.title
            a.iphone.artist = s.artist
            a.iphone.duration = s.duration
            a.iphone.position = s.elapsed
            a.iphone.playing = s.playing
            if time.monotonic() - getattr(self, "_volume_touch_ts", 0.0) > 0.8:
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
        a.route_name = getattr(model, "route_name", "")
        a.route_protocols = list(getattr(model, "route_protocols", []) or [])
        a.route_warnings = list(getattr(model, "route_warnings", []) or [])
        a.route_cables = list(getattr(model, "route_cables", []) or [])
        a.active_session = getattr(model, "active_session", "remote")
        a.power_tier = getattr(model, "power_tier", "boot")
        if s.source == "mac":
            a.mac.connected = bool(s.connected)
            a.mac.title = s.title
            a.mac.artist = s.artist
            a.mac.duration = s.duration
            a.mac.position = s.elapsed
            a.mac.playing = s.playing
            if time.monotonic() - getattr(self, "_volume_touch_ts", 0.0) > 0.8:
                a.mac.volume = s.volume
        else:
            a.mac.connected = False
            a.mac.title = a.mac.artist = ""
            a.mac.duration = a.mac.position = 0.0
            a.mac.playing = False
        a.clock_text = time.strftime("%H:%M")
        a.device_name = identity_service.visible_name()

    def _sync_trusted_iphone(self, a, connected, peer=None):
        """iPhone (BLE-bonded источник) -> статус в СУЩЕСТВУЮЩЕЙ device-записи.
        [CLAUDE 2026-06-11] БАГ-ФИКС: раньше сюда добавлялся стаб key="iphone" БЕЗ
        endpoints и БЕЗ сверки по адресу -> в списке входов появлялся ВТОРОЙ iPhone
        (legacy + source:ADDR), выбор стаба ронял route_planner («no audio input
        endpoint») и кнопка маршрута мертвела. Теперь: ищем по адресу, стабов не
        создаём (запись источника создаёт load_trusted из keystore/state.json).
        Один физический iPhone (BLE+classic) = ОДНА запись для пользователя."""
        from app_state import normalize_address
        addr = normalize_address(peer) if peer else ""
        entry = None
        if addr:
            entry = next((d for d in a.trusted
                          if normalize_address(d.get("address")) == addr), None)
        if entry is None:   # fallback: единственный source (без peer-адреса в событии)
            sources = [d for d in a.trusted if d.get("role") == "source"]
            entry = sources[0] if len(sources) == 1 else                 next((d for d in a.trusted if d.get("key") == "iphone"), None)
        if entry is None:
            return          # бонда ещё нет — появится через load_trusted, стаб не плодим
        entry["connected"] = bool(connected)
        # У источника нет сигнала «онлайн, но не подключён» -> online == connected
        # (отключён = offline = красный, не залипает жёлтым). Жёлтый — только для динамиков.
        entry["online"] = bool(connected)
        if connected and addr and not entry.get("address"):
            entry["address"] = addr

    def render(self):
        try:
            self.compositor.broadcast_state(self.app_state)
        except Exception as e:
            logger.error("render error: %s", e)

    def set_pairing_mode(self, on: bool, role=None):
        if role:
            self.app_state.pairing_role = role
        self.app_state.pairing_mode = bool(on)

    def show_screen(self, index: int):
        self._cancel_scroll_inertia()
        self._view_stack.clear()
        self.compositor.active = index
        if index == ROUTER:
            self._enter_route_view()
        self.compositor.render()

    def show_session_screen(self):
        self.show_screen(SESSIONS)

    def show_router_screen(self):
        self.show_screen(ROUTER)

    def show_transfer_screen(self):
        self.show_router_screen()

    def show_mac_screen(self):
        self.show_screen(MAC)

    def show_home(self):
        self.show_screen(HOME)
