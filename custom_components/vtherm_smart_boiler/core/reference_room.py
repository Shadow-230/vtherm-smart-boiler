"""Reference room: one room temperature and setpoint for controllers that need a single room.

Only zones taking part in heating with valid readings count; temperature and setpoint always come
from the same zone (or, for the average, the same set of zones). The choice changes only on a
clear difference, but at once when the chosen zone drops out. There is no invented fallback:
"no active zone" and "no valid measurement" are explicit states.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .readings import ZoneState
from .zones import SelectionStatus, eligible_zones

DEFAULT_SWITCH_MARGIN_K = 0.3


class Strategy(StrEnum):
    LARGEST_DEFICIT = "largest_deficit"
    CHOSEN_ZONE = "chosen_zone"
    AVERAGE = "average"


@dataclass(frozen=True, slots=True)
class ReferenceRoom:
    status: SelectionStatus
    zone_id: str | None = None  # the selected zone; None for the average or without a reference
    temperature: float | None = None
    target: float | None = None
    zones: tuple[str, ...] = ()  # zones the values come from

    @property
    def deficit(self) -> float | None:
        if self.temperature is None or self.target is None:
            return None
        return self.target - self.temperature


def _from_zone(zone: ZoneState) -> ReferenceRoom:
    return ReferenceRoom(
        SelectionStatus.OK, zone.zone_id, zone.temperature, zone.target, (zone.zone_id,)
    )


def select_reference(
    zones: Sequence[ZoneState],
    strategy: Strategy,
    now: float,
    max_age: float | None,
    previous: ReferenceRoom | None = None,
    chosen_zone: str | None = None,
    switch_margin: float = DEFAULT_SWITCH_MARGIN_K,
) -> ReferenceRoom:
    """The reference room now, given the previous one for the selection hysteresis."""
    if strategy is Strategy.CHOSEN_ZONE:
        chosen = [z for z in zones if z.zone_id == chosen_zone]
        found = eligible_zones(chosen, now, max_age)
        if found.status is not SelectionStatus.OK:
            return ReferenceRoom(found.status)
        return _from_zone(found.zones[0])

    found = eligible_zones(zones, now, max_age)
    if found.status is not SelectionStatus.OK:
        return ReferenceRoom(found.status)
    valid = found.zones

    if strategy is Strategy.AVERAGE:
        # Temperature and setpoint averaged over one and the same set of zones (S29).
        pairs = [
            (z.zone_id, z.temperature, z.target)
            for z in valid
            if z.temperature is not None and z.target is not None
        ]
        return ReferenceRoom(
            SelectionStatus.OK,
            None,
            sum(temperature for _, temperature, _ in pairs) / len(pairs),
            sum(target for _, _, target in pairs) / len(pairs),
            tuple(sorted(zone_id for zone_id, _, _ in pairs)),
        )

    # Largest signed deficit: an overheated room wins only when every room is overheated.
    best = max(valid, key=lambda z: (z.deficit, z.zone_id))
    if previous is not None and previous.zone_id is not None:
        kept = next((z for z in valid if z.zone_id == previous.zone_id), None)
        if (
            kept is not None
            and kept.deficit is not None
            and best.deficit is not None
            and best.deficit <= kept.deficit + switch_margin
        ):
            return _from_zone(kept)
    return _from_zone(best)
