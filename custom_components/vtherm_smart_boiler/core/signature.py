"""The energy signature, for the Boiler page's Analyses tab
(``docs/en/development/plans/plan-0.2-i10.md``, I10.7): each day's heating gas against its mean
outdoor temperature, the days the plugin only watched and the days under control apart.

A day is shown where its gas and its outdoor mean are known and most of it was seen (the
building fit's coverage), its gas per 24 hours so a day of 23 or 25 hours compares. Each group
gets a straight line through its heating days — colder than the heating threshold in use, with
heating gas — by the building fit's own rules (``core.building``): enough days, enough spread of
outdoor temperature, more gas on colder days, and a fit close enough; otherwise no line, and why.
Where both lines exist and their temperatures overlap, they are compared in the middle of the
overlap: how much more or less gas a day under control took there.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from .building import MIN_FIT_DAYS, MIN_OUTDOOR_SPREAD_K, MIN_QUALITY
from .daily import DAY, FIT_COVERAGE, DaySummary


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


@dataclass(frozen=True, slots=True)
class Comparison:
    outdoor: float  # °C, the middle of the temperatures both lines were fitted over
    observing: float  # gas per day there, watched
    control: float  # gas per day there, under control
    change: float  # control against watched: -0.1 is 10 % less


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
    return Signature(tuple(shown), observing, control, _compare(observing.line, control.line))


def _fit(days: list[SignatureDay]) -> SignatureFit:
    if len(days) < MIN_FIT_DAYS:
        return SignatureFit(None, NoLine.TOO_FEW_DAYS)
    xs = [d.outdoor for d in days]
    ys = [d.gas for d in days]
    if max(xs) - min(xs) < MIN_OUTDOOR_SPREAD_K:
        return SignatureFit(None, NoLine.TOO_LITTLE_SPREAD)
    n = len(days)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    if slope >= 0:
        return SignatureFit(None, NoLine.NOT_HEATING)
    intercept = mean_y - slope * mean_x
    # A falling line means the gas varies: ``total`` is above zero.
    total = sum((y - mean_y) ** 2 for y in ys)
    residual = sum((y - (intercept + slope * x)) ** 2 for x, y in zip(xs, ys, strict=True))
    r_squared = 1.0 - residual / total
    if r_squared < MIN_QUALITY:
        return SignatureFit(None, NoLine.TOO_SCATTERED)
    return SignatureFit(SignatureLine(slope, intercept, min(xs), max(xs), n, r_squared), None)


def _compare(observing: SignatureLine | None, control: SignatureLine | None) -> Comparison | None:
    if observing is None or control is None:
        return None
    low, high = max(observing.low, control.low), min(observing.high, control.high)
    if low > high:
        return None
    outdoor = (low + high) / 2
    watched, controlled = observing.at(outdoor), control.at(outdoor)
    if watched <= 0:
        return None
    return Comparison(outdoor, watched, controlled, controlled / watched - 1)
