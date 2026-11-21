from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from corridor.domain.scenario import EnemyRadar, Scenario, load_scenario
from corridor.domain.state import WorldState
from corridor.domain.zones import constraints_by_mission


def _data(scenario: Scenario) -> dict[str, Any]:
    data: dict[str, Any] = scenario.model_dump(mode="json")
    return data


def test_demo_scenario_loads(scenario: Scenario) -> None:
    jammer = scenario.friendly_jammer("J3")
    assert jammer is not None
    assert jammer.operator_callsign == "EW-J3"
    assert scenario.friendly_jammer("R1") is None
    assert isinstance(scenario.enemy_threats[0], EnemyRadar)


def test_clock_label_uses_start_time(scenario: Scenario) -> None:
    assert scenario.clock_label(15 * 60 + 30) == "14:15:30"


def test_scenario_cuts_start_scheduled(scenario: Scenario) -> None:
    data = _data(scenario)
    data["friendly_jammers"][0]["cuts"] = [{"start_s": 900, "end_s": 1260}]
    state = WorldState.from_scenario(Scenario.model_validate(data))
    (cut,) = state.cuts.values()
    assert (cut.jammer, cut.start_s, cut.end_s, cut.status) == ("J3", 900, 1260, "scheduled")


def test_overlapping_scenario_cuts_are_rejected(scenario: Scenario) -> None:
    data = _data(scenario)
    data["friendly_jammers"][0]["cuts"] = [
        {"start_s": 900, "end_s": 1260},
        {"start_s": 1200, "end_s": 1500},
    ]
    with pytest.raises(ValidationError, match="overlapping cuts"):
        Scenario.model_validate(data)


def test_duplicate_ids_are_rejected(scenario: Scenario) -> None:
    data = _data(scenario)
    data["enemy_threats"][0]["id"] = "J3"
    with pytest.raises(ValidationError, match="duplicate ids"):
        Scenario.model_validate(data)


def test_unknown_threat_type_is_rejected(scenario: Scenario) -> None:
    data = _data(scenario)
    data["enemy_threats"][0]["type"] = "sam"
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_unknown_field_is_rejected(scenario: Scenario) -> None:
    data = _data(scenario)
    data["missions"][0]["cruise_speed_ms"] = 15
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


def test_roles_come_from_the_scenario(two_missions: Scenario) -> None:
    roles = {c: two_missions.role_of(c) for c in ("CMD", "PILOT-2", "EW-J4", "NOBODY")}
    assert roles == {"CMD": "command", "PILOT-2": "pilot", "EW-J4": "operator", "NOBODY": None}
    assert two_missions.mission("M2") is not None
    assert two_missions.mission("J4") is None


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("drone_id", "UAV-1", "duplicate drones"),
        ("pilot_callsign", "PILOT-1", "duplicate callsigns"),
        ("pilot_callsign", "CMD", "duplicate callsigns"),
        ("pilot_callsign", "EW-J3", "duplicate callsigns"),
        ("id", "M1", "duplicate ids"),
    ],
)
def test_missions_need_their_own_drone_pilot_and_id(
    two_missions: Scenario, field: str, value: str, reason: str
) -> None:
    data = _data(two_missions)
    data["missions"][1][field] = value
    with pytest.raises(ValidationError, match=reason):
        Scenario.model_validate(data)


def test_one_operator_may_run_several_jammers(two_missions: Scenario) -> None:
    data = _data(two_missions)
    data["friendly_jammers"][1]["operator_callsign"] = "EW-J3"
    assert Scenario.model_validate(data).role_of("EW-J3") == "operator"


def test_a_scenario_needs_a_mission(scenario: Scenario) -> None:
    data = _data(scenario)
    data["missions"] = []
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)


@pytest.mark.parametrize("name", ["demo", "directional"])
def test_shipped_scenarios_give_each_mission_its_own_jammer(name: str) -> None:
    shipped = load_scenario(Path(__file__).resolve().parent.parent / "scenarios" / f"{name}.json")
    constraints = constraints_by_mission(shipped, 100)
    assert {m: c.jammers for m, c in constraints.items()} == {"M1": ["J3"], "M2": ["J4"]}
