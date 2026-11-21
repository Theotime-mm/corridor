"""FastAPI application exposing the engine on ``/ws?callsign=...``.

The callsign says who connects; the scenario gives its role (``Scenario.role_of``). An unknown
callsign is closed with code ``4003``. Each client gets the snapshot and the events of its role
(``corridor.adapters.ws.audience``), and may only send commands as itself: no authentication,
but the filter would be decorative if any client could act under another callsign.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from corridor.adapters.ws.audience import Audience, Viewer
from corridor.adapters.ws.hub import Hub, Outbox
from corridor.adapters.ws.schemas import Ack, ClientMessage, Error, MissionView, Snapshot
from corridor.domain.geo import Grid
from corridor.domain.scenario import Scenario
from corridor.domain.zones import Zone, constraints_by_mission, nominal_zones
from corridor.engine.clock import SimClock
from corridor.engine.engine import CommandRejected, Engine
from corridor.engine.replan import Replanner

ReplannerFactory = Callable[[Scenario, dict[str, Grid]], Replanner]
"""Takes the planning grid of each mission, by mission id."""

TICK_S = 0.5
UNKNOWN_CALLSIGN = 4003
log = logging.getLogger(__name__)


async def _tick_forever(engine: Engine) -> None:
    while True:
        try:
            engine.tick()
        except Exception:
            log.exception("engine tick failed")
        await asyncio.sleep(TICK_S)


def snapshot(engine: Engine, audience: Audience, viewer: Viewer, nominal: list[Zone]) -> Snapshot:
    scope = audience.scope(viewer)
    return Snapshot(
        viewer=viewer,
        scenario=audience.scenario_for(viewer),
        nominal_zones=audience.nominal_zones_for(viewer, nominal),
        missions=[
            MissionView(
                constraints=runtime.constraints,
                status=engine.state.missions[mission_id],
                plan=runtime.plan,
                drone=runtime.drone,
            )
            for mission_id, runtime in engine.missions.items()
            if mission_id in scope.missions
        ],
        clock=engine.clock.state(),
        cuts=[c for c in engine.state.cuts.values() if c.jammer in scope.jammers],
    )


def handle_message(raw: str, viewer: Viewer, engine: Engine, hub: Hub, outbox: Outbox) -> None:
    try:
        message = ClientMessage.model_validate_json(raw)
    except ValidationError as exc:
        hub.reply(outbox, Error(req_id=None, reason=str(exc)))
        return
    if message.command.actor != viewer.callsign:
        reason = f"connected as {viewer.callsign}, cannot act as {message.command.actor}"
        hub.reply(outbox, Error(req_id=message.req_id, reason=reason))
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
    constraints = constraints_by_mission(scenario, cell_m)
    nominal = nominal_zones(scenario)
    grids = {mission: c.grid for mission, c in constraints.items()}
    planner = replanner(scenario, grids) if replanner else None
    engine = Engine(scenario, constraints, SimClock(clock_factor), planner)
    audience = Audience(scenario, constraints)
    hub = Hub(engine.clock.now, audience.sees)
    engine.subscribe(hub.publish)

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        engine.request_plans()
        ticker = asyncio.create_task(_tick_forever(engine))
        yield
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker
        if planner:
            planner.close()

    app = FastAPI(title="Corridor", lifespan=lifespan)

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket, callsign: str = "") -> None:
        await websocket.accept()
        viewer = audience.viewer(callsign)
        if viewer is None:
            await websocket.close(code=UNKNOWN_CALLSIGN, reason=f"unknown callsign {callsign!r}")
            return
        outbox = hub.connect(viewer, snapshot(engine, audience, viewer, nominal))
        sender = asyncio.create_task(_pump(websocket, outbox))
        try:
            while True:
                handle_message(await websocket.receive_text(), viewer, engine, hub, outbox)
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(outbox)
            sender.cancel()
            # The pump may already have died sending to a closed socket: nothing to report.
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await sender

    return app
