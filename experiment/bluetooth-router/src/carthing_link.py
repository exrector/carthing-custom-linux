"""Car Thing Link — custom GATT service for bidirectional messaging.

Wire model mirrors the Nordic UART Service: a peer writes to RX, the
device replies via TX notifications. The framing is line-oriented JSON,
one logical message per BLE packet (caller splits chunks larger than the
negotiated MTU).

Service:  6E7C0001-A37C-4D6D-8C3F-2B7C5E8D9F11
RX char:  6E7C0002-...  (Write / WriteWithoutResponse, peer -> device)
TX char:  6E7C0003-...  (Notify, device -> peer)

The handler interface is intentionally minimal: register a coroutine
`async def on_message(self, payload: bytes) -> bytes | None`. Returning
bytes triggers an immediate notification; returning None stays silent.
Multiple async listeners are supported via add_listener().
"""

import asyncio
import json
import logging

from runtime_paths import ensure_runtime_paths

ensure_runtime_paths()

from bumble.core import UUID
from bumble.gatt import Characteristic, Service

logger = logging.getLogger(__name__)

LINK_SERVICE_UUID = UUID("6E7C0001-A37C-4D6D-8C3F-2B7C5E8D9F11")
LINK_RX_UUID      = UUID("6E7C0002-A37C-4D6D-8C3F-2B7C5E8D9F11")
LINK_TX_UUID      = UUID("6E7C0003-A37C-4D6D-8C3F-2B7C5E8D9F11")


class CarThingLink:
    def __init__(self):
        self._listeners: list = []
        self._tx_char: Characteristic | None = None
        self._device = None
        self._rx_char: Characteristic | None = None

    def install(self, device) -> None:
        self._device = device

        rx_char = Characteristic(
            LINK_RX_UUID,
            Characteristic.WRITE | Characteristic.WRITE_WITHOUT_RESPONSE,
            Characteristic.WRITEABLE,
            bytes(),
        )
        rx_char.on("write", self._on_rx_write)

        tx_char = Characteristic(
            LINK_TX_UUID,
            Characteristic.NOTIFY,
            Characteristic.READABLE,
            bytes(),
        )

        device.add_service(Service(LINK_SERVICE_UUID, [rx_char, tx_char]))
        self._rx_char = rx_char
        self._tx_char = tx_char
        logger.info("CarThingLink: service installed")

    def add_listener(self, handler) -> None:
        """Register `async def handler(payload: bytes) -> bytes | None`."""
        self._listeners.append(handler)

    def _on_rx_write(self, connection, value):
        payload = bytes(value)
        logger.info("link RX %d bytes from %s: %r",
                    len(payload), getattr(connection, "peer_address", "?"), payload[:64])
        asyncio.ensure_future(self._dispatch(payload))

    async def _dispatch(self, payload: bytes):
        for handler in list(self._listeners):
            try:
                response = await handler(payload)
            except Exception as exc:
                logger.exception("link handler error: %s", exc)
                continue
            if response is not None:
                await self.send(response)

    async def send(self, payload: bytes) -> None:
        if self._tx_char is None or self._device is None:
            logger.warning("link: send called before install()")
            return
        try:
            self._tx_char.value = payload
            await self._device.notify_subscribers(self._tx_char, payload)
            logger.info("link TX %d bytes: %r", len(payload), payload[:64])
        except Exception as exc:
            logger.warning("link send error: %s", exc)

    async def send_json(self, obj) -> None:
        await self.send(json.dumps(obj, ensure_ascii=False).encode("utf-8"))
