"""Gas per degree-day week by week, for the Boiler page's Use tab
(``docs/en/development/plans/plan-0.2-i10.md``, I10.5).

Weeks are seven-day blocks counted back from the end of the newest daily summary. A week's gas is
known only where all seven of its days have theirs — gas known for part of a week over the
degree-days of all of it would read too little, the monitor's own rule (``core.monitor``) — and
likewise its degree-days; its gas per degree-day only at ``MIN_WEEK_DEGREE_DAYS`` or more (I13.5),
with a band from the house's own day-to-day scatter around its energy signature, where it has
one (Phillips and Wilson 2024).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

from .daily import DaySummary
from .regression import Line

DAY = 86400.0
WEEK = 7 * DAY
DAYS_IN_WEEK = 7
# I13.5: a week's gas per degree-day is shown from 14 K·day on — the days 2 K below the heating
# threshold on average. The threshold in use may be off by about 2 K (the plugin's tolerance for
# it, and its fit's standard-error cap), which moves a week's degree-days by up to 14 K·day:
# below that, the error could be as large as the degree-days themselves, and the figure would
# say more about the threshold than about the house. The cautious side: a mild week shows none.
MIN_WEEK_DEGREE_DAYS = 14.0


@dataclass(frozen=True, slots=True)
class WeekUse:
    start: float
    end: float
    days: int  # daily summaries within it
    gas: float | None
    degree_days: float | None
    per_degree_day: float | None
    # I13.5: where the week's gas per degree-day likely lies (95 %), from the house's own
    # day-to-day scatter; ``None`` without a signature line to take it from.
    low: float | None = None
    high: float | None = None


def week_spread(scatter: Line) -> float:
    """I13.5: the standard deviation of a week's gas — seven days scattering as the signature's
    days do around its line, each correlated with the day before by the line's ``rho``."""
    rho = scatter.rho
    pairs = sum((DAYS_IN_WEEK - lag) * rho**lag for lag in range(1, DAYS_IN_WEEK))
    return scatter.deviation * math.sqrt(DAYS_IN_WEEK + 2 * pairs)


def weekly_use(
    days: Iterable[DaySummary], weeks: int, scatter: Line | None = None
) -> tuple[WeekUse, ...]:
    """Up to ``weeks`` weeks, oldest first, back to the oldest summary; ``scatter``: the
    house's signature line (``core.signature``), whose scatter gives each week's band."""
    ordered = sorted(days, key=lambda day: day.start)
    if not ordered:
        return ()
    newest_end = ordered[-1].end
    half_gas = None if scatter is None else scatter.t * week_spread(scatter)
    out: list[WeekUse] = []
    for k in range(weeks):
        end = newest_end - k * WEEK
        start = end - WEEK
        if end <= ordered[0].start:
            break
        inside = [day for day in ordered if start <= day.start < end]
        whole = len(inside) == DAYS_IN_WEEK
        gas = (
            sum(day.gas for day in inside if day.gas is not None)
            if whole and all(day.gas is not None for day in inside)
            else None
        )
        degree_days = (
            sum(day.degree_days for day in inside if day.degree_days is not None)
            if whole and all(day.degree_days is not None for day in inside)
            else None
        )
        if gas is None or degree_days is None or degree_days < MIN_WEEK_DEGREE_DAYS:
            out.append(WeekUse(start, end, len(inside), gas, degree_days, None))
            continue
        per_degree_day = gas / degree_days
        low = high = None
        if half_gas is not None and math.isfinite(half_gas):
            low = max(0.0, (gas - half_gas) / degree_days)
            high = (gas + half_gas) / degree_days
        out.append(WeekUse(start, end, len(inside), gas, degree_days, per_degree_day, low, high))
    return tuple(reversed(out))
