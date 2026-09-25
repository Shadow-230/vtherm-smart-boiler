"""Daily summaries: what the verdict needs from each local day, kept for up to a year.

A day's summary holds only amounts that add up across days — known time, heating starts and
burns, the hours with heating, the condensing and load shares as their parts, degree-days and
heating gas — so the verdict over any window is built from its days. The raw history is kept
for a few days only; the summaries outlive it (``SCOPE.md`` §10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .building import DayPoint
from .history import History
from .metrics import CH_KINDS, CycleStats, Share
from .monitor import MonitorOptions, summarize
from .parameters import ParameterSet
from .series import time_weighted_mean
from .verdict import VerdictOptions, VerdictResult, assess

DAY = 86400.0
KEEP_DAYS = 365
FIT_COVERAGE = 0.9  # a day the fit uses is known for this much of it


@dataclass(frozen=True, slots=True)
class DaySummary:
    start: float
    end: float
    observed_s: float  # flame state known
    starts: int  # heating burns whose start was seen
    complete_burns: int
    short_burns: int
    burn_s: float
    heating_s: float  # time in the clock hours with heating
    condensing_s: float  # heating burn time with a condensing return
    condensing_basis_s: float  # heating burn time with the return known
    below_min_s: float  # heating-season time with the load below the boiler's minimum
    season_s: float  # heating-season time with a known load
    load_known: bool  # a load model and a minimum power existed that day
    degree_days: float | None
    gas: float | None  # heating gas, hot water left out where known
    outdoor_mean: float | None = None  # over the day, when known for most of it
    heat_kwh: float | None = None  # heating output, when known for every burn

    @classmethod
    def empty(cls, start: float, end: float) -> DaySummary:
        return cls(start, end, 0.0, 0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, False, None, None)

    @property
    def fit_point(self) -> DayPoint | None:
        """The day as the building fit uses it: known outdoor, complete heat, most of it seen."""
        if (
            self.outdoor_mean is None
            or self.heat_kwh is None
            or self.observed_s < FIT_COVERAGE * (self.end - self.start)
        ):
            return None
        # A day of 23 or 25 hours (the clock change) counts as a whole day of heating.
        return DayPoint(self.outdoor_mean, self.heat_kwh * DAY / (self.end - self.start))

    @property
    def has_data(self) -> bool:
        return self.observed_s > 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DaySummary:
        """A stored summary; raises ``KeyError``, ``TypeError`` or ``ValueError`` when broken."""

        def number(key: str) -> float:
            return float(data[key])

        def optional(key: str) -> float | None:
            return None if data.get(key) is None else float(data[key])

        return cls(
            start=number("start"),
            end=number("end"),
            observed_s=number("observed_s"),
            starts=int(data["starts"]),
            complete_burns=int(data["complete_burns"]),
            short_burns=int(data["short_burns"]),
            burn_s=number("burn_s"),
            heating_s=number("heating_s"),
            condensing_s=number("condensing_s"),
            condensing_basis_s=number("condensing_basis_s"),
            below_min_s=number("below_min_s"),
            season_s=number("season_s"),
            load_known=bool(data["load_known"]),
            degree_days=optional("degree_days"),
            gas=optional("gas"),
            outdoor_mean=optional("outdoor_mean"),
            heat_kwh=optional("heat_kwh"),
        )


def summarize_day(
    history: History,
    parameters: ParameterSet,
    start: float,
    end: float,
    options: MonitorOptions | None = None,
) -> DaySummary:
    """One day of history, reduced to what adds up."""
    summary = summarize(history, parameters, start, end, options)
    heating = summary.heating
    outdoor = time_weighted_mean(history.outdoor(), start, end)
    heat = summary.heat_output_kwh
    condensing = summary.condensing
    load = summary.load_below_min
    return DaySummary(
        start=start,
        end=end,
        observed_s=summary.observed_s,
        starts=heating.starts,
        complete_burns=heating.complete_burns,
        short_burns=heating.short_burns,
        burn_s=heating.burn_s,
        heating_s=heating.active_s or 0.0,
        condensing_s=_part(condensing),
        condensing_basis_s=0.0 if condensing is None else condensing.basis_s,
        below_min_s=_part(load),
        season_s=0.0 if load is None else load.basis_s,
        load_known=load is not None,
        degree_days=None if summary.degree_days is None else summary.degree_days.value,
        gas=None if summary.gas is None else summary.gas.amount,
        outdoor_mean=(outdoor.value if outdoor.known_s >= FIT_COVERAGE * (end - start) else None),
        heat_kwh=heat.amount if heat is not None and heat.complete else None,
    )


def fit_points(days: Sequence[DaySummary]) -> list[DayPoint]:
    """Every kept day the building fit can use."""
    return [point for day in days if (point := day.fit_point) is not None]


def _part(share: Share | None) -> float:
    if share is None or share.value is None:
        return 0.0
    return share.value * share.basis_s


def verdict_over_days(
    days: Sequence[DaySummary],
    options: VerdictOptions | None = None,
    window_days: int | None = None,
) -> VerdictResult:
    """The verdict over the latest ``window_days`` days with data (all of them by default)."""
    with_data = sorted((d for d in days if d.has_data), key=lambda d: d.start)
    chosen = with_data if window_days is None else with_data[-window_days:]
    observed = sum(d.observed_s for d in chosen)
    heating = CycleStats(
        observed_s=observed,
        starts=sum(d.starts for d in chosen),
        complete_burns=sum(d.complete_burns for d in chosen),
        burn_s=sum(d.burn_s for d in chosen),
        median_burn_s=None,
        p10_burn_s=None,
        p90_burn_s=None,
        short_burns=sum(d.short_burns for d in chosen),
        active_s=sum(d.heating_s for d in chosen),
    )
    basis = sum(d.condensing_basis_s for d in chosen)
    condensing = (
        Share(sum(d.condensing_s for d in chosen) / basis if basis > 0 else None, basis)
        if basis > 0
        else None
    )
    season = sum(d.season_s for d in chosen)
    load = (
        Share(sum(d.below_min_s for d in chosen) / season if season > 0 else None, season)
        if any(d.load_known for d in chosen)
        else None
    )
    return assess(observed, heating, condensing, load, options)


__all__ = ["CH_KINDS", "KEEP_DAYS", "DaySummary", "summarize_day", "verdict_over_days"]
