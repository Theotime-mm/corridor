from corridor.engine.clock import SimClock


class FakeWall:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_clock_starts_paused_at_zero() -> None:
    wall = FakeWall()
    clock = SimClock(10, wall)
    wall.t += 5
    assert clock.now() == 0.0


def test_clock_runs_at_factor_and_keeps_time_on_changes() -> None:
    wall = FakeWall()
    clock = SimClock(10, wall)
    clock.set(paused=False)
    wall.t += 3
    assert clock.now() == 30.0
    clock.set(factor=20)
    wall.t += 1
    assert clock.now() == 50.0
    clock.set(paused=True)
    wall.t += 100
    assert clock.state().sim_time_s == 50.0
