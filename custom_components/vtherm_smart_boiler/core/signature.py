"""The energy signature, for the Boiler page's Analyses tab
(``docs/en/development/plans/plan-0.2-i10.md``, I10.7): each day's heating gas against its mean
outdoor temperature, the days the plugin only watched and the days under control apart.

A day is shown where its gas and its outdoor mean are known and most of it was seen (the
building fit's coverage), its gas per 24 hours so a day of 23 or 25 hours compares. Each group
gets a straight line through its heating days — colder than the heating threshold in use, with
heating gas — by the building fit's own rules (``core.building``): enough days, enough spread of
outdoor temperature, more gas on colder days, and a fit close enough; otherwise no line, and why.
Where both lines exist and their temperatures overlap, they are compared in the middle of the
overlap: how much more or less gas a day under control took there — each line's value with its
95 % range, widened for correlated days (``core.regression``, I13.4), and the change with its
range. Where the two ranges overlap, no difference is shown: daily signatures with correlated
days give ranges too narrow otherwise (Gondian and Thiery 2026), and the independent evidence of
control savings is weak (Lomas et al. 2018).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from itertools import pairwise
from typing import cast

from .building import MIN_FIT_DAYS, MIN_OUTDOOR_SPREAD_K, MIN_QUALITY, NEXT_DAY_S
from .daily import DAY, FIT_COVERAGE, DaySummary
from .regression import Line, fit_line


class NoLine(StrEnum):
    TOO_FEW_DAYS = "too_few_days"
    TOO_LITTLE_SPREAD = "too_little_spread"
    NOT_HEATING = "not_heating"  # no more gas on colder days
    TOO_SCATTERED = "too_scattered"


@dataclass(frozen=True, slots=True)
class SignatureDay:
    start: float
    outdoor: float  # the day's mean outdoor temperature, °C
    gas: float  # heating gas per 24 hours, in the meter's unit
    controlled: bool  # under control for an hour or more (``DaySummary.under_control``)
    fitted: bool  # a heating day its group's line uses


@dataclass(frozen=True, slots=True)
class SignatureLine:
    slope: float  # gas per K
    intercept: float  # gas at 0 °C
    low: float  # the outdoor temperatures it was fitted over, °C
    high: float
    days: int
    r_squared: float

    def at(self, outdoor: float) -> float:
        return self.intercept + self.slope * outdoor

    @property
    def balance(self) -> float:
        """Where the heating gas reaches nothing, °C."""
        return -self.intercept / self.slope


@dataclass(frozen=True, slots=True)
class SignatureFit:
    line: SignatureLine | None
    reason: NoLine | None  # why there is no line
    # The fit behind the line, for its ranges (I13.4); not shown itself.
    fitted: Line | None = None


@dataclass(frozen=True, slots=True)
class Comparison:
    outdoor: float  # °C, the middle of the temperatures both lines were fitted over
    observing: float  # gas per day there, watched
    control: float  # gas per day there, under control
    change: float  # control against watched: -0.1 is 10 % less
    # I13.4: each line's 95 % range there, and the change's from them (``None``: the watched
    # range reaches zero, so the change could be anything); ``shown``: the two ranges do not
    # overlap — a difference the days show.
    observing_low: float
    observing_high: float
    control_low: float
    control_high: float
    change_low: float | None
    change_high: float | None
    shown: bool


@dataclass(frozen=True, slots=True)
class Signature:
    days: tuple[SignatureDay, ...]
    observing: SignatureFit
    control: SignatureFit
    comparison: Comparison | None


def energy_signature(days: Iterable[DaySummary], threshold: float | None) -> Signature:
    """The signature of ``days``; ``threshold``: the heating threshold in use, °C (``None``:
    every day with heating gas is a heating day)."""
    shown: list[SignatureDay] = []
    for day in sorted(days, key=lambda d: d.start):
        length = day.end - day.start
        if (
            day.gas is None
            or day.outdoor_mean is None
            or length <= 0
            or day.observed_s < FIT_COVERAGE * length
        ):
            continue
        gas = day.gas * DAY / length
        heating = gas > 0 and (threshold is None or day.outdoor_mean < threshold)
        shown.append(SignatureDay(day.start, day.outdoor_mean, gas, day.under_control, heating))
    observing = _fit([d for d in shown if d.fitted and not d.controlled])
    control = _fit([d for d in shown if d.fitted and d.controlled])
    return Signature(tuple(shown), observing, control, _compare(observing, control))


def _fit(days: list[SignatureDay]) -> SignatureFit:
    """The line through ``days`` (in time order), or why there is none."""
    if len(days) < MIN_FIT_DAYS:
        return SignatureFit(None, NoLine.TOO_FEW_DAYS)
    xs = [d.outdoor for d in days]
    ys = [d.gas for d in days]
    if max(xs) - min(xs) < MIN_OUTDOOR_SPREAD_K:
        return SignatureFit(None, NoLine.TOO_LITTLE_SPREAD)
    adjacent = [after.start - before.start <= NEXT_DAY_S for before, after in pairwise(days)]
    # Seven days over 8 K or more: a spread, so a line.
    fitted = cast(Line, fit_line(xs, ys, adjacent))
    if fitted.slope >= 0:
        return SignatureFit(None, NoLine.NOT_HEATING)
    mean_y = sum(ys) / len(ys)
    # A falling line means the gas varies: ``total`` is above zero.
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum((y - fitted.at(x)) ** 2 for x, y in zip(xs, ys, strict=True))
    r_squared = 1.0 - residual / total
    if r_squared < MIN_QUALITY:
        return SignatureFit(None, NoLine.TOO_SCATTERED)
    line = SignatureLine(fitted.slope, fitted.intercept, min(xs), max(xs), fitted.n, r_squared)
    return SignatureFit(line, None, fitted)


def _compare(observing: SignatureFit, control: SignatureFit) -> Comparison | None:
    """The two lines in the middle of the temperatures both cover, each with its range; none
    without both lines, an overlap, or gas watched there."""
    watched_line, controlled_line = observing.fitted, control.fitted
    if (
        observing.line is None
        or control.line is None
        or watched_line is None
        or controlled_line is None
    ):
        return None
    low = max(observing.line.low, control.line.low)
    high = min(observing.line.high, control.line.high)
    if low > high:
        return None
    outdoor = (low + high) / 2
    watched, controlled = watched_line.at(outdoor), controlled_line.at(outdoor)
    if watched <= 0:
        return None
    watched_half = watched_line.t * watched_line.error_at(outdoor)
    controlled_half = controlled_line.t * controlled_line.error_at(outdoor)
    w_low, w_high = watched - watched_half, watched + watched_half
    c_low, c_high = controlled - controlled_half, controlled + controlled_half
    bounded = w_low > 0
    return Comparison(
        outdoor,
        watched,
        controlled,
        controlled / watched - 1,
        w_low,
        w_high,
        c_low,
        c_high,
        c_low / w_high - 1 if bounded else None,
        c_high / w_low - 1 if bounded else None,
        shown=c_high < w_low or c_low > w_high,
    )
