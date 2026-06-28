"""Single Bluetooth owner for the minimal LE-only Car Thing product."""

import asyncio
import logging
import struct

from bumble.core import UUID
from bumble.device import AdvertisingData, Device
from bumble.hci import (
    Address,
    HCI_LE_Set_Random_Address_Command,
    OwnAddressType,
)
from bumble.pairing import PairingConfig, PairingDelegate

import identity_service


logger = logging.getLogger(__name__)

APPEARANCE_REMOTE = 0x0180
HID_SERVICE_UUID = 0x1812
SESSION_SERVICE_UUID = "C7C50000-0000-4000-8000-00C7C7C7C7C7"
STICKY_ADV_INTERVAL_MS = 60
LE_ONLY_FLAGS = (
    AdvertisingData.LE_GENERAL_DISCOVERABLE_MODE_FLAG
    | AdvertisingData.BR_EDR_NOT_SUPPORTED_FLAG
)


class AccessoryOrchestrator:
    """Own iPhone advertising and the short CTSP bootstrap window."""

    def __init__(self, device: Device, on_phase_change=None, hci_gate=None):
        self.device = device
        self.on_phase_change = on_phase_change
        self.hci_gate = hci_gate
        self.pairing_armed = False
        self.media_connected = False
        self.session_connected = False
        self.session_bootstrap_active = False
        self.phase = "idle"
        self._session_timeout_task = None

    async def _gate(self, label, operation):
        if self.hci_gate is None:
            return await operation()
        return await self.hci_gate.run(label, operation)

    def _set_phase(self, phase):
        if phase == self.phase:
            return
        self.phase = phase
        if self.on_phase_change is not None:
            try:
                self.on_phase_change(phase)
            except Exception:
                pass

    async def apply_identity(self):
        name = identity_service.visible_name()
        self.device.name = name

    def pairing_config_factory(self, _connection):
        key_distribution = (
            PairingDelegate.KeyDistribution.DISTRIBUTE_ENCRYPTION_KEY
            | PairingDelegate.KeyDistribution.DISTRIBUTE_IDENTITY_KEY
        )
        delegate = PairingDelegate(
            io_capability=PairingDelegate.NO_OUTPUT_NO_INPUT,
            local_initiator_key_distribution=key_distribution,
            local_responder_key_distribution=key_distribution,
        )
        return PairingConfig(
            sc=True,
            mitm=False,
            bonding=True,
            ct2=False,
            delegate=delegate,
            identity_address_type=PairingConfig.AddressType.PUBLIC,
        )

    def install(self):
        self.device.pairing_config_factory = self.pairing_config_factory
        self.device.le_enabled = True
        self.device.classic_enabled = False
        self.device.le_simultaneous_enabled = False
        self.device.classic_smp_enabled = False
        logger.info("minimal Bluetooth host installed: LE only")

    async def _bonded_address(self):
        try:
            keystore = getattr(self.device, "keystore", None)
            if keystore is None:
                return None
            for name, keys in reversed(await keystore.get_all()):
                if getattr(keys, "ltk", None) or getattr(keys, "irk", None):
                    return Address(name)
        except Exception as error:
            logger.warning("bond inspection failed: %s", error)
        return None

    def _iphone_payload(self):
        return bytes(
            AdvertisingData(
                [
                    (AdvertisingData.FLAGS, bytes([LE_ONLY_FLAGS])),
                    (
                        AdvertisingData.APPEARANCE,
                        struct.pack("<H", APPEARANCE_REMOTE),
                    ),
                    (
                        AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
                        struct.pack("<H", HID_SERVICE_UUID),
                    ),
                ]
            )
        )

    def _scan_response(self, include_name):
        if not include_name:
            return b""
        return bytes(
            AdvertisingData(
                [
                    (
                        AdvertisingData.COMPLETE_LOCAL_NAME,
                        identity_service.visible_name().encode("utf-8"),
                    )
                ]
            )
        )

    def _session_payload(self):
        return bytes(
            AdvertisingData(
                [
                    (AdvertisingData.FLAGS, bytes([LE_ONLY_FLAGS])),
                    (
                        AdvertisingData.COMPLETE_LIST_OF_128_BIT_SERVICE_CLASS_UUIDS,
                        UUID(SESSION_SERVICE_UUID).to_bytes(force_128=True),
                    ),
                ]
            )
        )

    def _session_random_address(self):
        parts = str(self.device.public_address).split("/", 1)[0].split(":")
        parts[0] = f"{(int(parts[0], 16) | 0xC0) ^ 0x01:02X}"
        return Address(":".join(parts), Address.RANDOM_DEVICE_ADDRESS)

    async def _stop_advertising(self):
        if not getattr(self.device, "is_advertising", False):
            return
        try:
            await self._gate("advertising-stop", self.device.stop_advertising)
        except Exception as error:
            if "COMMAND_DISALLOWED" in str(error):
                self._clear_stale_advertiser()
            else:
                logger.warning("advertising stop failed: %s", error)

    def _clear_stale_advertiser(self):
        if getattr(self.device, "legacy_advertiser", None) is not None:
            self.device.legacy_advertiser = None

    async def _advertise_iphone(self, include_name, allow_connected=False):
        await self._stop_advertising()
        if self._has_le_connection() and not allow_connected:
            self._clear_stale_advertiser()
            return
        try:
            await self._gate(
                "filter-accept-list",
                self.device.refresh_filter_accept_list,
            )
        except Exception:
            pass
        self.device.advertising_data = self._iphone_payload()
        self.device.scan_response_data = self._scan_response(include_name)
        self.device.advertising_interval_min = STICKY_ADV_INTERVAL_MS
        self.device.advertising_interval_max = STICKY_ADV_INTERVAL_MS
        for attempt in range(3):
            try:
                await self._gate(
                    "iphone-advertising",
                    lambda: self.device.start_advertising(
                        own_address_type=OwnAddressType.PUBLIC,
                        auto_restart=False,
                        advertising_filter_policy=0x00,
                    ),
                )
                logger.info(
                    "%s iPhone advertising started",
                    "Pairing" if include_name else "Sticky",
                )
                return
            except Exception as error:
                if attempt == 2:
                    logger.warning("iPhone advertising failed: %s", error)
                else:
                    await asyncio.sleep(0.7)

    async def apply_visibility(self):
        bonded = await self._bonded_address()
        if self.media_connected:
            self._set_phase("iphone_connected")
            await self._stop_advertising()
        elif self.pairing_armed:
            self._set_phase("iphone_pairing")
            await self._advertise_iphone(include_name=True)
        elif bonded is not None:
            self._set_phase("iphone_sticky")
            await self._advertise_iphone(include_name=False)
        else:
            self._set_phase("idle")
            await self._stop_advertising()
        logger.info(
            "Bluetooth phase=%s pairing=%s session=%s",
            self.phase,
            self.pairing_armed,
            self.session_connected,
        )

    def _has_le_connection(self):
        try:
            return bool(self.device.connections)
        except Exception:
            return False

    async def _disconnect_all(self):
        try:
            connections = list(self.device.connections.values())
        except Exception:
            connections = []
        for connection in connections:
            try:
                await connection.disconnect()
            except Exception as error:
                logger.warning("connection cleanup failed: %s", error)
        for _ in range(10):
            if not self._has_le_connection():
                break
            await asyncio.sleep(0.2)

    async def _disable_resolution_for_pairing(self):
        from bumble.hci import (
            HCI_LE_Clear_Resolving_List_Command,
            HCI_LE_Set_Address_Resolution_Enable_Command,
        )

        await self._stop_advertising()
        try:
            await self._gate(
                "resolution-disable",
                lambda: self.device.send_command(
                    HCI_LE_Set_Address_Resolution_Enable_Command(
                        address_resolution_enable=0
                    )
                ),
            )
            await self._gate(
                "resolution-clear",
                lambda: self.device.send_command(
                    HCI_LE_Clear_Resolving_List_Command()
                ),
            )
            logger.info("address resolution cleared for fresh iPhone pairing")
        except Exception as error:
            logger.warning("address resolution cleanup failed: %s", error)

    async def arm_pairing(
        self,
        on,
        disconnect_current=False,
        classic_discoverable=False,
    ):
        del classic_discoverable
        self.pairing_armed = bool(on)
        if on:
            if disconnect_current:
                await self._disconnect_all()
            await self._disable_resolution_for_pairing()
            self.media_connected = False
            self.session_connected = False
            self.session_bootstrap_active = False
        await self.apply_visibility()

    async def on_bonded(self):
        self.pairing_armed = False
        await self.apply_visibility()

    async def on_le_connection_started(self):
        self.pairing_armed = False
        self.media_connected = True
        self._set_phase("iphone_connected")
        self._clear_stale_advertiser()

    async def on_disconnect(self):
        self.media_connected = False
        await asyncio.sleep(0.5)
        if self.media_connected:
            logger.info("stale iPhone disconnect recovery cancelled")
            return
        if self.pairing_armed:
            await self.apply_visibility()
            return
        await self._advertise_iphone(
            include_name=False,
            allow_connected=self.session_connected,
        )
        self._set_phase("iphone_sticky")

    async def kick_reconnect(self):
        await self.apply_visibility()

    def is_session_connection(self):
        return bool(
            self.session_bootstrap_active and not self.session_connected
        )

    async def start_session_bootstrap(self, timeout=10.0):
        if self.session_connected or self.session_bootstrap_active:
            return
        await self._stop_advertising()
        random_address = self._session_random_address()
        try:
            await self._gate(
                "session-random-address",
                lambda: self.device.send_command(
                    HCI_LE_Set_Random_Address_Command(
                        random_address=random_address
                    )
                ),
            )
            self.device.random_address = random_address
            self.device.advertising_data = self._session_payload()
            self.device.scan_response_data = bytes(
                AdvertisingData(
                    [
                        (
                            AdvertisingData.COMPLETE_LOCAL_NAME,
                            b"Car Thing Assistant",
                        )
                    ]
                )
            )
            self.device.advertising_interval_min = STICKY_ADV_INTERVAL_MS
            self.device.advertising_interval_max = STICKY_ADV_INTERVAL_MS
            await self._gate(
                "session-advertising",
                lambda: self.device.start_advertising(
                    own_address_type=OwnAddressType.RANDOM,
                    auto_restart=False,
                    advertising_filter_policy=0x00,
                ),
            )
            self.session_bootstrap_active = True
            logger.info(
                "CTSP bootstrap advertising started: %s", random_address
            )
        except Exception as error:
            self.session_bootstrap_active = False
            logger.warning("CTSP bootstrap failed: %s", error)
            return
        if self._session_timeout_task is not None:
            self._session_timeout_task.cancel()
        self._session_timeout_task = asyncio.create_task(
            self._session_timeout(float(timeout))
        )

    async def _session_timeout(self, timeout):
        try:
            await asyncio.sleep(timeout)
            if not self.session_bootstrap_active:
                return
            self.session_bootstrap_active = False
            await self._stop_advertising()
            if not self.media_connected:
                await self._advertise_iphone(
                    include_name=False,
                    allow_connected=True,
                )
        except asyncio.CancelledError:
            pass

    async def on_session_connection_started(self):
        self.session_connected = True
        self.session_bootstrap_active = False
        if self._session_timeout_task is not None:
            self._session_timeout_task.cancel()
            self._session_timeout_task = None
        self._clear_stale_advertiser()
        logger.info("CTSP peer attached")
        if not self.media_connected:
            await self._advertise_iphone(
                include_name=False,
                allow_connected=True,
            )

    async def on_session_disconnect(self):
        self.session_connected = False
        self.session_bootstrap_active = False
        await asyncio.sleep(0.5)
        if self.pairing_armed:
            await self.apply_visibility()
            return
        if not self.media_connected:
            await self._advertise_iphone(
                include_name=False,
                allow_connected=True,
            )
            await asyncio.sleep(8.0)
            if self.media_connected:
                return
        await self.start_session_bootstrap()
