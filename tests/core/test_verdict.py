"""Verdict: enough data, problems and fine findings, load against the boiler's minimum power."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.building import LoadModel
from custom_components.vtherm_smart_boiler.core.metrics import CycleStats, Share
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.verdict import (
    ESTIMATE_ONLY,
    WATER_NOT_CONTROLLED,
    Reason,
    ReasonCode,
    ReasonKind,
    Verdict,
    VerdictOptions,
    assess,
    load_below_min_share,
)

# The water-temperature path (a flow-setpoint boiler) and the relay path (an on/off boiler).
FLOW_SETPOINT = VerdictOptions(control_sets_water=True)
RELAY = VerdictOptions(control_sets_water=False)

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


def reason(result, code: ReasonCode) -> Reason:
    return next(r for r in result.reasons if r.code is code)


def test_short_cycling_is_found_with_its_value_and_limit() -> None:
    result = assess(10 * DAY, stats(4.5, 0.7), Share(0.9, DAY), Share(0.05, DAY), FLOW_SETPOINT)
    assert {ReasonCode.FREQUENT_STARTS, ReasonCode.SHORT_BURNS} <= codes(result)
    frequent = reason(result, ReasonCode.FREQUENT_STARTS)
    assert frequent.kind is ReasonKind.PROBLEM
    assert frequent.value == pytest.approx(4.5)
    assert frequent.limit == 3.0


def test_low_condensing_alone_is_worth_it_where_control_sets_the_water() -> None:
    result = assess(10 * DAY, stats(1.0, 0.1), Share(0.2, DAY), Share(0.05, DAY), FLOW_SETPOINT)
    assert result.verdict is Verdict.WORTH_IT
    assert ReasonCode.LOW_CONDENSING in codes(result)


def test_load_often_below_min_power_is_found_but_not_changed_yet() -> None:
    result = assess(10 * DAY, stats(1.0, 0.1), Share(0.9, DAY), Share(0.6, DAY), FLOW_SETPOINT)
    assert result.verdict is Verdict.NOT_WORTH_IT
    load = reason(result, ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER)
    assert load.kind is ReasonKind.PROBLEM
    assert load.changed_by_control is False


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
    """Only the starts and the burn length judged, 2 of 4: not enough to say "not worth it"
    (S-32) — and the two missing inputs are named."""
    result = assess(10 * DAY, stats(2.0, 0.3), None, None)
    assert result.verdict is Verdict.NOT_ENOUGH_DATA
    assert {ReasonCode.CONDENSING_UNKNOWN, ReasonCode.LOAD_UNKNOWN} <= codes(result)
    assert reason(result, ReasonCode.CRITERIA_JUDGED) == Reason(
        ReasonCode.CRITERIA_JUDGED, ReasonKind.DATA, 2, 3
    )


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
    options = replace(FLOW_SETPOINT, condensing_boiler=False)
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
    assert minutes.verdict is Verdict.NOT_ENOUGH_DATA  # 2 criteria of 4 judged (S-32)
    hours = assess(10 * DAY, stats(1.0, 0.1), Share(0.0, 20 * HOUR), Share(0.05, 3 * DAY))
    assert ReasonCode.LOW_CONDENSING in codes(hours)


def test_the_verdict_load_criterion_needs_a_confident_model() -> None:
    """T-43 (S-17): only rough answers — the loss from the floor area (DEFAULT, 0.3), the class
    default threshold — and a minimum power: the load is not judged, and the reason says the
    model is an estimate only; nothing of it can make the verdict. Entered values judge it."""
    from custom_components.vtherm_smart_boiler.core.building import (
        InsulationClass,
        loss_from_coarse_answers,
    )
    from custom_components.vtherm_smart_boiler.core.history import History
    from custom_components.vtherm_smart_boiler.core.monitor import summarize, verdict
    from custom_components.vtherm_smart_boiler.core.parameters import (
        Estimate,
        ParameterKey,
        ParameterSet,
        Source,
    )
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    flame = Series[bool]([(0, False)])
    for k in range(int(8 * DAY // (30 * 60))):  # a 10-minute burn every half hour, 8 days
        flame.append(k * 1800 + 300, True)
        flame.append(k * 1800 + 900, False)
    history = History(
        signals={
            Signal.FLAME: flame,
            Signal.RETURN: Series([(0, 35.0)]),  # condensing: judged, fine
            Signal.DHW_ACTIVE: Series([(0, False)]),
        },
        weather=Series([(0, 8.0)]),
    )
    rough = (
        ParameterSet()
        .with_estimate(
            ParameterKey.LOSS_COEFFICIENT,
            loss_from_coarse_answers(150.0, InsulationClass.AVERAGE, -15.0, 20.0),
        )
        .with_estimate(ParameterKey.BOILER_MIN_POWER, Estimate(4.0, Source.ENTERED))
    )
    summary = summarize(history, rough, 0, 8 * DAY)
    assert summary.load_below_min is None
    result = verdict(summary)
    load = reason(result, ReasonCode.LOAD_UNKNOWN)
    assert load.kind is ReasonKind.MISSING
    assert load.detail == ESTIMATE_ONLY
    assert not any(r.code is ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER for r in result.reasons)
    # The user's own loss with the default threshold is half a model: an estimate still.
    half = rough.with_estimate(ParameterKey.LOSS_COEFFICIENT, Estimate(0.2, Source.ENTERED))
    assert reason(verdict(summarize(history, half, 0, 8 * DAY)), ReasonCode.LOAD_UNKNOWN).detail
    # Both entered: judged — 1.4 kW at 8 °C, below the 4 kW minimum all the time.
    entered = half.with_estimate(ParameterKey.HEATING_THRESHOLD, Estimate(15.0, Source.ENTERED))
    judged = verdict(summarize(history, entered, 0, 8 * DAY))
    assert ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER in codes(judged)
    # Without a minimum power, or without any outdoor temperature, the load is unknown, but
    # not for the model's sake.
    no_power = rough.without(ParameterKey.BOILER_MIN_POWER, Source.ENTERED)
    missing = reason(verdict(summarize(history, no_power, 0, 8 * DAY)), ReasonCode.LOAD_UNKNOWN)
    assert missing.detail is None
    history.weather = Series()
    no_outdoor = reason(verdict(summarize(history, rough, 0, 8 * DAY)), ReasonCode.LOAD_UNKNOWN)
    assert no_outdoor.detail is None


def test_not_worth_it_needs_three_of_four_criteria_judged() -> None:
    """S-32: "not worth it" rests on at least 3 of the 4 criteria — starts, burn length,
    condensing, load — with a known input; with 2 it is "not enough data", saying how many were
    judged. A non-condensing boiler has 3 criteria and needs 2."""
    two = assess(10 * DAY, stats(1.0, 0.1), None, None, FLOW_SETPOINT)
    assert two.verdict is Verdict.NOT_ENOUGH_DATA
    assert reason(two, ReasonCode.CRITERIA_JUDGED).value == 2
    assert reason(two, ReasonCode.CRITERIA_JUDGED).limit == 3
    for condensing, load in ((Share(0.9, DAY), None), (None, Share(0.05, DAY))):
        three = assess(10 * DAY, stats(1.0, 0.1), condensing, load, FLOW_SETPOINT)
        assert three.verdict is Verdict.NOT_WORTH_IT
        assert ReasonCode.CRITERIA_JUDGED not in codes(three)
    # A value between "fine" and "problem" is judged all the same: 2.0 starts an hour, 65 %.
    between = assess(10 * DAY, stats(2.0, 0.1), Share(0.65, DAY), None, FLOW_SETPOINT)
    assert between.verdict is Verdict.NOT_WORTH_IT
    non_condensing = replace(FLOW_SETPOINT, condensing_boiler=False)
    enough = assess(10 * DAY, stats(1.0, 0.1), None, None, non_condensing)
    assert enough.verdict is Verdict.NOT_WORTH_IT  # starts and burn length: 2 of 3
    assert reason(enough, ReasonCode.LOAD_UNKNOWN).kind is ReasonKind.MISSING


def test_each_problem_reason_says_whether_this_release_changes_it() -> None:
    """S-22: every problem carries ``changed_by_control``: low condensing is changed where
    control sets the water temperature, not through a relay; frequent starts, short burns and a
    load below the minimum power are not changed by 0.2.2's control. Other reasons carry
    nothing."""
    problems = (stats(4.5, 0.7), Share(0.2, DAY), Share(0.6, DAY))
    for options, condensing_changed in ((FLOW_SETPOINT, True), (RELAY, False)):
        result = assess(10 * DAY, *problems, options)
        changed = {r.code: r.changed_by_control for r in result.reasons}
        assert changed == {
            ReasonCode.FREQUENT_STARTS: False,
            ReasonCode.SHORT_BURNS: False,
            ReasonCode.LOW_CONDENSING: condensing_changed,
            ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER: False,
        }
    fine = assess(10 * DAY, stats(1.0, 0.1), Share(0.9, DAY), Share(0.05, DAY), FLOW_SETPOINT)
    assert all(r.changed_by_control is None for r in fine.reasons)


def test_worth_it_only_from_a_problem_control_changes() -> None:
    """Answer K: "worth it" only from a problem 0.2.2's control changes. Frequent starts and
    short burns alone: not worth it, both kept as "not changed yet". Low condensing on a
    flow-setpoint path: worth it; on the relay path: not."""
    cycling = assess(10 * DAY, stats(4.5, 0.7), Share(0.9, DAY), Share(0.05, DAY), FLOW_SETPOINT)
    assert cycling.verdict is Verdict.NOT_WORTH_IT
    for code in (ReasonCode.FREQUENT_STARTS, ReasonCode.SHORT_BURNS):
        found = reason(cycling, code)
        assert found.kind is ReasonKind.PROBLEM
        assert found.changed_by_control is False
    low = (stats(1.0, 0.1), Share(0.2, DAY), Share(0.05, DAY))
    assert assess(10 * DAY, *low, FLOW_SETPOINT).verdict is Verdict.WORTH_IT
    relay = assess(10 * DAY, *low, RELAY)
    assert relay.verdict is Verdict.NOT_WORTH_IT
    assert reason(relay, ReasonCode.LOW_CONDENSING).changed_by_control is False
    # Without knowing what control sets (the default), nothing is claimed changed.
    assert assess(10 * DAY, *low).verdict is Verdict.NOT_WORTH_IT


def test_without_a_flame_signal_the_verdict_says_so() -> None:
    """S-43: no burner signal mapped — the verdict stays "not enough data", with that reason,
    whatever else is known."""
    result = assess(
        10 * DAY, stats(4.5, 0.7), Share(0.2, DAY), Share(0.6, DAY), FLOW_SETPOINT,
        burner_signal=False,
    )  # fmt: skip
    assert result.verdict is Verdict.NOT_ENOUGH_DATA
    assert result.reasons == (Reason(ReasonCode.NO_BURNER_SIGNAL, ReasonKind.DATA),)


def test_the_load_share_uses_the_current_model_on_stored_days() -> None:
    """P-91: each day keeps seconds per whole °C of outdoor temperature (−30…+30 °C, the ends
    clamped), not a share computed with the model of its day; the load share is computed from
    them with the model and minimum power of now — a later measured loss changes it for every
    stored day. Days stored before, without it, are left out of the load criterion."""
    from custom_components.vtherm_smart_boiler.core.daily import (
        DaySummary,
        outdoor_distribution,
        verdict_over_days,
    )
    from custom_components.vtherm_smart_boiler.core.parameters import (
        Estimate,
        ParameterKey,
        ParameterSet,
        Source,
    )
    from custom_components.vtherm_smart_boiler.core.verdict import LoadBasis

    outdoor = Series([(0, -35.2), (HOUR, 2.4), (2 * HOUR, 2.6), (3 * HOUR, 41.0), (4 * HOUR, None)])
    assert outdoor_distribution(outdoor, 0, 5 * HOUR) == (
        (-30, HOUR),
        (2, HOUR),
        (3, HOUR),
        (30, HOUR),
    )
    assert outdoor_distribution(Series([(0, None)]), 0, HOUR) == ()  # known nowhere: nothing

    def day(index: int) -> DaySummary:
        """Twelve hours at 0 °C and twelve at 10 °C; a burn an hour, condensing well."""
        return replace(
            DaySummary.empty(index * DAY, (index + 1) * DAY),
            observed_s=DAY, starts=24, complete_burns=24, burn_s=6 * HOUR, heating_s=DAY,
            condensing_s=6 * HOUR, condensing_basis_s=6 * HOUR,
            outdoor_s=((0, 12 * HOUR), (10, 12 * HOUR)),
        )  # fmt: skip

    days = [day(index) for index in range(10)]

    def parameters(loss: float) -> ParameterSet:
        return (
            ParameterSet()
            .with_estimate(ParameterKey.LOSS_COEFFICIENT, Estimate(loss, Source.ENTERED))
            .with_estimate(ParameterKey.HEATING_THRESHOLD, Estimate(15.0, Source.ENTERED))
            .with_estimate(ParameterKey.BOILER_MIN_POWER, Estimate(2.5, Source.ENTERED))
        )

    def verdict_with(loss: float, kept: list[DaySummary]):
        basis = LoadBasis.from_parameters(parameters(loss))
        return verdict_over_days(kept, FLOW_SETPOINT, load=basis)

    # 0.2 kW/K: 3 kW at 0 °C, 1 kW at 10 °C — below the 2.5 kW minimum half the time.
    below = reason(verdict_with(0.2, days), ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER)
    assert below.value == pytest.approx(0.5)
    # The same stored days with a larger loss: 5 kW at 10 °C, never below.
    rarely = reason(verdict_with(0.5, days), ReasonCode.LOAD_RARELY_BELOW_MIN_POWER)
    assert rarely.value == pytest.approx(0.0)
    # Days stored before the distribution was kept count for everything but the load.
    old = [replace(d, outdoor_s=None) for d in days]
    unknown = verdict_with(0.2, old)
    assert reason(unknown, ReasonCode.LOAD_UNKNOWN).kind is ReasonKind.MISSING
    assert unknown.verdict is Verdict.NOT_WORTH_IT  # starts, burns, condensing: 3 judged
    mixed = [*old[:5], *days[5:]]
    assert reason(verdict_with(0.2, mixed), ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER).value == (
        pytest.approx(0.5)
    )
    # A stored day round-trips its distribution; an old stored day reads none.
    assert DaySummary.from_dict(days[0].to_dict()) == days[0]
    legacy = {k: v for k, v in days[0].to_dict().items() if k != "outdoor_s"}
    assert DaySummary.from_dict(legacy).outdoor_s is None


def test_low_condensing_not_changed_says_why_for_the_path() -> None:
    """Y4 (the Y3 carry-over): where control does not set the water temperature — a relay, or
    no water-temperature control — low condensing is "not changed" for that reason, not for
    anti-cycling planned later: its ``detail`` says so. Where control sets the water, and for
    the cycling problems, no such detail."""
    low = (stats(1.0, 0.1), Share(0.2, DAY), Share(0.05, DAY))
    relay = reason(assess(10 * DAY, *low, RELAY), ReasonCode.LOW_CONDENSING)
    assert (relay.changed_by_control, relay.detail) == (False, WATER_NOT_CONTROLLED)
    unknown = reason(assess(10 * DAY, *low), ReasonCode.LOW_CONDENSING)
    assert unknown.detail == WATER_NOT_CONTROLLED
    water = reason(assess(10 * DAY, *low, FLOW_SETPOINT), ReasonCode.LOW_CONDENSING)
    assert (water.changed_by_control, water.detail) == (True, None)
    cycling = assess(10 * DAY, stats(4.5, 0.7), Share(0.9, DAY), Share(0.05, DAY), RELAY)
    assert reason(cycling, ReasonCode.FREQUENT_STARTS).detail is None


# --- P-115: the verdict's precedence, as a table -------------------------------------------------
# Several findings at once, and what wins: no flame signal, then too little data, then a problem
# control changes, then too few criteria judged, then "not worth it". The table the split of
# ``assess`` must keep green; each reason as (code, kind, changed by control, detail), in order.

_NON_CONDENSING = VerdictOptions(condensing_boiler=False, control_sets_water=True)
P, F, M, D = ReasonKind.PROBLEM, ReasonKind.FINE, ReasonKind.MISSING, ReasonKind.DATA
C = ReasonCode

VERDICT_PRECEDENCE = [
    (
        "no flame signal beats short monitoring and problems",
        {
            "days": 2,
            "heating": stats(5.0, 0.9, burns=3),
            "condensing": 0.1,
            "load": 0.9,
            "burner": False,
        },
        Verdict.NOT_ENOUGH_DATA,
        [(C.NO_BURNER_SIGNAL, D, None, None)],
    ),
    (
        "too few days beat a problem control changes",
        {"days": 3, "heating": stats(5.0, 0.9), "condensing": 0.1, "load": 0.9},
        Verdict.NOT_ENOUGH_DATA,
        [(C.MONITORED_DAYS, D, None, None), (C.HEATING_BURNS, D, None, None)],
    ),
    (
        "too few burns, the days enough",
        {"days": 10, "heating": stats(5.0, 0.9, burns=5), "condensing": 0.1},
        Verdict.NOT_ENOUGH_DATA,
        [(C.MONITORED_DAYS, D, None, None), (C.HEATING_BURNS, D, None, None)],
    ),
    (
        "a problem control changes beats too few criteria judged",
        {"days": 10, "heating": stats(2.0, 0.3), "condensing": 0.1},
        Verdict.WORTH_IT,
        [
            (C.LONG_BURNS, F, None, None),
            (C.LOW_CONDENSING, P, True, None),
            (C.LOAD_UNKNOWN, M, None, None),
        ],
    ),
    (
        "problems control does not change, enough criteria judged",
        {"days": 10, "heating": stats(5.0, 0.9), "condensing": 0.9, "load": 0.5},
        Verdict.NOT_WORTH_IT,
        [
            (C.FREQUENT_STARTS, P, False, None),
            (C.SHORT_BURNS, P, False, None),
            (C.GOOD_CONDENSING, F, None, None),
            (C.LOAD_OFTEN_BELOW_MIN_POWER, P, False, None),
        ],
    ),
    (
        "low condensing on the relay path is not control's to change",
        {"days": 10, "heating": stats(1.0, 0.1), "condensing": 0.1, "load": 0.05, "options": RELAY},
        Verdict.NOT_WORTH_IT,
        [
            (C.FEW_STARTS, F, None, None),
            (C.LONG_BURNS, F, None, None),
            (C.LOW_CONDENSING, P, False, WATER_NOT_CONTROLLED),
            (C.LOAD_RARELY_BELOW_MIN_POWER, F, None, None),
        ],
    ),
    (
        "too few criteria judged: named first",
        {"days": 10, "heating": stats(2.0, 0.3)},
        Verdict.NOT_ENOUGH_DATA,
        [
            (C.CRITERIA_JUDGED, D, None, None),
            (C.LONG_BURNS, F, None, None),
            (C.CONDENSING_UNKNOWN, M, None, None),
            (C.LOAD_UNKNOWN, M, None, None),
        ],
    ),
    (
        "a boiler not built to condense: two of three criteria",
        {"days": 10, "heating": stats(2.0, 0.3), "condensing": 0.1, "options": _NON_CONDENSING},
        Verdict.NOT_WORTH_IT,
        [(C.LONG_BURNS, F, None, None), (C.LOAD_UNKNOWN, M, None, None)],
    ),
    (
        "minutes of a known return decide nothing",
        {
            "days": 10,
            "heating": stats(2.0, 0.3),
            "condensing": 0.1,
            "condensing_s": 600.0,
            "load": 0.5,
        },
        Verdict.NOT_WORTH_IT,
        [
            (C.LONG_BURNS, F, None, None),
            (C.CONDENSING_UNKNOWN, M, None, None),
            (C.LOAD_OFTEN_BELOW_MIN_POWER, P, False, None),
        ],
    ),
    (
        "a load model from rule-of-thumb values only is named",
        {"days": 10, "heating": stats(1.0, 0.1), "condensing": 0.9, "estimate_only": True},
        Verdict.NOT_WORTH_IT,
        [
            (C.FEW_STARTS, F, None, None),
            (C.LONG_BURNS, F, None, None),
            (C.GOOD_CONDENSING, F, None, None),
            (C.LOAD_UNKNOWN, M, None, ESTIMATE_ONLY),
        ],
    ),
    (
        "a load between rarely and often: judged, no reason",
        {"days": 10, "heating": stats(1.0, 0.1), "condensing": 0.9, "load": 0.2},
        Verdict.NOT_WORTH_IT,
        [
            (C.FEW_STARTS, F, None, None),
            (C.LONG_BURNS, F, None, None),
            (C.GOOD_CONDENSING, F, None, None),
        ],
    ),
    (
        "the starts unknown: not judged, three of four enough",
        {
            "days": 10,
            "heating": replace(stats(1.0, 0.1), active_s=0.0),
            "condensing": 0.9,
            "load": 0.05,
        },
        Verdict.NOT_WORTH_IT,
        [
            (C.LONG_BURNS, F, None, None),
            (C.GOOD_CONDENSING, F, None, None),
            (C.LOAD_RARELY_BELOW_MIN_POWER, F, None, None),
        ],
    ),
    (
        "all fine",
        {"days": 10, "heating": stats(1.0, 0.1), "condensing": 0.9, "load": 0.05},
        Verdict.NOT_WORTH_IT,
        [
            (C.FEW_STARTS, F, None, None),
            (C.LONG_BURNS, F, None, None),
            (C.GOOD_CONDENSING, F, None, None),
            (C.LOAD_RARELY_BELOW_MIN_POWER, F, None, None),
        ],
    ),
]


@pytest.mark.parametrize(
    ("given", "verdict", "reasons"),
    [row[1:] for row in VERDICT_PRECEDENCE],
    ids=[row[0] for row in VERDICT_PRECEDENCE],
)
def test_the_precedence_of_the_verdict(given: dict, verdict: Verdict, reasons: list[tuple]) -> None:
    """P-115: the verdict and exactly these reasons, in this order, for each set of findings."""
    condensing = given.get("condensing")
    load = given.get("load")
    result = assess(
        given["days"] * DAY,
        given["heating"],
        None if condensing is None else Share(condensing, given.get("condensing_s", DAY)),
        None if load is None else Share(load, DAY),
        given.get("options", FLOW_SETPOINT),
        load_estimate_only=given.get("estimate_only", False),
        burner_signal=given.get("burner", True),
    )
    assert result.verdict is verdict
    assert [(r.code, r.kind, r.changed_by_control, r.detail) for r in result.reasons] == reasons
