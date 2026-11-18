"""The weeks the Boiler page's Use tab draws (``docs/en/development/plans/plan-0.2-i10.md``,
I10.5): gas per degree-day week by week, from the daily summaries — the same rule as the
monitor's, a week whose gas is not known for every day having none."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.weekly import weekly_use

DAY = 86400.0


def day(index: int, gas: float | None, degree_days: float | None) -> DaySummary:
    start = index * DAY
    return replace(DaySummary.empty(start, start + DAY), gas=gas, degree_days=degree_days)


def test_weeks_count_back_from_the_newest_day() -> None:
    days = [day(i, 10.0, 2.0) for i in range(14)]
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
