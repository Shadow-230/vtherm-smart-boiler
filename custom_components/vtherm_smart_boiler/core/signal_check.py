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


class FeatureStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"  # works, from weaker inputs (e.g. inferred instead of measured)
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FeatureState:
    status: FeatureStatus
    missing: tuple[Signal, ...] = ()  # what to map for the full feature
    reason: str | None = None  # why it is inactive where no signal would help


# The boiler's own fault signals (Y1), in the order the form asks for them.
FAULT_SIGNALS = (Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT)


def features(
    mapped: frozenset[Signal],
    has_weather: bool,
    has_gas_rates: bool,
    *,
    add_water: bool = False,
    bypass: bool = False,
    zone_valves: bool | None = None,
    zone_data: bool = True,
    gateway: frozenset[Signal] = frozenset(),
    has_dhw: bool = False,
) -> dict[Feature, FeatureState]:
    """What the mapped signals enable; ``has_gas_rates``: gas at min and max power are known.
    Y1: ``add_water`` — the user entered the "add water" threshold; ``bypass`` — a bypass or a
    low-loss header is declared; ``zone_valves`` — whether every zone reports a valve opening
    (``None``: not known yet); ``zone_data`` — zones are configured; ``gateway`` — the mapped
    signals the OpenTherm Gateway reports, whose fault flags need the fault indication (Q3.9);
    ``has_dhw`` — the boiler heats hot water, which the low-flow warning must tell apart."""

    def need(*signals: Signal) -> FeatureState:
        missing = tuple(s for s in signals if s not in mapped)
        return FeatureState(
            FeatureStatus.UNAVAILABLE if missing else FeatureStatus.AVAILABLE, missing
        )

    result = {
        Feature.CYCLES: need(Signal.FLAME),
        Feature.CONDENSING: need(Signal.FLAME, Signal.RETURN),
        Feature.HOT_WATER: need(Signal.FLOW),
        Feature.EMITTER_FACTOR: need(Signal.FLOW),
        Feature.FLUE_GAS_WARNING: need(Signal.FLUE_GAS, Signal.RETURN),
        Feature.PRESSURE_WARNING: need(Signal.PRESSURE),
    }
    if Signal.DHW_ACTIVE in mapped:
        result[Feature.DHW_DETECTION] = FeatureState(FeatureStatus.AVAILABLE)
    elif Signal.CH_ACTIVE in mapped or Signal.FLOW in mapped:
        result[Feature.DHW_DETECTION] = FeatureState(FeatureStatus.DEGRADED, (Signal.DHW_ACTIVE,))
    else:
        result[Feature.DHW_DETECTION] = FeatureState(
            FeatureStatus.UNAVAILABLE, (Signal.DHW_ACTIVE,)
        )
    if Signal.GAS_METER in mapped:
        result[Feature.GAS] = FeatureState(FeatureStatus.AVAILABLE)
    elif Signal.MODULATION in mapped and has_gas_rates:
        result[Feature.GAS] = FeatureState(FeatureStatus.DEGRADED, (Signal.GAS_METER,))
    else:
        result[Feature.GAS] = FeatureState(FeatureStatus.UNAVAILABLE, (Signal.GAS_METER,))
    if Signal.OUTDOOR in mapped:
        result[Feature.DEGREE_DAYS] = FeatureState(FeatureStatus.AVAILABLE)
    elif has_weather:
        result[Feature.DEGREE_DAYS] = FeatureState(FeatureStatus.DEGRADED, (Signal.OUTDOOR,))
    else:
        result[Feature.DEGREE_DAYS] = FeatureState(FeatureStatus.UNAVAILABLE, (Signal.OUTDOOR,))
    outdoor_check = Signal.OUTDOOR in mapped and has_weather
    result[Feature.OUTDOOR_CHECK] = FeatureState(
        FeatureStatus.AVAILABLE if outdoor_check else FeatureStatus.UNAVAILABLE,
        () if Signal.OUTDOOR in mapped else (Signal.OUTDOOR,),
    )
    result[Feature.LOW_FLOW] = _low_flow_feature(mapped, bypass, zone_valves, has_dhw)
    result[Feature.BOILER_FAULT_STOP] = _fault_feature(mapped, gateway)
    add = need(Signal.PRESSURE)
    if add.status is FeatureStatus.AVAILABLE and not add_water:
        add = FeatureState(FeatureStatus.UNAVAILABLE, reason="no_threshold")
    result[Feature.ADD_WATER] = add
    result[Feature.PRESSURE_TREND] = need(Signal.PRESSURE, Signal.FLAME, Signal.FLOW)
    if Signal.FLAME not in mapped:
        result[Feature.UNSTABLE_IGNITION] = need(Signal.FLAME)
    else:
        # P-81: without flow and CH setpoint every short burn counts, as before.
        ignition = need(Signal.FLOW, Signal.CH_SETPOINT)
        if ignition.missing:
            ignition = FeatureState(FeatureStatus.DEGRADED, ignition.missing)
        result[Feature.UNSTABLE_IGNITION] = ignition
    drift = need(Signal.FLAME, Signal.FLOW)
    if drift.status is FeatureStatus.AVAILABLE and not zone_data:
        drift = FeatureState(FeatureStatus.UNAVAILABLE, reason="no_zone_data")
    result[Feature.HYSTERESIS_DRIFT] = drift
    return result


def _low_flow_feature(
    mapped: frozenset[Signal], bypass: bool, zone_valves: bool | None, has_dhw: bool
) -> FeatureState:
    """P-99: the low-flow warning needs a pump-running or CH-active signal and zones that report
    a valve opening — and, on a boiler with hot water, the hot-water signal: with hot water
    unknown it is not judged (P-27); with a bypass or a low-loss header it does not apply."""
    if Signal.PUMP_RUNNING not in mapped and Signal.CH_ACTIVE not in mapped:
        return FeatureState(FeatureStatus.UNAVAILABLE, (Signal.PUMP_RUNNING, Signal.CH_ACTIVE))
    if bypass:
        return FeatureState(FeatureStatus.UNAVAILABLE, reason="bypass")
    if has_dhw and Signal.DHW_ACTIVE not in mapped:
        return FeatureState(FeatureStatus.UNAVAILABLE, (Signal.DHW_ACTIVE,))
    if zone_valves is False:
        return FeatureState(FeatureStatus.UNAVAILABLE, reason="zone_without_valve")
    return FeatureState(FeatureStatus.AVAILABLE)


def _fault_feature(mapped: frozenset[Signal], gateway: frozenset[Signal]) -> FeatureState:
    """Y1: the stop on the boiler's own fault needs one of its fault signals; a flag the
    OpenTherm Gateway reports counts only with the boiler's fault indication mapped (Q3.9) —
    without it, that flag stops nothing."""
    flags = [s for s in FAULT_SIGNALS if s in mapped]
    if not flags:
        return FeatureState(FeatureStatus.UNAVAILABLE, FAULT_SIGNALS)
    if Signal.FAULT_INDICATION in mapped:
        return FeatureState(FeatureStatus.AVAILABLE)
    gated = [s for s in flags if s in gateway]
    if not gated:
        return FeatureState(FeatureStatus.AVAILABLE)
    status = FeatureStatus.UNAVAILABLE if len(gated) == len(flags) else FeatureStatus.DEGRADED
    return FeatureState(status, (Signal.FAULT_INDICATION,))


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
