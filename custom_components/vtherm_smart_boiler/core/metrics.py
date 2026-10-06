"""Boiler metrics: starts, burn times, condensing, degree-days, gas — with their data basis.

Every metric says how much known data it rests on, so a gap is never mistaken for a quiet boiler.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from .cycles import Burn, BurnKind, ClassifiedBurn
from .series import Series, known_duration

HOUR = 3600.0
DAY = 86400.0

CH_KINDS = frozenset({BurnKind.CH})  # burns known to heat the rooms
DHW_KINDS = frozenset({BurnKind.DHW})
UNKNOWN_KINDS = frozenset({BurnKind.UNKNOWN})  # counted apart: it may have been hot water
NOT_DHW_KINDS = CH_KINDS | UNKNOWN_KINDS  # energy and gas not known to be hot water
DEFAULT_SHORT_BURN_S = 10 * 60.0
DEFAULT_CONDENSING_RETURN = 55.0
MIN_DEGREE_DAYS = 0.5  # below this, gas per degree-day means nothing


def _percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """Nearest-rank percentile of already sorted values."""
    rank = max(1, math.ceil(fraction * len(sorted_values)))
    return sorted_values[rank - 1]


@dataclass(frozen=True, slots=True)
class CycleStats:
    """Starts and burn times over ``observed_s`` seconds of known flame state; ``active_s`` is
    the time in the clock hours with a burn of these kinds."""

    observed_s: float
    starts: int
    complete_burns: int
    burn_s: float
    median_burn_s: float | None
    p10_burn_s: float | None
    p90_burn_s: float | None
    short_burns: int
    active_s: float | None = None

    @property
    def starts_per_hour(self) -> float | None:
        """Starts per hour of heating: idle hours would dilute short-cycling into calm."""
        basis = self.observed_s if self.active_s is None else self.active_s
        return self.starts / (basis / HOUR) if basis > 0 else None

    @property
    def short_burn_share(self) -> float | None:
        return self.short_burns / self.complete_burns if self.complete_burns else None


def cycle_stats(
    burns: Iterable[ClassifiedBurn],
    observed_s: float,
    kinds: frozenset[BurnKind] = CH_KINDS,
    short_burn_s: float = DEFAULT_SHORT_BURN_S,
    window: tuple[float, float] | None = None,
) -> CycleStats:
    """Starts and burn-time distribution of the burns of ``kinds``.

    ``observed_s`` is the time with the flame state known, e.g. from ``known_duration``.
    Burn times use complete burns only; a burn cut by the window or a gap is too short. With
    ``window``, a burn counts — its start, its length — in the window that holds its start,
    and its burn time only within the window: a burn across midnight found whole is one burn of
    the day it started in, its time split at midnight (P-83).
    """
    low, high = window if window is not None else (-math.inf, math.inf)
    selected = [b.burn for b in burns if b.kind in kinds]
    own = [b for b in selected if low <= b.start < high]
    durations = sorted(b.duration for b in own if b.complete)
    return CycleStats(
        observed_s=observed_s,
        starts=sum(1 for b in own if b.start_seen),
        complete_burns=len(durations),
        burn_s=sum(max(0.0, min(b.end, high) - max(b.start, low)) for b in selected),
        median_burn_s=_percentile(durations, 0.5) if durations else None,
        p10_burn_s=_percentile(durations, 0.1) if durations else None,
        p90_burn_s=_percentile(durations, 0.9) if durations else None,
        short_burns=sum(1 for d in durations if d < short_burn_s),
        active_s=hours_with(selected, window),
    )


def hours_with(burns: Iterable[Burn], window: tuple[float, float] | None = None) -> float:
    """The time in the clock hours that hold any of these burns — within ``window``, when an
    hour is cut by it."""
    hours: set[int] = set()
    for burn in burns:
        if burn.end > burn.start:
            hours.update(range(math.floor(burn.start / HOUR), math.ceil(burn.end / HOUR)))
    low, high = window if window is not None else (-math.inf, math.inf)
    return sum(max(0.0, min((hour + 1) * HOUR, high) - max(hour * HOUR, low)) for hour in hours)


@dataclass(frozen=True, slots=True)
class Share:
    """A fraction of ``basis_s`` seconds; ``None`` without any basis."""

    value: float | None
    basis_s: float


def condensing_share(
    return_temp: Series[float],
    burns: Iterable[ClassifiedBurn],
    threshold: float = DEFAULT_CONDENSING_RETURN,
    kinds: frozenset[BurnKind] = CH_KINDS,
    window: tuple[float, float] | None = None,
) -> Share:
    """Share of burn time with the return below ``threshold`` (where the return is known);
    with ``window``, only the burn time within it (P-83)."""
    low, high = window if window is not None else (-math.inf, math.inf)
    basis = 0.0
    below = 0.0
    for classified in burns:
        if classified.kind not in kinds:
            continue
        burn = classified.burn
        for segment in return_temp.segments(max(burn.start, low), min(burn.end, high)):
            if segment.value is None:
                continue
            basis += segment.duration
            if segment.value < threshold:
                below += segment.duration
    return Share(below / basis if basis > 0 else None, basis)


@dataclass(frozen=True, slots=True)
class DegreeDays:
    """Heating degree-days (K·day) over the known part of a window."""

    value: float
    known_s: float
    window_s: float

    @property
    def coverage(self) -> float:
        return self.known_s / self.window_s if self.window_s > 0 else 0.0

    def estimated_total(self, min_coverage: float = 0.8) -> float | None:
        """Degree-days for the whole window, scaled from the known part if it covers enough."""
        if self.coverage < min_coverage or self.known_s <= 0:
            return None
        return self.value * self.window_s / self.known_s


def degree_days(outdoor: Series[float], base: float, start: float, end: float) -> DegreeDays:
    """Time integral of ``max(0, base − outdoor)``, in K·day."""
    total = 0.0
    known = 0.0
    for segment in outdoor.segments(start, end):
        if segment.value is None:
            continue
        known += segment.duration
        total += max(0.0, base - segment.value) * segment.duration
    return DegreeDays(total / DAY, known, max(0.0, end - start))


@dataclass(frozen=True, slots=True)
class Consumption:
    """An amount (gas in the meter's unit, or energy) and whether it covers the whole window."""

    amount: float
    complete: bool


# A reading below 90 % of the mark is a meter restarted from zero, as Home Assistant takes a
# total_increasing sensor (PB-19): a daily meter or a "today" sensor read hourly, or a reset
# first seen hours later, reads well above a tenth of the old value. A smaller step back is a
# correction.
METER_RESET_FRACTION = 0.9


def meter_rise(high: float | None, value: float) -> tuple[float, float]:
    """What a new reading of a cumulative meter adds, and the highest reading since (P-97): one
    rule for the consumption and its split alike. Above the highest reading so far (``high``;
    ``None`` before the first), the difference counts; a small step back — rounding, a
    correction under a tenth — counts nothing, and neither does the way back up to the mark (it
    was counted once already); a reading below 90 % of the mark is a meter restarted from zero,
    counted from zero (PB-19)."""
    if high is None:
        return 0.0, value
    if high > 0 and value < METER_RESET_FRACTION * high:
        return max(0.0, value), value  # counted from zero since the reset
    if value > high:
        return value - high, value
    return 0.0, high


def meter_consumption(meter: Series[float], start: float, end: float) -> Consumption | None:
    """Consumption from a cumulative meter in ``[start, end)``, reading by reading
    (``meter_rise``: only a rise above the highest reading counts; a drop to under 90 % of it
    is a reset to zero — adding a whole reading would count years of gas at once).

    The meter keeps counting through a gap in the data, so known values on both sides of a gap
    still give the consumption in between. Complete when the meter is known at both ends of the
    window; ``None`` when it is never known.
    """
    segments = list(meter.segments(start, end))
    known = [segment.value for segment in segments if segment.value is not None]
    if not known:
        return None
    amount = 0.0
    high: float | None = None
    for value in known:
        rise, high = meter_rise(high, value)
        amount += rise
    complete = segments[0].value is not None and segments[-1].value is not None
    return Consumption(amount, complete)


class ModulationScale(StrEnum):
    """What the boiler's modulation percentage means."""

    RANGE = "range"  # 0 % is minimum power, 100 % maximum (OpenTherm definition)
    CAPACITY = "capacity"  # percent of maximum power


def rate_at(modulation: float, at_min: float, at_max: float, scale: ModulationScale) -> float:
    """Gas or power rate at a modulation level, between its minimum and maximum."""
    fraction = min(100.0, max(0.0, modulation)) / 100.0
    if scale is ModulationScale.RANGE:
        return at_min + fraction * (at_max - at_min)
    return max(at_min, fraction * at_max)


def integrate_rate(
    flame: Series[bool],
    modulation: Series[float],
    at_min: float,
    at_max: float,
    scale: ModulationScale,
    start: float,
    end: float,
) -> Consumption:
    """Integral of a per-hour rate while the flame burns (gas or heat output estimate).

    Complete when the modulation is known for all of the burn time.
    """
    amount = 0.0
    unknown = False
    for segment in flame.segments(start, end):
        if segment.value is None:
            unknown = True
            continue
        if not segment.value:
            continue
        for part in modulation.segments(segment.start, segment.end):
            if part.value is None:
                unknown = True
                continue
            amount += rate_at(part.value, at_min, at_max, scale) * part.duration / HOUR
    return Consumption(amount, not unknown)


def per_degree_day(amount: float, days: DegreeDays) -> float | None:
    total = days.estimated_total()
    if total is None or total < MIN_DEGREE_DAYS:
        return None
    return amount / total


@dataclass(frozen=True, slots=True)
class OutdoorBin:
    """Time with the outdoor temperature in ``[low, low + width)``."""

    low: float
    width: float
    intervals: tuple[tuple[float, float], ...]


def outdoor_bins(
    outdoor: Series[float], start: float, end: float, width: float = 5.0
) -> list[OutdoorBin]:
    """Split the known outdoor time of ``[start, end)`` into temperature bins."""
    grouped: dict[float, list[tuple[float, float]]] = {}
    for segment in outdoor.segments(start, end):
        if segment.value is None:
            continue
        low = math.floor(segment.value / width) * width
        grouped.setdefault(low, []).append((segment.start, segment.end))
    return [OutdoorBin(low, width, tuple(grouped[low])) for low in sorted(grouped)]


def binned_cycle_stats(
    burns: Sequence[ClassifiedBurn],
    flame: Series[bool],
    outdoor: Series[float],
    start: float,
    end: float,
    width: float = 5.0,
    kinds: frozenset[BurnKind] = CH_KINDS,
    short_burn_s: float = DEFAULT_SHORT_BURN_S,
) -> dict[float, CycleStats]:
    """Cycle statistics per outdoor-temperature bin; a burn belongs to the bin of its start."""
    result: dict[float, CycleStats] = {}
    for bin_ in outdoor_bins(outdoor, start, end, width):
        observed = sum(known_duration(flame, a, b) for a, b in bin_.intervals)
        inside = [b for b in burns if _in_intervals(b.burn, bin_.intervals)]
        result[bin_.low] = cycle_stats(inside, observed, kinds, short_burn_s)
    return result


def _in_intervals(burn: Burn, intervals: Iterable[tuple[float, float]]) -> bool:
    return any(a <= burn.start < b for a, b in intervals)
