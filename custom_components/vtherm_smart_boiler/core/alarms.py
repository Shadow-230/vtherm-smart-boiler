"""Alarms and early warnings — information only in the monitor.

Alarms look at the current state, with hysteresis so they do not flap: water pressure too low
or too high, flue gas too hot, starts too frequent, ignition unstable, a circuit's water too hot
for its maximum (decision 10). Early warnings compare a recent window with a baseline window:
pressure falling in the cold system, the flue gas running hotter above the return (a fouling heat
exchanger), the CH hysteresis drifting.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from .cycles import ClassifiedBurn
from .installation import Circuit, CircuitControl
from .metrics import CH_KINDS
from .readings import ZONE_OPEN, ZoneState
from .series import Series, duration_where

MIN = 60.0


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
    active: bool
    level: Level | None = None
    value: float | None = None
    limit: float | None = None
    reason: str | None = None  # why it cannot be judged, or why it does not apply
    since: float | None = None  # when its condition began (a warning that waits)


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


PRESSURE_LOW_BAND = Band(warning=1.0, alarm=0.7, rising=False, hysteresis=0.1)
PRESSURE_HIGH_BAND = Band(warning=2.5, alarm=2.8, rising=True, hysteresis=0.1)
# Flue gas of a condensing boiler; a non-condensing boiler runs far hotter and has no default.
FLUE_GAS_CONDENSING_BAND = Band(warning=85.0, alarm=100.0, rising=True, hysteresis=5.0)


def banded_alarm(kind: AlarmKind, value: float | None, band: Band, previous: Alarm | None) -> Alarm:
    """Level of a value against a band. An unknown value keeps what was known, hysteresis
    included; an active level clears only once the value is past its limit by the hysteresis —
    from alarm to warning as from warning to none (P64)."""
    if value is None:
        return previous if previous is not None else Alarm(kind, False)

    def beyond(limit: float | None) -> bool:
        if limit is None:
            return False
        return value > limit if band.rising else value < limit

    def released(limit: float) -> float:
        return limit - band.hysteresis if band.rising else limit + band.hysteresis

    if beyond(band.alarm):
        return Alarm(kind, True, Level.ALARM, value, band.alarm)
    was_alarm = previous is not None and previous.active and previous.level is Level.ALARM
    if was_alarm and band.alarm is not None and beyond(released(band.alarm)):
        return Alarm(kind, True, Level.ALARM, value, band.alarm)
    if beyond(band.warning):
        return Alarm(kind, True, Level.WARNING, value, band.warning)
    was_active = previous is not None and previous.active
    if was_active and band.warning is not None and beyond(released(band.warning)):
        return Alarm(kind, True, Level.WARNING, value, band.warning)
    return Alarm(kind, False, None, value)


DEFAULT_FREQUENT_STARTS_PER_HOUR = 12
DEFAULT_UNSTABLE_BURN_S = 60.0
DEFAULT_UNSTABLE_BURNS_PER_DAY = 10


def frequent_starts(
    burns: Iterable[ClassifiedBurn],
    now: float,
    limit: int = DEFAULT_FREQUENT_STARTS_PER_HOUR,
) -> Alarm:
    """Seen starts in the last hour above ``limit``."""
    starts = sum(1 for b in burns if b.burn.start_seen and now - 3600.0 <= b.burn.start < now)
    return Alarm(
        AlarmKind.FREQUENT_STARTS,
        starts > limit,
        Level.WARNING if starts > limit else None,
        float(starts),
        float(limit),
    )


def unstable_ignition(
    burns: Iterable[ClassifiedBurn],
    now: float,
    shortest_s: float = DEFAULT_UNSTABLE_BURN_S,
    limit: int = DEFAULT_UNSTABLE_BURNS_PER_DAY,
    demand: Series[bool] | None = None,
) -> Alarm:
    """Complete burns shorter than ``shortest_s`` in the last day — flame lost soon after
    ignition — above ``limit``. A burn that ended with the zones' demand (a TPI zone's short
    on-time, followed at once) lost no flame: with ``demand`` — whether the zones ask for heat
    at each moment — only one during which, its end included, no moment is known without
    demand counts; the boiler was told to stop at such a moment."""
    count = sum(
        1
        for b in burns
        if b.burn.complete
        and b.burn.duration < shortest_s
        and now - 86400.0 <= b.burn.start < now
        and _asked_throughout(demand, b.burn.start, b.burn.end)
    )
    return Alarm(
        AlarmKind.UNSTABLE_IGNITION,
        count > limit,
        Level.WARNING if count > limit else None,
        float(count),
        float(limit),
    )


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
    """Warning when the change exceeds ``max_change`` in ``direction`` (+1 up, −1 down, 0 any)."""
    if trend is None:
        return Alarm(kind, False)
    change = trend.change
    exceeded = abs(change) > max_change if direction == 0 else change * direction > max_change
    return Alarm(kind, exceeded, Level.WARNING if exceeded else None, change, max_change)


DEFAULT_PRESSURE_DROP_BAR = 0.2
DEFAULT_FLUE_RISE_K = 5.0
DEFAULT_HYSTERESIS_DRIFT_K = 3.0
COLD_FLOW = 35.0
STEADY_AFTER_S = 3 * MIN


def cold_pressure_samples(
    pressure: Series[float],
    flame: Series[bool],
    flow: Series[float],
    start: float,
    end: float,
    step: float = 10 * MIN,
) -> list[float]:
    """Pressure sampled while the burner is off and the water cold, so temperature does not
    move it."""
    samples: list[float] = []
    t = start
    while t < end:
        p, f, w = pressure.value_at(t), flame.value_at(t), flow.value_at(t)
        if p is not None and f is False and w is not None and w < COLD_FLOW:
            samples.append(p)
        t += step
    return samples


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
) -> list[float]:
    """Flow when the burner stopped minus flow when it restarted, for heating cycles.

    Only pauses between two heating burns with both edges seen count, and — when the setpoint is
    known — only those during which it moved less than ``max_setpoint_change``.
    """
    samples: list[float] = []
    for before, after in pairwise(burns):
        if before.kind not in CH_KINDS or after.kind not in CH_KINDS:
            continue
        if not (before.burn.end_seen and after.burn.start_seen):
            continue
        stop, restart = before.burn.end, after.burn.start
        off_flow, on_flow = flow.value_at(stop), flow.value_at(restart)
        if off_flow is None or on_flow is None:
            continue
        if setpoint is not None:
            a, b = setpoint.value_at(stop), setpoint.value_at(restart)
            if a is None or b is None or abs(a - b) > max_setpoint_change:
                continue
        samples.append(off_flow - on_flow)
    return samples


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
) -> Alarm:
    """Warning while the pump runs and every zone's valve has been closed for a while: no path
    for the water.

    Only zones with a fresh, known valve opening count; a zone without one (e.g. a relay) could be
    the open path, so it keeps the warning off. ``pump_running`` comes from a pump-running or a
    CH-active signal. Not applied during hot water (the pump may serve it) or with a bypass or a
    low-loss header (the water always has a path); ``reason`` says why it is off when it cannot
    be judged or does not apply.
    """
    kind = AlarmKind.LOW_FLOW
    if bypass:
        return Alarm(kind, False, reason="bypass")
    if pump_running is None:
        return Alarm(kind, False, reason="no_pump_signal")
    if dhw is True:
        return Alarm(kind, False, reason="hot_water")
    fresh = [z for z in zones if z.is_fresh(now, max_age)]
    if not fresh:
        return Alarm(kind, False, reason="no_fresh_zone")
    if any(z.valve_open is None for z in fresh):
        return Alarm(kind, False, reason="zone_without_valve")
    widest = max(z.valve_open for z in fresh if z.valve_open is not None)
    if not (pump_running and widest <= ZONE_OPEN):
        return Alarm(kind, False, None, widest, ZONE_OPEN)
    since = previous.since if previous is not None and previous.since is not None else now
    active = now - since >= LOW_FLOW_HOLD_S
    return Alarm(kind, active, Level.WARNING if active else None, widest, ZONE_OPEN, since=since)


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
    ``CIRCUIT_ALARM_HYSTERESIS_K``. Without a flow reading it is inactive with its reason
    (``reason``, else ``no_flow_reading``). A wait begun later than now — the clock set back —
    begins now."""
    kind = AlarmKind.CIRCUIT_TOO_HOT
    if flow is None:
        return Alarm(kind, False, limit=alarm_at, reason=reason or NO_FLOW_READING)
    if previous is not None and previous.active and flow >= alarm_at - CIRCUIT_ALARM_HYSTERESIS_K:
        return Alarm(kind, True, Level.WARNING, flow, alarm_at, since=previous.since)
    if flow <= alarm_at:
        return Alarm(kind, False, None, flow, alarm_at)
    since = now
    if previous is not None and not previous.active and previous.since is not None:
        since = min(previous.since, now)
    active = now - since >= hold_s
    return Alarm(kind, active, Level.WARNING if active else None, flow, alarm_at, since=since)
