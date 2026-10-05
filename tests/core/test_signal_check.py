"""Signal check: health per signal, features from mapped signals, outdoor sensor plausibility."""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.vtherm_smart_boiler.core.readings import BoilerSnapshot, Reading
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signal_check import (
    ADD_WATER_THRESHOLD,
    CONTROL,
    ENTITY_FOR_TWO_SIGNALS,
    ControlKind,
    Feature,
    FeatureState,
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
    assert result[Feature.GAS].status is FeatureStatus.INACTIVE
    assert result[Feature.DEGREE_DAYS].status is FeatureStatus.INACTIVE
    assert result[Feature.OUTDOOR_CHECK].status is FeatureStatus.INACTIVE


# Everything an installation can give, on a water-temperature path: a gateway with an OpenTherm
# thermostat, every signal but the relay's power, a circuit with its maximum.
EVERYTHING = frozenset(Signal)
FULL: dict[str, Any] = {
    "add_water": True,
    "zone_valves": True,
    "zone_data": True,
    "has_dhw": True,
    "condensing": True,
    "control": ControlKind.WATER,
    "circuit_maximum": True,
    "wall_thermostat": True,
    "comfort_correction": True,  # off by default since K4.1: switched on here
}


def test_full_mapping() -> None:
    result = features(EVERYTHING, has_weather=True, has_gas_rates=True, **FULL)
    assert set(result) == set(Feature)
    inactive = {f for f, state in result.items() if state.status is not FeatureStatus.AVAILABLE}
    # Decision 2 of 0.2.3 (SB-01): a water path's proof of heat is its flame or its flow.
    assert inactive == set()
    relay = features(
        EVERYTHING,
        has_weather=True,
        has_gas_rates=True,
        **(FULL | {"control": ControlKind.RELAY, "wall_thermostat": False}),
    )
    inactive = {f for f, state in relay.items() if state.status is not FeatureStatus.AVAILABLE}
    # A relay sets no water temperature, and a gateway's wall thermostat is no relay's.
    assert inactive == {Feature.COMFORT_CORRECTION, Feature.WALL_THERMOSTAT_FALLBACK}


# The missing-data rule (Y4): for each feature of the table, each required input taken away —
# (feature, what changes, the status then, the codes it names). A signal is taken off the
# mapping; every other input is a keyword of ``features``.
CASES: list[tuple[Feature, dict[str, Any], FeatureStatus, tuple[str, ...]]] = [
    (Feature.CYCLES, {"without": {Signal.FLAME}}, FeatureStatus.INACTIVE, ("flame",)),
    (Feature.CONDENSING, {"without": {Signal.FLAME}}, FeatureStatus.INACTIVE, ("flame",)),
    (Feature.CONDENSING, {"without": {Signal.RETURN}}, FeatureStatus.INACTIVE, ("return",)),
    (
        Feature.DHW_DETECTION,
        {"without": {Signal.DHW_ACTIVE}},
        FeatureStatus.DEGRADED,
        ("dhw_active",),
    ),
    (
        Feature.DHW_DETECTION,
        {"without": {Signal.DHW_ACTIVE, Signal.CH_ACTIVE, Signal.FLOW}},
        FeatureStatus.INACTIVE,
        ("dhw_active",),
    ),
    (Feature.GAS, {"without": {Signal.GAS_METER}}, FeatureStatus.DEGRADED, ("gas_meter",)),
    (
        Feature.GAS,
        {"without": {Signal.GAS_METER}, "has_gas_rates": False},
        FeatureStatus.INACTIVE,
        ("gas_meter",),
    ),
    (Feature.DEGREE_DAYS, {"without": {Signal.OUTDOOR}}, FeatureStatus.DEGRADED, ("outdoor",)),
    (
        Feature.DEGREE_DAYS,
        {"without": {Signal.OUTDOOR}, "has_weather": False},
        FeatureStatus.INACTIVE,
        ("outdoor", "weather_entity"),
    ),
    (Feature.HOT_WATER, {"without": {Signal.FLOW}}, FeatureStatus.INACTIVE, ("flow",)),
    (
        Feature.HOT_WATER,
        {"without": {Signal.FLOW}, "circuit_flow": True},
        FeatureStatus.DEGRADED,
        ("flow",),
    ),
    (Feature.EMITTER_FACTOR, {"without": {Signal.FLOW}}, FeatureStatus.INACTIVE, ("flow",)),
    (
        Feature.FLUE_GAS_WARNING,
        {"without": {Signal.FLUE_GAS}},
        FeatureStatus.INACTIVE,
        ("flue_gas",),
    ),
    (
        Feature.FLUE_GAS_WARNING,
        {"condensing": False},
        FeatureStatus.INACTIVE,
        ("condensing_boiler",),
    ),
    # The absolute alarm needs no return; only the trend over the return does.
    (Feature.FLUE_GAS_WARNING, {"without": {Signal.RETURN}}, FeatureStatus.DEGRADED, ("return",)),
    (
        Feature.PRESSURE_WARNING,
        {"without": {Signal.PRESSURE}},
        FeatureStatus.INACTIVE,
        ("pressure",),
    ),
    (Feature.ADD_WATER, {"without": {Signal.PRESSURE}}, FeatureStatus.INACTIVE, ("pressure",)),
    (
        Feature.ADD_WATER,
        {"add_water": False},
        FeatureStatus.INACTIVE,
        ("add_water_threshold",),
    ),
    *(
        (Feature.PRESSURE_TREND, {"without": {signal}}, FeatureStatus.INACTIVE, (signal.value,))
        for signal in (Signal.PRESSURE, Signal.FLAME, Signal.FLOW)
    ),
    *(
        (Feature.HYSTERESIS_DRIFT, {"without": {signal}}, FeatureStatus.INACTIVE, (signal.value,))
        for signal in (Signal.FLOW, Signal.FLAME)
    ),
    (Feature.HYSTERESIS_DRIFT, {"zone_data": False}, FeatureStatus.INACTIVE, ("zone_data",)),
    (
        Feature.UNSTABLE_IGNITION,
        {"without": {Signal.FLAME}},
        FeatureStatus.INACTIVE,
        ("flame",),
    ),
    (
        Feature.UNSTABLE_IGNITION,
        {"without": {Signal.FLOW}},
        FeatureStatus.DEGRADED,
        ("flow",),
    ),
    (
        Feature.UNSTABLE_IGNITION,
        {"without": {Signal.CH_SETPOINT}},
        FeatureStatus.DEGRADED,
        ("ch_setpoint",),
    ),
    (
        Feature.LOW_FLOW,
        {"without": {Signal.PUMP_RUNNING, Signal.CH_ACTIVE}},
        FeatureStatus.INACTIVE,
        ("pump_running", "ch_active"),
    ),
    (Feature.LOW_FLOW, {"zone_valves": False}, FeatureStatus.INACTIVE, ("valve_openings",)),
    (Feature.LOW_FLOW, {"zone_data": False}, FeatureStatus.INACTIVE, ("valve_openings",)),
    (Feature.LOW_FLOW, {"bypass": True}, FeatureStatus.INACTIVE, ("no_bypass",)),
    (
        Feature.LOW_FLOW,
        {"without": {Signal.DHW_ACTIVE}},
        FeatureStatus.INACTIVE,
        ("dhw_active",),
    ),
    (
        Feature.OUTDOOR_CHECK,
        {"without": {Signal.OUTDOOR}},
        FeatureStatus.INACTIVE,
        ("outdoor",),
    ),
    (Feature.OUTDOOR_CHECK, {"has_weather": False}, FeatureStatus.INACTIVE, ("weather_entity",)),
    (
        Feature.BOILER_FAULT_STOP,
        {"without": {Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT}},
        FeatureStatus.INACTIVE,
        ("low_pressure_fault", "boiler_lockout"),
    ),
    (Feature.BOILER_FAULT_STOP, {"control": None}, FeatureStatus.INACTIVE, ("control",)),
    (Feature.VERDICT, {"without": {Signal.FLAME}}, FeatureStatus.INACTIVE, ("flame",)),
    (Feature.COMFORT_CORRECTION, {"control": None}, FeatureStatus.INACTIVE, ("control",)),
    (
        Feature.COMFORT_CORRECTION,
        {"control": ControlKind.RELAY},
        FeatureStatus.INACTIVE,
        ("water_control",),
    ),
    (Feature.COMFORT_CORRECTION, {"zone_data": False}, FeatureStatus.INACTIVE, ("zone_data",)),
    (
        Feature.COMFORT_CORRECTION,
        {"comfort_correction": False},
        FeatureStatus.INACTIVE,
        ("turned_off",),
    ),
    (Feature.FROST_PROTECTION, {"control": None}, FeatureStatus.INACTIVE, ("control",)),
    (Feature.FROST_PROTECTION, {"zone_data": False}, FeatureStatus.INACTIVE, ("zone_data",)),
    (Feature.ACTIVATION_DELAY, {"control": None}, FeatureStatus.INACTIVE, ("control",)),
    (
        Feature.CIRCUIT_OVERSHOOT_ALARM,
        {"without": {Signal.FLOW}},
        FeatureStatus.INACTIVE,
        ("flow",),
    ),
    (
        Feature.CIRCUIT_OVERSHOOT_ALARM,
        {"circuit_maximum": False},
        FeatureStatus.INACTIVE,
        ("circuit_maximum",),
    ),
    *(
        (
            Feature.LOWEST_WATER_SUGGESTION,
            {"without": {signal}},
            FeatureStatus.INACTIVE,
            (signal.value,),
        )
        for signal in (Signal.FLAME, Signal.FLOW, Signal.CH_SETPOINT)
    ),
    (
        Feature.WALL_THERMOSTAT_FALLBACK,
        {"wall_thermostat": False},
        FeatureStatus.INACTIVE,
        ("wall_thermostat",),
    ),
    (
        Feature.WALL_THERMOSTAT_FALLBACK,
        {"without": {Signal.ROOM_SETPOINT}},
        FeatureStatus.INACTIVE,
        ("room_setpoint",),
    ),
    (Feature.RELAY_PROOF, {"control": None}, FeatureStatus.INACTIVE, ("control",)),
    (
        Feature.RELAY_PROOF,
        {"control": ControlKind.WATER, "without": {Signal.FLAME, Signal.FLOW}},
        FeatureStatus.INACTIVE,
        ("flame", "flow"),
    ),
    (
        Feature.RELAY_PROOF,
        {
            "control": ControlKind.RELAY,
            "without": {Signal.FLAME, Signal.FLOW, Signal.GAS_METER, Signal.BOILER_POWER},
        },
        FeatureStatus.INACTIVE,
        ("flame", "flow", "gas_meter", "boiler_power"),
    ),
    (Feature.FORECASTS, {"has_weather": False}, FeatureStatus.INACTIVE, ("weather_entity",)),
]


@pytest.mark.parametrize(
    ("feature", "change", "status", "missing"),
    CASES,
    ids=[f"{case[0].value}-{index}" for index, case in enumerate(CASES)],
)
def test_every_feature_names_what_it_lacks(
    feature: Feature, change: dict[str, Any], status: FeatureStatus, missing: tuple[str, ...]
) -> None:
    """The missing-data rule: a feature whose input is missing is inactive — or degraded where
    it works from a weaker one — and names it, a code with a translated text."""
    change = dict(change)
    mapped = EVERYTHING - change.pop("without", set())
    arguments = {"has_weather": True, "has_gas_rates": True, **FULL}
    if feature is Feature.RELAY_PROOF:
        arguments |= {"control": ControlKind.RELAY, "power_threshold": True}
    arguments |= change
    weather = arguments.pop("has_weather")
    rates = arguments.pop("has_gas_rates")
    result = features(mapped, weather, rates, **arguments)[feature]
    assert (result.status, result.missing) == (status, missing)
    assert all(isinstance(code, str) for code in result.missing)
    full = features(EVERYTHING, True, True, **(FULL | _path(feature)))[feature]
    assert full.status is FeatureStatus.AVAILABLE, feature  # the input is what it lacked


def _path(feature: Feature) -> dict[str, Any]:
    if feature is Feature.RELAY_PROOF:
        return {"control": ControlKind.RELAY, "power_threshold": True}
    return {}


def test_a_signal_whose_entity_feeds_an_earlier_one_is_named_so() -> None:
    """X5: one entity mapped to two signals is kept for the first; the later signal is dropped,
    and each feature that needs it names it with ``entity_for_two_signals`` and the signal that
    kept the entity."""
    result = features(
        EVERYTHING - {Signal.RETURN},
        True,
        True,
        **FULL,
        shared={Signal.RETURN: Signal.FLOW},
    )
    condensing = result[Feature.CONDENSING]
    assert (condensing.status, condensing.missing) == (
        FeatureStatus.INACTIVE,
        (ENTITY_FOR_TWO_SIGNALS,),
    )
    assert condensing.shared == ((Signal.RETURN, Signal.FLOW),)
    flue = result[Feature.FLUE_GAS_WARNING]
    assert (flue.status, flue.missing, flue.shared) == (
        FeatureStatus.DEGRADED,
        (ENTITY_FOR_TWO_SIGNALS,),
        ((Signal.RETURN, Signal.FLOW),),
    )
    # Negative: a feature that does not need the dropped signal names nothing.
    assert result[Feature.CYCLES] == FeatureState(FeatureStatus.AVAILABLE)


def test_nothing_known_names_every_input() -> None:
    """Negative: with no input at all, every feature is inactive or degraded and names what it
    lacks — none is inactive without a code."""
    result = features(frozenset(), False, False, zone_data=False)
    for feature, state in result.items():
        assert state.status is FeatureStatus.INACTIVE, feature
        assert state.missing, feature


def test_the_y1_features_name_what_they_lack() -> None:
    """Y1 (P-99 and the missing-data rule): each feature says why it is inactive — a signal to
    map, or another input, each a code."""
    nothing = features(frozenset(), False, False)
    low_flow = nothing[Feature.LOW_FLOW]
    assert (low_flow.status, low_flow.missing) == (
        FeatureStatus.INACTIVE,
        (Signal.PUMP_RUNNING, Signal.CH_ACTIVE),
    )
    fault = nothing[Feature.BOILER_FAULT_STOP]
    assert (fault.status, fault.missing) == (
        FeatureStatus.INACTIVE,
        (CONTROL, Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT),
    )
    assert nothing[Feature.ADD_WATER].missing == (Signal.PRESSURE, ADD_WATER_THRESHOLD)
    assert nothing[Feature.PRESSURE_TREND].missing == (Signal.PRESSURE, Signal.FLAME, Signal.FLOW)
    assert nothing[Feature.HYSTERESIS_DRIFT].missing == (Signal.FLAME, Signal.FLOW)
    pump = frozenset({Signal.PUMP_RUNNING})
    assert features(pump, False, False)[Feature.LOW_FLOW].status is FeatureStatus.AVAILABLE
    # P-27: a boiler with hot water needs the hot-water signal, or hot water stays unknown.
    combi = features(pump, False, False, has_dhw=True)[Feature.LOW_FLOW]
    assert (combi.status, combi.missing) == (FeatureStatus.INACTIVE, (Signal.DHW_ACTIVE,))
    told = features(pump | {Signal.DHW_ACTIVE}, False, False, has_dhw=True)[Feature.LOW_FLOW]
    assert told.status is FeatureStatus.AVAILABLE
    # Zones whose valves are not known yet do not make the warning inactive.
    assert features(pump, False, False, zone_valves=None)[Feature.LOW_FLOW].status is (
        FeatureStatus.AVAILABLE
    )


def test_a_gateway_fault_flag_needs_the_fault_indication() -> None:
    """Q3.9: a fault flag the OpenTherm Gateway reports counts only with the boiler's fault
    indication mapped — without it that flag stops nothing, and the feature names it; one from
    elsewhere counts alone."""
    flags = frozenset({Signal.LOW_PRESSURE_FAULT})
    water = {"control": ControlKind.WATER}
    gated = features(flags, False, False, gateway=flags, **water)[Feature.BOILER_FAULT_STOP]
    assert (gated.status, gated.missing) == (FeatureStatus.INACTIVE, (Signal.FAULT_INDICATION,))
    both = features(flags | {Signal.FAULT_INDICATION}, False, False, gateway=flags, **water)
    assert both[Feature.BOILER_FAULT_STOP].status is FeatureStatus.AVAILABLE
    mixed = features(flags | {Signal.BOILER_LOCKOUT}, False, False, gateway=flags, **water)[
        Feature.BOILER_FAULT_STOP
    ]
    assert (mixed.status, mixed.missing) == (FeatureStatus.DEGRADED, (Signal.FAULT_INDICATION,))
    alone = features(flags, False, False, **water)[Feature.BOILER_FAULT_STOP]
    assert alone.status is FeatureStatus.AVAILABLE
    relay = features(flags, False, False, control=ControlKind.RELAY)[Feature.BOILER_FAULT_STOP]
    assert relay.status is FeatureStatus.AVAILABLE  # the relay stops for it too (Y1)


def test_the_relay_proof_counts_the_power_only_with_its_threshold() -> None:
    """X8 (R12): the boiler's electric power proves heat only against the threshold the user
    gave; without it, and with no other proof input, the proof is inactive."""
    power = frozenset({Signal.BOILER_POWER})
    relay = {"control": ControlKind.RELAY}
    without = features(power, False, False, **relay)[Feature.RELAY_PROOF]
    assert without.status is FeatureStatus.INACTIVE
    with_threshold = features(power, False, False, power_threshold=True, **relay)
    assert with_threshold[Feature.RELAY_PROOF].status is FeatureStatus.AVAILABLE


def test_a_water_path_proves_heat_by_its_flame_or_its_flow() -> None:
    """Decision 2 of 0.2.3 (SB-01): "no sign the boiler heats" on the water-temperature paths
    judges the flame, else the flow — either one makes it available; the gas meter and the
    power, which only the relay's proof reads, do not."""
    water = {"control": ControlKind.WATER}
    for signals in ({Signal.FLAME}, {Signal.FLOW}):
        state = features(frozenset(signals), False, False, **water)[Feature.RELAY_PROOF]
        assert state.status is FeatureStatus.AVAILABLE, signals
    others = frozenset({Signal.GAS_METER, Signal.BOILER_POWER})
    state = features(others, False, False, power_threshold=True, **water)[Feature.RELAY_PROOF]
    assert (state.status, state.missing) == (FeatureStatus.INACTIVE, ("flame", "flow"))


def test_the_suggestion_takes_the_read_back_for_the_ch_setpoint() -> None:
    """X6: without the CH setpoint signal, control's read-back is the suggestion's setpoint."""
    mapped = frozenset({Signal.FLAME, Signal.FLOW})
    alone = features(mapped, False, False)[Feature.LOWEST_WATER_SUGGESTION]
    assert (alone.status, alone.missing) == (FeatureStatus.INACTIVE, (Signal.CH_SETPOINT,))
    read_back = features(mapped, False, False, read_back=True)[Feature.LOWEST_WATER_SUGGESTION]
    assert read_back.status is FeatureStatus.AVAILABLE


@pytest.mark.parametrize(
    ("mapped", "rates", "status"),
    [
        ({Signal.MODULATION}, True, FeatureStatus.DEGRADED),
        ({Signal.MODULATION}, False, FeatureStatus.INACTIVE),
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
