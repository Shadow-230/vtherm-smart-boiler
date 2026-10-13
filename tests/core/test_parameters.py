"""Parameters: precedence of sources, confidence, suggestions and declared-vs-measured findings."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.parameters import (
    DEFAULT_CONFIDENCE,
    PARAMETER_DEFS,
    Estimate,
    Mismatch,
    ParameterKey,
    ParameterSet,
    Source,
)

MIN_POWER = ParameterKey.BOILER_MIN_POWER
HYSTERESIS = ParameterKey.CH_HYSTERESIS


def test_every_key_has_a_definition() -> None:
    assert set(PARAMETER_DEFS) == set(ParameterKey)


def test_unknown_without_estimates_or_default() -> None:
    assert ParameterSet().value(MIN_POWER) is None


def test_class_default_is_used_last_with_low_confidence() -> None:
    effective = ParameterSet().get(ParameterKey.HEATING_THRESHOLD).effective()
    assert effective == Estimate(15.0, Source.DEFAULT, DEFAULT_CONFIDENCE)


def test_entered_always_wins() -> None:
    params = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.5, Source.MEASURED, 0.9))
        .with_estimate(MIN_POWER, Estimate(4.0, Source.LEARNED, 0.95))
        .with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
    )
    assert params.value(MIN_POWER) == 3.0


def test_learned_before_measured_when_confident() -> None:
    params = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.5, Source.MEASURED, 0.9))
        .with_estimate(MIN_POWER, Estimate(4.0, Source.LEARNED, 0.6))
    )
    assert params.value(MIN_POWER) == 4.0
    assert params.value(MIN_POWER, min_confidence=0.7) == 3.5


def test_low_confidence_falls_through_to_default() -> None:
    key = ParameterKey.HEATING_THRESHOLD
    params = ParameterSet().with_estimate(key, Estimate(12.0, Source.MEASURED, 0.3))
    assert params.value(key) == 15.0


def test_suggestion_is_never_effective_until_confirmed() -> None:
    key = ParameterKey.MAX_CH_SETPOINT
    params = ParameterSet().with_estimate(key, Estimate(65.0, Source.SUGGESTED))
    assert params.value(key) is None
    confirmed = params.confirm_suggestion(key, at=10.0)
    assert confirmed.get(key).effective() == Estimate(65.0, Source.ENTERED, 1.0, 10.0)
    assert confirmed.get(key).estimate(Source.SUGGESTED) is None


def test_confirming_without_suggestion_fails() -> None:
    with pytest.raises(KeyError):
        ParameterSet().confirm_suggestion(MIN_POWER)


def test_implausible_values_and_confidence_are_rejected() -> None:
    with pytest.raises(ValueError, match="outside"):
        ParameterSet().with_estimate(MIN_POWER, Estimate(0.0, Source.ENTERED))
    with pytest.raises(ValueError, match="confidence"):
        ParameterSet().with_estimate(MIN_POWER, Estimate(3.0, Source.MEASURED, 1.5))


def test_sets_are_immutable() -> None:
    empty = ParameterSet()
    empty.with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
    assert empty.value(MIN_POWER) is None


def test_mismatch_needs_both_tolerances_exceeded() -> None:
    declared = ParameterSet().with_estimate(HYSTERESIS, Estimate(5.0, Source.ENTERED))
    close = declared.with_estimate(HYSTERESIS, Estimate(6.5, Source.MEASURED, 0.8))
    assert close.mismatches() == []
    far = declared.with_estimate(HYSTERESIS, Estimate(10.0, Source.MEASURED, 0.8))
    assert far.mismatches() == [
        Mismatch(HYSTERESIS, 5.0, Estimate(10.0, Source.MEASURED, 0.8)),
    ]


def test_mismatch_ignores_unconfident_observations_and_missing_declaration() -> None:
    unsure = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
        .with_estimate(MIN_POWER, Estimate(6.0, Source.MEASURED, 0.2))
    )
    assert unsure.mismatches() == []
    undeclared = ParameterSet().with_estimate(MIN_POWER, Estimate(6.0, Source.MEASURED, 0.9))
    assert undeclared.mismatches() == []


def test_mismatch_compares_with_the_best_observation() -> None:
    params = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
        .with_estimate(MIN_POWER, Estimate(3.1, Source.LEARNED, 0.9))
        .with_estimate(MIN_POWER, Estimate(9.0, Source.MEASURED, 0.9))
    )
    assert params.mismatches() == []


def test_without_removes_one_source() -> None:
    params = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
        .with_estimate(MIN_POWER, Estimate(4.0, Source.MEASURED, 0.9))
        .without(MIN_POWER, Source.ENTERED)
    )
    assert params.value(MIN_POWER) == 4.0


# --- Mutation testing (2026-10-12): range and tolerance edges, defaults of other sources ---


@pytest.mark.parametrize("value", [PARAMETER_DEFS[MIN_POWER].low, PARAMETER_DEFS[MIN_POWER].high])
def test_the_plausible_range_includes_its_ends(value: float) -> None:
    """A value exactly at either end of the plausible range is accepted."""
    params = ParameterSet().with_estimate(MIN_POWER, Estimate(value, Source.ENTERED))
    assert params.value(MIN_POWER) == value


def test_a_confidence_of_zero_is_accepted_and_never_effective() -> None:
    """Confidence runs from 0 to 1 inclusive: an estimate with none at all is stored, not used."""
    params = ParameterSet().with_estimate(MIN_POWER, Estimate(3.0, Source.MEASURED, 0.0))
    assert params.get(MIN_POWER).estimate(Source.MEASURED) == Estimate(3.0, Source.MEASURED, 0.0)
    assert params.value(MIN_POWER) is None


def test_the_class_default_answers_only_for_the_default_source() -> None:
    """Negative: the class default is no entry, no measurement and no suggestion; and an
    estimate that exists is returned as it is."""
    key = ParameterKey.HEATING_THRESHOLD
    parameter = ParameterSet().get(key)
    for source in (Source.ENTERED, Source.MEASURED, Source.LEARNED, Source.SUGGESTED):
        assert parameter.estimate(source) is None, source
    entered = Estimate(17.0, Source.ENTERED)
    assert ParameterSet().with_estimate(key, entered).get(key).estimate(Source.ENTERED) == entered


def test_an_observation_at_exactly_the_minimum_confidence_is_compared() -> None:
    """The confidence the plugin counts includes its edge: such an observation shows a mismatch."""
    params = (
        ParameterSet()
        .with_estimate(MIN_POWER, Estimate(3.0, Source.ENTERED))
        .with_estimate(MIN_POWER, Estimate(6.0, Source.MEASURED, 0.5))
    )
    assert params.mismatches() == [Mismatch(MIN_POWER, 3.0, Estimate(6.0, Source.MEASURED, 0.5))]


@pytest.mark.parametrize(
    ("key", "entered", "measured"),
    [
        (HYSTERESIS, 5.0, 7.0),  # exactly the absolute tolerance (2 K)
        (MIN_POWER, 5.0, 6.0),  # exactly the relative tolerance (20 % of 5 kW)
    ],
)
def test_a_difference_of_exactly_the_tolerance_is_no_mismatch(
    key: ParameterKey, entered: float, measured: float
) -> None:
    """Negative: declared and measured values mismatch only when they differ by more than the
    tolerance, not by exactly it."""
    params = (
        ParameterSet()
        .with_estimate(key, Estimate(entered, Source.ENTERED))
        .with_estimate(key, Estimate(measured, Source.MEASURED, 0.9))
    )
    assert params.mismatches() == []
