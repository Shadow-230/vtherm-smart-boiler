"""Which VT zones count when the plugin picks one: taking part in heating, with valid readings."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .readings import ZoneState

ROOM_LOW = 5.0  # plausible room temperature and setpoint, °C
ROOM_HIGH = 35.0


class SelectionStatus(StrEnum):
    OK = "ok"
    NO_ACTIVE_ZONE = "no_active_zone"
    NO_VALID_MEASUREMENT = "no_valid_measurement"


def has_valid_readings(zone: ZoneState, now: float, max_age: float | None) -> bool:
    """Fresh, plausible room temperature and setpoint."""
    if not zone.is_fresh(now, max_age):
        return False
    return all(
        value is not None and ROOM_LOW <= value <= ROOM_HIGH
        for value in (zone.temperature, zone.target)
    )


@dataclass(frozen=True, slots=True)
class Eligible:
    status: SelectionStatus
    zones: tuple[ZoneState, ...] = ()


def eligible_zones(zones: Sequence[ZoneState], now: float, max_age: float | None) -> Eligible:
    """Zones in a heating mode with valid readings, or why there are none.

    ``zones`` are the zones taking part in the plugin's heating (assigned to its circuits).
    """
    active = [z for z in zones if z.heating_enabled is True]
    if not active:
        return Eligible(SelectionStatus.NO_ACTIVE_ZONE)
    valid = tuple(z for z in active if has_valid_readings(z, now, max_age))
    if not valid:
        return Eligible(SelectionStatus.NO_VALID_MEASUREMENT)
    return Eligible(SelectionStatus.OK, valid)
