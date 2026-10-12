"""Circuits run by other automation (I8, decisions F3 and F6): a mixer or a pump the plugin
never drives. Such a circuit asks for heat through an entity of its own — the boiler heats for
it as for a VT zone asking — and through its VT zones; while it asks, the boiler's water stays
at or above its need plus a margin. Pure logic: the entities' readings come in as values."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass

# The water kept above a circuit's need, for the mixer to mix down from (provisional, K4) — as
# a fixed valve's margin.
OTHER_AUTOMATION_MARGIN_K = 5.0


@dataclass(frozen=True, slots=True)
class OtherAutomation:
    """A circuit run by other automation. ``requests``: an entity says whether it asks for
    heat; ``needed``: the water it needs, entered — an entity's reading of it comes first."""

    circuit_id: str
    zones: frozenset[str] = frozenset()
    requests: bool = False
    needed: float | None = None


@dataclass(frozen=True, slots=True)
class CircuitsAsking:
    """Which circuits ask now, which cannot say (their entity unreadable: they do not ask, the
    user's answer of 2026-10-12), and the water they hold: the highest need plus the margin
    among those asking with a need known; ``None`` without one."""

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
        if request is not True and not circuit.zones & set(zones_wanting):
            continue
        asking.append(circuit.circuit_id)
        reported = needs.get(circuit.circuit_id)
        need = reported if reported is not None else circuit.needed
        if need is not None:
            held = need + OTHER_AUTOMATION_MARGIN_K
            floor = held if floor is None else max(floor, held)
    return CircuitsAsking(tuple(asking), tuple(unknown), floor)
