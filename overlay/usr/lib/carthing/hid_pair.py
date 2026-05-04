"""
BLE HID Consumer Control — Media Remote для iPhone.
HID service UUID 0x1812 в advertising → iPhone показывает в BT Settings.
"""
import asyncio, logging, struct
from runtime_paths import BD_ADDRESS, KEYSTORE_PATH, TRANSPORT
from bumble.device import Device, OwnAddressType, AdvertisingData
from bumble.host import Host
from bumble.transport import open_transport_or_link
from bumble.gatt import Service, Characteristic, Descriptor
from bumble.core import UUID
from bumble.smp import PairingConfig
from bumble.keys import JsonKeyStore

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

GAP_SERVICE_UUID        = UUID.from_16_bits(0x1800)
GATT_SERVICE_UUID       = UUID.from_16_bits(0x1801)
BATTERY_SERVICE_UUID    = UUID.from_16_bits(0x180F)
HID_SERVICE_UUID        = UUID.from_16_bits(0x1812)

DEVICE_NAME_UUID        = UUID.from_16_bits(0x2A00)
APPEARANCE_UUID         = UUID.from_16_bits(0x2A01)
BATTERY_LEVEL_UUID      = UUID.from_16_bits(0x2A19)
HID_INFORMATION_UUID    = UUID.from_16_bits(0x2A4A)
REPORT_MAP_UUID         = UUID.from_16_bits(0x2A4B)
HID_CONTROL_POINT_UUID  = UUID.from_16_bits(0x2A4C)
REPORT_UUID             = UUID.from_16_bits(0x2A4D)
PROTOCOL_MODE_UUID      = UUID.from_16_bits(0x2A4E)

CCCD_UUID               = UUID.from_16_bits(0x2902)
REPORT_REFERENCE_UUID   = UUID.from_16_bits(0x2908)

HID_REPORT_MAP = bytes([
    0x05, 0x0C,        # Usage Page (Consumer)
    0x09, 0x01,        # Usage (Consumer Control)
    0xA1, 0x01,        # Collection (Application)
    0x85, 0x01,        #   Report ID (1)
    0x15, 0x00,        #   Logical Minimum (0)
    0x25, 0x01,        #   Logical Maximum (1)
    0x75, 0x01,        #   Report Size (1 bit)
    0x95, 0x05,        #   Report Count (5)
    0x09, 0xCD,        #   Usage (Play/Pause)
    0x09, 0xB5,        #   Usage (Scan Next Track)
    0x09, 0xB6,        #   Usage (Scan Previous Track)
    0x09, 0xE9,        #   Usage (Volume Increment)
    0x09, 0xEA,        #   Usage (Volume Decrement)
    0x81, 0x02,        #   Input (Data, Variable, Absolute)
    0x95, 0x03,        #   Report Count (3 bits padding)
    0x81, 0x03,        #   Input (Constant)
    0xC0,              # End Collection
])

HID_INFORMATION = struct.pack("<HBB", 0x0111, 0x00, 0x03)


def on_connection(conn):
    log.info(">>> Подключился: %s", conn.peer_address)
    conn.on("pairing_start", lambda: log.info(">>> SMP: pairing started"))
    conn.on("pairing", lambda keys: log.info("=== BONDING COMPLETE! keys=%s ===", keys))
    conn.on("pairing_failure", lambda reason: log.error("!!! PAIRING FAILED: reason=%s", reason))
    conn.on("disconnection", lambda reason: log.info(">>> Отключился: reason=0x%02x", reason))
    # Peripheral requests pairing from Central (iPhone) via SMP Security Request
    conn.request_pairing()


async def main():
    transport = await open_transport_or_link(TRANSPORT)
    device = Device(
        name="CarThing",
        address=BD_ADDRESS,
        host=Host(controller_source=transport.source, controller_sink=transport.sink),
    )
    device.keystore = JsonKeyStore("CarThing", str(KEYSTORE_PATH))

    device.add_service(Service(GAP_SERVICE_UUID, [
        Characteristic(DEVICE_NAME_UUID,
                       Characteristic.READ, Characteristic.READABLE,
                       b"CarThing"),
        Characteristic(APPEARANCE_UUID,
                       Characteristic.READ, Characteristic.READABLE,
                       struct.pack("<H", 0x0180)),
    ]))
    device.add_service(Service(GATT_SERVICE_UUID, []))
    device.add_service(Service(BATTERY_SERVICE_UUID, [
        Characteristic(BATTERY_LEVEL_UUID,
                       Characteristic.READ | Characteristic.NOTIFY,
                       Characteristic.READABLE,
                       bytes([100])),
    ]))

    report_char = Characteristic(
        REPORT_UUID,
        Characteristic.READ | Characteristic.NOTIFY,
        Characteristic.READABLE,
        bytes([0x00]),
        descriptors=[
            Descriptor(CCCD_UUID,
                       Descriptor.READABLE | Descriptor.WRITEABLE,
                       bytes([0x00, 0x00])),
            Descriptor(REPORT_REFERENCE_UUID,
                       Descriptor.READABLE,
                       bytes([0x01, 0x01])),
        ],
    )

    device.add_service(Service(HID_SERVICE_UUID, [
        Characteristic(HID_INFORMATION_UUID,
                       Characteristic.READ, Characteristic.READABLE,
                       HID_INFORMATION),
        Characteristic(REPORT_MAP_UUID,
                       Characteristic.READ, Characteristic.READABLE,
                       HID_REPORT_MAP),
        Characteristic(PROTOCOL_MODE_UUID,
                       Characteristic.READ | Characteristic.WRITE_WITHOUT_RESPONSE,
                       Characteristic.READABLE | Characteristic.WRITEABLE,
                       bytes([0x01])),
        report_char,
        Characteristic(HID_CONTROL_POINT_UUID,
                       Characteristic.WRITE_WITHOUT_RESPONSE,
                       Characteristic.WRITEABLE,
                       bytes([0x00])),
    ]))

    device.pairing_config_factory = lambda conn: PairingConfig(
        sc=True, mitm=False, bonding=True
    )
    device.on("connection", on_connection)

    await device.power_on()

    device.advertising_data = bytes(AdvertisingData([
        (AdvertisingData.FLAGS, bytes([0x06])),
        (AdvertisingData.APPEARANCE, struct.pack("<H", 0x0180)),
        (AdvertisingData.COMPLETE_LIST_OF_16_BIT_SERVICE_CLASS_UUIDS,
         struct.pack("<H", 0x1812)),
        (AdvertisingData.COMPLETE_LOCAL_NAME, b"CarThing"),
    ]))

    await device.start_advertising(
        own_address_type=OwnAddressType.PUBLIC,
        auto_restart=True,
    )
    log.info("BLE HID рекламируется. iPhone → Настройки → Bluetooth → 'CarThing'")

    await asyncio.get_event_loop().create_future()

asyncio.run(main())
