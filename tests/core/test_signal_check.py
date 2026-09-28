"""Signal check: health per signal, features from mapped signals, outdoor sensor plausibility."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import BoilerSnapshot, Reading
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signal_check import (
    Feature,
    FeatureStatus,
    OutdoorCheck,
    OutdoorStatus,
    SignalHealth,
    SignalStatus,
    check_outdoor,
    check_signals,
    curve_sensor,
    features,
    link_connected,
    link_problems,
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
    assert link_problems(health) == []
    limited = check_signals(snapshot, {Signal.FLOW: HOUR})
    assert limited[Signal.FLOW] == SignalHealth(SignalStatus.STALE, True, 2 * HOUR)
    assert link_problems(limited) == [Signal.FLOW]


def test_the_connection_follows_the_mapped_link_signals_and_the_relay() -> None:
    """X8 (R4): on while every mapped link signal is OK and, on the relay path, the relay is
    within reach; unknown with no link signal mapped and no relay."""
    fresh = BoilerSnapshot(
        NOW, {Signal.FLAME: Reading(False, NOW), Signal.FLOW: Reading(40.0, NOW)}
    )
    flame_only = BoilerSnapshot(NOW, {Signal.FLAME: Reading(False, NOW)})
    lost = BoilerSnapshot(NOW, {Signal.FLAME: Reading(None, NOW)})
    nothing = BoilerSnapshot(NOW, {})
    assert link_connected(check_signals(fresh)) is True
    assert link_connected(check_signals(flame_only)) is True  # the flow not mapped: no problem
    assert link_problems(check_signals(flame_only)) == []
    assert link_connected(check_signals(lost)) is False
    assert link_problems(check_signals(lost)) == [Signal.FLAME]
    assert link_connected(check_signals(nothing)) is None
    assert link_connected(check_signals(nothing), relay_reachable=True) is True
    assert link_connected(check_signals(nothing), relay_reachable=False) is False
    assert link_connected(check_signals(fresh), relay_reachable=False) is False
    assert link_connected(check_signals(lost), relay_reachable=True) is False


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
    result = features(frozenset(Signal), has_weather=True, has_gas_rates=True, add_water=True)
    assert all(state.status is FeatureStatus.AVAILABLE for state in result.values())
    assert set(result) == set(Feature)


def test_the_y1_features_name_what_they_lack() -> None:
    """Y1 (P-99 and the missing-data rule): each feature says why it is inactive — a signal to
    map, or a reason that is no signal."""
    nothing = features(frozenset(), False, False)
    low_flow = nothing[Feature.LOW_FLOW]
    assert (low_flow.status, low_flow.missing) == (
        FeatureStatus.UNAVAILABLE,
        (Signal.PUMP_RUNNING, Signal.CH_ACTIVE),
    )
    fault = nothing[Feature.BOILER_FAULT_STOP]
    assert (fault.status, fault.missing) == (
        FeatureStatus.UNAVAILABLE,
        (Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT),
    )
    assert nothing[Feature.ADD_WATER].missing == (Signal.PRESSURE,)
    assert nothing[Feature.PRESSURE_TREND].missing == (Signal.PRESSURE, Signal.FLAME, Signal.FLOW)
    assert nothing[Feature.HYSTERESIS_DRIFT].missing == (Signal.FLAME, Signal.FLOW)
    pressure = features(frozenset({Signal.PRESSURE}), False, False)
    add_water = pressure[Feature.ADD_WATER]
    assert (add_water.status, add_water.reason) == (FeatureStatus.UNAVAILABLE, "no_threshold")
    assert (
        features(frozenset({Signal.PRESSURE}), False, False, add_water=True)[
            Feature.ADD_WATER
        ].status
        is FeatureStatus.AVAILABLE
    )
    pump = frozenset({Signal.PUMP_RUNNING})
    assert features(pump, False, False)[Feature.LOW_FLOW].status is FeatureStatus.AVAILABLE
    bypass = features(pump, False, False, bypass=True)[Feature.LOW_FLOW]
    assert (bypass.status, bypass.reason) == (FeatureStatus.UNAVAILABLE, "bypass")
    valves = features(pump, False, False, zone_valves=False)[Feature.LOW_FLOW]
    assert (valves.status, valves.reason) == (FeatureStatus.UNAVAILABLE, "zone_without_valve")
    # P-27: a boiler with hot water needs the hot-water signal, or hot water stays unknown.
    combi = features(pump, False, False, has_dhw=True)[Feature.LOW_FLOW]
    assert (combi.status, combi.missing) == (FeatureStatus.UNAVAILABLE, (Signal.DHW_ACTIVE,))
    told = features(pump | {Signal.DHW_ACTIVE}, False, False, has_dhw=True)[Feature.LOW_FLOW]
    assert told.status is FeatureStatus.AVAILABLE
    drift = features(frozenset({Signal.FLAME, Signal.FLOW}), False, False, zone_data=False)
    assert drift[Feature.HYSTERESIS_DRIFT].reason == "no_zone_data"


def test_a_gateway_fault_flag_needs_the_fault_indication() -> None:
    """Q3.9: a fault flag the OpenTherm Gateway reports counts only with the boiler's fault
    indication mapped — without it that flag stops nothing, and the feature names it; one from
    elsewhere counts alone."""
    flags = frozenset({Signal.LOW_PRESSURE_FAULT})
    gated = features(flags, False, False, gateway=flags)[Feature.BOILER_FAULT_STOP]
    assert (gated.status, gated.missing) == (FeatureStatus.UNAVAILABLE, (Signal.FAULT_INDICATION,))
    both = features(flags | {Signal.FAULT_INDICATION}, False, False, gateway=flags)
    assert both[Feature.BOILER_FAULT_STOP].status is FeatureStatus.AVAILABLE
    mixed = features(flags | {Signal.BOILER_LOCKOUT}, False, False, gateway=flags)[
        Feature.BOILER_FAULT_STOP
    ]
    assert (mixed.status, mixed.missing) == (FeatureStatus.DEGRADED, (Signal.FAULT_INDICATION,))
    alone = features(flags, False, False)[Feature.BOILER_FAULT_STOP]
    assert alone.status is FeatureStatus.AVAILABLE


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


def test_outdoor_stuck_is_detected_within_twelve_hours() -> None:
    """T-16 (P-26): in the day's window the sensor follows the weather for 8 h, then keeps one
    value for 16 h while the weather falls 4 K — stuck, judged on the tail since its last change
    (12 h at least), not on the whole day."""
    weather = Series([(i * HOUR, 5.0 - max(0, i - 8) * 0.25) for i in range(25)])
    sensor = Series([(i * HOUR, 5.0 + 0.1 * i) for i in range(9)])  # changes until 8 h
    result = check_outdoor(sensor, weather, 0, 24 * HOUR)
    assert result.status is OutdoorStatus.STUCK


def test_a_sensor_that_last_changed_eleven_hours_ago_is_not_stuck() -> None:
    """Negative: the tail since the last change is 11 h — not stuck yet, even though the weather
    moved 3 K over it; nor is a tail of 12 h over which the weather moved less than 3 K."""
    weather = Series([(i * HOUR, 5.0 - max(0, i - 13) * 0.3) for i in range(25)])
    sensor = Series([(i * HOUR, 5.0 + 0.01 * i) for i in range(14)])  # last change at 13 h
    assert check_outdoor(sensor, weather, 0, 24 * HOUR).status is not OutdoorStatus.STUCK
    calm = Series([(i * HOUR, 5.0 - max(0, i - 12) * 0.2) for i in range(25)])  # 2.4 K
    still = Series([(i * HOUR, 5.0 + 0.01 * i) for i in range(13)])  # last change at 12 h
    assert check_outdoor(still, calm, 0, 24 * HOUR).status is not OutdoorStatus.STUCK


def test_an_unknown_stretch_does_not_end_the_stuck_tail() -> None:
    """A frozen sensor that drops out for a while and comes back with the same value is still
    the same value: the stretch without a value neither ends the tail nor counts toward its
    12 h."""
    weather = Series([(i * HOUR, 5.0 - i * 0.25) for i in range(25)])
    sensor = Series([(0, 3.0), (6 * HOUR, None), (8 * HOUR, 3.0)])
    assert check_outdoor(sensor, weather, 0, 24 * HOUR).status is OutdoorStatus.STUCK
    gap = Series([(0, 3.0), (4 * HOUR, None), (14 * HOUR, 3.0)])  # 14 h known in all
    assert check_outdoor(gap, weather, 0, 24 * HOUR).status is OutdoorStatus.STUCK
    short = Series([(0, 3.0), (2 * HOUR, None), (15 * HOUR, 3.0)])  # 11 h known
    assert check_outdoor(short, weather, 0, 24 * HOUR).status is not OutdoorStatus.STUCK


def test_outdoor_unknown_without_overlap() -> None:
    sensor = hourly([5.0, None, None])
    weather = hourly([None, 5.0, 5.0])
    assert check_outdoor(sensor, weather, 0, 3 * HOUR).status is OutdoorStatus.UNKNOWN


@pytest.mark.parametrize(
    ("status", "difference", "sensor", "weather", "used"),
    [
        (OutdoorStatus.OK, 0.0, -5.0, 0.0, -5.0),
        (None, None, -5.0, None, -5.0),  # not judged yet
        (OutdoorStatus.STUCK, 0.0, -5.0, 0.0, None),  # never a frozen value
        (OutdoorStatus.STUCK, 0.0, 5.0, 0.0, None),
        # Deviating: the colder of the two — more heat, which the valves throttle; the warmer
        # could leave the house cold (a sensor in a cold-air pool, a weather entity elsewhere).
        (OutdoorStatus.DEVIATES, -7.0, -9.0, -2.0, -9.0),
        (OutdoorStatus.DEVIATES, 7.0, 4.0, -2.0, None),  # the weather entity's colder value then
        (OutdoorStatus.DEVIATES, 7.0, -9.0, -2.0, -9.0),  # colder now, whatever it was
        # Without a weather reading, what the check saw over the day tells which is colder: the
        # sensor that has been the colder one is used, the warmer one gives way to the held
        # value and the fallback — which ask for more heat, not less (R6, A3).
        (OutdoorStatus.DEVIATES, -7.0, -9.0, None, -9.0),
        (OutdoorStatus.DEVIATES, 7.0, 4.0, None, None),
        (OutdoorStatus.OK, 0.0, None, 0.0, None),
    ],
)
def test_what_the_curve_takes_from_the_outdoor_sensor(
    status: OutdoorStatus | None,
    difference: float | None,
    sensor: float | None,
    weather: float | None,
    used: float | None,
) -> None:
    """A3: a deviating sensor is used only while it reads colder than the weather entity."""
    check = None if status is None else OutdoorCheck(status, difference, 86400.0)
    assert curve_sensor(check, sensor, weather) == used
