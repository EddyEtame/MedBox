"""In-process publish/subscribe for live telemetry.

Every connected screen gets its own bounded queue. A slow or wedged client
drops its oldest frames instead of applying backpressure to the sensor loop —
a screen that cannot keep up must never be able to stall a measurement.
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any, AsyncIterator

# A screen only ever needs the newest state, so this can stay small.
QUEUE_SIZE = 32


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self.dropped = 0

    def publish(self, message: dict[str, Any]) -> None:
        """Never blocks, never raises. Safe to call from the sensor loop."""
        for q in list(self._subscribers):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                # Discard this client's oldest frame and keep the newest.
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                    self.dropped += 1
                with contextlib.suppress(asyncio.QueueFull):
                    q.put_nowait(message)

    @contextlib.asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue]:
        q: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_SIZE)
        self._subscribers.add(q)
        try:
            yield q
        finally:
            self._subscribers.discard(q)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


BUS = EventBus()
