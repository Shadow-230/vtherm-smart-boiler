"""Signal check: health per signal, features from mapped signals, outdoor sensor plausibility."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import BoilerSnapshot, Reading
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signal_check import (
    Feature,
    FeatureStatus,
    OutdoorStatus,
    SignalHealth,
    SignalStatus,
    check_outdoor,
    check_signals,
    curve_sensor,
    features,
    required_problems,
)
from custom_components.vtherm_smart_boiler.core.signals import Signal

HOUR = 3600.0
NOW = 100 * HOUR


def test_signal_health() -> None:
    """One freshness rule for the monitor and control: a steady reading is not a stale one —
    many sources report only on change — so without a limit the user set, age never counts."""
    snapshot = BoilerSnapshot(
        NOW,
        {
            Signal.FLAME: Reading(False, NOW - 20 * HOUR),
            Signal.FLOW: Reading(40.0, NOW - 2 * HOUR),  # steady for two hours
            Signal.RETURN: Reading(None, NOW),
            Signal.PRESSURE: Reading(1.5, NOW - HOUR),
        },
    )
    health = check_signals(snapshot)
    assert health[Signal.FLAME] == SignalHealth(SignalStatus.OK, True, 20 * HOUR)
    assert health[Signal.FLOW] == SignalHealth(SignalStatus.OK, True, 2 * HOUR)
    assert health[Signal.RETURN].status is SignalStatus.UNAVAILABLE
    assert health[Signal.PRESSURE].status is SignalStatus.OK
    assert health[Signal.GAS_METER] == SignalHealth(SignalStatus.NOT_MAPPED, False)
    assert set(health) == set(Signal)
    assert required_problems(health) == []
    limited = check_signals(snapshot, {Signal.FLOW: HOUR})
    assert limited[Signal.FLOW] == SignalHealth(SignalStatus.STALE, True, 2 * HOUR)
    assert required_problems(limited) == [Signal.FLOW]


def test_freshness_limits_can_be_overridden() -> None:
    snapshot = BoilerSnapshot(NOW, {Signal.FLOW: Reading(40.0, NOW - 2 * HOUR)})
    health = check_signals(snapshot, {Signal.FLOW: 3 * HOUR})
    assert health[Signal.FLOW].status is SignalStatus.OK
    no_limit = check_signals(snapshot, {Signal.FLOW: None})
    assert no_limit[Signal.FLOW].status is SignalStatus.OK


def test_minimal_mapping_enables_the_basics() -> None:
    result = features(
        frozenset({Signal.FLAME, Signal.FLOW}), has_weather=False, has_gas_rates=False
    )
    assert result[Feature.CYCLES].status is FeatureStatus.AVAILABLE
    assert result[Feature.HOT_WATER].status is FeatureStatus.AVAILABLE
    assert result[Feature.CONDENSING].missing == (Signal.RETURN,)
    assert result[Feature.DHW_DETECTION].status is FeatureStatus.DEGRADED
    assert result[Feature.GAS].status is FeatureStatus.UNAVAILABLE
    assert result[Feature.DEGREE_DAYS].status is FeatureStatus.UNAVAILABLE
    assert result[Feature.OUTDOOR_CHECK].status is FeatureStatus.UNAVAILABLE


def test_full_mapping() -> None:
    result = features(frozenset(Signal), has_weather=True, has_gas_rates=True)
    assert all(state.status is FeatureStatus.AVAILABLE for state in result.values())
    assert set(result) == set(Feature)


@pytest.mark.parametrize(
    ("mapped", "rates", "status"),
    [
        ({Signal.MODULATION}, True, FeatureStatus.DEGRADED),
        ({Signal.MODULATION}, False, FeatureStatus.UNAVAILABLE),
        ({Signal.GAS_METER}, False, FeatureStatus.AVAILABLE),
    ],
)
def test_gas_feature(mapped: set[Signal], rates: bool, status: FeatureStatus) -> None:
    result = features(frozenset({Signal.FLAME, Signal.FLOW, *mapped}), False, rates)
    assert result[Feature.GAS].status is status


def test_degree_days_from_weather_only_is_degraded() -> None:
    result = features(frozenset({Signal.FLAME, Signal.FLOW}), has_weather=True, has_gas_rates=False)
    assert result[Feature.DEGREE_DAYS].status is FeatureStatus.DEGRADED


def hourly(values: list[float | None]) -> Series[float]:
    return Series([(i * HOUR, v) for i, v in enumerate(values)])


def test_outdoor_agrees() -> None:
    sensor = hourly([5.0, 6.0, 7.0, 6.5, 6.0])
    weather = hourly([4.0, 5.5, 6.0, 6.0, 5.0])
    result = check_outdoor(sensor, weather, 0, 5 * HOUR)
    assert result.status is OutdoorStatus.OK
    assert result.mean_difference == pytest.approx(0.8)
    assert result.overlap_s == 5 * HOUR


def test_outdoor_deviates() -> None:
    sensor = hourly([15.0, 16.0, 17.0])
    weather = hourly([5.0, 6.0, 7.0])
    result = check_outdoor(sensor, weather, 0, 3 * HOUR)
    assert result.status is OutdoorStatus.DEVIATES
    assert result.mean_difference == pytest.approx(10.0)


def test_outdoor_stuck() -> None:
    sensor = Series([(0, 3.0)])
    weather = hourly([float(v) for v in range(13)])
    assert check_outdoor(sensor, weather, 0, 13 * HOUR).status is OutdoorStatus.STUCK


def test_outdoor_unknown_without_overlap() -> None:
    sensor = hourly([5.0, None, None])
    weather = hourly([None, 5.0, 5.0])
    assert check_outdoor(sensor, weather, 0, 3 * HOUR).status is OutdoorStatus.UNKNOWN


@pytest.mark.parametrize(
    ("status", "sensor", "weather", "used"),
    [
        (OutdoorStatus.OK, -5.0, 0.0, -5.0),
        (None, -5.0, None, -5.0),  # not judged yet
        (OutdoorStatus.STUCK, -5.0, 0.0, None),  # never a frozen value
        (OutdoorStatus.STUCK, 5.0, 0.0, None),
        # Deviating: the colder of the two — more heat, which the valves throttle; the warmer
        # could leave the house cold (a sensor in a cold-air pool, a weather entity elsewhere).
        (OutdoorStatus.DEVIATES, -9.0, -2.0, -9.0),
        (OutdoorStatus.DEVIATES, 4.0, -2.0, None),  # the weather entity's colder value then
        (OutdoorStatus.DEVIATES, -9.0, None, -9.0),  # nothing colder to fall back on
        (OutdoorStatus.OK, None, 0.0, None),
    ],
)
def test_what_the_curve_takes_from_the_outdoor_sensor(
    status: OutdoorStatus | None, sensor: float | None, weather: float | None, used: float | None
) -> None:
    """A3: a deviating sensor is dropped only where the weather entity reads colder."""
    assert curve_sensor(status, sensor, weather) == used
