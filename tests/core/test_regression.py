"""I13.4: straight lines through daily figures, with an allowance for correlated days."""

from __future__ import annotations

import math

import pytest

from custom_components.vtherm_smart_boiler.core.regression import (
    MAX_LAG_ONE,
    effective_n,
    fit_line,
    lag_one,
    t95,
    widening,
)


@pytest.mark.parametrize(
    ("dof", "expected"),
    [(1, 12.706), (2, 4.303), (3, 3.182), (4, 2.776), (5, 2.571), (10, 2.228), (30, 2.042)],
)
def test_t95_follows_students_table(dof: float, expected: float) -> None:
    """The table's values, and the series within 0.01 of the table from 5 degrees on."""
    assert t95(dof) == pytest.approx(expected, abs=0.01)


def test_t95_rounds_a_small_fraction_down_and_is_infinite_under_one() -> None:
    """Fewer than 5 degrees of freedom: rounded down, the wider range; under 1, no range."""
    assert t95(2.9) == t95(2)
    assert t95(0.99) == math.inf
    assert t95(1e6) == pytest.approx(1.96, abs=0.001)


def test_lag_one_of_alternating_residuals_is_held_at_zero() -> None:
    """Residuals that change sign each day correlate negatively: no allowance, never a
    narrower range."""
    assert lag_one([1.0, -1.0, 1.0, -1.0]) == 0.0


def test_lag_one_of_a_slow_wave() -> None:
    """Residuals that stay on one side for days correlate: about 0.4 here."""
    residuals = [1.0, 1.0, 1.0, -1.0, -1.0, -1.0, 1.0, 1.0, 1.0, -1.0, -1.0, -1.0]
    # 11 pairs: 8 alike, 3 not — (8 − 3) / 12 · 11 / 11.
    assert lag_one(residuals) == pytest.approx(5 / 12)
    assert lag_one([2.0] * 20) == MAX_LAG_ONE  # 19 / 20 = 0.95, held


def test_lag_one_counts_only_neighbours_and_scales_for_the_gaps() -> None:
    """A gap between two days breaks their pair; the pairs left speak for every pair."""
    residuals = [1.0, 1.0, -1.0, -1.0]
    # Only the first and the last pair are neighbours: both alike, 2 / 4 · 3 / 2.
    assert lag_one(residuals, [True, False, True]) == pytest.approx(0.75)
    assert lag_one(residuals, [False, False, False]) == 0.0  # no pair at all


def test_lag_one_of_rounding_only_is_zero() -> None:
    """Residuals of a clean line are rounding, not weather: no correlation."""
    assert lag_one([1e-12, 1e-12, 1e-12], scale=100.0) == 0.0
    assert lag_one([0.0, 0.0, 0.0]) == 0.0


def test_widening_and_effective_n() -> None:
    assert widening(0.0) == 1.0
    assert widening(0.5) == pytest.approx(math.sqrt(3.0))
    assert effective_n(30, 0.5) == pytest.approx(10.0)


def test_a_line_and_its_errors() -> None:
    """y = 10 − 2x with residuals ±1: the slope's error, and the line's error widest at the
    ends."""
    xs = [0.0, 1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [10.0 - 2.0 * x + (1.0 if i % 2 else -1.0) for i, x in enumerate(xs)]
    line = fit_line(xs, ys)
    assert line is not None
    assert line.rho == 0.0  # alternating: no allowance
    assert line.n == 6
    assert line.mean_x == pytest.approx(2.5)
    assert line.sxx == pytest.approx(17.5)
    assert line.at(2.5) == pytest.approx(sum(ys) / 6)
    assert line.slope_error == pytest.approx(line.deviation / math.sqrt(17.5))
    assert line.error_at(2.5) == pytest.approx(line.deviation / math.sqrt(6))
    assert line.error_at(0.0) > line.error_at(2.5)
    assert line.t == pytest.approx(t95(4))


def test_no_line_without_three_points_or_a_spread() -> None:
    assert fit_line([1.0, 2.0], [1.0, 2.0]) is None
    assert fit_line([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
