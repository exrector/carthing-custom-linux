"""accessory_orchestrator — product-level Bluetooth owner above Bumble.

runtime-contract.md §Module Boundaries + pairing-and-transfer-scenarios.md.

ЭТО KEYSTONE. Он one-shot убирает корень всех dual-mode жалоб:
  «два устройства в рекламе» · «BLE и classic не вместе» · «не прилипает» · «баннер висит».

Владеет ЛОГИЧЕСКИМ аксессуаром: ОДНО видимое имя (identity_service), ОДИН источник-сессия,
CTKD-pairing (LE+BR/EDR link-key в одну сессию, без перезатирания), фазовая машина и
политика видимости. BLE и Classic — транспорты-адаптеры НИЖЕ этого слоя, не отдельные персоны.
GUI сюда шлёт лишь intents «add source / add speaker», но НЕ решает, что видимо.

Фазы (pairing-and-transfer-scenarios.md):
  pairing                  — бондов нет           → general discoverable (BLE+classic)
  classic_ready_needs_le   — classic есть, LE нет  → general (восстановить LE)
  le_ready_needs_classic   — LE есть, classic нет  → bonded-only/directed (скрыт, ждём classic)
  both_bonded_transfer_idle— оба бонда, transfer off→ directed-to-bonded / silent; classic connectable=False
  ready                    — оба бонда, A2DP open  → directed-to-bonded / silent

ИНВАРИАНТ (pairing-and-transfer-scenarios.md): Classic-HW включён на КАЖДОМ boot
(иначе CTKD не отработает при первом BLE-сопряжении), но connectable=False вне Transfer.
Вне сопряжения — directed-к-bonded ИЛИ полная тишина. «Пока пара не активирована через меню —
устройство молчит и отказывает всем.»
"""

import asyncio
import logging
import struct
import time

from bumble.device import AdvertisingData, AdvertisingType, Device, OwnAddressType
from bumble.hci import Address, HCI_Write_Local_Name_Command
from bumble.smp import PairingConfig

import identity_service

logger = logging.getLogger(__name__)

APPEARANCE_REMOTE = 0x0180          # Generic Remote Control
HID_SERVICE_UUID = 0x1812          # HID-over-GATT

# [CLAUDE 2026-06-01] Быстрый интервал рекламы для sticky-реконнекта. Дефолт Bumble = 1000мс
# (раз в секунду) => iPhone долго обнаруживает устройство для реконнекта («долго думает»).
# 60мс ~ как у AirPods; устройство на USB-питании, энергия не критична.
STICKY_ADV_INTERVAL_MS = 60


# ── фазы ──────────────────────────────────────────────────────────────────────
PAIRING = "pairing"
CLASSIC_READY_NEEDS_LE = "classic_ready_needs_le"
LE_READY_NEEDS_CLASSIC = "le_ready_needs_classic"
BOTH_BONDED_TRANSFER_IDLE = "both_bonded_transfer_idle"
READY = "ready"


class AccessoryOrchestrator:
    def __init__(self, device: Device, on_phase_change=None):
        self.device = device
        self.on_phase_change = on_phase_change
        self.pairing_armed = False        # выставляется GUI-intent'ом «add source/speaker»
        self.transfer_connectable = False # classic connectable для A2DP (Transfer)
        self.a2dp_open = False
        self.phase = PAIRING

    # ── идентичность (одно имя на все транспорты) ─────────────────────────────
    async def apply_identity(self):
        name = identity_service.visible_name()
        self.device.name = name
        try:
            await self.device.host.send_command(
                HCI_Write_Local_Name_Command(local_name=name.encode("utf-8"))
            )
        except Exception as e:
            logger.warning("Write_Local_Name(%s) failed: %s", name, e)

    # ── CTKD-pairing (один pairing → оба ключа в одну логическую сессию) ──────
    def pairing_config_factory(self, connection):
        # sc=True (Secure Connections) — обязателен для CTKD; bonding=True — храним.
        # При sc=True и поднятом classic Bumble выводит BR/EDR link-key из LE LTK (CTKD),
        # так пользователь парится ОДИН раз, а Transfer потом не требует повторной пары.
        return PairingConfig(sc=True, mitm=False, bonding=True)

    def install(self):
        """Повесить pairing_config_factory на Device. Classic-HW держим включённым."""
        self.device.pairing_config_factory = self.pairing_config_factory
        # Classic включён всегда (для CTKD), но не connectable/discoverable вне нужды.
        try:
            self.device.classic_enabled = True
        except Exception as e:
            logger.warning("classic_enable failed: %s", e)

    # ── состояние бондов ─────────────────────────────────────────────────────
    async def _bonds(self):
        """(le_addr|None, has_classic) из keystore. LE-бонд = есть ltk/irk."""
        le_addr, has_classic = None, False
        try:
            ks = getattr(self.device, "keystore", None)
            if ks is None:
                return le_addr, has_classic
            for name, keys in reversed(await ks.get_all()):
                if getattr(keys, "ltk", None) or getattr(keys, "irk", None):
                    if le_addr is None:
                        le_addr = Address(name)
                if getattr(keys, "link_key", None):
                    has_classic = True
        except Exception as e:
            logger.warning("bond inspection failed: %s", e)
        return le_addr, has_classic

    async def _compute_phase(self, le_addr, has_classic):
        if le_addr is None and not has_classic:
            return PAIRING
        if le_addr is None and has_classic:
            return CLASSIC_READY_NEEDS_LE
        if le_addr is not None and not has_classic:
            return LE_READY_NEEDS_CLASSIC
        return READY if self.a2dp_open else BOTH_BONDED_TRANSFER_IDLE

    # ── ЕДИНСТВЕННЫЙ метод видимости: всё advertising+classic из текущей фазы ──
    async def apply_visibility(self):
        le_addr, has_classic = await self._bonds()
        phase = await self._compute_phase(le_addr, has_classic)
        if phase != self.phase:
            self.phase = phase
            if self.on_phase_change:
                try:
                    self.on_phase_change(phase)
                except Exception:
                    pass

        # 1) classic: connectable ТОЛЬКО в Transfer; НИКОГДА не discoverable.
        # Иначе в режиме сопряжения classic светится как ВТОРОЕ устройство рядом с BLE.
        # iPhone парится по BLE, classic-ключ выводится через CTKD (не отдельной classic-парой);
        # динамики добавляются инквайр-сканом (устройство ищет их, а не рекламирует себя).
        await self._set_classic(
            connectable=self.transfer_connectable,
            discoverable=False,
        )

        # 2) BLE advertising по фазе/режиму. Когда УЖЕ подключены — не рекламируемся
        # (иначе контроллер отдаёт HCI_COMMAND_DISALLOWED 0xC).
        connected = False
        try:
            connected = len(self.device.connections) > 0
        except Exception:
            pass
        if connected:
            await self._advertise_silent()
        elif self.pairing_armed:
            await self._advertise_general()        # видим ТОЛЬКО в режиме сопряжения (из меню)
        elif le_addr is not None:
            await self._advertise_bonded_only()     # sticky: реконнект к УЖЕ-bonded iPhone
        else:
            await self._advertise_silent()          # нет бонда + не сопряжение -> ПОЛНАЯ ТИШИНА

        logger.info("Visibility: phase=%s pairing_armed=%s transfer_conn=%s",
                    phase, self.pairing_armed, self.transfer_connectable)

    # ── BLE advertising примитивы (порт проверенного из media_remote) ─────────
    def _adv_payload(self):
        items = [
            (AdvertisingData.FLAGS, bytes([0x06])),
            (AdvertisingData.APPEARANCE, struct.pack("<H", APPEARANCE_REMOTE)),
            (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
             struct.pack("<H", HID_SERVICE_UUID)),
        ]
        return bytes(AdvertisingData(items))

    def _scan_response_payload(self, with_name: bool):
        if not with_name:
            return b""
        return bytes(AdvertisingData([
            (AdvertisingData.COMPLETE_LOCAL_NAME,
             identity_service.visible_name().encode("utf-8")),
        ]))

    async def _advertise_general(self):
        await self._stop()
        self.device.advertising_data = self._adv_payload()
        self.device.scan_response_data = self._scan_response_payload(with_name=True)
        try:
            await self.device.start_advertising(
                own_address_type=OwnAddressType.PUBLIC, auto_restart=True)
            logger.info("General pairing advertising started (public, scan-name)")
        except Exception as e:
            logger.warning("general advertising failed: %s", e)

    async def _advertise_directed(self, target):
        await self._stop()
        try:
            await self.device.refresh_filter_accept_list()
        except Exception:
            pass
        try:
            await self.device.start_advertising(
                advertising_type=AdvertisingType.DIRECTED_CONNECTABLE_LOW_DUTY,
                target=target,
                own_address_type=OwnAddressType.PUBLIC,
                auto_restart=True)
        except Exception as e:
            logger.warning("directed advertising failed: %s", e)

    async def _advertise_silent(self):
        await self._stop()

    async def _stop(self):
        try:
            await self.device.stop_advertising()
        except Exception:
            pass

    async def _set_classic(self, connectable: bool, discoverable: bool):
        for fn_name, val in (("set_connectable", connectable),
                             ("set_discoverable", discoverable)):
            fn = getattr(self.device, fn_name, None)
            if fn is None:
                continue
            try:
                res = fn(val)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.warning("%s(%s) failed: %s", fn_name, val, e)

    # ── intents / события (пересчитывают видимость) ──────────────────────────
    async def arm_pairing(self, on: bool):
        """GUI: вход/выход «Режим сопряжения» (двунаправленный — источники И динамики)."""
        self.pairing_armed = bool(on)
        if on:
            # [CLAUDE 2026-06-01] ПЕРВАЯ-ЖЕ пара чистая. Вход в режим сопряжения = явное намерение
            # спарить заново. Если оставить включённый address-resolution (загружен на power_on из
            # старого бонда), контроллер резолвит RPA новой пары в СТАРУЮ identity -> в SC-крипто
            # device берёт identity-адрес, iPhone — свой RPA -> DHKey check НЕ сходится ->
            # SMP_DHKEY_CHECK_FAILED, и пара создаётся только со ВТОРОЙ попытки (после reactive
            # auto-forget в carthing_runtime). Гасим резолвинг СРАЗУ при входе в pairing -> первая
            # попытка идёт на on-air RPA с обеих сторон -> DHKey сходится. Свежая пара перезапишет
            # старый бонд (keystore keyed by identity). Резолвинг вернётся на следующем power_on.
            # Codex: долгосрочно — refresh resolving list на on_bonded (тогда и рестарт не нужен).
            await self._disable_resolution_for_pairing()
            await self._disconnect_current_connections_for_pairing()
        await self.apply_visibility()

    async def _disconnect_current_connections_for_pairing(self):
        """Pairing is a deliberate service operation.

        On this controller, trying to start undirected advertising while an
        existing central is connected is unreliable and often gets silenced by
        apply_visibility(). Drop current links first so a new iPhone/Mac can
        actually see the accessory.
        """
        try:
            raw_connections = self.device.connections
            connections = list(raw_connections.values() if hasattr(raw_connections, "values") else raw_connections)
        except Exception:
            connections = []
        for connection in connections:
            try:
                peer = getattr(connection, "peer_address", connection)
                logger.info("Pairing mode: disconnect current peer %s", peer)
                await connection.disconnect()
            except Exception as e:
                logger.warning("pairing disconnect ignored: %s", e)
        for _ in range(10):
            try:
                if not self.device.connections:
                    break
            except Exception:
                break
            await asyncio.sleep(0.2)

    async def _disable_resolution_for_pairing(self):
        try:
            from bumble.hci import (HCI_LE_Set_Address_Resolution_Enable_Command,
                                    HCI_LE_Clear_Resolving_List_Command)
            await self._stop()   # резолвинг-лист правим не на ходу
            await self.device.send_command(
                HCI_LE_Set_Address_Resolution_Enable_Command(address_resolution_enable=0))
            await self.device.send_command(HCI_LE_Clear_Resolving_List_Command())
            logger.info("Pairing mode: address resolution OFF (clean first-try pairing)")
        except Exception as e:
            logger.warning("disable resolution for pairing failed: %s", e)

    async def set_transfer_connectable(self, on: bool):
        """Transfer: открыть classic для входящего A2DP (link-key уже есть из CTKD)."""
        self.transfer_connectable = bool(on)
        await self.apply_visibility()

    async def on_bonded(self):
        """Вызывать после успешного SMP-бонда (CTKD мог положить и LE, и classic ключ)."""
        # успешная пара → снять armed, перейти к directed/тишине по фазе.
        self.pairing_armed = False
        await self.apply_visibility()

    async def on_a2dp_state(self, opened: bool):
        self.a2dp_open = bool(opened)
        await self.apply_visibility()

    async def on_disconnect(self):
        await asyncio.sleep(0.5)   # дать контроллеру осесть (иначе start_advertising = 0xC)
        await self.kick_reconnect()

    async def _advertise_bonded_only(self):
        """НЕПРЕРЫВНАЯ undirected bonded reconnect (named scan response).
        Приватный iPhone (RPA) реконнектит bonded HID-периферию по ней в ЛЮБОЙ момент
        (10 минут/час отсутствия — без разницы). На BCM4345/iOS hardware accept-list после
        cold boot может быть слишком строгим к RPA, поэтому reconnect-реклама совместимая:
        public own-address + scan-response name, а новая пара всё равно гейтится рантаймом."""
        await self._stop()
        try:
            await self.device.refresh_filter_accept_list()
        except Exception:
            pass
        self.device.advertising_data = self._adv_payload()
        self.device.scan_response_data = self._scan_response_payload(with_name=True)
        # [CLAUDE 2026-06-01] быстрый интервал -> iPhone обнаруживает для реконнекта почти мгновенно
        self.device.advertising_interval_min = STICKY_ADV_INTERVAL_MS
        self.device.advertising_interval_max = STICKY_ADV_INTERVAL_MS
        try:
            await self.device.start_advertising(
                own_address_type=OwnAddressType.PUBLIC,
                auto_restart=True,
                advertising_filter_policy=0x00)
            logger.info("Sticky: continuous bonded reconnect advertising (public, scan-name, %dms)",
                        STICKY_ADV_INTERVAL_MS)
        except Exception as e:
            logger.warning("bonded-only advertising failed: %s", e)

    async def kick_reconnect(self):
        """Прилипание = НЕПРЕРЫВНАЯ bonded-only реклама (apply_visibility). Точка вызова
        на старте/диссконнекте; auto_restart держит рекламу живой бесконечно.
        [CLAUDE 2026-06-01] Убрал directed-burst (+4с): directed-к-identity приватный iPhone (RPA)
        ИГНОРИРУЕТ, он только задерживал поднятие undirected sticky на 4с => медленный реконнект.
        Теперь sticky встаёт сразу с быстрым интервалом."""
        await self.apply_visibility()
