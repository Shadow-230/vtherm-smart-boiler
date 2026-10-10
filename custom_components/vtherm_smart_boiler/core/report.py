"""Report explaining changes: why this period used more or less than the previous one.

The change in total use is split into weather (degree-days at the previous period's use per
degree-day), DHW (its own change), settings (a changed mean zone setpoint acts like extra
degree-days on every heating day) and whatever is left. The parts always add up to the change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

MIN_DEGREE_DAYS = 0.5


@dataclass(frozen=True, slots=True)
class PeriodSummary:
    """Use in one period, in one unit for both periods (gas, energy or burner hours).

    ``heating_days`` is the time with the outdoor temperature below the heating threshold, in
    days; ``mean_target`` the time-weighted mean zone setpoint, when known.
    """

    heating: float
    dhw: float
    degree_days: float
    heating_days: float
    mean_target: float | None = None

    @property
    def total(self) -> float:
        return self.heating + self.dhw


class Cause(StrEnum):
    WEATHER = "weather"
    DHW = "dhw"
    SETTINGS = "settings"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class Contribution:
    cause: Cause
    amount: float  # part of the change, in the periods' unit


@dataclass(frozen=True, slots=True)
class ChangeReport:
    previous_total: float
    current_total: float
    contributions: tuple[Contribution, ...]
    unexplained: tuple[Cause, ...] = ()  # causes that could not be judged (folded into OTHER)

    @property
    def change(self) -> float:
        return self.current_total - self.previous_total

    @property
    def relative_change(self) -> float | None:
        return self.change / self.previous_total if self.previous_total > 0 else None

    def amount(self, cause: Cause) -> float:
        return sum(c.amount for c in self.contributions if c.cause is cause)


def _use_per_degree_day(previous: PeriodSummary, current: PeriodSummary) -> float | None:
    for period in (previous, current):
        if period.degree_days >= MIN_DEGREE_DAYS and period.heating > 0:
            return period.heating / period.degree_days
    return None


def explain_change(previous: PeriodSummary, current: PeriodSummary) -> ChangeReport:
    """Split the change between two periods into weather, DHW, settings and other."""
    specific = _use_per_degree_day(previous, current)
    unexplained: list[Cause] = []
    if specific is None:
        weather = 0.0
        unexplained.append(Cause.WEATHER)
    else:
        weather = specific * (current.degree_days - previous.degree_days)
    dhw = current.dhw - previous.dhw
    if specific is None or previous.mean_target is None or current.mean_target is None:
        settings = 0.0
        unexplained.append(Cause.SETTINGS)
    else:
        settings = specific * (current.mean_target - previous.mean_target) * current.heating_days
    change = current.total - previous.total
    other = change - weather - dhw - settings
    return ChangeReport(
        previous.total,
        current.total,
        (
            Contribution(Cause.WEATHER, weather),
            Contribution(Cause.DHW, dhw),
            Contribution(Cause.SETTINGS, settings),
            Contribution(Cause.OTHER, other),
        ),
        tuple(unexplained),
    )
