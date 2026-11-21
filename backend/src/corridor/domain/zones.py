"""Zones the mission may not enter, and the planning grid around them.

Jammer zones come from the J/S ratio at the drone, in free space, with EIRP taken toward the
drone (omnidirectional, or the drone in the main beam) and the jammer on the link band:

    J/S = (Pj / dj^2) / (Ps / ds^2)

Pj is the jammer EIRP, Ps the pilot link EIRP, dj and ds the distances from the drone to the
jammer and to the pilot. The link is lost where J/S >= t, t = 10^(threshold_db / 10), that is
where ds / dj >= k with k = sqrt(t * Ps / Pj). The boundary ds / dj = k is a circle of
Apollonius:

- k > 1: a disc around the jammer, pushed away from the pilot. Forbidden inside.
- k < 1: the jammer wins everywhere but a bubble around the pilot. Forbidden outside.

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
from corridor.domain.scenario import EnemyJammer, EnemyRadar, Scenario

RING_VERTICES = 64
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
class ThreatDisc:
    """Zone of one threat, as a disc in the mission frame (``LocalFrame(mission.launch)``)."""

    threat: str
    kind: ZoneKind
    disc: Disc


def mission_discs(scenario: Scenario) -> list[ThreatDisc]:
    """Zones that matter to the mission: jammers on its band, every radar."""
    mission = scenario.mission
    frame = LocalFrame(mission.launch)

    def jammer_zone(threat: str, kind: ZoneKind, pos: Position, eirp_w: float) -> ThreatDisc:
        disc = js_disc(
            (0.0, 0.0),
            frame.to_xy(pos),
            mission.link_eirp_w,
            eirp_w,
            scenario.js_threshold_db,
        )
        return ThreatDisc(threat, kind, disc)

    zones = [
        jammer_zone(j.id, "friendly_jammer", j.pos, j.eirp_w)
        for j in scenario.friendly_jammers
        if mission.band in j.bands
    ]
    for threat in scenario.enemy_threats:
        match threat:
            case EnemyJammer() if mission.band in threat.bands:
                zones.append(jammer_zone(threat.id, "enemy_jammer", threat.pos, threat.eirp_w))
            case EnemyRadar():
                x, y = frame.to_xy(threat.pos)
                disc = Disc(x=x, y=y, radius_m=threat.radius_m, forbidden="inside")
                zones.append(ThreatDisc(threat.id, "radar", disc))
    return zones


def mission_zones(scenario: Scenario) -> list[Zone]:
    """``mission_discs`` as rings, for the front end."""
    frame = LocalFrame(scenario.mission.launch)
    return [_zone(z.threat, z.kind, z.disc, frame) for z in mission_discs(scenario)]


def planning_grid(scenario: Scenario, cell_m: float) -> Grid:
    """Grid around launch, target and every threat, with ``GRID_MARGIN_M`` on each side.

    Zones may reach past the grid: the planner treats cells outside it as unreachable.
    """
    threats = [*scenario.friendly_jammers, *scenario.enemy_threats]
    points = [scenario.mission.launch, scenario.mission.target, *(t.pos for t in threats)]
    return Grid.covering(points, GRID_MARGIN_M, cell_m)


def _zone(threat: str, kind: ZoneKind, disc: Disc, frame: LocalFrame) -> Zone:
    ring = [
        frame.to_position(
            disc.x + disc.radius_m * math.cos(2 * math.pi * i / RING_VERTICES),
            disc.y + disc.radius_m * math.sin(2 * math.pi * i / RING_VERTICES),
        )
        for i in range(RING_VERTICES)
    ]
    return Zone(threat=threat, kind=kind, forbidden=disc.forbidden, ring=ring)
