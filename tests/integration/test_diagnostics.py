"""Diagnostics download: complete enough to help, and without entity IDs."""

from __future__ import annotations

import json

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.diagnostics import async_get_config_entry_diagnostics

from .harness import WEATHER_ENTITY, FakeBoiler, FakeForecasts, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_diagnostics_are_redacted(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.PRESSURE))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0, Signal.PRESSURE: 1.5})
    living = zones.add("living", hvac_action="heating", valve_open_percent=40)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping(),
            "weather": WEATHER_ENTITY,
            "zones": [{"entity_id": living}],
            "parameters": {"boiler_min_power": 4.0},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)  # the first analysis
    await entry.runtime_data.async_run_analysis()
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    for entity in (*boiler.mapping().values(), living, WEATHER_ENTITY):
        assert entity not in text
    assert result["options"]["signals"]["flame"].startswith("entity_")
    assert result["signals"]["flow"]["status"] == "ok"
    assert result["parameters"]["boiler_min_power"]["effective"] == 4.0
    assert result["capabilities"]["vtherm_api_version"] == "0.5.0"
    assert result["analysis"]["verdict"] == "not_enough_data"
    assert len(result["zones"]) == 1
    assert result["forecasts"]["snapshots"] >= 1


async def test_the_control_section_keeps_what_is_not_personal(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P69: service names and versions are not personal and stay readable; entity IDs and the
    gateway's identifiers do not."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=40)
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping(),
            "boiler": {"class": "flow_setpoint", "dhw": "combi"},
            "zones": [{"entity_id": living}],
            "monitor": {"monitoring_days": 0},
            "control": {
                "write_path": "opentherm_gw",
                "gateway_id": "gw-in-the-cellar",
                "confirmed_entity": "sensor.gw_control_setpoint",
                "topology": "gateway_with_thermostat",
                "curve": {"design_outdoor": -15, "design_flow": 55},
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    control = result["control"]
    assert control["enabled"] is False
    assert "opentherm_gw.set_control_setpoint" in control["allowed_services"]
    assert control["status"]["configured"] is True
    assert "controlling" in control["stored"]
    assert "gw-in-the-cellar" not in text
    assert "sensor.gw_control_setpoint" not in text
    assert living not in text
