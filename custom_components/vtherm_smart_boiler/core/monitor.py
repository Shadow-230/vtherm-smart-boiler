"""The monitor: from recorded history to burns, metrics, daily points and the verdict."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from .building import DayPoint, LoadModel
from .cycles import ClassifiedBurn, DhwInputs, classify_burns, find_burns
from .history import History
from .metrics import (
    CH_KINDS,
    DEFAULT_CONDENSING_RETURN,
    DEFAULT_SHORT_BURN_S,
    DHW_KINDS,
    Consumption,
    CycleStats,
    DegreeDays,
    ModulationScale,
    Share,
    binned_cycle_stats,
    condensing_share,
    cycle_stats,
    degree_days,
    integrate_rate,
    meter_consumption,
    per_degree_day,
)
from .parameters import ParameterKey, ParameterSet
from .series import Series, known_duration, time_weighted_mean
from .signals import Signal
from .verdict import VerdictOptions, VerdictResult, assess, load_below_min_share


@dataclass(frozen=True, slots=True)
class MonitorOptions:
    condensing_return: float = DEFAULT_CONDENSING_RETURN
    short_burn_s: float = DEFAULT_SHORT_BURN_S
    modulation_scale: ModulationScale = ModulationScale.RANGE
    bin_width: float = 5.0
    setpoint_margin: float = 5.0
    verdict: VerdictOptions = field(default_factory=VerdictOptions)


class GasSource(StrEnum):
    METER = "meter"
    MODULATION = "modulation"


@dataclass(frozen=True, slots=True)
class MonitorSummary:
    start: float
    end: float
    burns: tuple[ClassifiedBurn, ...]
    observed_s: float  # time with the flame state known
    heating: CycleStats
    dhw: CycleStats
    condensing: Share | None  # None when the return is not mapped
    degree_days: DegreeDays | None  # None without any outdoor temperature
    gas: Consumption | None
    gas_source: GasSource | None
    gas_per_degree_day: float | None
    heat_output_kwh: Consumption | None  # heating only, estimated from modulation
    by_outdoor: dict[float, CycleStats]
    load_below_min: Share | None


def dhw_inputs(
    history: History, parameters: ParameterSet, start: float, end: float, options: MonitorOptions
) -> DhwInputs:
    """What the history offers to tell DHW burns from heating burns."""

    def mapped(signal: Signal) -> Series | None:
        return history.signals.get(signal)

    return DhwInputs(
        dhw_active=mapped(Signal.DHW_ACTIVE),
        ch_active=mapped(Signal.CH_ACTIVE),
        flow=mapped(Signal.FLOW),
        ch_setpoint=mapped(Signal.CH_SETPOINT),
        max_ch_setpoint=parameters.value(ParameterKey.MAX_CH_SETPOINT),
        zone_demand=history.zone_demand(start, end),
        setpoint_margin=options.setpoint_margin,
    )


def _heat_output(
    history: History,
    parameters: ParameterSet,
    burns: Sequence[ClassifiedBurn],
    scale: ModulationScale,
) -> Consumption | None:
    low = parameters.value(ParameterKey.BOILER_MIN_POWER)
    high = parameters.value(ParameterKey.BOILER_MAX_POWER)
    if low is None or high is None or not history.is_mapped(Signal.MODULATION):
        return None
    flame = history.signal(Signal.FLAME)
    modulation = history.signal(Signal.MODULATION)
    total = 0.0
    complete = True
    for classified in burns:
        if classified.kind not in CH_KINDS:
            continue
        burn = classified.burn
        part = integrate_rate(flame, modulation, low, high, scale, burn.start, burn.end)
        total += part.amount
        complete = complete and part.complete
    return Consumption(total, complete)


def _gas(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    scale: ModulationScale,
) -> tuple[Consumption | None, GasSource | None]:
    if history.is_mapped(Signal.GAS_METER):
        return meter_consumption(history.signal(Signal.GAS_METER), start, end), GasSource.METER
    low = parameters.value(ParameterKey.GAS_AT_MIN_POWER)
    high = parameters.value(ParameterKey.GAS_AT_MAX_POWER)
    if low is None or high is None or not history.is_mapped(Signal.MODULATION):
        return None, None
    gas = integrate_rate(
        history.signal(Signal.FLAME),
        history.signal(Signal.MODULATION),
        low,
        high,
        scale,
        start,
        end,
    )
    return gas, GasSource.MODULATION


def summarize(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    options: MonitorOptions | None = None,
) -> MonitorSummary:
    """Everything the monitor reports for ``[start, end)``."""
    opts = options or MonitorOptions()
    flame = history.signal(Signal.FLAME)
    burns = tuple(
        classify_burns(
            find_burns(flame, start, end), dhw_inputs(history, parameters, start, end, opts)
        )
    )
    observed = known_duration(flame, start, end)
    outdoor = history.outdoor()
    threshold = parameters.value(ParameterKey.HEATING_THRESHOLD)
    days = (
        degree_days(outdoor, threshold, start, end)
        if threshold is not None and len(outdoor)
        else None
    )
    condensing = (
        condensing_share(history.signal(Signal.RETURN), burns, opts.condensing_return)
        if history.is_mapped(Signal.RETURN)
        else None
    )
    gas, source = _gas(history, parameters, start, end, opts.modulation_scale)
    gas_per_dd = per_degree_day(gas.amount, days) if gas is not None and days is not None else None
    model = LoadModel.from_parameters(parameters)
    min_power = parameters.value(ParameterKey.BOILER_MIN_POWER)
    load_below = (
        load_below_min_share(outdoor, model, min_power, start, end)
        if model is not None and min_power is not None and len(outdoor)
        else None
    )
    return MonitorSummary(
        start=start,
        end=end,
        burns=burns,
        observed_s=observed,
        heating=cycle_stats(burns, observed, CH_KINDS, opts.short_burn_s),
        dhw=cycle_stats(burns, observed, DHW_KINDS, opts.short_burn_s),
        condensing=condensing,
        degree_days=days,
        gas=gas,
        gas_source=source,
        gas_per_degree_day=gas_per_dd,
        heat_output_kwh=_heat_output(history, parameters, burns, opts.modulation_scale),
        by_outdoor=(
            binned_cycle_stats(
                burns, flame, outdoor, start, end, opts.bin_width, CH_KINDS, opts.short_burn_s
            )
            if len(outdoor)
            else {}
        ),
        load_below_min=load_below,
    )


def verdict(summary: MonitorSummary, options: MonitorOptions | None = None) -> VerdictResult:
    opts = options or MonitorOptions()
    return assess(
        summary.observed_s,
        summary.heating,
        summary.condensing,
        summary.load_below_min,
        opts.verdict,
    )


def daily_points(
    history: History,
    parameters: ParameterSet,
    days: Sequence[tuple[float, float]],
    options: MonitorOptions | None = None,
    min_coverage: float = 0.9,
) -> list[DayPoint]:
    """Mean outdoor temperature and heating output per day, for the building load fit.

    ``days`` are the day windows (local midnight to midnight, computed by the caller). A day
    counts when the outdoor temperature and the heat output are known for most of it.
    """
    opts = options or MonitorOptions()
    outdoor = history.outdoor()
    points: list[DayPoint] = []
    for start, end in days:
        mean = time_weighted_mean(outdoor, start, end)
        if mean.value is None or mean.known_s < min_coverage * (end - start):
            continue
        summary = summarize(history, parameters, start, end, opts)
        heat = summary.heat_output_kwh
        if heat is None or not heat.complete:
            continue
        if summary.observed_s < min_coverage * (end - start):
            continue
        points.append(DayPoint(mean.value, heat.amount))
    return points
