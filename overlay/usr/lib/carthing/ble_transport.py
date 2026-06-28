import asyncio
import logging
import socket
from runtime_paths import BD_ADDRESS, KEYSTORE_PATH, TRANSPORT, device_name, name_from_mac
from bumble.device import Device
from bumble.host import Host
from bumble.transport import open_transport_or_link
from bumble.keys import JsonKeyStore

logger = logging.getLogger(__name__)


async def init_ble(configure_device=None, on_ready=None):
    logger.info("Opening transport %s", TRANSPORT)
    transport = await open_transport_or_link(TRANSPORT)

    device = Device(
        name=device_name(),                 # provisional (hostname/config) until power_on
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

    # device_name() is the cross-layer identity source: factory efuse serial
    # first, then explicit config, then hostname/MAC fallback.
    real_mac = str(device.public_address).split("/")[0]
    unique = device_name() or name_from_mac(real_mac)
    logger.info("Controller public address: %s  -> name=%s", real_mac, unique)

    device.name = unique
    try:
        socket.sethostname(unique)
    except Exception as e:
        logger.warning("sethostname(%s) failed: %s", unique, e)
    logger.info("BLE device ON — address: %s  name: %s", device.public_address, unique)

    if on_ready:
        await on_ready(device)

    return device, transport
