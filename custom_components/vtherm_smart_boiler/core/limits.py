"""Limits on the flow setpoint and frost protection.

Every setpoint the plugin writes passes ``limit_flow``. Caps that protect the installation — the
hard maximum, a circuit's maximum (underfloor on an unmixed loop), the boiler's own maximum —
win over the hard minimum when the two conflict. The weather-dependent ceiling protects nothing
but gas, so it never falls below the hard minimum, nor below the temperature a fixed circuit (a
thermostatic mixing valve) needs from the boiler. Frost protection watches the same rooms for the
alarm "handed back in frost": a hand-back that stops heating leaves a room near freezing.
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


PLAUSIBLE_ROOM = (-30.0, 45.0)  # °C: a room reading outside is a broken sensor, not a room


@dataclass(frozen=True, slots=True)
class FrostConfig:
    """Frost protection: a safety net below VT's own frost presets (°C). The one case where the
    plugin heats without VT's call; it watches every zone, VT's switched-off ones included, or
    only the zone the user picks."""

    room_limit: float = 5.0  # a watched zone below this starts frost heating
    release: float = 7.0  # frost heating ends once every watched zone is at or above this
    zone: str | None = None  # watch only this zone; None: every zone

    def __post_init__(self) -> None:
        if self.release < self.room_limit:
            raise ValueError("the release temperature must not be below the frost limit")


def watched_temperatures(
    zones: Sequence[ZoneState], now: float, max_age: float | None, config: FrostConfig
) -> list[float]:
    """Fresh, plausible room temperatures of the zones frost protection watches."""
    low, high = PLAUSIBLE_ROOM
    return [
        z.temperature
        for z in zones
        if (config.zone is None or z.zone_id == config.zone)
        and z.temperature is not None
        and low <= z.temperature <= high
        and z.is_fresh(now, max_age)
    ]


def frost_needed(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    active: bool,
    config: FrostConfig,
) -> bool:
    """Whether a watched zone is cold enough for frost heating, with hysteresis."""
    temperatures = watched_temperatures(zones, now, max_age, config)
    if any(t < config.room_limit for t in temperatures):
        return True
    return active and any(t < config.release for t in temperatures)


def handed_back_in_frost(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    config: FrostConfig,
    *,
    heating_stops: bool,
    controlling: bool,
    active: bool,
) -> bool:
    """The alarm "handed back in frost" (S-57): control does not hold the boiler — for any
    reason, a switch-off included — where a hand-back stops heating (``heating_stops``), so
    frost protection rests on the boiler's own, if it has one, and a watched zone reads below
    the frost limit. Once raised (``active``) it holds until every watched zone with a known
    temperature is at or above the release. A zone not known is not counted, so with none known
    it is off. Information only: it never starts heating (principle 12)."""
    if controlling or not heating_stops:
        return False
    return frost_needed(zones, now, max_age, active, config)
