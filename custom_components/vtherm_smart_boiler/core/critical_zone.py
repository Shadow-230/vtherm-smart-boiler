"""Critical zone of a circuit: the zone whose own controller works hardest.

Its valve opening (or duty cycle) is the demand; among zones with about the same demand the one
furthest below its setpoint wins. A critical zone that is fully open and still too cold is
*saturated*: the water is too cold for it, so it bounds how low the circuit's water can go —
"too cold" judged against VT's setpoint. Only a room whose temperature is trusted counts
(``core.zones``).

The window rule (I12, decision 8; the user's decision of 2026-11-25): no room is the critical
zone, nor saturated, while its window is open, nor after it closes while it warms back. The
hold-off ends at the first of: the room back within ``BACK_K`` of its target, or no longer
warming — risen less than ``WARMING_K`` over the last ``WARMING_S``, from its own readings the
plugin keeps. Until it has been closed that long, warming cannot be told and the hold-off stays.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from .readings import ZoneState
from .zones import SelectionStatus, eligible_zones

DEFAULT_DEMAND_MARGIN = 0.1
DEFAULT_DEFICIT_MARGIN_K = 0.3
# The window rule (decided, the user's decision of 2026-11-25).
WARMING_K = 0.2  # a room that rose less over ``WARMING_S`` is not warming
WARMING_S = 30 * 60.0
BACK_K = 0.3  # a room this close below its target, or above it, is back
READING_S = 60.0  # a room's reading kept at most this often

type RoomReadings = tuple[tuple[float, float], ...]  # (time, °C), oldest first


@dataclass(frozen=True, slots=True)
class WindowHold:
    """A room's window as the critical zone sees it: open now, or closed at ``closed_at`` while
    the room warms back; neither: no hold-off."""

    open: bool = False
    closed_at: float | None = None

    @property
    def held(self) -> bool:
        return self.open or self.closed_at is not None


def keep_readings(readings: RoomReadings, now: float, temperature: float | None) -> RoomReadings:
    """A room's recent readings after a look at ``now``: this one added — none while unknown, nor
    within ``READING_S`` of the last kept —; those older than the rise over the last
    ``WARMING_S`` needs dropped — the newest at or before its start stays. One later than ``now``
    means the clock was set back: it goes (C9)."""
    kept = [reading for reading in readings if reading[0] <= now]
    if temperature is not None and (not kept or now - kept[-1][0] >= READING_S):
        kept.append((now, temperature))
    start = now - WARMING_S
    older = [i for i, (t, _value) in enumerate(kept) if t <= start]
    return tuple(kept[older[-1] :] if older else kept)


def rise(readings: RoomReadings, now: float, temperature: float | None) -> float | None:
    """How much the room rose over the last ``WARMING_S``: its temperature now minus the newest
    reading at or before the span's start; ``None`` without either."""
    before = [value for t, value in readings if t <= now - WARMING_S]
    if not before or temperature is None:
        return None
    return temperature - before[-1]


def follow_window(
    previous: WindowHold,
    open_now: bool,
    now: float,
    readings: RoomReadings,
    temperature: float | None,
    target: float | None,
) -> WindowHold:
    """The window rule at a look: held while the window is open; once it closes, until the room
    is within ``BACK_K`` of its ``target`` or no longer warming (``rise`` below ``WARMING_K``).
    Warming is told only once it has been closed for ``WARMING_S`` with a reading that old;
    until then, or while the room's temperature is not known, it stays held."""
    if open_now:
        return WindowHold(open=True)
    closed_at = now if previous.open else previous.closed_at
    if closed_at is None:
        return WindowHold()
    closed_at = min(closed_at, now)  # a clock set back counts from now (C9)
    if temperature is not None and target is not None and target - temperature <= BACK_K:
        return WindowHold()
    if now - closed_at >= WARMING_S:
        risen = rise(readings, now, temperature)
        if risen is not None and risen < WARMING_K:
            return WindowHold()
    return WindowHold(closed_at=closed_at)


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


def _demand(zone: ZoneState) -> float:
    return zone.demand if zone.demand is not None else -1.0


def _deficit_rank(zone: ZoneState) -> tuple[float, str]:
    return (zone.deficit if zone.deficit is not None else float("-inf")), zone.zone_id


def critical_zone(
    circuit_id: str,
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    previous: CriticalZone | None = None,
    demand_margin: float = DEFAULT_DEMAND_MARGIN,
    deficit_margin: float = DEFAULT_DEFICIT_MARGIN_K,
    held: Collection[str] = (),
) -> CriticalZone:
    """The critical zone among ``zones`` of one circuit, with hysteresis on the previous one.
    ``held``: the rooms the window rule holds off now (``follow_window``)."""
    found = eligible_zones(zones, now, max_age)
    if found.status is not SelectionStatus.OK:
        return CriticalZone(circuit_id, found.status)
    candidates = [z for z in found.zones if z.zone_id not in held]
    if not candidates:
        return CriticalZone(circuit_id, SelectionStatus.NO_VALID_MEASUREMENT)
    # The highest demand; among zones about as high, the one furthest below its setpoint.
    top = max(_demand(z) for z in candidates)
    close = [z for z in candidates if _demand(z) >= top - demand_margin]
    best = max(close, key=_deficit_rank)
    if previous is not None and previous.zone_id is not None:
        kept = next((z for z in candidates if z.zone_id == previous.zone_id), None)
        if kept is not None and not _clearly_worse(best, kept, demand_margin, deficit_margin):
            best = kept
    demand = best.demand
    deficit = best.deficit
    saturated = best.fully_open and deficit is not None and deficit > 0
    return CriticalZone(circuit_id, SelectionStatus.OK, best.zone_id, demand, deficit, saturated)
