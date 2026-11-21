"""Safe Interval Path Planning (SIPP): A* over (cell, safe interval).

A safe interval of a cell is a maximal stretch of time during which the cell is free. A search
state is a cell and one of its safe intervals, and its cost is the earliest arrival time in it.
From a state the drone may leave at any time before the interval closes, hovering until then,
so waiting for a cut is part of the search and needs no time step. A cell free all along has
one interval; with no cut, SIPP is plain A* on the grid.

Moves go to the 8 neighbours at cruise speed. A move is safe when both cells are free for its
whole duration (the drone is somewhere between them meanwhile), and for a diagonal, the two
cells whose corner it cuts too.

The heuristic is the octile distance at cruise speed, a lower bound on the time left, waiting
included. So the first time the goal is popped, its arrival is the earliest possible.
"""

from __future__ import annotations

import heapq
import math
from dataclasses import dataclass

from corridor.domain.geo import Cell
from corridor.domain.planner.masks import TimedMasks

NEIGHBOURS = [
    (dc, dr, math.hypot(dc, dr)) for dc in (-1, 0, 1) for dr in (-1, 0, 1) if (dc, dr) != (0, 0)
]

State = tuple[Cell, int]
"""A cell and the index of one of its safe intervals."""


@dataclass(frozen=True)
class Step:
    """The drone reaches ``cell`` at ``arrive_s`` and hovers there until ``depart_s``."""

    cell: Cell
    arrive_s: float
    depart_s: float


def earliest_path(
    timed: TimedMasks,
    start: Cell,
    goal: Cell,
    start_s: float,
    cell_s: float,
    deadline_s: float = math.inf,
) -> list[Step] | None:
    """Earliest arrival at ``goal``, standing in ``start`` at ``start_s``.

    ``cell_s`` is the time to fly one cell straight. None when the goal cannot be reached
    before the masks end, or by ``deadline_s``: the search stops as soon as its lower bound
    passes it, which saves most of the work on a hopeless takeoff time.
    """
    cols, rows = timed.shape
    intervals = timed.safe_intervals

    def inside(cell: Cell) -> bool:
        return 0 <= cell[0] < cols and 0 <= cell[1] < rows

    def free_during(cell: Cell, t1: float, t2: float) -> bool:
        return inside(cell) and any(a <= t1 and t2 <= b for a, b in intervals(cell))

    def heuristic(cell: Cell) -> float:
        dc, dr = abs(cell[0] - goal[0]), abs(cell[1] - goal[1])
        return (max(dc, dr) + (math.sqrt(2) - 1) * min(dc, dr)) * cell_s

    if not (inside(start) and inside(goal)):
        return None
    first_interval = next(
        (i for i, (a, b) in enumerate(intervals(start)) if a <= start_s < b), None
    )
    if first_interval is None:
        return None
    origin: State = (start, first_interval)
    arrival = {origin: start_s}
    parent: dict[State, tuple[State, float]] = {}
    closed: set[State] = set()
    heap = [(start_s + heuristic(start), start_s, origin)]
    while heap:
        bound, t, state = heapq.heappop(heap)
        if bound > deadline_s:
            return None
        if state in closed:
            continue
        closed.add(state)
        cell, index = state
        if cell == goal:
            return _unwind(parent, arrival, state)
        closes = intervals(cell)[index][1]
        for dc, dr, cells in NEIGHBOURS:
            neighbour = (cell[0] + dc, cell[1] + dr)
            if not inside(neighbour):
                continue
            duration = cells * cell_s
            for j, (opens, ends) in enumerate(intervals(neighbour)):
                depart = max(t, opens)
                arrive = depart + duration
                if arrive > closes:
                    break  # later intervals open later still
                if arrive > ends:
                    continue
                corners = ((cell[0] + dc, cell[1]), (cell[0], cell[1] + dr))
                if dc and dr and not all(free_during(c, depart, arrive) for c in corners):
                    continue
                child = (neighbour, j)
                if child in closed or arrive >= arrival.get(child, math.inf):
                    continue
                arrival[child] = arrive
                parent[child] = (state, depart)
                heapq.heappush(heap, (arrive + heuristic(neighbour), arrive, child))
    return None


def _unwind(
    parent: dict[State, tuple[State, float]], arrival: dict[State, float], goal: State
) -> list[Step]:
    steps = [Step(goal[0], arrival[goal], arrival[goal])]
    state = goal
    while state in parent:
        previous, depart = parent[state]
        steps.append(Step(previous[0], arrival[previous], depart))
        state = previous
    return steps[::-1]
