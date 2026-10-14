"""Circuits run by other automation (I8, decisions F3 and F6): a mixer or a pump the plugin
never drives. Such a circuit asks for heat through an entity of its own — the boiler heats for
it as for a VT zone asking — and through its VT zones; while it asks, the boiler's water stays
at or above its need. Nothing is added to the need: a mixer standing open with the water at its
target is no problem (the user's decision of 2026-10-14), and a circuit needing headroom says so
in its need. Pure logic: the entities' readings come in as values."""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class OtherAutomation:
    """A circuit run by other automation. ``requests``: an entity says whether it asks for
    heat; ``needed``: the water it needs, entered — an entity's reading of it comes first.
    ``devices``: for a zone it feeds only some devices of, those devices (I8.8b)."""

    circuit_id: str
    zones: frozenset[str] = frozenset()
    requests: bool = False
    needed: float | None = None
    devices: Mapping[str, frozenset[str]] = field(default_factory=dict)

    def asks_through(
        self, zones_wanting: Collection[str], active: Mapping[str, frozenset[str] | None]
    ) -> bool:
        """One of its zones wants heat — a zone it feeds by some devices only while VT lists
        one of them active, or while VT's list is not known (an older VT): the warmer side."""
        for zone in self.zones:
            if zone not in zones_wanting:
                continue
            devices = self.devices.get(zone)
            running = active.get(zone)
            if not devices or running is None or devices & running:
                return True
        return False


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
    devices_active: Mapping[str, frozenset[str] | None] | None = None,
) -> CircuitsAsking:
    """The circuits run by other automation that ask now — their entity on, or one of their
    zones wanting heat — and the floor their needs set. ``requests``: each entity's reading
    (``None``: unreadable); ``needs``: each need entity's reading (``None``: unreadable, the
    value entered then); ``devices_active``: by zone, the devices VT lists active (``None``
    or absent: not known)."""
    active = devices_active or {}
    asking: list[str] = []
    unknown: list[str] = []
    floor: float | None = None
    for circuit in circuits:
        request = requests.get(circuit.circuit_id) if circuit.requests else False
        if request is None:
            unknown.append(circuit.circuit_id)
        if request is not True and not circuit.asks_through(zones_wanting, active):
            continue
        asking.append(circuit.circuit_id)
        reported = needs.get(circuit.circuit_id)
        need = reported if reported is not None else circuit.needed
        if need is not None:
            floor = need if floor is None else max(floor, need)
    return CircuitsAsking(tuple(asking), tuple(unknown), floor)
