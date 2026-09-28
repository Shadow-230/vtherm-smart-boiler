"""VT link: zones from VT climate entities, the central mode and capability detection."""

from __future__ import annotations

from typing import Any

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
    link = VThermLink(hass, [])
    await link.async_detect()
    capabilities = link.capabilities()
    assert capabilities.vt_loaded is False
    assert capabilities.vt_version is None
    assert capabilities.vtherm_api_version == "0.5.0"
    assert capabilities.smartpi_loaded is False


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
        assert link.capabilities().vtherm_api_version == "0.5.0"
    assert threads == [False]  # once, not in the loop's thread


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


def vt_central_entry(hass: HomeAssistant, feature: bool | None) -> tuple[Any, str]:
    """VT's central configuration entry, loaded, and the registry entry of its central-boiler
    sensor, as VT 10.4.0 leaves them."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    data = {} if feature is None else {"use_central_boiler_feature": feature}
    central = MockConfigEntry(
        domain="versatile_thermostat", data=data, state=ConfigEntryState.LOADED
    )
    central.add_to_hass(hass)
    entry = er.async_get(hass).async_get_or_create(
        "binary_sensor", VT_PLATFORM, "central_boiler_state", config_entry=central
    )
    return central, entry.entity_id


async def test_vt_central_boiler_detection(hass: HomeAssistant) -> None:
    from homeassistant.config_entries import ConfigEntryState

    link = VThermLink(hass, [])
    assert link.vt_central_boiler_configured() is False  # no such entity at all
    central, entity_id = vt_central_entry(hass, True)
    hass.states.async_set(entity_id, "off", {"is_central_boiler_configured": False})
    assert link.vt_central_boiler_configured() is False
    hass.states.async_set(entity_id, "on", {"is_central_boiler_configured": True})
    assert link.vt_central_boiler_configured() is True
    # VT's own central boiler cannot be ruled out while its entity is away and VT's central
    # entry is being set up again (a reload, a late start): unknown, and control waits.
    central.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    for state in ("unavailable", "unknown"):
        hass.states.async_set(entity_id, state)
        assert link.vt_central_boiler_configured() is None
    er.async_get(hass).async_get(entity_id).write_unavailable_state(hass)
    assert link.vt_central_boiler_configured() is None
    hass.states.async_remove(entity_id)
    assert link.vt_central_boiler_configured() is None


@pytest.mark.parametrize("feature", [False, None])
async def test_vt_central_boiler_switched_off_is_not_there(
    hass: HomeAssistant, feature: bool | None
) -> None:
    """H1: the user switched VT's central boiler off, as control asks. VT sets its central
    entry up again without the sensor, and Home Assistant keeps the old registry entry with a
    stand-in state for good: the feature is not there — not "unknown", which would keep
    control waiting for ever."""
    link = VThermLink(hass, [])
    _central, entity_id = vt_central_entry(hass, feature)
    er.async_get(hass).async_get(entity_id).write_unavailable_state(hass)  # the stand-in
    assert hass.states.get(entity_id).attributes.get("restored") is True
    assert link.vt_central_boiler_configured() is False


async def test_a_disabled_vt_central_boiler_sensor_follows_the_feature(
    hass: HomeAssistant,
) -> None:
    """The sensor disabled by the user shows nothing: VT's own setting then decides, and while
    the feature is on, VT's central boiler still counts as there."""
    registry = er.async_get(hass)
    link = VThermLink(hass, [])
    central, entity_id = vt_central_entry(hass, True)
    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    assert hass.states.get(entity_id) is None
    assert link.vt_central_boiler_configured() is True
    hass.config_entries.async_update_entry(central, data={"use_central_boiler_feature": False})
    assert link.vt_central_boiler_configured() is False


async def test_vt_is_loaded_only_with_a_loaded_entry(hass: HomeAssistant) -> None:
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    hass.config.components.add("versatile_thermostat")
    entry = MockConfigEntry(domain="versatile_thermostat", state=ConfigEntryState.SETUP_ERROR)
    entry.add_to_hass(hass)
    assert not VThermLink(hass, []).capabilities().vt_loaded  # set up, but its entries failed
    entry.mock_state(hass, ConfigEntryState.LOADED)
    assert VThermLink(hass, []).capabilities().vt_loaded


async def test_a_zone_whose_room_sensor_is_lost_says_so(hass: HomeAssistant) -> None:
    """R6, T2: VT keeps the last temperature of a room sensor that went away, and its own
    safety check sleeps while the zone is off. The sensor VT reads — in VT's entry — tells: gone,
    unavailable or unknown, the zone's temperature is no measurement now. A steady sensor
    stays fine, however long ago it last changed; history is VT's own view."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    vt = MockConfigEntry(
        domain="versatile_thermostat", data={"temperature_sensor_entity_id": "sensor.room"}
    )
    vt.add_to_hass(hass)
    climate = er.async_get(hass).async_get_or_create(
        "climate", VT_PLATFORM, "room", suggested_object_id="room", config_entry=vt
    )
    hass.states.async_set(
        climate.entity_id, "heat", {"current_temperature": 20.0, "hvac_action": "idle"}
    )
    link = VThermLink(hass, [climate.entity_id])
    hass.states.async_set("sensor.room", "20.0")
    assert link.zone(climate.entity_id).room_sensor_lost is False
    for state in ("unavailable", "unknown"):
        hass.states.async_set("sensor.room", state)
        zone = link.zone(climate.entity_id)
        assert zone.room_sensor_lost is True
        assert zone.temperature == 20.0  # VT's view is kept: VT still runs the zone on it
    hass.states.async_remove("sensor.room")
    assert link.zone(climate.entity_id).room_sensor_lost is True
    recorded = link.zone_from_state(climate.entity_id, hass.states.get(climate.entity_id))
    assert recorded.room_sensor_lost is False  # a past state: its sensor then is not known
    hass.config_entries.async_update_entry(vt, data={})  # a VT that keeps it elsewhere
    assert link.zone(climate.entity_id).room_sensor_lost is False


# --- X4, decision 5: VT's activation delay, from its central entry -----------------------------


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ({"central_boiler_activation_delay_sec": 120}, 120.0),
        ({"central_boiler_activation_delay_sec": 0}, 0.0),
        ({"central_boiler_activation_delay_sec": 600.0}, 600.0),
        ({}, None),  # never saved
        ({"central_boiler_activation_delay_sec": "120"}, None),  # not a number
        ({"central_boiler_activation_delay_sec": True}, None),
        ({"central_boiler_activation_delay_sec": 900}, None),  # outside VT's own range
        ({"central_boiler_activation_delay_sec": -10}, None),
        ({"central_boiler_activation_delay_sec": float("nan")}, None),
    ],
)
async def test_vts_activation_delay_is_read_from_its_central_entry(
    hass: HomeAssistant, data: dict[str, Any], expected: float | None
) -> None:
    """VT keeps the delay in its central entry's data, also once its central boiler is
    unticked (VT 10.4.0 ``config_flow.py``); the value within VT's 0–600 s, else nothing. A
    thermostat's entry is not the central one."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(
        domain=VT_PLATFORM,
        data={
            "thermostat_type": "thermostat_over_switch",
            "central_boiler_activation_delay_sec": 50,
        },
    ).add_to_hass(hass)
    MockConfigEntry(
        domain=VT_PLATFORM, data={"thermostat_type": "thermostat_central_config"} | data
    ).add_to_hass(hass)
    assert VThermLink(hass, []).vt_central_activation_delay() == expected


async def test_without_vt_there_is_no_activation_delay_to_offer(hass: HomeAssistant) -> None:
    assert VThermLink(hass, []).vt_central_activation_delay() is None


# --- X5: a zone's underlying entities (X5.19), zones of another kind (X5.7) ---------------------


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
