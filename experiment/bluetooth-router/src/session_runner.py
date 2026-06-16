"""Session runner for planned Car Thing route graphs.

This is deliberately above Bumble/HCI/USB. It owns session start/stop order and
delegates real protocol work to adapter connectors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from route_graph import PlannedSession, Protocol

logger = logging.getLogger(__name__)


class AdapterConnector:
    """Base class for concrete BLE/A2DP/USB connectors."""

    protocol: Protocol | str = ""

    async def start(self):
        pass

    async def stop(self):
        pass

    async def attach_session(self, session: PlannedSession):
        pass

    async def detach_session(self, session: PlannedSession):
        pass


@dataclass(slots=True)
class RunningSession:
    plan: PlannedSession
    connectors: list[AdapterConnector] = field(default_factory=list)


class SessionRunner:
    def __init__(self):
        self.connectors: dict[Protocol | str, AdapterConnector] = {}
        self.current: RunningSession | None = None

    def register(self, connector: AdapterConnector):
        if not connector.protocol:
            raise ValueError("connector.protocol is required")
        self.connectors[connector.protocol] = connector

    async def stop_current(self):
        running = self.current
        if running is None:
            return
        logger.info("session stop: %s", running.plan.name)
        for connector in reversed(running.connectors):
            try:
                await connector.detach_session(running.plan)
            except Exception as exc:
                logger.warning("connector detach failed: %s: %s", connector.protocol, exc)
        for connector in reversed(running.connectors):
            try:
                await connector.stop()
            except Exception as exc:
                logger.warning("connector stop failed: %s: %s", connector.protocol, exc)
        self.current = None

    async def start(self, plan: PlannedSession):
        await self.stop_current()
        connectors = []
        missing = []
        for protocol in sorted(plan.required_protocols, key=lambda item: str(item.value if hasattr(item, "value") else item)):
            connector = self.connectors.get(protocol)
            if connector is None:
                missing.append(protocol)
            else:
                connectors.append(connector)
        if missing:
            readable = ", ".join(str(item.value if hasattr(item, "value") else item) for item in missing)
            raise RuntimeError(f"missing adapter connectors: {readable}")

        logger.info("session start: %s", plan.name)
        for connector in connectors:
            await connector.start()
        for connector in connectors:
            await connector.attach_session(plan)
        self.current = RunningSession(plan=plan, connectors=connectors)

