"""Accelerated simulation clock.

The wall-clock source is injectable, so tests drive time by hand.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from corridor.domain.state import ClockState


class SimClock:
    """Simulated seconds from the scenario epoch. Starts paused at t = 0."""

    def __init__(self, factor: float, wall: Callable[[], float] = time.monotonic) -> None:
        if factor <= 0:
            raise ValueError("factor must be positive")
        self._wall = wall
        self._factor = factor
        self._paused = True
        self._anchor_sim = 0.0
        self._anchor_wall = wall()

    def now(self) -> float:
        if self._paused:
            return self._anchor_sim
        return self._anchor_sim + (self._wall() - self._anchor_wall) * self._factor

    def set(self, factor: float | None = None, paused: bool | None = None) -> None:
        self._anchor_sim = self.now()
        self._anchor_wall = self._wall()
        if factor is not None:
            if factor <= 0:
                raise ValueError("factor must be positive")
            self._factor = factor
        if paused is not None:
            self._paused = paused

    def state(self) -> ClockState:
        return ClockState(sim_time_s=self.now(), factor=self._factor, paused=self._paused)
