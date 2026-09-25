"""Boiler demand from the VT zones — what VT's central boiler decided, now the plugin's job.

A zone wants heat when it is in a mode that may heat and VT says one of its devices is active
(its own view, the one its central boiler counts, with VT's minimum activation time respected);
without that, when its valve opening or duty cycle is above a few percent, else when VT says it
is heating. A zone in "auto" or heat_cool heats only while its action says so. The boiler has
demand when enough zones want heat, or — when set — their power or the widest valve opening
reaches a threshold; each criterion can stand alone, a count threshold of 0 turning the count
off, as in VT. Only zones whose state is known count: a zone that is unavailable, not started
by VT or whose room sensor has gone quiet is unknown, never "no demand"; with no zone known,
demand is unknown.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .readings import ZoneState


@dataclass(frozen=True, slots=True)
class DemandConfig:
    count_threshold: int = 1  # zones wanting heat; 0 turns the count off
    power_threshold_kw: float | None = None  # their power times opening, summed
    opening_threshold: float | None = None  # the widest opening, 0 to 1
    zone_opening: float = 0.05  # a zone wants heat above this opening or duty cycle

    def __post_init__(self) -> None:
        if self.count_threshold < 0:
            raise ValueError("the zone count threshold must not be negative")
        if not 0.0 <= self.zone_opening < 1.0:
            raise ValueError("the zone opening must be between 0 and 1")
        if (
            self.count_threshold == 0
            and self.power_threshold_kw is None
            and self.opening_threshold is None
        ):
            raise ValueError("at least one demand criterion must be set")
        if self.power_threshold_kw is not None and self.power_threshold_kw <= 0:
            raise ValueError("a power threshold must be above 0: 0 would mean demand for ever")
        if self.opening_threshold is not None and not 0.0 < self.opening_threshold <= 1.0:
            raise ValueError("an opening threshold must be above 0: 0 would mean demand for ever")


@dataclass(frozen=True, slots=True)
class Demand:
    wanted: bool | None  # None: no zone is known
    zones_wanting: int = 0
    power_kw: float | None = None
    widest_opening: float | None = None
    fresh_zones: int = 0  # the zones known now
    unknown: tuple[str, ...] = ()  # zones whose state is not known


def zone_wants_heat(zone: ZoneState, zone_opening: float) -> bool:
    if zone.heating_enabled is not True:
        return False
    opening = zone.demand
    if zone.auto_mode:
        if zone.calling is not None:
            return zone.calling
        return opening is not None and opening > zone_opening
    if zone.device_active is not None:
        return zone.device_active
    if opening is not None:
        return opening > zone_opening
    return zone.calling is True


def boiler_demand(
    zones: Sequence[ZoneState], now: float, max_age: float | None, config: DemandConfig
) -> Demand:
    known = [z for z in zones if z.is_known(now, max_age)]
    unknown = tuple(z.zone_id for z in zones if not z.is_known(now, max_age))
    if not known:
        return Demand(None, unknown=unknown)
    wanting = [z for z in known if zone_wants_heat(z, config.zone_opening)]
    openings = [z.demand for z in known if z.demand is not None and z.heating_enabled is True]
    widest = max(openings) if openings else None
    powers = [
        z.power * (z.demand if z.demand is not None else 1.0)
        for z in wanting
        if z.power is not None
    ]
    power = sum(powers) if powers else None
    # Never more zones than are known: an unknown zone must not make the count unreachable.
    count = min(config.count_threshold, len(known))
    wanted = count > 0 and len(wanting) >= count
    if config.power_threshold_kw is not None and power is not None:
        wanted = wanted or power >= config.power_threshold_kw
    if config.opening_threshold is not None and widest is not None:
        wanted = wanted or widest >= config.opening_threshold
    return Demand(wanted, len(wanting), power, widest, len(known), unknown)
