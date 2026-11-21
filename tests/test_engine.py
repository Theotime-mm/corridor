import pytest

from corridor.domain.commands import (
    CancelCut,
    ConfirmCut,
    LaunchMission,
    ScheduleCut,
    SetClock,
)
from corridor.domain.events import (
    ClockChanged,
    CutConfirmed,
    CutScheduled,
    Event,
    MissionStatusChanged,
    Notification,
)
from corridor.domain.scenario import Scenario
from corridor.engine.clock import SimClock
from corridor.engine.engine import CommandRejected, Engine

EW = "EW-OFFICER"


@pytest.fixture
def engine(scenario: Scenario) -> Engine:
    return Engine(scenario, SimClock(20, wall=lambda: 0.0))


def schedule(engine: Engine, start: float = 900, end: float = 1260) -> str:
    events = engine.submit(ScheduleCut(actor=EW, jammer="J3", start_s=start, end_s=end))
    assert isinstance(events[0], CutScheduled)
    return events[0].cut.id


def test_schedule_cut_notifies_the_operator(engine: Engine) -> None:
    published: list[Event] = []
    engine.subscribe(published.append)
    events = engine.submit(ScheduleCut(actor=EW, jammer="J3", start_s=900, end_s=1260))
    assert published == events
    scheduled, notification = events
    assert isinstance(scheduled, CutScheduled)
    assert scheduled.cut.status == "scheduled"
    assert isinstance(notification, Notification)
    assert notification.to == "EW-J3"
    assert "14:15:00 to 14:21:00" in notification.text
    assert notification.action is not None
    assert notification.action.cut == scheduled.cut.id


@pytest.mark.parametrize(
    ("jammer", "start", "end", "reason"),
    [
        ("R1", 900, 1000, "unknown friendly jammer"),
        ("J3", 1000, 1100, "overlaps"),
    ],
)
def test_schedule_cut_rejections(
    engine: Engine, jammer: str, start: float, end: float, reason: str
) -> None:
    schedule(engine)
    with pytest.raises(CommandRejected, match=reason):
        engine.submit(ScheduleCut(actor=EW, jammer=jammer, start_s=start, end_s=end))


def test_schedule_cut_in_the_past_is_rejected(scenario: Scenario) -> None:
    wall = [0.0]
    engine = Engine(scenario, SimClock(20, wall=lambda: wall[0]))
    engine.submit(SetClock(actor=EW, paused=False))
    wall[0] = 25.0  # 500 simulated seconds
    with pytest.raises(CommandRejected, match="past"):
        engine.submit(ScheduleCut(actor=EW, jammer="J3", start_s=400, end_s=600))


def test_only_the_jammer_operator_confirms(engine: Engine) -> None:
    cut_id = schedule(engine)
    with pytest.raises(CommandRejected, match="only the operator"):
        engine.submit(ConfirmCut(actor="PILOT-1", cut=cut_id))
    assert engine.state.cuts[cut_id].status == "scheduled"

    (event,) = engine.submit(ConfirmCut(actor="EW-J3", cut=cut_id))
    assert isinstance(event, CutConfirmed)
    assert engine.state.cuts[cut_id].status == "confirmed"
    with pytest.raises(CommandRejected, match="already confirmed"):
        engine.submit(ConfirmCut(actor="EW-J3", cut=cut_id))


def test_cancel_cut(engine: Engine) -> None:
    cut_id = schedule(engine)
    engine.submit(CancelCut(actor=EW, cut=cut_id))
    assert engine.state.cuts == {}
    with pytest.raises(CommandRejected, match="unknown cut"):
        engine.submit(CancelCut(actor=EW, cut=cut_id))


def test_launch_mission_once(engine: Engine) -> None:
    (event,) = engine.submit(LaunchMission(actor="PILOT-1"))
    assert event == MissionStatusChanged(status="flying")
    with pytest.raises(CommandRejected, match="already flying"):
        engine.submit(LaunchMission(actor="PILOT-1"))


def test_set_clock(engine: Engine) -> None:
    (event,) = engine.submit(SetClock(actor=EW, factor=30, paused=False))
    assert isinstance(event, ClockChanged)
    assert event.clock.factor == 30
    assert event.clock.paused is False
