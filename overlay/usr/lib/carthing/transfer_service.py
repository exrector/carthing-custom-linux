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

    async def start(self):
        """Поднять SDP + relay-машинерию (listener). Видимость остаётся за orchestrator."""
        self.bridge.install_sdp_records()
        self.bridge.install_safe_link_key_provider()
        await self.bridge.start()               # AVDTP listener up
        # ВАЖНО: вызвать orchestrator.apply_visibility() ПОСЛЕ — он перегейтит classic в not-connectable.

    async def start_speaker_enrollment(self):
        try:
            await self.bridge.scan_pairable_speakers()
        except Exception as e:
            logger.warning("speaker enrollment scan failed: %s", e)
            try:
                self.bridge.state.speaker_pairing_status = "error"
            except Exception:
                pass
        self._sync()

    async def stop_speaker_enrollment(self):
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
        await self.orch.set_transfer_connectable(True)   # classic connectable для входящего A2DP
        await self.orch.on_a2dp_state(True)
        self._sync()

    async def deactivate(self):
        # Снимаем classic-connectable -> входящий A2DP больше не принимается, приёмник
        # отваливается сам (on_receiver_disconnected). Чистого disconnect-метода у bridge нет.
        self.model.transfer_active = False
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
            await self.bridge.request_receiver_connection(address)
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
        self.model.speaker_connected = bool(getattr(self.bridge, "receiver_address", None))
        self.model.speaker_name = getattr(self.bridge, "receiver_address", None)
        self.on_change()
