"""The monitor: from recorded history to burns, metrics, daily points and the verdict."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from itertools import pairwise
from typing import Any

from .building import DayPoint, LoadModel
from .cycles import Burn, BurnKind, ClassifiedBurn, DhwInputs, classify_burns, find_burns
from .history import History
from .metrics import (
    CH_KINDS,
    DEFAULT_CONDENSING_RETURN,
    DEFAULT_SHORT_BURN_S,
    DHW_KINDS,
    METER_RESET_FRACTION,
    NOT_DHW_KINDS,
    UNKNOWN_KINDS,
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
    has_dhw: bool = True  # False: the boiler heats no hot water, so every burn heats
    verdict: VerdictOptions = field(default_factory=VerdictOptions)
    verdict_window_days: int | None = None  # the latest days with data; None: every day kept


class GasSource(StrEnum):
    METER = "meter"
    MODULATION = "modulation"


@dataclass(frozen=True, slots=True)
class MonitorSummary:
    start: float
    end: float
    burns: tuple[ClassifiedBurn, ...]
    observed_s: float  # time with the flame state known
    heating: CycleStats  # burns known to heat
    dhw: CycleStats
    unknown: CycleStats  # burns of unknown kind, counted apart
    condensing: Share | None  # None when the return is not mapped
    degree_days: DegreeDays | None  # None without any outdoor temperature
    gas: Consumption | None
    gas_source: GasSource | None
    gas_per_degree_day: float | None
    heat_output_kwh: Consumption | None  # heating only, estimated from modulation
    dhw_output_kwh: Consumption | None  # DHW only, estimated from modulation
    by_outdoor: dict[float, CycleStats]
    load_below_min: Share | None


def dhw_inputs(
    history: History, parameters: ParameterSet, start: float, end: float, options: MonitorOptions
) -> DhwInputs:
    """What the history offers to tell DHW burns from heating burns."""

    def mapped(signal: Signal) -> Series[Any] | None:
        return history.signals.get(signal)

    return DhwInputs(
        dhw_active=mapped(Signal.DHW_ACTIVE),
        ch_active=mapped(Signal.CH_ACTIVE),
        flow=mapped(Signal.FLOW),
        ch_setpoint=mapped(Signal.CH_SETPOINT),
        max_ch_setpoint=parameters.value(ParameterKey.MAX_CH_SETPOINT),
        zone_demand=history.zone_demand(start, end),
        setpoint_margin=options.setpoint_margin,
        has_dhw=options.has_dhw,
    )


def _heat_output(
    history: History,
    parameters: ParameterSet,
    burns: Sequence[ClassifiedBurn],
    scale: ModulationScale,
    kinds: frozenset[BurnKind] = NOT_DHW_KINDS,
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
        if classified.kind not in kinds:
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
    burns: Sequence[ClassifiedBurn],
) -> tuple[Consumption | None, GasSource | None]:
    """Heating gas: the gas of the burns known as hot water is left out."""
    hot_water = [b.burn for b in burns if b.kind in DHW_KINDS]
    if history.is_mapped(Signal.GAS_METER):
        meter = history.signal(Signal.GAS_METER)
        total = meter_consumption(meter, start, end)
        if total is None:
            return None, GasSource.METER
        dhw = _metered_hot_water(meter, burns, start, end)
        return Consumption(max(0.0, total.amount - dhw), total.complete), GasSource.METER
    low = parameters.value(ParameterKey.GAS_AT_MIN_POWER)
    high = parameters.value(ParameterKey.GAS_AT_MAX_POWER)
    if low is None or high is None or not history.is_mapped(Signal.MODULATION):
        return None, None
    flame, modulation = history.signal(Signal.FLAME), history.signal(Signal.MODULATION)
    gas = integrate_rate(flame, modulation, low, high, scale, start, end)
    for burn in hot_water:
        part = integrate_rate(flame, modulation, low, high, scale, burn.start, burn.end)
        gas = Consumption(gas.amount - part.amount, gas.complete and part.complete)
    return Consumption(max(0.0, gas.amount), gas.complete), GasSource.MODULATION


def _metered_hot_water(
    meter: Series[float], burns: Sequence[ClassifiedBurn], start: float, end: float
) -> float:
    """The hot water's part of a meter's gas. A meter shows a burn's gas when it next reports —
    during the burn, or minutes or an hour later — so each rise is split by the burner time
    between its two readings: the hot water's share of that time is left out. Exact for a
    meter that reports within each burn, fair for one that reports every hour."""
    readings = [(s.start, s.value) for s in meter.segments(start, end) if s.value is not None]
    dhw = 0.0
    for (since, before), (at, after) in pairwise(readings):
        if after >= before:
            rise = after - before
        elif after < METER_RESET_FRACTION * before:
            rise = after  # counted from zero since a reset
        else:
            continue
        burning = [(b, _overlap(b.burn, since, at)) for b in burns]
        total = sum(seconds for _b, seconds in burning)
        if rise <= 0 or total <= 0:
            continue
        dhw += rise * sum(s for b, s in burning if b.kind in DHW_KINDS) / total
    return dhw


def _overlap(burn: Burn, start: float, end: float) -> float:
    return max(0.0, min(burn.end, end) - max(burn.start, start))


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
    gas, source = _gas(history, parameters, start, end, opts.modulation_scale, burns)
    # Gas known for part of the window over degree-days for all of it would be too little.
    gas_per_dd = (
        per_degree_day(gas.amount, days)
        if gas is not None and gas.complete and days is not None
        else None
    )
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
        heating=cycle_stats(burns, observed, CH_KINDS, opts.short_burn_s, (start, end)),
        dhw=cycle_stats(burns, observed, DHW_KINDS, opts.short_burn_s, (start, end)),
        unknown=cycle_stats(burns, observed, UNKNOWN_KINDS, opts.short_burn_s, (start, end)),
        condensing=condensing,
        degree_days=days,
        gas=gas,
        gas_source=source,
        gas_per_degree_day=gas_per_dd,
        heat_output_kwh=_heat_output(history, parameters, burns, opts.modulation_scale),
        dhw_output_kwh=_heat_output(history, parameters, burns, opts.modulation_scale, DHW_KINDS),
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
