#!/usr/bin/env python3
"""carthing_runtime — release entrypoint (runtime-contract.md §Entrypoint).

Проверяет persistent-state, поднимает ОДИН логический аксессуар и сводит сервисы.
Супервизор (S50/дирижёр) может рестартовать этот процесс, но НЕ владеет BT/GUI/pairing —
этим владеют сервисы здесь. Никаких заплаток: advertising/видимость — только через
accessory_orchestrator; идентичность — только через identity_service; bt-состояние —
только через runtime_model.

Текущий объём: спайн (state + identity + accessory + model) + источник iPhone.
Адаптеры GUI/Transfer подключаются к этим же точкам (gui_controller/transfer_service).
"""

import asyncio
import logging
import os
import time

# Часы: CTS синкает системное время в UTC -> выставляем локальную зону для strftime.
os.environ.setdefault("TZ", os.environ.get("CARTHING_TZ", "MSK-3"))  # Москва UTC+3, без DST
try:
    time.tzset()
except Exception:
    pass

import runtime_paths  # noqa: F401  (ставит sys.path)
import state_paths
import identity_service
from ble_transport import init_ble
from accessory_orchestrator import AccessoryOrchestrator
from runtime_model import RuntimeModel
from iphone_service import IPhoneService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("carthing_runtime")

RENDER_INTERVAL = 0.2   # с: рендер-тик (живой прогресс на экране)
PUBLISH_EVERY = 5       # каждые N тиков писать runtime-bt.json (~1 с)

orch: AccessoryOrchestrator | None = None
model = RuntimeModel()
_iphone: IPhoneService | None = None
gui = None
transfer = None          # TransferService
backchannel = None       # TransferControlBackchannel
settings = None          # SettingsService
hw_caps = {}             # hardware_inventory.probe()
mac = None               # MacService
power = None             # IdlePowerController

VALID_DEVICE_MODES = {"remote", "transfer", "mac", "pairing", "quiet", "service"}


def _on_command(source, command):
    if source == "iphone" and _iphone is not None:
        asyncio.ensure_future(_iphone.command(command))
    elif source == "mac" and mac is not None:
        asyncio.ensure_future(mac.command(command))


def _on_pairing(enabled):
    if power is not None:
        power.set_pairing(bool(enabled))
    if orch is not None:
        asyncio.ensure_future(orch.arm_pairing(bool(enabled)))
    if gui is not None:
        gui.set_pairing_mode(bool(enabled))


def _on_transfer_rescan():
    if power is not None:
        power.note_transfer_scan()
    if transfer is not None:
        asyncio.ensure_future(transfer.rescan())


def _on_transfer_select(address):
    if power is not None:
        power.note_activity("transfer_select")
    if transfer is not None:
        asyncio.ensure_future(transfer.select(address))


def _on_mode_select(mode):
    asyncio.ensure_future(_apply_device_mode(mode))


def _on_toggle_sleep(on):
    # [CLAUDE 2026-06-01] тумблер «Сон экрана» из Settings: применяем к power + персистим.
    if power is not None:
        power.set_idle_sleep(bool(on))
    if settings is not None:
        settings.set("sleep_on_idle", bool(on))


def _on_set_off_timeout(sec):
    # [CLAUDE 2026-06-01] ±тайм-аут полного гашения из Settings: применяем к power + персистим.
    sec = int(sec)
    if power is not None:
        power.set_off_after(sec)
    if settings is not None:
        settings.set("screen_off_after_sec", sec)


async def _apply_device_mode(mode, persist=True):
    mode = mode if mode in VALID_DEVICE_MODES else "remote"
    model.device_mode = mode
    model.mode_status = "applying"
    if settings is not None and persist and mode != "pairing":
        settings.set("device_mode", mode)
    if power is not None:
        power.set_device_mode(mode)

    if mode != "pairing":
        if power is not None:
            power.set_pairing(False)
        if gui is not None:
            gui.set_pairing_mode(False)
        if orch is not None:
            await orch.arm_pairing(False)

    if mode in ("remote", "quiet", "service", "mac", "pairing") and transfer is not None:
        await transfer.deactivate()

    if mode == "remote":
        model.audio_sink = "builtin"
        model.mode_status = "iPhone remote"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_home()
    elif mode == "transfer":
        model.audio_sink = "speaker"
        model.mode_status = "transfer armed"
        if _iphone is not None:
            _iphone.activate_source()
        if transfer is not None:
            await transfer.activate()
            asyncio.ensure_future(transfer.rescan())
        if power is not None:
            power.note_transfer_scan(hold_sec=15.0)
        if gui is not None:
            gui.show_transfer_screen()
    elif mode == "mac":
        model.audio_sink = "builtin"
        model.mode_status = "macOS control"
        if mac is not None:
            mac.attach()
        if gui is not None:
            gui.show_mac_screen()
    elif mode == "pairing":
        model.audio_sink = "builtin"
        model.mode_status = "pairing window"
        if gui is not None:
            gui.show_mode_screen()
        _on_pairing(True)
    elif mode == "quiet":
        model.audio_sink = "builtin"
        model.mode_status = "connected quiet"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_mode_screen()
    elif mode == "service":
        model.audio_sink = "builtin"
        model.mode_status = "service safe"
        if mac is not None:
            mac.detach()
        if _iphone is not None:
            _iphone.activate_source()
        if gui is not None:
            gui.show_mode_screen()

    logger.info("device mode: %s (%s)", mode, model.mode_status)
    _on_publish()


async def _emit_source_intent(intent):
    """Для backchannel: команда динамика -> активный источник."""
    if _iphone is not None:
        await _iphone.command(intent)


def _on_notif_dismiss(uid):
    """Свайп-влево на уведомлении -> очистить и на iPhone (ANCS negative)."""
    if _iphone is not None:
        asyncio.ensure_future(_iphone.dismiss(uid))


def _verify_persistent():
    try:
        state_paths.ensure_files()
        logger.info("persistent state OK (%s)", state_paths.STATE_DIR)
    except state_paths.PersistentStateError as e:
        # degraded: не выдумываем базу на tmpfs (контракт). Работаем, но без persistent-бондов.
        logger.error("DEGRADED — %s", e)


def _on_publish():
    model.write_bt_json()


def _is_classic(connection) -> bool:
    try:
        from bumble.core import BT_BR_EDR_TRANSPORT
        return getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT
    except Exception:
        return False


async def _on_connection(connection):
    global _iphone
    classic = _is_classic(connection)
    logger.info("connected: %s classic=%s encrypted=%s",
                getattr(connection, "peer_address", "?"), classic,
                getattr(connection, "is_encrypted", False))

    # Входящий classic A2DP (iPhone выбрал Car Thing аудиовыходом) -> Transfer-маршрут.
    if classic:
        if transfer is not None:
            await transfer.on_incoming_classic(connection)
        return

    _iphone = IPhoneService(model, on_update=_on_publish)
    started = {"v": False}

    async def _start_ams(why):
        # AMS-характеристики требуют ШИФРОВАНИЯ — поднимаем только когда encrypted.
        if started["v"] or not getattr(connection, "is_encrypted", False):
            return
        started["v"] = True
        logger.info("AMS start (%s)", why)
        try:
            await _iphone.setup(connection)
        except Exception as e:
            started["v"] = False
            logger.warning("iphone setup failed: %s", e)
        if orch is not None:
            await orch.on_bonded()

    def _disc(*_):
        if _iphone is not None:
            _iphone.reset()
        if orch is not None:
            asyncio.ensure_future(orch.on_disconnect())

    async def _on_pairing_failure(reason):
        # [CLAUDE 2026-06-01] АВТО-«ЗАБЫТЬ» при сбое пары.
        # Симптом: iPhone «забыл» устройство и парится заново, а device держит СТАРЫЙ бонд +
        # включён address-resolution (загружен на power_on). Контроллер резолвит RPA телефона в
        # старую identity -> в SC-крипто device использует identity-адрес, iPhone — свой RPA ->
        # DHKey check НЕ сходится -> SMP_DHKEY_CHECK_FAILED, пара не создаётся (нужна ручная чистка).
        # Фикс: на сбое пары авто-сбрасываем старый бонд + резолвинг -> СЛЕДУЮЩИЙ ретрай iPhone
        # (он реконнектит сам) идёт без резолвинга -> on-air RPA с обеих сторон -> DHKey сходится ->
        # свежая пара создаётся автоматически, без ручного rm keys.json.
        # Codex: это закрывает "forget на iPhone -> не пере-парится". Долгосрочно лучше дроп бонда
        # на СТАРТЕ пары (pairing request), но reactive-на-failure надёжно (iPhone сам ретраит).
        logger.error("SMP pairing failed: %s — auto-forget stale bond + resolving", reason)
        dev = orch.device if orch is not None else None
        if dev is None:
            return
        try:
            if dev.keystore is not None:
                await dev.keystore.delete_all()
            from bumble.hci import (HCI_LE_Set_Address_Resolution_Enable_Command,
                                    HCI_LE_Clear_Resolving_List_Command)
            await dev.send_command(HCI_LE_Set_Address_Resolution_Enable_Command(
                address_resolution_enable=0))
            await dev.send_command(HCI_LE_Clear_Resolving_List_Command())
            logger.info("Auto-forget: dropped stale bond + cleared resolving (clean re-pair on retry)")
        except Exception as e:
            logger.warning("auto-forget failed: %s", e)

    connection.on("disconnection", _disc)
    connection.on("pairing", lambda *_: asyncio.ensure_future(_start_ams("pairing")))
    connection.on("pairing_failure", lambda r: asyncio.ensure_future(_on_pairing_failure(r)))
    connection.on("connection_encryption_change",
                  lambda *_: asyncio.ensure_future(_start_ams("encryption")))

    if gui is not None:
        gui.set_pairing_mode(False)   # авто-закрыть pairing-модалку на коннекте
    if power is not None:
        power.set_pairing(False)

    if getattr(connection, "is_encrypted", False):
        await _start_ams("connected-encrypted")
    else:
        logger.info("requesting pairing (link not encrypted yet)")
        try:
            connection.request_pairing()
        except Exception as e:
            logger.warning("request_pairing failed: %s", e)


async def main():
    global orch, gui, transfer, backchannel, settings, hw_caps, mac, power
    _verify_persistent()

    # Per-boot инвентарь возможностей + настройки.
    import hardware_inventory
    from settings_service import SettingsService
    hw_caps = hardware_inventory.probe()
    settings = SettingsService()
    logger.info("hw capabilities: %s", {k: v for k, v in hw_caps.items() if v})

    def _configure(device):
        global orch
        orch = AccessoryOrchestrator(device, on_phase_change=lambda p: logger.info("phase=%s", p))
        orch.install()  # CTKD pairing config + classic enabled (для CTKD)

    # Cold-boot: hci0 (btattach) может быть ещё не готов -> Errno 16 busy. Терпеливый retry.
    device = None
    for attempt in range(8):
        try:
            device, _transport = await init_ble(configure_device=_configure)
            break
        except OSError as e:
            logger.warning("init_ble attempt %d failed (HCI busy?): %s", attempt + 1, e)
            await asyncio.sleep(3)
    if device is None:
        logger.error("init_ble failed after retries — exiting (supervisor restart)")
        return
    await orch.apply_identity()       # одно имя на все транспорты

    device.on("connection", lambda c: asyncio.ensure_future(_on_connection(c)))

    # GUI: один home-surface + views поверх DRM (если дисплей доступен).
    if hw_caps.get("display_drm"):
        try:
            from drm_display import DRMDisplay
            from gui_controller import GuiController
            gui = GuiController(DRMDisplay(),
                                on_command=_on_command, on_pairing=_on_pairing,
                                on_transfer_rescan=_on_transfer_rescan,
                                on_transfer_select=_on_transfer_select,
                                on_notif_dismiss=_on_notif_dismiss,
                                on_mode_select=_on_mode_select,
                                on_toggle_sleep=_on_toggle_sleep,
                                on_set_off_timeout=_on_set_off_timeout)
            logger.info("GUI active (modular Compositor)")
            from power_policy import IdlePowerController
            power = IdlePowerController(settings)
            # [CLAUDE] начальные значения для Settings = реальные из power
            gui.app_state.sleep_on_idle = bool(getattr(power, "enabled", True))
            gui.app_state.screen_off_sec = int(getattr(power, "off_after", 150))
        except Exception as e:
            gui = None
            logger.warning("GUI disabled: %s", e)

    # Transfer: A2DP relay + backchannel (внутри единого рантайма).
    try:
        from transfer_service import TransferService
        from transfer_control import TransferControlBackchannel
        app_state = gui.app_state if gui is not None else None
        transfer = TransferService(device, app_state, orch, model, on_change=_on_publish)
        backchannel = TransferControlBackchannel(_emit_source_intent, model=model)
        await transfer.start()        # SDP + AVDTP listener (видимость ещё перегейтим)
    except Exception as e:
        transfer = None
        logger.warning("transfer disabled: %s", e)

    # macOS-источник (Фаза 4, каркас).
    from mac_service import MacService
    mac = MacService(model, on_update=_on_publish)
    await _apply_device_mode(settings.get("device_mode", "remote"), persist=False)

    # Видимость — ПОСЛЕ transfer.start(): orchestrator перегейтит classic в not-connectable
    # (никакой открытой A2DP-рекламы; directed-к-bonded / тишина по фазе).
    await orch.apply_visibility()
    # Старт с существующим бондом -> активно прилипнуть (high-duty directed burst).
    asyncio.ensure_future(orch.kick_reconnect())

    # Рендер-цикл — ОТДЕЛЬНАЯ задача (не зависит от input.start, который блокирует loop).
    async def _render_loop():
        tick = 0
        while True:
            # Во время шторки экраном владеет отдельный тикер (_shade_loop) — основной
            # цикл молчит, чтобы не было двойного рендера/гонки за дисплей.
            shade = gui is not None and gui.needs_fast_render()
            if power is not None:
                power.note_model(model)
                power.tick()
                model.power_tier = power.runtime_tier
            if gui is not None and not shade:
                gui.apply(model)      # RuntimeModel -> AppState (живой прогресс)
                if power is None or power.display_awake:
                    gui.render()
            publish_due = (tick % PUBLISH_EVERY == 0) if power is None else power.should_publish()
            if not shade and publish_due:
                _on_publish()         # runtime-bt.json для дирижёра/sync
            tick += 1
            interval = RENDER_INTERVAL if power is None else power.render_interval
            await asyncio.sleep(interval)

    asyncio.ensure_future(_render_loop())

    # Физический ввод (энкодер/кнопки/тач) -> GUI (параллельно рендеру).
    if gui is not None:
        try:
            import input_handler
            def _on_input(event):
                if power is not None:
                    power.note_activity("input")
                gui.handle_input(event)
            asyncio.ensure_future(input_handler.start(on_event=_on_input))
        except Exception as e:
            logger.warning("input disabled: %s", e)

    logger.info("runtime up — name=%s", identity_service.visible_name())
    await asyncio.get_event_loop().create_future()   # работать вечно


if __name__ == "__main__":
    asyncio.run(main())
