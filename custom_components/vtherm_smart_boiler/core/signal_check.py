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
    required: bool
    age_s: float | None = None


def check_signals(
    snapshot: BoilerSnapshot, max_ages: Mapping[Signal, float | None] | None = None
) -> dict[Signal, SignalHealth]:
    """Health of every signal; ``max_ages``: the age limits the user set (none: availability)."""
    result: dict[Signal, SignalHealth] = {}
    for signal, spec in SIGNAL_SPECS.items():
        max_age = (max_ages or {}).get(signal)
        if not snapshot.is_mapped(signal):
            result[signal] = SignalHealth(SignalStatus.NOT_MAPPED, spec.required)
            continue
        reading = snapshot.reading(signal)
        age = reading.age(snapshot.t)
        if reading.value is None:
            status = SignalStatus.UNAVAILABLE
        elif not reading.is_fresh(snapshot.t, max_age):
            status = SignalStatus.STALE
        else:
            status = SignalStatus.OK
        result[signal] = SignalHealth(status, spec.required, age)
    return result


def required_problems(health: Mapping[Signal, SignalHealth]) -> list[Signal]:
    """Required signals that are not OK."""
    return [s for s, h in health.items() if h.required and h.status is not SignalStatus.OK]


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


class FeatureStatus(StrEnum):
    AVAILABLE = "available"
    DEGRADED = "degraded"  # works, from weaker inputs (e.g. inferred instead of measured)
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class FeatureState:
    status: FeatureStatus
    missing: tuple[Signal, ...] = ()  # what to map for the full feature


def features(
    mapped: frozenset[Signal],
    has_weather: bool,
    has_gas_rates: bool,
) -> dict[Feature, FeatureState]:
    """What the mapped signals enable; ``has_gas_rates``: gas at min and max power are known."""

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
    return result


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
    """Compare the boiler's outdoor sensor with the weather entity over ``[start, end)``."""
    overlap = 0.0
    total_difference = 0.0
    sensor_values: set[float] = set()
    sensor_known = 0.0
    weather_values: list[float] = []
    for segment in sensor.segments(start, end):
        if segment.value is None:
            continue
        sensor_values.add(segment.value)
        sensor_known += segment.duration
        for part in weather.segments(segment.start, segment.end):
            if part.value is None:
                continue
            overlap += part.duration
            total_difference += (segment.value - part.value) * part.duration
            weather_values.append(part.value)
    if overlap < MIN_OVERLAP_S:
        return OutdoorCheck(OutdoorStatus.UNKNOWN, None, overlap)
    mean_difference = total_difference / overlap
    if (
        len(sensor_values) == 1
        and sensor_known >= STUCK_WINDOW_S
        and max(weather_values) - min(weather_values) >= STUCK_WEATHER_RANGE_K
    ):
        return OutdoorCheck(OutdoorStatus.STUCK, mean_difference, overlap)
    if abs(mean_difference) > max_deviation:
        return OutdoorCheck(OutdoorStatus.DEVIATES, mean_difference, overlap)
    return OutdoorCheck(OutdoorStatus.OK, mean_difference, overlap)


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
