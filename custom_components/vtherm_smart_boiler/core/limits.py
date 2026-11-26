"""Limits on the flow setpoint, a setpoint entity's grid, and the alarm "handed back in frost".

Every setpoint the plugin writes passes ``limit_flow``. Caps that protect the installation — the
hard maximum, a circuit's maximum (underfloor on an unmixed loop), the boiler's own maximum —
win over the hard minimum and the need of a circuit run by other automation when they conflict.
A thermostatic mixing valve sets no lower bound: the boiler follows its curve, and the valve stands
open while the water is at or below its setting (the user's decision of 2026-10-14). There is no
weather ceiling of its own (I8, decision B6): above the curve only the comfort correction goes,
bounded by its own limit. A value for an
entity with a step is put on its grid inside the limits, in the entity's own unit, before the
write guard compares it (P-15, P-98).

The plugin has no frost protection of its own (I12, decision 4): VT's frost preset and central
mode make the rooms call, and VT's central boiler turns its helper on. The alarm "handed back in
frost" (S-57) watches every room: a hand-back that stops heating leaves a room near freezing
with nothing to heat it.
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
    # I8 (decision F3): a circuit run by other automation, asking, needs at least its need.
    CIRCUIT_NEED = "circuit_need"


@dataclass(frozen=True, slots=True)
class FlowLimits:
    """Hard limits of the flow setpoint (°C)."""

    hard_min: float = 25.0
    hard_max: float = 70.0

    def __post_init__(self) -> None:
        if not 10.0 <= self.hard_min < self.hard_max <= 95.0:
            raise ValueError("hard limits must satisfy 10 <= minimum < maximum <= 95")


@dataclass(frozen=True, slots=True)
class Limited:
    value: float
    applied: tuple[LimitCode, ...] = ()  # the limits that changed the requested value


def limit_flow(
    requested: float,
    limits: FlowLimits,
    circuit_max: float | None = None,
    boiler_max: float | None = None,
    need: float | None = None,
) -> Limited:
    """``requested`` within the limits. ``need``: what circuits run by other automation, asking,
    need (I8, decision F3), as they state it — nothing added. Installation caps win over the lower
    bounds."""
    caps = [(limits.hard_max, LimitCode.HARD_MAX)]
    if circuit_max is not None:
        caps.append((circuit_max, LimitCode.CIRCUIT_MAX))
    if boiler_max is not None:
        caps.append((boiler_max, LimitCode.BOILER_MAX))
    install, install_code = min(caps, key=lambda cap: cap[0])
    lower, lower_code = limits.hard_min, LimitCode.HARD_MIN
    if need is not None and need > lower:
        lower, lower_code = need, LimitCode.CIRCUIT_NEED
    if requested > install:
        return Limited(install, (install_code,))
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
) -> tuple[float, float]:
    """The lowest and highest heating setpoint ``limit_flow`` gives without a circuit's need: a
    value put on an entity's grid stays inside them."""
    high = install_cap(limits, circuit_max, boiler_max)
    return min(limits.hard_min, high), high


def within_write_bounds(
    value: float,
    limits: FlowLimits,
    circuit_max: float | None = None,
    boiler_max: float | None = None,
) -> float:
    """``value`` moved inside ``write_bounds``: a setpoint kept from options changed since — a
    command given again after a restart — goes out within the limits as they are now (PB-11)."""
    low, high = write_bounds(limits, circuit_max, boiler_max)
    return min(max(value, low), high)


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
# S-57: the alarm "handed back in frost" rises while a room reads below this, where a hand-back
# that stops heating holds, and clears once every room known is at or above the release
# (provisional, K4). The values the frost options had by default: frost protection itself is
# VT's, through its frost preset and central mode (I12, decision 4), so they are no options.
FROST_ALARM_LIMIT = 5.0
FROST_ALARM_RELEASE = 7.0


def room_temperatures(zones: Sequence[ZoneState], now: float, max_age: float | None) -> list[float]:
    """The rooms' fresh, plausible temperatures."""
    low, high = PLAUSIBLE_ROOM
    return [
        z.temperature
        for z in zones
        if z.temperature is not None and low <= z.temperature <= high and z.is_fresh(now, max_age)
    ]


def handed_back_in_frost(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    *,
    heating_stops: bool,
    controlling: bool,
    active: bool,
) -> bool | None:
    """The alarm "handed back in frost" (S-57): control does not hold the boiler — for any
    reason, a switch-off included — where a hand-back stops heating (``heating_stops``), so
    neither VT's frost protection nor anything else can reach the boiler: frost protection rests
    on the boiler's own, if it has one, and a room reads below ``FROST_ALARM_LIMIT``. Once raised
    (``active``) it holds until every room with a known temperature is at or above
    ``FROST_ALARM_RELEASE``. A room not known is not counted; with none known it cannot be judged
    (``None``): the control unit holds its last state for an hour, then shows it unknown (S-16,
    Y1). Information only: it never starts heating (principle 12)."""
    if controlling or not heating_stops:
        return False
    temperatures = room_temperatures(zones, now, max_age)
    if not temperatures:
        return None
    if any(t < FROST_ALARM_LIMIT for t in temperatures):
        return True
    return active and any(t < FROST_ALARM_RELEASE for t in temperatures)
