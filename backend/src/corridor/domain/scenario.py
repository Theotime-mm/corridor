"""Scenario: the static input of a run, loaded from a JSON file.

Times are simulated seconds from ``start_time``. Jammers are described by their power: the
zone they deny is computed from the J/S ratio against the pilot link (``corridor.domain.zones``).
A jammer only matters to the mission if its ``bands`` contain the mission ``band``. Radars are
discs (``radius_m``) and block every band. Friendly jammers are on except during cuts. ``cuts``
in the file are cuts already scheduled at start; they still need the operator's confirmation,
like any other cut.
"""

from __future__ import annotations

import itertools
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, model_validator

from corridor.domain.geo import Position
from corridor.domain.model import Model


class PlannedCut(Model):
    start_s: float = Field(ge=0)
    end_s: float

    @model_validator(mode="after")
    def _end_after_start(self) -> Self:
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be after start_s")
        return self


class FriendlyJammer(Model):
    id: str
    operator_callsign: str
    pos: Position
    eirp_w: float = Field(gt=0, description="Effective isotropic radiated power, watts.")
    bands: list[str] = Field(min_length=1)
    cuts: list[PlannedCut] = Field(default_factory=list)

    @model_validator(mode="after")
    def _cuts_do_not_overlap(self) -> Self:
        ordered = sorted(self.cuts, key=lambda c: c.start_s)
        for before, after in itertools.pairwise(ordered):
            if after.start_s < before.end_s:
                raise ValueError(f"{self.id}: overlapping cuts")
        return self


class EnemyRadar(Model):
    type: Literal["radar"] = "radar"
    id: str
    pos: Position
    radius_m: float = Field(gt=0, description="Estimated detection range.")


class EnemyJammer(Model):
    type: Literal["jammer"] = "jammer"
    id: str
    pos: Position
    eirp_w: float = Field(gt=0, description="Estimated EIRP, watts.")
    bands: list[str] = Field(min_length=1)


EnemyThreat = Annotated[EnemyRadar | EnemyJammer, Field(discriminator="type")]


class Mission(Model):
    id: str
    drone_id: str
    pilot_callsign: str = Field(description="The pilot stands at the launch point.")
    launch: Position
    target: Position
    band: str
    link_eirp_w: float = Field(gt=0, description="EIRP of the pilot's control link, watts.")
    cruise_speed_mps: float = Field(gt=0)
    battery_max_s: float = Field(gt=0, description="Flight time on a full battery.")
    departure_s: float = Field(ge=0, description="Earliest departure.")


class Scenario(Model):
    start_time: AwareDatetime = Field(description="Wall-clock time of simulated t = 0.")
    js_threshold_db: float = Field(
        description="The control link is lost where J/S at the drone reaches this value."
    )
    friendly_jammers: list[FriendlyJammer]
    enemy_threats: list[EnemyThreat] = Field(default_factory=list)
    mission: Mission

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [
            *(j.id for j in self.friendly_jammers),
            *(t.id for t in self.enemy_threats),
            self.mission.id,
        ]
        duplicates = sorted(i for i, n in Counter(ids).items() if n > 1)
        if duplicates:
            raise ValueError(f"duplicate ids: {duplicates}")
        return self

    def friendly_jammer(self, jammer_id: str) -> FriendlyJammer | None:
        return next((j for j in self.friendly_jammers if j.id == jammer_id), None)

    def clock_label(self, t: float) -> str:
        """Simulated time as wall-clock ``HH:MM:SS``, for human-facing text."""
        return (self.start_time + timedelta(seconds=t)).strftime("%H:%M:%S")


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate_json(path.read_text(encoding="utf-8"))
