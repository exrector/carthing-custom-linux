"""Single-owner serialization for HCI operations."""

import asyncio


class HciOperationGate:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def run(self, _label, operation):
        async with self._lock:
            return await operation()
