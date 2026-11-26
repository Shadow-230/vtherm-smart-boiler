"""Principle 13's rules 3 and 5 for the comfort correction (decision 11 of plan 0.2.3, SB-11).

**Rule 3 — it moves only while cycling does not rise.** The correction rises only while the
boiler's heating starts since it began are no more than in the same hours before it began, and
steps back — falls at its fall rate — while they are more. The hours compared grow from its
beginning up to ``STARTS_WINDOW_S``; after that the last hours count against the same hours
before it began. Equal spans, so counts compare as starts per hour. Its beginning — the first
rise from 0 — and the starts before it are kept until the correction has stayed at 0 for the
window: a rise after a step back to 0 is judged against the same hours as before, never against
hours the correction itself made busier. A start is a burn seen to begin; hot-water draws are
left out and a burn of unknown kind counts, in both windows alike. With the starts unknown it
does not rise.

**Rule 5 — it does not rise in extreme weather**: the outdoor reading below the curve's design
outdoor temperature, or changing faster than ``EXTREME_RATE_K_PER_H`` — more than that spread
within the last hour of readings. With the reading unknown, or less than an hour of readings to
judge the rate by, it does not rise either. Every fall passes — the rooms satisfied or too warm,
rule 3's step back: a fast outdoor rise (sun on the sensor, a warm front) or a long outage must
not hold the water up while rooms overshoot (M1 of the part-2 check, the cautious side).

**The pace (I13.3).** The correction is a slow loop above the rooms' own controllers, and must be
several times slower than they are (mid-ranging and valve-position control: Skogestad 2023, at
least 4 times; Hägglund 2021). A room counts as short (``held_short``) only once it has been fully
open and short for ``HELD_CYCLES`` of its own cycles, and at least ``HELD_S``, without a break; the
rise takes at least ``RISE_CYCLES`` cycles of the slowest room it judges per kelvin
(``rise_seconds``), and never less than the controller's 30 minutes. A room's cycle not known
counts as ``DEFAULT_CYCLE_S``. No rise while a room warms back after its setpoint was raised — a
morning setback's recovery — judged by the window rule's "still warming" test
(``follow_raise``, ``core.critical_zone.still_warming``).

**The trim (I13.3).** Below the curve the correction trims the water, at most ``TRIM_MAX_K``, at
``trim_seconds`` of heat flow per kelvin — at least ``TRIM_S`` and twice the rise's —, and at most
``TRIM_DAY_K`` within a day, while every room it judges is clearly satisfied (valve-driven reset:
Boegli et al. 2022; ASHRAE Guideline 36's trim and respond). Rule 3 holds both ways: the correction
moves away from 0 — up or down — only while the starts do not rise, and steps back towards 0 while
they do; rule 5 likewise: no deeper trim in extreme weather.

The values are provisional, K4.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from .critical_zone import RoomReadings, keep_readings, still_warming
from .cycles import BurnKind, ClassifiedBurn

HOUR = 3600.0
# Rule 3: the most hours compared, and how long the correction stays at 0 before a new beginning
# takes new hours to compare with (provisional, K4).
STARTS_WINDOW_S = 2 * HOUR
# Rule 5: extreme weather — the outdoor reading changing faster than this, judged over the last
# hour of readings, one kept per ``OUTDOOR_SAMPLE_S`` (provisional, K4: a ±3 K daily swing
# changes about 0.8 K per hour at most; a passing front changes faster).
EXTREME_RATE_K_PER_H = 2.0
OUTDOOR_WINDOW_S = HOUR
OUTDOOR_SAMPLE_S = 300.0

# I13.3, the pace (provisional, K4): a room short this many of its own cycles, and this long at
# least, counts; the rise takes this many cycles of the slowest room per kelvin at the fastest; a
# cycle not known counts as 15 min — the cycle the plugin advises for rooms that call a boiler,
# three times VT's default 5 min, so the slower side.
HELD_CYCLES = 2
HELD_S = HOUR
RISE_CYCLES = 4
DEFAULT_CYCLE_S = 15 * 60.0
# I13.3, the trim below the curve (provisional, K4): at most this deep; this much heat flow per
# kelvin at the fastest, and never faster than half the rise's rate; at most this much a day.
TRIM_MAX_K = 3.0
TRIM_S = 2 * HOUR
TRIM_DAY_K = 3.0

Readings = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class RoomPace:
    """What the correction's pace keeps of one room (I13.3): since when it has been fully open and
    short without a break (``None``: it is not), its last known setpoint, since when it warms back
    after that setpoint was raised (``None``: it does not), and its recent readings."""

    short_since: float | None = None
    target: float | None = None
    raised_at: float | None = None
    readings: RoomReadings = ()


def follow_raise(
    raised_at: float | None,
    previous_target: float | None,
    target: float | None,
    now: float,
    readings: RoomReadings,
    temperature: float | None,
) -> float | None:
    """Since when a room warms back after its setpoint was raised — the setpoint above the last
    one known —, as long as it is still warming (``still_warming``: the window rule's test); a
    clock set back counts from now (C9). ``None``: it does not."""
    if previous_target is not None and target is not None and target > previous_target:
        raised_at = now
    if raised_at is None:
        return None
    raised_at = min(raised_at, now)
    return raised_at if still_warming(raised_at, now, readings, temperature, target) else None


def follow_room(
    previous: RoomPace, now: float, short: bool, temperature: float | None, target: float | None
) -> RoomPace:
    """A room's pace after a look at ``now``: ``short`` — fully open and short now — continues its
    run or starts one, anything else breaks it; its readings kept; a raised setpoint followed."""
    readings = keep_readings(previous.readings, now, temperature)
    since = previous.short_since
    if not short:
        since = None
    elif since is None or since > now:
        since = now  # a new run, or a clock set back (C9)
    raised = follow_raise(previous.raised_at, previous.target, target, now, readings, temperature)
    kept = target if target is not None else previous.target
    return RoomPace(since, kept, raised, readings)


def cycle_of(cycle_s: float | None) -> float:
    """A room's cycle, ``DEFAULT_CYCLE_S`` where not known."""
    return DEFAULT_CYCLE_S if cycle_s is None else cycle_s


def held_short(pace: RoomPace, now: float, cycle_s: float | None) -> bool:
    """The room has been fully open and short for ``HELD_CYCLES`` of its cycles and ``HELD_S``
    at least, without a break."""
    since = pace.short_since
    if since is None:
        return False
    return now - since >= max(HELD_CYCLES * cycle_of(cycle_s), HELD_S)


def counted_for(pace: RoomPace, now: float, cycle_s: float | None) -> float:
    """How long the room has counted as short (``held_short``): 0 until it does — so the heat
    of a decision interval that began before it counts only from then."""
    since = pace.short_since
    if since is None:
        return 0.0
    return max(0.0, now - since - max(HELD_CYCLES * cycle_of(cycle_s), HELD_S))


def rise_seconds(cycles: Iterable[float | None], fastest_s: float) -> float:
    """Heat flow per kelvin of rise: ``RISE_CYCLES`` cycles of the slowest room judged, never less
    than ``fastest_s``; a cycle not known counts as ``DEFAULT_CYCLE_S``, no room as one."""
    slowest = max((cycle_of(c) for c in cycles), default=DEFAULT_CYCLE_S)
    return max(fastest_s, RISE_CYCLES * slowest)


def trim_seconds(rise_s: float) -> float:
    """Heat flow per kelvin of trim: twice the rise's, ``TRIM_S`` at least — always slower."""
    return max(TRIM_S, 2.0 * rise_s)


@dataclass(frozen=True, slots=True)
class StartsBaseline:
    """Rule 3's reference: when the correction began to move from 0 — up, or down (I13.3) —, the
    heating starts within ``STARTS_WINDOW_S`` before it, and since when it has been back at 0
    (``None``: it is not)."""

    began: float
    before: tuple[float, ...]
    zero_since: float | None = None


def heating_starts(
    burns: Iterable[ClassifiedBurn], now: float, window_s: float = STARTS_WINDOW_S
) -> tuple[float, ...]:
    """The heating starts within ``window_s`` up to ``now``: each burn seen to begin, but a
    hot-water draw."""
    return tuple(
        sorted(
            b.burn.start
            for b in burns
            if b.burn.start_seen
            and b.kind is not BurnKind.DHW
            and 0.0 <= now - b.burn.start <= window_s
        )
    )


def starts_rose(
    baseline: StartsBaseline, starts: Sequence[float], now: float, window_s: float = STARTS_WINDOW_S
) -> bool:
    """More starts since the correction began — the last ``window_s`` at most — than in the same
    hours before it began. Nothing to compare at its beginning or before it (a clock set back)."""
    span = min(now - baseline.began, window_s)
    if span <= 0.0:
        return False
    after = sum(1 for t in starts if now - span <= t <= now)
    before = sum(1 for t in baseline.before if baseline.began - span <= t < baseline.began)
    return after > before


def may_rise(
    baseline: StartsBaseline | None,
    starts: Sequence[float] | None,
    now: float,
    window_s: float = STARTS_WINDOW_S,
) -> bool:
    """Rule 3 lets the correction move away from 0 — rise, or trim below the curve (I13.3): its
    starts known, the clock not before its beginning, and the starts not risen. Its first move
    has nothing to compare yet."""
    if starts is None:
        return False
    if baseline is None:
        return True
    return now >= baseline.began and not starts_rose(baseline, starts, now, window_s)


def follow_baseline(
    baseline: StartsBaseline | None,
    correction: float,
    now: float,
    window_s: float = STARTS_WINDOW_S,
) -> StartsBaseline | None:
    """The baseline at a water decision, before the correction moves: kept while the correction
    is away from 0 — above it, or below it (I13.3); at 0 counted from the decision that finds it
    there — or from a clock set back — and dropped once at 0 for ``window_s``."""
    if baseline is None:
        return None
    if correction != 0.0:
        return replace(baseline, zero_since=None)
    since = baseline.zero_since
    if since is None or since > now:
        since = now
    if now - since >= window_s:
        return None
    return replace(baseline, zero_since=since)


def follow_outdoor(seen: Readings, reading: float | None, now: float) -> Readings:
    """The outdoor readings rule 5 judges by: one per ``OUTDOOR_SAMPLE_S``, those within the
    last hour and the newest one before it — which shows the hour is covered — none older than
    two hours, none after ``now`` (a clock set back)."""
    kept = [(t, v) for t, v in seen if 0.0 <= now - t <= 2 * OUTDOOR_WINDOW_S]
    older = [s for s in kept if now - s[0] > OUTDOOR_WINDOW_S]
    kept = older[-1:] + [s for s in kept if now - s[0] <= OUTDOOR_WINDOW_S]
    if reading is not None and (not kept or now - kept[-1][0] >= OUTDOOR_SAMPLE_S):
        kept.append((now, reading))
    return tuple(kept)


def extreme_weather(
    seen: Readings, reading: float | None, now: float, design_outdoor: float
) -> bool:
    """Rule 5: the correction does not rise — the reading unknown or below the design outdoor
    temperature, less than an hour of readings, or a spread above ``EXTREME_RATE_K_PER_H`` within
    the last hour (a rise counts as a fall does)."""
    if reading is None or reading < design_outdoor:
        return True
    if not seen or now - seen[0][0] < OUTDOOR_WINDOW_S:
        return True
    values = [v for t, v in seen if now - t <= OUTDOOR_WINDOW_S]
    values.append(reading)
    return max(values) - min(values) > EXTREME_RATE_K_PER_H * OUTDOOR_WINDOW_S / HOUR
