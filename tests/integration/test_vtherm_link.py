"""VT link: zones from VT climate entities, the central mode and capability detection."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from importlib.metadata import version
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.vtherm_smart_boiler.vtherm_attributes import CentralMode
from custom_components.vtherm_smart_boiler.vtherm_link import (
    VT_OLDEST,
    VThermLink,
    register_thermostat,
    unregister_thermostat,
    vt_climate_entities,
    vt_supported,
)

from .harness import VT_HELPER, VT_PLATFORM, FakeVtThermostat, FakeZones, vt_central_settings

# The installed vtherm_api: the pinned version, or the newest in the early warnings.
VTHERM_API = version("vtherm_api")


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


async def test_a_zones_device_count_comes_from_its_vt_entry(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """2026-10-14: what a count of devices is capped by — the devices VT's entry lists for the
    zone; a zone whose list cannot be read has none (``None``: it counts one)."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    living = zones.add("living", hvac_action="heating", valve_open_percent=80)
    bedroom = zones.add("bedroom", hvac_action="idle")
    entry = MockConfigEntry(
        domain="versatile_thermostat", data={"underlying_entity_ids": ["switch.a", "switch.b"]}
    )
    entry.add_to_hass(hass)
    er.async_get(hass).async_update_entity(living, config_entry_id=entry.entry_id)
    states = {z.zone_id: z for z in VThermLink(hass, [living, bedroom]).zones()}
    assert states[living].device_count == 2
    assert states[bedroom].device_count is None


async def test_nothing_of_smartpi_is_read(hass: HomeAssistant, zones: FakeZones) -> None:
    """I12.9: SmartPI's diagnostic sensor, named in VT's ``specific_states``, is not read, nor
    its learning flag, nor VT's Auto-TPI keys; a SmartPI room is judged like any other."""
    living = zones.add(
        "living",
        configuration={"proportional_function": "smartpi"},
        specific_states={"regulation_diagnostics": "sensor.diag", "smartpi_learning_enabled": True},
    )
    hass.states.async_set("sensor.diag", "bootstrap_hysteresis")
    link = VThermLink(hass, [living])
    zone = link.zone(living)
    assert not hasattr(zone, "smartpi_learning_phase")
    algorithm = link.zone_algorithm(living)
    for gone in ("proportional_function", "smartpi_learning", "auto_tpi", "uses_water_data"):
        assert not hasattr(algorithm, gone), gone


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
    link = VThermLink(hass, [])
    await link.async_detect()
    capabilities = link.capabilities()
    assert capabilities.vt_loaded is False
    assert capabilities.vt_version is None
    assert capabilities.vtherm_api_version == VTHERM_API
    assert not hasattr(capabilities, "smartpi_loaded")  # I12.9


async def test_the_api_version_is_read_once_off_the_event_loop(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P30: reading package metadata is disk I/O — once, in the executor, not every update."""
    import threading

    from custom_components.vtherm_smart_boiler import vtherm_link

    threads: list[bool] = []
    real = vtherm_link.version

    def counted(name: str) -> str:
        threads.append(threading.current_thread() is threading.main_thread())
        return real(name)

    monkeypatch.setattr(vtherm_link, "version", counted)
    link = VThermLink(hass, [])
    await link.async_detect()
    for _ in range(5):
        assert link.capabilities().vtherm_api_version == VTHERM_API
    assert threads == [False]  # once, not in the loop's thread


async def test_zone_algorithm_from_live_attributes(hass: HomeAssistant, zones: FakeZones) -> None:
    """Whether VT's central boiler counts the zone, from its live configuration; unknown for a
    zone VT does not show."""
    counted = zones.add("counted", configuration={"is_used_by_central_boiler": True})
    left_out = zones.add("left_out", configuration={"is_used_by_central_boiler": False})
    link = VThermLink(hass, [counted, left_out])
    assert link.zone_algorithm(counted).used_by_central_boiler is True
    assert link.zone_algorithm(left_out).used_by_central_boiler is False
    assert link.zone_algorithm(counted).known
    missing = link.zone_algorithm("climate.missing")
    assert missing.used_by_central_boiler is None
    assert not missing.known


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("10.1.0", False),  # takes the registration, never creates the manager (Q3.1)
        ("10.5.1", False),
        ("10.6.3", False),
        ("10.6.4.beta1", False),  # a beta is not a supported install: under-claimed
        ("10.6.4", True),  # VT 10.6.5's manifest says 10.6.4
        ("10.6.5", True),
        ("10.6.6.beta2", True),
        ("10.10.0", True),
        (None, None),  # unknown: capability detection decides
        ("not a version", None),
        ("", None),
    ],
)
def test_vt_versions_the_plugin_supports(version: str | None, expected: bool | None) -> None:
    """I12.6: the oldest VT supported is 10.6.5, compared as 10.6.4 — what its manifest says."""
    assert vt_supported(version) is expected
    assert VT_OLDEST == "10.6.4"


async def test_vt_is_loaded_only_with_a_loaded_entry(hass: HomeAssistant) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.config.components.add("versatile_thermostat")
    entry = MockConfigEntry(domain="versatile_thermostat", state=ConfigEntryState.SETUP_ERROR)
    entry.add_to_hass(hass)
    assert not VThermLink(hass, []).capabilities().vt_loaded  # set up, but its entries failed
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert VThermLink(hass, []).capabilities().vt_loaded


async def test_a_rooms_thermometer_from_entry_infos_decides_its_trust(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12, decision 8: the room's thermometer is the sensor the thermostat's ``entry_infos``
    names (VT 10.6.5 ``temperature_sensor_entity_id``), the user's device: unavailable, unknown or
    gone, the room's temperature is not trusted — VT keeps its last view and still runs the zone
    on it. A steady thermometer stays fine, however long ago it changed."""
    living = zones.add("living", current_temperature=20.0, hvac_action="idle")
    thermometer = zones.thermostats["living"].thermometer
    link = VThermLink(hass, [living])
    stop = link.start(dt_util.utcnow().timestamp() - 60.0)
    assert link.zone(living).room_sensor_lost is False
    for state in ("unavailable", "unknown"):
        hass.states.async_set(thermometer, state)
        zone = link.zone(living)
        assert zone.room_sensor_lost is True
        assert zone.temperature == 20.0  # VT's view is kept: VT still runs the zone on it
    hass.states.async_remove(thermometer)
    assert link.zone(living).room_sensor_lost is True
    hass.states.async_set(thermometer, "19.0")
    assert link.zone(living).room_sensor_lost is False
    # A thermostat whose entry_infos names no thermometer: nothing to judge by — trusted.
    zones.stand_in.entry_infos = {}
    zones.thermostats["living"].thermometer = ""
    assert link.zone(living).room_sensor_lost is False
    stop()


async def test_vts_safety_event_leaves_a_room_out_until_it_ends(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12, decision 8: VT's safety event (``versatile_thermostat_safety_event``, VT 10.6.5
    ``feature_safety_manager.py``: ``type`` start or end, the thermostat in ``entity_id``) takes
    the room out of the curve's judgement until it ends. Another thermostat's event, one of
    another type or without a thermostat changes nothing; a thermostat VT hands over anew — VT
    reloaded it — is not taken for the old one; once stopped, the link hears no more."""
    living = zones.add("living", hvac_action="idle")
    bedroom = zones.add("bedroom", hvac_action="idle")
    link = VThermLink(hass, [living, bedroom])
    stop = link.start(dt_util.utcnow().timestamp() - 60.0)

    def lost() -> list[str]:
        return [z.zone_id for z in link.zones() if z.room_sensor_lost]

    zones.vt_event("living", "safety", start=True)
    await hass.async_block_till_done()
    assert lost() == [living]
    for data in ({"type": "start"}, {"type": "pause", "entity_id": bedroom}, {"entity_id": 3}):
        hass.bus.async_fire("versatile_thermostat_safety_event", data)
    await hass.async_block_till_done()
    assert lost() == [living]
    zones.vt_event("living", "safety", start=False)
    await hass.async_block_till_done()
    assert lost() == []
    zones.vt_event("bedroom", "safety", start=True)
    await hass.async_block_till_done()
    assert lost() == [bedroom]
    old = zones.thermostats["bedroom"]
    unregister_thermostat(hass, old)  # VT reloads it: a new thermostat handed over
    renewed = replace(old)
    register_thermostat(hass, renewed)
    assert lost() == []  # forgotten with the old thermostat
    stop()
    zones.vt_event("living", "safety", start=True)
    await hass.async_block_till_done()
    assert lost() == []


async def test_a_room_counts_only_once_vt_measured_it_after_the_plugins_start(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12, decision 8: after the plugin starts, a room's temperature counts only once VT's
    ``last_temperature_measure`` for it — through ``vtherm_api`` only — is newer than the
    start; one VT never handed over has no such clock: never trusted."""
    living = zones.add("living", hvac_action="idle")
    away = zones.add("bedroom", handed_over=False, hvac_action="idle")
    link = VThermLink(hass, [living, away])
    start = dt_util.utcnow()
    stop = link.start(start.timestamp())
    thermostat = zones.thermostats["living"]
    thermostat.measured = start - timedelta(minutes=5)
    assert link.zone(living).room_sensor_lost is True
    thermostat.measured = start
    assert link.zone(living).room_sensor_lost is True  # not newer than the start
    thermostat.measured = start + timedelta(seconds=1)
    assert link.zone(living).room_sensor_lost is False
    assert link.zone(away).room_sensor_lost is True
    stop()


@pytest.mark.parametrize("source", ["sensor", "vt_event", "vt_off_reason", "none"])
async def test_a_rooms_window_is_open_by_vt_or_by_its_sensor(
    hass: HomeAssistant, zones: FakeZones, source: str
) -> None:
    """I12.10 (gap 22): a room's window is open while VT holds it off for a window
    (``hvac_off_reason`` ``hvac_off_window_detection``), VT's automatic window detection says so
    (``versatile_thermostat_window_auto_event`` start, until its end), or the window sensor the
    thermostat's ``entry_infos`` names (``window_sensor_entity_id``) reads on."""
    living = zones.add("living", hvac_action="idle")
    link = VThermLink(hass, [living])
    stop = link.start(dt_util.utcnow().timestamp() - 60.0)
    assert link.zone(living).window_open is False
    if source == "sensor":
        hass.states.async_set(zones.thermostats["living"].window_sensor, "on")
    elif source == "vt_event":
        zones.vt_event("living", "window_auto", start=True)
        await hass.async_block_till_done()
    elif source == "vt_off_reason":
        reason = {"hvac_off_reason": "hvac_off_window_detection"}
        zones.set("living", "off", hvac_action="off", specific_states=reason)
    else:
        zones.set("living", "off", specific_states={"hvac_off_reason": "hvac_off_manual"})
    assert link.zone(living).window_open is (source != "none")
    if source == "vt_event":
        zones.vt_event("living", "window_auto", start=False)
        await hass.async_block_till_done()
        assert link.zone(living).window_open is False
    stop()


async def test_a_zones_underlying_entities_are_read_from_its_vt_entry(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """VT 10.4.0 keeps what a thermostat drives in its entry's data. Negative: a zone not
    registered, without an entry, whose entry is gone, or without the list (an older VT) cannot
    be read — ``None``; items that are not entity IDs are left out."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import zone_underlying_entities

    registry = er.async_get(hass)
    living = zones.add("living")
    assert zone_underlying_entities(hass, "climate.not_registered") is None
    assert zone_underlying_entities(hass, living) is None  # no entry
    entry = MockConfigEntry(
        domain=VT_PLATFORM, data={"underlying_entity_ids": ["switch.valve", "", 7, None]}
    )
    entry.add_to_hass(hass)
    registry.async_update_entity(living, config_entry_id=entry.entry_id)
    assert zone_underlying_entities(hass, living) == ("switch.valve",)
    hass.config_entries.async_update_entry(entry, data={"underlying_entity_ids": "switch.valve"})
    assert zone_underlying_entities(hass, living) is None  # not a list
    hass.config_entries.async_update_entry(entry, data={})
    assert zone_underlying_entities(hass, living) is None  # an older VT: no list
    await hass.config_entries.async_remove(entry.entry_id)
    assert zone_underlying_entities(hass, living) is None


async def test_each_vt_zones_devices_are_found_with_their_zone(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I8.8c: the devices a circuit's form offers — each VT zone's own, with the zone; a zone
    whose list cannot be read offers none; a device two zones name stays the first's."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import zone_devices

    registry = er.async_get(hass)
    living, bedroom = zones.add("living"), zones.add("bedroom")
    zones.add("hall")  # no entry: nothing to offer
    assert zone_devices(hass) == {}
    for zone, devices in ((living, ["switch.radiator", "switch.loop"]), (bedroom, ["switch.loop"])):
        entry = MockConfigEntry(domain=VT_PLATFORM, data={"underlying_entity_ids": devices})
        entry.add_to_hass(hass)
        registry.async_update_entity(zone, config_entry_id=entry.entry_id)
    assert zone_devices(hass) == {"switch.loop": bedroom, "switch.radiator": living}


async def test_only_climates_of_the_boilers_devices_count_as_its_thermostat(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """X5.19: an ``opentherm_gw`` climate, or a climate on a device that carries a boiler
    entity, among a zone's underlying entities. Negative: a switch of the gateway, a climate of
    another device, an underlying climate not registered."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import zones_on_boiler_thermostat

    registry = er.async_get(hass)
    owner = MockConfigEntry(domain="mqtt")
    owner.add_to_hass(hass)
    boiler = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("mqtt", "boiler")}
    )
    room = dr.async_get(hass).async_get_or_create(
        config_entry_id=owner.entry_id, identifiers={("mqtt", "room")}
    )
    flame = registry.async_get_or_create(
        "binary_sensor", "mqtt", "flame", device_id=boiler.id
    ).entity_id
    gateway = registry.async_get_or_create("climate", "opentherm_gw", "gw").entity_id
    gateway_switch = registry.async_get_or_create("switch", "opentherm_gw", "gw-ch").entity_id
    on_boiler = registry.async_get_or_create("climate", "mqtt", "thermostat", device_id=boiler.id)
    elsewhere = registry.async_get_or_create("climate", "mqtt", "trv", device_id=room.id)
    cases = {
        "gateway": [gateway],
        "boiler_device": [on_boiler.entity_id],
        "switch_of_gateway": [gateway_switch],
        "other_device": [elsewhere.entity_id],
        "not_registered": ["climate.nowhere"],
    }
    found: dict[str, list[str]] = {}
    for name, underlying in cases.items():
        zone = zones.add(name)
        entry = MockConfigEntry(domain=VT_PLATFORM, data={"underlying_entity_ids": underlying})
        entry.add_to_hass(hass)
        registry.async_update_entity(zone, config_entry_id=entry.entry_id)
        found[name] = zones_on_boiler_thermostat(hass, [zone], [flame])
    assert {name for name, zones_found in found.items() if zones_found} == {
        "gateway",
        "boiler_device",
    }
    zone = zones.entities["boiler_device"]
    assert zones_on_boiler_thermostat(hass, [zone], []) == []  # no boiler entity on that device


async def test_zones_of_another_kind(hass: HomeAssistant, zones: FakeZones) -> None:
    """X5.7: a zone registered by another integration, or of another domain, or reported but
    not registered, is not a VT climate. Negative: a zone neither registered nor reported is
    unknown (VT away), not of another kind."""
    from custom_components.vtherm_smart_boiler.vtherm_link import is_vt_climate

    registry = er.async_get(hass)
    living = zones.add("living")
    other = registry.async_get_or_create("climate", "generic_thermostat", "hall").entity_id
    wrong_domain = registry.async_get_or_create("switch", VT_PLATFORM, "lock").entity_id
    hass.states.async_set("climate.template_room", "heat")
    link = VThermLink(hass, [living, other, wrong_domain, "climate.template_room", "climate.away"])
    assert link.zones_of_another_kind() == [other, wrong_domain, "climate.template_room"]
    assert is_vt_climate(hass, living)
    assert not is_vt_climate(hass, other)
    assert not is_vt_climate(hass, "climate.away")


# --- I12: VT's central boiler's commands, settings and event, read only ---------------------


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ("switch.r/switch.turn_on", ("switch.r", "switch", "turn_on", None, None)),
        (  # a template in the value, "/" included (VT 10.6.1)
            "input_boolean.h/input_boolean.turn_on/value:{{ 1/2 }}",
            ("input_boolean.h", "input_boolean", "turn_on", "value", "{{ 1/2 }}"),
        ),
        (
            " climate.b / climate.set_hvac_mode / hvac_mode : heat ",
            ("climate.b", "climate", "set_hvac_mode", "hvac_mode", "heat"),
        ),
        ("switch.r/switch.turn_on/", None),  # an empty attribute part
        ("switch.r/switch.turn_on/value", None),  # no "attribute:value"
        ("switch.r", None),
        ("switch/switch.turn_on", None),  # no entity ID
        ("switch.r/turn_on", None),  # no service domain
        ("a/b/c/d", None),
        ("", None),
        (None, None),
        (5, None),
    ],
)
def test_vt_commands_are_read_in_vts_documented_format(raw: object, parsed: tuple | None) -> None:
    from custom_components.vtherm_smart_boiler.vtherm_link import VtCommand, parse_vt_command

    assert parse_vt_command(raw) == (None if parsed is None else VtCommand(*parsed))


ON = f"{VT_HELPER}/input_boolean.turn_on"
OFF = f"{VT_HELPER}/input_boolean.turn_off"


@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ((True, ON, OFF), (None, None)),
        ((True, ON.replace("input_boolean.turn", "homeassistant.turn"), OFF), (None, None)),
        ((False, ON, OFF), ("vt_central_boiler_not_set", None)),
        ((True, None, OFF), ("vt_central_boiler_not_set", None)),
        ((True, ON, None), ("vt_central_boiler_not_set", None)),
        ((True, "switch.r/switch.turn_on", OFF), ("vt_command_not_helper", "switch.r")),
        ((True, ON, "switch.r/switch.turn_off"), ("vt_command_not_helper", "switch.r")),
        ((True, OFF, ON), ("vt_command_not_helper", VT_HELPER)),  # the other way round
        ((True, f"{VT_HELPER}/input_boolean.toggle", OFF), ("vt_command_not_helper", VT_HELPER)),
        ((True, f"{ON}/value:1", OFF), ("vt_command_not_helper", VT_HELPER)),
        ((True, "nonsense", OFF), ("vt_command_not_helper", "nonsense")),
    ],
)
def test_vts_central_boiler_must_switch_the_helper_alone(
    settings: tuple[bool, str | None, str | None], expected: tuple[str | None, str | None]
) -> None:
    """I12: ticked with both commands, the activation turning the helper on, the deactivation
    turning it off — else the problem, and the entity a command targets instead."""
    from custom_components.vtherm_smart_boiler.vtherm_link import VtCentralBoiler

    problem, target = VtCentralBoiler(*settings).check(VT_HELPER)
    assert (None if problem is None else problem.value, target) == expected


async def test_vts_central_boiler_settings_come_from_the_newest_thermostat(
    hass: HomeAssistant,
) -> None:
    """I12: read from ``entry_infos`` of the newest thermostat VT handed over that gives them —
    its own settings merged over VT's central entry's; none handed over in this run, or none
    giving them: not known; none held now (VT reloading them), the last ones handed over in
    this run stand. Nothing of VT is written."""
    from custom_components.vtherm_smart_boiler.vtherm_link import VtCentralBoiler, vt_central_boiler

    assert vt_central_boiler(hass) is None
    register_thermostat(hass, FakeVtThermostat(entry_infos=None, unique_id="first"))  # type: ignore[arg-type]
    assert vt_central_boiler(hass) is None  # none gives them
    older = FakeVtThermostat(unique_id="older")
    register_thermostat(hass, older)
    assert vt_central_boiler(hass) == VtCentralBoiler(True, ON, OFF)
    unticked = vt_central_settings(use_central_boiler_feature=False)
    newer = FakeVtThermostat(entry_infos=unticked, unique_id="newer")
    register_thermostat(hass, newer)
    assert vt_central_boiler(hass) == VtCentralBoiler(False, ON, OFF)

    class Broken:
        unique_id = "broken"

        @property
        def entry_infos(self) -> dict:
            raise RuntimeError("VT's property failed")

    register_thermostat(hass, Broken())
    register_thermostat(hass, FakeVtThermostat(entry_infos=None, unique_id="none"))  # type: ignore[arg-type]
    assert vt_central_boiler(hass) == VtCentralBoiler(False, ON, OFF)  # passed over
    blank = FakeVtThermostat(
        entry_infos={"central_boiler_activation_service": "  ", "other": 1}, unique_id="blank"
    )
    register_thermostat(hass, blank)
    assert vt_central_boiler(hass) == VtCentralBoiler(False, None, None)
    for thermostat in list(hass.data["vtherm_smart_boiler_vt_thermostats"]):
        unregister_thermostat(hass, thermostat)
    assert vt_central_boiler(hass) == VtCentralBoiler(False, None, None)  # the last, this run
    hass.data.pop("vtherm_smart_boiler_vt_central_boiler")  # a new run
    assert vt_central_boiler(hass) is None


@pytest.mark.parametrize(
    ("data", "said"),
    [
        ({"central_boiler": True}, (True, None)),
        ({"central_boiler": False, "delayed_activation_sec": 30}, (True, None)),
        ({"delayed_activation_sec": 120}, (False, 120.0)),
        ({"delayed_activation_sec": 0}, None),
        ({"delayed_activation_sec": True}, None),
        ({"delayed_activation_sec": float("inf")}, None),
        ({"delayed_activation_sec": "60"}, None),
        ({}, None),
    ],
)
def test_vts_central_boiler_event_is_read(data: dict, said: tuple | None) -> None:
    """I12: VT's event — its command went out, or its activation delay starts, a positive
    number of seconds; anything else is not read."""
    from custom_components.vtherm_smart_boiler.vtherm_link import (
        VtBoilerEvent,
        read_central_boiler_event,
    )

    assert read_central_boiler_event(data) == (None if said is None else VtBoilerEvent(*said))


def test_vts_central_boiler_event_is_named_as_vtherm_api_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The name from ``vtherm_api``; where it lacks it, the name VT has always given it."""
    import sys

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        CENTRAL_BOILER_EVENT,
        central_boiler_event,
    )

    assert central_boiler_event() == CENTRAL_BOILER_EVENT
    monkeypatch.setitem(sys.modules, "vtherm_api.const", None)  # an import that fails
    assert central_boiler_event() == CENTRAL_BOILER_EVENT


async def test_a_relay_a_vt_zone_drives_or_of_the_gateway_is_found(hass: HomeAssistant) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        relay_of_boiler_interface,
        relay_used_by_zone,
    )

    registry = er.async_get(hass)
    zone = registry.async_get_or_create("climate", VT_PLATFORM, "room").entity_id
    vt = MockConfigEntry(domain=VT_PLATFORM, data={"underlying_entity_ids": ["switch.heater"]})
    vt.add_to_hass(hass)
    registry.async_update_entity(zone, config_entry_id=vt.entry_id)
    assert relay_used_by_zone(hass, "switch.heater")
    assert not relay_used_by_zone(hass, "switch.relay")
    gateway = registry.async_get_or_create("switch", "opentherm_gw", "ch").entity_id
    assert relay_of_boiler_interface(hass, gateway)
    assert relay_of_boiler_interface(hass, zone)  # a VT entity
    assert not relay_of_boiler_interface(hass, "switch.relay")  # not registered


async def test_a_zone_without_a_state_is_named_from_its_registry_entry(hass: HomeAssistant) -> None:
    """PB-80: a zone whose climate has no state yet at setup is named from its registry entry —
    the user's name, its own name, then its device's — before its entity ID, so its entities
    are not named "Boiler climate.x ..." until a reload. Negative: outside the registry, the
    entity ID; with a state, the state's name."""
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import zone_name

    registry = er.async_get(hass)
    named = registry.async_get_or_create("climate", VT_PLATFORM, "a", original_name="Living")
    assert zone_name(hass, named.entity_id) == "Living"
    registry.async_update_entity(named.entity_id, name="Salon")
    assert zone_name(hass, named.entity_id) == "Salon"
    source = MockConfigEntry(domain=VT_PLATFORM)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(VT_PLATFORM, "b")}, name="Bedroom"
    )
    by_device = registry.async_get_or_create(
        "climate", VT_PLATFORM, "b", device_id=device.id, has_entity_name=True
    )
    assert zone_name(hass, by_device.entity_id) == "Bedroom"
    assert zone_name(hass, "climate.not_registered") == "climate.not_registered"
    bare = registry.async_get_or_create("climate", VT_PLATFORM, "c")
    assert zone_name(hass, bare.entity_id) == bare.entity_id  # nothing to name it by
    hass.states.async_set(named.entity_id, "heat", {"friendly_name": "Living room"})
    assert zone_name(hass, named.entity_id) == "Living room"


class Runtime:
    """VT's thermostat as ``vtherm_api`` declares it (VT 10.6.5's values), with a duty cycle whose
    reading would act on the regulation — counted, so a test sees whether it was read."""

    def __init__(self, unique_id: str, **values: Any) -> None:
        self.unique_id = unique_id
        self.values = {
            "current_temperature": 19.46,
            "target_temperature": 21.0,
            "vtherm_hvac_mode": "heat",
            "hvac_action": "heating",
            "is_device_active": True,
            "last_temperature_measure": datetime(2026, 11, 24, 9, 0, tzinfo=dt_util.UTC),
            "is_overpowering_detected": True,
            "hvac_off_reason": None,
            "cycle_min": 10,
        } | values
        self.duty_reads = 0

    def __getattr__(self, name: str) -> Any:
        values = self.__dict__.get("values", {})
        if name not in values:
            raise AttributeError(name)
        value = values[name]
        if isinstance(value, Exception):
            raise value
        return value

    @property
    def on_percent(self) -> float:
        self.duty_reads += 1
        return 0.9


async def test_zone_values_come_through_vtherm_api(hass: HomeAssistant, zones: FakeZones) -> None:
    """The user's rule (2026-11-24): where VT has handed the thermostat to the plugin, the values
    ``vtherm_api`` declares come from it — the rest from the attributes, the duty cycle among
    them (its reading would act on SmartPI). Negative: without the thermostat, or with VT not
    showing it running, the attributes."""
    living = zones.add(
        "living",
        handed_over=False,
        current_temperature=20.0,
        temperature=20.0,
        hvac_action="idle",
        on_percent=0.3,
        valve_open_percent=30,
        specific_states={"is_device_active": False, "hvac_off_reason": "hvac_off_manual"},
        configuration={"cycle_min": 5},
    )
    link = VThermLink(hass, [living])
    assert link.zone(living).temperature == pytest.approx(20.0)
    assert link.zones_through_api() == []
    thermostat = Runtime("fake_living")
    register_thermostat(hass, thermostat)
    zone = link.zone(living)
    assert zone.temperature == pytest.approx(19.5)  # to a tenth, as the attributes show it
    assert zone.target == pytest.approx(21.0)
    assert (zone.heating_enabled, zone.calling, zone.device_active) == (True, True, True)
    assert zone.shedding is True
    assert zone.temperature_at == datetime(2026, 11, 24, 9, 0, tzinfo=dt_util.UTC).timestamp()
    assert zone.on_percent == pytest.approx(0.3)  # the attribute's
    assert zone.valve_open == pytest.approx(0.3)  # not in the API: the attribute's
    assert thermostat.duty_reads == 0
    assert link.zone_off_reason(living) is None  # the thermostat's: no reason
    assert link.zone_algorithm(living).cycle_min == 10
    assert link.zones_through_api() == [living]

    zones.set("living", state="unavailable", current_temperature=20.0)
    assert link.zone(living).temperature != pytest.approx(19.5)
    assert link.zones_through_api() == []
    zones.set("living", current_temperature=20.0, temperature=20.0)
    unregister_thermostat(hass, thermostat)
    assert link.zone(living).temperature == pytest.approx(20.0)
    assert link.zone_algorithm(living).cycle_min is None  # no cycle in these attributes


async def test_a_member_that_fails_or_is_missing_keeps_the_attribute(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """Negative: a member VT lacks, one whose property fails, or a method where ``vtherm_api``
    declares a property gives nothing — that field keeps the attribute's value, the others
    still come from the thermostat; another VT entity's thermostat is never taken."""
    living = zones.add(
        "living", handed_over=False, current_temperature=20.0, temperature=20.0, hvac_action="idle"
    )
    bedroom = zones.add("bedroom", handed_over=False, current_temperature=18.0, temperature=18.0)
    thermostat = Runtime(
        "fake_living",
        current_temperature=RuntimeError("VT failed"),
        hvac_action=lambda: "heating",
    )
    del thermostat.values["target_temperature"]
    register_thermostat(hass, thermostat)
    link = VThermLink(hass, [living, bedroom])
    zone = link.zone(living)
    assert zone.temperature == pytest.approx(20.0)
    assert zone.target == pytest.approx(20.0)
    assert zone.calling is False  # the attribute's "idle"
    assert zone.device_active is True  # still the thermostat's
    assert link.zone(bedroom).temperature == pytest.approx(18.0)
    assert link.zones_through_api() == [living]


async def test_the_newest_thermostat_handed_over_is_read(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """VT's reload hands over a new thermostat for the same unique ID: the newest is read, as
    VT's own ``get_feature_manager`` picks; one VT stopped is forgotten."""
    living = zones.add("living", current_temperature=20.0)
    old, new = Runtime("fake_living"), Runtime("fake_living", current_temperature=22.0)
    register_thermostat(hass, old)
    register_thermostat(hass, new)
    register_thermostat(hass, new)  # once only
    link = VThermLink(hass, [living])
    assert link.zone(living).temperature == pytest.approx(22.0)
    unregister_thermostat(hass, new)
    assert link.zone(living).temperature == pytest.approx(19.5)
