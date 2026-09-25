"""Limits on the flow setpoint and frost protection.

Every setpoint the plugin writes passes ``limit_flow``. Caps that protect the installation — the
hard maximum, a circuit's maximum (underfloor on an unmixed loop), the boiler's own maximum and
the weather-dependent ceiling — win over the hard minimum when the two conflict.
"""

from __future__ import annotations

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
) -> Limited:
    """``requested`` within the limits; the caps win when they fall below the hard minimum."""
    caps = [
        (limits.hard_max, LimitCode.HARD_MAX),
        (curve_value + limits.ceiling_band, LimitCode.CEILING),
    ]
    if circuit_max is not None:
        caps.append((circuit_max, LimitCode.CIRCUIT_MAX))
    if boiler_max is not None:
        caps.append((boiler_max, LimitCode.BOILER_MAX))
    upper, upper_code = min(caps, key=lambda cap: cap[0])
    if requested > upper:
        return Limited(upper, (upper_code,))
    if requested < limits.hard_min:
        if limits.hard_min > upper:
            return Limited(upper, (LimitCode.HARD_MIN, upper_code))
        return Limited(limits.hard_min, (LimitCode.HARD_MIN,))
    return Limited(requested)


@dataclass(frozen=True, slots=True)
class FrostConfig:
    """Frost protection: a safety net below VT's own frost presets (°C)."""

    room_limit: float = 5.0  # any zone below this starts frost heating
    release: float = 7.0  # frost heating ends once every zone is at or above this

    def __post_init__(self) -> None:
        if self.release < self.room_limit:
            raise ValueError("the release temperature must not be below the frost limit")


def frost_needed(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    active: bool,
    config: FrostConfig,
) -> bool:
    """Whether a fresh zone is cold enough for frost heating, with hysteresis."""
    temperatures = [
        z.temperature for z in zones if z.temperature is not None and z.is_fresh(now, max_age)
    ]
    if any(t < config.room_limit for t in temperatures):
        return True
    return active and any(t < config.release for t in temperatures)
