"""Critical zone of a circuit: the zone whose own controller works hardest.

Its valve opening (or duty cycle) is the demand; among zones with about the same demand the one
furthest below its setpoint wins. A critical zone that is fully open and still too cold is
*saturated*: the water is too cold for it, so it bounds how low the circuit's water can go.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .readings import ZoneState
from .zones import SelectionStatus, eligible_zones

DEFAULT_DEMAND_MARGIN = 0.1
DEFAULT_DEFICIT_MARGIN_K = 0.3
SATURATED_DEMAND = 0.95


@dataclass(frozen=True, slots=True)
class CriticalZone:
    circuit_id: str
    status: SelectionStatus
    zone_id: str | None = None
    demand: float | None = None
    deficit: float | None = None
    saturated: bool = False


def _clearly_worse(
    candidate: ZoneState, current: ZoneState, demand_margin: float, deficit_margin: float
) -> bool:
    """Whether ``candidate`` needs heat clearly more than ``current``."""
    cand, curr = candidate.demand, current.demand
    if cand is not None and curr is not None:
        if cand > curr + demand_margin:
            return True
        if cand < curr - demand_margin:
            return False
    elif cand is not None:
        return True
    elif curr is not None:
        return False
    cand_deficit, curr_deficit = candidate.deficit, current.deficit
    return (
        cand_deficit is not None
        and curr_deficit is not None
        and cand_deficit > curr_deficit + deficit_margin
    )


def _rank(zone: ZoneState) -> tuple[float, float, str]:
    demand = zone.demand if zone.demand is not None else -1.0
    deficit = zone.deficit if zone.deficit is not None else float("-inf")
    return demand, deficit, zone.zone_id


def critical_zone(
    circuit_id: str,
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    previous: CriticalZone | None = None,
    demand_margin: float = DEFAULT_DEMAND_MARGIN,
    deficit_margin: float = DEFAULT_DEFICIT_MARGIN_K,
) -> CriticalZone:
    """The critical zone among ``zones`` of one circuit, with hysteresis on the previous one."""
    found = eligible_zones(zones, now, max_age)
    if found.status is not SelectionStatus.OK:
        return CriticalZone(circuit_id, found.status)
    best = max(found.zones, key=_rank)
    if previous is not None and previous.zone_id is not None:
        kept = next((z for z in found.zones if z.zone_id == previous.zone_id), None)
        if kept is not None and not _clearly_worse(best, kept, demand_margin, deficit_margin):
            best = kept
    demand = best.demand
    deficit = best.deficit
    saturated = (
        demand is not None and demand >= SATURATED_DEMAND and deficit is not None and deficit > 0
    )
    return CriticalZone(circuit_id, SelectionStatus.OK, best.zone_id, demand, deficit, saturated)
