"""What the monitor shows about the water's lowest temperature and about the wall thermostat on a
gateway (X6): evidence and a suggestion, an estimate beside it, a fallback shown and warned —
nothing here changes a setting or writes anything.

The lowest water temperature (decision 2, S-02, S-56) is one setting the user enters, like a
point of the curve; 0.2.2 only suggests. The evidence, over the last ``WINDOW_DAYS`` of the
history: a heating burn counts when it is complete, the zones asked for heat throughout it and
at its end (a moment not known does not count — a burn with it is left out), no hot water ran
during it, its setpoint at its start lay within ``BAND_K`` of the reference, it ended on
temperature (the flow at its end at least its setpoint − ``ENDED_ON_TEMPERATURE_K``), and —
valves as an input — where a zone calling during it reports its opening, one such zone was at
least ``OPEN_ENOUGH`` open throughout it (zones that report no opening exclude nothing). The
reference: where the plugin sets the water, the lowest water temperature set; where the boiler's
own curve, a thermostat or another device sets it, the lowest setpoint the source showed at the
start of the burns that count otherwise. With at least the verdict's number of counted burns
(20) and more than the verdict's share (0.5) of them shorter than the monitor's short burn
(10 min), the suggestion is the reference + ``RAISE_K``, rounded up to 0.5 °C, never above the
lowest of the caps − ``UNDER_CAPS_K`` nor above ``SUGGESTION_CEILING``. Nothing heats while a
stand-alone gateway is handed back: no suggestion then.

Beside it, as information only, an "about" estimate from the boiler's minimum power (Q3.4): the
curve's flow where the emitters give off that power, ``room + (design flow − room) ·
(P_min / P_design)^(1/n)`` — only with the minimum power entered, a design load entered or
measured with confidence and an entered curve, never for a boiler that does not condense. The
boiler's reported bounds for its maximum CH setpoint (OpenTherm ID 49) are not its minimum flow
temperature and are never used as one (Q3.2).

The wall thermostat on a gateway (with an OpenTherm thermostat): the temperature it keeps after
a hand-back, from the optional "wired thermostat setpoint" signal, warned when that is not mapped,
unknown or below ``WALL_THERMOSTAT_LOW``; its repair issue follows once it has been low or
unknown for ``WALL_THERMOSTAT_ISSUE_S``.

Every number here is provisional, for the user at K4 (``SCOPE.md``'s fixed values, S-37).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from .curve import HeatingCurve
from .cycles import classify_burn, find_burns
from .history import History
from .metrics import CH_KINDS
from .monitor import MonitorOptions, dhw_inputs
from .parameters import ParameterKey, ParameterSet, Source
from .series import Series, duration_where, known_duration
from .signals import Signal

DAY = 86400.0
# Provisional, K4 (S-37) — the suggestion's evidence:
WINDOW_DAYS = 7  # the history the evidence is taken from
BAND_K = 1.0  # a burn's setpoint at its start this close to the reference
ENDED_ON_TEMPERATURE_K = 1.0  # the flow at a burn's end at least its setpoint minus this
OPEN_ENOUGH = 0.5  # a calling zone that reports its opening: at least this open throughout
RAISE_K = 2.0  # the suggestion: the reference plus this
UNDER_CAPS_K = 2.0  # ... never closer than this below the lowest cap
SUGGESTION_CEILING = 50.0  # ... nor above the setting's own upper end
STEP_K = 0.5  # values are shown on this grid
# The wall thermostat on a gateway (provisional, K4): below this the house cools after a
# hand-back; its repair issue once low or unknown this long.
WALL_THERMOSTAT_LOW = 15.0
WALL_THERMOSTAT_ISSUE_S = 30 * 60.0


class SuggestionState(StrEnum):
    SUGGESTION = "suggestion"  # the boiler keeps stopping at the reference: a value to consider
    GOOD_ENOUGH = "good_enough"  # enough burns counted, not mostly short
    NO_DATA = "no_data"  # too few burns counted
    INACTIVE = "inactive"  # a signal it needs is missing: named in ``missing``
    # Nothing heats (a stand-alone gateway handed back), or no raise fits under the caps.
    NOT_APPLICABLE = "not_applicable"


class SetpointSource(StrEnum):
    """Where the setpoint in force at a burn's start comes from."""

    CH_SETPOINT = "ch_setpoint"  # the boiler's CH setpoint signal, where mapped
    READ_BACK = "read_back"  # under control: the control's setpoint read-back


class WaterSetBy(StrEnum):
    PLUGIN = "plugin"  # the plugin's control sets the water: the setting's own suggestion
    DEVICE = "device"  # the boiler's own curve, a thermostat or another device sets it


class EstimateGap(StrEnum):
    """Why there is no estimate from the boiler's minimum power (the input named)."""

    MIN_POWER = "boiler_min_power"  # the boiler's minimum power not entered
    DESIGN_LOAD = "design_load"  # no design load entered or measured with confidence
    CURVE = "curve"  # no curve entered
    MIN_POWER_NOT_BELOW_LOAD = "min_power_not_below_load"  # the rule has no solution
    NOT_CONDENSING = "not_condensing"  # its manual's minimum governs, far higher


@dataclass(frozen=True, slots=True)
class PowerEstimate:
    """The "about" estimate from the boiler's minimum power, °C; ``None`` with its gap."""

    value: float | None = None
    gap: EstimateGap | None = None


@dataclass(frozen=True, slots=True)
class SuggestionContext:
    """What the evidence is judged against: who sets the water now; the lowest water
    temperature set (needed where the plugin sets it); the caps known — the highest water
    temperature, the circuit's and the boiler's maximum; whether nothing heats (a stand-alone
    gateway handed back); the estimate carried beside the suggestion."""

    set_by: WaterSetBy = WaterSetBy.DEVICE
    lowest: float | None = None
    caps: tuple[float, ...] = ()
    nothing_heats: bool = False
    estimate: PowerEstimate | None = None

    def __post_init__(self) -> None:
        if self.set_by is WaterSetBy.PLUGIN and self.lowest is None:
            raise ValueError("where the plugin sets the water, its lowest temperature is needed")


@dataclass(frozen=True, slots=True)
class LowestWaterSuggestion:
    """The suggestion and its evidence. ``value``: °C, only in the state ``suggestion``."""

    state: SuggestionState
    value: float | None = None
    counted: int = 0
    short: int = 0
    reference: float | None = None
    source: SetpointSource | None = None
    set_by: WaterSetBy = WaterSetBy.DEVICE
    missing: tuple[str, ...] = ()
    window_days: int = WINDOW_DAYS
    short_burn_s: float = 600.0
    estimate: PowerEstimate | None = None

    @property
    def short_share(self) -> float | None:
        """The share of the counted burns shorter than the short burn; ``None`` without any."""
        return None if self.counted == 0 else self.short / self.counted


def _round_up(value: float) -> float:
    return math.ceil(value / STEP_K - 1e-9) * STEP_K


def _round_down(value: float) -> float:
    return math.floor(value / STEP_K + 1e-9) * STEP_K


def _setpoints(history: History, source: SetpointSource | None) -> Series[float] | None:
    if source is SetpointSource.CH_SETPOINT:
        return history.signals.get(Signal.CH_SETPOINT)
    if source is SetpointSource.READ_BACK:
        return history.setpoint_read_back
    return None


def _asked_throughout(demand: Series[bool] | None, start: float, end: float) -> bool:
    """The zones asked for heat at every moment of the burn and at its end, each moment known:
    an unknown one leaves the burn out (the evidence's side of the missing-data rule)."""
    if demand is None or demand.value_at(end) is not True:
        return False
    return all(part.value is True for part in demand.segments(start, end) if part.duration > 0)


def _open_enough(history: History, start: float, end: float) -> bool:
    """Valves as an input: where a zone calling during the burn reports its opening, one such
    zone was at least ``OPEN_ENOUGH`` open at every known moment of it; zones that report no
    opening exclude nothing."""
    reporting = [
        zone
        for zone in history.zones.values()
        if duration_where(zone.calling_between(start, end), start, end, bool) > 0
        and known_duration(zone.valve_open, start, end) > 0
    ]
    if not reporting:
        return True
    return any(
        duration_where(zone.valve_open, start, end, lambda opening: opening < OPEN_ENOUGH) == 0
        for zone in reporting
    )


def suggest_lowest_water(
    history: History,
    source: SetpointSource | None,
    now: float,
    parameters: ParameterSet,
    options: MonitorOptions,
    context: SuggestionContext,
) -> LowestWaterSuggestion:
    """The evidence of the last ``WINDOW_DAYS`` and what it suggests (see the module's text).
    ``source``: where the setpoint comes from (``None``: nowhere — inactive, naming
    ``ch_setpoint``)."""
    setpoints = _setpoints(history, source)
    base = LowestWaterSuggestion(
        SuggestionState.NOT_APPLICABLE,
        source=source if setpoints is not None else None,
        set_by=context.set_by,
        short_burn_s=options.short_burn_s,
        estimate=context.estimate,
    )
    if context.nothing_heats:
        return base  # nothing heats: nothing to suggest, whatever is missing
    missing = tuple(
        name
        for name, present in (
            (Signal.FLAME.value, history.is_mapped(Signal.FLAME)),
            (Signal.FLOW.value, history.is_mapped(Signal.FLOW)),
            (Signal.CH_SETPOINT.value, setpoints is not None),
        )
        if not present
    )
    if missing or setpoints is None:
        return _with(base, state=SuggestionState.INACTIVE, missing=missing)
    start = now - WINDOW_DAYS * DAY
    flame, flow = history.signal(Signal.FLAME), history.signal(Signal.FLOW)
    demand = history.zone_calling(start, now)
    hot_water = history.signals.get(Signal.DHW_ACTIVE)
    inputs = dhw_inputs(history, parameters, start, now, options)
    candidates: list[tuple[float, float]] = []  # (duration, setpoint at the start)
    for burn in find_burns(flame, start, now):
        if not burn.complete or classify_burn(burn, inputs).kind not in CH_KINDS:
            continue
        if hot_water is not None and (
            duration_where(hot_water, burn.start, burn.end, bool) > 0
            or hot_water.value_at(burn.end) is True
        ):
            continue  # hot water ran: the burn may have ended for it
        if not _asked_throughout(demand, burn.start, burn.end):
            continue  # ended by the zones' demand, or the demand not known
        at_start, at_end = setpoints.value_at(burn.start), _at_end(setpoints, burn.end)
        end_flow = _flow_at_end(flow, burn.end)
        if at_start is None or at_end is None or end_flow is None:
            continue
        if end_flow < at_end - ENDED_ON_TEMPERATURE_K:
            continue  # not ended on temperature: a flame lost, or stopped by something else
        if not _open_enough(history, burn.start, burn.end):
            continue  # throttled emitters, not the water's floor
        candidates.append((burn.duration, at_start))
    if context.set_by is WaterSetBy.PLUGIN:
        reference = context.lowest
    else:
        reference = min((setpoint for _duration, setpoint in candidates), default=None)
    counted = [
        duration
        for duration, setpoint in candidates
        if reference is not None and abs(setpoint - reference) <= BAND_K
    ]
    short = sum(1 for duration in counted if duration < options.short_burn_s)
    found = _with(base, counted=len(counted), short=short, reference=reference)
    verdict = options.verdict
    if reference is None or len(counted) < verdict.min_heating_burns:
        return _with(found, state=SuggestionState.NO_DATA)
    if short / len(counted) <= verdict.short_burn_share:
        return _with(found, state=SuggestionState.GOOD_ENOUGH)
    value = _suggested(reference, context.caps)
    if value is None:
        return found  # no raise fits under the caps
    return _with(found, state=SuggestionState.SUGGESTION, value=value)


def _at_end(series: Series[float], end: float) -> float | None:
    """The value in force as a burn ended: the one holding just before its end, else one
    reported at it."""
    before = series.value_before(end)
    return before if before is not None else series.value_at(end)


def _flow_at_end(flow: Series[float], end: float) -> float | None:
    """The flow as a burn ended: the higher of the value holding just before its end and one
    reported with the flame going out — a reading and the flame's report may share a moment."""
    known = [value for value in (flow.value_before(end), flow.value_at(end)) if value is not None]
    return max(known) if known else None


def _suggested(reference: float, caps: Sequence[float]) -> float | None:
    """The reference + ``RAISE_K`` rounded up, under the caps; ``None`` when that is no raise."""
    ceiling = min((*(cap - UNDER_CAPS_K for cap in caps), SUGGESTION_CEILING))
    value = min(_round_up(reference + RAISE_K), _round_down(ceiling))
    return value if value > reference else None


def _with(result: LowestWaterSuggestion, **changes: object) -> LowestWaterSuggestion:
    return replace(result, **changes)  # type: ignore[arg-type]


# --- the estimate from the boiler's minimum power (Q3.4) -----------------------------------------

# A heat loss that counts: the user's own (entered, or given as a design load), or one measured
# or learned with the confidence the plugin counts — never a coarse estimate.
_CONFIDENT_SOURCES = frozenset({Source.ENTERED, Source.MEASURED, Source.LEARNED})


def design_load_kw(parameters: ParameterSet, curve: HeatingCurve) -> float | None:
    """The house's design load at the curve's design point, kW: the heat loss entered, or
    measured or learned with confidence (``parameters.MIN_CONFIDENCE``), times the curve's room
    minus its design outdoor temperature — the curve's own law. ``None`` from a coarse estimate
    (floor area, annual energy) or without one."""
    loss = parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    if loss is None or loss.source not in _CONFIDENT_SOURCES:
        return None
    return loss.value * (curve.room - curve.design_outdoor)


def estimate_from_power(
    min_power_kw: float | None,
    design_load: float | None,
    curve: HeatingCurve | None,
    *,
    condensing: bool,
) -> PowerEstimate:
    """``room + (design flow − room) · (P_min / P_design)^(1/n)``, rounded to 0.5 °C — the curve's
    flow at the crossover outdoor temperature (without its parallel shift). Never for a boiler
    that does not condense; ``None`` with the first gap: the minimum power not entered, no design
    load, no curve, the minimum at or above the load."""
    if not condensing:
        return PowerEstimate(gap=EstimateGap.NOT_CONDENSING)
    if min_power_kw is None:
        return PowerEstimate(gap=EstimateGap.MIN_POWER)
    if curve is None:
        return PowerEstimate(gap=EstimateGap.CURVE)
    if design_load is None:
        return PowerEstimate(gap=EstimateGap.DESIGN_LOAD)
    if min_power_kw >= design_load:
        return PowerEstimate(gap=EstimateGap.MIN_POWER_NOT_BELOW_LOAD)
    ratio = min_power_kw / design_load
    value = curve.room + (curve.design_flow - curve.room) * math.pow(ratio, 1.0 / curve.exponent)
    return PowerEstimate(round(value / STEP_K) * STEP_K)


def entered_min_power(parameters: ParameterSet) -> float | None:
    """The boiler's minimum power as the user entered it (no reading from the boiler in 0.2.2)."""
    entered = parameters.get(ParameterKey.BOILER_MIN_POWER).estimate(Source.ENTERED)
    return None if entered is None else entered.value


# --- the wall thermostat on a gateway -----------------------------------------------------------


class WallWarning(StrEnum):
    NOT_MAPPED = "not_mapped"  # its setpoint signal is not mapped: not known
    UNKNOWN = "unknown"  # mapped, but it reports no setpoint
    LOW = "low"  # below ``WALL_THERMOSTAT_LOW``: the house cools after a hand-back


@dataclass(frozen=True, slots=True)
class WallFallback:
    """What the wall thermostat keeps after a hand-back, °C, and the warning about it."""

    setpoint: float | None
    warning: WallWarning | None


def wall_thermostat_fallback(mapped: bool, value: float | None) -> WallFallback:
    """The wall thermostat's own setting as its signal shows it, and the warning: not mapped,
    unknown, or below ``WALL_THERMOSTAT_LOW``."""
    if not mapped:
        return WallFallback(None, WallWarning.NOT_MAPPED)
    if value is None:
        return WallFallback(None, WallWarning.UNKNOWN)
    return WallFallback(value, WallWarning.LOW if value < WALL_THERMOSTAT_LOW else None)


def wall_warning_since(previous: float | None, fallback: WallFallback, now: float) -> float | None:
    """Since when the mapped value has been low or unknown — one stretch, whichever of the two;
    ``None`` while it is fine or not mapped (no issue for that: nothing is known). A moment
    later than now (the clock set back) counts as now."""
    if fallback.warning not in (WallWarning.LOW, WallWarning.UNKNOWN):
        return None
    if previous is None or previous > now:
        return now
    return previous


def wall_issue_due(since: float | None, now: float) -> bool:
    return since is not None and now - since >= WALL_THERMOSTAT_ISSUE_S
