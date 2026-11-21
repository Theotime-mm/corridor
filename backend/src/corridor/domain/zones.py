"""Zones the mission may not enter, and the planning grid around them.

Jammer zones come from the J/S ratio at the drone, in free space, with EIRP taken toward the
drone and the jammer on the link band:

    J/S = (Pj / dj^2) / (Ps / ds^2)

Pj is the jammer EIRP, Ps the pilot link EIRP, dj and ds the distances from the drone to the
jammer and to the pilot. The link is lost where J/S >= t, t = 10^(threshold_db / 10), that is
where ds / dj >= k with k = sqrt(t * Ps / Pj). The boundary ds / dj = k is a circle of
Apollonius:

- k > 1: a disc around the jammer, pushed away from the pilot. Forbidden inside.
- k < 1: the jammer wins everywhere but a bubble around the pilot. Forbidden outside.

A directional jammer (``Antenna``) has two EIRPs: the main beam one inside a horizontal sector
with a hard edge, the sidelobe one elsewhere. Its zone is the main disc inside the beam and the
sidelobe disc outside it. Both discs contain the jammer, so the zone is star-shaped around the
jammer. Only k > 1 is supported: with k < 1 the zone would be an unbounded wedge, which a ring
cannot describe.

The pilot stands at the launch point, so the zones are fixed for a mission. Whether a friendly
jammer zone is active at a given time depends on its cuts, not on this module.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from corridor.domain.geo import Grid, LocalFrame, Position
from corridor.domain.model import Model
from corridor.domain.scenario import Antenna, EnemyJammer, EnemyRadar, Scenario

RING_VERTICES = 64
"""Vertices of a full circle; a directional zone uses as many across its main beam."""
GRID_MARGIN_M = 3000.0
"""Room around the mission and the threats, so detours fit inside the grid. Must exceed the
largest radar radius, or the grid edge closes detours the jury could rightly ask about."""
MAX_ZONE_RADIUS_M = 100_000.0
"""Beyond this, k is so close to 1 that the boundary is nearly a straight line."""

ZoneKind = Literal["friendly_jammer", "enemy_jammer", "radar"]
ForbiddenSide = Literal["inside", "outside"]


class Zone(Model):
    threat: str = Field(description="Id of the jammer or radar.")
    kind: ZoneKind
    forbidden: ForbiddenSide = Field(description="Side of the ring the mission may not enter.")
    ring: list[Position] = Field(description="Closed boundary; the first vertex is not repeated.")


@dataclass(frozen=True)
class Disc:
    """Circle in a local frame, metres."""

    x: float
    y: float
    radius_m: float
    forbidden: ForbiddenSide


@dataclass(frozen=True)
class Beam:
    """Horizontal sector of a directional jammer, in a local frame.

    ``axis_rad`` is a mathematical angle: counter-clockwise from east.
    """

    x: float
    y: float
    axis_rad: float
    half_width_rad: float

    def contains(self, x: float, y: float) -> bool:
        """True if (x, y) lies inside the beam, edges included."""
        return angle_off_axis(x - self.x, y - self.y, self.axis_rad) <= self.half_width_rad

    def edges(self) -> tuple[float, float]:
        """Directions of the two edge rays, mathematical angles."""
        return self.axis_rad - self.half_width_rad, self.axis_rad + self.half_width_rad


def azimuth_to_angle(azimuth_deg: float) -> float:
    """Azimuth (degrees clockwise from north) to a mathematical angle (radians from east)."""
    return math.radians(90.0 - azimuth_deg)


def angle_off_axis(dx: float, dy: float, axis_rad: float) -> float:
    """Absolute angle between the direction (dx, dy) and ``axis_rad``, in [0, pi]."""
    a = math.atan2(dy, dx) - axis_rad
    return abs(math.atan2(math.sin(a), math.cos(a)))


def js_disc(
    pilot: tuple[float, float],
    jammer: tuple[float, float],
    link_eirp_w: float,
    jammer_eirp_w: float,
    threshold_db: float,
) -> Disc:
    """Boundary of J/S >= threshold, as a circle of Apollonius."""
    (px, py), (jx, jy) = pilot, jammer
    distance = math.hypot(jx - px, jy - py)
    if distance < 1.0:
        raise ValueError("jammer at the pilot position")
    k2 = 10 ** (threshold_db / 10) * link_eirp_w / jammer_eirp_w
    if k2 == 1.0 or math.sqrt(k2) * distance / abs(k2 - 1) > MAX_ZONE_RADIUS_M:
        raise ValueError("J/S boundary is nearly a straight line: adjust the powers")
    return Disc(
        x=(k2 * jx - px) / (k2 - 1),
        y=(k2 * jy - py) / (k2 - 1),
        radius_m=math.sqrt(k2) * distance / abs(k2 - 1),
        forbidden="inside" if k2 > 1 else "outside",
    )


@dataclass(frozen=True)
class ThreatShape:
    """Zone of one threat in the mission frame (``LocalFrame(mission.launch)``).

    Without ``beam``, ``disc`` is the zone. With ``beam``, the zone is ``disc`` inside the beam
    and ``sidelobe`` outside it; both are then forbidden inside and contain the jammer.
    """

    threat: str
    kind: ZoneKind
    disc: Disc
    beam: Beam | None = None
    sidelobe: Disc | None = None

    def contains(self, x: float, y: float) -> bool:
        """True if (x, y) lies on the forbidden side of the zone (exact, no cell margin)."""
        d = self.disc
        if self.beam is not None and not self.beam.contains(x, y):
            if self.sidelobe is None:
                return False
            d = self.sidelobe
        inside = math.hypot(x - d.x, y - d.y) < d.radius_m
        return inside == (d.forbidden == "inside")


def mission_shapes(scenario: Scenario) -> list[ThreatShape]:
    """Zones that matter to the mission: jammers on its band, every radar."""
    mission = scenario.mission
    frame = LocalFrame(mission.launch)

    def disc(pos: Position, eirp_w: float) -> Disc:
        return js_disc(
            (0.0, 0.0), frame.to_xy(pos), mission.link_eirp_w, eirp_w, scenario.js_threshold_db
        )

    zones: list[ThreatShape] = []
    for j in scenario.friendly_jammers:
        if mission.band not in j.bands:
            continue
        main = disc(j.pos, j.eirp_w)
        if j.antenna is None:
            zones.append(ThreatShape(j.id, "friendly_jammer", main))
        else:
            sidelobe = disc(j.pos, j.eirp_w * 10 ** (j.antenna.sidelobe_db / 10))
            zones.append(_directional(j.id, frame.to_xy(j.pos), j.antenna, main, sidelobe))
    for threat in scenario.enemy_threats:
        match threat:
            case EnemyJammer() if mission.band in threat.bands:
                zones.append(
                    ThreatShape(threat.id, "enemy_jammer", disc(threat.pos, threat.eirp_w))
                )
            case EnemyRadar():
                x, y = frame.to_xy(threat.pos)
                radar = Disc(x=x, y=y, radius_m=threat.radius_m, forbidden="inside")
                zones.append(ThreatShape(threat.id, "radar", radar))
    return zones


def mission_zones(scenario: Scenario) -> list[Zone]:
    """``mission_shapes`` as rings, for the front end."""
    frame = LocalFrame(scenario.mission.launch)
    return [
        Zone(
            threat=z.threat,
            kind=z.kind,
            forbidden=z.disc.forbidden,
            ring=[frame.to_position(x, y) for x, y in _ring(z)],
        )
        for z in mission_shapes(scenario)
    ]


def planning_grid(scenario: Scenario, cell_m: float) -> Grid:
    """Grid around launch, target and every threat, with ``GRID_MARGIN_M`` on each side.

    Zones may reach past the grid: the planner treats cells outside it as unreachable.
    """
    threats = [*scenario.friendly_jammers, *scenario.enemy_threats]
    points = [scenario.mission.launch, scenario.mission.target, *(t.pos for t in threats)]
    return Grid.covering(points, GRID_MARGIN_M, cell_m)


def _directional(
    threat: str, jammer: tuple[float, float], antenna: Antenna, main: Disc, sidelobe: Disc
) -> ThreatShape:
    if main.forbidden != "inside":
        raise ValueError(
            f"{threat}: directional jammer stronger than the link (k < 1) is not supported"
        )
    beam = Beam(
        x=jammer[0],
        y=jammer[1],
        axis_rad=azimuth_to_angle(antenna.azimuth_deg),
        half_width_rad=math.radians(antenna.beamwidth_deg) / 2,
    )
    return ThreatShape(threat, "friendly_jammer", main, beam, sidelobe)


def _ring(zone: ThreatShape) -> list[tuple[float, float]]:
    d, beam = zone.disc, zone.beam
    if beam is None:
        return [
            (
                d.x + d.radius_m * math.cos(2 * math.pi * i / RING_VERTICES),
                d.y + d.radius_m * math.sin(2 * math.pi * i / RING_VERTICES),
            )
            for i in range(RING_VERTICES)
        ]
    # Star-shaped around the jammer: walk the main beam, then the rest of the circle on the
    # sidelobe disc. At each beam edge the boundary steps radially from one disc to the other.
    start, end = beam.edges()
    ring = _arc(beam, d, start, end, RING_VERTICES)
    rest = 2 * math.pi - (end - start)
    if zone.sidelobe is not None and rest > 0:
        steps = max(2, math.ceil(RING_VERTICES * rest / (2 * math.pi)))
        ring += _arc(beam, zone.sidelobe, end, end + rest, steps)
    return ring


def _arc(beam: Beam, disc: Disc, start: float, end: float, steps: int) -> list[tuple[float, float]]:
    """Points where rays from the jammer leave ``disc``, ``steps + 1`` angles from ``start`` to
    ``end`` included."""
    points = []
    for i in range(steps + 1):
        a = start + (end - start) * i / steps
        r = _exit_distance(beam.x, beam.y, math.cos(a), math.sin(a), disc)
        points.append((beam.x + r * math.cos(a), beam.y + r * math.sin(a)))
    return points


def _exit_distance(x: float, y: float, ux: float, uy: float, disc: Disc) -> float:
    """Distance along the unit ray from (x, y), inside ``disc``, to its boundary."""
    wx, wy = x - disc.x, y - disc.y
    along = wx * ux + wy * uy
    return -along + math.sqrt(along**2 - (wx**2 + wy**2 - disc.radius_m**2))
