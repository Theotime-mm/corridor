"""Zones rasterised on the planning grid, over time.

A mask is a boolean array indexed ``[row, col]`` (row grows north, as in ``Grid``), True where
the drone may not be. A cell is forbidden as soon as any part of it may lie on the forbidden
side of a boundary: the test runs on the cell centre, with the boundary pushed out by half the
cell diagonal. A route that stays in free cells therefore never grazes a zone.

Cuts are piecewise constant in time, so the masks are too: one mask per segment between cut
boundaries, not one per time step.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable
from dataclasses import dataclass, field

import numpy as np
import numpy.typing as npt

from corridor.domain.geo import Cell, Grid, LocalFrame
from corridor.domain.state import Cut
from corridor.domain.zones import Disc, ThreatDisc

Mask = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class TimedMasks:
    """Forbidden cells over time: ``masks[k]`` holds on ``[edges[k], edges[k + 1])``.

    ``masks`` has shape (segments, rows, cols). Nothing is known past ``edges[-1]``.
    """

    edges: list[float]
    masks: Mask
    _intervals: dict[Cell, list[tuple[float, float]]] = field(
        default_factory=dict, compare=False, repr=False
    )

    @property
    def shape(self) -> tuple[int, int]:
        """(cols, rows) of the grid."""
        return int(self.masks.shape[2]), int(self.masks.shape[1])

    def safe_intervals(self, cell: Cell) -> list[tuple[float, float]]:
        """Maximal ``(start, end)`` stretches during which ``cell`` is free, in time order.

        Cached: several searches run on the same masks.
        """
        cached = self._intervals.get(cell)
        if cached is not None:
            return cached
        forbidden: list[bool] = self.masks[:, cell[1], cell[0]].tolist()
        runs: list[tuple[float, float]] = []
        for k, blocked in enumerate(forbidden):
            if blocked:
                continue
            if runs and runs[-1][1] == self.edges[k]:
                runs[-1] = (runs[-1][0], self.edges[k + 1])
            else:
                runs.append((self.edges[k], self.edges[k + 1]))
        self._intervals[cell] = runs
        return runs


def disc_mask(grid: Grid, disc: Disc, frame: LocalFrame) -> Mask:
    """Cells that may reach the forbidden side of ``disc``, whose centre is given in ``frame``."""
    cx, cy = grid.to_xy(frame.to_position(disc.x, disc.y))
    xs = (np.arange(grid.cols) + 0.5) * grid.cell_m - cx
    ys = (np.arange(grid.rows) + 0.5) * grid.cell_m - cy
    distance: npt.NDArray[np.float64] = np.hypot(xs[np.newaxis, :], ys[:, np.newaxis])
    half_diagonal = grid.cell_m * math.sqrt(2) / 2
    if disc.forbidden == "inside":
        return distance < disc.radius_m + half_diagonal
    return distance > disc.radius_m - half_diagonal


def timed_masks(
    grid: Grid,
    zones: Iterable[ThreatDisc],
    frame: LocalFrame,
    cuts: Iterable[Cut],
    start_s: float,
    end_s: float,
) -> TimedMasks:
    """Masks from ``start_s`` to ``end_s``. A friendly jammer zone is off during its cuts."""
    zones, cuts = list(zones), list(cuts)
    zone_masks = [disc_mask(grid, z.disc, frame) for z in zones]
    inner = sorted({t for c in cuts for t in (c.start_s, c.end_s) if start_s < t < end_s})
    edges = [start_s, *inner, end_s]
    masks = []
    for a, b in itertools.pairwise(edges):
        middle = (a + b) / 2
        cut_off = {c.jammer for c in cuts if c.start_s <= middle < c.end_s}
        mask = np.zeros((grid.rows, grid.cols), dtype=np.bool_)
        for zone, zone_mask in zip(zones, zone_masks, strict=True):
            if not (zone.kind == "friendly_jammer" and zone.threat in cut_off):
                mask |= zone_mask
        masks.append(mask)
    return TimedMasks(edges=edges, masks=np.stack(masks))
