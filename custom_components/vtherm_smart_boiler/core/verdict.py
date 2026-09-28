"""Verdict: is boiler control worth enabling here? Always with reasons.

Too little data gives "not enough data". Otherwise any problem that control addresses — frequent
starts, mostly short burns, little condensing, a building load often below the boiler's minimum
power — makes it "worth it"; none makes it "not worth it". Every reason carries its value and
limit so the user sees why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .building import LoadModel
from .metrics import CycleStats, Share
from .series import Series

DAY = 86400.0
# Share of the monitoring days that must hold known data: a restart's seconds of unknown state
# must not keep the verdict away for ever.
MIN_COVERAGE = 0.9
# The least a share must rest on to decide anything, as the burn statistics need 20 burns.
MIN_CONDENSING_BASIS_S = 10 * 3600.0  # heating burn time with the return known
MIN_LOAD_BASIS_S = 86400.0  # heating-season time with the load known


class Verdict(StrEnum):
    WORTH_IT = "worth_it"
    NOT_WORTH_IT = "not_worth_it"
    NOT_ENOUGH_DATA = "not_enough_data"


class ReasonCode(StrEnum):
    MONITORED_DAYS = "monitored_days"
    HEATING_BURNS = "heating_burns"
    FREQUENT_STARTS = "frequent_starts"
    FEW_STARTS = "few_starts"
    SHORT_BURNS = "short_burns"
    LONG_BURNS = "long_burns"
    LOW_CONDENSING = "low_condensing"
    GOOD_CONDENSING = "good_condensing"
    CONDENSING_UNKNOWN = "condensing_unknown"
    LOAD_OFTEN_BELOW_MIN_POWER = "load_often_below_min_power"
    LOAD_RARELY_BELOW_MIN_POWER = "load_rarely_below_min_power"
    LOAD_UNKNOWN = "load_unknown"


class ReasonKind(StrEnum):
    PROBLEM = "problem"  # something control improves
    FINE = "fine"  # nothing to improve here
    MISSING = "missing"  # could not be judged
    DATA = "data"  # why there is not enough data yet


@dataclass(frozen=True, slots=True)
class Reason:
    code: ReasonCode
    kind: ReasonKind
    value: float | None = None
    limit: float | None = None


@dataclass(frozen=True, slots=True)
class VerdictOptions:
    min_days: float = 7.0
    min_heating_burns: int = 20
    frequent_starts_per_hour: float = 3.0
    few_starts_per_hour: float = 1.5
    short_burn_share: float = 0.5
    low_condensing_share: float = 0.5
    good_condensing_share: float = 0.8
    below_min_power_share: float = 0.3
    rarely_below_min_power_share: float = 0.1
    # A boiler not built to condense runs its return hot on purpose: condensing is no reason.
    condensing_boiler: bool = True


@dataclass(frozen=True, slots=True)
class VerdictResult:
    verdict: Verdict
    reasons: tuple[Reason, ...] = field(default_factory=tuple)
    # P-96: days with data left out because the plugin controlled the boiler for an hour or
    # more of them — the verdict is the installation's own, without control.
    days_left_out: int = 0


def load_below_min_share(
    outdoor: Series[float], model: LoadModel, min_power_kw: float, start: float, end: float
) -> Share:
    """Share of heating-season time (outdoor below the threshold) with the load below the
    boiler's minimum power."""
    crossover = model.outdoor_at_load(min_power_kw)
    season = 0.0
    below = 0.0
    for segment in outdoor.segments(start, end):
        if segment.value is None or segment.value >= model.heating_threshold:
            continue
        season += segment.duration
        if segment.value > crossover:
            below += segment.duration
    return Share(below / season if season > 0 else None, season)


def assess(
    monitored_s: float,
    heating: CycleStats,
    condensing: Share | None,
    load_below_min: Share | None,
    options: VerdictOptions | None = None,
) -> VerdictResult:
    """The verdict from the monitoring period's metrics.

    ``heating`` holds the heating-burn statistics of the period; ``condensing`` is ``None`` when
    the return is not mapped; ``load_below_min`` is ``None`` without a load model, a minimum
    power or outdoor data.
    """
    opts = options or VerdictOptions()
    days = monitored_s / DAY
    if days < opts.min_days * MIN_COVERAGE or heating.complete_burns < opts.min_heating_burns:
        return VerdictResult(
            Verdict.NOT_ENOUGH_DATA,
            (
                Reason(ReasonCode.MONITORED_DAYS, ReasonKind.DATA, days, opts.min_days),
                Reason(
                    ReasonCode.HEATING_BURNS,
                    ReasonKind.DATA,
                    heating.complete_burns,
                    opts.min_heating_burns,
                ),
            ),
        )

    if condensing is not None and condensing.basis_s < MIN_CONDENSING_BASIS_S:
        condensing = None  # minutes of a known return decide nothing
    if load_below_min is not None and load_below_min.basis_s < MIN_LOAD_BASIS_S:
        load_below_min = None

    reasons: list[Reason] = []
    starts = heating.starts_per_hour
    if starts is not None and starts > opts.frequent_starts_per_hour:
        reasons.append(
            Reason(
                ReasonCode.FREQUENT_STARTS,
                ReasonKind.PROBLEM,
                starts,
                opts.frequent_starts_per_hour,
            )
        )
    elif starts is not None and starts <= opts.few_starts_per_hour:
        reasons.append(
            Reason(ReasonCode.FEW_STARTS, ReasonKind.FINE, starts, opts.few_starts_per_hour)
        )

    short = heating.short_burn_share
    if short is not None and short > opts.short_burn_share:
        reasons.append(
            Reason(ReasonCode.SHORT_BURNS, ReasonKind.PROBLEM, short, opts.short_burn_share)
        )
    elif short is not None:
        reasons.append(Reason(ReasonCode.LONG_BURNS, ReasonKind.FINE, short, opts.short_burn_share))

    if opts.condensing_boiler:  # a boiler not built to condense is not judged on it
        if condensing is None or condensing.value is None:
            reasons.append(Reason(ReasonCode.CONDENSING_UNKNOWN, ReasonKind.MISSING))
        elif condensing.value < opts.low_condensing_share:
            reasons.append(
                Reason(
                    ReasonCode.LOW_CONDENSING,
                    ReasonKind.PROBLEM,
                    condensing.value,
                    opts.low_condensing_share,
                )
            )
        elif condensing.value >= opts.good_condensing_share:
            reasons.append(
                Reason(
                    ReasonCode.GOOD_CONDENSING,
                    ReasonKind.FINE,
                    condensing.value,
                    opts.good_condensing_share,
                )
            )

    if load_below_min is None or load_below_min.value is None:
        reasons.append(Reason(ReasonCode.LOAD_UNKNOWN, ReasonKind.MISSING))
    elif load_below_min.value >= opts.below_min_power_share:
        reasons.append(
            Reason(
                ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER,
                ReasonKind.PROBLEM,
                load_below_min.value,
                opts.below_min_power_share,
            )
        )
    elif load_below_min.value < opts.rarely_below_min_power_share:
        reasons.append(
            Reason(
                ReasonCode.LOAD_RARELY_BELOW_MIN_POWER,
                ReasonKind.FINE,
                load_below_min.value,
                opts.rarely_below_min_power_share,
            )
        )

    worth = any(reason.kind is ReasonKind.PROBLEM for reason in reasons)
    return VerdictResult(Verdict.WORTH_IT if worth else Verdict.NOT_WORTH_IT, tuple(reasons))
