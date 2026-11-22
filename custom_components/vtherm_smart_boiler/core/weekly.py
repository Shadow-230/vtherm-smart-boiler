"""Gas per degree-day week by week, for the Boiler page's Use tab
(``docs/en/development/plans/plan-0.2-i10.md``, I10.5).

Weeks are seven-day blocks counted back from the end of the newest daily summary. A week's gas is
known only where all seven of its days have theirs — gas known for part of a week over the
degree-days of all of it would read too little, the monitor's own rule (``core.monitor``) — and
likewise its degree-days; its gas per degree-day only at ``MIN_DEGREE_DAYS`` or more.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .daily import DaySummary
from .metrics import MIN_DEGREE_DAYS

DAY = 86400.0
WEEK = 7 * DAY
DAYS_IN_WEEK = 7


@dataclass(frozen=True, slots=True)
class WeekUse:
    start: float
    end: float
    days: int  # daily summaries within it
    gas: float | None
    degree_days: float | None
    per_degree_day: float | None


def weekly_use(days: Iterable[DaySummary], weeks: int) -> tuple[WeekUse, ...]:
    """Up to ``weeks`` weeks, oldest first, back to the oldest summary."""
    ordered = sorted(days, key=lambda day: day.start)
    if not ordered:
        return ()
    newest_end = ordered[-1].end
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
        per_degree_day = (
            gas / degree_days
            if gas is not None and degree_days is not None and degree_days >= MIN_DEGREE_DAYS
            else None
        )
        out.append(WeekUse(start, end, len(inside), gas, degree_days, per_degree_day))
    return tuple(reversed(out))
