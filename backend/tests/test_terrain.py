"""Terrain: elevation file and flight levels in the scenario, ground per grid, route profile."""

import itertools
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from corridor.domain.events import PlanMetrics, RoutePoint
from corridor.domain.geo import Grid, LocalFrame, Position
from corridor.domain.planner.plan import MissionPlan
from corridor.domain.rf.dem import RasterDem
from corridor.domain.scenario import Mission, Scenario, Terrain, load_scenario
from corridor.domain.state import Cut
from corridor.domain.terrain import PROFILE_STEP_M, ground_grid, profile
from corridor.engine.clock import SimClock
from corridor.engine.engine import Engine
from corridor.engine.replan import PlanDone

ORIGIN = Position(lat=48.0, lon=11.0)
PIXEL_DEG = 1 / 3600  # about 30 m
BASE_M, HILL_M = 500.0, 120.0


class FakeReplanner:
    """Records the plan requests; the test finishes them."""

    def __init__(self) -> None:
        self.done: list[tuple[int, PlanDone]] = []

    def request(
        self,
        scenario: Scenario,
        mission: Mission,
        grid: Grid,
        revision: int,
        cuts: list[Cut],
        earliest_departure_s: float,
        done: PlanDone,
    ) -> None:
        self.done.append((revision, done))

    def request_fallback(
        self,
        scenario: Scenario,
        mission: Mission,
        grid: Grid,
        revision: int,
        position: Position,
        now_s: float,
        done: PlanDone,
    ) -> None:
        raise AssertionError("no flight in these tests")

    def close(self) -> None:
        pass


@pytest.fixture
def hill(tmp_path: Path) -> Terrain:
    """100 x 100 pixels from ORIGIN (north-west corner), a hill at pixel (row 50, col 50)."""
    RasterDem.create_test_raster(
        tmp_path / "hill.tif",
        origin_lat=ORIGIN.lat,
        origin_lon=ORIGIN.lon,
        pixel_size_deg=PIXEL_DEG,
        base_elevation=BASE_M,
        hill_center_px=(50, 50),
        hill_height_m=HILL_M,
    )
    return Terrain(dem=str(tmp_path / "hill.tif"))


def pixel_centre(row: int, col: int) -> Position:
    return Position(
        lat=ORIGIN.lat - (row + 0.5) * PIXEL_DEG, lon=ORIGIN.lon + (col + 0.5) * PIXEL_DEG
    )


def test_raster_is_sampled_at_pixel_centres(hill: Terrain) -> None:
    assert hill.dem is not None
    dem = RasterDem(hill.dem)
    top = pixel_centre(50, 50)
    assert dem.get_elevation(top) == pytest.approx(BASE_M + HILL_M)
    lons = np.array([[top.lon, ORIGIN.lon + 0.001]])
    lats = np.array([[top.lat, ORIGIN.lat - 0.001]])
    elevations = dem.get_elevations_lonlat(lons, lats)
    assert elevations.shape == (1, 2)
    assert elevations[0].tolist() == pytest.approx([BASE_M + HILL_M, BASE_M])


def test_without_a_file_the_ground_is_flat() -> None:
    grid = Grid(origin=ORIGIN, cell_m=100, cols=4, rows=3)
    ground = ground_grid(Terrain(), grid)
    assert ground.shape == (3, 4)
    assert not ground.any()


def test_ground_of_a_grid_is_cached_until_the_grid_changes(hill: Terrain) -> None:
    south_west = Position(lat=ORIGIN.lat - 100 * PIXEL_DEG, lon=ORIGIN.lon)
    grid = Grid(origin=south_west, cell_m=100, cols=20, rows=20)
    ground = ground_grid(hill, grid)
    assert ground.shape == (20, 20)
    assert ground_grid(hill, grid) is ground
    assert not ground.flags.writeable
    # The cell holding the hill top is the highest, the corners are on the base.
    col, row = (int(v // 100) for v in LocalFrame(south_west).to_xy(pixel_centre(50, 50)))
    assert np.unravel_index(ground.argmax(), ground.shape) == (row, col)
    assert ground[0, 0] == pytest.approx(BASE_M)
    wider = grid.model_copy(update={"cols": 25})
    assert ground_grid(hill, wider).shape == (20, 25)


def test_profile_follows_the_route_over_the_hill(hill: Terrain) -> None:
    frame = LocalFrame(pixel_centre(50, 0))
    a, b = frame.to_position(0, 0), frame.to_position(2500, 0)  # due east over the top
    route = [
        RoutePoint(lat=a.lat, lon=a.lon, t=0, action="ground"),
        RoutePoint(lat=a.lat, lon=a.lon, t=100, action="fly"),
        RoutePoint(lat=b.lat, lon=b.lon, t=350, action="fly"),
    ]
    points = profile(hill, route)
    distances = [p.distance_m for p in points]
    assert distances[0] == 0
    assert distances[-1] == pytest.approx(2500, abs=0.1)
    assert max(b - a for a, b in itertools.pairwise(distances)) <= PROFILE_STEP_M + 0.1
    top = max(points, key=lambda p: p.ground_m)
    assert top.ground_m == pytest.approx(BASE_M + HILL_M, abs=5)
    assert top.distance_m == pytest.approx(frame.to_xy(pixel_centre(50, 50))[0], abs=50)
    assert all(p.alt_m is None for p in points)  # the planner is still 2D


def test_profile_interpolates_the_drone_height() -> None:
    route = [
        RoutePoint(lat=48.0, lon=11.0, t=0, action="fly", alt_m=30),
        RoutePoint(lat=48.0, lon=11.01, t=75, action="fly", alt_m=120),
    ]
    points = profile(Terrain(), route)
    middle = points[len(points) // 2]
    assert middle.alt_m == pytest.approx(30 + 90 * middle.distance_m / points[-1].distance_m)
    assert all(p.ground_m == 0 for p in points)


def test_levels_must_rise() -> None:
    assert Terrain().levels_m == (30, 60, 120, 250)
    for levels in [(), (0, 30), (60, 30), (30, 30)]:
        with pytest.raises(ValidationError):
            Terrain(levels_m=levels)


def test_scenario_files_name_an_elevation_file_that_exists(tmp_path: Path) -> None:
    for path in Path(__file__).resolve().parent.parent.glob("scenarios/*.json"):
        assert load_scenario(path).terrain.dem is not None, path
    demo = Path(__file__).resolve().parent.parent / "scenarios" / "demo.json"
    missing = tmp_path / "missing.json"
    missing.write_text(demo.read_text().replace("copernicus_munich.tif", "nowhere.tif"))
    with pytest.raises(ValueError, match="elevation file not found"):
        load_scenario(missing)


def test_plans_carry_the_profile_of_their_route(scenario: Scenario) -> None:
    replanner = FakeReplanner()
    engine = Engine(scenario, 100, SimClock(20, wall=lambda: 0.0), replanner)
    engine.request_plans()
    m1 = scenario.missions[0]
    route = [
        RoutePoint(lat=m1.launch.lat, lon=m1.launch.lon, t=600, action="fly"),
        RoutePoint(lat=m1.target.lat, lon=m1.target.lon, t=1400, action="fly"),
    ]
    metrics = PlanMetrics(
        baseline_battery_used_pct=40, optimised_battery_used_pct=40, saved_pct=0, saved_s=0
    )
    revision, done = replanner.done[0]
    plan = MissionPlan(
        status="baseline", metrics=metrics, baseline_route=route, optimised_route=route
    )
    done(revision, plan)
    updated = engine.missions["M1"].plan
    assert updated is not None
    assert updated.profile[-1].distance_m == pytest.approx(8000, rel=0.02)
    assert all(400 < p.ground_m < 700 for p in updated.profile)  # Munich, from the elevation file
