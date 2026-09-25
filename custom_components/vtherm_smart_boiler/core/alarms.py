"""Alarms and early warnings — information only in the monitor.

Alarms look at the current state, with hysteresis so they do not flap: water pressure too low
or too high, flue gas too hot, starts too frequent, ignition unstable. Early warnings compare a
recent window with a baseline window: pressure falling in the cold system, the flue gas running
hotter above the return (a fouling heat exchanger), the CH hysteresis drifting.
"""

from __future__ import annotations

import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise

from .cycles import ClassifiedBurn
from .metrics import CH_KINDS
from .readings import ZONE_OPEN, ZoneState
from .series import Series

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
    """Level of a value against a band; an unknown value keeps no alarm active."""
    if value is None:
        return Alarm(kind, False)

    def beyond(limit: float | None) -> bool:
        if limit is None:
            return False
        return value > limit if band.rising else value < limit

    if beyond(band.alarm):
        return Alarm(kind, True, Level.ALARM, value, band.alarm)
    if beyond(band.warning):
        return Alarm(kind, True, Level.WARNING, value, band.warning)
    if previous is not None and previous.active and band.warning is not None:
        release = band.warning - band.hysteresis if band.rising else band.warning + band.hysteresis
        still = value > release if band.rising else value < release
        if still:
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
) -> Alarm:
    """Complete burns shorter than ``shortest_s`` in the last day — flame lost soon after
    ignition — above ``limit``."""
    count = sum(
        1
        for b in burns
        if b.burn.complete and b.burn.duration < shortest_s and now - 86400.0 <= b.burn.start < now
    )
    return Alarm(
        AlarmKind.UNSTABLE_IGNITION,
        count > limit,
        Level.WARNING if count > limit else None,
        float(count),
        float(limit),
    )


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




def low_flow(
    zones: Sequence[ZoneState],
    pump_running: bool | None,
    now: float,
    max_age: float | None,
) -> Alarm:
    """Warning while the pump runs and every zone's valve is closed: no path for the water.

    Only zones with a fresh, known valve opening count; a zone without one (e.g. a relay) could be
    the open path, so it keeps the warning off. ``pump_running`` comes from a pump-running or a
    CH-active signal; without either the warning cannot be judged (``None``).
    """
    kind = AlarmKind.LOW_FLOW
    if pump_running is None:
        return Alarm(kind, False)
    fresh = [z for z in zones if z.is_fresh(now, max_age)]
    if not fresh or any(z.valve_open is None for z in fresh):
        return Alarm(kind, False)
    widest = max(z.valve_open for z in fresh if z.valve_open is not None)
    active = pump_running and widest <= ZONE_OPEN
    return Alarm(kind, active, Level.WARNING if active else None, widest, ZONE_OPEN)
