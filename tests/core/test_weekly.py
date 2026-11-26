"""The weeks the Boiler page's Use tab draws (``docs/en/development/plans/plan-0.2-i10.md``,
I10.5): gas per degree-day week by week, from the daily summaries — the same rule as the
monitor's, a week whose gas is not known for every day having none."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.regression import Line
from custom_components.vtherm_smart_boiler.core.weekly import (
    MIN_WEEK_DEGREE_DAYS,
    week_spread,
    weekly_use,
)

DAY = 86400.0


def day(index: int, gas: float | None, degree_days: float | None) -> DaySummary:
    start = index * DAY
    return replace(DaySummary.empty(start, start + DAY), gas=gas, degree_days=degree_days)


def test_weeks_count_back_from_the_newest_day() -> None:
    days = [day(i, 10.0, 2.0) for i in range(14)]  # 14 K·d a week: just enough (I13.5)
    weeks = weekly_use(days, weeks=3)
    assert [(w.start, w.end) for w in weeks] == [(0.0, 7 * DAY), (7 * DAY, 14 * DAY)]
    assert all(w.gas == pytest.approx(70.0) for w in weeks)
    assert all(w.degree_days == pytest.approx(14.0) for w in weeks)
    assert all(w.per_degree_day == pytest.approx(5.0) for w in weeks)


def test_a_week_with_gas_missing_on_a_day_has_none() -> None:
    days = [day(i, None if i == 3 else 10.0, 2.0) for i in range(7)]
    (week,) = weekly_use(days, weeks=1)
    assert week.gas is None
    assert week.per_degree_day is None
    assert week.degree_days == pytest.approx(14.0)


def test_a_mild_week_has_no_gas_per_degree_day() -> None:
    days = [day(i, 1.0, 0.05) for i in range(7)]  # 0.35 K·d: below the floor
    (week,) = weekly_use(days, weeks=1)
    assert week.per_degree_day is None
    assert week.gas == pytest.approx(7.0)


def test_unknown_degree_days_and_missing_days() -> None:
    days = [day(i, 10.0, None if i == 0 else 2.0) for i in range(7)] + [day(9, 10.0, 2.0)]
    weeks = weekly_use(days, weeks=2)
    # The newest week runs back from day 9: days 3 to 9, two of them missing.
    assert (weeks[-1].start, weeks[-1].end) == (3 * DAY, 10 * DAY)
    assert weeks[-1].days == 5
    assert weeks[-1].gas is None  # gas not known for the days missing
    assert weeks[0].degree_days is None  # day 0's degree-days unknown


def test_no_days_no_weeks() -> None:
    assert weekly_use([], weeks=12) == ()


# --- I13.5: the floor and the band --------------------------------------------------------------


@pytest.mark.parametrize(("per_day", "shown"), [(1.99, False), (2.0, True)])
def test_a_week_shows_its_gas_per_degree_day_from_14_degree_days(
    per_day: float, shown: bool
) -> None:
    """A week of 13.93 K·day is too mild — the threshold's own uncertainty could be as large;
    14 is enough."""
    (week,) = weekly_use([day(i, 10.0, per_day) for i in range(7)], weeks=1)
    assert (week.per_degree_day is not None) is shown
    assert MIN_WEEK_DEGREE_DAYS == 14.0


def _line(deviation: float, rho: float) -> Line:
    """A signature line with this scatter, over 30 days (t about 2.05 without correlation)."""
    return Line(-0.8, 12.0, 30, 2.0, 400.0, deviation, rho)


def test_a_week_gets_a_band_from_the_houses_own_scatter() -> None:
    """Days scattering by 1 a day, uncorrelated: a week's gas scatters by √7, and its band is
    t times that over the week's degree-days."""
    line = _line(1.0, 0.0)
    (week,) = weekly_use([day(i, 10.0, 3.0) for i in range(7)], weeks=1, scatter=line)
    assert week_spread(line) == pytest.approx(7**0.5)
    half = line.t * 7**0.5 / 21.0
    assert week.per_degree_day == pytest.approx(70.0 / 21.0)
    assert (week.low, week.high) == (
        pytest.approx(70.0 / 21.0 - half),
        pytest.approx(70.0 / 21.0 + half),
    )


def test_correlated_days_widen_a_weeks_band_and_it_never_goes_below_zero() -> None:
    """Days that follow each other scatter together: a week's spread grows (the sum's variance
    gains each pair's correlation). A band reaching below zero stops at zero."""
    assert week_spread(_line(1.0, 0.5)) > week_spread(_line(1.0, 0.0))
    (week,) = weekly_use([day(i, 1.0, 3.0) for i in range(7)], weeks=1, scatter=_line(5.0, 0.5))
    assert week.low == 0.0
    assert week.high is not None


def test_no_band_without_a_line_or_a_value() -> None:
    (week,) = weekly_use([day(i, 10.0, 3.0) for i in range(7)], weeks=1)
    assert (week.low, week.high) == (None, None)
    (mild,) = weekly_use([day(i, 10.0, 1.0) for i in range(7)], weeks=1, scatter=_line(1, 0))
    assert (mild.per_degree_day, mild.low, mild.high) == (None, None, None)
    # Thirty days so correlated that they leave no degree of freedom: no band, never a made-up one.
    (spent,) = weekly_use([day(i, 10.0, 3.0) for i in range(7)], weeks=1, scatter=_line(1, 0.9))
    assert spent.per_degree_day is not None
    assert (spent.low, spent.high) == (None, None)
