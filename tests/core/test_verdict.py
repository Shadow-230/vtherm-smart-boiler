"""Verdict: enough data, problems and fine findings, load against the boiler's minimum power."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.building import LoadModel
from custom_components.vtherm_smart_boiler.core.metrics import CycleStats, Share
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.verdict import (
    Reason,
    ReasonCode,
    ReasonKind,
    Verdict,
    VerdictOptions,
    assess,
    load_below_min_share,
)

DAY = 86400.0
HOUR = 3600.0


def stats(starts_per_hour: float, short_share: float, burns: int = 100) -> CycleStats:
    observed = 10 * DAY
    return CycleStats(
        observed_s=observed,
        starts=round(starts_per_hour * observed / HOUR),
        complete_burns=burns,
        burn_s=0.0,
        median_burn_s=600.0,
        p10_burn_s=300.0,
        p90_burn_s=1200.0,
        short_burns=round(short_share * burns),
    )


def codes(result) -> set[ReasonCode]:
    return {r.code for r in result.reasons}


def test_not_enough_days_or_burns() -> None:
    result = assess(3 * DAY, stats(5.0, 0.9), Share(0.1, DAY), Share(0.9, DAY))
    assert result.verdict is Verdict.NOT_ENOUGH_DATA
    assert result.reasons[0] == Reason(ReasonCode.MONITORED_DAYS, ReasonKind.DATA, 3.0, 7.0)
    few = assess(10 * DAY, stats(5.0, 0.9, burns=5), None, None)
    assert few.verdict is Verdict.NOT_ENOUGH_DATA
    assert Reason(ReasonCode.HEATING_BURNS, ReasonKind.DATA, 5, 20) in few.reasons


def test_short_cycling_is_worth_it() -> None:
    result = assess(10 * DAY, stats(4.5, 0.7), Share(0.9, DAY), Share(0.05, DAY))
    assert result.verdict is Verdict.WORTH_IT
    assert {ReasonCode.FREQUENT_STARTS, ReasonCode.SHORT_BURNS} <= codes(result)
    frequent = next(r for r in result.reasons if r.code is ReasonCode.FREQUENT_STARTS)
    assert frequent.value == pytest.approx(4.5)
    assert frequent.limit == 3.0


def test_low_condensing_alone_is_worth_it() -> None:
    result = assess(10 * DAY, stats(1.0, 0.1), Share(0.2, DAY), Share(0.05, DAY))
    assert result.verdict is Verdict.WORTH_IT
    assert ReasonCode.LOW_CONDENSING in codes(result)


def test_load_often_below_min_power_is_worth_it() -> None:
    result = assess(10 * DAY, stats(1.0, 0.1), Share(0.9, DAY), Share(0.6, DAY))
    assert result.verdict is Verdict.WORTH_IT
    assert ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER in codes(result)


def test_well_behaved_boiler_is_not_worth_it() -> None:
    result = assess(10 * DAY, stats(1.0, 0.1), Share(0.9, DAY), Share(0.05, DAY))
    assert result.verdict is Verdict.NOT_WORTH_IT
    assert codes(result) == {
        ReasonCode.FEW_STARTS,
        ReasonCode.LONG_BURNS,
        ReasonCode.GOOD_CONDENSING,
        ReasonCode.LOAD_RARELY_BELOW_MIN_POWER,
    }
    assert all(r.kind is ReasonKind.FINE for r in result.reasons)


def test_missing_inputs_are_named() -> None:
    result = assess(10 * DAY, stats(2.0, 0.3), None, None)
    assert result.verdict is Verdict.NOT_WORTH_IT
    assert {ReasonCode.CONDENSING_UNKNOWN, ReasonCode.LOAD_UNKNOWN} <= codes(result)


def test_load_below_min_share_over_heating_season_time() -> None:
    model = LoadModel(loss_coefficient=0.2, heating_threshold=15.0)  # 3 kW at 0 °C
    outdoor = Series([(0, -5.0), (HOUR, 5.0), (2 * HOUR, 10.0), (3 * HOUR, 20.0)])
    share = load_below_min_share(outdoor, model, 3.0, 0, 4 * HOUR)
    assert share.basis_s == 3 * HOUR  # the warm hour is outside the heating season
    assert share.value == pytest.approx(2 / 3)
    assert load_below_min_share(Series([(0, 20.0)]), model, 3.0, 0, HOUR).value is None


def test_a_non_condensing_boiler_is_not_judged_on_condensing() -> None:
    """A1: a boiler not built to condense runs its return hot on purpose — no reason to enable
    control — and one that condenses often is no merit either."""
    from dataclasses import replace

    options = replace(VerdictOptions(), condensing_boiler=False)
    hot_return = assess(10 * DAY, stats(1.0, 0.1), Share(0.0, DAY), Share(0.05, DAY), options)
    assert hot_return.verdict is Verdict.NOT_WORTH_IT
    condensing = assess(10 * DAY, stats(1.0, 0.1), Share(0.95, DAY), Share(0.05, DAY), options)
    assert not {
        ReasonCode.LOW_CONDENSING,
        ReasonCode.GOOD_CONDENSING,
        ReasonCode.CONDENSING_UNKNOWN,
    } & (codes(hot_return) | codes(condensing))


def test_shares_on_minutes_of_data_decide_nothing() -> None:
    """A6: the burn statistics need twenty complete burns; the condensing and load shares
    decided from any basis at all — five minutes of a known return made a verdict."""
    minutes = assess(10 * DAY, stats(1.0, 0.1), Share(0.0, 300.0), Share(0.9, 600.0))
    assert ReasonCode.CONDENSING_UNKNOWN in codes(minutes)
    assert ReasonCode.LOAD_UNKNOWN in codes(minutes)
    assert minutes.verdict is Verdict.NOT_WORTH_IT
    hours = assess(10 * DAY, stats(1.0, 0.1), Share(0.0, 20 * HOUR), Share(0.05, 3 * DAY))
    assert ReasonCode.LOW_CONDENSING in codes(hours)
