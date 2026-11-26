"""The modulation cap (I13.7): its floor, its level, when it applies, the lift when the boiler
falls short, the repeat, the read-back and the suggestion."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.cap_suggestion import (
    cap_suggestion,
    design_load_kw,
    suggested_cap,
)
from custom_components.vtherm_smart_boiler.core.modulation_cap import (
    ABOVE_MINIMUM_PCT,
    CAP_BOUNDS_PCT,
    CAP_DEFAULT_PCT,
    LIFTED_S,
    SAFE_FLOOR_PCT,
    SHORT_K,
    SHORT_S,
    CapInputs,
    CapReason,
    CapState,
    cap_floor,
    cap_level,
    cap_step,
    read_back_shows,
    write_due,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.verdict import (
    Reason,
    ReasonCode,
    ReasonKind,
    Verdict,
    VerdictResult,
)

T = 1_000_000.0


def inputs(**changes: object) -> CapInputs:
    """Control holds the boiler, no hot water, the flame on at the setpoint, the cap in force."""
    base: dict[str, object] = {
        "now": T,
        "holding": True,
        "hot_water": False,
        "flame": True,
        "flow": 50.0,
        "setpoint": 50.0,
        "capped": True,
    }
    return CapInputs(**(base | changes))  # type: ignore[arg-type]


def test_the_provisional_values() -> None:
    assert CAP_BOUNDS_PCT == (30.0, 100.0)
    assert CAP_DEFAULT_PCT == 70.0
    assert SAFE_FLOOR_PCT == 30.0
    assert ABOVE_MINIMUM_PCT == 10.0
    assert (SHORT_K, SHORT_S, LIFTED_S) == (5.0, 600.0, 3 * 3600.0)


@pytest.mark.parametrize(
    ("low", "high", "floor"),
    [
        (None, None, 30.0),  # nothing known: the safe floor
        (4.0, None, 30.0),
        (None, 24.0, 30.0),
        (3.0, 30.0, 30.0),  # 10 % + 10: under the safe floor
        (6.0, 24.0, 35.0),  # 25 % + 10
        (8.0, 24.0, 100.0 * 8.0 / 24.0 + 10.0),
        (22.0, 24.0, 100.0),  # never above the full range
        (24.0, 24.0, 30.0),  # nonsense: the safe floor
        (0.0, 24.0, 30.0),
        (30.0, 24.0, 30.0),
    ],
)
def test_the_floor(low: float | None, high: float | None, floor: float) -> None:
    assert cap_floor(low, high) == pytest.approx(floor)


def test_the_level_is_a_whole_percent_on_the_cautious_side() -> None:
    assert cap_level(70.0, 30.0) == 70
    assert cap_level(20.0, 30.0) == 30  # never below the floor
    assert cap_level(40.0, 43.33) == 44  # rounded up
    assert cap_level(55.5, 30.0) == 56
    assert cap_level(150.0, 30.0) == 100


def test_the_cap_applies_while_control_holds_the_boiler_without_hot_water() -> None:
    state, reason = cap_step(CapState(), inputs(), 50)
    assert (state, reason) == (CapState(), CapReason.APPLIED)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"holding": False}, CapReason.NOT_HOLDING),
        ({"hot_water": True}, CapReason.HOT_WATER),
        ({"hot_water": None}, CapReason.HOT_WATER_UNKNOWN),
    ],
)
def test_released_while_not_holding_and_while_hot_water_runs_or_is_unknown(
    changes: dict[str, object], reason: CapReason
) -> None:
    assert cap_step(CapState(), inputs(**changes), 50)[1] is reason


def test_a_cap_of_the_full_range_caps_nothing() -> None:
    assert cap_step(CapState(), inputs(), 100)[1] is CapReason.FULL_RANGE


def test_the_boiler_short_at_the_cap_lifts_it_for_three_hours() -> None:
    """The flow more than 5 K under the setpoint with the flame on for 10 min: lifted for 3 h,
    whatever the flow does meanwhile; then applied again."""
    short = {"flow": 50.0 - SHORT_K - 0.1}
    state, reason = cap_step(CapState(), inputs(**short), 50)
    assert (state, reason) == (CapState(short_since=T), CapReason.APPLIED)
    state, reason = cap_step(state, inputs(now=T + SHORT_S - 1, **short), 50)
    assert reason is CapReason.APPLIED
    state, reason = cap_step(state, inputs(now=T + SHORT_S, **short), 50)
    assert (state, reason) == (CapState(lifted_until=T + SHORT_S + LIFTED_S), CapReason.LIFTED)
    # Held while lifted, the flow back at the setpoint or not; hot water still releases it.
    later = T + SHORT_S + LIFTED_S - 1
    assert cap_step(state, inputs(now=later), 50) == (state, CapReason.LIFTED)
    assert cap_step(state, inputs(now=later, hot_water=True), 50) == (state, CapReason.HOT_WATER)
    assert cap_step(state, inputs(now=later, holding=False), 50) == (state, CapReason.NOT_HOLDING)
    assert cap_step(state, inputs(now=later + 1), 50) == (CapState(), CapReason.APPLIED)


@pytest.mark.parametrize(
    "changes",
    [
        {"flow": 50.0 - SHORT_K},  # at the limit: not short
        {"flame": False},
        {"flame": None},
        {"flow": None},
        {"setpoint": None},
        {"capped": False},  # not the cap's doing
    ],
)
def test_no_shortfall_is_counted_otherwise(changes: dict[str, object]) -> None:
    started = CapState(short_since=T - SHORT_S + 1)
    short = {"flow": 40.0} | changes
    assert cap_step(started, inputs(now=T, **short), 50) == (CapState(), CapReason.APPLIED)


def test_a_clock_set_back_starts_the_shortfall_again_and_ends_a_lift() -> None:
    short = {"flow": 40.0}
    state, _ = cap_step(CapState(short_since=T + 100), inputs(**short), 50)
    assert state.short_since == T
    lifted = CapState(lifted_until=T + LIFTED_S + 3600)  # longer than a lift: the clock moved
    assert cap_step(lifted, inputs(), 50) == (CapState(), CapReason.APPLIED)


def test_write_due() -> None:
    assert write_due(None, 50, None, T, 30.0)
    assert write_due(50, 60, T, T + 1, 30.0)  # a new value at once
    assert write_due(50, 50, None, T, 30.0)
    assert not write_due(50, 50, T, T + 29, 30.0)
    assert write_due(50, 50, T, T + 30, 30.0)  # the repeat
    assert write_due(50, 50, T, T - 1, 30.0)  # the clock set back


def test_the_read_back() -> None:
    assert read_back_shows(None, 50) is None
    assert read_back_shows(50.0, 50) is True
    assert read_back_shows(51.0, 50) is True
    assert read_back_shows(52.0, 50) is False
    assert read_back_shows(100.0, 100) is True


@pytest.mark.parametrize(
    ("load", "low", "high", "expected"),
    [
        (5.0, 4.0, 24.0, 30),  # 25 % with the margin: the floor 30 % (4/24 + 10 = 26.7)
        (8.0, 4.0, 24.0, 40),  # 9.6 / 24 = 40 %
        (8.2, 4.0, 24.0, 45),  # 41 %: up to the next 5
        (8.0, 6.0, 24.0, 40),  # the floor 35 %
        (3.0, 8.0, 24.0, 45),  # the floor 43.3 %, rounded up to 45
        (18.0, 4.0, 24.0, None),  # 90 %: little to gain
        (None, 4.0, 24.0, None),
        (8.0, None, 24.0, None),
        (8.0, 4.0, None, None),
        (0.0, 4.0, 24.0, None),
        (8.0, 24.0, 24.0, None),
    ],
)
def test_the_suggestion_covers_the_design_load(
    load: float | None, low: float | None, high: float | None, expected: int | None
) -> None:
    assert suggested_cap(load, low, high) == expected


def parameters(**values: float) -> ParameterSet:
    found = ParameterSet()
    for key, value in values.items():
        found = found.with_estimate(ParameterKey(key), Estimate(value, Source.ENTERED))
    return found


def test_the_design_load_rests_on_a_trusted_heat_loss_only() -> None:
    """The loss entered (or measured with confidence) times indoor less design outdoor; a rule
    of thumb or a confidence too low gives none."""
    entered = parameters(loss_coefficient=0.2, design_outdoor=-20.0, indoor_reference=20.0)
    assert design_load_kw(entered) == pytest.approx(8.0)
    assert design_load_kw(parameters(loss_coefficient=0.2)) == pytest.approx(0.2 * 35.0)
    assert design_load_kw(ParameterSet()) is None
    weak = ParameterSet().with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(0.2, Source.MEASURED, 0.3)
    )
    assert design_load_kw(weak) is None
    sure = ParameterSet().with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(0.2, Source.MEASURED, 0.9)
    )
    assert design_load_kw(sure) == pytest.approx(7.0)
    warm = parameters(loss_coefficient=0.2, design_outdoor=10.0, indoor_reference=10.0)
    assert design_load_kw(warm) is None


def verdict(*reasons: Reason) -> VerdictResult:
    return VerdictResult(Verdict.NOT_WORTH_IT, reasons)


SHORT = Reason(ReasonCode.SHORT_BURNS, ReasonKind.PROBLEM, 0.7, 0.5, changed_by_control=False)


def test_the_suggestion_needs_short_burns_and_the_boilers_powers() -> None:
    known = parameters(
        loss_coefficient=0.2, boiler_min_power=4.0, boiler_max_power=24.0, design_outdoor=-20.0
    )
    assert cap_suggestion(verdict(SHORT), known) == 40
    assert cap_suggestion(None, known) is None
    fine = Reason(ReasonCode.LONG_BURNS, ReasonKind.FINE, 0.2, 0.5)
    assert cap_suggestion(verdict(fine), known) is None
    assert cap_suggestion(verdict(SHORT), parameters(loss_coefficient=0.2)) is None
