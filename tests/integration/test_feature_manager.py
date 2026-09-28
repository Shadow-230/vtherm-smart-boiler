"""The VT feature manager: registered only once VT's API exists, values on VT's thermostats,
never an exception into VT, unregistered with the last installation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed
from vtherm_api.vtherm_api import VThermAPI

from custom_components.vtherm_smart_boiler import feature_manager, vtherm_link
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
    assert set(attributes["smart_boiler"]) == {"heat_available", "emitter_power_factor"}
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
    assert manager.heat_available is attributes["smart_boiler"]["heat_available"]  # P92
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


async def test_a_new_vt_api_gets_the_factory_before_its_thermostat_starts(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """VT drops its API with its last entry (VT 10.4.0 ``remove_entry``); set up again, it
    builds a thermostat, which writes its first state, and only then starts it and asks for
    feature managers. The factory is registered with the new API at that first state — the
    plugin's next update would come after the start, and the thermostat would never ask again
    until the next reload, which would drop the API once more."""
    api = vt_is_set_up(hass)
    await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    VThermAPI.reset_vtherm_api()
    new = VThermAPI.get_vtherm_api(hass)
    assert new.list_feature_managers() == []
    hass.states.async_set("climate.rebuilt_thermostat", "heat")  # its first state
    assert new.list_feature_managers() == [DOMAIN]  # at once, with no update in between


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
    values = {"heat_available": True, "emitter_power_factor": 0.5}
    zones.set("living", hvac_action="heating", valve_open_percent=60, smart_boiler=values)
    await entry.runtime_data.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    assert living


# --- X7: errors never reach VT (T-53), the reload repair (P-59), an old VT (P-60), the public
# name (P-61), a real change only (P-63) --------------------------------------------------------


class BrokenApi:
    """VT's API as a broken or odd VT might leave it: registering fails (``fail`` "register"),
    or asking whether it can register does (``fail`` "hasattr"); unregistering always fails."""

    def __init__(self, fail: str) -> None:
        self.fail = fail
        self.registered: list[Any] = []

    def __getattr__(self, name: str) -> Any:
        if self.fail == "hasattr" and name == "register_feature_manager":
            raise ValueError("an API that cannot even say")
        raise AttributeError(name)

    def register(self, factory: Any) -> None:
        if self.fail == "register":
            raise RuntimeError("boom")
        self.registered.append(factory)

    def unregister_feature_manager(self, name: str) -> None:
        raise RuntimeError("boom")


def broken_vt(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, fail: str) -> BrokenApi:
    api = BrokenApi(fail)
    if fail != "hasattr":
        api.register_feature_manager = api.register  # type: ignore[attr-defined]
    hass.config.components.add(VT_DOMAIN)
    hass.data[VT_DOMAIN] = {"vtherm_api": api}

    def get_vtherm_api(_hass: Any = None) -> Any:
        if fail == "get":
            raise RuntimeError("boom")
        return api

    monkeypatch.setattr(VThermAPI, "get_vtherm_api", staticmethod(get_vtherm_api))
    return api


@pytest.mark.parametrize(
    ("fail", "expected"),
    [
        ("get", feature_manager.RegistrationState.WAITING),
        ("register", feature_manager.RegistrationState.UNSUPPORTED),
        ("hasattr", feature_manager.RegistrationState.UNSUPPORTED),
        ("unregister", feature_manager.RegistrationState.REGISTERED),
    ],
)
async def test_registration_errors_never_reach_vt(
    hass: HomeAssistant,
    zones: FakeZones,
    monkeypatch: pytest.MonkeyPatch,
    fail: str,
    expected: feature_manager.RegistrationState,
) -> None:
    """T-53: an API whose ``get_vtherm_api``, ``register_feature_manager`` or
    ``unregister_feature_manager`` raises — or that cannot even say whether it registers —
    never passes an error on: attached, checked at each update and detached without one, the
    state waiting or unsupported, and the unload clean."""
    from homeassistant.config_entries import ConfigEntryState

    api = broken_vt(hass, monkeypatch, fail)
    entry = await setup(hass, zones)
    registration = feature_manager.registration(hass)
    assert registration is not None
    assert registration.state is expected
    await entry.runtime_data.async_refresh()  # the check at each update
    assert entry.runtime_data.last_update_success
    assert registration.state is expected
    assert len(api.registered) == (1 if fail == "unregister" else 0)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert feature_manager.registration(hass) is None
    assert ir.async_get(hass).async_get_issue(DOMAIN, "vt_feature_manager_unsupported") is None
    hass.data.pop(VT_DOMAIN)  # the stand-in API cannot be reset


async def test_the_reload_repair_skips_zones_that_are_away_or_not_ready(
    hass: HomeAssistant, zones: FakeZones, freezer
) -> None:
    """P-59: only a thermostat VT shows running — reported, ready, its mode known — and still
    without the values some time after the registration needs VT's reload; one unavailable,
    not ready, of unknown mode or away is not listed. Negative: none of them known, no
    issue."""
    vt_is_set_up(hass)
    zones.add("living", hvac_action="heating")
    zones.add("away")
    zones.add("unavailable", state="unavailable")
    zones.add("starting", state="off", is_ready=False)
    zones.add("placeholder", state="off", is_ready=None, specific_states=None)
    entry = await setup(hass, zones)
    hass.states.async_remove(zones.entities["away"])
    issue_id = f"vt_reload_needed_{entry.entry_id}"
    freezer.tick(20 * 60)
    zones.set("living", hvac_action="heating")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_placeholders == {"zones": "fake living"}  # the one running
    zones.set("living", state="unavailable")
    await entry.runtime_data.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None


@pytest.mark.parametrize(
    ("version", "method", "expected"),
    [
        ("10.1.0", True, feature_manager.RegistrationState.UNSUPPORTED),
        ("10.0.2", True, feature_manager.RegistrationState.UNSUPPORTED),
        ("10.2.0", True, feature_manager.RegistrationState.REGISTERED),
        ("10.4.0", True, feature_manager.RegistrationState.REGISTERED),
        (None, True, feature_manager.RegistrationState.REGISTERED),  # detection as before
        (None, False, feature_manager.RegistrationState.UNSUPPORTED),
        ("not a version", True, feature_manager.RegistrationState.REGISTERED),
    ],
)
async def test_an_old_vt_is_detected_by_its_version(
    hass: HomeAssistant,
    zones: FakeZones,
    monkeypatch: pytest.MonkeyPatch,
    version: str | None,
    method: bool,
    expected: feature_manager.RegistrationState,
) -> None:
    """P-60 (Q3.1): VT 10.0 and 10.1 take the registration — the shared ``vtherm_api`` has the
    method — and never create the manager: their version tells, and the issue names the first
    VT that does, 10.2.0 (provisional, K4). Negative: the version unknown or unreadable, the
    capability decides as before."""
    monkeypatch.setattr(vtherm_link, "vt_version", lambda _hass: version)
    if method:
        api = vt_is_set_up(hass)
    else:
        hass.config.components.add(VT_DOMAIN)
        hass.data[VT_DOMAIN] = {"vtherm_api": object()}
    await setup(hass, zones)
    registration = feature_manager.registration(hass)
    assert registration is not None
    assert registration.state is expected
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "vt_feature_manager_unsupported")
    if expected is feature_manager.RegistrationState.UNSUPPORTED:
        assert issue is not None
        assert issue.translation_placeholders == {"version": "10.2.0"}
    else:
        assert issue is None
    if method:
        unsupported = expected is feature_manager.RegistrationState.UNSUPPORTED
        assert api.list_feature_managers() == ([] if unsupported else [DOMAIN])
    else:
        hass.data.pop(VT_DOMAIN)


async def test_the_zone_value_is_named_heat_available(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P-61: what VT's thermostats and other plugins see is "heat available" — heat reaches
    the zone — not "hot water", which the boiler's domestic hot water is."""
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    attributes: dict = {}
    manager.add_custom_attributes(attributes)
    assert set(attributes["smart_boiler"]) == {"heat_available", "emitter_power_factor"}
    assert manager.heat_available is attributes["smart_boiler"]["heat_available"]
    assert not hasattr(manager, "hot_water")


def test_the_attribute_changes_only_on_a_real_change(hass: HomeAssistant) -> None:
    """P-63: VT records its thermostats' attributes, so the plugin's are replaced only when
    heat availability changes, the factor comes or goes, or it moves by 0.05 or more from what
    was published (provisional, K4) — not at every small step of the factor. Negative: values
    that go away take the attribute with them; back, they are published afresh."""
    values: dict[str, Any] | None = {"heat_available": True, "emitter_power_factor": 0.812}
    manager = feature_manager.SmartBoilerFeatureManager(
        hass, Thermostat("climate.a"), lambda _entity: None if values is None else dict(values)
    )

    def shown() -> dict[str, Any] | None:
        attributes: dict[str, Any] = {"other": 1}
        manager.add_custom_attributes(attributes)
        assert attributes.pop("other") == 1
        return attributes.get("smart_boiler")

    assert shown() == {"heat_available": True, "emitter_power_factor": 0.812}
    values = {"heat_available": True, "emitter_power_factor": 0.826}
    assert shown() == {"heat_available": True, "emitter_power_factor": 0.812}  # nothing new
    values = {"heat_available": True, "emitter_power_factor": 0.861}
    assert shown() == {"heat_available": True, "emitter_power_factor": 0.812}  # 0.049: nothing
    values = {"heat_available": True, "emitter_power_factor": 0.87}
    assert shown() == {"heat_available": True, "emitter_power_factor": 0.87}  # 0.058: published
    values = {"heat_available": True, "emitter_power_factor": 0.83}
    assert shown() == {"heat_available": True, "emitter_power_factor": 0.87}  # from 0.87 now
    values = {"heat_available": False, "emitter_power_factor": 0.915}
    assert shown() == {"heat_available": False, "emitter_power_factor": 0.915}  # a flip
    values = {"heat_available": None, "emitter_power_factor": 0.915}
    assert shown() == {"heat_available": None, "emitter_power_factor": 0.915}  # unknown now
    values = {"heat_available": None, "emitter_power_factor": None}
    assert shown() == {"heat_available": None, "emitter_power_factor": None}  # the factor gone
    values = {"heat_available": None, "emitter_power_factor": 0.5}
    assert shown() == {"heat_available": None, "emitter_power_factor": 0.5}  # back
    values = None
    assert shown() is None  # not the plugin's zone any more: no attribute
    values = {"heat_available": None, "emitter_power_factor": 0.51}
    assert shown() == {"heat_available": None, "emitter_power_factor": 0.51}  # afresh
