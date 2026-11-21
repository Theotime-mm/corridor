"""FastAPI application exposing the engine on ``/ws``."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from corridor.adapters.ws.hub import Hub, Outbox
from corridor.adapters.ws.schemas import Ack, ClientMessage, Error, Snapshot
from corridor.domain.geo import Grid
from corridor.domain.scenario import Scenario
from corridor.domain.zones import Zone, mission_zones, planning_grid
from corridor.engine.clock import SimClock
from corridor.engine.engine import CommandRejected, Engine
from corridor.engine.replan import Replanner

ReplannerFactory = Callable[[Scenario, Grid], Replanner]


def snapshot(engine: Engine, grid: Grid, zones: list[Zone]) -> Snapshot:
    return Snapshot(
        scenario=engine.scenario,
        grid=grid,
        zones=zones,
        clock=engine.clock.state(),
        cuts=list(engine.state.cuts.values()),
        mission_status=engine.state.mission_status,
        plan=engine.plan,
    )


def handle_message(raw: str, engine: Engine, hub: Hub, outbox: Outbox) -> None:
    try:
        message = ClientMessage.model_validate_json(raw)
    except ValidationError as exc:
        hub.reply(outbox, Error(req_id=None, reason=str(exc)))
        return
    try:
        engine.submit(message.command)
    except CommandRejected as exc:
        hub.reply(outbox, Error(req_id=message.req_id, reason=str(exc)))
        return
    hub.reply(outbox, Ack(req_id=message.req_id))


async def _pump(websocket: WebSocket, outbox: Outbox) -> None:
    while True:
        await websocket.send_text(await outbox.get())


def create_app(
    scenario: Scenario,
    clock_factor: float,
    cell_m: float,
    replanner: ReplannerFactory | None = None,
) -> FastAPI:
    """Without ``replanner``, nothing is planned. The first plan is requested at startup."""
    grid = planning_grid(scenario, cell_m)
    zones = mission_zones(scenario)
    planner = replanner(scenario, grid) if replanner else None
    engine = Engine(scenario, SimClock(clock_factor), planner)
    hub = Hub(engine.clock.now)
    engine.subscribe(hub.publish)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine.request_plan()
        yield
        if planner:
            planner.close()

    app = FastAPI(title="Corridor", lifespan=lifespan)

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        outbox = hub.connect(snapshot(engine, grid, zones))
        sender = asyncio.create_task(_pump(websocket, outbox))
        try:
            while True:
                handle_message(await websocket.receive_text(), engine, hub, outbox)
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(outbox)
            sender.cancel()
            # The pump may already have died sending to a closed socket: nothing to report.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender

    return app
