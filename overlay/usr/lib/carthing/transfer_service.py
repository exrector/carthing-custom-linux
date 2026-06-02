"""transfer_service — A2DP relay ВНУТРИ единого рантайма (runtime-contract §Transfer).

Transfer = внутренняя маршрутизация аудио (iPhone -> Car Thing -> BT-динамик), НЕ вторая
BT-персона и НЕ режим. Обёртка над проверенным a2dp_bridge (AAC passthrough relay).

КЛЮЧЕВОЙ СТЫК (чинит «iPhone цепляется колонкой»): a2dp_bridge сам включал classic
connectable + COD_LOUDSPEAKER на старте. Здесь classic-connectable ГЕЙТИТ
accessory_orchestrator (connectable=False вне Transfer; True только при activate()).
Так relay сохраняется, а дефолтная A2DP-видимость убрана.

Получатель НЕ хардкожен (runtime-contract): из настройки/intent -> trusted speakers -> нет приёмника.
"""

import asyncio
import logging

import identity_service
from a2dp_bridge import A2DPBridge

logger = logging.getLogger(__name__)


class TransferService:
    def __init__(self, device, app_state, orchestrator, model, on_change=None):
        self.orch = orchestrator
        self.model = model
        self.on_change = on_change or (lambda: None)
        self.bridge = A2DPBridge(
            device, app_state,
            bt_name=identity_service.classic_audio_name(),
            autoconnect=False,                  # никакого авто-коннекта/визибилити по умолчанию
            on_state_change=self._sync,
        )
        self._speaker_enroll_task = None

    async def start(self):
        """Поднять SDP + relay-машинерию (listener). Видимость остаётся за orchestrator."""
        self.bridge.install_sdp_records()
        self.bridge.install_safe_link_key_provider()
        await self.bridge.start()               # AVDTP listener up
        self.bridge.start_standby_loop()        # trusted speakers stick when available
        # ВАЖНО: вызвать orchestrator.apply_visibility() ПОСЛЕ — он перегейтит classic в not-connectable.

    async def start_speaker_enrollment(self):
        if self._speaker_enroll_task is not None and not self._speaker_enroll_task.done():
            return
        self._speaker_enroll_task = asyncio.create_task(self._speaker_enrollment_loop())
        self._sync()

    async def _speaker_enrollment_loop(self):
        while bool(getattr(self.bridge.state, "pairing_mode", False)):
            try:
                await self.bridge.scan_pairable_speakers(duration=8.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("speaker enrollment scan failed: %s", e)
                try:
                    self.bridge.state.speaker_pairing_status = "error"
                except Exception:
                    pass
                self._sync()
                await asyncio.sleep(1.0)
                continue
            if bool(getattr(self.bridge.state, "pairing_mode", False)):
                try:
                    self.bridge.state.speaker_pairing_status = "scan"
                except Exception:
                    pass
                self._sync()
                await asyncio.sleep(1.0)

    async def stop_speaker_enrollment(self):
        if self._speaker_enroll_task is not None and not self._speaker_enroll_task.done():
            self._speaker_enroll_task.cancel()
            try:
                await self._speaker_enroll_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.warning("speaker enrollment loop stop ignored: %s", e)
        self._speaker_enroll_task = None
        try:
            await self.bridge.device.stop_discovery()
        except Exception:
            pass
        try:
            self.bridge.state.speaker_pairing_status = "idle"
        except Exception:
            pass
        self._sync()

    async def pair_speaker(self, address):
        try:
            await self.bridge.pair_speaker(address)
            if getattr(self.bridge.state, "speaker_pairing_status", "") == "done":
                await asyncio.sleep(1.2)
                self.bridge.state.pairing_mode = False
                self.bridge.state.speaker_pairing_status = "idle"
        except Exception as e:
            logger.warning("speaker pair failed: %s", e)
            try:
                self.bridge.state.speaker_pairing_status = "error"
                self.bridge.state.pairing_message = "Пара не завершена"
            except Exception:
                pass
        self._sync()

    async def forget_trusted(self, address):
        try:
            await self.bridge.forget_peer_key(address)
        except Exception as e:
            logger.warning("speaker forget key failed: %s", e)
        try:
            self.bridge.state.clear_connected_speakers()
        except Exception:
            pass
        self._sync()

    # ── активация Transfer (вручную из Routes-view, runtime-contract) ────────
    async def activate(self):
        self.model.transfer_active = True
        try:
            self.bridge.state.transfer_active = True
            self.bridge.state.transfer_status = "armed"
        except Exception:
            pass
        await self.orch.set_transfer_connectable(True)   # classic connectable (bonded-only, не discoverable)
        await self.orch.on_a2dp_state(True)
        # [CLAUDE 2026-06-02] CarThing САМ звонит bonded айфону по classic (исходящий) — это
        # «мы инициируем classic из меню, айфон подхватывает». Раньше код только ЖДАЛ входящего.
        src = None
        try:
            sources = list(self.bridge.state.trusted_sources)
            if sources:
                src = sources[0].get("address")
        except Exception:
            src = None
        if src:
            try:
                await self.bridge.connect_source(src)
                logger.info("transfer: dialed bonded source over classic: %s", src)
            except Exception as e:
                logger.warning("source classic dial failed (iPhone may still pick up): %s", e)
        else:
            logger.info("transfer armed: no bonded source yet — nothing to dial")
        await self.bridge.ensure_trusted_speakers_connected()
        await self.bridge.request_receiver_connection()
        self._sync()

    async def deactivate(self):
        # Transfer выключен: останавливаем только аудиопоток. Classic standby с
        # доверенными динамиками остаётся жить и будет переподключаться само.
        self.model.transfer_active = False
        try:
            self.bridge.state.transfer_active = False
        except Exception:
            pass
        await self.bridge.stop_receiver_stream()
        await self.orch.set_transfer_connectable(False)
        await self.orch.on_a2dp_state(False)
        self._sync()

    # ── Routes-view intents ──────────────────────────────────────────────────
    async def rescan(self):
        try:
            await self.bridge.scan_trusted_speakers()
        except Exception as e:
            logger.warning("speaker rescan failed: %s", e)
        self._sync()

    async def select(self, address):
        try:
            self.bridge.state.select_default_speaker(address)
            self.bridge.state.transfer_status = "standby"
            await self.bridge.ensure_trusted_speakers_connected()
        except Exception as e:
            logger.warning("speaker select failed: %s", e)
        self._sync()

    # ── входящий classic A2DP от iPhone (выбрал Car Thing аудиовыходом) ───────
    async def on_incoming_classic(self, connection):
        try:
            await self.bridge.handle_classic_connection(connection)
        except Exception as e:
            logger.warning("handle classic conn failed: %s", e)
        await self.orch.on_a2dp_state(True)
        self.model.transfer_active = True
        self._sync()

    def _sync(self):
        ready = getattr(self.bridge, "receiver_rtp_channel", None) is not None
        standby = [
            speaker for speaker in self.bridge.state.trusted_speakers
            if speaker.get("connected")
        ]
        self.model.speaker_connected = bool(ready or standby)
        self.model.speaker_name = (
            getattr(self.bridge, "receiver_address", None)
            or (standby[0].get("address") if standby else None)
        )
        status = getattr(self.bridge.state, "transfer_status", "")
        if status:
            self.model.mode_status = status if not ready else "transfer connected"
        self.on_change()
