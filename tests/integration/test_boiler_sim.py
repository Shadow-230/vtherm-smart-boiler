"""The test-only simulator component: entities, the gateway-like and entity write paths, and
the scenario services the acceptance scenarios use."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
START = datetime(2026, 1, 12, 8, tzinfo=UTC)


async def setup_sim(hass: HomeAssistant, freezer, **conf) -> None:
    freezer.move_to(START)
    assert await async_setup_component(hass, "boiler_sim", {"boiler_sim": conf})
    await hass.async_block_till_done()


async def advance(hass: HomeAssistant, freezer, seconds: float) -> None:
    for _ in range(int(seconds // 10)):
        freezer.tick(10)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


def value(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def test_entities_follow_the_plant(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer, outdoor=0.0)
    for entity_id in (
        "binary_sensor.boiler_sim_flame",
        "sensor.boiler_sim_flow",
        "sensor.boiler_sim_ch_setpoint",
        "sensor.boiler_sim_zone_living_temperature",
        "switch.boiler_sim_zone_living_valve",
        "weather.boiler_sim_weather",
    ):
        assert value(hass, entity_id) not in ("unavailable", "unknown"), entity_id
    assert value(hass, "number.boiler_sim_flow_setpoint") == "unknown"  # nothing written yet
    assert float(value(hass, "sensor.boiler_sim_outdoor")) == 0.0
    await advance(hass, freezer, 1800)
    assert float(value(hass, "sensor.boiler_sim_zone_living_temperature")) > 15.0


async def test_the_gateway_path_lapses_unless_repeated(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer, outdoor=5.0)
    own = float(value(hass, "sensor.boiler_sim_ch_setpoint"))
    await hass.services.async_call(
        "opentherm_gw", "set_control_setpoint", {"gateway_id": "sim", "temperature": 52.0},
        blocking=True,
    )
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 52.0
    await advance(hass, freezer, 80)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == own  # lapsed
    await hass.services.async_call(
        "opentherm_gw", "set_control_setpoint", {"gateway_id": "sim", "temperature": 5.0},
        blocking=True,
    )
    await advance(hass, freezer, 600)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 5.0  # below 8 °C: holds


async def test_a_persistent_setpoint_holds_and_counts_writes(
    hass: HomeAssistant, freezer
) -> None:
    await setup_sim(hass, freezer, write_type="persistent")
    await hass.services.async_call(
        "number", "set_value", {"entity_id": "number.boiler_sim_flow_setpoint", "value": 48},
        blocking=True,
    )
    await advance(hass, freezer, 600)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 48.0
    assert value(hass, "sensor.boiler_sim_persistent_writes") == "1"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.boiler_sim_external_control"}, blocking=True
    )
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) != 48.0  # handed back


async def test_scenario_services(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer)
    await hass.services.async_call(
        "boiler_sim", "fail_signal", {"signal": "flow"}, blocking=True
    )
    assert value(hass, "sensor.boiler_sim_flow") == "unavailable"
    await hass.services.async_call(
        "boiler_sim", "fail_signal", {"signal": "flow", "failed": False}, blocking=True
    )
    assert value(hass, "sensor.boiler_sim_flow") != "unavailable"
    await hass.services.async_call("boiler_sim", "force_setpoint", {"value": 61}, blocking=True)
    await hass.services.async_call(
        "opentherm_gw", "set_control_setpoint", {"gateway_id": "sim", "temperature": 40.0},
        blocking=True,
    )
    await advance(hass, freezer, 20)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 61.0  # the other controller
    await hass.services.async_call("boiler_sim", "set_outdoor", {"temperature": -8}, blocking=True)
    assert float(value(hass, "sensor.boiler_sim_outdoor")) == -8.0
    await hass.services.async_call(
        "opentherm_gw", "set_hot_water_ovrd", {"gateway_id": "sim", "dhw_override": "0"},
        blocking=True,
    )
    assert value(hass, "binary_sensor.boiler_sim_dhw_enable") == "off"
    counters = hass.states.get("sensor.boiler_sim_persistent_writes").attributes
    assert counters["dhw_enable_writes"] == 1
