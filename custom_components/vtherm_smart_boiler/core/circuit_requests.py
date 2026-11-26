"""Circuits run by other automation (I8, decisions F3 and F6): a mixer or a pump the plugin
never drives. Such a circuit asks for heat through an entity of its own — the boiler heats for
it as for a VT zone asking — and through its VT zones; while it asks, the boiler's water stays
at or above its need. Nothing is added to the need: a mixer standing open with the water at its
target is no problem (the user's decision of 2026-10-14), and a circuit needing headroom says so
in its need. Pure logic: the entities' readings come in as values."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OtherAutomation:
    """A circuit run by other automation. ``requests``: an entity says whether it asks for
    heat; ``needed``: the water it needs, entered — an entity's reading of it comes first.
    ``every_room``: the only circuit, which every room is on (I12.11) — ``zones`` then unused."""

    circuit_id: str
    zones: frozenset[str] = frozenset()
    requests: bool = False
    needed: float | None = None
    every_room: bool = False

    def asks_through(self, zones_wanting: Collection[str]) -> bool:
        """One of its zones wants heat. A zone it feeds by some devices only (I8.8b) asks
        through it too: ``vtherm_api`` does not tell which devices VT has on (I12.7) — the warmer
        side."""
        if self.every_room:
            return bool(zones_wanting)
        return any(zone in zones_wanting for zone in self.zones)


@dataclass(frozen=True, slots=True)
class CircuitsAsking:
    """Which circuits ask now, which cannot say (their entity unreadable: they do not ask, the
    user's answer of 2026-10-12), and the water they hold: the highest need among those asking
    with a need known; ``None`` without one."""

    asking: tuple[str, ...] = ()
    unknown: tuple[str, ...] = ()
    floor: float | None = None


def circuits_asking(
    circuits: Sequence[OtherAutomation],
    requests: Mapping[str, bool | None],
    needs: Mapping[str, float | None],
    zones_wanting: Collection[str],
) -> CircuitsAsking:
    """The circuits run by other automation that ask now — their entity on, or one of their
    zones wanting heat — and the floor their needs set. ``requests``: each entity's reading
    (``None``: unreadable); ``needs``: each need entity's reading (``None``: unreadable, the
    value entered then)."""
    asking: list[str] = []
    unknown: list[str] = []
    floor: float | None = None
    for circuit in circuits:
        request = requests.get(circuit.circuit_id) if circuit.requests else False
        if request is None:
            unknown.append(circuit.circuit_id)
        if request is not True and not circuit.asks_through(zones_wanting):
            continue
        asking.append(circuit.circuit_id)
        reported = needs.get(circuit.circuit_id)
        need = reported if reported is not None else circuit.needed
        if need is not None:
            floor = need if floor is None else max(floor, need)
    return CircuitsAsking(tuple(asking), tuple(unknown), floor)
