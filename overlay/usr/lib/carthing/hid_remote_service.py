"""Minimal HID-over-GATT profile for the iPhone Play Now connection."""

import asyncio
import logging
import struct

from bumble.core import UUID
from bumble.gatt import Characteristic, Descriptor, Service

logger = logging.getLogger(__name__)

GATT_SERVICE_UUID = UUID.from_16_bits(0x1801)
BATTERY_SERVICE_UUID = UUID.from_16_bits(0x180F)
HID_SERVICE_UUID = UUID.from_16_bits(0x1812)
BATTERY_LEVEL_UUID = UUID.from_16_bits(0x2A19)
HID_INFORMATION_UUID = UUID.from_16_bits(0x2A4A)
REPORT_MAP_UUID = UUID.from_16_bits(0x2A4B)
HID_CONTROL_POINT_UUID = UUID.from_16_bits(0x2A4C)
REPORT_UUID = UUID.from_16_bits(0x2A4D)
PROTOCOL_MODE_UUID = UUID.from_16_bits(0x2A4E)
CCCD_UUID = UUID.from_16_bits(0x2902)
REPORT_REFERENCE_UUID = UUID.from_16_bits(0x2908)

HID_REPORT_MAP = bytes(
    [
        0x05, 0x0C,
        0x09, 0x01,
        0xA1, 0x01,
        0x85, 0x01,
        0x15, 0x00,
        0x25, 0x01,
        0x75, 0x01,
        0x95, 0x05,
        0x09, 0xCD,
        0x09, 0xB5,
        0x09, 0xB6,
        0x09, 0xE9,
        0x09, 0xEA,
        0x81, 0x02,
        0x95, 0x03,
        0x81, 0x03,
        0xC0,
    ]
)
HID_INFORMATION = struct.pack("<HBB", 0x0111, 0x00, 0x03)
CONSUMER_USAGE_BITS = {
    "play_pause": 0x01,
    "next": 0x02,
    "prev": 0x04,
    "vol_up": 0x08,
    "vol_down": 0x10,
}

_device = None
_report_char = None
_send_lock = None


def install_hid_remote_profile(device):
    global _device, _report_char

    report_char = Characteristic(
        REPORT_UUID,
        Characteristic.READ | Characteristic.NOTIFY,
        Characteristic.READABLE,
        bytes([0x00]),
        descriptors=[
            Descriptor(
                CCCD_UUID,
                Descriptor.READABLE | Descriptor.WRITEABLE,
                bytes([0x00, 0x00]),
            ),
            Descriptor(
                REPORT_REFERENCE_UUID,
                Descriptor.READABLE,
                bytes([0x01, 0x01]),
            ),
        ],
    )
    _device = device
    _report_char = report_char
    device.add_service(Service(GATT_SERVICE_UUID, []))
    device.add_service(
        Service(
            BATTERY_SERVICE_UUID,
            [
                Characteristic(
                    BATTERY_LEVEL_UUID,
                    Characteristic.READ | Characteristic.NOTIFY,
                    Characteristic.READABLE,
                    bytes([100]),
                )
            ],
        )
    )
    device.add_service(
        Service(
            HID_SERVICE_UUID,
            [
                Characteristic(
                    HID_INFORMATION_UUID,
                    Characteristic.READ,
                    Characteristic.READABLE,
                    HID_INFORMATION,
                ),
                Characteristic(
                    REPORT_MAP_UUID,
                    Characteristic.READ,
                    Characteristic.READABLE,
                    HID_REPORT_MAP,
                ),
                Characteristic(
                    PROTOCOL_MODE_UUID,
                    Characteristic.READ | Characteristic.WRITE_WITHOUT_RESPONSE,
                    Characteristic.READABLE | Characteristic.WRITEABLE,
                    bytes([0x01]),
                ),
                report_char,
                Characteristic(
                    HID_CONTROL_POINT_UUID,
                    Characteristic.WRITE_WITHOUT_RESPONSE,
                    Characteristic.WRITEABLE,
                    bytes([0x00]),
                ),
            ],
        )
    )
    logger.info("minimal HID remote profile installed")


async def send_consumer_usage(command):
    global _send_lock

    value = CONSUMER_USAGE_BITS.get(str(command))
    if value is None or _device is None or _report_char is None:
        return False
    if _send_lock is None:
        _send_lock = asyncio.Lock()
    async with _send_lock:
        await _device.notify_subscribers(_report_char, bytes([value]))
        await asyncio.sleep(0.035)
        await _device.notify_subscribers(_report_char, bytes([0x00]))
    logger.info("HID consumer usage sent: %s", command)
    return True
