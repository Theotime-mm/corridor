from typing import Any

import pytest
from pydantic import ValidationError

from corridor.domain.scenario import EnemyRadar, Scenario
from corridor.domain.state import WorldState


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
    data["mission"]["cruise_speed_ms"] = 15
    with pytest.raises(ValidationError):
        Scenario.model_validate(data)
