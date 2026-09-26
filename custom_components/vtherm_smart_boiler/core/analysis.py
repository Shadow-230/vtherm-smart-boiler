"""The periodic analysis: summaries, verdict, trend warnings, report, outdoor check, building fit.

It runs every few minutes on a copy of the rolling history, off the event loop. Local day
boundaries come from the caller: the core knows no time zones.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .alarms import (
    DEFAULT_FLUE_RISE_K,
    DEFAULT_HYSTERESIS_DRIFT_K,
    DEFAULT_PRESSURE_DROP_BAR,
    Alarm,
    AlarmKind,
    cold_pressure_samples,
    compare_windows,
    flue_excess_samples,
    hysteresis_samples,
    trend_warning,
)
from .building import LoadFit, fit_daily_load
from .cycles import ClassifiedBurn
from .daily import DaySummary, fit_points, summarize_day, verdict_over_days
from .history import History
from .monitor import MonitorOptions, MonitorSummary, summarize
from .parameters import ParameterKey, ParameterSet
from .report import ChangeReport, PeriodSummary, explain_change
from .series import duration_where, time_weighted_mean
from .signal_check import OutdoorCheck, check_outdoor
from .signals import Signal
from .verdict import VerdictResult

DAY = 86400.0
HISTORY_DAYS = 8.0


class ReportUnit(StrEnum):
    KWH = "kWh"
    BURNER_HOURS = "h"


@dataclass(frozen=True, slots=True)
class Analysis:
    at: float
    day: MonitorSummary
    week: MonitorSummary
    verdict: VerdictResult
    trends: dict[AlarmKind, Alarm]
    report: ChangeReport | None
    report_unit: ReportUnit | None
    outdoor: OutdoorCheck | None
    fit: LoadFit | None
    new_days: tuple[DaySummary, ...] = ()  # complete days summarised now, to keep


def analyse(
    history: History,
    parameters: ParameterSet,
    options: MonitorOptions,
    now: float,
    days: Sequence[tuple[float, float]] = (),
    kept: Sequence[DaySummary] = (),
    settings: str = "",
) -> Analysis:
    """``days``: the complete local days of the history; ``kept``: the day summaries kept from
    earlier. The verdict covers the kept days, the history's days not kept yet and today. Only
    days summarised with ``settings`` count (the key of the current settings); the history's
    days summarised with others are summarised again."""
    full = summarize(history, parameters, now - HISTORY_DAYS * DAY, now, options)
    kept = [day for day in kept if day.settings == settings]
    known = {day.start for day in kept}
    new_days = tuple(
        summarize_day(history, parameters, start, end, options, settings)
        for start, end in days
        if start not in known
    )
    today_start = max((end for _start, end in days), default=now - DAY)
    today = summarize_day(history, parameters, today_start, now, options, settings)
    week = summarize(history, parameters, now - 7 * DAY, now, options)
    day = summarize(history, parameters, now - DAY, now, options)
    threshold = parameters.value(ParameterKey.HEATING_THRESHOLD)
    fit = None
    points = fit_points([*kept, *new_days])  # every day kept, not only the rolling few
    if threshold is not None and points:
        fit = fit_daily_load(points, threshold, now)
    report, unit = _report(history, parameters, options, now, threshold)
    return Analysis(
        at=now,
        day=day,
        week=week,
        verdict=verdict_over_days(
            [*kept, *new_days], options.verdict, options.verdict_window_days, today
        ),
        trends=_trends(history, full, now, options.verdict.condensing_boiler),
        report=report,
        report_unit=unit,
        outdoor=_outdoor(history, now),
        fit=fit,
        new_days=tuple(day for day in new_days if day.has_data),
    )


def _trends(
    history: History, full: MonitorSummary, now: float, condensing: bool = True
) -> dict[AlarmKind, Alarm]:
    """Slow drifts: falling pressure, a flue gas rising over the return, the burner's
    hysteresis. A non-condensing boiler's flue temperature follows the return, and so the
    weather: its trend, like its absolute flue gas alarm, is left out."""
    baseline = (now - HISTORY_DAYS * DAY, now - 4 * DAY)
    recent = (now - DAY, now)
    trends: dict[AlarmKind, Alarm] = {}
    if all(history.is_mapped(s) for s in (Signal.PRESSURE, Signal.FLAME, Signal.FLOW)):
        pressure, flame, flow = (
            history.signal(Signal.PRESSURE),
            history.signal(Signal.FLAME),
            history.signal(Signal.FLOW),
        )
        trend = compare_windows(
            cold_pressure_samples(pressure, flame, flow, *baseline),
            cold_pressure_samples(pressure, flame, flow, *recent),
        )
        trends[AlarmKind.PRESSURE_FALLING] = trend_warning(
            AlarmKind.PRESSURE_FALLING, trend, DEFAULT_PRESSURE_DROP_BAR, direction=-1
        )

    def burns_in(window: tuple[float, float]) -> list[ClassifiedBurn]:
        return [b for b in full.burns if window[0] <= b.burn.start < window[1]]

    if condensing and history.is_mapped(Signal.FLUE_GAS) and history.is_mapped(Signal.RETURN):
        flue, back = history.signal(Signal.FLUE_GAS), history.signal(Signal.RETURN)
        trend = compare_windows(
            flue_excess_samples(flue, back, burns_in(baseline)),
            flue_excess_samples(flue, back, burns_in(recent)),
        )
        trends[AlarmKind.FLUE_GAS_RISING] = trend_warning(
            AlarmKind.FLUE_GAS_RISING, trend, DEFAULT_FLUE_RISE_K, direction=1
        )
    if history.is_mapped(Signal.FLOW):
        flow = history.signal(Signal.FLOW)
        setpoint = history.signals.get(Signal.CH_SETPOINT)
        trend = compare_windows(
            hysteresis_samples(flow, burns_in(baseline), setpoint),
            hysteresis_samples(flow, burns_in(recent), setpoint),
            min_samples=10,
        )
        trends[AlarmKind.HYSTERESIS_DRIFT] = trend_warning(
            AlarmKind.HYSTERESIS_DRIFT, trend, DEFAULT_HYSTERESIS_DRIFT_K, direction=0
        )
    return trends


def _period(
    history: History,
    parameters: ParameterSet,
    options: MonitorOptions,
    start: float,
    end: float,
    threshold: float,
) -> tuple[PeriodSummary, ReportUnit] | None:
    summary = summarize(history, parameters, start, end, options)
    if summary.observed_s < 0.9 * (end - start) or summary.degree_days is None:
        return None
    degree_days = summary.degree_days.estimated_total()
    if degree_days is None:
        return None
    heat, dhw_heat = summary.heat_output_kwh, summary.dhw_output_kwh
    if heat is not None and dhw_heat is not None and heat.complete and dhw_heat.complete:
        heating, dhw, unit = heat.amount, dhw_heat.amount, ReportUnit.KWH
    else:
        heating = summary.heating.burn_s / 3600.0
        dhw = summary.dhw.burn_s / 3600.0
        unit = ReportUnit.BURNER_HOURS
    heating_days = duration_where(history.outdoor(), start, end, lambda v: v < threshold) / DAY
    targets = [time_weighted_mean(z.target, start, end).value for z in history.zones.values()]
    known = [t for t in targets if t is not None]
    mean_target = sum(known) / len(known) if known else None
    return PeriodSummary(heating, dhw, degree_days, heating_days, mean_target), unit


def _report(
    history: History,
    parameters: ParameterSet,
    options: MonitorOptions,
    now: float,
    threshold: float | None,
) -> tuple[ChangeReport | None, ReportUnit | None]:
    if threshold is None:
        return None, None
    previous = _period(history, parameters, options, now - 2 * DAY, now - DAY, threshold)
    current = _period(history, parameters, options, now - DAY, now, threshold)
    if previous is None or current is None or previous[1] is not current[1]:
        return None, None
    return explain_change(previous[0], current[0]), current[1]


def _outdoor(history: History, now: float) -> OutdoorCheck | None:
    if not history.is_mapped(Signal.OUTDOOR) or not len(history.weather):
        return None
    return check_outdoor(history.signal(Signal.OUTDOOR), history.weather, now - DAY, now)
