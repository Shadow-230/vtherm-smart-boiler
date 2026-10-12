"""I8.8 (decisions F3, F6): circuits run by other automation — a mixer or a pump the plugin
never drives — ask for heat through an entity of their own and their VT zones; while one asks,
the boiler's water stays at or above its need plus a margin."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.circuit_requests import (
    OTHER_AUTOMATION_MARGIN_K,
    OtherAutomation,
    circuits_asking,
)

MIXER = OtherAutomation("floor", zones=frozenset({"climate.bath"}), requests=True, needed=35.0)


def test_a_circuit_asks_through_its_entity_and_its_need_holds_the_water() -> None:
    """Its entity on: it asks, and the water holds its need plus the margin."""
    found = circuits_asking((MIXER,), {"floor": True}, {}, frozenset())
    assert found.asking == ("floor",)
    assert found.unknown == ()
    assert found.floor == 35.0 + OTHER_AUTOMATION_MARGIN_K


def test_a_circuit_asks_through_its_zones_too() -> None:
    """Its entity off, one of its VT zones asking: it asks, as a zone does."""
    found = circuits_asking((MIXER,), {"floor": False}, {}, frozenset({"climate.bath"}))
    assert found.asking == ("floor",)
    assert found.floor == 40.0


@pytest.mark.parametrize("reading", [None, False])
def test_an_unknown_or_quiet_request_does_not_ask(reading: bool | None) -> None:
    """The user's answer of 2026-10-12: an entity that cannot be read does not ask — named, so
    the control state can say why; one that reads off asks nothing either. No need applies."""
    found = circuits_asking((MIXER,), {"floor": reading}, {}, frozenset({"climate.other"}))
    assert found.asking == ()
    assert found.floor is None
    assert found.unknown == (("floor",) if reading is None else ())


def test_the_needs_entity_comes_first_its_value_without_it() -> None:
    """The need an entity reports comes first; unknown, the value entered; neither, no floor —
    the curve gives the water (Claude's call)."""
    assert circuits_asking((MIXER,), {"floor": True}, {"floor": 50.0}, frozenset()).floor == 55.0
    assert circuits_asking((MIXER,), {"floor": True}, {"floor": None}, frozenset()).floor == 40.0
    bare = OtherAutomation("floor", requests=True)
    found = circuits_asking((bare,), {"floor": True}, {}, frozenset())
    assert found.asking == ("floor",)
    assert found.floor is None


def test_the_highest_need_of_those_asking_wins() -> None:
    """Several asking: the highest need, plus the margin; one not asking adds none."""
    hot = OtherAutomation("pool", requests=True, needed=55.0)
    cool = OtherAutomation("floor", requests=True, needed=35.0)
    quiet = OtherAutomation("garage", requests=True, needed=70.0)
    requests = {"pool": True, "floor": True, "garage": False}
    found = circuits_asking((cool, hot, quiet), requests, {}, frozenset())
    assert found.asking == ("floor", "pool")
    assert found.floor == 60.0


def test_a_circuit_without_its_own_entity_asks_through_its_zones_alone() -> None:
    """No request entity: never unknown, asking only through its zones."""
    zones_only = OtherAutomation("floor", zones=frozenset({"climate.bath"}), needed=30.0)
    assert circuits_asking((zones_only,), {}, {}, frozenset()).asking == ()
    found = circuits_asking((zones_only,), {}, {}, frozenset({"climate.bath"}))
    assert (found.asking, found.unknown, found.floor) == (("floor",), (), 35.0)


def test_a_zone_split_by_its_devices_asks_through_its_devices_there() -> None:
    """I8.8b (Claude's call): a zone listed by its devices asks in the circuit while it wants
    heat and VT lists one of those devices active; VT's list unknown (an older VT), it asks in
    each of its circuits — the warmer side."""
    split = OtherAutomation(
        "floor",
        zones=frozenset({"climate.living"}),
        needed=35.0,
        devices={"climate.living": frozenset({"switch.loop"})},
    )
    wanting = frozenset({"climate.living"})

    def asking(active: frozenset[str] | None) -> tuple[str, ...]:
        found = circuits_asking((split,), {}, {}, wanting, {"climate.living": active})
        return found.asking

    assert asking(frozenset({"switch.loop", "switch.radiator"})) == ("floor",)
    assert asking(frozenset({"switch.radiator"})) == ()
    assert asking(frozenset()) == ()
    assert asking(None) == ("floor",)
    assert circuits_asking((split,), {}, {}, wanting).asking == ("floor",)  # nothing read
    assert circuits_asking((split,), {}, {}, frozenset()).asking == ()  # not wanting heat
