"""Entity transport: readings with units and freshness, and no way to write."""

from __future__ import annotations

import inspect

import pytest
from homeassistant.core import HomeAssistant

from custom_components.vtherm_smart_boiler import transport
from custom_components.vtherm_smart_boiler.core.signals import GatewayOutdoor, Signal
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


async def test_a_gateway_outdoor_zero_follows_the_last_reading(hass: HomeAssistant) -> None:
    """PB-21, M1: the gateway's outdoor 0 °C is a reading after one near 0, unknown with none
    yet, after one far away or after the entity was unavailable; a recorded state goes through
    a memory of its own and leaves the live one as it was; flow keeps the 0-is-unknown rule."""
    outdoor, flow = BOILER_ENTITIES[Signal.OUTDOOR], BOILER_ENTITIES[Signal.FLOW]
    gateway = frozenset({Signal.OUTDOOR, Signal.FLOW})
    link = EntityTransport(hass, {Signal.OUTDOOR: outdoor, Signal.FLOW: flow}, gateway)
    unit = {"unit_of_measurement": "°C"}

    def read(value: str) -> object:
        hass.states.async_set(outdoor, value, unit)
        return link.snapshot(now=1e10).number(Signal.OUTDOOR)

    assert read("0.0") is None  # no reading yet in this run
    assert read("1.0") == 1.0
    assert read("0.0") == 0.0
    assert read("0") == 0.0  # hours at freezing
    hass.states.async_set(flow, "0.0", unit)
    assert link.snapshot(now=1e10).number(Signal.FLOW) is None
    recorded = GatewayOutdoor()
    state = hass.states.get(outdoor)
    assert link.reading_of(Signal.OUTDOOR, state, recorded).value is None  # its own memory
    assert read("0.0") == 0.0  # the live memory unchanged
    assert read("unavailable") is None
    assert read("0.0") is None  # back from unavailable: a reset's 0
    assert read("8.0") == 8.0
    assert read("0.0") is None
    assert (
        EntityTransport(hass, {Signal.OUTDOOR: outdoor}).snapshot(1e10).number(Signal.OUTDOOR)
        == 0.0
    )  # not the gateway's: 0 is a reading


WRITE_WORDS = ("write", "set", "turn", "send", "publish", "command", "call", "service")


def test_transport_package_has_no_write_method() -> None:
    for module in (transport, transport.entities):
        for name, obj in inspect.getmembers(module):
            if inspect.isclass(obj) and obj.__module__ == module.__name__:
                methods = [
                    m for m, _ in inspect.getmembers(obj, callable) if not m.startswith("__")
                ]
                assert not [m for m in methods if any(w in m.lower() for w in WRITE_WORDS)], name


async def test_other_inputs(hass: HomeAssistant) -> None:
    from custom_components.vtherm_smart_boiler.core.foreign_heat import SourceKind
    from custom_components.vtherm_smart_boiler.transport.entities import (
        read_source,
        read_temperature,
        read_weather_temperature,
    )

    hass.states.async_set("sensor.mix", "95.0", {"unit_of_measurement": "°F"})
    assert read_temperature(hass, "sensor.mix").value == pytest.approx(35.0)
    hass.states.async_set("sensor.mix", "500", {"unit_of_measurement": "°C"})
    assert read_temperature(hass, "sensor.mix").value is None
    assert read_temperature(hass, "sensor.none").reported_at is None
    hass.states.async_set("switch.fire", "on")
    hass.states.async_set("sensor.heater", "1.2", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.stove", "140", {"unit_of_measurement": "°F"})
    assert read_source(hass, "switch.fire", SourceKind.SWITCH) is True
    assert read_source(hass, "sensor.heater", SourceKind.POWER) == pytest.approx(1200.0)
    assert read_source(hass, "sensor.stove", SourceKind.TEMPERATURE) == pytest.approx(60.0)
    assert read_source(hass, "sensor.none", SourceKind.POWER) is None
    hass.states.async_set("weather.x", "sunny", {"temperature": 41.0, "temperature_unit": "°F"})
    assert read_weather_temperature(hass, "weather.x").value == pytest.approx(5.0)


def test_a_restart_indicator_is_read_by_its_kind() -> None:
    """Q3.7: a duration is an uptime, a timestamp a boot time, any other number a restart
    counter; a value not known reads as ``None``."""
    from homeassistant.core import State

    from custom_components.vtherm_smart_boiler.core.hand_back import RestartKind, restart_seen
    from custom_components.vtherm_smart_boiler.transport.entities import restart_reading

    uptime = State("sensor.up", "120", {"device_class": "duration", "unit_of_measurement": "s"})
    assert restart_reading(uptime) == (120.0, RestartKind.UPTIME)
    assert restart_reading(State("sensor.up", "5", {"unit_of_measurement": "min"}))[1] is (
        RestartKind.UPTIME
    )
    boot = State("sensor.boot", "2026-01-12T08:00:00+00:00", {"device_class": "timestamp"})
    value, kind = restart_reading(boot)
    assert kind is RestartKind.BOOT_TIME
    assert value is not None
    assert restart_reading(State("sensor.boot", "unknown", {"device_class": "timestamp"})) == (
        None,
        RestartKind.BOOT_TIME,
    )
    assert restart_reading(State("sensor.count", "7")) == (7.0, RestartKind.COUNTER)
    assert restart_reading(State("sensor.count", "unavailable"))[0] is None
    assert restart_reading(None) == (None, RestartKind.COUNTER)
    assert restart_seen(5000.0, 12.0, RestartKind.UPTIME)
    assert not restart_seen(12.0, 72.0, RestartKind.UPTIME)  # counting on: no restart
    assert restart_seen(3.0, 4.0, RestartKind.COUNTER)
    assert restart_seen(4.0, 0.0, RestartKind.COUNTER)  # a reset counter: cautious, a trace
    assert not restart_seen(3.0, 3.0, RestartKind.COUNTER)
    assert restart_seen(1.0, 2.0, RestartKind.BOOT_TIME)
    assert not restart_seen(None, 2.0, RestartKind.BOOT_TIME)


def test_a_setpoint_entitys_grid_is_read_in_its_unit() -> None:
    """P-15: the grid of a number entity in its own unit; none without a step above 0 or in a
    unit that is not a temperature."""
    from homeassistant.core import State

    from custom_components.vtherm_smart_boiler.transport.entities import grid_from_state

    grid = grid_from_state(
        State("number.flow", "40", {"unit_of_measurement": "°F", "step": 1, "min": 50})
    )
    assert grid is not None
    assert grid.scale == pytest.approx(1.8)
    assert grid.offset == pytest.approx(32.0)
    assert grid.minimum == 50.0
    assert grid.maximum is None
    assert grid_from_state(State("number.flow", "40", {"unit_of_measurement": "°C"})) is None
    assert grid_from_state(State("number.flow", "40", {"step": 0})) is None
    assert grid_from_state(State("number.flow", "40", {"unit_of_measurement": "%", "step": 1})) is (
        None
    )
    assert grid_from_state(None) is None


async def test_unreadable_or_missing_inputs_read_as_unknown(hass: HomeAssistant) -> None:
    """P-35: what cannot be read is unknown, never a guess — a foreign-heat sensor that is not a
    number, a missing weather entity or one reporting an implausible temperature, a missing
    entity's bounds and unit."""
    from homeassistant.core import State

    from custom_components.vtherm_smart_boiler.core.foreign_heat import SourceKind
    from custom_components.vtherm_smart_boiler.transport.entities import (
        bounds_from_state,
        read_source,
        temperature_unit_of,
        weather_from_state,
    )

    hass.states.async_set("sensor.stove_power", "not a number", {"unit_of_measurement": "W"})
    assert read_source(hass, "sensor.stove_power", SourceKind.POWER) is None
    assert weather_from_state(None).value is None
    hot = State("weather.home", "sunny", {"temperature": 99.0, "temperature_unit": "°C"})
    assert weather_from_state(hot).value is None  # outside -60..60 °C
    assert bounds_from_state(None) == (None, None)
    assert temperature_unit_of(hass, "number.gone") is None


def test_a_malformed_restart_indicator_or_unit_is_unknown() -> None:
    """PB-41: a timestamp naming a date that does not exist, or a unit that is not text, reads
    as unknown, never raises."""
    from homeassistant.core import State

    from custom_components.vtherm_smart_boiler.core.hand_back import RestartKind
    from custom_components.vtherm_smart_boiler.transport.entities import (
        restart_reading,
        temperature_from_state,
        weather_from_state,
    )

    for bad in ("2026-13-45T00:00:00+00:00", "2026-02-30T08:00:00+00:00"):
        boot = State("sensor.boot", bad, {"device_class": "timestamp"})
        assert restart_reading(boot) == (None, RestartKind.BOOT_TIME)
    listed = State("sensor.up", "5", {"unit_of_measurement": ["min"]})
    assert restart_reading(listed) == (5.0, RestartKind.COUNTER)
    flow = State("sensor.flow", "50", {"unit_of_measurement": {"u": "°C"}})
    assert temperature_from_state(flow).value is None
    weather = State("weather.home", "sunny", {"temperature": 10**400, "temperature_unit": "°C"})
    assert weather_from_state(weather).value is None
    weather = State("weather.home", "sunny", {"temperature": 10.0, "temperature_unit": ["°C"]})
    assert weather_from_state(weather).value is None


@pytest.mark.parametrize(
    ("kind", "state", "unit"),
    [
        ("power", "150000", "W"),  # a meter's spike above 100 kW
        ("power", "-20", "W"),
        ("temperature", "-40", "°C"),
        ("temperature", "127", "°C"),  # a probe's fault value
    ],
)
async def test_an_implausible_foreign_heat_reading_is_unknown(
    hass: HomeAssistant, kind: str, state: str, unit: str
) -> None:
    """PB-43: a foreign-heat power or temperature source outside -30..110 °C or 0..100 kW reads
    as unknown, so one spike does not flag the zone as foreign-heated for an hour."""
    from custom_components.vtherm_smart_boiler.core.foreign_heat import SourceKind
    from custom_components.vtherm_smart_boiler.transport.entities import read_source

    hass.states.async_set("sensor.source", state, {"unit_of_measurement": unit})
    assert read_source(hass, "sensor.source", SourceKind(kind)) is None
    hass.states.async_set("sensor.source", "100", {"unit_of_measurement": unit})
    assert read_source(hass, "sensor.source", SourceKind(kind)) is not None
