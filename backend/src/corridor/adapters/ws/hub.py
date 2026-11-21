"""Fan-out of server messages to connected WebSocket clients."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from corridor.adapters.ws.schemas import Ack, Error, ServerMessage, Snapshot
from corridor.domain.events import Event

Outbox = asyncio.Queue[str]


class Hub:
    def __init__(self, now: Callable[[], float]) -> None:
        self._now = now
        self._outboxes: set[Outbox] = set()
        self._seq = 0

    def connect(self, snapshot: Snapshot) -> Outbox:
        """Register a client. Its first message is ``snapshot``.

        Must be called without awaiting between building the snapshot and this call, so no
        event can fall between the two.
        """
        outbox: Outbox = asyncio.Queue()
        outbox.put_nowait(self._encode(snapshot))
        self._outboxes.add(outbox)
        return outbox

    def disconnect(self, outbox: Outbox) -> None:
        self._outboxes.discard(outbox)

    def publish(self, event: Event) -> None:
        self._seq += 1
        message = self._encode(event)
        for outbox in self._outboxes:
            outbox.put_nowait(message)

    def reply(self, outbox: Outbox, payload: Ack | Error) -> None:
        outbox.put_nowait(self._encode(payload))

    def _encode(self, payload: Event | Snapshot | Ack | Error) -> str:
        return ServerMessage(
            seq=self._seq, sim_time_s=self._now(), payload=payload
        ).model_dump_json()
