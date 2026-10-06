"""Signal check: which signals are mapped, present and fresh, what that enables, and whether
the boiler's outdoor sensor agrees with the weather entity."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .readings import BoilerSnapshot
from .series import Series
from .signals import SIGNAL_SPECS, Signal

HOUR = 3600.0


class SignalStatus(StrEnum):
    OK = "ok"
    NOT_MAPPED = "not_mapped"
    UNAVAILABLE = "unavailable"  # mapped, but no usable value
    STALE = "stale"  # not reported for longer than its freshness limit


@dataclass(frozen=True, slots=True)
class SignalHealth:
    status: SignalStatus
    link: bool  # part of the boiler link (``SignalSpec.link``)
    age_s: float | None = None


def check_signals(
    snapshot: BoilerSnapshot, max_ages: Mapping[Signal, float | None] | None = None
) -> dict[Signal, SignalHealth]:
    """Health of every signal; ``max_ages``: the age limits the user set (none: availability)."""
    result: dict[Signal, SignalHealth] = {}
    for signal, spec in SIGNAL_SPECS.items():
        max_age = (max_ages or {}).get(signal)
        if not snapshot.is_mapped(signal):
            result[signal] = SignalHealth(SignalStatus.NOT_MAPPED, spec.link)
            continue
        reading = snapshot.reading(signal)
        age = reading.age(snapshot.t)
        if reading.value is None:
            status = SignalStatus.UNAVAILABLE
        elif not reading.is_fresh(snapshot.t, max_age):
            status = SignalStatus.STALE
        else:
            status = SignalStatus.OK
        result[signal] = SignalHealth(status, spec.link, age)
    return result


def link_problems(health: Mapping[Signal, SignalHealth]) -> list[Signal]:
    """The boiler link's mapped signals that are not OK; an unmapped one is none (X8)."""
    return [
        s
        for s, h in health.items()
        if h.link and h.status not in (SignalStatus.OK, SignalStatus.NOT_MAPPED)
    ]


def link_connected(
    health: Mapping[Signal, SignalHealth], relay_reachable: bool | None = None
) -> bool | None:
    """The connection (X8, R4): every mapped link signal OK and, on the relay path, the relay
    within reach (``relay_reachable``; ``None``: no relay). Unknown with no link signal mapped
    and no relay: nothing tells."""
    mapped = [s for s, h in health.items() if h.link and h.status is not SignalStatus.NOT_MAPPED]
    if not mapped and relay_reachable is None:
        return None
    return not link_problems(health) and relay_reachable is not False


class Feature(StrEnum):
    """What the plugin does with the inputs an installation gives (the missing-data rule): each
    feature is available, degraded or inactive, and names what it lacks."""

    CYCLES = "cycles"
    CONDENSING = "condensing"
    DHW_DETECTION = "dhw_detection"
    GAS = "gas"
    DEGREE_DAYS = "degree_days"
    HOT_WATER = "hot_water"
    EMITTER_FACTOR = "emitter_factor"
    FLUE_GAS_WARNING = "flue_gas_warning"
    PRESSURE_WARNING = "pressure_warning"
    OUTDOOR_CHECK = "outdoor_check"
    # Y1: the low-flow warning (P-99), the stop on the boiler's own fault, the "add water"
    # notification, the pressure trend, unstable ignition (P-81) and hysteresis drift (P-29).
    LOW_FLOW = "low_flow"
    BOILER_FAULT_STOP = "boiler_fault_stop"
    ADD_WATER = "add_water"
    PRESSURE_TREND = "pressure_trend"
    UNSTABLE_IGNITION = "unstable_ignition"
    HYSTERESIS_DRIFT = "hysteresis_drift"
    # Y4: the verdict, and the features of phase X — the comfort correction, frost protection
    # and VT's activation delay (X4), the circuit's too-hot alarm (X4, decision 10), the lowest
    # water temperature's suggestion and the wall thermostat after a hand-back (X6), the relay's
    # proof that the boiler heats (X8; on the water paths too, decision 2 of 0.2.3) — and the
    # forecast snapshots.
    VERDICT = "verdict"
    COMFORT_CORRECTION = "comfort_correction"
    FROST_PROTECTION = "frost_protection"
    ACTIVATION_DELAY = "activation_delay"
    CIRCUIT_OVERSHOOT_ALARM = "circuit_overshoot_alarm"
    LOWEST_WATER_SUGGESTION = "lowest_water_suggestion"
    WALL_THERMOSTAT_FALLBACK = "wall_thermostat_fallback"
    RELAY_PROOF = "relay_proof"
    FORECASTS = "forecasts"


class FeatureStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"  # works, from weaker inputs (e.g. inferred instead of measured)
    INACTIVE = "inactive"  # an input it needs is missing, unknown or unavailable


# The inputs a feature may lack that are no signal — each a code in ``FeatureState.missing``,
# beside the signals' own (``Signal`` values), named in a translated text.
ADD_WATER_THRESHOLD = "add_water_threshold"  # the "add water" threshold, from the manual
# The high-pressure warning or alarm, from the safety valve's rating (decision 13 of 0.2.3).
PRESSURE_HIGH_THRESHOLD = "pressure_high_threshold"
CONDENSING_BOILER = "condensing_boiler"  # the boiler declared condensing
ZONE_DATA = "zone_data"  # VT zones configured, and at run time one known
VALVE_OPENINGS = "valve_openings"  # every zone reports its valve opening
NO_BYPASS = "no_bypass"  # no bypass or low-loss header declared
WEATHER_ENTITY = "weather_entity"  # the weather entity, and at run time its state
CONTROL = "control"  # control configured
WATER_CONTROL = "water_control"  # control that sets the water temperature, not a relay
RELAY_CONTROL = "relay_control"  # control through a relay
WALL_THERMOSTAT = "wall_thermostat"  # control through a gateway with an OpenTherm thermostat
CIRCUIT_MAXIMUM = "circuit_maximum"  # a circuit with a maximum flow temperature
TURNED_OFF = "turned_off"  # the option that runs it is off
# A signal dropped because its entity feeds an earlier signal (X5), in place of its own code.
ENTITY_FOR_TWO_SIGNALS = "entity_for_two_signals"


class ControlKind(StrEnum):
    """What control is configured to drive: the water temperature, or a relay (X8)."""

    WATER = "water"
    RELAY = "relay"


@dataclass(frozen=True, slots=True)
class FeatureState:
    status: FeatureStatus
    # The inputs it lacks — for an inactive feature what it needs, for a degraded one what
    # would make it whole: a signal's code, another input's (above), or, for a signal dropped
    # because its entity feeds an earlier one, ``ENTITY_FOR_TWO_SIGNALS``.
    missing: tuple[str, ...] = ()
    # For each ``ENTITY_FOR_TWO_SIGNALS`` in ``missing``, in order: the signal dropped and the
    # signal that kept its entity.
    shared: tuple[tuple[Signal, Signal], ...] = ()


# The boiler's own fault signals (Y1), in the order the form asks for them.
FAULT_SIGNALS = (Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT)
# What proves a relay's boiler heats (X8, R12): any one of them; the power with its threshold.
PROOF_SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.GAS_METER, Signal.BOILER_POWER)


def _state(required: list[str], improving: list[str] | None = None) -> FeatureState:
    """Inactive naming what is required and missing; else degraded naming what would make it
    whole; else available."""
    if required:
        return FeatureState(FeatureStatus.INACTIVE, tuple(required))
    if improving:
        return FeatureState(FeatureStatus.DEGRADED, tuple(improving))
    return FeatureState(FeatureStatus.AVAILABLE)


def features(
    mapped: frozenset[Signal],
    has_weather: bool,
    has_gas_rates: bool,
    *,
    add_water: bool = False,
    pressure_high: bool = False,
    bypass: bool = False,
    zone_valves: bool | None = None,
    zone_data: bool = True,
    gateway: frozenset[Signal] = frozenset(),
    has_dhw: bool = False,
    condensing: bool = True,
    control: ControlKind | None = None,
    comfort_correction: bool = False,
    circuit_maximum: bool = False,
    circuit_flow: bool = False,
    circuit_maximum_unmixed: bool = True,
    circuit_maximum_flow: bool = False,
    wall_thermostat: bool = False,
    read_back: bool = False,
    power_threshold: bool = False,
    shared: Mapping[Signal, Signal] | None = None,
) -> dict[Feature, FeatureState]:
    """What the inputs enable (the missing-data rule): each feature available, degraded or
    inactive, naming what it lacks. Configured, ``mapped`` holds the mapped signals and each
    flag what the options give; at run time the signals known now, and the flags what is known
    now. ``has_gas_rates``: gas at min and max power are known. Y1: ``add_water`` — the user
    entered the "add water" threshold; ``pressure_high`` — a high-pressure limit (decision 13
    of 0.2.3); ``bypass`` — a bypass or a low-loss header is declared;
    ``zone_valves`` — whether every zone reports a valve opening (``None``: not known yet);
    ``zone_data`` — zones are configured (at run time: one is known); ``gateway`` — the mapped
    signals the OpenTherm Gateway reports, whose fault flags need the fault indication (Q3.9);
    ``has_dhw`` — the boiler heats hot water, which the low-flow warning must tell apart.
    Y4: ``condensing`` — the boiler is declared condensing; ``control`` — what control drives,
    ``None`` without control; ``comfort_correction`` — its option; ``circuit_maximum`` — a
    circuit has a maximum flow; ``circuit_flow`` — a circuit has its own flow sensor;
    ``circuit_maximum_unmixed`` — a circuit with a maximum is unmixed, so the boiler's flow shows
    its water; ``circuit_maximum_flow`` — one has its own flow sensor (SB-32: a passive circuit
    with neither is not measured, and its too-hot alarm is inactive);
    ``wall_thermostat`` — control through a gateway with an OpenTherm thermostat (X6);
    ``read_back`` — control's read-back stands in for the CH setpoint signal (X6);
    ``power_threshold`` — the relay's proof has a power threshold (X8); ``shared`` — signals
    dropped because their entity feeds an earlier one, each with the signal that kept it."""

    def lacking(*signals: Signal) -> list[str]:
        return [s.value for s in signals if s not in mapped]

    result: dict[Feature, FeatureState] = {
        Feature.CYCLES: _state(lacking(Signal.FLAME)),
        Feature.CONDENSING: _state(lacking(Signal.FLAME, Signal.RETURN)),
        Feature.PRESSURE_WARNING: _state(
            lacking(Signal.PRESSURE) + ([] if pressure_high else [PRESSURE_HIGH_THRESHOLD])
        ),
        Feature.PRESSURE_TREND: _state(lacking(Signal.PRESSURE, Signal.FLAME, Signal.FLOW)),
        Feature.VERDICT: _state(lacking(Signal.FLAME)),
    }
    # The heat reaching a zone: the boiler's flow, or a circuit's own sensor for its zones.
    for feature in (Feature.HOT_WATER, Feature.EMITTER_FACTOR):
        flow = lacking(Signal.FLOW)
        result[feature] = _state(flow if not circuit_flow else [], flow)
    if Signal.DHW_ACTIVE in mapped:
        result[Feature.DHW_DETECTION] = _state([])
    elif Signal.CH_ACTIVE in mapped or Signal.FLOW in mapped:
        result[Feature.DHW_DETECTION] = _state([], [Signal.DHW_ACTIVE.value])
    else:
        result[Feature.DHW_DETECTION] = _state([Signal.DHW_ACTIVE.value])
    if Signal.GAS_METER in mapped:
        result[Feature.GAS] = _state([])
    elif Signal.MODULATION in mapped and has_gas_rates:
        result[Feature.GAS] = _state([], [Signal.GAS_METER.value])
    else:
        result[Feature.GAS] = _state([Signal.GAS_METER.value])
    if Signal.OUTDOOR in mapped:
        result[Feature.DEGREE_DAYS] = _state([])
    elif has_weather:
        result[Feature.DEGREE_DAYS] = _state([], [Signal.OUTDOOR.value])
    else:
        result[Feature.DEGREE_DAYS] = _state([Signal.OUTDOOR.value, WEATHER_ENTITY])
    weather = [] if has_weather else [WEATHER_ENTITY]
    result[Feature.OUTDOOR_CHECK] = _state(lacking(Signal.OUTDOOR) + weather)
    result[Feature.FORECASTS] = _state(weather)
    # The absolute flue gas alarm needs the flue gas of a condensing boiler; only the trend
    # over the return needs the return (P-85).
    result[Feature.FLUE_GAS_WARNING] = _state(
        lacking(Signal.FLUE_GAS) + ([] if condensing else [CONDENSING_BOILER]),
        lacking(Signal.RETURN),
    )
    result[Feature.ADD_WATER] = _state(
        lacking(Signal.PRESSURE) + ([] if add_water else [ADD_WATER_THRESHOLD])
    )
    result[Feature.HYSTERESIS_DRIFT] = _state(
        lacking(Signal.FLAME, Signal.FLOW) + ([] if zone_data else [ZONE_DATA])
    )
    if Signal.FLAME not in mapped:
        result[Feature.UNSTABLE_IGNITION] = _state(lacking(Signal.FLAME))
    else:
        # P-81: without flow and CH setpoint every short burn counts, as before.
        result[Feature.UNSTABLE_IGNITION] = _state([], lacking(Signal.FLOW, Signal.CH_SETPOINT))
    result[Feature.LOW_FLOW] = _low_flow_feature(mapped, bypass, zone_valves, zone_data, has_dhw)
    result[Feature.BOILER_FAULT_STOP] = _fault_feature(mapped, gateway, control)
    result.update(
        _control_features(mapped, control, comfort_correction, zone_data, wall_thermostat)
    )
    result[Feature.CIRCUIT_OVERSHOOT_ALARM] = _state(
        (
            []
            if circuit_maximum_flow or (circuit_maximum_unmixed and Signal.FLOW in mapped)
            else [Signal.FLOW.value]
        )
        + ([] if circuit_maximum else [CIRCUIT_MAXIMUM])
    )
    suggestion = lacking(Signal.FLAME, Signal.FLOW)
    if Signal.CH_SETPOINT not in mapped and not read_back:
        suggestion.append(Signal.CH_SETPOINT.value)
    result[Feature.LOWEST_WATER_SUGGESTION] = _state(suggestion)
    result[Feature.RELAY_PROOF] = _proof_feature(mapped, control, power_threshold)
    return {feature: _named_shared(state, shared or {}) for feature, state in result.items()}


def _control_features(
    mapped: frozenset[Signal],
    control: ControlKind | None,
    comfort_correction: bool,
    zone_data: bool,
    wall_thermostat: bool,
) -> dict[Feature, FeatureState]:
    """The features of control: each needs control configured; the comfort correction one that
    sets the water temperature, and its option on; frost protection and the correction the
    zones; the wall thermostat after a hand-back a gateway with an OpenTherm thermostat and its
    setpoint signal (X6)."""
    configured = [] if control is not None else [CONTROL]
    zones = [] if zone_data else [ZONE_DATA]
    water = configured or ([] if control is ControlKind.WATER else [WATER_CONTROL])
    return {
        Feature.COMFORT_CORRECTION: _state(
            water + zones + ([] if comfort_correction else [TURNED_OFF])
        ),
        Feature.FROST_PROTECTION: _state(configured + zones),
        Feature.ACTIVATION_DELAY: _state(configured),
        Feature.WALL_THERMOSTAT_FALLBACK: _state(
            ([] if wall_thermostat else [WALL_THERMOSTAT])
            + ([] if Signal.ROOM_SETPOINT in mapped else [Signal.ROOM_SETPOINT.value])
        ),
    }


def _proof_feature(
    mapped: frozenset[Signal], control: ControlKind | None, power_threshold: bool
) -> FeatureState:
    """X8 (R12): the proof that a relay's boiler heats — any one proof input, the power only
    with its threshold. Decision 2 of 0.2.3 (SB-01): on the water-temperature paths, "no sign
    the boiler heats" — the flame or the flow."""
    if control is None:
        return _state([CONTROL])
    if control is ControlKind.WATER:
        water = (Signal.FLAME, Signal.FLOW)
        return _state([] if any(s in mapped for s in water) else [s.value for s in water])
    inputs = [s for s in PROOF_SIGNALS if s in mapped]
    if inputs and not (inputs == [Signal.BOILER_POWER] and not power_threshold):
        return _state([])
    return _state([s.value for s in PROOF_SIGNALS])


def _named_shared(state: FeatureState, shared: Mapping[Signal, Signal]) -> FeatureState:
    """X5: a signal dropped because its entity feeds an earlier one is named so, with the
    signal that kept the entity."""
    if not shared or not any(code in shared for code in state.missing):
        return state
    missing: list[str] = []
    pairs: list[tuple[Signal, Signal]] = []
    for code in state.missing:
        dropped = next((s for s in shared if s.value == code), None)
        if dropped is None:
            missing.append(code)
        else:
            missing.append(ENTITY_FOR_TWO_SIGNALS)
            pairs.append((dropped, shared[dropped]))
    return FeatureState(state.status, tuple(missing), tuple(pairs))


def _low_flow_feature(
    mapped: frozenset[Signal],
    bypass: bool,
    zone_valves: bool | None,
    zone_data: bool,
    has_dhw: bool,
) -> FeatureState:
    """P-99: the low-flow warning needs a pump-running or CH-active signal and zones that report
    a valve opening — and, on a boiler with hot water, the hot-water signal: with hot water
    unknown it is not judged (P-27); with a bypass or a low-loss header it does not apply.
    Zones whose valves are not known yet (``zone_valves`` ``None``) do not make it inactive."""
    missing: list[str] = []
    if Signal.PUMP_RUNNING not in mapped and Signal.CH_ACTIVE not in mapped:
        missing += [Signal.PUMP_RUNNING.value, Signal.CH_ACTIVE.value]
    if not zone_data or zone_valves is False:
        missing.append(VALVE_OPENINGS)
    if bypass:
        missing.append(NO_BYPASS)
    if has_dhw and Signal.DHW_ACTIVE not in mapped:
        missing.append(Signal.DHW_ACTIVE.value)
    return _state(missing)


def _fault_feature(
    mapped: frozenset[Signal], gateway: frozenset[Signal], control: ControlKind | None
) -> FeatureState:
    """Y1: the stop on the boiler's own fault is control's — it needs control and one of its
    fault signals; a flag the OpenTherm Gateway reports counts only with the boiler's fault
    indication mapped (Q3.9) — without it, that flag stops nothing."""
    flags = [s for s in FAULT_SIGNALS if s in mapped]
    configured = [] if control is not None else [CONTROL]
    if not flags:
        return _state(configured + [s.value for s in FAULT_SIGNALS])
    if configured or Signal.FAULT_INDICATION in mapped:
        return _state(configured)
    gated = [s for s in flags if s in gateway]
    if not gated:
        return _state([])
    indication = [Signal.FAULT_INDICATION.value]
    return _state(indication) if len(gated) == len(flags) else _state([], indication)


class OutdoorStatus(StrEnum):
    OK = "ok"
    DEVIATES = "deviates"  # disagrees with the weather entity for a long time
    STUCK = "stuck"  # does not move while the weather does
    UNKNOWN = "unknown"  # not enough overlapping data


@dataclass(frozen=True, slots=True)
class OutdoorCheck:
    status: OutdoorStatus
    mean_difference: float | None = None  # sensor minus weather, K
    overlap_s: float = 0.0


DEFAULT_MAX_DEVIATION_K = 6.0
MIN_OVERLAP_S = 2 * HOUR
STUCK_WINDOW_S = 12 * HOUR
STUCK_WEATHER_RANGE_K = 3.0


def check_outdoor(
    sensor: Series[float],
    weather: Series[float],
    start: float,
    end: float,
    max_deviation: float = DEFAULT_MAX_DEVIATION_K,
) -> OutdoorCheck:
    """Compare the boiler's outdoor sensor with the weather entity over ``[start, end)``.

    Stuck (P-26): the sensor has held one value since its last change — a stretch without a
    value neither ends that tail nor counts toward it — for at least ``STUCK_WINDOW_S``, while
    the weather moved at least ``STUCK_WEATHER_RANGE_K`` over that same tail. Judged on the tail,
    a sensor that changed earlier in the window and then froze is caught twelve hours after it
    froze, not only once the whole window is flat."""
    overlap = 0.0
    total_difference = 0.0
    for segment in sensor.segments(start, end):
        if segment.value is None:
            continue
        for part in weather.segments(segment.start, segment.end):
            if part.value is None:
                continue
            overlap += part.duration
            total_difference += (segment.value - part.value) * part.duration
    if overlap < MIN_OVERLAP_S:
        return OutdoorCheck(OutdoorStatus.UNKNOWN, None, overlap)
    mean_difference = total_difference / overlap
    if _stuck(sensor, weather, start, end):
        return OutdoorCheck(OutdoorStatus.STUCK, mean_difference, overlap)
    if abs(mean_difference) > max_deviation:
        return OutdoorCheck(OutdoorStatus.DEVIATES, mean_difference, overlap)
    return OutdoorCheck(OutdoorStatus.OK, mean_difference, overlap)


def _stuck(sensor: Series[float], weather: Series[float], start: float, end: float) -> bool:
    """The tail since the sensor's last change, within ``[start, end)``: its value known for
    ``STUCK_WINDOW_S`` at least, and the weather over those stretches spanning
    ``STUCK_WEATHER_RANGE_K`` or more."""
    tail: list[tuple[float, float]] = []  # the stretches holding the tail's value
    value: float | None = None
    for segment in reversed(list(sensor.segments(start, end))):
        if segment.value is None:
            continue  # no value: neither a change nor held
        if value is not None and segment.value != value:
            break  # the last change
        value = segment.value
        tail.append((segment.start, segment.end))
    if value is None or sum(stop - begin for begin, stop in tail) < STUCK_WINDOW_S:
        return False
    moved = [
        part.value
        for begin, stop in tail
        for part in weather.segments(begin, stop)
        if part.value is not None
    ]
    return bool(moved) and max(moved) - min(moved) >= STUCK_WEATHER_RANGE_K


def curve_sensor(
    check: OutdoorCheck | None, sensor: float | None, weather: float | None
) -> float | None:
    """The boiler's outdoor sensor as the curve may take it. A stuck sensor is never used. One
    that deviates from the weather entity is used only while it reads colder: the colder value
    asks for more heat, which the valves throttle, where the warmer one could leave the house
    cold — a sensor in a cold-air pool is right, a weather entity for somewhere else is not.
    Without a weather reading, the check's day tells which of the two is the colder one; the
    warmer sensor gives way to the held value and the fallback, which ask for more heat."""
    if sensor is None or check is None:
        return sensor
    if check.status is OutdoorStatus.STUCK:
        return None
    if check.status is OutdoorStatus.DEVIATES:
        if weather is not None:
            return sensor if sensor <= weather else None
        colder = check.mean_difference is not None and check.mean_difference < 0.0
        return sensor if colder else None
    return sensor
