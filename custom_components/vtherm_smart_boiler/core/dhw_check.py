"""The hot-water self-check (I13.5): does the gas classed as hot water follow the weather?

Hot water is used about the same through the year; heating follows the outdoor temperature
(Phillips and Wilson 2024: hot water roughly flat, space heating most of a boiler's gas). Colder
mains water in winter raises hot water's gas a little — about a third more from summer to winter,
1 to 1.5 % per kelvin over a year's outdoor range. A clear slope of the daily hot-water gas on the
daily mean outdoor temperature therefore says the split is wrong: heating burns counted as hot
water (the slope falls), or hot water counted as heating in cold weather (it rises) — and the
heat loss and the gas per degree-day take the same error. Information only: nothing changes in
control.

The test: a line through the kept days' hot-water gas (per 24 hours) against their mean outdoor
temperature, over ``MIN_DAYS`` days or more spread over ``MIN_OUTDOOR_SPREAD_K`` or more. A slope
is clear when it is at least ``MIN_T`` standard errors from zero — widened for days that follow
each other (``core.regression``) — and at least ``MIN_SLOPE_SHARE`` of the days' mean hot-water
gas per kelvin, twice what colder mains water explains (provisional, K4).
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise
from typing import cast

from .building import MIN_OUTDOOR_SPREAD_K, NEXT_DAY_S
from .daily import DAY, FIT_COVERAGE, DaySummary
from .regression import Line, fit_line

MIN_DAYS = 28
MIN_T = 3.0
MIN_SLOPE_SHARE = 0.03  # of the mean hot-water gas, per kelvin


@dataclass(frozen=True, slots=True)
class DhwCheck:
    days: int
    slope_share: float  # the change per kelvin warmer, as a share of the mean: −0.05 is −5 %/K
    t: float  # the slope in its standard errors
    suspect: bool  # a clear slope: the split looks wrong


def check_dhw_split(days: Iterable[DaySummary]) -> DhwCheck | None:
    """The check over ``days``; ``None`` where they cannot carry it — too few, too little
    spread of outdoor temperature, or no hot-water gas at all."""
    points = sorted(
        (
            day
            for day in days
            if day.dhw_gas is not None
            and day.outdoor_mean is not None
            and day.end > day.start
            and day.observed_s >= FIT_COVERAGE * (day.end - day.start)
        ),
        key=lambda day: day.start,
    )
    if len(points) < MIN_DAYS:
        return None
    xs = [day.outdoor_mean or 0.0 for day in points]
    ys = [(day.dhw_gas or 0.0) * DAY / (day.end - day.start) for day in points]
    mean = sum(ys) / len(ys)
    if max(xs) - min(xs) < MIN_OUTDOOR_SPREAD_K or mean <= 0:
        return None
    adjacent = [after.start - before.start <= NEXT_DAY_S for before, after in pairwise(points)]
    # 28 days over 8 K or more: a spread, so a line.
    line = cast(Line, fit_line(xs, ys, adjacent))
    error = line.slope_error
    if error > 0:
        t = line.slope / error
    else:  # days exactly on a line: a slope is as clear as can be, none is none
        t = math.copysign(math.inf, line.slope) if line.slope else 0.0
    share = line.slope / mean
    return DhwCheck(len(points), share, t, abs(t) >= MIN_T and abs(share) >= MIN_SLOPE_SHARE)
