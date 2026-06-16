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
import os
import struct
import time

from bumble.device import AdvertisingData, AdvertisingType, Device
from bumble.hci import Address, HCI_Write_Local_Name_Command, OwnAddressType
from bumble.pairing import PairingConfig, PairingDelegate

import identity_service

logger = logging.getLogger(__name__)

APPEARANCE_REMOTE = 0x0180          # Generic Remote Control
HID_SERVICE_UUID = 0x1812          # HID-over-GATT
DUAL_MODE_ADV_FLAGS = (
    AdvertisingData.LE_GENERAL_DISCOVERABLE_MODE_FLAG
    | AdvertisingData.BR_EDR_CONTROLLER_FLAG
    | AdvertisingData.BR_EDR_HOST_FLAG
)
LE_ONLY_ADV_FLAGS = (
    AdvertisingData.LE_GENERAL_DISCOVERABLE_MODE_FLAG
    | AdvertisingData.BR_EDR_NOT_SUPPORTED_FLAG
)

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
    def __init__(self, device: Device, on_phase_change=None, hci_gate=None):
        self.device = device
        self.on_phase_change = on_phase_change
        self.hci_gate = hci_gate          # [CLAUDE 2026-06-03] ЕДИНЫЙ арбитр доступа к чипу
        self.pairing_armed = False        # выставляется GUI-intent'ом «add source/speaker»
        self.classic_pairing_discoverable = False
        self.transfer_connectable = False # classic connectable для A2DP (Transfer)
        self.a2dp_open = False
        self.phase = PAIRING

    async def _gate(self, label, operation):
        """[CLAUDE 2026-06-03] ВСЁ, что трогает контроллер, идёт через ОДИН общий гейт —
        тот же, что у a2dp_bridge/iphone_service. Иначе оркестратор флипал видимость, пока
        bridge был в середине connect: «занято / висит / не может подключиться»."""
        if self.hci_gate is None:
            return await operation()
        return await self.hci_gate.run(label, operation)

    # ── идентичность (одно имя на все транспорты) ─────────────────────────────
    async def apply_identity(self):
        name = identity_service.visible_name()
        self.device.name = name
        try:
            await self._gate(
                "orch-write-local-name",
                lambda: self.device.host.send_command(
                    HCI_Write_Local_Name_Command(local_name=name.encode("utf-8"))),
            )
        except Exception as e:
            logger.warning("Write_Local_Name(%s) failed: %s", name, e)

    # ── CTKD-pairing (один pairing → оба ключа в одну логическую сессию) ──────
    def pairing_config_factory(self, connection):
        # sc=True (Secure Connections) — обязателен для CTKD; bonding=True — храним.
        # [CLAUDE 2026-06-02] ПОЧЕМУ CTKD НЕ РАБОТАЛ: дефолтный PairingDelegate раздаёт
        # только ENC|ID (DEFAULT_KEY_DISTRIBUTION=0b0011), БЕЗ link-key флага (0b1000).
        # Поэтому ветка деривации BR/EDR link-key из LTK (bumble smp.py ~стр.970:
        # `if responder_key_distribution & SMP_LINK_KEY_DISTRIBUTION_FLAG`) НИКОГДА не
        # срабатывала → classic-ключ не выводился → айфону приходилось ОТДЕЛЬНО classic-
        # париться = ровно жалоба «сначала BLE, потом Classic, как два устройства».
        # Передаём delegate с SMP_LINK_KEY_DISTRIBUTION_FLAG → теперь ОДНА BLE-пара (sc=True)
        # выводит и LTK/IRK, и BR/EDR link-key (CTKD h6→'lebr') и bumble персистит его в
        # keystore (smp on_pairing → keys.link_key). Одно имя, два транспорта, ОДНА пара.
        # БЕЗОПАСНОСТЬ: меняет ТОЛЬКО рукопожатие НОВОЙ пары; sticky-реконнект по уже
        # сохранённому LTK не трогается. Если телефон не поддержит link-key distribution —
        # AND даст 0 и поведение = прежнее (отдельная classic-пара), без регресса.
        # ЧТОБ ПОЛУЧИТЬ ЭФФЕКТ на уже-спаренном айфоне: «забыть» на телефоне + спарить заново
        # один раз (старый бонд не содержит classic-ключа — он создан до CTKD).
        classic_enabled = os.environ.get("CARTHING_CLASSIC_ENABLE", "1") != "0"
        keydist = (
            PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
            | PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
        )
        # CTKD direction matters:
        # - LE pairing distributes LINK_KEY so BR/EDR can be derived from the LTK.
        # - SMP over BR/EDR keeps the controller-created Link Key and distributes
        #   ENC_KEY so the LE LTK is derived from it. Asking for LINK_KEY again in
        #   that direction can replace the primary Classic key with another
        #   derived key and split the accessory identity.
        from bumble.core import BT_BR_EDR_TRANSPORT
        is_classic = getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT
        if classic_enabled and not is_classic:
            keydist |= PairingDelegate.KeyDistribution.DISTRIBUTE_LINK_KEY
        delegate = PairingDelegate(
            io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT,
            local_initiator_key_distribution=keydist,
            local_responder_key_distribution=keydist,
        )
        return PairingConfig(
            sc=True,
            mitm=False,
            bonding=True,
            ct2=classic_enabled,
            delegate=delegate,
            identity_address_type=PairingConfig.AddressType.PUBLIC,
        )

    def install(self):
        """Повесить pairing_config_factory на Device. Classic-HW держим включённым."""
        self.device.pairing_config_factory = self.pairing_config_factory
        # Configure the controller as a real dual-mode host before power_on().
        # The BLE advertising flags already claim simultaneous LE + BR/EDR;
        # HCI_Write_LE_Host_Support must report the same capability.
        if os.environ.get("CARTHING_CLASSIC_ENABLE", "1") == "0":
            logger.info("classic disabled by CARTHING_CLASSIC_ENABLE=0 for LE-only lab")
            return
        try:
            self.device.le_enabled = True
            self.device.classic_enabled = True
            self.device.le_simultaneous_enabled = True
            self.device.classic_smp_enabled = True
            logger.info("dual-mode host enabled: LE + Classic + simultaneous + SMP/CTKD")
        except Exception as e:
            logger.warning("dual-mode host enable failed: %s", e)

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

        # 1) classic: connectable=True для уже bonded/transfer, но discoverable по умолчанию
        # выключен. iPhone при classic-first создаёт отдельную audio-запись, а последующий
        # BLE-добор становится второй записью с тем же именем. Поэтому source/iPhone pairing
        # должен быть BLE-first; classic discoverable можно включать только для отдельных
        # classic enrollment flows, не для общего iPhone pairing.
        classic_first = os.environ.get("CARTHING_PAIRING_PRIMARY", "").lower() == "classic"
        classic_discoverable = self.pairing_armed and (
            self.classic_pairing_discoverable or classic_first
        )
        await self._set_classic(connectable=True, discoverable=classic_discoverable)

        # 2) BLE advertising по фазе/режиму (рабочая 4-веточная логика коммита):
        #   • активный BLE-коннект → тишина (HCI 0xC). Считаем ТОЛЬКО LE — classic Fosi не глушит.
        #   • pairing_armed → general с именем (видим при сопряжении из меню)
        #   • есть LE-бонд → bonded-only sticky (реконнект к уже-bonded iPhone)
        #   • иначе → ПОЛНАЯ ТИШИНА (нет бонда + не сопряжение)
        ble_connected = self._has_le_connection()
        if ble_connected:
            self._mark_advertising_silent_after_le_connect()
        elif self.pairing_armed and classic_first:
            # Audio-first lab flow: expose exactly one Classic pairing surface.
            # After Classic SSP, SMP over BR/EDR derives the LE bond through CTKD;
            # the user must not have to tap a second BLE row.
            await self._advertise_silent()
        elif self.pairing_armed:
            await self._advertise_general()
        elif le_addr is not None:
            await self._advertise_bonded_only()
        else:
            await self._advertise_silent()

        logger.info("Visibility: phase=%s pairing_armed=%s transfer_conn=%s",
                    phase, self.pairing_armed, self.transfer_connectable)

    # ── BLE advertising примитивы (порт проверенного из media_remote) ─────────
    def _adv_payload(self):
        flags = LE_ONLY_ADV_FLAGS if os.environ.get("CARTHING_CLASSIC_ENABLE", "1") == "0" else DUAL_MODE_ADV_FLAGS
        items = [
            # This is a dual-mode accessory. 0x06 says "BR/EDR Not Supported"
            # and makes the first iPhone pairing look BLE-only, which breaks
            # the single-accessory CTKD/A2DP contract.
            (AdvertisingData.FLAGS, bytes([flags])),
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
        if self._has_le_connection():
            self._mark_advertising_silent_after_le_connect()
            return
        self.device.advertising_data = self._adv_payload()
        self.device.scan_response_data = self._scan_response_payload(with_name=True)
        # [CLAUDE 2026-06-04] После disconnect контроллер может вернуть HCI_COMMAND_DISALLOWED 0xC
        # если ещё не завершил обработку разрыва. Retry с паузой.
        for attempt in range(3):
            try:
                await self._gate("orch-adv-general", lambda: self.device.start_advertising(
                    own_address_type=OwnAddressType.PUBLIC, auto_restart=True))
                logger.info(
                    "General pairing advertising started (public, scan-name, flags=0x%02x %s)",
                    self._advertising_flags(),
                    AdvertisingData.flags_to_string(self._advertising_flags(), short=True),
                )
                return
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(1.0)
                else:
                    logger.warning("general advertising failed after retries: %s", e)

    async def _advertise_directed(self, target):
        await self._stop()
        try:
            await self._gate("orch-refresh-fal", self.device.refresh_filter_accept_list)
        except Exception:
            pass
        try:
            await self._gate("orch-adv-directed", lambda: self.device.start_advertising(
                advertising_type=AdvertisingType.DIRECTED_CONNECTABLE_LOW_DUTY,
                target=target,
                own_address_type=OwnAddressType.PUBLIC,
                auto_restart=True))
        except Exception as e:
            logger.warning("directed advertising failed: %s", e)

    async def _advertise_silent(self):
        await self._stop()

    async def _stop(self):
        if not getattr(self.device, "is_advertising", False):
            return
        try:
            await self._gate("orch-adv-stop", self.device.stop_advertising)
        except Exception:
            pass

    def _has_le_connection(self) -> bool:
        try:
            from bumble.core import BT_BR_EDR_TRANSPORT
            return any(
                getattr(c, "transport", None) != BT_BR_EDR_TRANSPORT
                for c in self.device.connections.values()
            )
        except Exception:
            return False

    def _mark_advertising_silent_after_le_connect(self):
        """Connection complete already makes legacy advertising inactive.

        Some controllers reject an explicit LE Set Advertising Enable=0 after
        that point with COMMAND_DISALLOWED. Drop Bumble's stale local advertiser
        handle instead of sending another HCI command while an LE central is
        connected.
        """
        if getattr(self.device, "legacy_advertiser", None) is not None:
            self.device.legacy_advertiser = None

    async def _set_classic(self, connectable: bool, discoverable: bool):
        if os.environ.get("CARTHING_CLASSIC_ENABLE", "1") == "0":
            return
        for fn_name, val in (("set_connectable", connectable),
                             ("set_discoverable", discoverable)):
            fn = getattr(self.device, fn_name, None)
            if fn is None:
                continue
            try:
                await self._gate(f"orch-{fn_name}", lambda fn=fn, val=val: fn(val))
            except Exception as e:
                logger.warning("%s(%s) failed: %s", fn_name, val, e)

    # ── intents / события (пересчитывают видимость) ──────────────────────────
    async def arm_pairing(self, on: bool, disconnect_current: bool = False,
                          classic_discoverable: bool = False):
        """GUI: вход/выход «Режим сопряжения» (двунаправленный — источники И динамики)."""
        self.pairing_armed = bool(on)
        self.classic_pairing_discoverable = bool(on and classic_discoverable)
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
            if disconnect_current:
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

    async def disconnect_le_connections_for_pairing(self):
        """Free BLE advertising for adding another input without dropping Classic outputs."""
        disconnected = set()
        try:
            from bumble.core import BT_BR_EDR_TRANSPORT
            raw_connections = self.device.connections
            connections = list(raw_connections.values() if hasattr(raw_connections, "values") else raw_connections)
        except Exception:
            connections = []
            BT_BR_EDR_TRANSPORT = object()
        for connection in connections:
            if getattr(connection, "transport", None) == BT_BR_EDR_TRANSPORT:
                continue
            try:
                peer = getattr(connection, "peer_address", connection)
                disconnected.add(str(peer))
                logger.info("Input pairing mode: disconnect current LE peer %s", peer)
                await connection.disconnect()
            except Exception as e:
                logger.warning("input pairing LE disconnect ignored: %s", e)
        for _ in range(10):
            try:
                raw_connections = self.device.connections
                current = list(raw_connections.values() if hasattr(raw_connections, "values") else raw_connections)
                if not any(getattr(c, "transport", None) != BT_BR_EDR_TRANSPORT for c in current):
                    break
            except Exception:
                break
            await asyncio.sleep(0.2)
        return disconnected

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

    def _advertising_flags(self):
        if os.environ.get("CARTHING_CLASSIC_ENABLE", "1") == "0":
            return LE_ONLY_ADV_FLAGS
        return DUAL_MODE_ADV_FLAGS

    async def set_transfer_connectable(self, on: bool):
        """Transfer: открыть classic для входящего A2DP (link-key уже есть из CTKD)."""
        self.transfer_connectable = bool(on)
        await self.apply_visibility()

    async def on_bonded(self):
        """Вызывать после успешного SMP-бонда (CTKD мог положить и LE, и classic ключ)."""
        # успешная пара → снять armed, перейти к directed/тишине по фазе.
        self.pairing_armed = False
        await self.apply_visibility()

    async def on_le_connection_started(self):
        """A central has already selected this advertising surface.

        Stop general pairing advertising immediately so iOS does not keep a
        second discovery row with the scan-response name while the real bonded
        row is being created/renamed in Settings.
        """
        self.pairing_armed = False
        self.classic_pairing_discoverable = False
        await self._advertise_silent()

    async def on_a2dp_state(self, opened: bool):
        self.a2dp_open = bool(opened)
        await self.apply_visibility()

    async def on_disconnect(self):
        await asyncio.sleep(0.5)   # дать контроллеру осесть (иначе start_advertising = 0xC)
        await self.kick_reconnect()

    async def _advertise_bonded_only(self):
        """НЕПРЕРЫВНАЯ undirected bonded reconnect — БЕЗ ИМЕНИ в scan response.
        [CLAUDE 2026-06-03] Имя убрано: неспаренные не должны видеть «Car Thing (SN)». Уже
        bonded iPhone реконнектит HID-периферию по БОНДУ + HID-service UUID + адресу, имя ему
        для реконнекта не нужно (оно нужно только для человеко-видимого discovery в режиме
        сопряжения -> _advertise_general). Так девайс вне сопряжения анонимен для чужих."""
        await self._stop()
        try:
            await self._gate("orch-refresh-fal", self.device.refresh_filter_accept_list)
        except Exception:
            pass
        if self._has_le_connection():
            self._mark_advertising_silent_after_le_connect()
            return
        self.device.advertising_data = self._adv_payload()
        self.device.scan_response_data = self._scan_response_payload(with_name=False)
        # [CLAUDE 2026-06-01] быстрый интервал -> iPhone обнаруживает для реконнекта почти мгновенно
        self.device.advertising_interval_min = STICKY_ADV_INTERVAL_MS
        self.device.advertising_interval_max = STICKY_ADV_INTERVAL_MS
        try:
            await self._gate("orch-adv-bonded", lambda: self.device.start_advertising(
                own_address_type=OwnAddressType.PUBLIC,
                auto_restart=True,
                advertising_filter_policy=0x00))
            logger.info("Sticky: continuous bonded reconnect advertising (public, NO-name, %dms)",
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
