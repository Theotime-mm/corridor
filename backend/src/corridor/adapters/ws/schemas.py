"""WebSocket wire format.

Client to server: ``{"req_id": "...", "command": {"type": "cut.schedule", ...}}``.
Server to client: ``{"seq": 42, "sim_time_s": 900.0, "payload": {"type": "...", ...}}``.

Domain events go out as they are, wrapped in the envelope. ``seq`` grows by one per broadcast
event; ``snapshot``, ``ack`` and ``error`` carry the current ``seq`` without incrementing it.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from corridor.domain.commands import Command
from corridor.domain.events import Event
from corridor.domain.geo import Grid
from corridor.domain.model import Model
from corridor.domain.scenario import Scenario
from corridor.domain.state import ClockState, Cut, MissionStatus
from corridor.domain.zones import Zone


class Snapshot(Model):
    """Full state, sent on connect. Enough to render any instant on the client."""

    type: Literal["snapshot"] = "snapshot"
    scenario: Scenario
    grid: Grid = Field(description="Planning grid, derived from the scenario positions.")
    zones: list[Zone] = Field(description="Zones that matter to the mission, see domain.zones.")
    clock: ClockState
    cuts: list[Cut]
    mission_status: MissionStatus


class Ack(Model):
    type: Literal["ack"] = "ack"
    req_id: str


class Error(Model):
    type: Literal["error"] = "error"
    req_id: str | None = Field(description="None when the message could not be parsed.")
    reason: str


Reply = Annotated[Snapshot | Ack | Error, Field(discriminator="type")]


class ClientMessage(Model):
    req_id: str
    command: Command


class ServerMessage(Model):
    seq: int
    sim_time_s: float
    payload: Event | Reply
