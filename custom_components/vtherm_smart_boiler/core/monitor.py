"""The monitor: from recorded history to burns, metrics and the verdict."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .cycles import Burn, BurnKind, ClassifiedBurn, DhwInputs, classify_burns, find_burns
from .history import History
from .metrics import (
    CH_KINDS,
    DEFAULT_CONDENSING_RETURN,
    DEFAULT_SHORT_BURN_S,
    DHW_KINDS,
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
    meter_rise,
    per_degree_day,
)
from .parameters import ParameterKey, ParameterSet
from .series import Series, known_duration
from .signals import Signal
from .verdict import LoadBasis, VerdictOptions, VerdictResult, assess, load_below_min_share


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


GAS_COVERAGE = 0.99  # the flame known this much of the window: the gas from modulation counts


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
    # Burns not known to be hot water — heating and unknown-kind burns (PB-66) — estimated
    # from modulation.
    heat_output_kwh: Consumption | None
    dhw_output_kwh: Consumption | None  # DHW only, estimated from modulation
    by_outdoor: dict[float, CycleStats]
    load_below_min: Share | None
    # S-31: gas the meter counted while the burner was known off throughout — another consumer
    # (a cooker) — left out of ``gas`` and shown apart; ``None`` without a meter reading.
    other_gas: float | None = None
    # S-17: ``load_below_min`` is missing only because the building model is an estimate.
    load_estimate_only: bool = False
    # S-43: a flame signal is mapped at all.
    burner_signal: bool = True


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
    window: tuple[float, float],
    kinds: frozenset[BurnKind] = NOT_DHW_KINDS,
) -> Consumption | None:
    """Heat output of the burns of ``kinds`` within ``window`` (a burn across its edge counts
    only its part inside, P-83), estimated from modulation."""
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
        part = integrate_rate(flame, modulation, low, high, scale, *_inside(classified, window))
        total += part.amount
        complete = complete and part.complete
    return Consumption(total, complete)


def _inside(classified: ClassifiedBurn, window: tuple[float, float]) -> tuple[float, float]:
    """The part of a burn within ``window``."""
    burn = classified.burn
    return max(burn.start, window[0]), min(burn.end, window[1])


def _gas(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    scale: ModulationScale,
    burns: Sequence[ClassifiedBurn],
) -> tuple[Consumption | None, GasSource | None, float | None]:
    """Heating gas, its source and, from a meter, the gas other consumers used while the burner
    was off (S-31, shown apart). The gas of the burns known as hot water is left out."""
    if history.is_mapped(Signal.GAS_METER):
        meter = history.signal(Signal.GAS_METER)
        total = meter_consumption(meter, start, end)
        if total is None:
            return None, GasSource.METER, None
        dhw, other = _metered_split(meter, history.signal(Signal.FLAME), burns, start, end)
        heating = max(0.0, total.amount - dhw - other)
        return Consumption(heating, total.complete), GasSource.METER, other
    low = parameters.value(ParameterKey.GAS_AT_MIN_POWER)
    high = parameters.value(ParameterKey.GAS_AT_MAX_POWER)
    if low is None or high is None or not history.is_mapped(Signal.MODULATION):
        return None, None, None
    # Burn by burn, hot water left out; complete while the flame is known nearly all the time
    # (a restart's seconds without it must not void a week) and the modulation in every burn.
    flame, modulation = history.signal(Signal.FLAME), history.signal(Signal.MODULATION)
    amount = 0.0
    complete = known_duration(flame, start, end) >= GAS_COVERAGE * (end - start)
    for classified in burns:
        if classified.kind in DHW_KINDS:
            continue
        part = integrate_rate(
            flame, modulation, low, high, scale, *_inside(classified, (start, end))
        )
        amount += part.amount
        complete = complete and part.complete
    return Consumption(amount, complete), GasSource.MODULATION, None


def _metered_split(
    meter: Series[float],
    flame: Series[bool],
    burns: Sequence[ClassifiedBurn],
    start: float,
    end: float,
) -> tuple[float, float]:
    """The hot water's part and other consumers' part of a meter's gas in ``[start, end)``.

    A meter shows a burn's gas when it next reports — during the burn, or minutes or an hour
    later — so each rise (``meter_rise``: above the highest reading only, P-97) is split by the
    burner time between its two readings: the hot water's share of that time is left out. Exact
    for a meter that reports within each burn, fair for one that reports every hour. A rise
    between two readings with the flame known off throughout is another consumer's — a cooker,
    another appliance — shown apart (S-31); one with neither burner time nor the flame known
    throughout counts as heating, as before. Readings and time-sorted burns are walked once,
    side by side (P-84)."""
    readings = [(s.start, s.value) for s in meter.segments(start, end) if s.value is not None]
    ordered = sorted(burns, key=lambda classified: classified.burn.start)
    dhw = other = 0.0
    high: float | None = None
    first = 0  # the first burn that may reach into the current interval
    since: float | None = None
    for at, value in readings:
        rise, high = meter_rise(high, value)
        if since is None:
            since = at
            continue
        # Burns are disjoint and in time order: one ended by ``since`` touches no later interval.
        while first < len(ordered) and ordered[first].burn.end <= since:
            first += 1
        burning = hot = 0.0
        index = first
        while index < len(ordered) and ordered[index].burn.start < at:
            seconds = _overlap(ordered[index].burn, since, at)
            burning += seconds
            if ordered[index].kind in DHW_KINDS:
                hot += seconds
            index += 1
        if rise > 0 and burning > 0:
            dhw += rise * hot / burning
        elif rise > 0 and all(part.value is False for part in flame.segments(since, at)):
            other += rise  # the flame known off throughout: not the boiler's gas
        since = at
    return dhw, other


def _overlap(burn: Burn, start: float, end: float) -> float:
    return max(0.0, min(burn.end, end) - max(burn.start, start))


def summarize(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    options: MonitorOptions | None = None,
    *,
    search: tuple[float, float] | None = None,
    outdoor: Series[float] | None = None,
) -> MonitorSummary:
    """Everything the monitor reports for ``[start, end)``.

    ``search``: a wider window the burns are found in, so a burn across an edge of the window is
    whole — it counts (its start, its length) in the window that holds its start, and its time
    only within each (P-83); by default the window itself. ``outdoor``: the outdoor temperature
    to use, by default the history's (P-86: a day summary may leave a stuck sensor out)."""
    opts = options or MonitorOptions()
    flame = history.signal(Signal.FLAME)
    low, high = search if search is not None else (start, end)
    low, high = min(low, start), max(high, end)
    found = classify_burns(
        find_burns(flame, low, high), dhw_inputs(history, parameters, low, high, opts)
    )
    burns = tuple(b for b in found if b.burn.end > start and b.burn.start < end)
    window = (start, end)
    observed = known_duration(flame, start, end)
    outdoor = history.outdoor() if outdoor is None else outdoor
    threshold = parameters.value(ParameterKey.HEATING_THRESHOLD)
    days = (
        degree_days(outdoor, threshold, start, end)
        if threshold is not None and len(outdoor)
        else None
    )
    condensing = (
        condensing_share(
            history.signal(Signal.RETURN), burns, opts.condensing_return, window=window
        )
        if history.is_mapped(Signal.RETURN)
        else None
    )
    gas, source, other_gas = _gas(history, parameters, start, end, opts.modulation_scale, burns)
    # Gas known for part of the window over degree-days for all of it would be too little.
    gas_per_dd = (
        per_degree_day(gas.amount, days)
        if gas is not None and gas.complete and days is not None
        else None
    )
    # S-17: the load is judged only with a trusted building model — entered, or measured with
    # confidence; a model from rule-of-thumb defaults decides nothing.
    load = LoadBasis.from_parameters(parameters)
    load_below = (
        load_below_min_share(outdoor, load.model, load.min_power_kw, start, end)
        if load.model is not None and load.min_power_kw is not None and len(outdoor)
        else None
    )
    return MonitorSummary(
        start=start,
        end=end,
        burns=burns,
        observed_s=observed,
        heating=cycle_stats(burns, observed, CH_KINDS, opts.short_burn_s, window),
        dhw=cycle_stats(burns, observed, DHW_KINDS, opts.short_burn_s, window),
        unknown=cycle_stats(burns, observed, UNKNOWN_KINDS, opts.short_burn_s, window),
        condensing=condensing,
        degree_days=days,
        gas=gas,
        gas_source=source,
        gas_per_degree_day=gas_per_dd,
        heat_output_kwh=_heat_output(history, parameters, burns, opts.modulation_scale, window),
        dhw_output_kwh=_heat_output(
            history, parameters, burns, opts.modulation_scale, window, DHW_KINDS
        ),
        by_outdoor=(
            binned_cycle_stats(
                burns, flame, outdoor, start, end, opts.bin_width, CH_KINDS, opts.short_burn_s
            )
            if len(outdoor)
            else {}
        ),
        load_below_min=load_below,
        other_gas=other_gas,
        load_estimate_only=load.estimate_only and len(outdoor) > 0,
        burner_signal=history.is_mapped(Signal.FLAME),
    )


def verdict(summary: MonitorSummary, options: MonitorOptions | None = None) -> VerdictResult:
    opts = options or MonitorOptions()
    return assess(
        summary.observed_s,
        summary.heating,
        summary.condensing,
        summary.load_below_min,
        opts.verdict,
        load_estimate_only=summary.load_estimate_only,
        burner_signal=summary.burner_signal,
    )
