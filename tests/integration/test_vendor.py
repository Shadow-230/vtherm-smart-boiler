"""The vendored VT integration loads in the in-process Home Assistant, and the plugin works with it
(no SmartPI: the plugin reads nothing of it since I12.9)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry
from vtherm_api.vtherm_api import VThermAPI

from custom_components.vtherm_smart_boiler.const import DOMAIN, control_store_key
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .conftest import requires_vendor
from .harness import FakeBoiler

pytestmark = [requires_vendor, pytest.mark.usefixtures("enable_custom_integrations")]


# The pinned VT is 10.6.5 (I12.6), whose manifest says 10.6.4 (the tag's ``manifest.json``).
async def test_vendored_integration_loads(hass: HomeAssistant) -> None:
    integration = await async_get_integration(hass, "versatile_thermostat")
    version = "10.6.4"
    # CI's early warning runs the newest releases instead of the pinned ones (VENDOR_VERSIONS_PINNED
    # "0"): there only the loading is checked.
    if os.environ.get("VENDOR_VERSIONS_PINNED", "1") != "0":
        assert str(integration.version) == version
    assert await integration.async_get_component() is not None


LIVING = "climate.living"


def vt_thermostat(current: bool = False, **changes: Any) -> MockConfigEntry:
    """A VT over_switch thermostat in the entry format of VT 10.4.0; ``changes`` replace its
    data's keys. ``current``: stored at VT's own entry version, which VT does not migrate — its
    migration from an older version switches Auto-TPI off. VT's central boiler counts it ("Used
    by central boiler" ticked), so it is a room of the plugin's (I12.11)."""
    from custom_components.versatile_thermostat import const as vt

    version = (vt.CONFIG_VERSION, vt.CONFIG_MINOR_VERSION) if current else (1, 1)
    return MockConfigEntry(
        version=version[0],
        minor_version=version[1],
        domain=vt.DOMAIN,
        title="Living",
        unique_id="living",
        data={
            vt.CONF_THERMOSTAT_TYPE: vt.CONF_THERMOSTAT_SWITCH,
            vt.CONF_NAME: "Living",
            vt.CONF_TEMP_SENSOR: "sensor.living_temperature",
            vt.CONF_EXTERNAL_TEMP_SENSOR: "sensor.outdoor_temperature",
            vt.CONF_CYCLE_MIN: 5,
            vt.CONF_TEMP_MIN: 7.0,
            vt.CONF_TEMP_MAX: 30.0,
            vt.CONF_STEP_TEMPERATURE: 0.1,
            vt.CONF_UNDERLYING_LIST: ["input_boolean.living_valve"],
            vt.CONF_HEATER_KEEP_ALIVE: 0,
            vt.CONF_PROP_FUNCTION: vt.PROPORTIONAL_FUNCTION_TPI,
            vt.CONF_AC_MODE: False,
            vt.CONF_INVERSE_SWITCH: False,
            vt.CONF_TPI_COEF_INT: 0.3,
            vt.CONF_TPI_COEF_EXT: 0.01,
            vt.CONF_MINIMAL_ACTIVATION_DELAY: 10,
            vt.CONF_MINIMAL_DEACTIVATION_DELAY: 0,
            vt.CONF_TPI_THRESHOLD_LOW: 0.0,
            vt.CONF_TPI_THRESHOLD_HIGH: 0.0,
            vt.CONF_AUTO_TPI_MODE: False,
            vt.CONF_SAFETY_DELAY_MIN: 5,
            vt.CONF_SAFETY_MIN_ON_PERCENT: 0.4,
            vt.CONF_SAFETY_DEFAULT_ON_PERCENT: 0.3,
            vt.CONF_USED_BY_CENTRAL_BOILER: True,
        }
        | changes,
    )


async def room_and_boiler(hass: HomeAssistant) -> MockConfigEntry:
    """The thermostat's sensors and switch, and the plugin's entry for a boiler with that zone."""
    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hass.states.async_set("sensor.living_temperature", "19.0", celsius)
    hass.states.async_set("sensor.outdoor_temperature", "5.0", celsius)
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"living_valve": {}}}
    )
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    return MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": boiler.mapping(),
            "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0},
        },
    )


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def heat_to(hass: HomeAssistant, target: float, zone: str = LIVING) -> None:
    for service, data in (
        ("set_hvac_mode", {"hvac_mode": "heat"}),
        ("set_temperature", {"temperature": target}),
    ):
        await hass.services.async_call(
            "climate", service, {"entity_id": zone, **data}, blocking=True
        )
    await hass.async_block_till_done()


async def test_at_start_a_real_vt_thermostat_is_read_through_the_plugins_manager(
    hass: HomeAssistant,
) -> None:
    """P59: VT itself (the pinned 10.6.5; 10.5.1 until 2026-11-25, 10.4.0 until 2026-10-13), not a
    state standing in for it, through Home Assistant's start (VT starts its thermostats once Home
    Assistant has started): VT hands the thermostat to the plugin's feature manager, and the
    plugin reads the room temperature, target, heating mode and duty cycle of an over_switch
    thermostat below its target through it. The manager publishes nothing on the thermostat
    (I12.9: the water interface went)."""
    entry = await room_and_boiler(hass)
    hass.set_state(CoreState.starting)
    await setup(hass, entry)
    await setup(hass, vt_thermostat())
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)

    zone = entry.runtime_data.link.zone(LIVING)
    assert (zone.temperature, zone.target, zone.heating_enabled) == (19.0, 21.0, True)
    assert zone.on_percent == pytest.approx(0.76)  # TPI: 0.3 · 2 K + 0.01 · 16 K
    assert zone.calling is True
    assert zone.device_active is True
    assert zone.temperature_at is not None
    assert DOMAIN in VThermAPI.get_vtherm_api(hass).list_feature_managers()
    # I12 (the user's rule, 2026-11-24): VT handed the thermostat to the plugin's manager, and
    # the zone above was read from it through ``vtherm_api``; it is a room, as VT's central boiler
    # counts it (I12.11: ``entry_infos``' ``used_by_controls_central_boiler``).
    assert entry.runtime_data.link.rooms() == [LIVING]
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)  # VT publishes its attributes again
    assert "smart_boiler" not in hass.states.get(LIVING).attributes


async def test_a_vt_thermostat_already_running_is_handed_over_after_vt_reloads(
    hass: HomeAssistant,
) -> None:
    """A thermostat that started before the plugin registered does not ask again: VT hands it
    to the plugin's feature manager at its next reload — what the plugin's repair issue asks
    for."""
    from custom_components.vtherm_smart_boiler.vtherm_link import vt_thermostat as handed_over

    entry = await room_and_boiler(hass)
    thermostat = vt_thermostat()
    await setup(hass, thermostat)
    await setup(hass, entry)
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    assert handed_over(hass, LIVING) is None
    assert await hass.config_entries.async_reload(thermostat.entry_id)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    assert handed_over(hass, LIVING) is not None


async def test_a_steady_room_under_real_vt_stays_known(hass: HomeAssistant, freezer: Any) -> None:
    """T2 with VT itself: VT reports when its room sensor last changed, so after three hours of a
    steady room its temperature time is three hours old — and the zone is still known."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    from custom_components.vtherm_smart_boiler.coordinator import ZONE_MAX_AGE_S

    entry = await room_and_boiler(hass)
    await setup(hass, entry)
    await setup(hass, vt_thermostat())
    await heat_to(hass, 21.0)
    freezer.tick(timedelta(hours=3))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    now = dt_util.utcnow().timestamp()
    zone = entry.runtime_data.link.zone(LIVING)
    assert zone.temperature_at is not None
    assert now - zone.temperature_at >= 3 * 3600 - 60  # the sensor has not changed
    assert zone.is_known(now, ZONE_MAX_AGE_S)


# --- X3: what a VT zone shows before its start, during a reload and after (decision 3) ----------

OFFICE = "climate.office"


def vt_over_climate() -> MockConfigEntry:
    """A VT over_climate thermostat over a climate of its own (Home Assistant's generic one),
    counted by VT's central boiler: a room of the plugin's (I12.11)."""
    from custom_components.versatile_thermostat import const as vt

    return MockConfigEntry(
        domain=vt.DOMAIN,
        title="Office",
        unique_id="office",
        data={
            vt.CONF_THERMOSTAT_TYPE: vt.CONF_THERMOSTAT_CLIMATE,
            vt.CONF_NAME: "Office",
            vt.CONF_TEMP_SENSOR: "sensor.office_temperature",
            vt.CONF_EXTERNAL_TEMP_SENSOR: "sensor.outdoor_temperature",
            vt.CONF_CYCLE_MIN: 5,
            vt.CONF_TEMP_MIN: 7.0,
            vt.CONF_TEMP_MAX: 30.0,
            vt.CONF_STEP_TEMPERATURE: 0.1,
            vt.CONF_UNDERLYING_LIST: ["climate.office_trv"],
            vt.CONF_AC_MODE: False,
            vt.CONF_USED_BY_CENTRAL_BOILER: True,
        },
    )


def vt_central() -> MockConfigEntry:
    """VT's central configuration, without its central boiler."""
    from custom_components.versatile_thermostat import const as vt

    return MockConfigEntry(
        domain=vt.DOMAIN,
        title="Central",
        unique_id="central",
        data={
            vt.CONF_NAME: "Central",
            vt.CONF_THERMOSTAT_TYPE: vt.CONF_THERMOSTAT_CENTRAL_CONFIG,
            vt.CONF_EXTERNAL_TEMP_SENSOR: "sensor.outdoor_temperature",
            vt.CONF_TEMP_MIN: 7.0,
            vt.CONF_TEMP_MAX: 30.0,
            vt.CONF_STEP_TEMPERATURE: 0.1,
            vt.CONF_TPI_COEF_INT: 0.3,
            vt.CONF_TPI_COEF_EXT: 0.01,
            vt.CONF_USE_CENTRAL_BOILER_FEATURE: False,
        },
    )


@dataclass(frozen=True)
class Shown:
    """One state a VT climate published, as recorded, and whether the plugin then counted the
    thermostat started (I12.7: VT had called its manager's ``refresh_state``)."""

    phase: str
    entity_id: str
    state: str
    is_ready: object  # the attribute, or "absent"
    specific_states: bool  # published at all
    started: bool  # the plugin: VT has started the thermostat


async def test_what_a_vt_zone_shows_before_its_start_during_a_reload_and_after(
    hass: HomeAssistant,
) -> None:
    """Decision 3's rules are written against this (VT 10.4.0, 10.5.1 and the pinned 10.6.5 alike,
    over_switch and over_climate), with the plugin's manager registered (I12.7: a zone is
    started from VT's first ``refresh_state`` on it, which VT calls only once the thermostat is
    ready):

    - before Home Assistant has started, a thermostat shows the placeholder "off": at first with
      neither ``is_ready`` nor ``specific_states`` (before VT's first refresh), later — once an
      underlying device reports — with ``is_ready`` false; never started;
    - once started, ``is_ready`` true with its ``specific_states``: started;
    - a thermostat's reload: unavailable, the placeholder "off" with neither — a new thermostat,
      not started: the placeholder is VT's, not the user's "off" — then its restored mode with
      ``is_ready`` true, started;
    - a reload of VT's central entry changes no thermostat's state.
    """
    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event

    from custom_components.vtherm_smart_boiler.feature_manager import SmartBoilerFeatureFactory
    from custom_components.vtherm_smart_boiler.vtherm_link import THERMOSTATS_KEY, VThermLink
    from custom_components.vtherm_smart_boiler.vtherm_link import vt_thermostat as handed_over

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    for sensor in ("living", "office", "outdoor"):
        hass.states.async_set(f"sensor.{sensor}_temperature", "19.0", celsius)
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"living_valve": {}, "office_heater": {}}}
    )
    trv = {
        "platform": "generic_thermostat",
        "name": "office_trv",
        "heater": "input_boolean.office_heater",
        "target_sensor": "sensor.office_temperature",
    }
    assert await async_setup_component(hass, "climate", {"climate": trv})
    await hass.async_block_till_done()
    link = VThermLink(hass)
    seen: list[Shown] = []
    phase = ["before_start"]

    def note(event: Event) -> None:
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        if entity_id not in (LIVING, OFFICE) or new is None:
            return
        attributes = new.attributes
        seen.append(
            Shown(
                phase[0],
                entity_id,
                new.state,
                attributes.get("is_ready", "absent"),
                "specific_states" in attributes,
                link.zone(entity_id).started,
            )
        )

    hass.bus.async_listen(EVENT_STATE_CHANGED, note)
    hass.set_state(CoreState.starting)
    central = vt_central()
    await setup(hass, central)
    VThermAPI.get_vtherm_api(hass).register_feature_manager(SmartBoilerFeatureFactory(hass))
    living = vt_thermostat()
    await setup(hass, living)
    await setup(hass, vt_over_climate())
    for service in ("turn_on", "turn_off"):  # an underlying device reports before the start
        await hass.services.async_call(
            "input_boolean", service, {"entity_id": "input_boolean.living_valve"}, blocking=True
        )
    await hass.async_block_till_done()
    phase[0] = "after_start"
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)
    old = handed_over(hass, LIVING)
    phase[0] = "thermostat_reload"
    assert await hass.config_entries.async_reload(living.entry_id)
    await hass.async_block_till_done()
    # VT stopped the old thermostat (its manager's ``stop_listening``): forgotten, a new one read.
    assert old is not None
    assert handed_over(hass, LIVING) is not old
    assert all(kept.thermostat is not old for kept in hass.data[THERMOSTATS_KEY])
    phase[0] = "central_reload"
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()

    def shown(stage: str, entity_id: str) -> list[Shown]:
        return [s for s in seen if s.phase == stage and s.entity_id == entity_id]

    for entity_id in (LIVING, OFFICE):
        before = shown("before_start", entity_id)
        assert before, entity_id
        assert all(s.state == "off" and not s.started for s in before)
        assert (before[0].is_ready, before[0].specific_states) == ("absent", False)
        assert all(s.is_ready is False and s.specific_states for s in before[1:])
        assert len(before) > 1, entity_id  # an underlying device reported: not ready yet
        after = shown("after_start", entity_id)
        assert after
        assert all(s.is_ready is True and s.specific_states and s.started for s in after)
    reload = [
        (s.state, s.is_ready, s.specific_states, s.started)
        for s in shown("thermostat_reload", LIVING)
    ]
    assert [item[:3] for item in reload[:2]] == [
        ("unavailable", "absent", False),
        ("off", "absent", False),
    ]
    assert reload[1][3] is False  # the placeholder: a new thermostat, not started
    assert reload[2:]
    assert all(item == ("heat", True, True, True) for item in reload[2:])
    assert shown("thermostat_reload", OFFICE) == []
    assert [s for s in seen if s.phase == "central_reload"] == []
    for entity_id in (LIVING, OFFICE):  # the plugin reads each zone as VT has it now
        assert link.zone(entity_id).started


async def test_a_vt_thermostat_whose_devices_never_report_stays_unknown(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Check C's F1 (SB-02): the devices' integration never sets up after a restart — Home
    Assistant shows their entities restored "unavailable", and no state event ever comes. VT
    (10.4.0 to the pinned 10.6.5) keeps its placeholder "off", with neither ``is_ready`` nor
    ``specific_states``, for good — through 30 minutes of its cycles and room readings; the
    over_climate thermostat shows "off" with ``is_ready`` false. VT hands both to the plugin's
    manager but never calls its ``refresh_state`` (I12.7): the plugin reads each as unknown after
    the recognition period too, never as the user's "off": demand is unknown, not "no"."""
    from custom_components.vtherm_smart_boiler.core.demand import boiler_demand
    from custom_components.vtherm_smart_boiler.feature_manager import SmartBoilerFeatureFactory
    from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink
    from custom_components.vtherm_smart_boiler.vtherm_link import vt_thermostat as handed_over

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    for sensor in ("living", "office", "outdoor"):
        hass.states.async_set(f"sensor.{sensor}_temperature", "19.0", celsius)
    hass.states.async_set("input_boolean.living_valve", "unavailable", {"restored": True})
    hass.states.async_set("climate.office_trv", "unavailable", {"restored": True})
    hass.set_state(CoreState.starting)
    await setup(hass, vt_central())
    VThermAPI.get_vtherm_api(hass).register_feature_manager(SmartBoilerFeatureFactory(hass))
    await setup(hass, vt_thermostat())
    await setup(hass, vt_over_climate())
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    for step in range(6):  # room readings change and VT's cycles run, for 30 minutes
        for sensor in ("living", "office"):
            hass.states.async_set(f"sensor.{sensor}_temperature", f"{18.0 + step / 10}", celsius)
        await later(hass, freezer, 300.0)
    living, office = hass.states.get(LIVING), hass.states.get(OFFICE)
    assert living is not None
    assert office is not None
    assert living.state == "off"
    assert "is_ready" not in living.attributes
    assert "specific_states" not in living.attributes
    assert (office.state, office.attributes.get("is_ready")) == ("off", False)
    link = VThermLink(hass)
    for state in (living, office):
        assert handed_over(hass, state.entity_id) is not None
        zone = link.zone(state.entity_id)
        now = zone.reported_at or 0.0
        assert zone.heating_enabled is False
        assert not zone.started
        assert not zone.is_known(now, None)
        result = boiler_demand([zone], now, None, True)  # whatever VT's central boiler says
        assert (result.wanted, result.unknown) == (None, (state.entity_id,))


async def started_with_the_plugin(hass: HomeAssistant, *thermostats: MockConfigEntry) -> Any:
    """VT's entries and the plugin's, set up through Home Assistant's start, the zone heating
    towards 21 °C: the plugin's entry."""
    entry = await room_and_boiler(hass)
    hass.set_state(CoreState.starting)
    for thermostat in thermostats:
        await setup(hass, thermostat)
    await setup(hass, entry)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)
    return entry


async def later(hass: HomeAssistant, freezer: Any, seconds: float) -> None:
    from datetime import timedelta

    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()


RADIATOR = "input_number.living_radiator"


@pytest.mark.parametrize("max_closing", [100, 90], ids=["closes_fully", "floor_10_percent"])
async def test_a_real_vt_valve_zone_calls_only_with_its_valve_opened_past_its_floor(
    hass: HomeAssistant, freezer: Any, max_closing: int
) -> None:
    """VT 10.5.0's change (the test session's gap 1, 2026-10-13): an over_valve zone whose valve
    may not close fully (VT's ``max_closing_degree`` below 100 — here a floor of 10 %) is not
    active at that floor: "a valve at its physical floor must not heat or request the boiler"
    (VT's own test); VT 10.4.0 counted it active there, so such a zone called for good. The
    plugin takes VT's ``is_device_active``: the zone wants heat with its valve opened past the
    floor by the room's need, not at the floor. Negative: a valve that closes fully, likewise
    — at 0."""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.core.demand import zone_wants_heat

    radiator = {"min": 0, "max": 100, "step": 1, "initial": 0}
    assert await async_setup_component(
        hass, "input_number", {"input_number": {"living_radiator": radiator}}
    )
    valve_zone = vt_thermostat(
        **{
            vt.CONF_THERMOSTAT_TYPE: vt.CONF_THERMOSTAT_VALVE,
            vt.CONF_UNDERLYING_LIST: [RADIATOR],
            vt.CONF_MAX_CLOSING_DEGREE: max_closing,
            vt.CONF_OPENING_THRESHOLD_DEGREE: 0,
        }
    )
    entry = await started_with_the_plugin(hass, valve_zone)  # 19 °C towards 21 °C
    await later(hass, freezer, 30.0)
    link = entry.runtime_data.link

    floor = 100 - max_closing
    zone = link.zone(LIVING)
    assert float(hass.states.get(RADIATOR).state) > floor  # opened by the room's need
    assert zone.device_active is True
    assert zone_wants_heat(zone)
    await heat_to(hass, 15.0)  # the room above its target: closed as far as the valve may
    await later(hass, freezer, 30.0)
    zone = link.zone(LIVING)
    assert float(hass.states.get(RADIATOR).state) == floor
    assert zone.device_active is False
    assert not zone_wants_heat(zone)


async def test_a_vt_safety_mode_zone_follows_vt_and_is_left_out_of_the_curve(
    hass: HomeAssistant, freezer: Any
) -> None:
    """T-44 (S-35), I12.10: the room sensor goes quiet; VT enters its safety mode, fires its
    safety event and runs the zone on its safety duty cycle. The plugin hears the event: the
    room is left out of the curve's judgement, while it follows VT's pulses — the zone stays
    known and its demand counts. The sensor back, VT ends its safety mode and the room counts
    again."""
    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    entry = await started_with_the_plugin(hass, vt_thermostat())
    link = entry.runtime_data.link
    events: list[dict[str, Any]] = []
    hass.bus.async_listen(
        "versatile_thermostat_safety_event", lambda event: events.append(dict(event.data))
    )
    await later(hass, freezer, 10.0)
    hass.states.async_set("sensor.living_temperature", "19.2", celsius)  # measured after the start
    await hass.async_block_till_done()
    assert link.zone(LIVING).room_sensor_lost is False
    for _ in range(6):  # the sensor quiet: VT's safety delay here is five minutes
        await later(hass, freezer, 60.0)
    attributes = hass.states.get(LIVING).attributes
    assert attributes["safety_manager"]["safety_state"] == "on"
    assert [(e["type"], e["entity_id"]) for e in events] == [("start", LIVING)]
    zone = link.zone(LIVING)
    assert zone.room_sensor_lost  # VT's safety event: left out of the curve's judgement
    now = zone.reported_at or 0.0
    assert zone.is_known(now, None)  # VT runs it: its demand still counts
    assert zone.on_percent == pytest.approx(0.3)  # VT's safety duty cycle
    hass.states.async_set("sensor.living_temperature", "19.1", celsius)
    hass.states.async_set("sensor.outdoor_temperature", "5.1", celsius)
    await later(hass, freezer, 300.0)
    assert [e["type"] for e in events] == ["start", "end"]
    assert not link.zone(LIVING).room_sensor_lost  # the sensor back: VT ends its safety mode


async def test_vt_power_shedding_removes_demand(hass: HomeAssistant, freezer: Any) -> None:
    """T-45: VT's power shedding holds the zone off: the zone stays known, and does not call —
    VT turns its device off and stops its cycle, which its power hook tells (I12.7: the plugin no
    longer reads VT's shedding itself); once shedding ends, it calls again."""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.core.demand import boiler_demand

    watts = {"unit_of_measurement": "W", "device_class": "power"}
    hass.states.async_set("sensor.house_power", "1000", watts)
    hass.states.async_set("sensor.house_max_power", "6000", watts)
    central = vt_central()
    powered = {
        vt.CONF_USE_POWER_FEATURE: True,
        vt.CONF_POWER_SENSOR: "sensor.house_power",
        vt.CONF_MAX_POWER_SENSOR: "sensor.house_max_power",
        vt.CONF_PRESET_POWER: 12,
        vt.CONF_POWER_UNIT: "W",
    }
    central = MockConfigEntry(
        domain=vt.DOMAIN, title="Central", unique_id="central", data={**central.data, **powered}
    )
    living = vt_thermostat()
    own = {
        vt.CONF_USE_POWER_FEATURE: True,
        vt.CONF_DEVICE_POWER: 2000,
        vt.CONF_POWER_UNIT: "W",
        vt.CONF_USE_POWER_CENTRAL_CONFIG: True,
    }
    living = MockConfigEntry(
        domain=vt.DOMAIN, title="Living", unique_id="living", data={**living.data, **own}
    )
    entry = await started_with_the_plugin(hass, central, living)
    link = entry.runtime_data.link

    def demand() -> Any:
        zone = link.zone(LIVING)
        return zone, boiler_demand([zone], zone.reported_at or 0.0, None, True)

    zone, before = demand()
    assert zone.on_percent == pytest.approx(0.76)  # VT's power hook: the duty applied
    assert before.zones_wanting == 1
    hass.states.async_set("sensor.house_power", "7000", watts)
    await later(hass, freezer, 30.0)
    zone, shed = demand()
    assert zone.device_active is False
    assert zone.on_percent == 0.0  # VT stopped the cycle: its power hook's stop
    assert zone.is_known(zone.reported_at or 0.0, None)
    assert shed.fresh_zones == 1  # known
    assert shed.zones_wanting == 0
    hass.states.async_set("sensor.house_power", "500", watts)
    await later(hass, freezer, 30.0)
    zone, after = demand()
    assert zone.device_active is True
    assert after.zones_wanting == 1


async def test_vts_power_hook_gives_the_applied_duty_of_an_over_switch_zone(
    hass: HomeAssistant, freezer: Any
) -> None:
    """I12.7 against the pinned VT (10.6.5): VT calls the plugin's manager's power hook
    ``async_on_underlying_power`` at each cycle start of an over_switch thermostat (its manager
    is configured), and the zone's duty is the share VT applied — not what TPI asked: a request
    shorter than VT's minimal activation delay is applied as 0. Never through VT's
    ``on_percent``, whose reading acts on the algorithm."""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.vtherm_link import vt_thermostat as handed_over

    living = vt_thermostat(**{vt.CONF_MINIMAL_ACTIVATION_DELAY: 60})
    entry = await started_with_the_plugin(hass, living)  # 19 °C towards 21 °C
    link = entry.runtime_data.link
    zone = link.zone(LIVING)
    assert zone.started
    assert zone.on_percent == pytest.approx(0.76)  # TPI: 0.3 · 2 K + 0.01 · 16 K, 228 s of 300
    assert zone.valve_open is None  # a switch: no valve
    await heat_to(hass, 19.0)  # TPI asks 0.01 · 14 K: 42 s, under VT's 60 s minimum
    await later(hass, freezer, 300.0)  # the next cycle starts
    thermostat = handed_over(hass, LIVING)
    assert thermostat is not None
    assert thermostat.prop_algorithm.on_percent == pytest.approx(0.14)  # what TPI asks
    assert link.zone(LIVING).on_percent == 0.0  # what VT applied


async def test_entry_infos_carry_a_thermostats_own_settings(hass: HomeAssistant) -> None:
    """I12.7 against the pinned VT (10.6.5): the ``entry_infos`` of the thermostat VT hands the
    plugin's manager carry its type, cycle, devices and whether VT's central boiler counts it
    (VT 10.6.5 ``const.py``: ``thermostat_type``, ``cycle_min``, ``underlying_entity_ids``,
    ``used_by_controls_central_boiler``) — what the short-cycle notice and the relay and
    boiler-thermostat blockers read now, instead of VT's climate attributes and entries."""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        ZoneAlgorithm,
        relay_used_by_zone,
        zone_underlying_entities,
    )
    from custom_components.vtherm_smart_boiler.vtherm_link import vt_thermostat as handed_over

    living = vt_thermostat(**{vt.CONF_USED_BY_CENTRAL_BOILER: True})
    entry = await started_with_the_plugin(hass, vt_central(), living)
    thermostat = handed_over(hass, LIVING)
    assert thermostat is not None
    infos = thermostat.entry_infos
    assert infos["thermostat_type"] == "thermostat_over_switch"
    assert infos["cycle_min"] == 5
    assert infos["underlying_entity_ids"] == ["input_boolean.living_valve"]
    assert infos["used_by_controls_central_boiler"] is True
    link = entry.runtime_data.link
    assert link.zone_algorithm(LIVING) == ZoneAlgorithm(True, "thermostat_over_switch", 5.0, True)
    assert zone_underlying_entities(hass, LIVING) == ("input_boolean.living_valve",)
    assert relay_used_by_zone(hass, "input_boolean.living_valve")


VT_HELPER = "input_boolean.vt_boiler"


def vt_central_with_boiler(helper: str = VT_HELPER) -> MockConfigEntry:
    """VT's central configuration with its central boiler on, its two commands — VT's
    documented format — switching the helper (I12)."""
    from custom_components.versatile_thermostat import const as vt

    boiler = {
        vt.CONF_USE_CENTRAL_BOILER_FEATURE: True,
        vt.CONF_CENTRAL_BOILER_ACTIVATION_SRV: f"{helper}/input_boolean.turn_on",
        vt.CONF_CENTRAL_BOILER_DEACTIVATION_SRV: f"{helper}/input_boolean.turn_off",
    }
    return MockConfigEntry(
        domain=vt.DOMAIN,
        title="Central",
        unique_id="central",
        data={**vt_central().data, **boiler},
    )


async def test_a_real_vts_central_boiler_reaches_the_plugin_through_its_thermostats(
    hass: HomeAssistant, freezer: Any
) -> None:
    """I12 against the pinned VT (10.6.5): VT's central boiler settings reach the plugin in the
    ``entry_infos`` of the thermostat VT hands its feature manager — its commands, which switch
    the helper; and VT's central boiler switches the helper on while the room calls, firing its
    event, which the plugin reads. Unticked in VT (VT reloads everything), the thermostat VT
    hands over again says so."""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        VtBoilerCheck,
        central_boiler_event,
        read_central_boiler_event,
        vt_central_boiler,
    )

    helpers = {"vt_boiler": {}, "living_valve": {}}  # the room's own valve with VT's helper
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": helpers})
    events: list[Any] = []
    hass.bus.async_listen(central_boiler_event(), events.append)
    central = vt_central_with_boiler()
    living = vt_thermostat(**{vt.CONF_USED_BY_CENTRAL_BOILER: True})  # counted by VT
    await started_with_the_plugin(hass, central, living)  # 19 °C towards 21 °C
    await hass.services.async_call(  # VT's own count: one device
        "number",
        "set_value",
        {"entity_id": "number.central_number_activation_threshold", "value": 1},
        blocking=True,
    )
    for _ in range(12):  # within VT's 5-minute cycle, the room's device goes on
        await later(hass, freezer, 30.0)
        if hass.states.get(VT_HELPER).state == "on":
            break
    settings = vt_central_boiler(hass)
    assert settings is not None
    assert settings.check(VT_HELPER) == (None, None)
    assert settings.check("input_boolean.another") == (VtBoilerCheck.NOT_HELPER, VT_HELPER)
    assert hass.states.get(VT_HELPER).state == "on"  # VT's central boiler: the room calls
    said = [read_central_boiler_event(event.data) for event in events]
    assert any(event is not None and event.switched for event in said)
    unticked = {
        key: value
        for key, value in central.data.items()
        if key
        not in (vt.CONF_CENTRAL_BOILER_ACTIVATION_SRV, vt.CONF_CENTRAL_BOILER_DEACTIVATION_SRV)
    } | {vt.CONF_USE_CENTRAL_BOILER_FEATURE: False}
    hass.config_entries.async_update_entry(central, data=unticked)  # VT reloads everything
    await hass.async_block_till_done()
    await later(hass, freezer, 30.0)
    settings = vt_central_boiler(hass)
    assert settings is not None
    assert settings.check(VT_HELPER) == (VtBoilerCheck.NOT_SET, None)


# --- Control on, with VT's central boiler (TB-15) -------------------------------------------

FLOW_NUMBER = "input_number.boiler_flow"
CH_SWITCH = "input_boolean.boiler_ch"


async def controlling_with_the_plugin(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    *thermostats: MockConfigEntry,
    office: bool = False,
) -> tuple[MockConfigEntry, FakeBoiler]:
    """VT's thermostats and the plugin set up through Home Assistant's start, the
    plugin controlling a boiler through a setpoint number and a heating switch, every zone
    heating towards 21 °C; ``office``: the over_climate zone too, over its own climate. The
    plugin's entry ran before and owes nothing."""

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hass.states.async_set("sensor.living_temperature", "19.0", celsius)
    hass.states.async_set("sensor.outdoor_temperature", "5.0", celsius)
    hass.states.async_set("sensor.office_temperature", "19.0", celsius)
    switches = {"living_valve": {}, "boiler_ch": {}, "office_heater": {}, "vt_boiler": {}}
    assert await async_setup_component(hass, "input_boolean", {"input_boolean": switches})
    zones = [LIVING, OFFICE] if office else [LIVING]
    if office:
        trv = {
            "platform": "generic_thermostat",
            "name": "office_trv",
            "heater": "input_boolean.office_heater",
            "target_sensor": "sensor.office_temperature",
        }
        assert await async_setup_component(hass, "climate", {"climate": trv})
    number = {"min": 20, "max": 80, "step": 0.5, "unit_of_measurement": "°C", "initial": 40}
    assert await async_setup_component(
        hass, "input_number", {"input_number": {"boiler_flow": number}}
    )
    signals = (Signal.FLAME, Signal.FLOW, Signal.OUTDOOR, Signal.DHW_ACTIVE)
    boiler = FakeBoiler(hass, signals)
    boiler.set_many(
        {Signal.FLAME: False, Signal.FLOW: 30.0, Signal.OUTDOOR: 5.0, Signal.DHW_ACTIVE: False}
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": boiler.mapping(),
            "boiler": {"class": "flow_setpoint", "dhw": "combi"},
            "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0},
            "monitor": {"monitoring_days": 0},
            "control": {
                "write_path": "entity",
                "setpoint_entity": FLOW_NUMBER,
                "write_type": "held",
                "ch_entity": CH_SWITCH,
                "ch_write_type": "held",
                "hand_back": "value",
                "hand_back_value": 50,
                "hand_back_value_effect": "own_control",
                "confirmed_entity": FLOW_NUMBER,
                "topology": "virtual",
                "curve": {"design_outdoor": -15, "design_flow": 55},
                "vt_boiler_helper": VT_HELPER,  # I12
            },
        },
    )
    if not any(t.data.get("thermostat_type") == "thermostat_central_config" for t in thermostats):
        thermostats = (vt_central_with_boiler(), *thermostats)  # VT's central boiler decides
    hass.set_state(CoreState.starting)
    for thermostat in thermostats:
        await setup(hass, thermostat)
    entry.add_to_hass(hass)
    key = control_store_key(entry.entry_id)
    hass_storage[key] = {"version": 1, "key": key, "data": {}}
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    for zone in zones:
        await heat_to(hass, 21.0, zone)
    control = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_control"
    )
    assert control is not None
    # I11.2: control switched on as an automation does it.
    await hass.services.async_call(DOMAIN, "set_control", {"enabled": True}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(control).state == "on"
    return entry, boiler


async def test_a_hot_water_draw_turns_gives_no_heat_on_under_a_real_vt(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any]
) -> None:
    """TB-15, I12.9: with control on and VT's central boiler calling (its helper on), "boiler
    gives no heat" is off; a hot-water draw on a combi turns it on with the reason ``hot_water``,
    and its end off again — what SmartPI 1.0's "heating unavailable" input reads."""
    from custom_components.versatile_thermostat import const as vt

    thermostat = vt_thermostat(**{vt.CONF_USED_BY_CENTRAL_BOILER: True})  # counted by VT
    entry, boiler = await controlling_with_the_plugin(hass, hass_storage, thermostat)
    await hass.services.async_call(  # VT's own count: one device
        "number",
        "set_value",
        {"entity_id": "number.central_number_activation_threshold", "value": 1},
        blocking=True,
    )
    for _ in range(12):  # within VT's 5-minute cycle, the room's device goes on
        await later(hass, freezer, 30.0)
        if hass.states.get(VT_HELPER).state == "on":
            break
    assert hass.states.get(VT_HELPER).state == "on"
    no_heat = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_no_heat"
    )
    assert no_heat is not None
    await later(hass, freezer, 10.0)
    assert hass.states.get(no_heat).state == "off"
    boiler.set(Signal.DHW_ACTIVE, True)
    await later(hass, freezer, 10.0)
    state = hass.states.get(no_heat)
    assert (state.state, state.attributes["reason"]) == ("on", "hot_water")
    boiler.set(Signal.DHW_ACTIVE, False)
    await later(hass, freezer, 10.0)
    assert hass.states.get(no_heat).state == "off"


async def test_a_vt_central_entry_update_reloads_every_zone_without_a_hand_back(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any], monkeypatch: Any
) -> None:
    """TB-35: VT's central entry updated — VT reloads every entry at once. Each thermostat shows
    unavailable, then its placeholder, then ready. Its setups held back for two control steps
    (a slow reload: in-process VT otherwise brings each zone back before the next one
    goes), every zone is gone at once: the recognition period begins again and keeps the
    command — no hand-back, heating neither switched off nor on — and ends once the zones are
    back."""
    import asyncio

    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event, callback
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    central = vt_central_with_boiler()
    entry, _ = await controlling_with_the_plugin(
        hass, hass_storage, central, vt_thermostat(), vt_over_climate(), office=True
    )
    control_state = er.async_get(hass).async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_control_state"
    )
    assert control_state is not None
    await later(hass, freezer, 30.0)

    def reasons() -> list[str]:
        state = hass.states.get(control_state)
        assert state is not None
        return list(state.attributes["reasons"])

    assert "zones_recognition" not in reasons()
    shown: dict[str, list[tuple[str, object]]] = {LIVING: [], OFFICE: []}
    writes: list[tuple[str, str]] = []

    @callback
    def note(event: Event) -> None:
        entity_id = event.data["entity_id"]
        new = event.data["new_state"]
        if new is None:
            return
        if entity_id in shown:
            shown[entity_id].append((new.state, new.attributes.get("is_ready", "absent")))
        elif entity_id in (FLOW_NUMBER, CH_SWITCH):
            writes.append((entity_id, new.state))

    hass.bus.async_listen(EVENT_STATE_CHANGED, note)
    hold = asyncio.Event()
    original_setup = hass.config_entries.async_setup

    async def held_setup(entry_id: str, **kwargs: Any) -> bool:
        held = hass.config_entries.async_get_entry(entry_id)
        if held is not None and held.domain == "versatile_thermostat":
            await hold.wait()
        return await original_setup(entry_id, **kwargs)

    monkeypatch.setattr(hass.config_entries, "async_setup", held_setup)
    ch_before = hass.states.get(CH_SWITCH).state
    number_before = hass.states.get(FLOW_NUMBER).state
    hass.config_entries.async_update_entry(central, data={**central.data, "temp_max": 29.0})
    for _ in range(2):  # two control steps while VT's thermostats are away
        freezer.tick(10)
        async_fire_time_changed(hass)
        for _ in range(20):
            await asyncio.sleep(0)
    assert hass.states.get(LIVING).state == "unavailable"
    assert hass.states.get(OFFICE).state == "unavailable"
    assert "zones_recognition" in reasons()  # begun again: no new decision meanwhile
    hold.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    for entity_id, states in shown.items():
        assert states[0] == ("unavailable", "absent"), entity_id
        assert ("off", "absent") in states[1:], entity_id  # VT's placeholder
        assert states[-1] == ("heat", True), entity_id
    await later(hass, freezer, 10.0)
    assert "zones_recognition" not in reasons()  # every zone reported again
    control = er.async_get(hass).async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_control"
    )
    assert control is not None
    assert hass.states.get(control).state == "on"
    assert not entry.runtime_data.control.hand_back_owed
    assert writes == []  # no hand-back value, heating neither off nor on
    assert hass.states.get(CH_SWITCH).state == ch_before
    assert hass.states.get(FLOW_NUMBER).state == number_before


def _j4_walk() -> Any:
    """The J4 runner's pure form walker, by its file (its ``lib`` reads the test instances'
    access data, so only this module is loaded)."""
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[2] / "devenv" / "j4" / "walk.py"
    spec = importlib.util.spec_from_file_location("j4_walk_vt", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _vt_rest(hass: HomeAssistant, hass_client: Any) -> Any:
    """The runner's ``rest``, on Home Assistant's own HTTP API."""
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    async def rest(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = await client.request(method, path, json=body)
        try:
            return response.status, await response.json()
        except ValueError:
            return response.status, await response.text()

    return rest


async def test_j4_sets_a_real_vts_cycle_through_vts_own_options(
    hass: HomeAssistant, hass_client: Any
) -> None:
    """J4's tool for the starts criterion's VT cycle (K4, #150; `devenv/j4/vt_cycle.py`): a real
    VT thermostat's cycle set to 15 min through VT's own options flow over Home Assistant's REST
    API, as a user changes it — its "main" form answered with what it shows but the cycle, then
    saved; VT reloads the thermostat, which publishes the new cycle; nothing else changes."""
    from custom_components.versatile_thermostat import const as vt

    await room_and_boiler(hass)
    # VT refuses "used by central boiler" in its own form without a central configuration.
    zone = vt_thermostat(current=True, **{vt.CONF_USED_BY_CENTRAL_BOILER: False})
    await setup(hass, zone)
    before = {**zone.data, **zone.options}
    rest = await _vt_rest(hass, hass_client)
    assert await _j4_walk().set_vt_cycle(rest, zone.entry_id, 15)
    await hass.async_block_till_done()
    after = {**zone.data, **zone.options}
    assert after[vt.CONF_CYCLE_MIN] == 15
    unchanged = {
        key for key in before if key != vt.CONF_CYCLE_MIN and before[key] == after.get(key)
    }
    assert unchanged == set(before) - {vt.CONF_CYCLE_MIN}, set(before) - unchanged
    state = hass.states.get(LIVING)
    assert state is not None
    assert state.attributes["configuration"]["cycle_min"] == 15


async def test_j4_leaves_a_vt_entry_whose_main_form_asks_no_cycle() -> None:
    """Negative: an entry whose "main" form asks no cycle (VT's central configuration) is left
    — its flow closed, nothing saved, ``False``."""
    calls: list[tuple[str, str, Any]] = []

    async def rest(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        calls.append((method, path, body))
        if method == "POST" and body and "handler" in body:
            return 200, {"type": "menu", "flow_id": "f1", "menu_options": ["main", "finalize"]}
        if method == "POST":
            return 200, {
                "type": "form",
                "flow_id": "f1",
                "step_id": "main",
                "data_schema": [{"name": "name", "default": "Central"}],
            }
        return 200, {}

    assert not await _j4_walk().set_vt_cycle(rest, "central", 15)
    assert calls[-1][0] == "DELETE"
    assert not any(body and "cycle_min" in body for _m, _p, body in calls)
