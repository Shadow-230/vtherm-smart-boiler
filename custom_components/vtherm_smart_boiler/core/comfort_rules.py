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

**Rule 5 — it freezes in extreme weather**, neither rising nor falling: the outdoor reading
below the curve's design outdoor temperature, or changing faster than ``EXTREME_RATE_K_PER_H``
— more than that spread within the last hour of readings. With the reading unknown, or less than
an hour of readings to judge the rate by, it freezes too.

The values are provisional, K4.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

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

Readings = tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class StartsBaseline:
    """Rule 3's reference: when the correction began to rise from 0, the heating starts within
    ``STARTS_WINDOW_S`` before it, and since when it has been back at 0 (``None``: it is not)."""

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
    """Rule 3 lets the correction rise: its starts known, the clock not before its beginning,
    and the starts not risen. Its first rise has nothing to compare yet."""
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
    is above 0; at 0 counted from the decision that finds it there — or from a clock set back —
    and dropped once at 0 for ``window_s``."""
    if baseline is None:
        return None
    if correction > 0.0:
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
    """Rule 5: the correction freezes — the reading unknown or below the design outdoor
    temperature, less than an hour of readings, or a spread above ``EXTREME_RATE_K_PER_H`` within
    the last hour (a rise counts as a fall does)."""
    if reading is None or reading < design_outdoor:
        return True
    if not seen or now - seen[0][0] < OUTDOOR_WINDOW_S:
        return True
    values = [v for t, v in seen if now - t <= OUTDOOR_WINDOW_S]
    values.append(reading)
    return max(values) - min(values) > EXTREME_RATE_K_PER_H * OUTDOOR_WINDOW_S / HOUR
