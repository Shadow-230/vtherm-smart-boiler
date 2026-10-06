"""VT link: zones from VT climate entities, the central mode and capability detection."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.vtherm_smart_boiler.vtherm_attributes import CentralMode
from custom_components.vtherm_smart_boiler.vtherm_link import (
    VT_CENTRAL_SEEN,
    VT_FEATURE_MANAGERS_FROM,
    VThermLink,
    vt_climate_entities,
    vt_loads_feature_managers,
)

from .harness import VT_PLATFORM, FakeZones, ha_started


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


def vt_central_entry(
    hass: HomeAssistant,
    feature: bool | None,
    state: Any = None,
    *,
    sensor: bool = True,
    disabled: bool = False,
) -> tuple[Any, str | None]:
    """VT's central configuration entry — loaded unless ``state`` says otherwise — and the
    registry entry of its central-boiler sensor, as VT 10.4.0 leaves them; ``feature`` ``None``:
    the flag not in its data."""
    from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    data: dict[str, Any] = {"thermostat_type": "thermostat_central_config"}
    if feature is not None:
        data["use_central_boiler_feature"] = feature
    central = MockConfigEntry(
        domain="versatile_thermostat",
        data=data,
        state=ConfigEntryState.LOADED if state is None else state,
        disabled_by=ConfigEntryDisabler.USER if disabled else None,
    )
    central.add_to_hass(hass)
    if not sensor:
        return central, None
    entry = er.async_get(hass).async_get_or_create(
        "binary_sensor",
        VT_PLATFORM,
        "central_boiler_state",
        config_entry=central,
        disabled_by=er.RegistryEntryDisabler.CONFIG_ENTRY if disabled else None,
    )
    return central, entry.entity_id


def vt_boiler_shown(hass: HomeAssistant, entity_id: str, configured: bool) -> None:
    """VT's central-boiler sensor provided, as VT shows it while its central entry runs."""
    hass.states.async_set(entity_id, "off", {"is_central_boiler_configured": configured})


def stand_in(hass: HomeAssistant, entity_id: str, *, at_start: bool = True) -> None:
    """VT no longer provides the sensor (unloaded, reloading, or its feature unticked): Home
    Assistant writes the registry entry's stand-in, "unavailable" and restored — ``at_start``:
    at its start, before the run's start is taken (decision 9), else later in the run."""
    er.async_get(hass).async_get(entity_id).write_unavailable_state(hass)
    assert hass.states.get(entity_id).attributes.get("restored") is True
    if at_start:
        ha_started(hass)


async def test_vt_central_boiler_detection(hass: HomeAssistant) -> None:
    link = VThermLink(hass, [])
    assert link.vt_central_boiler_configured() is False  # no such entity at all
    _central, entity_id = vt_central_entry(hass, True)
    assert entity_id is not None
    vt_boiler_shown(hass, entity_id, False)
    assert link.vt_central_boiler_configured() is False
    # VT's own entity, provided, but saying nothing: VT's central boiler cannot be ruled out.
    for state in ("unavailable", "unknown"):
        hass.states.async_set(entity_id, state)
        assert link.vt_central_boiler_configured() is None
    hass.states.async_set(entity_id, "off")  # without the attribute
    assert link.vt_central_boiler_configured() is None
    vt_boiler_shown(hass, entity_id, True)
    assert link.vt_central_boiler_configured() is True


@pytest.mark.parametrize("feature", [False, None])
async def test_vt_central_boiler_switched_off_is_not_there(
    hass: HomeAssistant, feature: bool | None
) -> None:
    """H1: the user switched VT's central boiler off, as control asks, and Home Assistant was
    restarted since. VT sets its central entry up without the sensor, and Home Assistant keeps
    the old registry entry with a stand-in state for good: the feature is not there. Its flag
    missing from VT's data cannot say so: unknown, and control waits (X7)."""
    link = VThermLink(hass, [])
    _central, entity_id = vt_central_entry(hass, feature)
    assert entity_id is not None
    stand_in(hass, entity_id)
    assert link.vt_central_boiler_configured() is (False if feature is False else None)


async def test_a_disabled_vt_central_boiler_sensor_follows_the_feature(
    hass: HomeAssistant,
) -> None:
    """The sensor disabled by the user shows nothing: VT's own setting then decides, and while
    the feature is on, VT's central boiler counts as there — from then on until Home Assistant
    restarts (X7)."""
    registry = er.async_get(hass)
    link = VThermLink(hass, [])
    central, entity_id = vt_central_entry(hass, False)
    assert entity_id is not None
    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    assert hass.states.get(entity_id) is None
    assert link.vt_central_boiler_configured() is False
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: True})
    assert link.vt_central_boiler_configured() is True
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
    assert link.vt_central_boiler_configured() is True  # seen in this run


FEATURE = "use_central_boiler_feature"


async def test_a_disabled_vt_central_entry_does_not_block_for_ever(hass: HomeAssistant) -> None:
    """T-52 (P-20): VT's boiler sensor in the registry, its central entry disabled by the user —
    VT has none running: not configured, not "unknown" for ever. Once VT's central boiler was
    seen configured earlier in this run, it counts as there until Home Assistant restarts: VT's
    manager, kept in its API, may still switch the boiler."""
    link = VThermLink(hass, [])
    _central, entity_id = vt_central_entry(hass, True, disabled=True)
    assert entity_id is not None
    assert er.async_get(hass).async_get(entity_id).disabled
    assert link.vt_central_boiler_configured() is False
    assert not link.vt_central_entry_failed()
    # The latch set earlier in the run, by another look at VT's central boiler.
    other = VThermLink(hass, [])
    hass.data[VT_CENTRAL_SEEN] = True
    assert other.vt_central_boiler_configured() is True
    assert link.vt_central_boiler_configured() is True


@pytest.mark.parametrize(
    "state",
    ["setup_error", "setup_retry", "migration_error", "failed_unload"],
)
async def test_a_vt_central_entry_in_a_failed_setup_is_read_from_its_data(
    hass: HomeAssistant, state: str
) -> None:
    """P-20: VT's central entry stuck in a failed setup — VT's manager may still switch the
    boiler: its feature on (or its flag missing) cannot be ruled out, and waits; off in its data,
    no VT central boiler. The control step tells the user after ten minutes
    (``test_control.py``, ``test_a_vt_central_entry_in_setup_error_is_told_after_ten_minutes``)."""
    from homeassistant.config_entries import ConfigEntryState

    failed = ConfigEntryState(state)
    for feature, expected in ((True, None), (None, None), (False, False)):
        _central, entity_id = vt_central_entry(hass, feature, failed)
        assert entity_id is not None
        stand_in(hass, entity_id)
        link = VThermLink(hass, [])
        assert link.vt_central_boiler_configured() is expected, feature
        assert link.vt_central_entry_failed()
        for entry in hass.config_entries.async_entries("versatile_thermostat"):
            await hass.config_entries.async_remove(entry.entry_id)
        er.async_get(hass).async_remove(entity_id)
    assert VT_CENTRAL_SEEN not in hass.data  # nothing was seen configured


@pytest.mark.parametrize(
    "state", ["loaded", "setup_in_progress", "unload_in_progress", "not_loaded"]
)
@pytest.mark.parametrize(("feature", "expected"), [(False, False), (True, True), (None, None)])
async def test_a_reloading_vt_central_entry_is_read_from_its_data(
    hass: HomeAssistant, state: str, feature: bool | None, expected: bool | None
) -> None:
    """P-105: while VT sets its central entry up again (or Home Assistant starts), its sensor
    is a stand-in or gone: its stored setting answers — off, no blocker and no hand-back; on,
    VT's central boiler is there; the flag missing, unknown."""
    from homeassistant.config_entries import ConfigEntryState

    _central, entity_id = vt_central_entry(hass, feature, ConfigEntryState(state))
    assert entity_id is not None
    link = VThermLink(hass, [])
    stand_in(hass, entity_id)
    assert link.vt_central_boiler_configured() is expected
    hass.states.async_remove(entity_id)  # the stand-in not written yet
    assert link.vt_central_boiler_configured() is expected
    assert not link.vt_central_entry_failed()


async def test_vt_central_boiler_seen_once_blocks_until_the_restart(hass: HomeAssistant) -> None:
    """VT's central boiler seen configured once in this run: the user unticks it and VT reloads
    — still there, as VT's manager may switch the boiler until Home Assistant restarts (with or
    without its keep-alive). Kept in Home Assistant's data, not in the link: a new link (the
    plugin reloaded) sees it too. After a restart, a new Home Assistant: not there."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import async_test_home_assistant

    central, entity_id = vt_central_entry(hass, True)
    assert entity_id is not None
    vt_boiler_shown(hass, entity_id, True)
    assert VThermLink(hass, []).vt_central_boiler_configured() is True
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
    central.mock_state(hass, ConfigEntryState.SETUP_IN_PROGRESS)
    stand_in(hass, entity_id, at_start=False)
    central.mock_state(hass, ConfigEntryState.LOADED)
    assert VThermLink(hass, []).vt_central_boiler_configured() is True
    async with async_test_home_assistant() as restarted:
        _central, again = vt_central_entry(restarted, False)
        assert again is not None
        stand_in(restarted, again)
        assert VThermLink(restarted, []).vt_central_boiler_configured() is False
        await restarted.async_stop(force=True)


async def test_vt_central_entry_is_read_without_its_sensor_in_the_registry(
    hass: HomeAssistant,
) -> None:
    """X7 (the cautious reading): VT's central boiler just ticked — VT has not registered its
    sensor yet — or an older VT whose sensor has another ID: VT's central entry says so."""
    link = VThermLink(hass, [])
    vt_central_entry(hass, True, sensor=False)
    assert link.vt_central_boiler_configured() is True


@pytest.mark.parametrize("feature", [False, None])
async def test_without_its_sensor_a_vt_central_entry_off_or_silent_is_not_there(
    hass: HomeAssistant, feature: bool | None
) -> None:
    """Negative: without the sensor in the registry, only a clear "on" in VT's central entry
    counts; off, or its flag not there — as in VT's thermostats' entries — is no VT central
    boiler, as before. A central entry in a failed setup with its feature on cannot be ruled
    out."""
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    link = VThermLink(hass, [])
    MockConfigEntry(
        domain="versatile_thermostat", data={"thermostat_type": "thermostat_over_switch"}
    ).add_to_hass(hass)
    assert link.vt_central_boiler_configured() is False
    central, _none = vt_central_entry(hass, feature, sensor=False)
    assert link.vt_central_boiler_configured() is False
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: True})
    central.mock_state(hass, ConfigEntryState.SETUP_ERROR)
    assert link.vt_central_boiler_configured() is None
    assert link.vt_central_entry_failed()
    central.mock_state(hass, ConfigEntryState.LOADED)
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
    assert link.vt_central_boiler_configured() is False


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("9.3.3", False),
        ("10.0.2", False),
        ("10.1.0", False),  # takes the registration, never creates the manager (Q3.1)
        ("10.2.0.beta1", False),  # a beta is not a supported install: under-claimed
        ("10.2.0", True),
        ("10.4.0", True),
        ("10.5.0.beta2", True),
        ("10.10.0", True),
        (None, None),  # unknown: capability detection decides
        ("not a version", None),
        ("", None),
    ],
)
def test_vt_versions_that_load_external_feature_managers(
    version: str | None, expected: bool | None
) -> None:
    """P-60 (Q3.1, provisional, K4): VT loads outside feature managers from 10.2.0 on."""
    assert vt_loads_feature_managers(version) is expected
    assert VT_FEATURE_MANAGERS_FROM == "10.2.0"


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


# --- X8: moving over from VT's central boiler (R14), read only -------------------------------


@pytest.mark.parametrize(
    ("raw", "parsed"),
    [
        ("switch.r/switch.turn_on", ("switch.r", "switch", "turn_on", None, None)),
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


@pytest.mark.parametrize(
    ("on", "off", "relay"),
    [
        ("switch.r/switch.turn_on", "switch.r/switch.turn_off", "switch.r"),
        (
            "climate.b/climate.set_hvac_mode/hvac_mode:heat",
            "climate.b/climate.set_hvac_mode/hvac_mode:off",
            "climate.b",
        ),
        ("switch.r/switch.turn_on", "switch.other/switch.turn_off", None),  # two entities
        ("switch.r/switch.turn_off", "switch.r/switch.turn_on", None),  # reversed
        ("switch.r/switch.toggle", "switch.r/switch.toggle", None),
        ("switch.r/switch.turn_on/brightness:5", "switch.r/switch.turn_off", None),
        (
            "climate.b/climate.set_hvac_mode/hvac_mode:auto",
            "climate.b/climate.set_hvac_mode/hvac_mode:off",
            None,
        ),
        (
            "climate.b/climate.set_temperature/temperature:60",
            "climate.b/climate.set_temperature/temperature:10",
            None,
        ),
        ("input_boolean.x/input_boolean.turn_on", "input_boolean.x/input_boolean.turn_off", None),
        ("script.on/script.turn_on", "script.off/script.turn_on", None),
    ],
)
def test_only_a_switch_or_boiler_thermostat_pair_names_the_relay(
    on: str, off: str, relay: str | None
) -> None:
    from custom_components.vtherm_smart_boiler.vtherm_link import (
        parse_vt_command,
        relay_from_vt_commands,
    )

    assert relay_from_vt_commands(parse_vt_command(on), parse_vt_command(off)) == relay


async def test_vt_central_boiler_settings_are_read_without_writing(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """R14: VT's central entry and threshold numbers read — its commands, delay and keep-alive,
    the thresholds as VT used them — and nothing written: the entry's data and the numbers stay
    as they were. Without VT's central entry, nothing to read."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        VtCommands,
        vt_central_boiler_settings,
    )

    assert vt_central_boiler_settings(hass, []) is None
    entry = MockConfigEntry(
        domain=VT_PLATFORM,
        data={
            "thermostat_type": "thermostat_central_config",
            "use_central_boiler_feature": True,
            "central_boiler_activation_service": "switch.r/switch.turn_on",
            "central_boiler_deactivation_service": "switch.r/switch.turn_off",
            "central_boiler_activation_delay_sec": 30,
            "keep_alive_boiler_delay_sec": 60,
        },
    )
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    power = registry.async_get_or_create("number", VT_PLATFORM, "boiler_power_activation_threshold")
    hass.states.async_set(power.entity_id, "3.9", {"unit_of_measurement": "kW"})
    data = dict(entry.data)
    before = hass.states.get(power.entity_id)
    settings = vt_central_boiler_settings(hass, [zones.add("living")])
    assert settings is not None
    assert settings.configured
    assert settings.commands is VtCommands.RELAY
    assert settings.relay == "switch.r"
    assert settings.activation_delay_s == 30.0
    assert settings.repeat_s == 60.0
    assert settings.power_threshold_kw == 3.0
    assert settings.count_threshold is None  # no count number
    assert dict(entry.data) == data
    assert hass.states.get(power.entity_id) == before
    # Unticked: VT deleted its commands — nothing to name the relay, the delay still kept.
    hass.config_entries.async_update_entry(
        entry,
        data={"thermostat_type": "thermostat_central_config", "keep_alive_boiler_delay_sec": 0},
    )
    settings = vt_central_boiler_settings(hass, [])
    assert settings is not None
    assert settings.commands is VtCommands.NONE
    assert not settings.exists
    assert settings.relay is None
    assert settings.repeat_s is None
    assert settings.keep_alive_s is None
    # A power threshold in another unit is not converted.
    hass.states.async_set(power.entity_id, "3000", {"unit_of_measurement": "BTU/h"})
    settings = vt_central_boiler_settings(hass, [])
    assert settings is not None
    assert settings.power_threshold_kw is None


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


# --- PB-08 (decision 9 of plan 0.2.3): VT's central boiler unticked while nobody watched -------


@pytest.mark.parametrize("sensor", ["stand_in", "deleted"])
async def test_an_untick_no_entry_watched_latches_until_the_restart(
    hass: HomeAssistant, freezer: Any, sensor: str
) -> None:
    """PB-08: VT's central boiler ticked and unticked again in this run before any entry of the
    plugin watched VT — VT's manager may still switch the boiler until Home Assistant restarts:
    there until the restart. Its sensor's stand-in written in this run says so at any look;
    with the sensor's registry entry deleted, VT's central entry changed in this run does, at
    the watch's start."""
    central, entity_id = vt_central_entry(hass, False)
    assert entity_id is not None
    stand_in(hass, entity_id)  # from before this run: Home Assistant started after it
    freezer.tick(60)
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: True})
    vt_boiler_shown(hass, entity_id, True)  # nobody looks
    freezer.tick(60)
    hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
    stand_in(hass, entity_id, at_start=False)
    if sensor == "deleted":
        er.async_get(hass).async_remove(entity_id)
        hass.states.async_remove(entity_id)
    # Before any watch: the stand-in tells; without the sensor, nothing does yet.
    assert VThermLink(hass, []).vt_central_boiler_configured() is (sensor == "stand_in")
    freezer.tick(60)
    link = VThermLink(hass, [])
    link.watch_vt_central()
    assert link.vt_central_boiler_configured() is True
    link.stop_watching_vt_central()
    assert VThermLink(hass, []).vt_central_boiler_configured() is True  # the plugin reloaded
    freezer.tick(60)
    ha_started(hass)  # the restart
    after = VThermLink(hass, [])
    after.watch_vt_central()
    assert after.vt_central_boiler_configured() is False


@pytest.mark.parametrize("vt", ["absent", "unchanged", "changed_while_watched"])
async def test_no_latch_without_a_change_no_entry_watched(
    hass: HomeAssistant, freezer: Any, vt: str
) -> None:
    """Negatives: VT absent, or its central entry and its sensor's stand-in from before this
    run — nothing latches at the watch. A change while an entry of the plugin watched (an
    option VT's form saves) latches nothing — nor for a second entry's watch, nor the next one;
    a change once none watched does, at the next watch."""
    central = None
    if vt == "absent":
        ha_started(hass)
    else:
        central, entity_id = vt_central_entry(hass, False)
        assert entity_id is not None
        stand_in(hass, entity_id)
    freezer.tick(60)
    link = VThermLink(hass, [])
    link.watch_vt_central()
    link.watch_vt_central()  # once per link
    assert link.vt_central_boiler_configured() is False
    if central is not None and vt == "changed_while_watched":
        freezer.tick(60)
        hass.config_entries.async_update_entry(central, data={**central.data, "other": 1})
        second = VThermLink(hass, [])
        second.watch_vt_central()  # beside a watching one: watched all along
        assert second.vt_central_boiler_configured() is False
        second.stop_watching_vt_central()
        second.stop_watching_vt_central()  # once per link
        link.stop_watching_vt_central()
        again = VThermLink(hass, [])
        again.watch_vt_central()
        assert again.vt_central_boiler_configured() is False
        again.stop_watching_vt_central()
        freezer.tick(60)
        hass.config_entries.async_update_entry(central, data={**central.data, "other": 2})
        freezer.tick(60)
        last = VThermLink(hass, [])
        last.watch_vt_central()
        assert last.vt_central_boiler_configured() is True
        return
    assert VT_CENTRAL_SEEN not in hass.data


async def test_while_home_assistant_starts_the_watch_begins_before_any_change(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The plugin set up while Home Assistant starts — its usual start — watches before Home
    Assistant has started: VT's migration of its central entry at its setup and the stand-ins
    Home Assistant writes at its start latch nothing. Its start is taken once it has started; a
    stand-in written after it latches (decision 9)."""
    from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
    from homeassistant.core import CoreState

    from custom_components.vtherm_smart_boiler.vtherm_link import VT_RUN, vt_run

    hass.set_state(CoreState.not_running)
    try:
        assert vt_run(hass).started is None
        central, entity_id = vt_central_entry(hass, False)  # VT set up, its entry migrated
        assert entity_id is not None
        stand_in(hass, entity_id, at_start=False)  # Home Assistant's own, at its start
        link = VThermLink(hass, [])
        link.watch_vt_central()
        assert link.vt_central_boiler_configured() is False  # not judged before the start
        freezer.tick(5)
        hass.set_state(CoreState.running)
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
        await hass.async_block_till_done()
        assert hass.data[VT_RUN].started is not None
        assert link.vt_central_boiler_configured() is False
        freezer.tick(60)
        hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: True})
        vt_boiler_shown(hass, entity_id, False)  # on, no commands: VT's sensor provided
        freezer.tick(60)
        hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
        stand_in(hass, entity_id, at_start=False)
        assert link.vt_central_boiler_configured() is True
    finally:
        hass.set_state(CoreState.running)


@pytest.mark.parametrize("recorder", ["none", "before", "after", "broken"])
async def test_a_plugin_first_set_up_after_the_start_takes_the_recorders(
    hass: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch, recorder: str
) -> None:
    """The plugin first set up once Home Assistant runs — an entry added or enabled — has not
    seen the start: the recorder's (before VT's setup) stands for it. VT's central entry changed
    before it — no latch; after, or no recorder to say, or one that does not — a doubt: latched
    until the restart."""
    import homeassistant.helpers.recorder as ha_recorder

    from custom_components.vtherm_smart_boiler.vtherm_link import RUN_START_UNKNOWN, vt_run

    vt_central_entry(hass, False, sensor=False)
    freezer.tick(60)
    began = dt_util.utcnow()

    class Runs:
        recording_start: Any = began if recorder != "broken" else "soon"

    class Instance:
        recorder_runs_manager = Runs()

    if recorder != "none":
        hass.config.components.add("recorder")
        monkeypatch.setattr(ha_recorder, "get_instance", lambda _hass: Instance())
    if recorder == "after":
        Runs.recording_start = began - timedelta(minutes=5)
    run = vt_run(hass)
    expected = began if recorder in ("before", "after") else RUN_START_UNKNOWN
    if recorder == "after":
        expected = began - timedelta(minutes=5)
    assert run.started == expected
    link = VThermLink(hass, [])
    link.watch_vt_central()
    assert link.vt_central_boiler_configured() is (recorder != "before")


@pytest.mark.parametrize("case", ["at_start", "untick_in_the_run", "start_unknown"])
async def test_a_stand_in_from_home_assistants_start_does_not_latch_a_later_setup(
    hass: HomeAssistant, freezer: Any, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """M1 of the part-2 check: VT's central boiler unticked and Home Assistant restarted in an
    earlier run; Home Assistant writes the stand-in of VT's sensor at its start, after the
    recorder began; a day later the plugin's entry is added. VT's central entry unchanged since
    the run began — VT never provided the sensor in this run: no latch. Unticked in this run —
    VT provided it, its manager perhaps still switching: latched. No start known — a doubt:
    latched (decision 9)."""
    import homeassistant.helpers.recorder as ha_recorder

    from custom_components.vtherm_smart_boiler.vtherm_link import vt_run

    central, entity_id = vt_central_entry(hass, case == "untick_in_the_run")
    assert entity_id is not None  # its sensor's registry entry kept
    freezer.tick(60)
    began = dt_util.utcnow()  # the recorder's start, early in the bootstrap

    class Runs:
        recording_start: Any = began

    class Instance:
        recorder_runs_manager = Runs()

    if case != "start_unknown":
        hass.config.components.add("recorder")
        monkeypatch.setattr(ha_recorder, "get_instance", lambda _hass: Instance())
    freezer.tick(10)
    if case == "untick_in_the_run":
        vt_boiler_shown(hass, entity_id, False)  # provided in this run
        freezer.tick(3600)
        hass.config_entries.async_update_entry(central, data={**central.data, FEATURE: False})
    else:
        object.__setattr__(central, "modified_at", began - timedelta(days=2))  # an earlier run
    er.async_get(hass).async_get(entity_id).write_unavailable_state(hass)
    freezer.tick(86400)  # a day later the plugin's entry is added
    vt_run(hass)
    link = VThermLink(hass, [])
    assert link.vt_central_boiler_configured() is (case != "at_start")
    link.watch_vt_central()
    assert link.vt_central_boiler_configured() is (case != "at_start")


async def test_the_recorders_start_unreadable_counts_as_unknown(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative: a recorder whose instance cannot be read gives no start."""
    import homeassistant.helpers.recorder as ha_recorder

    from custom_components.vtherm_smart_boiler.vtherm_link import RUN_START_UNKNOWN, vt_run

    def broken(_hass: HomeAssistant) -> Any:
        raise KeyError("recorder_instance")

    hass.config.components.add("recorder")
    monkeypatch.setattr(ha_recorder, "get_instance", broken)
    assert vt_run(hass).started == RUN_START_UNKNOWN


@pytest.mark.parametrize("modified", [None, "naive"])
async def test_a_central_entry_without_a_change_time_counts_as_changed(
    hass: HomeAssistant, modified: str | None
) -> None:
    """Negative: VT's central entry without a change time, or one without a time zone — a
    doubt: latched until the restart."""
    central, _none = vt_central_entry(hass, False, sensor=False)
    ha_started(hass)
    value = None if modified is None else datetime(2026, 1, 1)
    object.__setattr__(central, "modified_at", value)
    link = VThermLink(hass, [])
    link.watch_vt_central()
    assert link.vt_central_boiler_configured() is True


async def test_a_left_behind_or_disabled_vt_sensor_is_no_stand_in_of_this_run(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Negatives of decision 9's stand-in: VT's sensor left in the registry by a VT entry that
    is gone — no VT central boiler, a stand-in written in this run or not (X7); a sensor the
    user disabled whose state still shows — no stand-in, VT's entry says "off": not there."""
    ha_started(hass)
    freezer.tick(60)
    registry = er.async_get(hass)
    orphan = registry.async_get_or_create("binary_sensor", VT_PLATFORM, "central_boiler_state")
    orphan.write_unavailable_state(hass)
    link = VThermLink(hass, [])
    assert link.vt_central_boiler_configured() is False
    registry.async_remove(orphan.entity_id)
    hass.states.async_remove(orphan.entity_id)
    _central, entity_id = vt_central_entry(hass, False)
    assert entity_id is not None
    registry.async_update_entity(entity_id, disabled_by=er.RegistryEntryDisabler.USER)
    vt_boiler_shown(hass, entity_id, True)
    assert link.vt_central_boiler_configured() is False
    assert VT_CENTRAL_SEEN not in hass.data
