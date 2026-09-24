"""Entity transport: readings with units and freshness, and no way to write."""

from __future__ import annotations

import inspect

import pytest
from homeassistant.core import HomeAssistant

from custom_components.vtherm_smart_boiler import transport
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.transport.entities import EntityTransport

from .harness import BOILER_ENTITIES, FakeBoiler


async def test_snapshot_reads_the_mapped_entities(hass: HomeAssistant, boiler: FakeBoiler) -> None:
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 52.0, Signal.PRESSURE: 1.4})
    hass.states.async_set(BOILER_ENTITIES[Signal.RETURN], "104.0", {"unit_of_measurement": "°F"})
    mapping = {
        s: BOILER_ENTITIES[s]
        for s in (Signal.FLAME, Signal.FLOW, Signal.RETURN, Signal.PRESSURE, Signal.MODULATION)
    }
    link = EntityTransport(hass, mapping)
    snapshot = link.snapshot(now=1e10)
    assert snapshot.flag(Signal.FLAME) is True
    assert snapshot.number(Signal.FLOW) == 52.0
    assert snapshot.number(Signal.RETURN) == pytest.approx(40.0)
    assert snapshot.number(Signal.PRESSURE) == 1.4
    assert snapshot.is_mapped(Signal.MODULATION)
    assert snapshot.reading(Signal.MODULATION).value is None  # entity does not exist
    assert not snapshot.is_mapped(Signal.GAS_METER)
    assert snapshot.reading(Signal.FLOW).reported_at is not None
    assert link.signal_of(BOILER_ENTITIES[Signal.FLOW]) is Signal.FLOW


async def test_implausible_and_unavailable_states_are_unknown(
    hass: HomeAssistant, boiler: FakeBoiler
) -> None:
    boiler.set_many({Signal.FLOW: 180.0, Signal.FLAME: None})
    link = EntityTransport(hass, {s: BOILER_ENTITIES[s] for s in (Signal.FLOW, Signal.FLAME)})
    snapshot = link.snapshot(now=1e10)
    assert snapshot.number(Signal.FLOW) is None
    assert snapshot.flag(Signal.FLAME) is None


WRITE_WORDS = ("write", "set", "turn", "send", "publish", "command", "call", "service")


def test_transport_package_has_no_write_method() -> None:
    for module in (transport, transport.entities):
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and obj.__module__ == module.__name__:
                methods = [
                    m for m, _ in inspect.getmembers(obj, callable) if not m.startswith("__")
                ]
                assert not [m for m in methods if any(w in m.lower() for w in WRITE_WORDS)], name
