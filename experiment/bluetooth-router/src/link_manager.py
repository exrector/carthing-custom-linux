"""Idle trusted-device link manager.

The link manager owns "hot inventory": trusted devices may be connected or
periodically probed without creating media traffic. Active sessions request
routes separately through SessionRunner.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from route_graph import Constraint, TrustedDevice

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class LinkAdapter:
    name: str

    async def probe(self, device: TrustedDevice) -> bool:
        return False

    async def connect_idle(self, device: TrustedDevice) -> bool:
        return False

    async def disconnect_idle(self, device: TrustedDevice) -> None:
        pass


class LinkManager:
    def __init__(self, registry, interval: float = 20.0):
        self.registry = registry
        self.interval = interval
        self.adapters: list[LinkAdapter] = []
        self._task: asyncio.Task | None = None
        self._running = False

    def register(self, adapter: LinkAdapter):
        self.adapters.append(adapter)

    def start(self):
        if self._task is None or self._task.done():
            self._running = True
            self._task = asyncio.create_task(self._loop())

    async def stop(self):
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def tick(self):
        for device in list(self.registry.devices):
            if not device.trusted:
                continue
            if Constraint.IDLE_LINK_ALLOWED not in device.constraints and "idle_link_allowed" not in device.constraints:
                continue
            await self._refresh_device(device)

    async def _loop(self):
        while self._running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("link manager tick failed: %s", exc)
            await asyncio.sleep(self.interval)

    async def _refresh_device(self, device: TrustedDevice):
        for adapter in self.adapters:
            try:
                if await adapter.probe(device):
                    device.online = True
                    if not device.connected:
                        device.connected = await adapter.connect_idle(device)
                    return
            except Exception as exc:
                logger.info("link adapter ignored: %s %s: %s", adapter.name, device.name, exc)
        if device.connected:
            for adapter in self.adapters:
                try:
                    await adapter.disconnect_idle(device)
                except Exception as exc:
                    logger.info("link adapter disconnect ignored: %s %s: %s", adapter.name, device.name, exc)
        device.online = False
        device.connected = False
