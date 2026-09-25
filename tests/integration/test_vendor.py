"""The vendored VT and SmartPI integrations load in the in-process Home Assistant."""

from __future__ import annotations

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from vtherm_api.vtherm_api import VThermAPI

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .conftest import requires_vendor
from .harness import FakeBoiler

pytestmark = [requires_vendor, pytest.mark.usefixtures("enable_custom_integrations")]


@pytest.mark.parametrize(
    ("domain", "version"),
    [("versatile_thermostat", "10.4.0"), ("vtherm_smartpi", "0.0.0")],
)
async def test_vendored_integration_loads(hass: HomeAssistant, domain: str, version: str) -> None:
    integration = await async_get_integration(hass, domain)
    assert str(integration.version) == version
    assert await integration.async_get_component() is not None


LIVING = "climate.living"


def vt_thermostat() -> MockConfigEntry:
    """A VT over_switch thermostat in the entry format of VT 10.4.0."""
    from custom_components.versatile_thermostat import const as vt

    return MockConfigEntry(
        domain=vt.DOMAIN,
        title="Living",
        unique_id="living",
        data={
            vt.CONF_THERMOSTAT_TYPE: vt.CONF_THERMOSTAT_SWITCH,
            vt.CONF_NAME: "Living",
            vt.CONF_TEMP_SENSOR: "sensor.living_temperature",
            vt.CONF_EXTERNAL_TEMP_SENSOR: "sensor.outdoor_temperature",
            vt.CONF_CYCLE_MIN: 5,
            vt.CONF_TEMP_MIN: 7.0,
            vt.CONF_TEMP_MAX: 30.0,
            vt.CONF_STEP_TEMPERATURE: 0.1,
            vt.CONF_UNDERLYING_LIST: ["input_boolean.living_valve"],
            vt.CONF_HEATER_KEEP_ALIVE: 0,
            vt.CONF_PROP_FUNCTION: vt.PROPORTIONAL_FUNCTION_TPI,
            vt.CONF_AC_MODE: False,
            vt.CONF_INVERSE_SWITCH: False,
            vt.CONF_TPI_COEF_INT: 0.3,
            vt.CONF_TPI_COEF_EXT: 0.01,
            vt.CONF_MINIMAL_ACTIVATION_DELAY: 10,
            vt.CONF_MINIMAL_DEACTIVATION_DELAY: 0,
            vt.CONF_TPI_THRESHOLD_LOW: 0.0,
            vt.CONF_TPI_THRESHOLD_HIGH: 0.0,
            vt.CONF_AUTO_TPI_MODE: False,
            vt.CONF_SAFETY_DELAY_MIN: 5,
            vt.CONF_SAFETY_MIN_ON_PERCENT: 0.4,
            vt.CONF_SAFETY_DEFAULT_ON_PERCENT: 0.3,
        },
    )


async def room_and_boiler(hass: HomeAssistant) -> MockConfigEntry:
    """The thermostat's sensors and switch, and the plugin's entry for a boiler with that zone."""
    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hass.states.async_set("sensor.living_temperature", "19.0", celsius)
    hass.states.async_set("sensor.outdoor_temperature", "5.0", celsius)
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"living_valve": {}}}
    )
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    return MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": boiler.mapping(),
            "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0},
            "zones": [{"entity_id": LIVING}],
        },
    )


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def heat_to(hass: HomeAssistant, target: float) -> None:
    for service, data in (
        ("set_hvac_mode", {"hvac_mode": "heat"}),
        ("set_temperature", {"temperature": target}),
    ):
        await hass.services.async_call(
            "climate", service, {"entity_id": LIVING, **data}, blocking=True
        )
    await hass.async_block_till_done()


async def test_at_start_a_real_vt_thermostat_is_read_and_shows_the_plugins_values(
    hass: HomeAssistant,
) -> None:
    """P59: VT 10.4.0 itself, not a state standing in for it, through Home Assistant's start
    (VT starts its thermostats once Home Assistant has started): the plugin reads the room
    temperature, target, heating mode and duty cycle of an over_switch thermostat below its
    target, and the thermostat shows the plugin's values through the feature manager."""
    entry = await room_and_boiler(hass)
    hass.set_state(CoreState.starting)
    await setup(hass, entry)
    await setup(hass, vt_thermostat())
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)

    zone = entry.runtime_data.link.zone(LIVING)
    assert (zone.temperature, zone.target, zone.heating_enabled) == (19.0, 21.0, True)
    assert zone.on_percent == pytest.approx(0.76)  # TPI: 0.3 · 2 K + 0.01 · 16 K
    assert zone.calling is True
    assert DOMAIN in VThermAPI.get_vtherm_api(hass).list_feature_managers()
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)  # VT publishes its attributes again
    shown = hass.states.get(LIVING).attributes.get("smart_boiler")
    assert shown is not None
    assert set(shown) == {"hot_water", "emitter_power_factor"}


async def test_a_vt_thermostat_already_running_shows_the_values_after_vt_reloads(
    hass: HomeAssistant,
) -> None:
    """A thermostat that started before the plugin registered does not ask again: it picks the
    feature manager up at VT's next reload — what the plugin's repair issue asks for."""
    entry = await room_and_boiler(hass)
    thermostat = vt_thermostat()
    await setup(hass, thermostat)
    await setup(hass, entry)
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)
    assert "smart_boiler" not in hass.states.get(LIVING).attributes
    assert await hass.config_entries.async_reload(thermostat.entry_id)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)
    assert hass.states.get(LIVING).attributes.get("smart_boiler") is not None
