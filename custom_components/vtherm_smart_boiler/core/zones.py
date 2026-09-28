"""Which VT zones count when the plugin picks one: taking part in heating, with valid readings.

One plausibility rule serves every room reading, −30 to 45 °C (S-06; ``core.limits``): frost
protection, the reference room and the critical zone alike — a narrower range would hide a cold
room. Setpoints keep 5 to 35 °C. A zone whose room sensor is lost (or whose VT safety mode is
on) keeps a frozen temperature, and one VT has not started runs nothing: neither is picked
(P-18).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .limits import PLAUSIBLE_ROOM
from .readings import ZoneState

SETPOINT_LOW = 5.0  # plausible room setpoint, °C
SETPOINT_HIGH = 35.0


class SelectionStatus(StrEnum):
    OK = "ok"
    NO_ACTIVE_ZONE = "no_active_zone"
    NO_VALID_MEASUREMENT = "no_valid_measurement"


def plausible_room(temperature: float) -> bool:
    """A room reading within the one plausibility rule (S-06)."""
    low, high = PLAUSIBLE_ROOM
    return low <= temperature <= high


def has_valid_readings(zone: ZoneState, now: float, max_age: float | None) -> bool:
    """Fresh, plausible room temperature and setpoint."""
    if not zone.is_fresh(now, max_age):
        return False
    temperature, target = zone.temperature, zone.target
    return (
        temperature is not None
        and plausible_room(temperature)
        and target is not None
        and SETPOINT_LOW <= target <= SETPOINT_HIGH
    )


@dataclass(frozen=True, slots=True)
class Eligible:
    status: SelectionStatus
    zones: tuple[ZoneState, ...] = ()


def eligible_zones(zones: Sequence[ZoneState], now: float, max_age: float | None) -> Eligible:
    """Zones in a heating mode with valid readings, VT running them and their room sensor
    there, or why there are none.

    ``zones`` are the zones taking part in the plugin's heating (assigned to its circuits).
    """
    active = [z for z in zones if z.heating_enabled is True]
    if not active:
        return Eligible(SelectionStatus.NO_ACTIVE_ZONE)
    valid = tuple(
        z
        for z in active
        if z.started and not z.room_sensor_lost and has_valid_readings(z, now, max_age)
    )
    if not valid:
        return Eligible(SelectionStatus.NO_VALID_MEASUREMENT)
    return Eligible(SelectionStatus.OK, valid)
