"""VT link: zones from VT climate entities, the central mode and capability detection."""

from __future__ import annotations

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.vtherm_smart_boiler.vtherm_attributes import CentralMode
from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink, vt_climate_entities

from .harness import VT_PLATFORM, FakeZones


async def test_zones_from_vt_climate_entities(hass: HomeAssistant, zones: FakeZones) -> None:
    living = zones.add(
        "living",
        current_temperature=19.5,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=80,
        on_percent=0.8,
    )
    bedroom = zones.add("bedroom", state="off")
    link = VThermLink(hass, [living, bedroom, "climate.missing"])
    states = {z.zone_id: z for z in link.zones()}
    assert states[living].deficit == pytest.approx(1.5)
    assert states[living].valve_open == pytest.approx(0.8)
    assert states[living].calling is True
    assert states[living].reported_at is not None
    assert states[bedroom].heating_enabled is False
    assert states["climate.missing"].temperature is None
    assert states["climate.missing"].reported_at is None
    assert vt_climate_entities(hass) == sorted([living, bedroom])


async def test_zone_temperatures_follow_the_unit_system(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    hass.config.units = US_CUSTOMARY_SYSTEM
    living = zones.add("living", current_temperature=68.0, temperature=69.8)
    zone = VThermLink(hass, [living]).zone(living)
    assert zone.temperature == pytest.approx(20.0)
    assert zone.target == pytest.approx(21.0)


async def test_central_mode(hass: HomeAssistant) -> None:
    link = VThermLink(hass, [])
    assert link.central_mode() is None
    entry = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(entry.entity_id, "Stopped")
    assert link.central_mode() is CentralMode.STOPPED
    hass.states.async_set(entry.entity_id, "unavailable")
    assert link.central_mode() is None


async def test_capabilities_without_vt(hass: HomeAssistant) -> None:
    capabilities = VThermLink(hass, []).capabilities()
    assert capabilities.vt_loaded is False
    assert capabilities.vt_version is None
    assert capabilities.vtherm_api_version == "0.5.0"
    assert capabilities.smartpi_loaded is False


async def test_zone_algorithm_from_live_attributes(hass: HomeAssistant, zones: FakeZones) -> None:
    smartpi = zones.add(
        "smartpi",
        configuration={"proportional_function": "smartpi", "is_used_by_central_boiler": False},
        specific_states={"smartpi_learning_enabled": True},
    )
    tpi = zones.add(
        "tpi",
        configuration={"proportional_function": "tpi", "is_used_by_central_boiler": True},
        specific_states={"auto_tpi_state": "on", "auto_tpi_continuous_kext": "off"},
    )
    # VT publishes the Auto-TPI keys for every TPI zone; "off" means no Auto-TPI learning.
    plain = zones.add(
        "plain",
        configuration={"proportional_function": "tpi", "is_used_by_central_boiler": True},
        specific_states={"auto_tpi_state": "off", "auto_tpi_continuous_kext": "off"},
    )
    kext = zones.add(
        "kext",
        configuration={"proportional_function": "tpi"},
        specific_states={"auto_tpi_state": "off", "auto_tpi_continuous_kext": "on"},
    )
    link = VThermLink(hass, [smartpi, tpi, plain, kext])
    assert link.zone_algorithm(smartpi).smartpi_learning is True
    assert link.zone_algorithm(smartpi).proportional_function == "smartpi"
    assert not link.zone_algorithm(smartpi).auto_tpi
    algo = link.zone_algorithm(tpi)
    assert algo.auto_tpi
    assert algo.used_by_central_boiler is True
    assert algo.smartpi_learning is None
    assert not link.zone_algorithm(plain).auto_tpi
    assert link.zone_algorithm(kext).auto_tpi
    assert link.zone_algorithm("climate.missing").proportional_function is None


async def test_vt_central_boiler_detection(hass: HomeAssistant) -> None:
    link = VThermLink(hass, [])
    assert not link.vt_central_boiler_configured()
    entry = er.async_get(hass).async_get_or_create(
        "binary_sensor", VT_PLATFORM, "central_boiler_state"
    )
    hass.states.async_set(entry.entity_id, "off", {"is_central_boiler_configured": False})
    assert not link.vt_central_boiler_configured()
    hass.states.async_set(entry.entity_id, "on", {"is_central_boiler_configured": True})
    assert link.vt_central_boiler_configured()
    # VT's own central boiler cannot be ruled out while its entity is away (a reload of VT's
    # central entry, a late start): unknown, which keeps control waiting — never "not there".
    for state in ("unavailable", "unknown"):
        hass.states.async_set(entry.entity_id, state)
        assert link.vt_central_boiler_configured() is None
    hass.states.async_remove(entry.entity_id)
    assert link.vt_central_boiler_configured() is None


async def test_vt_is_loaded_only_with_a_loaded_entry(hass: HomeAssistant) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.config.components.add("versatile_thermostat")
    entry = MockConfigEntry(domain="versatile_thermostat", state=ConfigEntryState.SETUP_ERROR)
    entry.add_to_hass(hass)
    assert not VThermLink(hass, []).capabilities().vt_loaded  # set up, but its entries failed
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert VThermLink(hass, []).capabilities().vt_loaded
