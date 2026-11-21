import pytest

from corridor.domain.geo import Grid, Position

GRID = Grid(origin=Position(lat=48.1, lon=11.5), cell_m=100, cols=100, rows=100)


def test_round_trip_to_metres() -> None:
    p = GRID.to_position(5000.0, 3000.0)
    x, y = GRID.to_xy(p)
    assert x == pytest.approx(5000.0)
    assert y == pytest.approx(3000.0)


def test_cell_of_counts_from_south_west_corner() -> None:
    assert GRID.cell_of(GRID.to_position(50.0, 50.0)) == (0, 0)
    assert GRID.cell_of(GRID.to_position(5050.0, 250.0)) == (50, 2)
    assert GRID.cell_of(GRID.to_position(9999.0, 9999.0)) == (99, 99)


def test_cell_of_outside_grid() -> None:
    assert GRID.cell_of(GRID.to_position(-1.0, 50.0)) is None
    assert GRID.cell_of(GRID.to_position(50.0, 10_001.0)) is None


def test_covering_grid_keeps_the_margin_around_every_point() -> None:
    a = GRID.to_position(1050.0, 2050.0)
    b = GRID.to_position(4050.0, 2550.0)
    grid = Grid.covering([a, b], margin_m=550, cell_m=100)
    assert (grid.cols, grid.rows) == (41, 16)
    assert grid.cell_of(a) == (5, 5)
    assert grid.cell_of(b) == (35, 10)


def test_covering_needs_a_point() -> None:
    with pytest.raises(ValueError):
        Grid.covering([], margin_m=500, cell_m=100)
