import math

import pytest
from pydantic import ValidationError

from corridor.domain.geo import LocalFrame
from corridor.domain.scenario import Scenario
from corridor.domain.zones import (
    GRID_MARGIN_M,
    RING_VERTICES,
    Beam,
    angle_off_axis,
    azimuth_to_angle,
    js_disc,
    mission_zones,
    planning_grid,
)


def js_db(
    pilot: tuple[float, float],
    jammer: tuple[float, float],
    at: tuple[float, float],
    link_w: float,
    jammer_w: float,
) -> float:
    """J/S at ``at`` computed directly, to check the closed form."""
    return 10 * math.log10(
        (jammer_w / math.dist(at, jammer) ** 2) / (link_w / math.dist(at, pilot) ** 2)
    )


@pytest.mark.parametrize(("link_w", "jammer_w"), [(10, 2), (1, 50)])
def test_disc_boundary_is_where_js_reaches_the_threshold(link_w: float, jammer_w: float) -> None:
    pilot, jammer, threshold = (0.0, 0.0), (4000.0, 0.0), 3.0
    disc = js_disc(pilot, jammer, link_w, jammer_w, threshold)
    for i in range(8):
        a = 2 * math.pi * i / 8
        on_ring = (disc.x + disc.radius_m * math.cos(a), disc.y + disc.radius_m * math.sin(a))
        assert js_db(pilot, jammer, on_ring, link_w, jammer_w) == pytest.approx(threshold)


def test_weak_jammer_denies_a_disc_around_itself() -> None:
    disc = js_disc((0.0, 0.0), (4000.0, 0.0), link_eirp_w=10, jammer_eirp_w=2, threshold_db=0)
    assert disc.forbidden == "inside"
    assert (disc.x, disc.y) == pytest.approx((5000.0, 0.0))  # pushed away from the pilot
    assert disc.radius_m == pytest.approx(4000 * math.sqrt(5) / 4)


def test_strong_jammer_leaves_only_a_bubble_around_the_pilot() -> None:
    disc = js_disc((0.0, 0.0), (4000.0, 0.0), link_eirp_w=1, jammer_eirp_w=50, threshold_db=0)
    assert disc.forbidden == "outside"
    assert math.hypot(disc.x, disc.y) < disc.radius_m  # the pilot is inside the bubble


@pytest.mark.parametrize(("link_w", "jammer_w"), [(1, 1), (1.0001, 1)])
def test_boundary_close_to_a_straight_line_is_rejected(link_w: float, jammer_w: float) -> None:
    with pytest.raises(ValueError, match="straight line"):
        js_disc((0.0, 0.0), (4000.0, 0.0), link_w, jammer_w, threshold_db=0)


def test_jammer_on_the_pilot_is_rejected() -> None:
    with pytest.raises(ValueError, match="pilot position"):
        js_disc((0.0, 0.0), (0.5, 0.0), 10, 2, 0)


def test_demo_zones(scenario: Scenario) -> None:
    zones = {z.threat: z for z in mission_zones(scenario)}
    assert set(zones) == {"J3", "E1", "R1"}
    assert zones["J3"].kind == "friendly_jammer"
    assert all(z.forbidden == "inside" for z in zones.values())
    assert all(len(z.ring) == RING_VERTICES for z in zones.values())

    frame = LocalFrame(scenario.mission.launch)
    target = frame.to_xy(scenario.mission.target)
    ring = [frame.to_xy(p) for p in zones["J3"].ring]
    assert max(x for x, _ in ring) < target[0]  # the target is reachable


def test_jammer_off_the_mission_band_has_no_zone(scenario: Scenario) -> None:
    data = scenario.model_dump(mode="json")
    data["mission"]["band"] = "900MHz"
    zones = mission_zones(Scenario.model_validate(data))
    assert [z.threat for z in zones] == ["R1"]


def test_planning_grid_covers_mission_and_threats_with_margin(scenario: Scenario) -> None:
    grid = planning_grid(scenario, cell_m=100)
    x, _ = grid.to_xy(scenario.mission.launch)
    assert x == pytest.approx(GRID_MARGIN_M, abs=5)  # the launch point is the westernmost
    for threat in [*scenario.friendly_jammers, *scenario.enemy_threats]:
        assert grid.cell_of(threat.pos) is not None


# --- directional jammers -------------------------------------------------------------------


def with_antenna(scenario: Scenario, **overrides: float) -> Scenario:
    """The demo with J3 directional: 60 degree beam pointing north, -20 dB sidelobes."""
    data = scenario.model_dump(mode="json")
    antenna = {"azimuth_deg": 0, "beamwidth_deg": 60, "sidelobe_db": -20}
    data["friendly_jammers"][0]["antenna"] = antenna
    for key, value in overrides.items():
        if key in antenna:
            antenna[key] = value
        else:
            data["friendly_jammers"][0][key] = value
    return Scenario.model_validate(data)


@pytest.mark.parametrize(
    ("azimuth_deg", "direction"), [(0, (0, 1)), (90, (1, 0)), (180, (0, -1)), (270, (-1, 0))]
)
def test_azimuth_is_clockwise_from_north(
    azimuth_deg: float, direction: tuple[float, float]
) -> None:
    a = azimuth_to_angle(azimuth_deg)
    assert (math.cos(a), math.sin(a)) == pytest.approx(direction, abs=1e-12)


def test_beam_across_north_wraps_around() -> None:
    beam = Beam(x=0, y=0, axis_rad=azimuth_to_angle(350), half_width_rad=math.radians(20))
    at = [(math.sin(math.radians(az)), math.cos(math.radians(az))) for az in (5, 325, 340, 15)]
    assert [beam.contains(x, y) for x, y in at] == [True, False, True, False]


def test_directional_ring_follows_the_main_and_sidelobe_boundaries(scenario: Scenario) -> None:
    directional = with_antenna(scenario)
    mission = directional.mission
    frame = LocalFrame(mission.launch)
    j3 = directional.friendly_jammers[0]
    jammer = frame.to_xy(j3.pos)
    zone = next(z for z in mission_zones(directional) if z.threat == "J3")
    assert zone.forbidden == "inside"
    side_w = j3.eirp_w * 10 ** (-20 / 10)
    for p in zone.ring:
        x, y = frame.to_xy(p)
        off_axis = math.degrees(angle_off_axis(x - jammer[0], y - jammer[1], math.pi / 2))
        if abs(off_axis - 30) < 0.1:
            continue  # on a beam edge, where the boundary steps from one disc to the other
        power = j3.eirp_w if off_axis < 30 else side_w
        js = js_db((0.0, 0.0), jammer, (x, y), mission.link_eirp_w, power)
        assert js == pytest.approx(directional.js_threshold_db, abs=1e-3)


def test_directional_zone_leaves_the_area_behind_the_beam(scenario: Scenario) -> None:
    frame = LocalFrame(scenario.mission.launch)
    ring = [
        frame.to_xy(p)
        for p in next(z for z in mission_zones(with_antenna(scenario)) if z.threat == "J3").ring
    ]
    _, jy = frame.to_xy(scenario.friendly_jammers[0].pos)
    assert max(y for _, y in ring) > jy + 2000  # the main beam reaches far north
    assert min(y for _, y in ring) > jy - 300  # only the sidelobe disc to the south


def test_directional_jammer_stronger_than_the_link_is_rejected(scenario: Scenario) -> None:
    with pytest.raises(ValueError, match="k < 1"):
        mission_zones(with_antenna(scenario, eirp_w=50))


@pytest.mark.parametrize(
    "antenna",
    [
        {"azimuth_deg": 0, "beamwidth_deg": 0, "sidelobe_db": -20},
        {"azimuth_deg": 0, "beamwidth_deg": 200, "sidelobe_db": -20},
        {"azimuth_deg": 360, "beamwidth_deg": 60, "sidelobe_db": -20},
        {"azimuth_deg": 0, "beamwidth_deg": 60, "sidelobe_db": 3},
        {"azimuth_deg": 0, "beamwidth_deg": 60},
    ],
)
def test_invalid_antenna_is_rejected(scenario: Scenario, antenna: dict[str, float]) -> None:
    data = scenario.model_dump(mode="json")
    data["friendly_jammers"][0]["antenna"] = antenna
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)
