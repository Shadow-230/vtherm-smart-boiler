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
        0.0, 0.0, 7.0, None, outdoor_mean=5.0, heat_kwh=46.0,
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


def midnight_burn(end_min: float | None = 20.0) -> History:
    """A heating burn from 23:50 to ``end_min`` minutes past midnight (``None``: still burning),
    at 50 % modulation with the return at 45 °C."""
    flame = Series[bool]([(0, False), (DAY - 10 * MIN, True)])
    if end_min is not None:
        flame.append(DAY + end_min * MIN, False)
    return History(
        signals={
            Signal.FLAME: flame,
            Signal.RETURN: Series([(0, 45.0)]),
            Signal.MODULATION: Series([(0, 50.0)]),
            Signal.DHW_ACTIVE: Series([(0, False)]),
        },
        weather=Series([(0, 8.0)]),
    )


POWER = PARAMETERS.with_estimate(
    ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED)
).with_estimate(ParameterKey.BOILER_MAX_POWER, Estimate(24.0, Source.ENTERED))


def test_a_burn_across_midnight_is_complete_in_its_start_day() -> None:
    """P-83: a burn from 23:50 to 00:20 is one whole burn of 30 minutes, counted in the day it
    started; its time is split at midnight — 10 minutes in the first day, 20 in the next,
    which has no start."""
    from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions

    history = midnight_burn()
    first = summarize_day(history, POWER, 0, DAY, known_until=2 * DAY)
    assert (first.starts, first.complete_burns) == (1, 1)
    assert first.burn_s == pytest.approx(10 * MIN)
    assert first.condensing_basis_s == pytest.approx(10 * MIN)
    assert first.heat_kwh == pytest.approx(14.0 * 10 / 60)  # 14 kW at 50 %, 10 minutes
    # Its length is the whole burn's: short below 31 minutes, not below 29.
    longer = MonitorOptions(short_burn_s=31 * MIN)
    assert summarize_day(history, POWER, 0, DAY, longer, known_until=2 * DAY).short_burns == 1
    shorter = MonitorOptions(short_burn_s=29 * MIN)
    assert summarize_day(history, POWER, 0, DAY, shorter, known_until=2 * DAY).short_burns == 0
    second = summarize_day(history, POWER, DAY, 2 * DAY, known_until=2 * DAY)
    assert (second.starts, second.complete_burns, second.short_burns) == (0, 0, 0)
    assert second.burn_s == pytest.approx(20 * MIN)
    assert second.condensing_basis_s == pytest.approx(20 * MIN)
    assert second.heat_kwh == pytest.approx(14.0 * 20 / 60)


def test_a_burn_is_not_followed_past_what_the_history_knows() -> None:
    """P-83's margin stops where the history does: a burn still running when the analysis runs
    is not taken to last twelve more hours."""
    history = midnight_burn(end_min=None)
    day = summarize_day(history, POWER, 0, DAY, known_until=DAY + 3 * MIN)
    assert (day.starts, day.complete_burns) == (1, 0)  # its end is not seen yet
    assert day.burn_s == pytest.approx(10 * MIN)
    today = summarize_day(history, POWER, DAY, DAY + 3 * MIN, known_until=DAY + 3 * MIN)
    assert today.burn_s == pytest.approx(3 * MIN)


def test_a_day_waits_for_a_burn_still_running() -> None:
    """P-83: a burn running at 00:03 that started the day before: that day is not summarised
    until the flame goes off, or six hours after its end — whichever comes first."""
    from custom_components.vtherm_smart_boiler.core.analysis import analyse
    from custom_components.vtherm_smart_boiler.core.daily import day_settled
    from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions

    running = midnight_burn(end_min=None)
    assert not day_settled(running, 0, DAY, DAY + 3 * MIN)
    assert not day_settled(running, 0, DAY, DAY + 6 * HOUR - 1)
    assert day_settled(running, 0, DAY, DAY + 6 * HOUR)  # six hours: summarised all the same
    result = analyse(running, POWER, MonitorOptions(), DAY + 3 * MIN, [(0, DAY)])
    assert result.new_days == ()  # not kept yet …
    [monitored] = [r for r in result.verdict.reasons if r.code.value == "monitored_days"]
    assert monitored.value == pytest.approx(1.0 + 3 / 1440)  # … but counted as it stands
    ended = midnight_burn(end_min=20.0)
    assert day_settled(ended, 0, DAY, DAY + 25 * MIN)
    result = analyse(ended, POWER, MonitorOptions(), DAY + 25 * MIN, [(0, DAY)])
    [day] = result.new_days
    assert (day.starts, day.complete_burns) == (1, 1)


def test_a_day_does_not_wait_for_a_flame_it_cannot_see() -> None:
    """The negative: a flame gone unknown before the analysis leaves nothing running to wait
    for (the burn ended unseen), and a day without a flame signal has no burns at all."""
    from custom_components.vtherm_smart_boiler.core.daily import day_settled

    history = midnight_burn(end_min=None)
    history.signals[Signal.FLAME].append(DAY - 5 * MIN, None)
    assert day_settled(history, 0, DAY, DAY + 3 * MIN)
    assert day_settled(History(), 0, DAY, DAY + 3 * MIN)


def test_days_under_control_carry_controlled_s() -> None:
    """P-96 (A12): each day keeps its time under control — the control state heating, idle,
    frost, fallback or the boiler's own fault — from the plugin's own control-state history.
    The verdict leaves out days with an hour of it or more, and says how many."""
    history = cycling(1)
    history.control_state = Series(
        [
            (0, "heating"),
            (3 * HOUR, "idle"),
            (5 * HOUR, "handed_back"),
            (6 * HOUR, "frost"),
            (6.5 * HOUR, "fallback"),
            (7 * HOUR, "boiler_fault"),
            (7.5 * HOUR, None),
            (8 * HOUR, "disabled"),
            (9 * HOUR, "waiting_data"),
            (10 * HOUR, "not_allowed"),
        ]
    )
    day = summarize_day(history, PARAMETERS, 0, DAY)
    assert day.controlled_s == pytest.approx(6.5 * HOUR)
    assert day.under_control
    assert DaySummary.from_dict(day.to_dict()) == day
    # A day with less than an hour of it counts as uncontrolled.
    short = cycling(1)
    short.control_state = Series([(0, "heating"), (59 * MIN, "handed_back")])
    brief = summarize_day(short, PARAMETERS, 0, DAY)
    assert brief.controlled_s == pytest.approx(59 * MIN)
    assert not brief.under_control


def test_days_without_a_control_history_are_uncontrolled() -> None:
    """The negative: control never configured leaves no control-state history — 0 s; a day
    stored before the field existed reads ``None`` and counts as uncontrolled, as no release
    ever controlled."""
    day = summarize_day(cycling(1), PARAMETERS, 0, DAY)
    assert day.controlled_s == 0.0
    assert not day.under_control
    legacy = {k: v for k, v in day.to_dict().items() if k != "controlled_s"}
    stored = DaySummary.from_dict(legacy)
    assert stored.controlled_s is None
    assert not stored.under_control


def test_the_verdict_leaves_out_days_under_control() -> None:
    """P-96: the verdict is the installation's own, without control: days with an hour of
    control or more are left out — today's too — and their number is given."""
    from dataclasses import replace

    options = VerdictOptions(min_days=7.0)
    baseline = days_of(cycling(7, every_min=12.0), 7)  # five starts an hour
    controlled = [
        replace(day, start=day.start + 7 * DAY, end=day.end + 7 * DAY, controlled_s=2 * HOUR)
        for day in days_of(cycling(3, every_min=60.0), 3)
    ]
    today = replace(controlled[0], start=10 * DAY, end=10 * DAY + HOUR)
    result = verdict_over_days([*baseline, *controlled], options, window_days=7, current=today)
    # Frequent starts found: a problem 0.2.2's control does not change (answer K).
    assert result.verdict is Verdict.NOT_WORTH_IT
    assert result.days_left_out == 4
    codes = {r.code.value: r.value for r in result.reasons}
    assert codes["frequent_starts"] == pytest.approx(5.0)
    # Without the tag the calm controlled days would take the window's place.
    untagged = [replace(day, controlled_s=None) for day in controlled]
    mixed = verdict_over_days([*baseline, *untagged], options, window_days=7)
    assert mixed.days_left_out == 0
    mixed_codes = {r.code.value: r.value for r in mixed.reasons}
    assert mixed_codes["frequent_starts"] == pytest.approx((4 * 120 + 3 * 24) / (7 * 24))


def test_a_stuck_outdoor_sensor_gives_way_to_the_weather_in_a_day() -> None:
    """P-86: a day checks the boiler's outdoor sensor against the weather over that day; a
    sensor found stuck is left out, and the weather gives the day's outdoor temperature and
    degree-days."""
    history = cycling(1)
    history.signals[Signal.OUTDOOR] = Series([(0, 8.0)])  # stuck at 8 °C all day
    history.weather = Series([(k * HOUR, 2.0 + (k % 12)) for k in range(24)])  # 2 to 13 °C
    day = summarize_day(history, PARAMETERS, 0, DAY)
    assert day.outdoor_mean == pytest.approx(7.5)
    assert day.degree_days == pytest.approx(7.5)  # base 15 °C
    # A sensor that moves with the weather is kept.
    history.signals[Signal.OUTDOOR] = Series([(k * HOUR, 1.0 + (k % 12)) for k in range(24)])
    assert summarize_day(history, PARAMETERS, 0, DAY).outdoor_mean == pytest.approx(6.5)


def test_a_stuck_sensor_without_the_weather_leaves_the_day_unknown() -> None:
    """P-86's negative: the sensor found stuck while the weather was there, then the weather
    lost for most of the day — the day's outdoor temperature and degree-days are unknown,
    not the stuck value; with no weather entity at all the sensor cannot be judged and is
    used as before."""
    history = cycling(1)
    history.signals[Signal.OUTDOOR] = Series([(0, 8.0)])
    history.weather = Series([*((k * HOUR, 2.0 + k / 2) for k in range(13)), (13 * HOUR, None)])
    day = summarize_day(history, PARAMETERS, 0, DAY)
    assert day.outdoor_mean is None
    assert day.degree_days is None
    history.weather = Series()
    alone = summarize_day(history, PARAMETERS, 0, DAY)
    assert alone.outdoor_mean == pytest.approx(8.0)


def test_a_reset_value_is_fitted_from_later_days_only() -> None:
    """P-90: the user reset a measured value at ``t0``; it is fitted again from the days that
    start from then on only, the other value from every kept day — each reset forgets only its
    own value. Here the house changed at ``t0`` (insulated: threshold 18 → 16 °C, loss 0.25 →
    0.2 kW/K)."""
    from custom_components.vtherm_smart_boiler.core.daily import fit_building
    from custom_components.vtherm_smart_boiler.core.parameters import DEFAULT_CONFIDENCE

    def kept(first: int, loss: float, threshold: float) -> list[DaySummary]:
        days = []
        for index in range(20):
            outdoor = -5.0 + 15.0 * index / 19
            start = (first + index) * DAY
            day = DaySummary(
                start, start + DAY, DAY, 10, 10, 0, HOUR, 10 * HOUR, 0.0, 0.0, None, None,
                outdoor_mean=outdoor, heat_kwh=24 * loss * (threshold - outdoor),
            )  # fmt: skip
            days.append(day)
        return days

    t0 = 20 * DAY
    days = [*kept(0, 0.25, 18.0), *kept(20, 0.2, 16.0)]
    threshold = Estimate(20.0, Source.DEFAULT, DEFAULT_CONFIDENCE)
    both = fit_building(days, threshold, 50 * DAY)  # no reset: every day, a blend
    assert both is not None
    assert both.loss is not None
    assert both.threshold is not None
    assert both.loss.value == pytest.approx(0.225)
    assert both.threshold.value == pytest.approx(17.1, abs=0.1)
    reset_threshold = fit_building(days, threshold, 50 * DAY, {ParameterKey.HEATING_THRESHOLD: t0})
    assert reset_threshold is not None
    assert reset_threshold.threshold is not None
    assert reset_threshold.threshold.value == pytest.approx(16.0)  # the later days only
    assert reset_threshold.loss == both.loss  # every day, as without a reset
    reset_loss = fit_building(days, threshold, 50 * DAY, {ParameterKey.LOSS_COEFFICIENT: t0})
    assert reset_loss is not None
    assert reset_loss.loss is not None
    assert reset_loss.loss.value == pytest.approx(0.2)
    assert reset_loss.threshold == both.threshold
    after = {ParameterKey.LOSS_COEFFICIENT: t0, ParameterKey.HEATING_THRESHOLD: t0}
    reset_both = fit_building(days, threshold, 50 * DAY, after)
    assert reset_both is not None
    assert reset_both.loss is not None
    assert reset_both.threshold is not None
    assert (reset_both.loss.value, reset_both.threshold.value) == (
        pytest.approx(0.2),
        pytest.approx(16.0),
    )
    # Reset just now: no later day yet — nothing measured for it, the other still fitted.
    now = {ParameterKey.HEATING_THRESHOLD: 40 * DAY}
    fresh = fit_building(days, threshold, 50 * DAY, now)
    assert fresh is not None
    assert fresh.threshold is None
    assert fresh.loss == both.loss
    both_now = {ParameterKey.HEATING_THRESHOLD: 40 * DAY, ParameterKey.LOSS_COEFFICIENT: 40 * DAY}
    assert fit_building(days, threshold, 50 * DAY, both_now) is None


def test_the_analysis_gives_no_verdict_without_a_flame_signal() -> None:
    """S-43: a history with no flame signal mapped — a relay without one, say — gets "not
    enough data" with the reason ``no_burner_signal``, whatever else it holds."""
    from custom_components.vtherm_smart_boiler.core.analysis import analyse
    from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions
    from custom_components.vtherm_smart_boiler.core.verdict import Reason, ReasonCode, ReasonKind

    history = History(signals={Signal.FLOW: Series([(0, 40.0)])}, weather=Series([(0, 5.0)]))
    days = [(d * DAY, (d + 1) * DAY) for d in range(8)]
    result = analyse(history, PARAMETERS, MonitorOptions(), 8 * DAY, days)
    assert result.verdict.verdict is Verdict.NOT_ENOUGH_DATA
    assert result.verdict.reasons == (Reason(ReasonCode.NO_BURNER_SIGNAL, ReasonKind.DATA),)
    mapped = analyse(cycling(8), PARAMETERS, MonitorOptions(), 8 * DAY, days)
    assert ReasonCode.NO_BURNER_SIGNAL not in {r.code for r in mapped.verdict.reasons}
