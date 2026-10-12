"""Heat available: whether the boiler's heat is reaching a zone's emitters right now — the one
value VT's thermostats are shown (I8, decision C1)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from .supply import Supply, SupplyReason

# The flow clearly above the return: the emitters are taking heat. Against the room only where
# no return is known, by a wider margin, as a room reading lags the water. Once available, the
# difference must fall the hysteresis below its margin to count as no heat again (provisional,
# K4).
RETURN_MARGIN_K = 2.0
ROOM_MARGIN_K = 3.0
HYSTERESIS_K = 1.0


class HeatReason(StrEnum):
    DHW_ACTIVE = "dhw_active"
    FLAME_OFF = "flame_off"
    FLAME_UNKNOWN = "flame_unknown"
    FLOW_NEAR_RETURN = "flow_near_return"
    FLOW_NEAR_ROOM = "flow_near_room"
    FLOW_STALE = "flow_stale"
    FLOW_UNKNOWN = "flow_unknown"
    CIRCUIT_NOT_MEASURED = "circuit_not_measured"
    ROOM_UNKNOWN = "room_unknown"


class Against(StrEnum):
    RETURN = "return"
    ROOM = "room"


@dataclass(frozen=True, slots=True)
class Heat:
    """``available`` is ``None`` when it cannot be told; ``reason`` explains a no or an unknown;
    ``excess`` is the flow above what it was judged ``against``, in K."""

    available: bool | None
    reason: HeatReason | None = None
    excess: float | None = None
    against: Against | None = None


def heat_available(
    supply: Supply,
    flame: bool | None,
    return_temp: float | None,
    room: float | None,
    dhw_active: bool | None,
    previous: bool | None = None,
    *,
    flame_mapped: bool = True,
) -> Heat:
    """Yes while the flame burns and the flow is clearly above the return — above the room
    where no return is known. No while hot water with priority takes the heat or the flame is
    out; unknown while a mapped flame, the flow or what it is judged against is unknown or
    stale. Without a flame signal the flow alone decides (the missing-data rule).

    An unknown hot-water state does not block: only a known draw does. A mixed circuit without
    its own sensor cannot be told; its water goes back through its own mixing, so it is judged
    against the room.
    """
    if dhw_active is True:
        return Heat(False, HeatReason.DHW_ACTIVE)
    if flame is False:
        return Heat(False, HeatReason.FLAME_OFF)
    if flame is None and flame_mapped:
        return Heat(None, HeatReason.FLAME_UNKNOWN)
    if supply.temperature is None:
        if supply.reason is SupplyReason.CIRCUIT_NOT_MEASURED:
            return Heat(None, HeatReason.CIRCUIT_NOT_MEASURED)
        # Unknown, not "no", while the flow is unknown or stale (the user's decision).
        if supply.reason is SupplyReason.FLOW_STALE:
            return Heat(None, HeatReason.FLOW_STALE)
        return Heat(None, HeatReason.FLOW_UNKNOWN)
    if return_temp is not None:
        against, base, margin = Against.RETURN, return_temp, RETURN_MARGIN_K
        near = HeatReason.FLOW_NEAR_RETURN
    elif room is not None:
        against, base, margin = Against.ROOM, room, ROOM_MARGIN_K
        near = HeatReason.FLOW_NEAR_ROOM
    else:
        return Heat(None, HeatReason.ROOM_UNKNOWN)
    excess = supply.temperature - base
    threshold = margin - HYSTERESIS_K if previous is True else margin
    if excess > threshold:
        return Heat(True, None, excess, against)
    return Heat(False, near, excess, against)


def heat_through_any(heats: Sequence[Heat]) -> Heat:
    """A zone fed by several circuits through its devices (I8.8b): heat while any circuit
    brings it; else what cannot be told, before a no; else the first no."""
    return next(
        (h for h in heats if h.available is True),
        next((h for h in heats if h.available is None), heats[0]),
    )
