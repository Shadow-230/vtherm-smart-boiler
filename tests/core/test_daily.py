"""Daily summaries: what the verdict needs from each day, adding up across days."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.daily import (
    DaySummary,
    fit_points,
    settings_key,
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


def test_a_day_remembers_the_settings_it_was_summarised_with() -> None:
    """A4: a day carries the key of the settings behind it, through the store too."""
    [day] = [summarize_day(cycling(1), PARAMETERS, 0.0, DAY, settings="abc")]
    assert day.settings == "abc"
    assert DaySummary.from_dict(day.to_dict()) == day
    legacy = {k: v for k, v in day.to_dict().items() if k != "settings"}
    assert DaySummary.from_dict(legacy).settings == ""  # stored before it had one


def test_the_settings_key_changes_with_every_setting_that_shapes_a_day() -> None:
    base = {"has_dhw": True, "condensing_return": 55.0, "signals": {"flame": "binary_sensor.f"}}
    assert settings_key(base) == settings_key(dict(reversed(list(base.items()))))
    for changed in (
        base | {"has_dhw": False},
        base | {"condensing_return": 50.0},
        base | {"signals": {"flame": "binary_sensor.g"}},
    ):
        assert settings_key(changed) != settings_key(base)


def test_days_summarised_with_other_settings_are_left_out_and_redone() -> None:
    """A4: the user corrects a setting (the hot-water type, say). Days summarised with the old
    one no longer count; those the history still holds are summarised again."""
    from custom_components.vtherm_smart_boiler.core.analysis import analyse
    from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions

    history = cycling(9)
    days = [(d * DAY, (d + 1) * DAY) for d in range(1, 9)]
    old = [summarize_day(history, PARAMETERS, a, b, settings="old") for a, b in days]
    result = analyse(history, PARAMETERS, MonitorOptions(), 9 * DAY, days, old, settings="new")
    assert {day.start for day in result.new_days} == {a for a, _b in days}  # all done again
    assert {day.settings for day in result.new_days} == {"new"}
    kept = [summarize_day(history, PARAMETERS, a, b, settings="new") for a, b in days]
    again = analyse(history, PARAMETERS, MonitorOptions(), 9 * DAY, days, kept, settings="new")
    assert again.new_days == ()  # nothing to redo


def test_today_does_not_take_a_place_in_the_verdict_window() -> None:
    """A5: with a window as long as the monitoring period, today's first hours took one of its
    days: "not enough data" every night until morning, weeks of data kept."""
    history = cycling(31)
    days = days_of(history, 30)
    today = summarize_day(history, PARAMETERS, 30 * DAY, 30 * DAY + HOUR)  # one hour in
    options = VerdictOptions(min_days=7.0)
    result = verdict_over_days(days, options, window_days=7, current=today)
    assert result.verdict is not Verdict.NOT_ENOUGH_DATA
