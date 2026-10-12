"""The periodic analysis: the windows it summarises, its verdict, trends, report and fit."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from itertools import pairwise
from typing import Any

import pytest

from custom_components.vtherm_smart_boiler.core.alarms import (
    DEFAULT_FLUE_RISE_K,
    DEFAULT_HYSTERESIS_DRIFT_K,
    DEFAULT_PRESSURE_DROP_BAR,
    HELD,
    NO_ZONE_DATA,
    UNKNOWN_INPUT,
    Alarm,
    AlarmKind,
    Level,
)
from custom_components.vtherm_smart_boiler.core.analysis import (
    HISTORY_DAYS,
    ReportUnit,
    _outdoor,
    _period,
    _report,
    _trends,
    analyse,
)
from custom_components.vtherm_smart_boiler.core.daily import (
    DaySummary,
    fit_building,
    summarize_day,
)
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.monitor import MonitorOptions, summarize
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.report import Cause, PeriodSummary
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import (
    ESTIMATE_ONLY,
    Reason,
    ReasonCode,
    ReasonKind,
    VerdictOptions,
)

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0
NOW = 8 * DAY  # the trends' baseline is then [0, 4 days), their recent window [7, 8 days)

PARAMETERS = ParameterSet().with_estimate(
    ParameterKey.LOSS_COEFFICIENT, Estimate(0.2, Source.ENTERED)
)
POWER = PARAMETERS.with_estimate(
    ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED)
).with_estimate(ParameterKey.BOILER_MAX_POWER, Estimate(24.0, Source.ENTERED))
THRESHOLD = 15.0  # the heating threshold's default


def flame_of(burns: Sequence[tuple[float, float]]) -> Series[bool]:
    """The flame: off from 0, on over each ``(start, end)``."""
    flame = Series[bool]([(0, False)])
    for start, end in burns:
        flame.append(start, True)
        flame.append(end, False)
    return flame


def cycling(days: int, dhw: bool = False) -> History:
    """A burn of 10 minutes every 30 minutes, the return at 45 °C, the weather at 8 °C;
    ``dhw``: the hot-water signal on throughout."""
    burns = [(k * 30 * MIN + 5 * MIN, k * 30 * MIN + 15 * MIN) for k in range(days * 48)]
    return History(
        signals={
            Signal.FLAME: flame_of(burns),
            Signal.RETURN: Series([(0, 45.0)]),
            Signal.DHW_ACTIVE: Series([(0, dhw)]),
        },
        weather=Series([(0, 8.0)]),
    )


# --- The trends: falling pressure, rising flue gas, the burner's hysteresis ---


def half_hourly(first: float, count: int) -> list[float]:
    return [first + k * 30 * MIN for k in range(count)]


BASELINE = half_hourly(3 * DAY, 12)  # 11 pauses, inside the baseline's last day
RECENT = half_hourly(7 * DAY, 11)  # 10 pauses, the first burn at the window's start


def trend_history(
    starts: Sequence[float],
    dhw: bool = False,
    moving_setpoint: tuple[float, float] | None = None,
) -> History:
    """Burns of 10 minutes at ``starts``, a zone calling throughout. Before day 5 the flow is
    60 °C at each stop and 50 °C at each restart, the flue gas 5 K over the 40 °C return; from
    day 5 on, 55 °C at each restart and 8 K. ``moving_setpoint``: within that window the CH
    setpoint moves 6 K in every pause, steady elsewhere."""
    flame = flame_of([(start, start + 10 * MIN) for start in starts])
    flow = Series[float]()
    for start in starts:
        flow.append(start, 50.0 if start < 5 * DAY else 55.0)
        flow.append(start + 10 * MIN, 60.0)
    signals: dict[Signal, Series[Any]] = {
        Signal.FLAME: flame,
        Signal.FLOW: flow,
        Signal.RETURN: Series([(0, 40.0)]),
        Signal.FLUE_GAS: Series([(0, 45.0), (5 * DAY, 48.0)]),
        Signal.DHW_ACTIVE: Series([(0, dhw)]),
    }
    if moving_setpoint is not None:
        low, high = moving_setpoint
        setpoint = Series[float]([(0, 50.0)])
        for before, after in pairwise(s for s in starts if low <= s < high):
            setpoint.append(before + 15 * MIN, 56.0)
            setpoint.append(after - 5 * MIN, 50.0)
        signals[Signal.CH_SETPOINT] = setpoint
    zone = ZoneSeries("zone_a", calling=Series([(0, True)]))
    return History(signals=signals, zones={"zone_a": zone})


def trends_of(
    history: History, condensing: bool = True, previous: dict[AlarmKind, Alarm] | None = None
) -> dict[AlarmKind, Alarm]:
    """The trends as the analysis takes them, from the burns of its whole history."""
    full = summarize(history, PARAMETERS, NOW - HISTORY_DAYS * DAY, NOW)
    return _trends(history, full, NOW, condensing, previous)


# The flue gas rose 3 K (less than its 5 K); the hysteresis fell from 10 K to 5 K (more than 3 K
# either way): each judged now.
JUDGED = {
    AlarmKind.FLUE_GAS_RISING: Alarm(
        AlarmKind.FLUE_GAS_RISING, False, None, 3.0, DEFAULT_FLUE_RISE_K, known_at=NOW
    ),
    AlarmKind.HYSTERESIS_DRIFT: Alarm(
        AlarmKind.HYSTERESIS_DRIFT,
        True,
        Level.WARNING,
        -5.0,
        DEFAULT_HYSTERESIS_DRIFT_K,
        known_at=NOW,
    ),
}
UNKNOWN_HYSTERESIS = Alarm(
    AlarmKind.HYSTERESIS_DRIFT, None, limit=DEFAULT_HYSTERESIS_DRIFT_K, reason=UNKNOWN_INPUT
)
NO_ZONES_HYSTERESIS = Alarm(
    AlarmKind.HYSTERESIS_DRIFT, None, limit=DEFAULT_HYSTERESIS_DRIFT_K, reason=NO_ZONE_DATA
)


def test_the_flue_gas_and_hysteresis_trends_compare_the_baseline_with_the_last_day() -> None:
    """The baseline's last day against the last day: a flue gas 3 K warmer over the return is
    no warning — only a rise over 5 K is; a hysteresis 5 K smaller is one — a drift either way
    over 3 K. Ten pauses in the last day are just enough; the first burn there starts at the
    window's very start and counts."""
    assert trends_of(trend_history([*BASELINE, *RECENT])) == JUDGED


def test_the_pressure_trend_compares_the_medians_of_its_windows() -> None:
    """The quiet, cold pressure 1.5 bar in the baseline's last day and 1.2 bar since: falling
    over 0.2 bar is a warning. Negative: without zone data no pause tells the hysteresis."""
    history = History(
        signals={
            Signal.FLAME: Series([(0, False)]),
            Signal.FLOW: Series([(0, 30.0)]),
            Signal.PRESSURE: Series([(3 * DAY, 1.5), (4 * DAY, 1.2)]),
        }
    )
    assert trends_of(history) == {
        AlarmKind.PRESSURE_FALLING: Alarm(
            AlarmKind.PRESSURE_FALLING,
            True,
            Level.WARNING,
            1.2 - 1.5,
            DEFAULT_PRESSURE_DROP_BAR,
            known_at=NOW,
        ),
        AlarmKind.HYSTERESIS_DRIFT: NO_ZONES_HYSTERESIS,
    }


@pytest.mark.parametrize(
    "window",
    [(0.0, 4 * DAY), (7 * DAY, 8 * DAY)],
    ids=["baseline", "recent"],
)
def test_a_pause_with_the_setpoint_moving_is_no_hysteresis_sample(
    window: tuple[float, float],
) -> None:
    """Negative (PB-67): where the CH setpoint moves in every pause of one window, that window
    has no sample: the drift cannot be judged."""
    history = trend_history([*BASELINE, *RECENT], moving_setpoint=window)
    assert trends_of(history)[AlarmKind.HYSTERESIS_DRIFT] == UNKNOWN_HYSTERESIS


def test_a_burn_starting_at_the_baselines_end_is_in_neither_window() -> None:
    """Negative: nine pauses before the baseline's end and a burn starting just at it: the
    pause before that burn is not the tenth sample — too few, the drift is not judged."""
    starts = [*half_hourly(3 * DAY, 10), 4 * DAY, *RECENT]
    assert trends_of(trend_history(starts))[AlarmKind.HYSTERESIS_DRIFT] == UNKNOWN_HYSTERESIS


def without(history: History, *signals: Signal) -> History:
    for signal in signals:
        del history.signals[signal]
    return history


@pytest.mark.parametrize(
    ("history", "condensing", "kinds"),
    [
        (trend_history([*BASELINE, *RECENT]), False, {AlarmKind.HYSTERESIS_DRIFT}),
        (
            without(trend_history([*BASELINE, *RECENT]), Signal.FLUE_GAS),
            True,
            {AlarmKind.HYSTERESIS_DRIFT},
        ),
        (History(signals={Signal.FLOW: Series([(0, 40.0)])}), True, set()),
    ],
    ids=["non_condensing", "no_flue_gas", "no_flame"],
)
def test_a_trend_without_its_signals_is_left_out(
    history: History, condensing: bool, kinds: set[AlarmKind]
) -> None:
    """Negative: a non-condensing boiler, or one without a flue gas sensor, has no flue gas
    trend; without a flame signal no hysteresis trend."""
    assert set(trends_of(history, condensing)) == kinds


def test_the_analysis_judges_trends_from_its_whole_history() -> None:
    """The analysis' trends come from the burns of its eight days, kinds told with its options:
    a boiler declared without hot water heats with every burn, whatever its hot-water signal."""
    history = trend_history([*BASELINE, *RECENT], dhw=True)
    result = analyse(history, PARAMETERS, MonitorOptions(has_dhw=False), NOW)
    assert result.trends == JUDGED


def test_a_trend_that_cannot_be_judged_keeps_its_last_state_for_an_hour() -> None:
    """S-16: the drift judged half an hour ago is held; one judged two hours ago is unknown now,
    its last known moment kept. Negative: nothing before — unknown at once."""
    history = History(
        signals={Signal.FLAME: Series([(0, False)]), Signal.FLOW: Series([(0, 40.0)])}
    )
    kind = AlarmKind.HYSTERESIS_DRIFT
    recent = Alarm(
        kind, True, Level.WARNING, 4.0, DEFAULT_HYSTERESIS_DRIFT_K, known_at=NOW - HOUR / 2
    )
    held = analyse(history, PARAMETERS, MonitorOptions(), NOW, previous={kind: recent})
    assert held.trends == {kind: replace(recent, reason=HELD)}
    old = replace(recent, known_at=NOW - 2 * HOUR)
    expired = analyse(history, PARAMETERS, MonitorOptions(), NOW, previous={kind: old})
    assert expired.trends == {kind: replace(NO_ZONES_HYSTERESIS, known_at=NOW - 2 * HOUR)}
    assert analyse(history, PARAMETERS, MonitorOptions(), NOW).trends == {kind: NO_ZONES_HYSTERESIS}


# --- The analysis: its windows, days, verdict and options ---


def test_every_window_of_the_analysis_uses_its_options() -> None:
    """The last 24 hours, the last 7 days, each day summarised now, today in the verdict and
    the change report all tell burns with the options: declared without hot water, every burn
    heats. A day kept with the current settings is not summarised again."""
    options = MonitorOptions(has_dhw=False)
    history = cycling(3, dhw=True)
    days = [(0.0, DAY), (DAY, 2 * DAY)]
    kept = [summarize_day(history, PARAMETERS, 0.0, DAY, options)]
    result = analyse(history, PARAMETERS, options, 3 * DAY, days, kept)
    assert result.at == 3 * DAY
    assert (result.day.start, result.day.heating.starts) == (2 * DAY, 48)
    assert (result.week.start, result.week.heating.starts) == (-4 * DAY, 144)
    assert [(day.start, day.starts) for day in result.new_days] == [(DAY, 48)]
    assert result.verdict.reasons == (
        Reason(ReasonCode.MONITORED_DAYS, ReasonKind.DATA, 3.0, 7.0),
        Reason(ReasonCode.HEATING_BURNS, ReasonKind.DATA, 144, 20),
    )
    assert result.report_unit is ReportUnit.BURNER_HOURS
    assert result.report is not None
    assert (result.report.previous_total, result.report.current_total) == (8.0, 8.0)
    assert result.report.amount(Cause.DHW) == 0.0
    assert result.report.unexplained == (Cause.SETTINGS,)
    assert result.trends == {}
    assert result.outdoor is None


def test_without_complete_days_today_is_the_last_24_hours() -> None:
    """With no complete day yet, today is the last 24 hours, and counts in the verdict."""
    result = analyse(cycling(1), PARAMETERS, MonitorOptions(), DAY)
    assert result.new_days == ()
    assert result.verdict.reasons[0] == Reason(ReasonCode.MONITORED_DAYS, ReasonKind.DATA, 1.0, 7.0)


def test_the_verdict_takes_its_options_and_window() -> None:
    """The verdict's own options and window: of three days the last one and today, two days of
    the three needed. Negative: the days before the window do not make up the difference."""
    options = MonitorOptions(verdict=VerdictOptions(min_days=3.0), verdict_window_days=1)
    days = [(d * DAY, (d + 1) * DAY) for d in range(3)]
    result = analyse(cycling(4), PARAMETERS, options, 4 * DAY, days)
    assert result.verdict.reasons == (
        Reason(ReasonCode.MONITORED_DAYS, ReasonKind.DATA, 2.0, 3.0),
        Reason(ReasonCode.HEATING_BURNS, ReasonKind.DATA, 96, 20),
    )


def test_the_verdict_names_a_load_model_from_defaults_only() -> None:
    """S-17: with the minimum power known and the threshold only the default, the load is not
    judged — and the verdict says the model is an estimate only."""
    parameters = PARAMETERS.with_estimate(
        ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED)
    )
    options = MonitorOptions(verdict=VerdictOptions(min_days=1.0))
    result = analyse(cycling(2), parameters, options, 2 * DAY, [(0.0, DAY)])
    missing = Reason(ReasonCode.LOAD_UNKNOWN, ReasonKind.MISSING, detail=ESTIMATE_ONLY)
    assert missing in result.verdict.reasons


def test_a_burn_still_running_is_judged_on_what_was_seen() -> None:
    """Negative (P-83): a burn running at the analysis, 15 of its 23 minutes so far on hot
    water, is a hot-water burn — in yesterday's summary and in today's — not a heating burn by
    its last state carried twelve hours ahead. No heating, so the starts are not judged."""
    history = History(
        signals={
            Signal.FLAME: Series([(0, False), (DAY - 20 * MIN, True)]),
            Signal.DHW_ACTIVE: Series([(0, False), (DAY - 20 * MIN, True), (DAY - 5 * MIN, False)]),
        },
        weather=Series([(0, 8.0)]),
    )
    options = MonitorOptions(verdict=VerdictOptions(min_days=0.5, min_heating_burns=0))
    result = analyse(history, PARAMETERS, options, DAY + 3 * MIN, [(0.0, DAY)])
    assert result.new_days == ()  # the day waits for the burn's end
    codes = {reason.code for reason in result.verdict.reasons}
    assert not codes & {ReasonCode.FEW_STARTS, ReasonCode.FREQUENT_STARTS}
    assert result.verdict.reasons[0] == Reason(ReasonCode.CRITERIA_JUDGED, ReasonKind.DATA, 0, 3)


# --- The building fit ---


def fit_days(count: int = 10) -> list[DaySummary]:
    """Kept days from −5 °C up, 1 K apart, each with the heat of 0.2 kW/K below 15 °C."""
    return [
        replace(
            DaySummary.empty(d * DAY, (d + 1) * DAY),
            observed_s=DAY,
            outdoor_mean=-5.0 + d,
            heat_kwh=24 * 0.2 * (15.0 - (-5.0 + d)),
        )
        for d in range(count)
    ]


def test_the_building_fit_uses_every_kept_day_and_dates_its_values() -> None:
    """P-32: the kept days are fitted with the threshold in use; the values found are dated
    now."""
    days = fit_days()
    result = analyse(History(), PARAMETERS, MonitorOptions(), NOW + 3 * DAY, kept=days)
    threshold = PARAMETERS.get(ParameterKey.HEATING_THRESHOLD).effective()
    assert threshold is not None
    assert result.fit is not None
    assert result.fit == fit_building(days, threshold, NOW + 3 * DAY)
    assert result.fit.loss is not None
    assert result.fit.loss.at == NOW + 3 * DAY


def test_the_building_fit_forgets_the_days_before_a_reset() -> None:
    """Negative (P-90): both values reset after every kept day: nothing to fit them from."""
    since = {ParameterKey.LOSS_COEFFICIENT: 20 * DAY, ParameterKey.HEATING_THRESHOLD: 20 * DAY}
    result = analyse(
        History(), PARAMETERS, MonitorOptions(), 21 * DAY, kept=fit_days(), fit_since=since
    )
    assert result.fit is None


# --- The change report's periods ---


def period_history(modulation: Series[float] | None = None) -> History:
    """A day with a heating burn of an hour, a hot-water burn of half an hour and a burn of a
    quarter of an hour of unknown kind; two zones with known targets — 20 °C, and 21 °C then
    23 °C — and one without; the weather at 20 °C."""
    signals: dict[Signal, Series[Any]] = {
        Signal.FLAME: flame_of(
            [(1 * HOUR, 2 * HOUR), (3 * HOUR, 3.5 * HOUR), (5 * HOUR, 5.25 * HOUR)]
        ),
        Signal.DHW_ACTIVE: Series(
            [(0, False), (3 * HOUR, True), (3.5 * HOUR, False), (5 * HOUR, None), (6 * HOUR, False)]
        ),
    }
    if modulation is not None:
        signals[Signal.MODULATION] = modulation
    zones = {
        "zone_a": ZoneSeries("zone_a", target=Series([(0, 20.0)])),
        "zone_b": ZoneSeries("zone_b", target=Series([(0, 21.0), (12 * HOUR, 23.0)])),
        "zone_c": ZoneSeries("zone_c"),
    }
    return History(signals=signals, zones=zones, weather=Series([(0, 20.0)]))


# 5 °C for half the day, then the threshold itself: 5 degree-days, half a heating day.
PERIOD_OUTDOOR = Series([(0, 5.0), (12 * HOUR, THRESHOLD)])


@pytest.mark.parametrize(
    ("options", "heating", "dhw"),
    [(MonitorOptions(), 1.25, 0.5), (MonitorOptions(has_dhw=False), 1.75, 0.0)],
    ids=["hot_water", "no_hot_water"],
)
def test_a_period_in_burner_hours(options: MonitorOptions, heating: float, dhw: float) -> None:
    """PB-66: without modulation, burner hours — the unknown kind counted as heating, hot water
    apart (none where the boiler heats none). Degree-days and heating days from the outdoor
    series given, below the threshold only; the mean of the known zone targets."""
    found = _period(period_history(), PARAMETERS, options, 0.0, DAY, THRESHOLD, PERIOD_OUTDOOR)
    assert found == (PeriodSummary(heating, dhw, 5.0, 0.5, 21.0), ReportUnit.BURNER_HOURS)


@pytest.mark.parametrize(
    ("modulation", "expected"),
    [
        (Series([(0, 50.0)]), (17.5, 7.0, ReportUnit.KWH)),
        (Series([(0, 50.0), (HOUR, None), (2 * HOUR, 50.0)]), (1.25, 0.5, ReportUnit.BURNER_HOURS)),
    ],
    ids=["complete", "incomplete"],
)
def test_a_period_in_kwh_only_with_every_burns_heat_known(
    modulation: Series[float], expected: tuple[float, float, ReportUnit]
) -> None:
    """With the modulation known through every burn, kWh at 14 kW (50 % of 4 to 24 kW).
    Negative: the heating burn's modulation unknown — burner hours, not part of the kWh."""
    found = _period(
        period_history(modulation), POWER, MonitorOptions(), 0.0, DAY, THRESHOLD, PERIOD_OUTDOOR
    )
    assert found is not None
    summary, unit = found
    assert (summary.heating, summary.dhw, unit) == expected


@pytest.mark.parametrize(
    ("flame", "outdoor"),
    [
        (Series([(0, None), (12 * HOUR, False)]), PERIOD_OUTDOOR),
        (Series([(0, False)]), Series[float]()),
    ],
    ids=["flame_half_known", "outdoor_unknown"],
)
def test_a_period_without_enough_data_is_no_period(
    flame: Series[bool], outdoor: Series[float]
) -> None:
    """Negative: the flame known for half the period, or no outdoor temperature at all: no
    period to compare."""
    history = History(signals={Signal.FLAME: flame})
    assert _period(history, PARAMETERS, MonitorOptions(), 0.0, DAY, THRESHOLD, outdoor) is None


def test_a_period_with_the_flame_known_for_nine_tenths_is_a_period() -> None:
    """The boundary: the flame known for exactly nine tenths of the period is enough."""
    history = History(signals={Signal.FLAME: Series([(0, None), (8640.0, False)])})
    found = _period(history, PARAMETERS, MonitorOptions(), 0.0, DAY, THRESHOLD, PERIOD_OUTDOOR)
    assert found == (PeriodSummary(0.0, 0.0, 5.0, 0.5, None), ReportUnit.BURNER_HOURS)


@pytest.mark.parametrize("known", [True, False], ids=["same_unit", "units_differ"])
def test_the_report_compares_two_days_in_one_unit(known: bool) -> None:
    """A heating hour each day at 14 kW: 14 kWh against 14 kWh. Negative: the modulation unknown
    the second day — kWh against burner hours cannot be compared, no report."""
    modulation = Series([(0, 50.0)]) if known else Series([(0, 50.0), (DAY, None)])
    history = History(
        signals={
            Signal.FLAME: flame_of([(HOUR, 2 * HOUR), (DAY + HOUR, DAY + 2 * HOUR)]),
            Signal.DHW_ACTIVE: Series([(0, False)]),
            Signal.MODULATION: modulation,
        },
        weather=Series([(0, 5.0)]),
    )
    report, unit = _report(history, POWER, MonitorOptions(), 2 * DAY, THRESHOLD, history.outdoor())
    if not known:
        assert (report, unit) == (None, None)
        return
    assert unit is ReportUnit.KWH
    assert report is not None
    assert (report.previous_total, report.current_total) == (14.0, 14.0)


# --- The outdoor check ---


@pytest.mark.parametrize(
    "history",
    [
        History(weather=Series([(0, 5.0)])),
        History(signals={Signal.OUTDOOR: Series([(0, 5.0)])}),
    ],
    ids=["no_sensor", "no_weather"],
)
def test_the_outdoor_sensor_is_checked_only_against_the_weather(history: History) -> None:
    """Negative: without the boiler's outdoor sensor, or without the weather to compare it
    with, there is no outdoor check."""
    assert _outdoor(history, DAY) is None
