"""I6.5 (decision 9): freshness limits a source earns, and the device's own MQTT repeats."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_mqtt_message

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW)


async def set_up(hass: HomeAssistant, options: dict[str, Any]) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def boiler_options(fake: FakeBoiler, **extra: Any) -> dict[str, Any]:
    return {"signals": fake.mapping()} | extra


async def look(hass: HomeAssistant, entry: MockConfigEntry, freezer, seconds: float) -> None:
    """Time passes, and the coordinator takes one look at every source."""
    freezer.tick(seconds)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()


async def test_a_source_that_repeats_unchanged_values_earns_its_limit(
    hass: HomeAssistant, freezer
) -> None:
    """A flow the source writes again unchanged every minute earns five times that, raised to
    the 10-minute floor; a flame that only changes earns nothing — availability only."""
    boiler = FakeBoiler(hass, SIGNALS)
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
    entry = await set_up(hass, boiler_options(boiler))
    coordinator = entry.runtime_data
    assert coordinator.max_age(Signal.FLOW) is None
    for flame in (True, False, True):
        boiler.set_many({Signal.FLAME: flame, Signal.FLOW: 40.0})  # the same flow again
        await look(hass, entry, freezer, 60)
    assert coordinator.max_age(Signal.FLOW) == 600.0
    assert coordinator.max_age(Signal.FLAME) is None
    assert coordinator.freshness_limits() == {Signal.FLAME: None, Signal.FLOW: 600.0}


@pytest.mark.parametrize(("stored", "expected"), [(0, None), (300, 300.0)])
async def test_the_users_limit_wins_and_zero_is_none(
    hass: HomeAssistant, freezer, stored: int, expected: float | None
) -> None:
    """A limit the user set is used as set; 0 is "no limit", whatever the source has shown."""
    boiler = FakeBoiler(hass, SIGNALS)
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
    options = boiler_options(boiler, freshness={"flow": stored, "weather": stored})
    entry = await set_up(hass, options | {"weather": "weather.home"})
    for _ in range(3):
        boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
        await look(hass, entry, freezer, 60)
    assert entry.runtime_data.max_age(Signal.FLOW) == expected
    assert entry.runtime_data.weather_max_age() == expected


async def test_the_weather_earns_its_own_longer_limit(hass: HomeAssistant, freezer) -> None:
    """A weather entity written again unchanged earns at least three hours — never the boiler's
    ten minutes."""
    boiler = FakeBoiler(hass, SIGNALS)
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
    hass.states.async_set("weather.home", "cloudy", {"temperature": 5.0})
    entry = await set_up(hass, boiler_options(boiler, weather="weather.home"))
    assert entry.runtime_data.weather_max_age() is None
    for _ in range(3):
        hass.states.async_set("weather.home", "cloudy", {"temperature": 5.0})
        await look(hass, entry, freezer, 600)
    assert entry.runtime_data.weather_max_age() == 3 * 3600.0


async def mqtt_flame(hass: HomeAssistant, topic: str, unique_id: str) -> str:
    """A flame entity made by Home Assistant's MQTT discovery, as the interface's would be."""
    config = {"name": "Flame", "state_topic": topic, "unique_id": unique_id}
    async_fire_mqtt_message(
        hass, f"homeassistant/binary_sensor/{unique_id}/config", json.dumps(config)
    )
    await hass.async_block_till_done()
    entity = er.async_get(hass).async_get_entity_id("binary_sensor", "mqtt", unique_id)
    assert entity is not None
    return entity


@pytest.mark.usefixtures("mock_hass_config")
@pytest.mark.parametrize(
    ("boiler", "topic"),
    [
        (
            {"connection": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"},
            "OTGW/value/otgw-1/flame",
        ),
        ({"connection": "ems_esp", "ems_esp_base": "ems-esp"}, "ems-esp/boiler_data"),
    ],
)
async def test_the_interfaces_own_mqtt_repeats_count_as_reports(
    hass: HomeAssistant,
    freezer,
    mqtt_mock_entry: Callable[[], Any],
    boiler: dict[str, Any],
    topic: str,
) -> None:
    """Home Assistant writes an MQTT entity only when its value changes; the plugin hears the
    interface repeat it on its own topic — the OTGW firmware's per signal, EMS-ESP's boiler
    data — and takes that as the signal's report: unchanged repeats earn the limit. A signal of
    another integration on the same entry is not this device's."""
    await mqtt_mock_entry()
    flame = await mqtt_flame(hass, "OTGW/value/otgw-1/flame", "flame-1")
    async_fire_mqtt_message(hass, "OTGW/value/otgw-1/flame", "OFF")
    hass.states.async_set("sensor.boiler_flow", "40.0", {"unit_of_measurement": "°C"})
    options = {
        "signals": {"flame": flame, "flow": "sensor.boiler_flow"},
        "boiler": boiler | {"control_mode": "monitor", "heat_source": "gas", "type": "single"},
    }
    entry = await set_up(hass, options)
    coordinator = entry.runtime_data
    before = coordinator.transport.reading(Signal.FLAME).reported_at
    for _ in range(3):
        freezer.tick(60)
        async_fire_mqtt_message(hass, topic, "OFF" if "flame" in topic else '{"burngas":"off"}')
        await hass.async_block_till_done()
        await coordinator.async_refresh()
    heard = coordinator.reports.heard
    assert set(heard) == {Signal.FLAME}  # the flow is no MQTT entity
    assert coordinator.transport.reading(Signal.FLAME).reported_at == heard[Signal.FLAME]
    assert heard[Signal.FLAME] > before
    assert coordinator.max_age(Signal.FLAME) == 600.0
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    heard_then = dict(heard)
    async_fire_mqtt_message(hass, topic, "OFF")
    await hass.async_block_till_done()
    assert heard == heard_then  # no longer listening


async def test_without_mqtt_nothing_is_heard(hass: HomeAssistant) -> None:
    """MQTT not set up: the report times stay Home Assistant's own — availability only."""
    boiler = FakeBoiler(hass, SIGNALS)
    registry = er.async_get(hass)
    for signal in SIGNALS:  # registered as MQTT's before their states exist
        registry.async_get_or_create(
            boiler.entity(signal).split(".")[0],
            "mqtt",
            f"uid-{signal.value}",
            suggested_object_id=boiler.entity(signal).split(".")[1],
        )
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
    panel = {"connection": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw-1"}
    options = boiler_options(boiler, boiler=panel | {"control_mode": "monitor"})
    entry = await set_up(hass, options)
    assert entry.runtime_data.reports.heard == {}
    assert entry.runtime_data._report_topics()  # topics there, but nothing to listen with


def esphome_flow(hass: HomeAssistant) -> str:
    entity = (
        er.async_get(hass)
        .async_get_or_create(
            "sensor", "esphome", "esp-t-boiler", suggested_object_id="esp_t_boiler"
        )
        .entity_id
    )
    hass.states.async_set(entity, "40.0", {"unit_of_measurement": "°C"})
    return entity


@pytest.mark.parametrize("repeats", [False, True])
async def test_esphome_sensors_that_never_repeat_are_named(
    hass: HomeAssistant, freezer, repeats: bool
) -> None:
    """On ESPHome, a numeric sensor that reported but never repeated an unchanged value in the
    run's first six hours is named in a warning (its force_update is likely off); one that
    repeats is not. Nothing is said before six hours."""
    flow = esphome_flow(hass)
    hass.states.async_set("binary_sensor.esp_flame", "off")
    options = {
        "signals": {"flame": "binary_sensor.esp_flame", "flow": flow},
        "boiler": {"connection": "esphome", "control_mode": "monitor", "heat_source": "gas"},
    }
    entry = await set_up(hass, options)
    coordinator = entry.runtime_data
    issue_id = f"esphome_no_repeats_{entry.entry_id}"
    for _ in range(3):
        hass.states.async_set(flow, "40.0" if repeats else "41.0", {"unit_of_measurement": "°C"})
        if not repeats:
            hass.states.async_set(flow, "40.0", {"unit_of_measurement": "°C"})
        await look(hass, entry, freezer, 60)
    now = coordinator._started_at
    coordinator._check_repeats(now + 3600.0)
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None  # too early
    coordinator._check_repeats(now + 6 * 3600.0 + 1)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert (issue is not None) is not repeats
    if issue is not None:
        assert flow in issue.translation_placeholders["entity"]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None  # gone with the entry


async def test_another_connection_is_never_named(hass: HomeAssistant, freezer) -> None:
    """The warning is ESPHome's only."""
    flow = esphome_flow(hass)
    options = {"signals": {"flow": flow}, "boiler": {"connection": "other_entity"}}
    entry = await set_up(hass, options)
    coordinator = entry.runtime_data
    coordinator._check_repeats(coordinator._started_at + 7 * 3600.0)
    issue_id = f"esphome_no_repeats_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
