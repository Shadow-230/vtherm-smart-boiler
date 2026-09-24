"""The integration-test harness itself: fakes and replay behave as Home Assistant states."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.units import signal_value
from custom_components.vtherm_smart_boiler.vtherm_attributes import zone_values
from sim.profiles import BOILERS, HOUSES, radiator_zones
from sim.simulator import Scenario, daily_cycle, simulate

from .harness import (
    VT_PLATFORM,
    WEATHER_ENTITY,
    FakeBoiler,
    FakeForecasts,
    FakeZones,
    apply_event,
    replay_events,
)


async def test_fake_boiler_states_carry_units(hass: HomeAssistant, boiler: FakeBoiler) -> None:
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 47.5, Signal.PRESSURE: None})
    flame = hass.states.get(boiler.entity(Signal.FLAME))
    flow = hass.states.get(boiler.entity(Signal.FLOW))
    assert flame is not None
    assert flame.state == "on"
    assert flow is not None
    assert signal_value(Signal.FLOW, flow.state, flow.attributes["unit_of_measurement"]) == 47.5
    pressure = hass.states.get(boiler.entity(Signal.PRESSURE))
    assert pressure is not None
    assert pressure.state == "unavailable"
    assert boiler.mapping()["flame"] == "binary_sensor.fake_boiler_flame"


async def test_fake_zones_are_registered_as_vt(hass: HomeAssistant, zones: FakeZones) -> None:
    entity_id = zones.add("living", hvac_action="heating", valve_open_percent=40)
    entry = er.async_get(hass).async_get(entity_id)
    assert entry is not None
    assert entry.platform == VT_PLATFORM
    state = hass.states.get(entity_id)
    assert state is not None
    values = zone_values(state.state, state.attributes)
    assert values.calling is True
    assert values.valve_open == pytest.approx(0.4)


async def test_fake_forecasts_answer_and_record(
    hass: HomeAssistant, forecasts: FakeForecasts
) -> None:
    response = await hass.services.async_call(
        "weather",
        "get_forecasts",
        {"entity_id": WEATHER_ENTITY, "type": "hourly"},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert len(response[WEATHER_ENTITY]["forecast"]) == 48
    assert forecasts.calls == [{"entity_id": WEATHER_ENTITY, "type": "hourly"}]


async def test_replay_of_a_simulated_hour(hass: HomeAssistant, freezer, boiler: FakeBoiler) -> None:
    start = datetime(2026, 1, 10, tzinfo=UTC).timestamp()
    scenario = Scenario(
        BOILERS["condensing_large"],
        HOUSES["average"],
        radiator_zones(),
        daily_cycle([5.0]),
        days=1 / 24,
        start=start,
    )
    history = simulate(scenario).history
    zones = FakeZones(hass)
    for zone_id in history.zones:
        zones.add(zone_id)
    last = start
    for t, changes in replay_events(history, zones):
        freezer.move_to(datetime.fromtimestamp(t, UTC))
        apply_event(boiler, zones, changes)
        async_fire_time_changed(hass)
        last = t
    await hass.async_block_till_done()
    flow = hass.states.get(boiler.entity(Signal.FLOW))
    assert flow is not None
    assert float(flow.state) == history.signal(Signal.FLOW).value_at(last)
    zone_state = hass.states.get(zones.entities["zone_living"])
    assert zone_state is not None
    expected = history.zones["zone_living"].temperature.value_at(last)
    assert zone_state.attributes["current_temperature"] == expected
