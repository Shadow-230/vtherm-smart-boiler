"""The VT feature manager: registered only once VT's API exists, values on VT's thermostats,
never an exception into VT, unregistered with the last installation."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
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


async def test_values_come_back_after_the_plugin_reloads(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P32: VT keeps the managers it created; they reach the plugin's data through a stable
    access point, so a reload of the plugin (an options change) does not blank them until VT
    reloads too."""
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    attributes: dict = {}
    manager.add_custom_attributes(attributes)
    assert "smart_boiler" in attributes
    assert manager.hot_water is attributes["smart_boiler"]["hot_water"]  # P92: as properties
    assert manager.emitter_power_factor == attributes["smart_boiler"]["emitter_power_factor"]


async def test_registered_again_after_vt_recreates_its_api(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P32: VT drops its API with its last entry and creates a new one — with an empty
    registry — when it is set up again."""
    api = vt_is_set_up(hass)
    entry = await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    VThermAPI.reset_vtherm_api()
    new = VThermAPI.get_vtherm_api(hass)
    assert new is not api
    await entry.runtime_data.async_refresh()
    assert new.list_feature_managers() == [DOMAIN]


async def test_a_vt_without_feature_managers_is_reported(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P107: the state is visible when the manager cannot work."""
    hass.config.components.add(VT_DOMAIN)
    hass.data[VT_DOMAIN] = {"vtherm_api": object()}  # an API without feature managers
    await setup(hass, zones)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "vt_feature_manager_unsupported")
    assert issue is not None
    hass.data.pop(VT_DOMAIN)  # the stand-in API cannot be reset


async def test_thermostats_started_before_the_registration_are_reported(
    hass: HomeAssistant, zones: FakeZones, freezer
) -> None:
    """P107: a thermostat already running picks the manager up only at VT's next reload."""
    vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    issue_id = f"vt_reload_needed_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None  # give VT time
    freezer.tick(20 * 60)
    zones.set("living", hvac_action="heating", valve_open_percent=60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    values = {"hot_water": True, "emitter_power_factor": 0.5}
    zones.set("living", hvac_action="heating", valve_open_percent=60, smart_boiler=values)
    await entry.runtime_data.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert living
