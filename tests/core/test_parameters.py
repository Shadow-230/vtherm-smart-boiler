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
