"""The VT feature manager: registered only once VT's API exists, the channel VT hands its
thermostats through, publishing nothing on them (I12.9), never an exception into VT,
unregistered with the last installation. And the heat a zone gets (I8, decision C1), which the
diagnostics show."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.config_entries import (
    SIGNAL_CONFIG_ENTRY_CHANGED,
    ConfigEntryChange,
    ConfigEntryState,
)
from homeassistant.const import EVENT_COMPONENT_LOADED
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
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


@dataclass
class Runtime:
    """A VT thermostat as ``vtherm_api`` declares it: its entity ID, nothing else."""

    entity_id: str


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


async def test_the_manager_keeps_the_thermostat_and_publishes_nothing(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """VT hands each thermostat to the factory; the manager keeps it for the zone reads and
    publishes nothing on it (I12.9: no ``smart_boiler`` attribute, no water properties — VT
    10.5.1 on calls ``add_custom_attributes`` only where a manager has it). The unload
    unregisters the factory."""
    api = vt_is_set_up(hass)
    living = zones.add("living", handed_over=False, hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    factory = api.get_feature_manager(DOMAIN)
    thermostat = Runtime(living)
    assert factory.supports(thermostat)
    manager = factory.create(thermostat)
    manager.post_init({})
    await manager.start_listening()
    assert await manager.refresh_state() is False
    assert vtherm_link.vt_thermostat(hass, living) is thermostat
    assert not hasattr(manager, "add_custom_attributes")
    for gone in (
        "heat_available",
        "heat_reason",
        "supply_temperature",
        "supply_reason",
        "supply_measured_at",
        "boiler_called",
        "call_reason",
    ):
        assert not hasattr(manager, gone), gone
    assert not hasattr(feature_manager, "ATTRIBUTE")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert api.list_feature_managers() == []


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


def test_the_manager_never_raises_into_vt(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T-53: keeping or forgetting the thermostat, noting it started or its power failing never
    reaches VT."""
    from .harness import power_command, run_now

    def boom(*_args: object) -> None:
        raise RuntimeError("boom")

    for name in (
        "register_thermostat",
        "unregister_thermostat",
        "thermostat_started",
        "thermostat_power",
    ):
        monkeypatch.setattr(vtherm_link, name, boom)
    manager = feature_manager.SmartBoilerFeatureManager(hass, Thermostat("climate.a"))
    assert run_now(manager.refresh_state()) is False
    command = power_command("switch.a", "switch", 0.5)
    assert run_now(manager.async_on_underlying_power(command)) is None
    assert manager.stop_listening() is None
    assert manager.name == DOMAIN
    assert manager.is_configured
    assert not manager.is_detected


async def test_the_thermostats_handed_over_outlive_the_plugins_reload(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P32: VT keeps the managers it created and hands nothing over again when the plugin
    reloads (an options change): the thermostats it handed over stay kept for this Home
    Assistant run, so the zones are still read through ``vtherm_api`` until VT reloads."""
    api = vt_is_set_up(hass)
    living = zones.add("living", handed_over=False, hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    thermostat = Runtime(living)
    api.get_feature_manager(DOMAIN).create(thermostat)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert vtherm_link.vt_thermostat(hass, living) is thermostat
    assert not hasattr(feature_manager, "zone_values")  # no values of the plugin's for VT


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


async def test_a_new_vt_api_gets_the_factory_when_a_vt_entry_is_set_up(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """A real VT 10.6.4, which the floor lets through, drops its API with its last entry and
    creates a new one when an entry is set up again. Home Assistant's signal for that entry
    being set up gives the new API the factory at once, before VT builds its thermostats.
    Negative: a climate's state no longer does (I12: nothing of VT's state is read), nor another
    integration's entry."""
    api = vt_is_set_up(hass)
    await setup(hass, zones)
    assert api.list_feature_managers() == [DOMAIN]
    VThermAPI.reset_vtherm_api()
    new = VThermAPI.get_vtherm_api(hass)
    hass.states.async_set("climate.rebuilt_thermostat", "heat")
    other = MockConfigEntry(domain="generic_thermostat")
    other.add_to_hass(hass)
    other.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.UPDATED, other)
    assert new.list_feature_managers() == []
    vt_entry = MockConfigEntry(domain=VT_DOMAIN)
    vt_entry.add_to_hass(hass)
    vt_entry.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    async_dispatcher_send(hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.UPDATED, vt_entry)
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
    """P107: a thermostat already running is handed over only at VT's next reload; once it is,
    the issue goes."""
    api = vt_is_set_up(hass)
    living = zones.add("living", handed_over=False, hvac_action="heating", valve_open_percent=60)
    entry = await setup(hass, zones)
    issue_id = f"vt_reload_needed_{entry.entry_id}"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None  # give VT time
    freezer.tick(20 * 60)
    zones.set("living", hvac_action="heating", valve_open_percent=60)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    api.get_feature_manager(DOMAIN).create(Runtime(living))  # VT reloaded
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
    not handed over some time after the registration needs VT's reload; one unavailable,
    not ready, of unknown mode or away is not listed. Negative: none of them known, no
    issue."""
    vt_is_set_up(hass)
    zones.add("living", handed_over=False, hvac_action="heating")
    zones.add("away", handed_over=False)
    zones.add("unavailable", handed_over=False, state="unavailable")
    zones.add("starting", handed_over=False, state="off", is_ready=False)
    zones.add("placeholder", handed_over=False, state="off", is_ready=None, specific_states=None)
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
        ("10.6.3", True, feature_manager.RegistrationState.UNSUPPORTED),
        ("10.6.4", True, feature_manager.RegistrationState.REGISTERED),  # 10.6.5's manifest
        ("10.6.5", True, feature_manager.RegistrationState.REGISTERED),
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
    """I12.6 (P-60): a VT older than the oldest supported is not registered with, whatever its
    API offers, and the issue names 10.6.5 — compared as 10.6.4, what its manifest says.
    Negative: the version unknown or unreadable, the capability decides as before."""
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
        assert issue.translation_placeholders == {"version": "10.6.5"}
    else:
        assert issue is None
    if method:
        unsupported = expected is feature_manager.RegistrationState.UNSUPPORTED
        assert api.list_feature_managers() == ([] if unsupported else [DOMAIN])
    else:
        hass.data.pop(VT_DOMAIN)


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
    """I8 (decision C1): the heat a zone gets, as the diagnostics show it — the flame burning
    and the flow clearly above the return; against the room only where no return is known."""
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
    assert entry.runtime_data.data.zones[living].heat.available is expected


async def test_a_zone_split_between_circuits_has_heat_through_either(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I8.8b: the living room's radiator on the straight circuit — its water as warm back as
    out, no heat there — and its floor loop behind a mixer whose own sensor reads 35 °C: heat
    reaches the room through the loop. One zone, in both circuits."""
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


def test_the_manager_answers_vt_without_state_of_its_own(hass: HomeAssistant) -> None:
    """The parts of VT's feature-manager contract the plugin has nothing to do in."""
    manager = feature_manager.SmartBoilerFeatureManager(hass, Thermostat("climate.a"))
    assert manager.hass is hass
    assert manager.add_listener(lambda: None) is None
    assert manager.restore_state(None) is None


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
    """Never into Home Assistant's entry signal, never out of a check: an error leaves it
    waiting."""
    current = feature_manager.FeatureRegistration(hass)

    def boom(*_args: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(feature_manager, "_stored_api", boom)
    vt_entry = MockConfigEntry(domain=VT_DOMAIN)
    vt_entry.add_to_hass(hass)
    vt_entry.mock_state(hass, ConfigEntryState.LOADED)
    current._on_entry_changed(ConfigEntryChange.UPDATED, vt_entry)
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
    """PB-46: an API that refuses the factory is not asked again at every VT entry signal and
    update — one warning with its trace; a new API VT creates is asked once, its refusal logged
    at debug."""
    import logging

    caplog.set_level(logging.DEBUG, logger="custom_components.vtherm_smart_boiler")
    api = broken_vt(hass, monkeypatch, "register")
    entry = await setup(hass, zones)
    vt_entry = MockConfigEntry(domain=VT_DOMAIN)
    vt_entry.add_to_hass(hass)
    vt_entry.mock_state(hass, ConfigEntryState.LOADED)

    def vt_entry_set_up() -> None:
        async_dispatcher_send(
            hass, SIGNAL_CONFIG_ENTRY_CHANGED, ConfigEntryChange.UPDATED, vt_entry
        )

    for _ in range(50):
        vt_entry_set_up()
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
    vt_entry_set_up()
    vt_entry_set_up()
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


# --- The heat a zone gets (I8, decision C1), as the diagnostics show it ----------------------


async def _refreshed(hass: HomeAssistant) -> None:
    """The installation computes its data again now, as at its next update."""
    await hass.async_block_till_done()
    await hass.config_entries.async_entries(DOMAIN)[0].runtime_data.async_refresh()


async def test_no_public_api_outside_vtherm_api(hass: HomeAssistant, zones: FakeZones) -> None:
    """The user's rule (2026-11-24): the public API the plugin kept in ``hass.data`` is gone; and
    since I12.9 nothing goes out to VT's thermostats either."""
    zones.add("living", hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)
    assert "vtherm_smart_boiler_api" not in hass.data
    assert not hasattr(feature_manager, "SmartBoilerApi")


async def test_vt_tells_the_manager_its_thermostat_started_and_its_power(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.7: VT's first ``refresh_state`` on the manager — which it calls only once the
    thermostat is ready — starts the zone; its power hook gives the duty, which VT calls only on a
    manager that is configured (``vtherm_api`` 0.9.0 ``underlying_hooks.py``). The hook has the
    name and the signature ``vtherm_api`` declares."""
    import inspect

    from vtherm_api.underlying_hooks import InterfaceUnderlyingPowerHook

    from .harness import power_command

    api = vt_is_set_up(hass)
    living = zones.add("living", handed_over=False, hvac_action="heating", on_percent=None)
    await setup(hass, zones)
    thermostat = Runtime(living)
    manager = api.get_feature_manager(DOMAIN).create(thermostat)
    assert isinstance(manager, InterfaceUnderlyingPowerHook)
    assert inspect.iscoroutinefunction(manager.async_on_underlying_power)
    assert manager.is_configured
    link = vtherm_link.VThermLink(hass, [living])
    assert (link.zone(living).started, link.zone(living).on_percent) == (False, None)
    await manager.refresh_state()
    await manager.async_on_underlying_power(power_command("switch.heater", "switch", 0.6))
    zone = link.zone(living)
    assert (zone.started, zone.on_percent, zone.valve_open) == (True, 0.6, None)
    manager.stop_listening()
    assert link.zone(living).started is False


async def test_the_manager_keeps_its_thermostat_for_the_zone_reads(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """The thermostat VT hands to the manager is the one the zone is read from through
    ``vtherm_api`` (``vtherm_link``), matched by its declared entity ID (I12.7); VT stopping it
    (the manager's ``stop_listening``) leaves the zone not known."""
    api = vt_is_set_up(hass)
    living = zones.add("living", handed_over=False, hvac_action="heating", valve_open_percent=60)
    await setup(hass, zones)
    thermostat = Runtime(living)
    manager = api.get_feature_manager(DOMAIN).create(thermostat)
    assert vtherm_link.vt_thermostat(hass, living) is thermostat
    manager.stop_listening()
    assert vtherm_link.vt_thermostat(hass, living) is None


async def test_no_water_sensor_is_not_mapped(hass: HomeAssistant, zones: FakeZones) -> None:
    """Negative: no water sensor mapped at all — a lasting `not_mapped` for the heat while the
    flame burns."""
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
    assert _heat(hass, living) == (None, "not_mapped")


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


def _heat(hass: HomeAssistant, living: str) -> tuple[Any, ...]:
    """The heat the zone gets, with its reason, as the diagnostics show it."""
    heat = hass.config_entries.async_entries(DOMAIN)[0].runtime_data.data.zones[living].heat
    return heat.available, None if heat.reason is None else heat.reason.value


async def test_a_mixed_circuit_without_its_own_sensor_is_not_measured(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """A zone on a mixed circuit with no flow sensor of its own — the boiler's flow says nothing
    about it: a lasting `circuit_not_measured` for the heat while the flame burns."""
    living = await _water_set_up(
        hass,
        zones,
        {Signal.FLAME: True, Signal.FLOW: 45.0},
        circuits=[
            {"id": "main", "control": "unmixed_shared"},
            {"id": "floor", "control": "separate"},
        ],
    )
    assert _heat(hass, living) == (None, "circuit_not_measured")


async def test_a_flow_reading_too_old_is_stale(
    hass: HomeAssistant, zones: FakeZones, freezer: Any
) -> None:
    """The boiler's flow older than its age limit (here set to 5 minutes) — a momentary
    `flow_stale`, the heat unknown, never "no"; fresh again, known again."""
    living = await _water_set_up(
        hass, zones, {Signal.FLAME: True, Signal.FLOW: 45.0}, freshness={"flow": 300.0}
    )
    assert _heat(hass, living) == (True, None)
    freezer.tick(400)
    await _refreshed(hass)
    assert _heat(hass, living) == (None, "flow_stale")
    FakeBoiler(hass, (Signal.FLOW,)).set(Signal.FLOW, 44.0)
    await _refreshed(hass)
    assert _heat(hass, living) == (True, None)


async def test_hot_water_takes_the_heat(hass: HomeAssistant, zones: FakeZones) -> None:
    """Hot water with priority running — the heat "no" for `dhw_active`; over, heat again."""
    values = {Signal.FLAME: True, Signal.FLOW: 45.0, Signal.DHW_ACTIVE: True}
    living = await _water_set_up(hass, zones, values)
    assert _heat(hass, living) == (False, "dhw_active")
    FakeBoiler(hass, (Signal.DHW_ACTIVE,)).set(Signal.DHW_ACTIVE, False)
    await _refreshed(hass)
    assert _heat(hass, living) == (True, None)


@pytest.mark.parametrize(
    ("room", "flow", "expected"),
    [
        (None, 45.0, (None, "room_unknown")),
        (20.0, 22.0, (False, "flow_near_room")),
        (20.0, 23.5, (True, None)),
    ],
    ids=["room_unknown", "flow_near_room", "above_the_margin"],
)
async def test_the_flow_is_judged_against_the_room_without_a_return(
    hass: HomeAssistant,
    zones: FakeZones,
    room: float | None,
    flow: float,
    expected: tuple[Any, ...],
) -> None:
    """No return mapped — the flow judged against the room: unknown without the room's
    temperature (`room_unknown`); "no" within 3 K of it (`flow_near_room`); heat above."""
    living = await _water_set_up(hass, zones, {Signal.FLAME: True, Signal.FLOW: flow}, room=room)
    assert _heat(hass, living) == expected
