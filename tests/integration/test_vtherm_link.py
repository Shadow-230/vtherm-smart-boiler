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
