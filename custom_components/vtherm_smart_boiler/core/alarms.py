"""Alarms and early warnings — information in the monitor; only the boiler's own fault stops
heating (boiler protection, below).

Alarms look at the current state, with hysteresis so they do not flap: water pressure below the
"add water" threshold the user took from the boiler's manual (none by default) or too high, flue
gas too hot, starts too frequent, ignition unstable, a circuit's water too hot for its maximum
(decision 10). Early warnings compare a recent window with a baseline window: pressure falling,
with the water temperature taken into account; the flue gas running hotter above the return (a
fouling heat exchanger); the CH hysteresis drifting.

Unknown inputs (S-16, the review's question 9): an alarm judged from a known input is known at
that moment (``known_at``). One whose input is unknown, or which cannot be judged, keeps its last
known state for ``UNKNOWN_HOLD_S`` (reason ``held``), then is unknown (``active is None``) with
the reason it cannot be judged; with nothing known before, unknown at once — never "OK". An
unknown value never raises an alarm, never completes a hold and never hands back. A banded alarm
reaches its alarm level only after ``ALARM_HOLD_S`` of known readings beyond the alarm limit
(decision 7); the warning level shows at once.

Boiler protection (a stated exception of principle 12): while the boiler itself reports a fault
that stops it — its own low-water-pressure fault, or another fault the user maps as stopping it —
for ``BOILER_FAULT_HOLD_S``, control sends its usual "off", with no hand-back and no latch, and
heats again in the step the fault reads off, unknown or unavailable. On the OpenTherm Gateway a
fault flag counts only while the boiler's general fault indication reads "on" too: the gateway
reads the fault details once per new fault and never again after it clears (Q3.9).
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import pairwise

from .cycles import ClassifiedBurn
from .installation import Circuit, CircuitControl
from .metrics import CH_KINDS
from .readings import ZONE_OPEN, ZoneState
from .series import Series, duration_where

MIN = 60.0
HOUR = 3600.0
DAY = 86400.0
# S-16, question 9: an alarm that cannot judge keeps its last known state this long, then shows
# unknown (provisional, K4).
UNKNOWN_HOLD_S = HOUR
# Decision 7: a banded alarm's alarm level counts once held this long with known readings
# (provisional, K4); the notifications and the fault stop wait as long.
ALARM_HOLD_S = 5 * MIN
# Reasons an alarm shows (translation keys): held through a gap, and why it cannot be judged.
HELD = "held"
UNKNOWN_INPUT = "unknown_input"
HOT_WATER_UNKNOWN = "hot_water_unknown"
NO_ZONE_DATA = "no_zone_data"


class AlarmKind(StrEnum):
    PRESSURE_LOW = "pressure_low"
    PRESSURE_HIGH = "pressure_high"
    FLUE_GAS_HIGH = "flue_gas_high"
    FREQUENT_STARTS = "frequent_starts"
    UNSTABLE_IGNITION = "unstable_ignition"
    PRESSURE_FALLING = "pressure_falling"
    FLUE_GAS_RISING = "flue_gas_rising"
    HYSTERESIS_DRIFT = "hysteresis_drift"
    LOW_FLOW = "low_flow"
    CIRCUIT_TOO_HOT = "circuit_too_hot"


class Level(StrEnum):
    WARNING = "warning"
    ALARM = "alarm"


@dataclass(frozen=True, slots=True)
class Alarm:
    kind: AlarmKind
    active: bool | None  # ``None``: it cannot be judged, and its hold is over (S-16)
    level: Level | None = None
    value: float | None = None
    limit: float | None = None
    reason: str | None = None  # why it cannot be judged, why it does not apply, or ``held``
    since: float | None = None  # when its condition began (a level or a warning that waits)
    known_at: float | None = None  # when it was last judged from a known input


def settle(alarm: Alarm, previous: Alarm | None, now: float) -> Alarm:
    """S-16: an alarm judged now (``active`` known) is known now. One that cannot be judged
    (``active is None``, its reason saying why) keeps the last known state for
    ``UNKNOWN_HOLD_S`` after it was last known — reason ``held``, and whatever it was waiting
    for starts again (``since``) — then is unknown; with nothing known before, unknown at once.
    A moment known later than now (the clock set back) is held."""
    if alarm.active is not None:
        return replace(alarm, known_at=now)
    known_at = None if previous is None else previous.known_at
    if (
        previous is not None
        and previous.active is not None
        and known_at is not None
        and now - known_at < UNKNOWN_HOLD_S
    ):
        return replace(previous, reason=HELD, since=None)
    return replace(alarm, known_at=known_at)


@dataclass(frozen=True, slots=True)
class Band:
    """Warning and alarm limits; ``rising`` means the danger is above the limits.

    An active alarm clears only once the value is back past the warning limit by
    ``hysteresis``. A ``None`` limit switches that level off.
    """

    warning: float | None
    alarm: float | None
    rising: bool
    hysteresis: float


# "Add water" (Y1): one optional threshold the user takes from the boiler's manual — none by
# default, replacing 0.2.1's 1.0 / 0.7 bar — cleared 0.1 bar above it; 0.1 to 2.0 bar.
ADD_WATER_HYSTERESIS_BAR = 0.1
ADD_WATER_RANGE_BAR = (0.1, 2.0)
# The high pressure (decision 13 of 0.2.3, SB-18): no limits by default, as "add water" — the
# user enters them below the safety valve's rating, read on the valve itself (often 3 bar in
# Europe, about 2.1 bar in North America: no one default fits); a level clears 0.1 bar below.
PRESSURE_HIGH_HYSTERESIS_BAR = 0.1
# Flue gas of a condensing boiler; a non-condensing boiler runs far hotter and has no default.
FLUE_GAS_CONDENSING_BAND = Band(warning=85.0, alarm=100.0, rising=True, hysteresis=5.0)


def pressure_high_band(warning: float | None, alarm: float | None) -> Band | None:
    """The high-pressure band from the user's limits — either may be missing, and that level is
    off; ``None`` without either: no high-pressure alarm at all."""
    if warning is None and alarm is None:
        return None
    return Band(warning, alarm, rising=True, hysteresis=PRESSURE_HIGH_HYSTERESIS_BAR)


def add_water_band(threshold: float) -> Band:
    """The "add water" band: its one level at the user's threshold, below which the pressure
    is too low; it clears ``ADD_WATER_HYSTERESIS_BAR`` above it."""
    return Band(warning=None, alarm=threshold, rising=False, hysteresis=ADD_WATER_HYSTERESIS_BAR)


def banded_alarm(
    kind: AlarmKind, value: float | None, band: Band, previous: Alarm | None, now: float
) -> Alarm:
    """Level of a value against a band. The warning level shows at once; the alarm level once
    the value has stayed beyond the alarm limit for ``ALARM_HOLD_S`` of known readings
    (``since``: the run began) — a gap restarts the count. An active level clears only once the
    value is past its limit by the hysteresis — from alarm to warning as from warning to none
    (P64). An unknown value keeps what was known, hysteresis included, for ``UNKNOWN_HOLD_S``,
    then the alarm is unknown (``settle``)."""
    if value is None:
        return settle(Alarm(kind, None, reason=UNKNOWN_INPUT), previous, now)
    prior = previous if previous is not None and previous.active is not None else None

    def beyond(limit: float | None) -> bool:
        if limit is None:
            return False
        return value > limit if band.rising else value < limit

    def released(limit: float) -> float:
        return limit - band.hysteresis if band.rising else limit + band.hysteresis

    was_alarm = prior is not None and prior.active is True and prior.level is Level.ALARM
    if beyond(band.alarm):
        since = now
        if prior is not None and prior.since is not None and prior.since <= now:
            since = prior.since  # a clock set back starts the count again now (C9)
        if was_alarm or now - since >= ALARM_HOLD_S:
            return Alarm(kind, True, Level.ALARM, value, band.alarm, since=since, known_at=now)
        if band.warning is not None:  # waiting for the alarm level: the warning meanwhile
            return Alarm(kind, True, Level.WARNING, value, band.warning, since=since, known_at=now)
        return Alarm(kind, False, None, value, band.alarm, since=since, known_at=now)
    if was_alarm and band.alarm is not None and beyond(released(band.alarm)):
        return Alarm(kind, True, Level.ALARM, value, band.alarm, known_at=now)
    if beyond(band.warning):
        return Alarm(kind, True, Level.WARNING, value, band.warning, known_at=now)
    was_active = prior is not None and prior.active is True
    if was_active and band.warning is not None and beyond(released(band.warning)):
        return Alarm(kind, True, Level.WARNING, value, band.warning, known_at=now)
    return Alarm(kind, False, None, value, known_at=now)


def pressure_alarms(
    value: float | None,
    add_water_below: float | None,
    high: Band | None,
    previous: Mapping[AlarmKind, Alarm],
    now: float,
) -> dict[AlarmKind, Alarm]:
    """The water pressure's alarms: "add water" only with the user's threshold, and the high
    pressure only with the user's limits (none by default: no such alarm at all; decision 13).
    Both only inform: heating stops only while the boiler itself reports a fault that stops
    it."""
    alarms: dict[AlarmKind, Alarm] = {}
    if add_water_below is not None:
        low = AlarmKind.PRESSURE_LOW
        band = add_water_band(add_water_below)
        alarms[low] = banded_alarm(low, value, band, previous.get(low), now)
    if high is not None:
        high_kind = AlarmKind.PRESSURE_HIGH
        alarms[high_kind] = banded_alarm(high_kind, value, high, previous.get(high_kind), now)
    return alarms


DEFAULT_FREQUENT_STARTS_PER_HOUR = 12
DEFAULT_UNSTABLE_BURN_S = 60.0
DEFAULT_UNSTABLE_BURNS_PER_DAY = 10
# P-82: a count alarm clears only at its limit minus this (provisional, K4).
COUNT_CLEAR_MARGIN = 2
# Y1: a count is judged only with the flame known for this share of its window (provisional,
# K4); otherwise it cannot be judged.
KNOWN_SHARE = 0.5
# P-81: a short burn that ends with the flow within this of the CH setpoint then in force ended
# on the boiler's own hysteresis, not on a lost flame (provisional, K4).
SETPOINT_REACHED_K = 2.0


def _count_alarm(
    kind: AlarmKind,
    count: int,
    limit: int,
    previous: Alarm | None,
    now: float,
) -> Alarm:
    """A count above ``limit`` raises it; once raised, it clears only at ``limit`` minus
    ``COUNT_CLEAR_MARGIN`` (P-82), and never lower than 0: at the smallest limits it clears at 0
    rather than never (PB-63)."""
    was = previous is not None and previous.active is True
    active = count > limit or (was and count > max(0, limit - COUNT_CLEAR_MARGIN))
    alarm = Alarm(kind, active, Level.WARNING if active else None, float(count), float(limit))
    return settle(alarm, previous, now)


def _flame_unknown(known_s: float | None, window_s: float) -> bool:
    """The flame known for less than ``KNOWN_SHARE`` of the window: the count cannot be judged.
    ``None``: not told — judged."""
    return known_s is not None and known_s < KNOWN_SHARE * window_s


def frequent_starts(
    burns: Iterable[ClassifiedBurn],
    now: float,
    limit: int = DEFAULT_FREQUENT_STARTS_PER_HOUR,
    previous: Alarm | None = None,
    known_s: float | None = None,
) -> Alarm:
    """Seen starts in the last hour above ``limit``; ``known_s``: the seconds of that hour the
    flame was known — under half, it cannot be judged."""
    kind = AlarmKind.FREQUENT_STARTS
    if _flame_unknown(known_s, HOUR):
        return settle(Alarm(kind, None, limit=float(limit), reason=UNKNOWN_INPUT), previous, now)
    starts = sum(1 for b in burns if b.burn.start_seen and now - HOUR <= b.burn.start < now)
    return _count_alarm(kind, starts, limit, previous, now)


def unstable_ignition(
    burns: Iterable[ClassifiedBurn],
    now: float,
    shortest_s: float = DEFAULT_UNSTABLE_BURN_S,
    limit: int = DEFAULT_UNSTABLE_BURNS_PER_DAY,
    demand: Series[bool] | None = None,
    flow: Series[float] | None = None,
    setpoint: Series[float] | None = None,
    previous: Alarm | None = None,
    known_s: float | None = None,
) -> Alarm:
    """Complete burns shorter than ``shortest_s`` in the last day — flame lost soon after
    ignition — above ``limit``. A burn that ended with the zones' demand (a TPI zone's short
    on-time, followed at once) lost no flame: with ``demand`` — whether the zones ask for heat
    at each moment — only one during which, its end included, no moment is known without
    demand counts; the boiler was told to stop at such a moment. Nor did one that ended on the
    boiler's own hysteresis (P-81): with ``flow`` and ``setpoint`` mapped (given), only a burn
    that ended with the flow known and more than ``SETPOINT_REACHED_K`` below the CH setpoint
    then in force counts — either unknown at its end, it does not; with either not mapped every
    such burn counts, as before (the feature is degraded). ``known_s``: the seconds of the day
    the flame was known — under half, it cannot be judged."""
    kind = AlarmKind.UNSTABLE_IGNITION
    if _flame_unknown(known_s, DAY):
        return settle(Alarm(kind, None, limit=float(limit), reason=UNKNOWN_INPUT), previous, now)
    count = sum(
        1
        for b in burns
        if b.burn.complete
        and b.burn.duration < shortest_s
        and now - DAY <= b.burn.start < now
        and _asked_throughout(demand, b.burn.start, b.burn.end)
        and _short_of_setpoint(flow, setpoint, b.burn.end)
    )
    return _count_alarm(kind, count, limit, previous, now)


def _short_of_setpoint(
    flow: Series[float] | None, setpoint: Series[float] | None, end: float
) -> bool:
    """P-81: the burn ended with the water known short of the CH setpoint then in force — its
    flame was lost — or, with flow or setpoint not mapped, it cannot be told (counted)."""
    if flow is None or setpoint is None:
        return True
    water, target = flow.value_at(end), setpoint.value_at(end)
    if water is None or target is None:
        return False  # mapped but unknown at its end: not counted
    return water < target - SETPOINT_REACHED_K


def _asked_throughout(demand: Series[bool] | None, start: float, end: float) -> bool:
    """No moment of ``[start, end]`` known without demand (an unknown one may be asking)."""
    if demand is None:
        return True
    if demand.value_at(end) is False:
        return False
    return duration_where(demand, start, end, lambda asked: not asked) == 0.0


# --- early warnings ---------------------------------------------------------------------------

MIN_TREND_SAMPLES = 20


@dataclass(frozen=True, slots=True)
class Trend:
    baseline: float
    recent: float

    @property
    def change(self) -> float:
        return self.recent - self.baseline


def compare_windows(
    baseline: Sequence[float], recent: Sequence[float], min_samples: int = MIN_TREND_SAMPLES
) -> Trend | None:
    """Medians of two windows, when both have enough samples."""
    if len(baseline) < min_samples or len(recent) < min_samples:
        return None
    return Trend(statistics.median(baseline), statistics.median(recent))


def trend_warning(kind: AlarmKind, trend: Trend | None, max_change: float, direction: int) -> Alarm:
    """Warning when the change exceeds ``max_change`` in ``direction`` (+1 up, −1 down, 0 any);
    without a trend it cannot be judged (``settle`` holds it, then shows it unknown)."""
    if trend is None:
        return Alarm(kind, None, limit=max_change, reason=UNKNOWN_INPUT)
    change = trend.change
    exceeded = abs(change) > max_change if direction == 0 else change * direction > max_change
    return Alarm(kind, exceeded, Level.WARNING if exceeded else None, change, max_change)


DEFAULT_PRESSURE_DROP_BAR = 0.2
DEFAULT_FLUE_RISE_K = 5.0
DEFAULT_HYSTERESIS_DRIFT_K = 3.0
COLD_FLOW = 35.0
STEADY_AFTER_S = 3 * MIN
# The pressure trend with the water temperature taken into account (Open after R6 #5, Y1): a
# sample every 10 min where the flame has been known off for the 10 min before; the pressure's
# rise per kelvin of water fitted over the whole history and used only where the flow spans at
# least 10 K and the fit lies within 0 to 0.05 bar/K; the pressure corrected to a 40 °C loop
# (each provisional, K4). Without a usable slope, only cold samples count, as before.
PRESSURE_SAMPLE_S = 10 * MIN
QUIET_FLAME_S = 10 * MIN
SLOPE_MIN_SPAN_K = 10.0
SLOPE_MAX_BAR_PER_K = 0.05
REFERENCE_FLOW = 40.0
_EPSILON = 1e-6


@dataclass(frozen=True, slots=True)
class PressureSample:
    t: float
    pressure: float
    flow: float


def pressure_samples(
    pressure: Series[float],
    flame: Series[bool],
    flow: Series[float],
    start: float,
    end: float,
    step: float = PRESSURE_SAMPLE_S,
) -> list[PressureSample]:
    """The pressure every ``step`` in ``[start, end)`` where the flame is known off and has been
    for ``QUIET_FLAME_S`` before — no burn heating the water just then — and pressure and flow
    are known."""
    samples: list[PressureSample] = []
    t = start
    while t < end:
        p, w = pressure.value_at(t), flow.value_at(t)
        off = duration_where(flame, t - QUIET_FLAME_S, t, lambda on: on is False)
        quiet = flame.value_at(t) is False and off >= QUIET_FLAME_S - _EPSILON
        if p is not None and w is not None and quiet:
            samples.append(PressureSample(t, p, w))
        t += step
    return samples


def pressure_slope(samples: Sequence[PressureSample]) -> float | None:
    """The pressure's rise per kelvin of water, fitted by least squares; ``None`` where the
    flow spans less than ``SLOPE_MIN_SPAN_K`` or the fit lies outside 0 to
    ``SLOPE_MAX_BAR_PER_K`` — heating the water never lowers the pressure, and no sealed system
    swells that much."""
    if len(samples) < 2:
        return None
    flows = [s.flow for s in samples]
    if max(flows) - min(flows) < SLOPE_MIN_SPAN_K:
        return None
    mean_flow = statistics.fmean(flows)
    mean_pressure = statistics.fmean(s.pressure for s in samples)
    spread = sum((w - mean_flow) ** 2 for w in flows)
    if spread <= 0.0:
        return None
    covariance = sum((s.flow - mean_flow) * (s.pressure - mean_pressure) for s in samples)
    slope = covariance / spread
    return slope if 0.0 <= slope <= SLOPE_MAX_BAR_PER_K else None


def pressure_trend(
    pressure: Series[float],
    flame: Series[bool],
    flow: Series[float],
    baseline: tuple[float, float],
    recent: tuple[float, float],
) -> Alarm:
    """ "Your pressure keeps falling — there is a risk of a leak": the median pressure of the
    ``recent`` window against the ``baseline`` window, each with at least ``MIN_TREND_SAMPLES``
    samples, falling by more than ``DEFAULT_PRESSURE_DROP_BAR``. With a usable slope over the
    whole history every quiet sample counts, corrected to a ``REFERENCE_FLOW`` loop — so a slow
    leak shows in winter too; without one only cold samples (flow below ``COLD_FLOW``). Too few
    samples: it cannot be judged."""
    samples = pressure_samples(pressure, flame, flow, baseline[0], recent[1])
    slope = pressure_slope(samples)

    def values(window: tuple[float, float]) -> list[float]:
        inside = [s for s in samples if window[0] <= s.t < window[1]]
        if slope is not None:
            return [s.pressure - slope * (s.flow - REFERENCE_FLOW) for s in inside]
        return [s.pressure for s in inside if s.flow < COLD_FLOW]

    trend = compare_windows(values(baseline), values(recent))
    return trend_warning(AlarmKind.PRESSURE_FALLING, trend, DEFAULT_PRESSURE_DROP_BAR, -1)


def flue_excess_samples(
    flue: Series[float],
    return_temp: Series[float],
    burns: Iterable[ClassifiedBurn],
    step: float = MIN,
) -> list[float]:
    """Flue gas minus return during steady heating burns (after the first minutes)."""
    samples: list[float] = []
    for classified in burns:
        if classified.kind not in CH_KINDS:
            continue
        t = classified.burn.start + STEADY_AFTER_S
        while t < classified.burn.end:
            f, r = flue.value_at(t), return_temp.value_at(t)
            if f is not None and r is not None:
                samples.append(f - r)
            t += step
    return samples


def hysteresis_samples(
    flow: Series[float],
    burns: Sequence[ClassifiedBurn],
    setpoint: Series[float] | None = None,
    max_setpoint_change: float = 1.0,
    *,
    demand: Series[bool] | None,
) -> list[float]:
    """Flow when the burner stopped minus flow when it restarted, for heating cycles.

    Only pauses between two heating burns with both edges seen count, during which the zones'
    demand (``History.zone_calling``) was known "asking" throughout — a pause without demand
    comes from the zones, not the burner's hysteresis (P-29); without zone data, none — and,
    when the setpoint is mapped, only those during which it was known throughout and its range
    stayed within ``max_setpoint_change`` (PB-67).
    """
    samples: list[float] = []
    if demand is None:
        return samples
    for before, after in pairwise(burns):
        if before.kind not in CH_KINDS or after.kind not in CH_KINDS:
            continue
        if not (before.burn.end_seen and after.burn.start_seen):
            continue
        stop, restart = before.burn.end, after.burn.start
        asked = duration_where(demand, stop, restart, lambda calling: calling is True)
        if asked < restart - stop - _EPSILON:
            continue
        off_flow, on_flow = flow.value_at(stop), flow.value_at(restart)
        if off_flow is None or on_flow is None:
            continue
        if setpoint is not None and not _steady(setpoint, stop, restart, max_setpoint_change):
            continue
        samples.append(off_flow - on_flow)
    return samples


def _steady(series: Series[float], start: float, end: float, max_range: float) -> bool:
    """Known throughout ``[start, end]`` and its range within ``max_range`` — a value that
    moves and comes back inside counts as moved (PB-67)."""
    values = [segment.value for segment in series.segments(start, end)]
    values.append(series.value_at(end))
    known = [value for value in values if value is not None]
    return len(known) == len(values) and max(known) - min(known) <= max_range


# A pump runs on after the burner, and rooms close their valves as they warm: only a closed
# circuit that lasts this long is a warning (S28; one boiler seen running on for 15 min, L3).
LOW_FLOW_HOLD_S = 15 * 60.0


def low_flow(
    zones: Sequence[ZoneState],
    pump_running: bool | None,
    now: float,
    max_age: float | None,
    previous: Alarm | None = None,
    dhw: bool | None = None,
    bypass: bool = False,
    has_dhw: bool = True,
) -> Alarm:
    """Warning while the pump runs and every zone's valve has been closed for a while: no path
    for the water.

    Only zones with a fresh, known valve opening count; a zone without one (e.g. a relay) could be
    the open path, so it cannot be judged. ``pump_running`` comes from a pump-running or a
    CH-active signal, each by its own age limit. Not judged during hot water (the pump may serve
    it), nor on a boiler with hot water (``has_dhw``) whose hot water is unknown (P-27: storage
    charging with the valves closed); off with a bypass or a low-loss header (the water always
    has a path). ``reason`` says why it cannot be judged or does not apply; what cannot be
    judged is held, then unknown (``settle``), and the wait starts again after it; an active
    warning is held with its first ``since``, so it stays on once judged again (PB-64).
    """
    kind = AlarmKind.LOW_FLOW
    if bypass:
        return Alarm(kind, False, reason="bypass", known_at=now)
    reason: str | None = None
    fresh = [z for z in zones if z.is_fresh(now, max_age)]
    if pump_running is None:
        reason = "no_pump_signal"
    elif has_dhw and dhw is None:
        reason = HOT_WATER_UNKNOWN
    elif has_dhw and dhw is True:
        reason = "hot_water"
    elif not fresh:
        reason = "no_fresh_zone"
    elif any(z.valve_open is None for z in fresh):
        reason = "zone_without_valve"
    if reason is not None:
        held = settle(Alarm(kind, None, reason=reason), previous, now)
        if held.reason == HELD and held.active is True and previous is not None:
            held = replace(held, since=previous.since)
        return held
    widest = max(z.valve_open for z in fresh if z.valve_open is not None)
    if not (pump_running and widest <= ZONE_OPEN):
        return Alarm(kind, False, None, widest, ZONE_OPEN, known_at=now)
    since = now
    if previous is not None and previous.since is not None and previous.since <= now:
        since = previous.since
    active = now - since >= LOW_FLOW_HOLD_S
    level = Level.WARNING if active else None
    return Alarm(kind, active, level, widest, ZONE_OPEN, since=since, known_at=now)


# --- decision 10: a circuit's water too hot for its maximum -------------------------------------

# The circuit's maximum limits the setpoint; the boiler may overshoot it by its own hysteresis.
# Once the measured flow has stayed above the user's alarm temperature for the user's time, an
# information alarm; it clears below the alarm temperature by this much (provisional, K4).
CIRCUIT_ALARM_HYSTERESIS_K = 1.0
CIRCUIT_ALARM_RISE_K = 5.0  # the alarm temperature's starting value: the maximum + 5 K (decided)
CIRCUIT_ALARM_MIN = 10.0  # the time's starting value, in minutes (decided)
NO_FLOW_READING = "no_flow_reading"
CIRCUIT_NOT_MEASURED = "circuit_not_measured"


def circuit_flow(
    circuit: Circuit, boiler_flow: float | None, own_flow: float | None, *, own_mapped: bool = False
) -> tuple[float | None, str | None]:
    """The flow a circuit's emitters get, as the too-hot alarm judges it, or why it is not
    known: the circuit's own flow sensor where it reads, else the boiler's flow for an unmixed
    circuit; a passive fixed or mixed circuit without its own reading is not measured —
    ``own_mapped``: it has a sensor that does not read now. Readings are fresh or ``None``."""
    if own_flow is not None:
        return own_flow, None
    if circuit.control is CircuitControl.UNMIXED_SHARED:
        return (boiler_flow, None) if boiler_flow is not None else (None, NO_FLOW_READING)
    return None, NO_FLOW_READING if own_mapped else CIRCUIT_NOT_MEASURED


def circuit_too_hot(
    flow: float | None,
    alarm_at: float,
    hold_s: float,
    now: float,
    previous: Alarm | None,
    reason: str | None = None,
) -> Alarm:
    """The circuit's water too hot (decision 10), information only: active once ``flow`` has
    stayed above ``alarm_at`` for ``hold_s``; it clears only below ``alarm_at`` by
    ``CIRCUIT_ALARM_HYSTERESIS_K``. Without a flow reading (``no_flow_reading``) it cannot be
    judged: held, then unknown (S-16, Y1); a circuit no reading can ever show
    (``circuit_not_measured``) is inactive with that reason — the alarm does not apply. A wait
    begun later than now — the clock set back — begins now."""
    kind = AlarmKind.CIRCUIT_TOO_HOT
    if flow is None:
        why = reason or NO_FLOW_READING
        if why == CIRCUIT_NOT_MEASURED:
            return Alarm(kind, False, limit=alarm_at, reason=why, known_at=now)
        return settle(Alarm(kind, None, limit=alarm_at, reason=why), previous, now)
    prior = previous if previous is not None and previous.active is not None else None
    if prior is not None and prior.active and flow >= alarm_at - CIRCUIT_ALARM_HYSTERESIS_K:
        return Alarm(kind, True, Level.WARNING, flow, alarm_at, since=prior.since, known_at=now)
    if flow <= alarm_at:
        return Alarm(kind, False, None, flow, alarm_at, known_at=now)
    since = now
    if prior is not None and not prior.active and prior.since is not None:
        since = min(prior.since, now)
    active = now - since >= hold_s
    level = Level.WARNING if active else None
    return Alarm(kind, active, level, flow, alarm_at, since=since, known_at=now)


# --- notifications (Y1) ------------------------------------------------------------------------

# A notification closes after this long of known readings in the normal range (decision 7:
# "about an hour"; provisional, K4).
NOTICE_CLOSE_S = HOUR


@dataclass(frozen=True, slots=True)
class Notice:
    """A notification — a repair issue telling the user what to do: whether it is open, and
    since when the readings have been known and in the normal range."""

    open: bool = False
    normal_since: float | None = None


def follow_notice(notice: Notice, raised: bool, normal: bool | None, now: float) -> Notice:
    """Open while ``raised`` — its alarm level held, or its trend exceeded. Once open, it closes
    after ``NOTICE_CLOSE_S`` of known readings in the normal range (``normal``): a reading
    outside it, or an unknown one (``None``), keeps it open and starts that hour again. A moment
    later than now (the clock set back) starts it again now."""
    if raised:
        return Notice(True)
    if not notice.open:
        return Notice()
    if normal is not True:
        return Notice(True)
    since = notice.normal_since
    since = now if since is None or since > now else since
    if now - since >= NOTICE_CLOSE_S:
        return Notice()
    return Notice(True, since)


# --- boiler protection: the boiler's own fault (Y1) -------------------------------------------

# A fault the boiler reports stops heating once it has read a known "on" this long (decision 7's
# hold; provisional, K4); it ends in the step it reads off, unknown or unavailable.
BOILER_FAULT_HOLD_S = ALARM_HOLD_S


def fault_counts(flag: bool | None, *, gated: bool, gate: bool | None) -> bool:
    """A fault signal counts while it reads a known "on" — an unknown or unavailable one counts
    as no fault. ``gated``: it comes from the OpenTherm Gateway, which reads the fault details
    once per new fault and never again after it clears (Q3.9), so it counts only while the
    boiler's general fault indication (``gate``) reads a known "on" too (provisional, K4)."""
    return flag is True and (not gated or gate is True)


def follow_fault(since: float | None, on: bool, now: float) -> float | None:
    """Since when a fault has counted without a break; ``None`` once it does not. A moment
    later than now (the clock set back) starts it again now."""
    if not on:
        return None
    return now if since is None or since > now else since


def fault_holds(since: float | None, now: float) -> bool:
    """The fault has counted for ``BOILER_FAULT_HOLD_S``: control sends its usual "off"."""
    return since is not None and now - since >= BOILER_FAULT_HOLD_S
