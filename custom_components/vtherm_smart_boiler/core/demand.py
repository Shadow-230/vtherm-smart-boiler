"""Boiler demand from the VT zones — what VT's central boiler decided, now the plugin's job.

A zone wants heat when it is in a mode that may heat and VT says one of its devices is active
(its own view, the one its central boiler counts, with VT's minimum activation time respected);
without that, when its valve opening or duty cycle is above a few percent, else when VT says it
is heating. A zone in "auto" or heat_cool heats only while its action says so; one VT's power
shedding holds off wants nothing. The boiler has demand when enough zones want heat, or — when
set — their power or the widest valve opening reaches a threshold; each criterion can stand
alone, a count threshold of 0 turning the count off, as in VT:

- the count: the zones that want heat, never more than are known;
- the power: each zone's mean power over its cycle, as VT counts it — a switch zone keeps it
  through the off part of its cycle — summed over the zones in a heating mode, and counted only
  while at least one zone that calls has its valve open or its device on: without that no heat
  can flow, and the criterion asks for nothing;
- the opening: the widest opening among the zones that call.

A criterion no known zone can feed — no device power above 0 (VT publishes 0 when none is set),
no opening or duty cycle at all — has no data: it is left out, and when no configured criterion
can be judged, demand is unknown, never a silent "no" (P-14; decision 3 then decides). Only
zones whose state is known count: a zone that is unavailable, heating while VT has not started
it, or whose room sensor has gone quiet is unknown, never "no demand"; a zone in its grace
period keeps its last known answer (``memory``); with no zone known, demand is unknown.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .readings import ZONE_OPEN, ZoneState

COUNT, POWER, OPENING = "count", "power", "opening"  # the criteria, as the alarm names them


@dataclass(frozen=True, slots=True)
class DemandConfig:
    count_threshold: int = 1  # zones wanting heat; 0 turns the count off
    power_threshold_kw: float | None = None  # their mean power over the cycle, summed
    opening_threshold: float | None = None  # the widest opening of a calling zone, 0 to 1
    zone_opening: float = ZONE_OPEN  # a zone wants heat above this opening or duty cycle

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
    wanted: bool | None  # None: no zone is known, or no configured criterion can be judged
    zones_wanting: int = 0
    power_kw: float | None = None  # None: no known zone feeds the power criterion
    widest_opening: float | None = None
    fresh_zones: int = 0  # the zones known now, those in their grace period included
    unknown: tuple[str, ...] = ()  # zones whose state is not known
    # Configured criteria no known zone can feed: left out of the decision.
    criteria_without_data: tuple[str, ...] = ()


def zone_wants_heat(zone: ZoneState, zone_opening: float) -> bool:
    if zone.heating_enabled is not True or zone.shedding:
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


def heat_can_flow(zone: ZoneState, zone_opening: float) -> bool:
    """The zone calls and heat can reach it now: its valve is open or its device is on. A zone
    whose VT shows neither (an older VT) is judged by its call alone."""
    if not zone_wants_heat(zone, zone_opening):
        return False
    if zone.device_active is True:
        return True
    if zone.valve_open is not None:
        return zone.valve_open > zone_opening
    return zone.device_active is None


def _mean_power(zone: ZoneState, zone_opening: float) -> float:
    """A zone's share of the power criterion, in kW: its mean power over the cycle; a zone VT
    gives only a device power, without a duty cycle, counts it while it calls (an older VT's
    over_climate). 0 or less counts nothing, as in VT."""
    power = zone.cycle_power
    if power is None:
        called = zone.power is not None and zone_wants_heat(zone, zone_opening)
        power = zone.power if called and zone.power is not None else 0.0
    return max(0.0, power)


def feeds_power(zone: ZoneState) -> bool:
    """VT gives the zone a device power, or a mean power, above 0 (P-14: 0 is no data)."""
    mean = zone.mean_power
    return zone.power is not None or (mean is not None and mean > 0.0)


def feeds_opening(zone: ZoneState) -> bool:
    """VT publishes the zone's valve opening or duty cycle."""
    return zone.demand is not None


def boiler_demand(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    config: DemandConfig,
    *,
    memory: Mapping[str, ZoneState] | None = None,
    recognition: bool = False,
) -> Demand:
    """Demand now. ``memory``: the last known state of each zone in its grace period, which
    stands for the zone whatever it shows now; ``recognition``: the recognition period runs, so
    a zone VT has not started is not known yet, whatever its mode (decision 3)."""
    memory = memory or {}
    known: list[ZoneState] = []
    unknown: list[str] = []
    for zone in zones:
        if zone.zone_id in memory:
            known.append(memory[zone.zone_id])
        elif zone.is_known(now, max_age, recognition):
            known.append(zone)
        else:
            unknown.append(zone.zone_id)
    if not known:
        return Demand(None, unknown=tuple(unknown))
    opening = config.zone_opening
    wanting = [z for z in known if zone_wants_heat(z, opening)]
    openings = [z.demand for z in wanting if z.demand is not None]
    widest = max(openings) if openings else None
    power: float | None = None
    if any(feeds_power(z) for z in known):
        heating = [z for z in known if z.heating_enabled is True and not z.shedding]
        flowing = any(heat_can_flow(z, opening) for z in heating)
        power = sum(_mean_power(z, opening) for z in heating) if flowing else 0.0
    judged: list[bool] = []
    without: list[str] = []
    if config.count_threshold > 0:
        # Never more zones than are known: an unknown zone must not make the count unreachable.
        count = min(config.count_threshold, len(known))
        judged.append(len(wanting) >= count)
    if config.power_threshold_kw is not None:
        if power is None:
            without.append(POWER)
        else:
            judged.append(power >= config.power_threshold_kw)
    if config.opening_threshold is not None:
        if not any(feeds_opening(z) for z in known):
            without.append(OPENING)
        else:
            judged.append(widest is not None and widest >= config.opening_threshold)
    wanted = any(judged) if judged else None
    return Demand(wanted, len(wanting), power, widest, len(known), tuple(unknown), tuple(without))
