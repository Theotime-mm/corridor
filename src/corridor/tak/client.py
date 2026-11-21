"""Plain TCP CoT streaming client for OpenTAKServer (port 8088)."""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from xml.etree.ElementTree import Element

from corridor.tak.cot import Framer, self_sa

ANNOUNCE_EVERY_S = 30.0
# OTS 1.8.3 eud_handler opens its RabbitMQ channel asynchronously after accepting the
# socket. If the first SA arrives before that, parse_device_info records our uid but skips
# declaring and binding our queues, and never retries: we can send but receive nothing,
# with no error logged. Verified: smoke fails 3/3 with 0 s, passes with 1 s.
CONNECT_SETTLE_S = 1.0


@dataclass
class Identity:
    uid: str
    callsign: str
    lat: float
    lon: float


@dataclass
class TakClient:
    host: str
    port: int
    me: Identity
    _reader: asyncio.StreamReader | None = field(default=None, init=False)
    _writer: asyncio.StreamWriter | None = field(default=None, init=False)
    _announcer: asyncio.Task[None] | None = field(default=None, init=False)

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        await asyncio.sleep(CONNECT_SETTLE_S)
        await self.announce()
        self._announcer = asyncio.create_task(self._announce_forever())

    async def announce(self) -> None:
        m = self.me
        await self.send(self_sa(m.uid, m.callsign, m.lat, m.lon, time.time()))

    async def _announce_forever(self) -> None:
        while True:
            await asyncio.sleep(ANNOUNCE_EVERY_S)
            await self.announce()

    async def send(self, cot: bytes) -> None:
        if self._writer is None:
            raise RuntimeError("not connected")
        self._writer.write(cot)
        await self._writer.drain()

    async def events(self) -> AsyncIterator[Element]:
        if self._reader is None:
            raise RuntimeError("not connected")
        framer = Framer()
        while data := await self._reader.read(65536):
            for ev in framer.feed(data):
                yield ev

    async def close(self) -> None:
        if self._announcer is not None:
            self._announcer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._announcer
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError):
                await self._writer.wait_closed()
