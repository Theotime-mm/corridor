"""Terrain: the ground under the missions and the flight levels above it.

The scenario names an elevation file (``Terrain.dem``: a GeoTIFF in metres above sea level,
looked up in ``backend/data/`` unless the path is absolute) and the flight levels
(``Terrain.levels_m``, metres above the ground). Without a file the ground is flat at 0 m, and
every zone stays the disc of the 2D model.

Each process reads an elevation file once (the server and the planner worker each keep their
copy). The ground of a planning grid, ``ground_grid``, is cached by file and grid: a mission's
grid only changes when a threat added or removed changes its area, and the new ground is
computed then, on first use.

``profile`` samples the ground and the drone height along a route, for the altitude profile
under the route on the map.
"""

from __future__ import annotations

import functools
import itertools
import math
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import numpy.typing as npt

from corridor.domain.events import ProfilePoint, RoutePoint
from corridor.domain.geo import EARTH_RADIUS_M, Grid, LocalFrame, Position
from corridor.domain.rf.dem import DemProvider, RasterDem
from corridor.domain.scenario import Terrain

DATA_DIR = Path(__file__).resolve().parents[3] / "data"
"""``backend/data``: where elevation files named by a scenario live."""
PROFILE_STEP_M = 50.0
"""Spacing of the profile samples along a route."""

Elevations = npt.NDArray[np.float64]


class FlatDem:
    """Flat ground at 0 m: no elevation file."""

    def get_elevation(self, pos: Position) -> float:
        return 0.0

    def get_elevations(self, positions: Sequence[Position]) -> Elevations:
        return np.zeros(len(positions), dtype=np.float64)

    def get_elevations_lonlat(self, lons: Elevations, lats: Elevations) -> Elevations:
        return np.zeros(np.broadcast(lons, lats).shape, dtype=np.float64)


FLAT = FlatDem()


def dem_path(name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else DATA_DIR / path


def check_terrain(terrain: Terrain) -> None:
    """Raise ValueError if the elevation file is missing (at scenario load, not mid-run)."""
    if terrain.dem is not None and not dem_path(terrain.dem).is_file():
        raise ValueError(f"elevation file not found: {dem_path(terrain.dem)}")


def ground_model(terrain: Terrain) -> DemProvider:
    return FLAT if terrain.dem is None else _raster(dem_path(terrain.dem))


@functools.cache
def _raster(path: Path) -> RasterDem:
    return RasterDem(path)


def ground_grid(terrain: Terrain, grid: Grid) -> Elevations:
    """Ground elevation (m above sea level) at each cell centre, indexed ``[row, col]`` like
    the masks. Read-only: shared by every caller."""
    return _ground_grid(terrain.dem, grid)


@functools.lru_cache(maxsize=64)
def _ground_grid(dem: str | None, grid: Grid) -> Elevations:
    cols = (np.arange(grid.cols) + 0.5) * grid.cell_m
    rows = (np.arange(grid.rows) + 0.5) * grid.cell_m
    xs, ys = np.meshgrid(cols, rows)
    lons, lats = _lonlat(grid.origin, xs, ys)
    ground = ground_model(Terrain(dem=dem)).get_elevations_lonlat(lons, lats)
    ground.setflags(write=False)
    return ground


def profile(terrain: Terrain, route: Sequence[RoutePoint]) -> list[ProfilePoint]:
    """Ground and drone height every ``PROFILE_STEP_M`` along the flown part of ``route``, and
    at each of its points. Ground waits and hovers add no distance."""
    flown = [p for p in route if p.action != "ground"] or list(route[:1])
    if not flown:
        return []
    frame = LocalFrame(Position(lat=flown[0].lat, lon=flown[0].lon))
    samples: list[tuple[float, Position, float | None]] = []
    distance = 0.0
    for a, b in itertools.pairwise(flown):
        ax, ay = frame.to_xy(Position(lat=a.lat, lon=a.lon))
        bx, by = frame.to_xy(Position(lat=b.lat, lon=b.lon))
        length = math.hypot(bx - ax, by - ay)
        steps = max(1, math.ceil(length / PROFILE_STEP_M))
        for i in range(steps):
            f = i / steps
            at = frame.to_position(ax + f * (bx - ax), ay + f * (by - ay))
            samples.append((distance + f * length, at, _height(a, b, f)))
        distance += length
    last = flown[-1]
    samples.append((distance, Position(lat=last.lat, lon=last.lon), last.alt_m))
    ground = ground_model(terrain).get_elevations([p for _, p, _ in samples])
    return [
        ProfilePoint(distance_m=round(d, 1), ground_m=round(float(g), 1), alt_m=alt)
        for (d, _, alt), g in zip(samples, ground, strict=True)
    ]


def _height(a: RoutePoint, b: RoutePoint, f: float) -> float | None:
    if a.alt_m is None or b.alt_m is None:
        return None
    return a.alt_m + f * (b.alt_m - a.alt_m)


def _lonlat(origin: Position, xs: Elevations, ys: Elevations) -> tuple[Elevations, Elevations]:
    """Vectorised ``LocalFrame(origin).to_position``."""
    cos_lat = math.cos(math.radians(origin.lat))
    lats = origin.lat + np.degrees(ys / EARTH_RADIUS_M)
    lons = origin.lon + np.degrees(xs / (EARTH_RADIUS_M * cos_lat))
    return lons, lats
