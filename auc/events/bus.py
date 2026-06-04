from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from auc.types import AgentId, RunEventType, RunId


@dataclass
class RunEvent:
    type: RunEventType
    run_id: RunId
    agent_id: AgentId
    payload: dict[str, Any]
    timestamp: float | None = None


Unsubscribe = Callable[[], None]


@dataclass
class EventBus:
    _handlers: list[Callable[[RunEvent], None]] = field(default_factory=list)
    _queues: list[asyncio.Queue[RunEvent | None]] = field(default_factory=list)

    def emit(self, event: RunEvent) -> None:
        if event.timestamp is None:
            event.timestamp = time.time()
        for h in list(self._handlers):
            h(event)
        for q in list(self._queues):
            q.put_nowait(event)

    def emit_typed(
        self,
        etype: RunEventType,
        run_id: RunId,
        agent_id: AgentId,
        payload: dict[str, Any],
    ) -> None:
        self.emit(RunEvent(type=etype, run_id=run_id, agent_id=agent_id, payload=payload))

    def subscribe(self, handler: Callable[[RunEvent], None]) -> Unsubscribe:
        self._handlers.append(handler)

        def _unsub() -> None:
            if handler in self._handlers:
                self._handlers.remove(handler)

        return _unsub

    def create_stream_queue(self) -> asyncio.Queue[RunEvent | None]:
        q: asyncio.Queue[RunEvent | None] = asyncio.Queue()
        self._queues.append(q)
        return q

    def close_stream_queue(self, q: asyncio.Queue[RunEvent | None]) -> None:
        if q in self._queues:
            self._queues.remove(q)
        q.put_nowait(None)
