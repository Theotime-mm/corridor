"""FastAPI application exposing the engine on ``/ws``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from corridor.adapters.ws.hub import Hub, Outbox
from corridor.adapters.ws.schemas import Ack, ClientMessage, Error, Snapshot
from corridor.domain.geo import Grid, Position
from corridor.domain.rf.coverage import (
    ContourLevel,
    compute_js_heatmap_geojson,
    compute_polar_coverage,
    polar_coverage_to_geojson,
    probe_point_rf,
)
from corridor.domain.rf.dem import DemProvider, HillFeature, RasterDem, SyntheticDem
from corridor.domain.scenario import Scenario
from corridor.domain.zones import Zone, mission_zones, planning_grid
from corridor.engine.clock import SimClock
from corridor.engine.engine import CommandRejected, Engine
from corridor.engine.replan import Replanner

ReplannerFactory = Callable[[Scenario, Grid], Replanner]

TICK_S = 0.5
log = logging.getLogger(__name__)


async def _tick_forever(engine: Engine) -> None:
    while True:
        try:
            engine.tick()
        except Exception:
            log.exception("engine tick failed")
        await asyncio.sleep(TICK_S)


def snapshot(engine: Engine, grid: Grid, zones: list[Zone]) -> Snapshot:
    return Snapshot(
        scenario=engine.scenario,
        grid=grid,
        zones=zones,
        clock=engine.clock.state(),
        cuts=list(engine.state.cuts.values()),
        mission_status=engine.state.mission_status,
        plan=engine.plan,
        drone=engine.drone,
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
        ticker = asyncio.create_task(_tick_forever(engine))
        yield
        ticker.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await ticker
        if planner:
            planner.close()

    app = FastAPI(title="Corridor", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/rf/coverage")
    async def get_rf_coverage(drone_h_agl_m: float = 20.0) -> dict[str, Any]:
        """Return terrain-aware RF coverage GeoJSON contours for scenario threats."""
        features: list[dict[str, Any]] = []
        launch_p = scenario.mission.launch
        dem: DemProvider

        if 45.5 <= launch_p.lat <= 46.5 and Path("data/copernicus_annecy.tif").exists():
            dem = RasterDem(Path("data/copernicus_annecy.tif"))
        elif 22.0 <= launch_p.lat <= 22.5 and Path("data/copernicus_hongkong.tif").exists():
            dem = RasterDem(Path("data/copernicus_hongkong.tif"))
        elif Path("data/copernicus_munich.tif").exists():
            dem = RasterDem(Path("data/copernicus_munich.tif"))
        else:
            dem = SyntheticDem(
                base_elevation_m=520.0,
                hills=[
                    HillFeature(
                        center=Position(lat=48.160, lon=11.550),
                        radius_m=1200.0,
                        height_m=95.0,
                    ),
                    HillFeature(
                        center=Position(lat=48.130, lon=11.580),
                        radius_m=1000.0,
                        height_m=80.0,
                    ),
                ],
            )

        friendly_contours = [
            ContourLevel(-70.0, "Friendly Denied (-70 dBm)", "#e03131", 0.32, "#c92a2a", 2),
            ContourLevel(-85.0, "Friendly Contention (-85 dBm)", "#f08c00", 0.20, "#e8590c", 2),
            ContourLevel(-100.0, "Friendly Fringe (-100 dBm)", "#fab005", 0.10, "#f59f00", 1),
        ]
        enemy_contours = [
            ContourLevel(-70.0, "Enemy Threat (-70 dBm)", "#9c36b5", 0.32, "#862e9c", 2),
            ContourLevel(-85.0, "Enemy Contention (-85 dBm)", "#ae3ec9", 0.20, "#9c36b5", 2),
            ContourLevel(-100.0, "Enemy Fringe (-100 dBm)", "#cc5de8", 0.10, "#ae3ec9", 1),
        ]

        for jammer in scenario.friendly_jammers:
            cov = compute_polar_coverage(
                dem=dem,
                tx_pos=jammer.pos,
                tx_eirp_w=jammer.eirp_w,
                band_or_freq_hz=scenario.mission.band,
                rx_h_agl_m=drone_h_agl_m,
                max_range_m=5000.0,
                azimuth_step_deg=10.0,
            )
            gj = polar_coverage_to_geojson(cov, contours=friendly_contours)
            for f in gj["features"]:
                props = dict(f.get("properties", {}))
                props["threat_id"] = jammer.id
                props["threat_kind"] = "friendly_jammer"
                f["properties"] = props
                features.append(f)

        for threat in scenario.enemy_threats:
            if threat.type == "jammer":
                cov = compute_polar_coverage(
                    dem=dem,
                    tx_pos=threat.pos,
                    tx_eirp_w=threat.eirp_w,
                    band_or_freq_hz=scenario.mission.band,
                    rx_h_agl_m=drone_h_agl_m,
                    max_range_m=5000.0,
                    azimuth_step_deg=10.0,
                )
                gj = polar_coverage_to_geojson(cov, contours=enemy_contours)
                for f in gj["features"]:
                    props = dict(f.get("properties", {}))
                    props["threat_id"] = threat.id
                    props["threat_kind"] = "enemy_jammer"
                    f["properties"] = props
                    features.append(f)

        return {"type": "FeatureCollection", "features": features}

    def _select_dem() -> DemProvider:
        launch_p = scenario.mission.launch
        if 40.5 <= launch_p.lat <= 41.0 and Path("data/copernicus_newyork.tif").exists():
            return RasterDem(Path("data/copernicus_newyork.tif"))
        if 45.5 <= launch_p.lat <= 46.5 and Path("data/copernicus_annecy.tif").exists():
            return RasterDem(Path("data/copernicus_annecy.tif"))
        if 22.0 <= launch_p.lat <= 22.5 and Path("data/copernicus_hongkong.tif").exists():
            return RasterDem(Path("data/copernicus_hongkong.tif"))
        if Path("data/copernicus_munich.tif").exists():
            return RasterDem(Path("data/copernicus_munich.tif"))
        return SyntheticDem(
            base_elevation_m=520.0,
            hills=[
                HillFeature(
                    center=Position(lat=48.160, lon=11.550),
                    radius_m=1200.0,
                    height_m=95.0,
                ),
                HillFeature(
                    center=Position(lat=48.130, lon=11.580),
                    radius_m=1000.0,
                    height_m=80.0,
                ),
            ],
        )

    @app.get("/api/rf/heatmap")
    async def get_rf_heatmap(
        drone_h_agl_m: float = 20.0,
        step_m: float = 300.0,
        cells: bool = False,
    ) -> dict[str, Any]:
        """Return continuous J/S heatmap grid for GPU-accelerated heatmap rendering."""
        dem = _select_dem()
        jammers: list[tuple[str, Position, float]] = [
            (j.id, j.pos, j.eirp_w) for j in scenario.friendly_jammers
        ]
        for t in scenario.enemy_threats:
            if t.type == "jammer":
                jammers.append((t.id, t.pos, t.eirp_w))

        # Calculate bounding box with 5km margin around scenario grid
        frame = grid.frame
        sw = frame.to_position(-5000.0, -5000.0)
        ne = frame.to_position(grid.cols * grid.cell_m + 5000.0, grid.rows * grid.cell_m + 5000.0)
        bounds = (sw.lat, sw.lon, ne.lat, ne.lon)

        return compute_js_heatmap_geojson(
            dem=dem,
            pilot_pos=scenario.mission.launch,
            pilot_eirp_w=scenario.mission.link_eirp_w,
            jammers=jammers,
            band_or_freq_hz=scenario.mission.band,
            bounds=bounds,
            step_m=max(step_m, 250.0),
            drone_h_agl_m=drone_h_agl_m,
            cells=cells,
        )

    @app.get("/api/rf/probe")
    async def probe_rf(lat: float, lon: float, drone_h_agl_m: float = 20.0) -> dict[str, Any]:
        """Probe real-time RF link budget & terrain shielding at a specific coordinate."""
        dem = _select_dem()
        jammers: list[tuple[str, Position, float]] = [
            (j.id, j.pos, j.eirp_w) for j in scenario.friendly_jammers
        ]
        for t in scenario.enemy_threats:
            if t.type == "jammer":
                jammers.append((t.id, t.pos, t.eirp_w))

        return probe_point_rf(
            dem=dem,
            target_pos=Position(lat=lat, lon=lon),
            pilot_pos=scenario.mission.launch,
            pilot_eirp_w=scenario.mission.link_eirp_w,
            jammers=jammers,
            band_or_freq_hz=scenario.mission.band,
            drone_h_agl_m=drone_h_agl_m,
        )

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
