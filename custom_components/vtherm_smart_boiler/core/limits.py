"""Limits on the flow setpoint, a setpoint entity's grid, and frost protection.

Every setpoint the plugin writes passes ``limit_flow``. Caps that protect the installation — the
hard maximum, a circuit's maximum (underfloor on an unmixed loop), the boiler's own maximum —
win over the hard minimum when the two conflict. The weather-dependent ceiling protects nothing
but gas, so it never falls below the hard minimum, nor below the temperature a fixed circuit (a
thermostatic mixing valve) needs from the boiler. A value for an entity with a step is put on its
grid inside the limits, in the entity's own unit, before the write guard compares it (P-15, P-98).

Frost protection (decision 4) watches every zone, or the one the user picks, but heats only for a
cold zone whose emitter can take heat: VT shows an opening above 0 or its device active — the
mode alone never counts. A zone whose valve state cannot be read is heated as before, unless the
user declared that it closes while VT has it off. A cold zone VT keeps closed is flagged instead:
heat for it cannot arrive. The alarm "handed back in frost" watches every watched room: a
hand-back that stops heating leaves a room near freezing, closed or not.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .readings import ZoneState


class LimitCode(StrEnum):
    HARD_MIN = "hard_min"
    HARD_MAX = "hard_max"
    CIRCUIT_MAX = "circuit_max"
    BOILER_MAX = "boiler_max"
    CEILING = "ceiling"
    FIXED_CIRCUIT = "fixed_circuit"  # a fixed circuit needs at least its temperature


@dataclass(frozen=True, slots=True)
class FlowLimits:
    """Hard limits of the flow setpoint and the band of the weather-dependent ceiling (°C, K)."""

    hard_min: float = 25.0
    hard_max: float = 70.0
    ceiling_band: float = 10.0

    def __post_init__(self) -> None:
        if not 10.0 <= self.hard_min < self.hard_max <= 95.0:
            raise ValueError("hard limits must satisfy 10 <= minimum < maximum <= 95")
        if self.ceiling_band < 0:
            raise ValueError("the ceiling band must not be negative")


@dataclass(frozen=True, slots=True)
class Limited:
    value: float
    applied: tuple[LimitCode, ...] = ()  # the limits that changed the requested value


def limit_flow(
    requested: float,
    curve_value: float,
    limits: FlowLimits,
    circuit_max: float | None = None,
    boiler_max: float | None = None,
    floor: float | None = None,
) -> Limited:
    """``requested`` within the limits. ``floor``: what a fixed circuit needs from the boiler.
    Installation caps win over the lower bounds; the weather ceiling gives way to them."""
    caps = [(limits.hard_max, LimitCode.HARD_MAX)]
    if circuit_max is not None:
        caps.append((circuit_max, LimitCode.CIRCUIT_MAX))
    if boiler_max is not None:
        caps.append((boiler_max, LimitCode.BOILER_MAX))
    install, install_code = min(caps, key=lambda cap: cap[0])
    lower, lower_code = limits.hard_min, LimitCode.HARD_MIN
    if floor is not None and floor > lower:
        lower, lower_code = floor, LimitCode.FIXED_CIRCUIT
    ceiling = max(curve_value + limits.ceiling_band, lower)
    upper, upper_code = (
        (install, install_code) if install <= ceiling else (ceiling, LimitCode.CEILING)
    )
    if requested > upper:
        return Limited(upper, (upper_code,))
    if requested < lower:
        if lower > install:
            return Limited(install, (lower_code, install_code))
        return Limited(lower, (lower_code,))
    return Limited(requested)


def install_cap(
    limits: FlowLimits, circuit_max: float | None = None, boiler_max: float | None = None
) -> float:
    """The lowest cap that protects the installation — the hard maximum, a circuit's maximum,
    the boiler's own — which a setpoint above it meets at once, unramped (S-23)."""
    return min(v for v in (limits.hard_max, circuit_max, boiler_max) if v is not None)


def write_bounds(
    limits: FlowLimits,
    circuit_max: float | None = None,
    boiler_max: float | None = None,
    floor: float | None = None,
) -> tuple[float, float]:
    """The lowest and highest heating setpoint ``limit_flow`` can give: a value put on an
    entity's grid stays inside them."""
    high = install_cap(limits, circuit_max, boiler_max)
    low = limits.hard_min if floor is None else max(limits.hard_min, floor)
    return min(low, high), high


GRID_EPSILON = 1e-6  # how close to a grid value (in steps) counts as on it
MAX_STEP_K = 1.0  # a setpoint entity with a coarser step cannot confirm a value (P-15)


def on_grid(
    value: float, step: float, base: float, low: float | None, high: float | None
) -> float | None:
    """``value`` on the grid ``base + n * step``: the nearest grid value inside ``[low, high]``,
    the one just inside where the nearest falls outside; ``None`` without one inside. A step of 0
    or less is no grid: ``value`` itself, inside the bounds."""
    if step <= 0:
        inside = (low is None or value >= low) and (high is None or value <= high)
        return value if inside else None
    n = round((value - base) / step)
    if low is not None and base + n * step < low - GRID_EPSILON * step:
        n = math.ceil((low - base) / step - GRID_EPSILON)
    if high is not None and base + n * step > high + GRID_EPSILON * step:
        n = math.floor((high - base) / step + GRID_EPSILON)
    candidate = base + n * step
    if (low is not None and candidate < low - GRID_EPSILON * step) or (
        high is not None and candidate > high + GRID_EPSILON * step
    ):
        return None
    return round(candidate, 9)


def is_on_grid(value: float, step: float, base: float) -> bool:
    """Whether ``value`` lies on the grid ``base + n * step`` (no grid: always)."""
    if step <= 0:
        return True
    n = (value - base) / step
    return abs(n - round(n)) <= GRID_EPSILON * max(1.0, abs(n))


@dataclass(frozen=True, slots=True)
class Grid:
    """A setpoint entity's grid in its own unit — ``minimum`` (else 0) plus steps — within its
    ``minimum`` and ``maximum``. ``scale`` and ``offset`` turn °C into that unit
    (``unit = °C * scale + offset``: °F 1.8 and 32, K 1 and 273.15)."""

    step: float
    minimum: float | None = None
    maximum: float | None = None
    scale: float = 1.0
    offset: float = 0.0

    @property
    def base(self) -> float:
        return 0.0 if self.minimum is None else self.minimum

    @property
    def step_k(self) -> float:
        """The step as a temperature difference, in K."""
        return self.step / self.scale

    @property
    def too_coarse(self) -> bool:
        """A step above ``MAX_STEP_K``: a value on it could read back more than the tolerance
        away from what was asked (P-15)."""
        return self.step_k > MAX_STEP_K

    def to_unit(self, celsius: float) -> float:
        return celsius * self.scale + self.offset

    def to_celsius(self, value: float) -> float:
        return (value - self.offset) / self.scale

    def put(
        self, celsius: float, low: float | None = None, high: float | None = None
    ) -> float | None:
        """``celsius`` on the grid inside ``[low, high]`` (°C) and the entity's own range, in
        °C; ``None`` without a grid value inside."""
        lows = [
            v for v in (self.minimum, None if low is None else self.to_unit(low)) if v is not None
        ]
        highs = [
            v for v in (self.maximum, None if high is None else self.to_unit(high)) if v is not None
        ]
        value = on_grid(
            self.to_unit(celsius),
            self.step,
            self.base,
            max(lows) if lows else None,
            min(highs) if highs else None,
        )
        return None if value is None else round(self.to_celsius(value), 9)


PLAUSIBLE_ROOM = (-30.0, 45.0)  # °C: a room reading outside is a broken sensor, not a room
FROST_OPEN = 0.0  # decided (decision 4): an opening above this can take heat


@dataclass(frozen=True, slots=True)
class FrostConfig:
    """Frost protection: a safety net below VT's own frost presets (°C). The one case where the
    plugin heats without VT's call; it watches every zone, VT's switched-off ones included, or
    only the zone the user picks — and heats only for those whose emitter can take heat."""

    room_limit: float = 5.0  # a watched zone below this starts frost heating
    release: float = 7.0  # frost heating ends once every watched zone is at or above this
    zone: str | None = None  # watch only this zone; None: every zone
    # Zones the user declared closed while VT has them off ("closes when VT switches it off",
    # off by default): without a published opening they then cannot take heat.
    closes_when_off: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.release < self.room_limit:
            raise ValueError("the release temperature must not be below the frost limit")


def can_take_heat(zone: ZoneState, config: FrostConfig) -> bool:
    """Whether heat for the zone can reach its room (decision 4): VT shows an opening above 0 —
    its valve, else its duty cycle — or its device active; the mode alone never counts (a heat
    mode with its valve closed cannot, an off zone asleep with its valve at 100 % can). A zone
    whose valve state cannot be read — no opening published, or VT has not started it (what it
    shows is a placeholder) — can, as before; unless the user declared that it closes while VT
    has it off, and VT has it off."""
    if zone.device_active is True:
        return True
    opening = zone.demand
    if opening is None or not zone.started:
        return not (zone.zone_id in config.closes_when_off and zone.heating_enabled is False)
    return opening > FROST_OPEN


def _watched(
    zones: Sequence[ZoneState], now: float, max_age: float | None, config: FrostConfig
) -> list[tuple[ZoneState, float]]:
    """The zones frost protection watches that have a fresh, plausible room temperature."""
    low, high = PLAUSIBLE_ROOM
    return [
        (z, z.temperature)
        for z in zones
        if (config.zone is None or z.zone_id == config.zone)
        and z.temperature is not None
        and low <= z.temperature <= high
        and z.is_fresh(now, max_age)
    ]


def watched_temperatures(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    config: FrostConfig,
    *,
    closed_too: bool = False,
) -> list[float]:
    """Fresh, plausible room temperatures of the watched zones that can take heat; with
    ``closed_too``, of every watched zone."""
    return [
        temperature
        for zone, temperature in _watched(zones, now, max_age, config)
        if closed_too or can_take_heat(zone, config)
    ]


def frost_needed(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    active: bool,
    config: FrostConfig,
    *,
    closed_too: bool = False,
) -> bool:
    """Whether a watched zone that can take heat is cold enough for frost heating, with
    hysteresis; closed zones neither start it nor hold it. ``closed_too``: every watched zone
    counts (the alarm "handed back in frost")."""
    temperatures = watched_temperatures(zones, now, max_age, config, closed_too=closed_too)
    if any(t < config.room_limit for t in temperatures):
        return True
    return active and any(t < config.release for t in temperatures)


def frost_closed(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    config: FrostConfig,
    flagged: Sequence[str] = (),
) -> tuple[str, ...]:
    """The watched zones below the frost limit that cannot take heat (decision 4): VT keeps
    them closed, so frost heat cannot reach them and does not start for them. One stays
    flagged (``flagged``: at the step before) until it is at or above the release, or can take
    heat. A zone VT has not started is not judged: its valve state is not known yet."""
    return tuple(
        zone.zone_id
        for zone, temperature in _watched(zones, now, max_age, config)
        if zone.started
        and not can_take_heat(zone, config)
        and (
            temperature < config.room_limit
            or (zone.zone_id in flagged and temperature < config.release)
        )
    )


def handed_back_in_frost(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    config: FrostConfig,
    *,
    heating_stops: bool,
    controlling: bool,
    active: bool,
) -> bool | None:
    """The alarm "handed back in frost" (S-57): control does not hold the boiler — for any
    reason, a switch-off included — where a hand-back stops heating (``heating_stops``), so
    frost protection rests on the boiler's own, if it has one, and a watched zone reads below
    the frost limit. Once raised (``active``) it holds until every watched zone with a known
    temperature is at or above the release. A zone not known is not counted; with none known it
    cannot be judged (``None``): the control unit holds its last state for an hour, then shows
    it unknown (S-16, Y1). Information only: it never starts heating (principle 12)."""
    if controlling or not heating_stops:
        return False
    if not watched_temperatures(zones, now, max_age, config, closed_too=True):
        return None
    return frost_needed(zones, now, max_age, active, config, closed_too=True)
