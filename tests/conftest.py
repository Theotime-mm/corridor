from pathlib import Path

import pytest

from corridor.domain.scenario import Scenario, load_scenario

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def scenario() -> Scenario:
    return load_scenario(ROOT / "scenarios" / "demo.json")
