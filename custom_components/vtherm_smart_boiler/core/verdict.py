"""Verdict: is boiler control worth enabling here? Always with reasons.

Too little data gives "not enough data". Every problem found — frequent starts, mostly short
burns, little condensing, a building load often below the boiler's minimum power — is a reason,
and says whether 0.2.2's control changes it (S-22): only low condensing, and only where control
sets the water temperature, not through a relay. "Worth it" comes only from a problem control
changes (the user's answer K, 2026-09-27); the others are shown as "not changed yet".
"Not worth it" needs enough criteria judged — 3 of 4, 2 of 3 for a boiler not built to condense
(S-32) — otherwise it is "not enough data" too. The load criterion counts only with a trusted
building model (S-17), and without a burner signal there is no verdict (S-43). Every reason
carries its value and limit so the user sees why.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from enum import StrEnum

from .building import LoadModel, trusted_load_model
from .metrics import CycleStats, Share
from .parameters import ParameterKey, ParameterSet
from .series import Series

DAY = 86400.0
# Share of the monitoring days that must hold known data: a restart's seconds of unknown state
# must not keep the verdict away for ever.
MIN_COVERAGE = 0.9
# The least a share must rest on to decide anything, as the burn statistics need 20 burns.
MIN_CONDENSING_BASIS_S = 10 * 3600.0  # heating burn time with the return known
MIN_LOAD_BASIS_S = 86400.0  # heating-season time with the load known
# S-32: the criteria judged — starts, burn length, condensing, load — "not worth it" needs: all
# but one (provisional, K4).
CRITERIA_JUDGED_CONDENSING = 3  # of 4
CRITERIA_JUDGED_NON_CONDENSING = 2  # of 3: condensing is no criterion
# S-17: the load was not judged because the building model is only an estimate.
ESTIMATE_ONLY = "estimate_only"


class Verdict(StrEnum):
    WORTH_IT = "worth_it"
    NOT_WORTH_IT = "not_worth_it"
    NOT_ENOUGH_DATA = "not_enough_data"


class ReasonCode(StrEnum):
    MONITORED_DAYS = "monitored_days"
    HEATING_BURNS = "heating_burns"
    NO_BURNER_SIGNAL = "no_burner_signal"  # S-43: no flame mapped, so no burns to judge
    CRITERIA_JUDGED = "criteria_judged"  # S-32: too few criteria judged for "not worth it"
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
    PROBLEM = "problem"  # a problem found; ``changed_by_control`` says whether control changes it
    FINE = "fine"  # nothing to improve here
    MISSING = "missing"  # could not be judged
    DATA = "data"  # why there is not enough data yet


@dataclass(frozen=True, slots=True)
class Reason:
    code: ReasonCode
    kind: ReasonKind
    value: float | None = None
    limit: float | None = None
    # S-22: for a problem, whether 0.2.2's control changes it; ``None`` for any other reason.
    changed_by_control: bool | None = None
    # Why a criterion was not judged, where a code says more (``ESTIMATE_ONLY``).
    detail: str | None = None


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
    # S-22: 0.2.2's control sets the water temperature here (a flow-setpoint boiler), so low
    # condensing is a problem it changes; not through a relay, nor where control is not offered.
    # Unknown, nothing is claimed changed.
    control_sets_water: bool = False


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


def load_below_min_from_distribution(
    outdoor_s: Iterable[tuple[float, float]], model: LoadModel, min_power_kw: float
) -> Share:
    """P-91: the same share from seconds per outdoor temperature — each stored day's, whole °C
    — with the model and minimum power of now, whatever they were when the days were kept."""
    crossover = model.outdoor_at_load(min_power_kw)
    season = 0.0
    below = 0.0
    for temperature, seconds in outdoor_s:
        if temperature >= model.heating_threshold:
            continue
        season += seconds
        if temperature > crossover:
            below += seconds
    return Share(below / season if season > 0 else None, season)


@dataclass(frozen=True, slots=True)
class LoadBasis:
    """What the load criterion rests on (S-17): the building model when it is trusted — both
    values entered, or measured or learned with confidence — and the boiler's minimum power.
    ``estimate_only``: with a minimum power, a model exists but only from rule-of-thumb
    defaults or uncertain values; it decides nothing, and the verdict says so."""

    model: LoadModel | None = None
    min_power_kw: float | None = None
    estimate_only: bool = False

    @classmethod
    def from_parameters(cls, parameters: ParameterSet) -> LoadBasis:
        model = trusted_load_model(parameters)
        min_power = parameters.value(ParameterKey.BOILER_MIN_POWER)
        estimate = (
            model is None
            and min_power is not None
            and LoadModel.from_parameters(parameters) is not None
        )
        return cls(model, min_power, estimate)


def assess(
    monitored_s: float,
    heating: CycleStats,
    condensing: Share | None,
    load_below_min: Share | None,
    options: VerdictOptions | None = None,
    *,
    load_estimate_only: bool = False,
    burner_signal: bool = True,
) -> VerdictResult:
    """The verdict from the monitoring period's metrics.

    ``heating`` holds the heating-burn statistics of the period; ``condensing`` is ``None`` when
    the return is not mapped; ``load_below_min`` is ``None`` without a trusted load model, a
    minimum power or outdoor data — ``load_estimate_only`` when only the model's trust was
    lacking (S-17). ``burner_signal``: whether a flame signal is mapped at all (S-43).
    """
    opts = options or VerdictOptions()
    if not burner_signal:
        return VerdictResult(
            Verdict.NOT_ENOUGH_DATA, (Reason(ReasonCode.NO_BURNER_SIGNAL, ReasonKind.DATA),)
        )
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
    judged = 0  # S-32: criteria whose input was known, found fine, a problem or in between
    starts = heating.starts_per_hour
    if starts is not None:
        judged += 1
    if starts is not None and starts > opts.frequent_starts_per_hour:
        reasons.append(
            Reason(
                ReasonCode.FREQUENT_STARTS,
                ReasonKind.PROBLEM,
                starts,
                opts.frequent_starts_per_hour,
                changed_by_control=False,  # anti-cycling: 0.3 at the earliest (decision 13)
            )
        )
    elif starts is not None and starts <= opts.few_starts_per_hour:
        reasons.append(
            Reason(ReasonCode.FEW_STARTS, ReasonKind.FINE, starts, opts.few_starts_per_hour)
        )

    short = heating.short_burn_share
    if short is not None:
        judged += 1
    if short is not None and short > opts.short_burn_share:
        reasons.append(
            Reason(
                ReasonCode.SHORT_BURNS,
                ReasonKind.PROBLEM,
                short,
                opts.short_burn_share,
                changed_by_control=False,
            )
        )
    elif short is not None:
        reasons.append(Reason(ReasonCode.LONG_BURNS, ReasonKind.FINE, short, opts.short_burn_share))

    if opts.condensing_boiler:  # a boiler not built to condense is not judged on it
        if condensing is None or condensing.value is None:
            reasons.append(Reason(ReasonCode.CONDENSING_UNKNOWN, ReasonKind.MISSING))
        else:
            judged += 1
            if condensing.value < opts.low_condensing_share:
                reasons.append(
                    Reason(
                        ReasonCode.LOW_CONDENSING,
                        ReasonKind.PROBLEM,
                        condensing.value,
                        opts.low_condensing_share,
                        # Lower water from the curve: only where control sets the water.
                        changed_by_control=opts.control_sets_water,
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
        reasons.append(
            Reason(
                ReasonCode.LOAD_UNKNOWN,
                ReasonKind.MISSING,
                detail=ESTIMATE_ONLY if load_estimate_only else None,
            )
        )
    else:
        judged += 1
        if load_below_min.value >= opts.below_min_power_share:
            reasons.append(
                Reason(
                    ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER,
                    ReasonKind.PROBLEM,
                    load_below_min.value,
                    opts.below_min_power_share,
                    changed_by_control=False,  # the boiler's minimum power: not control's
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

    # Answer K: "worth it" only from a problem control changes; the others stay as reasons.
    if any(r.kind is ReasonKind.PROBLEM and r.changed_by_control for r in reasons):
        return VerdictResult(Verdict.WORTH_IT, tuple(reasons))
    needed = (
        CRITERIA_JUDGED_CONDENSING if opts.condensing_boiler else CRITERIA_JUDGED_NON_CONDENSING
    )
    if judged < needed:
        counted = Reason(ReasonCode.CRITERIA_JUDGED, ReasonKind.DATA, judged, needed)
        return VerdictResult(Verdict.NOT_ENOUGH_DATA, (counted, *reasons))
    return VerdictResult(Verdict.NOT_WORTH_IT, tuple(reasons))
