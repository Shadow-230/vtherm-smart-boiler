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


async def setup(hass: HomeAssistant, zones: FakeZones) -> MockConfigEntry:
    """The one entry of this single-entry integration (P-125, T11)."""
    assert hass.config_entries.async_entries(DOMAIN) == []
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
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
    assert attributes["smart_boiler"] == {"heat_available": True, "supply_temperature": 45}
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


async def test_the_one_installation_registers_once_and_its_unload_unregisters(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P-125, T11: the integration allows one entry, and a test sets up one. Its setup registers
    the factory; a reload gives it back to VT's API, registered once; its unload — the last
    installation's — unregisters it."""
    api = vt_is_set_up(hass)
    entry = await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert api.list_feature_managers() == [DOMAIN]
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
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
    assert not hasattr(manager, "emitter_power_factor")  # I8.2: the factor left the manager


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
        self.attempts = 0

    def __getattr__(self, name: str) -> Any:
        if self.fail == "hasattr" and name == "register_feature_manager":
            raise ValueError("an API that cannot even say")
        raise AttributeError(name)

    def register(self, factory: Any) -> None:
        self.attempts += 1
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
    # PB-50: an unload leaves the issue as it is; it goes with the entry.
    unsupported = expected is feature_manager.RegistrationState.UNSUPPORTED
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "vt_feature_manager_unsupported")
    assert (issue is not None) is unsupported
    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
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
    assert set(attributes["smart_boiler"]) == {"heat_available", "supply_temperature"}
    assert manager.heat_available is attributes["smart_boiler"]["heat_available"]
    assert not hasattr(manager, "hot_water")


@pytest.mark.parametrize(
    ("flame", "flow", "returned", "expected"),
    [
        ("on", "45", "38", True),
        ("on", "45", "44.5", False),  # the emitters take no heat: the return is as warm
        ("off", "60", "40", False),  # the flame out: no heat from the boiler
        ("unavailable", "45", "38", None),  # cannot be told
        ("on", "45", "unavailable", True),  # no return known: against the room
    ],
    ids=["burning", "flow_near_return", "flame_off", "flame_unknown", "return_unknown"],
)
async def test_heat_available_is_the_flame_and_the_flow_against_the_return(
    hass: HomeAssistant,
    zones: FakeZones,
    flame: str,
    flow: str,
    returned: str,
    expected: bool | None,
) -> None:
    """I8 (decision C1): what VT's thermostat is shown — the flame burning and the flow clearly
    above the return; against the room only where no return is known."""
    api = vt_is_set_up(hass)
    living = zones.add("living", current_temperature=20.0, hvac_action="heating")
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={"signals": boiler.mapping(), "zones": [{"entity_id": living}]},
    )
    hass.states.async_set(boiler.entity(Signal.FLAME), flame)
    for signal, value in ((Signal.FLOW, flow), (Signal.RETURN, returned)):
        hass.states.async_set(boiler.entity(signal), value, {"unit_of_measurement": "°C"})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    assert manager.heat_available is expected


async def test_a_zone_split_between_circuits_has_heat_through_either(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I8.8b: the living room's radiator on the straight circuit — its water as warm back as
    out, no heat there — and its floor loop behind a mixer whose own sensor reads 35 °C: heat
    reaches the room through the loop. One zone, in both circuits."""
    api = vt_is_set_up(hass)
    living = zones.add("living", current_temperature=20.0, hvac_action="heating")
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    hass.states.async_set(boiler.entity(Signal.FLAME), "on")
    for signal, value in ((Signal.FLOW, "45"), (Signal.RETURN, "44.5")):
        hass.states.async_set(boiler.entity(signal), value, {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.loop_flow", "35", {"unit_of_measurement": "°C"})
    circuits = [
        {"id": "main", "zones": [living], "devices": {living: ["switch.radiator"]}},
        {"id": "floor", "control": "separate", "flow_entity": "sensor.loop_flow",
         "zones": [living], "devices": {living: ["switch.loop"]}},
    ]  # fmt: skip
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={"signals": boiler.mapping(), "circuits": circuits, "zones": []},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    view = entry.runtime_data.data.zones[living]
    assert view.circuit_ids == ("main", "floor")
    assert view.heat.available is True
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    assert manager.heat_available is True
    # I9 (water-interface.md §4.1): its two circuits' waters differ, 45 °C and 35 °C — no one
    # water, the lasting fallback.
    assert (manager.supply_temperature, manager.supply_reason) == (None, "several_circuits")


def test_the_call_properties_read_their_values_defensively(hass: HomeAssistant) -> None:
    """§4, §4.3 (SmartPI's request, 2026-10-14): the boiler's call and the demand as the
    manager's properties, each of its type. Negative: a value of another type is "no data"."""
    values: dict[str, Any] = {
        "boiler_called": False,
        "call_reason": "below_threshold",
        "demand_count": 1,
        "count_threshold": 2,
        "count_by": "devices",
        "demand_power_kw": 0.4,
        "power_threshold_kw": 0.6,
        "demand_opening": 0.2,
        "opening_threshold": None,
    }
    manager = feature_manager.SmartBoilerFeatureManager(
        hass, Thermostat("climate.a"), lambda _entity: dict(values)
    )
    assert (manager.boiler_called, manager.call_reason) == (False, "below_threshold")
    assert (manager.demand_count, manager.count_threshold, manager.count_by) == (1, 2, "devices")
    assert (manager.demand_power_kw, manager.power_threshold_kw) == (0.4, 0.6)
    assert (manager.demand_opening, manager.opening_threshold) == (0.2, None)
    values.update(boiler_called="no", demand_count=True, demand_power_kw="0.4", count_by=3)
    assert manager.boiler_called is None
    assert manager.demand_count is None
    assert manager.demand_power_kw is None
    assert manager.count_by is None


def test_the_attribute_changes_only_when_the_value_changes(hass: HomeAssistant) -> None:
    """P-63: VT records its thermostats' attributes, so the plugin's is replaced only when heat
    availability changes. Negative: a value that goes away takes the attribute with it; back, it
    is published afresh."""
    values: dict[str, Any] | None = {"heat_available": True, "supply_temperature": 45.0}
    manager = feature_manager.SmartBoilerFeatureManager(
        hass, Thermostat("climate.a"), lambda _entity: None if values is None else dict(values)
    )

    def shown() -> dict[str, Any] | None:
        attributes: dict[str, Any] = {"other": 1}
        manager.add_custom_attributes(attributes)
        assert attributes.pop("other") == 1
        return attributes.get("smart_boiler")

    assert shown() == {"heat_available": True, "supply_temperature": 45}
    first = manager._published
    assert shown() == {"heat_available": True, "supply_temperature": 45}
    assert manager._published is first  # nothing new: the same published value
    values = {"heat_available": False, "supply_temperature": 45.0}
    assert shown() == {"heat_available": False, "supply_temperature": 45}  # a flip
    values = {"heat_available": None, "supply_temperature": None}
    assert shown() == {"heat_available": None, "supply_temperature": None}  # unknown now
    values = None
    assert shown() is None  # not the plugin's zone any more: no attribute
    values = {"heat_available": None, "supply_temperature": 45.0}
    assert shown() == {"heat_available": None, "supply_temperature": 45}  # afresh


def test_the_manager_answers_vt_without_state_of_its_own(hass: HomeAssistant) -> None:
    """The parts of VT's feature-manager contract the plugin has nothing to do in, and a
    lookup that keeps failing: logged once at warning level, then quietly, never into VT."""
    calls: list[str] = []

    def broken(entity_id: str) -> dict:
        calls.append(entity_id)
        raise RuntimeError("boom")

    manager = feature_manager.SmartBoilerFeatureManager(hass, Thermostat("climate.a"), broken)
    assert manager.hass is hass
    assert manager.add_listener(lambda: None) is None
    assert manager.restore_state(None) is None
    for _ in range(2):
        attributes: dict = {"other": 1}
        manager.add_custom_attributes(attributes)
        assert attributes == {"other": 1}
    assert calls == ["climate.a", "climate.a"]


def test_vt_api_lookups_that_fail_leave_the_registration_waiting_or_unsupported(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-53's other half: each way VT's API can be missing gives a state, never an error — an
    older vtherm_api without its constant, no vtherm_api module, no API kept, an API lookup that
    gives nothing."""
    import sys

    monkeypatch.setitem(sys.modules, "vtherm_api.const", None)
    assert feature_manager._api_name() == "vtherm_api"
    monkeypatch.undo()
    hass.config.components.add(VT_DOMAIN)
    assert feature_manager._api(hass) == (None, feature_manager.RegistrationState.WAITING)
    monkeypatch.setattr(feature_manager, "_stored_api", lambda _hass: object())
    monkeypatch.setattr(VThermAPI, "get_vtherm_api", staticmethod(lambda _hass: None))
    assert feature_manager._api(hass) == (None, feature_manager.RegistrationState.WAITING)
    monkeypatch.setitem(sys.modules, "vtherm_api.vtherm_api", None)
    assert feature_manager._api(hass) == (None, feature_manager.RegistrationState.UNSUPPORTED)


def test_a_registration_whose_lookups_fail_keeps_waiting(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never into VT's state writes, never out of a check: an error leaves it waiting."""
    current = feature_manager.FeatureRegistration(hass)

    def boom(*_args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(feature_manager, "_stored_api", boom)
    current._on_climate_state(None)  # type: ignore[arg-type]
    monkeypatch.setattr(current, "_check", boom)
    assert current.check() is False
    assert current.state is feature_manager.RegistrationState.WAITING
    assert current.registered_at is None
    current.stop()  # never registered: nothing to unregister


async def test_installations_attach_and_detach_in_any_order(hass: HomeAssistant) -> None:
    """The first installation registers, the last one unregisters; detaching one that is not
    attached, or with nothing registered, changes nothing else."""
    from types import SimpleNamespace

    first = SimpleNamespace(config_entry=SimpleNamespace(entry_id="first"))
    second = SimpleNamespace(config_entry=SimpleNamespace(entry_id="second"))
    feature_manager.async_attach(hass, first)  # type: ignore[arg-type]
    registered = feature_manager.registration(hass)
    feature_manager.async_attach(hass, second)  # type: ignore[arg-type]
    assert feature_manager.registration(hass) is registered  # registered once
    stranger = SimpleNamespace(config_entry=SimpleNamespace(entry_id="stranger"))
    feature_manager.async_detach(hass, stranger)  # type: ignore[arg-type]
    feature_manager.async_detach(hass, first)  # type: ignore[arg-type]
    assert feature_manager.registration(hass) is registered  # one still attached
    feature_manager.async_detach(hass, second)  # type: ignore[arg-type]
    assert feature_manager.registration(hass) is None
    hass.data[feature_manager.DATA_KEY] = {"coordinators": [first]}  # nothing registered
    feature_manager.async_detach(hass, first)  # type: ignore[arg-type]
    assert feature_manager.DATA_KEY not in hass.data
    feature_manager.async_detach(hass, first)  # type: ignore[arg-type]


async def test_a_refused_registration_is_not_retried_on_the_same_api(
    hass: HomeAssistant,
    zones: FakeZones,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """PB-46: an API that refuses the factory is not asked again at every climate state and
    update — one warning with its trace; a new API VT creates is asked once, its refusal logged
    at debug."""
    import logging

    caplog.set_level(logging.DEBUG, logger="custom_components.vtherm_smart_boiler")
    api = broken_vt(hass, monkeypatch, "register")
    entry = await setup(hass, zones)
    for index in range(50):
        hass.states.async_set("climate.other", "heat", {"n": index})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert api.attempts == 1
    registration = feature_manager.registration(hass)
    assert registration is not None
    assert registration.state is feature_manager.RegistrationState.UNSUPPORTED
    refusals = [r for r in caplog.records if "Could not register" in r.getMessage()]
    assert [r.levelno for r in refusals] == [logging.WARNING]
    assert refusals[0].exc_info is not None
    newer = BrokenApi("register")
    newer.register_feature_manager = newer.register  # type: ignore[attr-defined]
    hass.data[VT_DOMAIN] = {"vtherm_api": newer}
    monkeypatch.setattr(VThermAPI, "get_vtherm_api", staticmethod(lambda _hass=None: newer))
    hass.states.async_set("climate.other", "heat", {"n": "new"})
    hass.states.async_set("climate.other", "heat", {"n": "again"})
    assert newer.attempts == 1
    refusals = [r for r in caplog.records if "Could not register" in r.getMessage()]
    assert [r.levelno for r in refusals] == [logging.WARNING, logging.DEBUG]
    hass.data.pop(VT_DOMAIN)  # the stand-in API cannot be reset


async def test_an_ignored_unsupported_issue_stays_ignored(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """PB-50: the issue is neither deleted at an unload nor while VT is not known yet (Home
    Assistant starting), so the user's "ignore" sticks; VT able to load the manager deletes
    it."""
    hass.config.components.add(VT_DOMAIN)
    hass.data[VT_DOMAIN] = {"vtherm_api": object()}  # an API without feature managers
    entry = await setup(hass, zones)
    issues = ir.async_get(hass)
    issues.async_ignore(DOMAIN, feature_manager.UNSUPPORTED_ISSUE, True)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.data.pop(VT_DOMAIN)  # VT not set up yet at the next start: waiting
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    registration = feature_manager.registration(hass)
    assert registration is not None
    assert registration.state is feature_manager.RegistrationState.WAITING
    hass.data[VT_DOMAIN] = {"vtherm_api": object()}
    registration.check()
    issue = issues.async_get_issue(DOMAIN, feature_manager.UNSUPPORTED_ISSUE)
    assert issue is not None
    assert issue.dismissed_version is not None
    hass.data.pop(VT_DOMAIN)
    vt_is_set_up(hass)
    registration.check()
    assert registration.state is feature_manager.RegistrationState.REGISTERED
    assert issues.async_get_issue(DOMAIN, feature_manager.UNSUPPORTED_ISSUE) is None


async def test_a_failed_refresh_publishes_no_zone_values(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """PB-48: while the monitor's refresh fails — the plugin's own entities unavailable — VT's
    thermostat shows no stale values either; they come back with the next good refresh."""
    vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    coordinator = entry.runtime_data
    assert feature_manager.zone_values([coordinator], living) is not None
    coordinator.last_update_success = False
    assert feature_manager.zone_values([coordinator], living) is None
    coordinator.last_update_success = True
    assert feature_manager.zone_values([coordinator], living) is not None


# --- I9.2: the water data (docs/en/specification/water-interface.md)
# --------------------------------


async def _refreshed(hass: HomeAssistant) -> None:
    """The installation computes its data again now, as at its next update."""
    await hass.async_block_till_done()
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()


def _flow_reported(hass: HomeAssistant) -> Any:
    state = hass.states.get(FakeBoiler(hass, (Signal.FLOW,)).entity(Signal.FLOW))
    assert state is not None
    return state.last_reported


async def test_the_manager_shows_the_zone_s_water(hass: HomeAssistant, zones: FakeZones) -> None:
    """§3.1, §4: the five fields as the manager's properties — the boiler's flow reaching the
    zone's circuit, with the time of its reading; lost for now, `None` with its momentary
    reason, and the heat unknown with it."""
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    assert manager.supply_temperature == 45.0
    assert manager.supply_reason is None
    assert manager.supply_measured_at == _flow_reported(hass)
    assert manager.supply_measured_at.tzinfo is not None
    assert manager.heat_available is True
    assert manager.heat_reason is None
    FakeBoiler(hass, (Signal.FLOW,)).set(Signal.FLOW, None)
    await _refreshed(hass)
    assert manager.supply_temperature is None
    assert manager.supply_reason == "flow_unknown"
    assert manager.supply_measured_at is None
    assert manager.heat_available is None
    assert manager.heat_reason == "flow_unknown"


async def test_the_api_gives_the_same_fields_without_vt_s_lookup(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """§3.2: `hass.data["vtherm_smart_boiler_api"].zone_water(entity_id)` — the same fields as a
    read-only mapping, with no VT and no manager at all (VT 10.4.0 has no
    `get_feature_manager`); `None` for a thermostat that is not a zone; gone with the plugin."""
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    water = hass.data["vtherm_smart_boiler_api"].zone_water(living)
    assert dict(water) == {
        "supply_temperature": 45.0,
        "supply_reason": None,
        "supply_measured_at": _flow_reported(hass),
        "heat_available": True,
        "heat_reason": None,
        # §4.3 (2026-10-14): monitoring only — the boiler is not the plugin's to call.
        "boiler_called": None,
        "call_reason": "not_controlling",
        "demand_count": None,
        "count_threshold": None,
        "count_by": None,
        "demand_power_kw": None,
        "power_threshold_kw": None,
        "demand_opening": None,
        "opening_threshold": None,
    }
    with pytest.raises(TypeError):
        water["supply_temperature"] = 20.0  # read-only
    assert hass.data["vtherm_smart_boiler_api"].zone_water("climate.not_ours") is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert "vtherm_smart_boiler_api" not in hass.data


async def test_the_api_never_raises(
    hass: HomeAssistant, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative, §3.2: any error reading the data is "no data" (`None`), never an exception
    into the consumer."""
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)

    def broken(*_args: Any) -> dict:
        raise RuntimeError("boom")

    monkeypatch.setattr(feature_manager, "zone_values", broken)
    assert hass.data["vtherm_smart_boiler_api"].zone_water(living) is None


async def test_no_water_sensor_is_not_mapped(hass: HomeAssistant, zones: FakeZones) -> None:
    """Negative, §5.1: no water sensor mapped at all — a lasting `not_mapped`, for the water and
    for the heat while the flame burns; the attribute shows no temperature."""
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    boiler = FakeBoiler(hass, (Signal.FLAME,))
    boiler.set(Signal.FLAME, True)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={"signals": boiler.mapping(), "zones": [{"entity_id": living}]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    assert (manager.supply_temperature, manager.supply_reason) == (None, "not_mapped")
    assert (manager.heat_available, manager.heat_reason) == (None, "not_mapped")
    attributes: dict = {}
    manager.add_custom_attributes(attributes)
    assert attributes["smart_boiler"] == {"heat_available": None, "supply_temperature": None}


async def test_the_attribute_publishes_the_water_rounded_on_a_change_of_1_k(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """§3.3: VT records the attribute, so it shows the water rounded to 1 °C and changes only
    when the water has moved at least 1 K since it was last published, or to or from `None`;
    the heat on every change. The live value is the manager's."""
    api = vt_is_set_up(hass)
    living = zones.add("living", hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)
    manager = api.get_feature_manager(DOMAIN).create(Thermostat(living))
    boiler = FakeBoiler(hass, (Signal.FLOW,))

    async def shown(flow: float | None) -> dict:
        boiler.set(Signal.FLOW, flow)
        await _refreshed(hass)
        attributes: dict = {}
        manager.add_custom_attributes(attributes)
        return attributes["smart_boiler"]

    assert (await shown(45.0))["supply_temperature"] == 45
    assert (await shown(45.9))["supply_temperature"] == 45  # 0.9 K: not yet
    assert manager.supply_temperature == 45.9  # the live value
    assert (await shown(46.2))["supply_temperature"] == 46  # 1.2 K from 45.0: published
    assert (await shown(45.4))["supply_temperature"] == 46  # 0.8 K back: kept
    assert await shown(None) == {"heat_available": None, "supply_temperature": None}
    assert (await shown(45.4))["supply_temperature"] == 45  # back from None: at once


async def _water_set_up(
    hass: HomeAssistant,
    zones: FakeZones,
    values: dict[Signal, float | bool | None],
    *,
    room: float | None = 20.0,
    circuits: list[dict[str, Any]] | None = None,
    freshness: dict[str, float] | None = None,
) -> str:
    """The living room, heating, with the boiler's ``values``; in the last of ``circuits``."""
    living = zones.add(
        "living", current_temperature=room, hvac_action="heating", valve_open_percent=60
    )
    boiler = FakeBoiler(hass, tuple(values))
    boiler.set_many(values)
    options: dict[str, Any] = {"signals": boiler.mapping(), "zones": [{"entity_id": living}]}
    if circuits is not None:
        options["circuits"] = circuits
        options["zones"] = [{"entity_id": living, "circuit": circuits[-1]["id"]}]
    if freshness is not None:
        options["freshness"] = freshness
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return living


def _water(hass: HomeAssistant, living: str) -> tuple[Any, ...]:
    """The public API's water and heat with their reasons; the moment of the reading known
    exactly while the water is."""
    water = hass.data["vtherm_smart_boiler_api"].zone_water(living)
    assert water is not None
    assert (water["supply_measured_at"] is None) is (water["supply_temperature"] is None)
    return tuple(
        water[name]
        for name in ("supply_temperature", "supply_reason", "heat_available", "heat_reason")
    )


async def test_the_api_says_a_mixed_circuit_without_its_own_sensor_is_not_measured(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """§4.1, §4.2: a zone on a mixed circuit with no flow sensor of its own — the boiler's flow
    says nothing about it: a lasting `circuit_not_measured`, for the water and for the heat
    while the flame burns."""
    living = await _water_set_up(
        hass,
        zones,
        {Signal.FLAME: True, Signal.FLOW: 45.0},
        circuits=[
            {"id": "main", "control": "unmixed_shared"},
            {"id": "floor", "control": "separate"},
        ],
    )
    assert _water(hass, living) == (None, "circuit_not_measured", None, "circuit_not_measured")


async def test_the_api_says_a_flow_reading_too_old_is_stale(
    hass: HomeAssistant, zones: FakeZones, freezer: Any
) -> None:
    """§4.1, §4.2: the boiler's flow older than its age limit (here set to 5 minutes) — a
    momentary `flow_stale`, the heat unknown with it, never "no"; fresh again, known again."""
    living = await _water_set_up(
        hass, zones, {Signal.FLAME: True, Signal.FLOW: 45.0}, freshness={"flow": 300.0}
    )
    assert _water(hass, living) == (45.0, None, True, None)
    freezer.tick(400)
    await _refreshed(hass)
    assert _water(hass, living) == (None, "flow_stale", None, "flow_stale")
    FakeBoiler(hass, (Signal.FLOW,)).set(Signal.FLOW, 44.0)
    await _refreshed(hass)
    assert _water(hass, living) == (44.0, None, True, None)


async def test_the_api_says_hot_water_takes_the_heat(hass: HomeAssistant, zones: FakeZones) -> None:
    """§4.2: hot water with priority running — the water still shown, the heat "no" for
    `dhw_active`; over, heat again."""
    values = {Signal.FLAME: True, Signal.FLOW: 45.0, Signal.DHW_ACTIVE: True}
    living = await _water_set_up(hass, zones, values)
    assert _water(hass, living) == (45.0, None, False, "dhw_active")
    FakeBoiler(hass, (Signal.DHW_ACTIVE,)).set(Signal.DHW_ACTIVE, False)
    await _refreshed(hass)
    assert _water(hass, living) == (45.0, None, True, None)


@pytest.mark.parametrize(
    ("room", "flow", "expected"),
    [
        (None, 45.0, (45.0, None, None, "room_unknown")),
        (20.0, 22.0, (22.0, None, False, "flow_near_room")),
        (20.0, 23.5, (23.5, None, True, None)),
    ],
    ids=["room_unknown", "flow_near_room", "above_the_margin"],
)
async def test_the_api_judges_the_flow_against_the_room_without_a_return(
    hass: HomeAssistant,
    zones: FakeZones,
    room: float | None,
    flow: float,
    expected: tuple[Any, ...],
) -> None:
    """§4.2: no return mapped — the flow judged against the room: unknown without the room's
    temperature (`room_unknown`); "no" within 3 K of it (`flow_near_room`); heat above."""
    living = await _water_set_up(hass, zones, {Signal.FLAME: True, Signal.FLOW: flow}, room=room)
    assert _water(hass, living) == expected
