"""The VT feature manager: registered only once VT's API exists, values on VT's thermostats,
never an exception into VT, unregistered with the last installation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry
from vtherm_api.vtherm_api import VThermAPI

from custom_components.vtherm_smart_boiler import feature_manager
from custom_components.vtherm_smart_boiler.const import DOMAIN, VT_DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@dataclass
class Thermostat:
    entity_id: str | None


@pytest.fixture(autouse=True)
def fresh_api():
    yield
    VThermAPI.reset_vtherm_api()


def vt_is_set_up(hass: HomeAssistant) -> VThermAPI:
    """What VT does at setup: it is a loaded component and has created its API."""
    hass.config.components.add(VT_DOMAIN)
    return VThermAPI.get_vtherm_api(hass)


async def setup(hass: HomeAssistant, zones: FakeZones, title: str = "Boiler") -> MockConfigEntry:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        data={},
        options={
            "signals": boiler.mapping(),
            "zones": [{"entity_id": e} for e in zones.entities.values()],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_values_appear_on_the_thermostat_and_go_with_the_plugin(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    factory = api.get_feature_manager(DOMAIN)
    thermostat = Thermostat(living)
    assert factory.supports(thermostat)
    manager = factory.create(thermostat)
    manager.post_init({})
    await manager.start_listening()
    assert await manager.refresh_state() is False
    attributes: dict = {}
    manager.add_custom_attributes(attributes)
    assert set(attributes["smart_boiler"]) == {"hot_water", "emitter_power_factor"}
    other: dict = {}
    factory.create(Thermostat("climate.not_ours")).add_custom_attributes(other)
    assert other == {}

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert api.list_feature_managers() == []
    manager.add_custom_attributes(attributes)  # still attached in VT: publishes nothing
    assert "smart_boiler" not in attributes


async def test_no_bare_api_is_created_without_vt(hass: HomeAssistant, zones: FakeZones) -> None:
    await setup(hass, zones)
    assert hass.data.get(VT_DOMAIN) is None


async def test_registers_once_vt_is_loaded_later(hass: HomeAssistant, zones: FakeZones) -> None:
    await setup(hass, zones)
    api = vt_is_set_up(hass)
    assert api.list_feature_managers() == []
    hass.bus.async_fire(EVENT_COMPONENT_LOADED, {"component": VT_DOMAIN})
    await hass.async_block_till_done()
    assert api.list_feature_managers() == [DOMAIN]


async def test_two_installations_share_one_registration(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    api = vt_is_set_up(hass)
    first = await setup(hass, zones, "First")
    second = await setup(hass, zones, "Second")
    assert api.list_feature_managers() == [DOMAIN]
    assert await hass.config_entries.async_unload(first.entry_id)
    assert api.list_feature_managers() == [DOMAIN]
    assert await hass.config_entries.async_unload(second.entry_id)
    assert api.list_feature_managers() == []


def test_the_manager_never_raises_into_vt(hass: HomeAssistant) -> None:
    def broken(entity_id: str) -> dict:
        raise RuntimeError("boom")

    manager = feature_manager.SmartBoilerFeatureManager(hass, Thermostat("climate.a"), broken)
    attributes: dict = {"other": 1}
    manager.add_custom_attributes(attributes)
    assert attributes == {"other": 1}
    half_built = feature_manager.SmartBoilerFeatureManager(
        hass, Thermostat(None), lambda entity_id: {"x": 1}
    )
    half_built.add_custom_attributes(attributes)
    assert attributes == {"other": 1}
    assert manager.name == DOMAIN
    assert manager.is_configured
    assert not manager.is_detected
