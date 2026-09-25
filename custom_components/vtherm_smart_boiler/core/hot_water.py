"""Hot water available: whether heat is reaching a zone's emitters right now."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .supply import Supply, SupplyReason

DEFAULT_NEAR_ROOM_K = 3.0
DEFAULT_HYSTERESIS_K = 1.0


class HotWaterReason(StrEnum):
    DHW_ACTIVE = "dhw_active"
    FLOW_NEAR_ROOM = "flow_near_room"
    FLOW_STALE = "flow_stale"
    FLOW_UNKNOWN = "flow_unknown"
    CIRCUIT_NOT_MEASURED = "circuit_not_measured"
    ROOM_UNKNOWN = "room_unknown"


@dataclass(frozen=True, slots=True)
class HotWater:
    """``available`` is ``None`` when it cannot be told; ``reason`` explains a no or an unknown."""

    available: bool | None
    reason: HotWaterReason | None = None
    excess: float | None = None  # supply minus room, K


def hot_water_available(
    supply: Supply,
    room: float | None,
    dhw_active: bool | None,
    previous: bool | None = None,
    near_room_k: float = DEFAULT_NEAR_ROOM_K,
    hysteresis_k: float = DEFAULT_HYSTERESIS_K,
) -> HotWater:
    """No while DHW is active, while the supply is near room temperature, or stale or unknown.

    An unknown DHW state does not block: only a known DHW run does. A mixed circuit without its
    own sensor cannot be told. Once available, the supply must fall ``hysteresis_k`` below the
    margin before it counts as near the room again.
    """
    if dhw_active is True:
        return HotWater(False, HotWaterReason.DHW_ACTIVE)
    if supply.temperature is None:
        if supply.reason is SupplyReason.CIRCUIT_NOT_MEASURED:
            return HotWater(None, HotWaterReason.CIRCUIT_NOT_MEASURED)
        # Unknown, not "no", while the flow is unknown or stale (the user's decision).
        if supply.reason is SupplyReason.FLOW_STALE:
            return HotWater(None, HotWaterReason.FLOW_STALE)
        return HotWater(None, HotWaterReason.FLOW_UNKNOWN)
    if room is None:
        return HotWater(None, HotWaterReason.ROOM_UNKNOWN)
    excess = supply.temperature - room
    threshold = near_room_k - hysteresis_k if previous is True else near_room_k
    if excess > threshold:
        return HotWater(True, None, excess)
    return HotWater(False, HotWaterReason.FLOW_NEAR_ROOM, excess)
