"""VT link: the rooms are the thermostats VT hands over and counts for its central boiler
(I12.7, I12.11), and capability detection."""

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

from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.vtherm_link import (
    VT_OLDEST,
    VThermLink,
    ZoneAlgorithm,
    any_handed_over,
    holds_thermostats,
    not_counted,
    register_thermostat,
    room_name,
    rooms,
    unregister_thermostat,
    vt_climates_registered,
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
    link = VThermLink(hass)
    states = {z.zone_id: z for z in link.zones()}
    assert set(states) == {living, bedroom}
    assert states[living].deficit == pytest.approx(1.5)
    assert states[living].valve_open == pytest.approx(0.8)
    assert states[living].calling is True
    assert states[living].reported_at is not None
    assert states[bedroom].heating_enabled is False
    missing = link.zone("climate.missing")
    assert missing.temperature is None
    assert missing.reported_at is None


async def test_the_rooms_are_the_thermostats_vts_central_boiler_counts(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.11: the rooms are the thermostats VT hands over whose ``entry_infos`` say its central
    boiler counts them (``used_by_controls_central_boiler``: only a clear true), sorted; the
    others it hands over are listed apart; one not handed over is neither. Each room is named by
    its thermostat's declared ``name``; one VT holds no thermostat for, by its entity ID."""
    assert not any_handed_over(hass) or holds_thermostats(hass)  # the stand-in, at most
    bedroom = zones.add("bedroom")
    living = zones.add("living")
    garage = zones.add("garage")
    zones.configure("garage", used_by_controls_central_boiler=False)
    odd = zones.add("odd")
    zones.configure("odd", used_by_controls_central_boiler="yes")
    late = zones.add("late", handed_over=False)
    assert rooms(hass) == sorted([bedroom, living])
    assert not_counted(hass) == sorted([garage, odd, zones.stand_in.entity_id])
    assert late not in rooms(hass) + not_counted(hass)
    link = VThermLink(hass)
    assert [z.zone_id for z in link.zones()] == link.rooms() == rooms(hass)  # nothing known before
    assert link.not_counted() == not_counted(hass)
    assert room_name(hass, living) == link.zone_name(living) == "fake living"
    assert room_name(hass, late) == late
    zones.thermostats["living"].name = ""
    assert room_name(hass, living) == living
    zones.configure("garage", used_by_controls_central_boiler=True)  # ticked in VT
    assert garage in rooms(hass)
    assert any_handed_over(hass)
    zones.withdraw()  # VT reloads them: none held now, handed over before in this run
    assert rooms(hass) == []
    assert not holds_thermostats(hass)
    assert any_handed_over(hass)


async def test_the_link_knows_its_rooms_while_vt_reloads_them(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.11, decision 3: a room VT stops — reloading it — stays a room of the link's, not
    known for a while, rather than gone; so does one the last run knew (``expect``) until VT
    hands it over. It goes once VT hands it over not counted, or once Home Assistant's registry
    no longer lists its entity; one never seen nor expected is none."""
    living, bedroom = zones.add("living"), zones.add("bedroom")
    link = VThermLink(hass)
    link.expect([living, "climate.last_run", "climate.gone"])
    er.async_get(hass).async_get_or_create(
        "climate", VT_PLATFORM, "last_run", suggested_object_id="last_run"
    )
    assert link.rooms() == sorted([bedroom, "climate.last_run", living])  # gone: no entity
    zones.withdraw()
    assert link.rooms() == sorted([bedroom, "climate.last_run", living])
    zones_now = {z.zone_id: z for z in link.zones()}
    assert zones_now[living] == ZoneState(living, started=False, room_sensor_lost=True)
    zones.hand_over()
    zones.configure("bedroom", used_by_controls_central_boiler=False)  # unticked in VT
    er.async_get(hass).async_remove("climate.last_run")
    assert link.rooms() == [living]
    assert VThermLink(hass).rooms() == [living]  # a new link knows what VT holds now


async def test_a_thermostat_whose_name_or_entity_cannot_be_read(hass: HomeAssistant) -> None:
    """Negative: a thermostat whose declared ``entity_id`` fails or is no text is no room nor
    counted apart; one whose ``name`` fails is named by its entity ID."""

    counted = {"used_by_controls_central_boiler": True}

    class Broken:
        entry_infos = counted

        @property
        def entity_id(self) -> str:
            raise RuntimeError("VT's property failed")

    class Nameless:
        entity_id = "climate.nameless"
        entry_infos = counted

        @property
        def name(self) -> str:
            raise RuntimeError("VT's property failed")

    register_thermostat(hass, Broken())
    register_thermostat(hass, type("Odd", (), {"entity_id": 3, "entry_infos": {}})())
    register_thermostat(hass, Nameless())
    assert rooms(hass) == ["climate.nameless"]
    assert not_counted(hass) == []
    assert room_name(hass, "climate.nameless") == "climate.nameless"


async def test_vts_climates_in_the_registry_tell_that_vt_has_thermostats(
    hass: HomeAssistant,
) -> None:
    """I12.11: Home Assistant's registry — no state of VT's — says whether VT has climates: a
    disabled one, or one of another integration or domain, does not count."""
    registry = er.async_get(hass)
    assert not vt_climates_registered(hass)
    registry.async_get_or_create("climate", "generic_thermostat", "hall")
    registry.async_get_or_create("select", VT_PLATFORM, "central_mode")
    off = registry.async_get_or_create(
        "climate", VT_PLATFORM, "off", disabled_by=er.RegistryEntryDisabler.USER
    )
    assert off.disabled_by is not None
    assert not vt_climates_registered(hass)
    registry.async_get_or_create("climate", VT_PLATFORM, "living")
    assert vt_climates_registered(hass)


async def test_a_zone_vt_has_not_handed_over_is_not_known(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.7: no attribute fallback — a zone whose thermostat VT started before the plugin
    registered is not known, whatever its climate shows: not started, no mode, never read."""
    late = zones.add("late", handed_over=False, hvac_action="heating", valve_open_percent=80)
    zone = VThermLink(hass).zone(late)
    assert zone == ZoneState(late, started=False, room_sensor_lost=True)
    assert not zone.is_known(dt_util.utcnow().timestamp(), None)


async def test_nothing_of_smartpi_is_read(hass: HomeAssistant, zones: FakeZones) -> None:
    """I12.9: SmartPI's diagnostic sensor, named in VT's ``specific_states``, is not read, nor
    its learning flag, nor VT's Auto-TPI keys; a SmartPI room is judged like any other."""
    living = zones.add(
        "living",
        specific_states={"regulation_diagnostics": "sensor.diag", "smartpi_learning_enabled": True},
    )
    zones.configure("living", proportional_function="smartpi")
    hass.states.async_set("sensor.diag", "bootstrap_hysteresis")
    link = VThermLink(hass)
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
    zone = VThermLink(hass).zone(living)
    assert zone.temperature == pytest.approx(20.0)
    assert zone.target == pytest.approx(21.0)


async def test_vts_central_mode_is_not_read(hass: HomeAssistant) -> None:
    """I12.11 (gap 12): VT's central mode is VT's to apply through the rooms' demand — the
    plugin no longer reads its select."""
    assert not hasattr(VThermLink(hass), "central_mode")


async def test_capabilities_without_vt(hass: HomeAssistant) -> None:
    link = VThermLink(hass)
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
    link = VThermLink(hass)
    await link.async_detect()
    for _ in range(5):
        assert link.capabilities().vtherm_api_version == VTHERM_API
    assert threads == [False]  # once, not in the loop's thread


async def test_zone_algorithm_from_entry_infos(hass: HomeAssistant, zones: FakeZones) -> None:
    """I12.7: a zone's settings from its thermostat's ``entry_infos`` (VT 10.6.5 ``const.py``)
    — whether VT's central boiler counts it, its type and its cycle; not known for a zone VT has
    not handed over, whatever its climate shows. A value of another kind tells nothing."""
    counted = zones.add("counted")
    zones.configure(
        "counted",
        used_by_controls_central_boiler=True,
        thermostat_type="thermostat_over_switch",
        cycle_min=5,
    )
    left_out = zones.add("left_out")
    zones.configure(
        "left_out", used_by_controls_central_boiler=False, thermostat_type="thermostat_over_valve"
    )
    odd = zones.add("odd")
    zones.configure("odd", used_by_controls_central_boiler="yes", thermostat_type=3, cycle_min=0)
    late = zones.add("late", handed_over=False, configuration={"is_used_by_central_boiler": True})
    link = VThermLink(hass)
    assert link.zone_algorithm(counted) == ZoneAlgorithm(True, "thermostat_over_switch", 5.0, True)
    assert link.zone_algorithm(counted).switches_on_off
    assert link.zone_algorithm(left_out).used_by_central_boiler is False
    assert not link.zone_algorithm(left_out).switches_on_off
    assert link.zone_algorithm(odd) == ZoneAlgorithm(known=True)
    assert link.zone_algorithm(late) == ZoneAlgorithm()
    assert link.zone_algorithm("climate.missing") == ZoneAlgorithm()
    zones.stand_in.entry_infos = None  # VT's settings cannot be read
    assert not link.zone_algorithm(counted).known


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
    assert not VThermLink(hass).capabilities().vt_loaded  # set up, but its entries failed
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert VThermLink(hass).capabilities().vt_loaded


async def test_a_rooms_thermometer_from_entry_infos_decides_its_trust(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12, decision 8: the room's thermometer is the sensor the thermostat's ``entry_infos``
    names (VT 10.6.5 ``temperature_sensor_entity_id``), the user's device: unavailable, unknown or
    gone, the room's temperature is not trusted — VT keeps its last view and still runs the zone
    on it. A steady thermometer stays fine, however long ago it changed."""
    living = zones.add("living", current_temperature=20.0, hvac_action="idle")
    thermometer = zones.thermostats["living"].thermometer
    link = VThermLink(hass)
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
    link = VThermLink(hass)
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
    link = VThermLink(hass)
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
    link = VThermLink(hass)
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


async def test_a_zones_underlying_entities_are_read_from_its_entry_infos(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.7: what a thermostat drives, from its ``entry_infos`` (VT 10.6.5
    ``underlying_entity_ids``). Negative: a zone VT has not handed over, or settings without the
    list, cannot be read — ``None``; items that are not entity IDs are left out."""
    from custom_components.vtherm_smart_boiler.vtherm_link import zone_underlying_entities

    living = zones.add("living")
    late = zones.add("late", handed_over=False)
    assert zone_underlying_entities(hass, "climate.not_registered") is None
    assert zone_underlying_entities(hass, living) is None  # no list
    zones.configure("living", underlying_entity_ids=["switch.valve", "", 7, None])
    zones.configure("late", underlying_entity_ids=["switch.valve"])
    assert zone_underlying_entities(hass, living) == ("switch.valve",)
    assert zone_underlying_entities(hass, late) is None  # not handed over
    zones.configure("living", underlying_entity_ids="switch.valve")
    assert zone_underlying_entities(hass, living) is None  # not a list
    zones.stop("living")
    assert zone_underlying_entities(hass, living) is None


async def test_each_rooms_devices_are_found_with_their_room(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I8.8c: the devices a circuit's form offers — each room's own, with the room, in the
    rooms' order; a room whose list cannot be read offers none; a device two rooms name stays
    the first's; a thermostat VT's central boiler does not count offers none (I12.11)."""
    from custom_components.vtherm_smart_boiler.vtherm_link import room_devices

    living, bedroom = zones.add("living"), zones.add("bedroom")
    zones.add("hall")  # no list: nothing to offer
    zones.add("garage")
    zones.configure("garage", used_by_controls_central_boiler=False, underlying_entity_ids=["s.g"])
    assert room_devices(hass) == {}
    zones.configure("living", underlying_entity_ids=["switch.radiator", "switch.loop"])
    zones.configure("bedroom", underlying_entity_ids=["switch.loop"])
    assert room_devices(hass) == {"switch.loop": bedroom, "switch.radiator": living}


async def test_only_climates_of_the_boilers_devices_count_as_its_thermostat(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """X5.19: an ``opentherm_gw`` climate, or a climate on a device that carries a boiler
    entity, among a zone's underlying entities (its ``entry_infos``). Negative: a switch of the
    gateway, a climate of another device, an underlying climate not registered, a zone VT has
    not handed over."""
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
        zones.configure(name, underlying_entity_ids=underlying)
        found[name] = zones_on_boiler_thermostat(hass, [zone], [flame])
    assert {name for name, zones_found in found.items() if zones_found} == {
        "gateway",
        "boiler_device",
    }
    zone = zones.entities["boiler_device"]
    assert zones_on_boiler_thermostat(hass, [zone], []) == []  # no boiler entity on that device
    late = zones.add("late", handed_over=False)
    zones.configure("late", underlying_entity_ids=[gateway])
    assert zones_on_boiler_thermostat(hass, [late], [flame]) == []


async def test_the_rooms_in_an_area_by_the_registry(hass: HomeAssistant, zones: FakeZones) -> None:
    """I8 (F2), I12.11: a circuit's area shortcut — the rooms whose entity, or else its device,
    Home Assistant's registries put in the area, in the rooms' order. Negative: a thermostat VT
    does not count, a room elsewhere, one outside the registry."""
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import rooms_in_area

    area = ar.async_get(hass).async_create("Ground floor")
    registry = er.async_get(hass)
    living, bedroom, garage = zones.add("living"), zones.add("bedroom"), zones.add("garage")
    zones.configure("garage", used_by_controls_central_boiler=False)
    for entity in (living, garage):
        registry.async_update_entity(entity, area_id=area.id)
    source = MockConfigEntry(domain=VT_PLATFORM)
    source.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=source.entry_id, identifiers={(VT_PLATFORM, "hall")}
    )
    dr.async_get(hass).async_update_device(device.id, area_id=area.id)
    hall = zones.add("hall")
    registry.async_update_entity(hall, device_id=device.id)
    register_thermostat(
        hass,
        type(
            "Unregistered",
            (),
            {"entity_id": "climate.unregistered", "entry_infos": zones.stand_in.entry_infos
             | {"used_by_controls_central_boiler": True}},
        )(),
    )  # fmt: skip
    assert rooms_in_area(hass, area.id) == [hall, living]
    assert bedroom not in rooms_in_area(hass, area.id)
    assert rooms_in_area(hass, "elsewhere") == []


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

    handed: list[Any] = []

    def hand(thermostat: Any) -> None:
        handed.append(thermostat)
        register_thermostat(hass, thermostat)

    assert vt_central_boiler(hass) is None
    hand(FakeVtThermostat(entry_infos=None, unique_id="first"))  # type: ignore[arg-type]
    assert vt_central_boiler(hass) is None  # none gives them
    hand(FakeVtThermostat(unique_id="older"))
    assert vt_central_boiler(hass) == VtCentralBoiler(True, ON, OFF)
    unticked = vt_central_settings(use_central_boiler_feature=False)
    hand(FakeVtThermostat(entry_infos=unticked, unique_id="newer"))
    assert vt_central_boiler(hass) == VtCentralBoiler(False, ON, OFF)

    class Broken:
        unique_id = "broken"

        @property
        def entry_infos(self) -> dict:
            raise RuntimeError("VT's property failed")

    hand(Broken())
    hand(FakeVtThermostat(entry_infos=None, unique_id="none"))  # type: ignore[arg-type]
    assert vt_central_boiler(hass) == VtCentralBoiler(False, ON, OFF)  # passed over
    hand(
        FakeVtThermostat(
            entry_infos={"central_boiler_activation_service": "  ", "other": 1}, unique_id="blank"
        )
    )
    assert vt_central_boiler(hass) == VtCentralBoiler(False, None, None)
    for thermostat in handed:
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


async def test_a_relay_a_vt_zone_drives_or_of_the_gateway_is_found(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """R2: a device any thermostat VT handed over lists in its ``entry_infos`` (I12.7) — a zone
    of the plugin's or not; a thermostat VT has not handed over is not seen."""
    from custom_components.vtherm_smart_boiler.vtherm_link import (
        relay_of_boiler_interface,
        relay_used_by_zone,
    )

    registry = er.async_get(hass)
    zone = zones.add("room")
    zones.configure("room", underlying_entity_ids=["switch.heater"])
    zones.add("late", handed_over=False)
    zones.configure("late", underlying_entity_ids=["switch.other_heater"])
    assert relay_used_by_zone(hass, "switch.heater")
    assert not relay_used_by_zone(hass, "switch.relay")
    assert not relay_used_by_zone(hass, "switch.other_heater")
    gateway = registry.async_get_or_create("switch", "opentherm_gw", "ch").entity_id
    assert relay_of_boiler_interface(hass, gateway)
    assert relay_of_boiler_interface(hass, zone)  # a VT entity
    assert not relay_of_boiler_interface(hass, "switch.relay")  # not registered


async def test_a_room_is_named_by_its_thermostat_not_by_vts_climate(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.11: a room's name is its thermostat's declared ``name`` — never its climate's state
    nor its registry entry, which are VT's entities."""
    living = zones.add("living")
    zones.thermostats["living"].name = "Salon"
    hass.states.async_set(living, "heat", {"friendly_name": "Living room"})
    er.async_get(hass).async_update_entity(living, name="Lounge")
    assert room_name(hass, living) == "Salon"


class Runtime:
    """VT's thermostat as ``vtherm_api`` declares it (VT 10.6.5's values), with a duty cycle whose
    reading would act on the regulation — counted, so a test sees whether it was read."""

    def __init__(self, entity_id: str, **values: Any) -> None:
        self.entity_id = entity_id
        self.values = {
            "current_temperature": 19.46,
            "target_temperature": 21.0,
            "vtherm_hvac_mode": "heat",
            "hvac_action": "heating",
            "is_device_active": True,
            "last_temperature_measure": datetime(2026, 11, 24, 9, 0, tzinfo=dt_util.UTC),
            "hvac_off_reason": None,
            "entry_infos": {"cycle_min": 10},
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


async def test_zone_values_come_through_vtherm_api_alone(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.7: where VT has handed the thermostat to the plugin, the zone is the thermostat's —
    its members, read now; the duty and valve only from VT's power hook (unknown until VT's
    first call), never its ``on_percent``, whose reading would act on SmartPI. Without the
    thermostat nothing of VT's climate stands in: not known."""
    living = zones.add(
        "living",
        handed_over=False,
        current_temperature=20.0,
        temperature=20.0,
        hvac_action="idle",
        on_percent=0.3,
        valve_open_percent=30,
        specific_states={"is_device_active": False, "hvac_off_reason": "hvac_off_manual"},
    )
    link = VThermLink(hass)
    assert link.zone(living).temperature is None
    thermostat = Runtime(living)
    register_thermostat(hass, thermostat)
    before = dt_util.utcnow().timestamp()
    zone = link.zone(living)
    assert zone.temperature == pytest.approx(19.5)  # to a tenth, as Home Assistant shows it
    assert zone.target == pytest.approx(21.0)
    assert (zone.heating_enabled, zone.calling, zone.device_active) == (True, True, True)
    assert zone.temperature_at == datetime(2026, 11, 24, 9, 0, tzinfo=dt_util.UTC).timestamp()
    assert (zone.on_percent, zone.valve_open) == (None, None)  # no power hook yet
    assert zone.started is False  # no ``refresh_state`` yet
    assert zone.reported_at is not None
    assert zone.reported_at >= before  # read now
    assert zone.window_open is False
    assert thermostat.duty_reads == 0
    assert link.zone_algorithm(living).cycle_min == 10
    unregister_thermostat(hass, thermostat)
    assert link.zone(living).temperature is None
    assert link.zone_algorithm(living).cycle_min is None


async def test_a_member_that_fails_or_is_missing_is_not_known(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """Negative: a member VT lacks, one whose property fails, or a method where ``vtherm_api``
    declares a property gives nothing — that field is not known, whatever VT's climate shows;
    the others still come from the thermostat; another VT entity's thermostat is never taken;
    one whose ``entity_id`` fails is passed over."""
    living = zones.add(
        "living", handed_over=False, current_temperature=20.0, temperature=20.0, hvac_action="idle"
    )
    bedroom = zones.add("bedroom", handed_over=False, current_temperature=18.0, temperature=18.0)
    thermostat = Runtime(
        living,
        current_temperature=RuntimeError("VT failed"),
        hvac_action=lambda: "heating",
        entry_infos=RuntimeError("VT failed"),
    )
    del thermostat.values["target_temperature"]
    register_thermostat(hass, thermostat)

    class NoEntity:
        @property
        def entity_id(self) -> str:
            raise RuntimeError("VT's property failed")

    register_thermostat(hass, NoEntity())
    link = VThermLink(hass)
    zone = link.zone(living)
    assert (zone.temperature, zone.target, zone.calling) == (None, None, None)
    assert zone.device_active is True  # still the thermostat's
    assert link.zone(bedroom).temperature is None
    assert link.zone_algorithm(living) == ZoneAlgorithm(known=False)


async def test_the_newest_thermostat_handed_over_is_read(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """VT's reload hands over a new thermostat for the same entity: the newest is read, as
    VT's own ``get_feature_manager`` picks; one VT stopped is forgotten."""
    living = zones.add("living", handed_over=False, current_temperature=20.0)
    old, new = Runtime(living), Runtime(living, current_temperature=22.0)
    register_thermostat(hass, old)
    register_thermostat(hass, new)
    register_thermostat(hass, new)  # once only
    link = VThermLink(hass)
    assert link.zone(living).temperature == pytest.approx(22.0)
    unregister_thermostat(hass, new)
    assert link.zone(living).temperature == pytest.approx(19.5)


async def test_vts_refresh_and_power_hook_tell_started_duty_and_valve(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """I12.7: the zone counts as started from VT's first ``refresh_state`` on the manager; its
    duty from VT's power hook — a switch's applied share; a valve's applied share is also its
    opening; a stop is 0 — and none of it is kept for a new thermostat VT hands over (its
    reload) nor once VT stops the thermostat. A notification that cannot be read changes
    nothing."""
    from custom_components.vtherm_smart_boiler.vtherm_link import (
        thermostat_power,
        thermostat_started,
    )

    from .harness import power_command

    living = zones.add("living", handed_over=False, on_percent=None)
    thermostat = Runtime(living)
    link = VThermLink(hass)
    thermostat_started(hass, thermostat)  # not handed over: nothing to note
    thermostat_power(hass, thermostat, power_command("switch.heater", "switch", 0.4))
    register_thermostat(hass, thermostat)
    zone = link.zone(living)
    assert (zone.started, zone.on_percent, zone.valve_open) == (False, None, None)
    thermostat_started(hass, thermostat)
    thermostat_power(hass, thermostat, power_command("switch.heater", "switch", 0.4))
    zone = link.zone(living)
    assert (zone.started, zone.on_percent, zone.valve_open) == (True, 0.4, None)
    assert zone.is_known(dt_util.utcnow().timestamp(), None)
    for kind in ("valve", "valve_regulation"):
        thermostat_power(hass, thermostat, power_command("number.valve", kind, 0.7))
        assert (link.zone(living).on_percent, link.zone(living).valve_open) == (0.7, 0.7)
    thermostat_power(hass, thermostat, power_command("number.valve", "valve", 0.7, stop=True))
    assert (link.zone(living).on_percent, link.zone(living).valve_open) == (0.0, 0.0)
    for bad in (1.5, -0.1, float("nan"), True, "0.5", None):
        command = replace(power_command("switch.heater", "switch", 0.4), applied_on_percent=bad)
        thermostat_power(hass, thermostat, command)
    thermostat_power(hass, thermostat, object())
    assert link.zone(living).on_percent == 0.0  # unchanged
    newer = Runtime(living)
    register_thermostat(hass, newer)  # VT reloaded it
    zone = link.zone(living)
    assert (zone.started, zone.on_percent) == (False, None)
    unregister_thermostat(hass, newer)
    unregister_thermostat(hass, thermostat)
    register_thermostat(hass, thermostat)  # handed over again: starts unknown
    assert (link.zone(living).started, link.zone(living).on_percent) == (False, None)
