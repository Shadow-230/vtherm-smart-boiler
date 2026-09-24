"""Boiler demand from the VT zones — what VT's central boiler decided, now the plugin's job.

A zone wants heat when it is in a heating mode and its valve opening or duty cycle is above a
few percent (without either, when VT says it is heating). The boiler has demand when enough zones
want heat, or — when set — their power or the widest valve opening reaches a threshold. Zones
without fresh data do not count; with no fresh zone at all, demand is unknown.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .readings import ZoneState


@dataclass(frozen=True, slots=True)
class DemandConfig:
    count_threshold: int = 1  # zones wanting heat
    power_threshold_kw: float | None = None  # their power times opening, summed
    opening_threshold: float | None = None  # the widest opening, 0 to 1
    zone_opening: float = 0.05  # a zone wants heat above this opening or duty cycle

    def __post_init__(self) -> None:
        if self.count_threshold < 1:
            raise ValueError("the zone count threshold must be at least 1")
        if not 0.0 <= self.zone_opening < 1.0:
            raise ValueError("the zone opening must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Demand:
    wanted: bool | None  # None: no fresh zone data
    zones_wanting: int = 0
    power_kw: float | None = None
    widest_opening: float | None = None
    fresh_zones: int = 0


def zone_wants_heat(zone: ZoneState, zone_opening: float) -> bool:
    if zone.heating_enabled is not True:
        return False
    opening = zone.demand
    if opening is not None:
        return opening > zone_opening
    return zone.calling is True


def boiler_demand(
    zones: Sequence[ZoneState], now: float, max_age: float | None, config: DemandConfig
) -> Demand:
    fresh = [z for z in zones if z.is_fresh(now, max_age)]
    if not fresh:
        return Demand(None)
    wanting = [z for z in fresh if zone_wants_heat(z, config.zone_opening)]
    openings = [z.demand for z in fresh if z.demand is not None and z.heating_enabled is True]
    widest = max(openings) if openings else None
    powers = [
        z.power * (z.demand if z.demand is not None else 1.0)
        for z in wanting
        if z.power is not None
    ]
    power = sum(powers) if powers else None
    wanted = len(wanting) >= config.count_threshold
    if config.power_threshold_kw is not None and power is not None:
        wanted = wanted or power >= config.power_threshold_kw
    if config.opening_threshold is not None and widest is not None:
        wanted = wanted or widest >= config.opening_threshold
    return Demand(wanted, len(wanting), power, widest, len(fresh))
