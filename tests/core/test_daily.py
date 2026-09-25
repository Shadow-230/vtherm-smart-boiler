"""Daily summaries: what the verdict needs from each day, adding up across days."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.daily import (
    DaySummary,
    fit_points,
    summarize_day,
    verdict_over_days,
)
from custom_components.vtherm_smart_boiler.core.history import History
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import Verdict, VerdictOptions

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0


def cycling(days: int, every_min: float = 30.0, gaps: bool = False) -> History:
    """A burn of 10 minutes every ``every_min``; ``gaps``: half a minute unknown at each noon."""
    flame = Series[bool]([(0, False)])
    step = every_min * MIN
    for k in range(int(days * DAY // step)):
        t = k * step
        if gaps and t % DAY == 12 * HOUR:
            flame.append(t + 1, None)
            flame.append(t + 31, False)
        flame.append(t + 5 * MIN, True)
        flame.append(t + 15 * MIN, False)
    return History(
        signals={
            Signal.FLAME: flame,
            Signal.RETURN: Series([(0, 45.0)]),
            Signal.DHW_ACTIVE: Series([(0, False)]),  # every burn heats
        },
        weather=Series([(0, 8.0)]),
    )


PARAMETERS = ParameterSet().with_estimate(
    ParameterKey.LOSS_COEFFICIENT, Estimate(0.2, Source.ENTERED)
)


def days_of(history: History, count: int) -> list[DaySummary]:
    return [summarize_day(history, PARAMETERS, d * DAY, (d + 1) * DAY) for d in range(count)]


def test_a_day_keeps_what_adds_up_and_round_trips() -> None:
    [day] = days_of(cycling(1), 1)
    assert day.observed_s == DAY
    assert day.starts == 48
    assert day.heating_s == DAY  # a burn in every hour
    assert day.condensing_basis_s == pytest.approx(8 * HOUR)
    assert day.degree_days == pytest.approx(7.0)
    assert DaySummary.from_dict(day.to_dict()) == day


def test_the_verdict_is_reached_despite_short_gaps() -> None:
    """P17: seconds of unknown flame after a restart no longer keep the verdict away."""
    days = days_of(cycling(7, gaps=True), 7)
    assert all(d.observed_s < DAY for d in days)
    result = verdict_over_days(days, VerdictOptions(min_days=7.0))
    assert result.verdict is not Verdict.NOT_ENOUGH_DATA


def test_a_monitoring_period_longer_than_a_week_is_reachable() -> None:
    days = days_of(cycling(14), 14)
    assert verdict_over_days(days[:7], VerdictOptions(min_days=14.0)).verdict is (
        Verdict.NOT_ENOUGH_DATA
    )
    assert verdict_over_days(days, VerdictOptions(min_days=14.0)).verdict is not (
        Verdict.NOT_ENOUGH_DATA
    )


def test_the_window_takes_the_latest_days_with_data() -> None:
    """Three days of cycling five times an hour, then seven calm days at one start an hour: a
    seven-day window sees only the calm ones; a day without data is not one of them."""
    busy = days_of(cycling(3, every_min=12.0), 3)
    calm = [
        summarize_day(cycling(10, every_min=60.0), PARAMETERS, d * DAY, (d + 1) * DAY)
        for d in range(3, 10)
    ]
    empty = DaySummary.empty(10 * DAY, 11 * DAY)
    options = VerdictOptions(min_days=7.0)
    window = verdict_over_days([*busy, *calm, empty], options, window_days=7)
    codes = {r.code.value: r.value for r in window.reasons}
    assert codes["few_starts"] == pytest.approx(1.0)
    everything = verdict_over_days([*busy, *calm, empty], options)
    assert "few_starts" not in {r.code.value for r in everything.reasons}


def test_a_day_keeps_its_outdoor_mean_and_heat_for_the_building_fit() -> None:
    """P44: the fit uses every day kept, not only the few the rolling history holds."""
    history = cycling(1)
    history.signals[Signal.MODULATION] = Series([(0, 50.0)])
    parameters = PARAMETERS.with_estimate(
        ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED)
    ).with_estimate(ParameterKey.BOILER_MAX_POWER, Estimate(24.0, Source.ENTERED))
    day = summarize_day(history, parameters, 0, DAY)
    assert day.outdoor_mean == pytest.approx(8.0)
    assert day.heat_kwh == pytest.approx(8 * 14.0)
    [point] = fit_points([day])
    assert (point.outdoor_mean, point.energy_kwh) == (day.outdoor_mean, day.heat_kwh)
    assert fit_points([DaySummary.empty(0, DAY)]) == []


def test_a_day_of_twenty_three_hours_is_fitted_as_a_whole_day() -> None:
    """P63: the day the clocks go forward has 23 hours; its heat counts as a day's."""
    day = DaySummary(
        0.0, 23 * HOUR, 23 * HOUR, 10, 10, 0, HOUR, 10 * HOUR,
        0.0, 0.0, 0.0, 0.0, False, 7.0, None, outdoor_mean=5.0, heat_kwh=46.0,
    )  # fmt: skip
    [point] = fit_points([day])
    assert point.energy_kwh == pytest.approx(48.0)
