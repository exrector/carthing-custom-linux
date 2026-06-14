import asyncio
import logging
import os
from runtime_paths import BD_ADDRESS, KEYSTORE_PATH, TRANSPORT
from bumble.device import Device
from bumble.host import Host
from bumble.transport import open_transport_or_link
from bumble.keys import JsonKeyStore

logger = logging.getLogger(__name__)


async def init_ble(configure_device=None, on_ready=None):
    logger.info("Opening transport %s", TRANSPORT)
    transport = await open_transport_or_link(TRANSPORT)

    device_name = os.environ.get("CARTHING_BT_ALIAS") or os.environ.get("CARTHING_A2DP_NAME") or "CarThing"

    device = Device(
        name=device_name,
        address=BD_ADDRESS,
        host=Host(
            controller_source=transport.source,
            controller_sink=transport.sink,
        ),
    )
    device.keystore = JsonKeyStore("CarThing", str(KEYSTORE_PATH))

    if configure_device:
        configure_device(device)

    await device.power_on()
    logger.info("BLE device ON — address: %s", device.public_address)

    if on_ready:
        await on_ready(device)

    return device, transport
