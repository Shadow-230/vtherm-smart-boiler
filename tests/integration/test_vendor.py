"""The vendored VT and SmartPI integrations load in the in-process Home Assistant."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    ("domain", "version"),
    [("versatile_thermostat", "10.4.0"), ("vtherm_smartpi", "0.0.0")],
)
async def test_vendored_integration_loads(hass: HomeAssistant, domain: str, version: str) -> None:
    integration = await async_get_integration(hass, domain)
    assert str(integration.version) == version
    assert await integration.async_get_component() is not None


LIVING = "climate.living"


def vt_thermostat(current: bool = False, **changes: Any) -> MockConfigEntry:
    """A VT over_switch thermostat in the entry format of VT 10.4.0; ``changes`` replace its
    data's keys. ``current``: stored at VT's own entry version, which VT does not migrate — its
    migration from an older version switches Auto-TPI off."""
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
            "zones": [{"entity_id": LIVING}],
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


async def test_at_start_a_real_vt_thermostat_is_read_and_shows_the_plugins_values(
    hass: HomeAssistant,
) -> None:
    """P59: VT 10.4.0 itself, not a state standing in for it, through Home Assistant's start
    (VT starts its thermostats once Home Assistant has started): the plugin reads the room
    temperature, target, heating mode and duty cycle of an over_switch thermostat below its
    target, and the thermostat shows the plugin's values through the feature manager."""
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
    assert DOMAIN in VThermAPI.get_vtherm_api(hass).list_feature_managers()
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)  # VT publishes its attributes again
    shown = hass.states.get(LIVING).attributes.get("smart_boiler")
    assert shown is not None
    assert set(shown) == {"heat_available", "emitter_power_factor"}


async def test_a_vt_thermostat_already_running_shows_the_values_after_vt_reloads(
    hass: HomeAssistant,
) -> None:
    """A thermostat that started before the plugin registered does not ask again: it picks the
    feature manager up at VT's next reload — what the plugin's repair issue asks for."""
    entry = await room_and_boiler(hass)
    thermostat = vt_thermostat()
    await setup(hass, thermostat)
    await setup(hass, entry)
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)
    assert "smart_boiler" not in hass.states.get(LIVING).attributes
    assert await hass.config_entries.async_reload(thermostat.entry_id)
    await hass.async_block_till_done()
    await heat_to(hass, 21.0)
    await entry.runtime_data.async_refresh()
    await heat_to(hass, 21.5)
    assert hass.states.get(LIVING).attributes.get("smart_boiler") is not None


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
    """A VT over_climate thermostat over a climate of its own (Home Assistant's generic one)."""
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
    """One state a VT climate published, as recorded, and as the plugin reads it."""

    phase: str
    entity_id: str
    state: str
    is_ready: object  # the attribute, or "absent"
    specific_states: bool  # published at all
    reported: bool  # the plugin: VT shows it started, with its mode known


async def test_what_a_vt_zone_shows_before_its_start_during_a_reload_and_after(
    hass: HomeAssistant,
) -> None:
    """Decision 3's rules are written against this (VT 10.4.0, over_switch and over_climate):

    - before Home Assistant has started, a thermostat shows the placeholder "off": at first with
      neither ``is_ready`` nor ``specific_states`` (before VT's first refresh), later — once an
      underlying device reports — with ``is_ready`` false; never "reported";
    - once started, ``is_ready`` true with its ``specific_states``: reported;
    - a thermostat's reload: unavailable, the placeholder "off" with neither, then its restored
      mode with ``is_ready`` true — the placeholder is VT's, not the user's "off";
    - a reload of VT's central entry changes no thermostat's state.
    """
    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event

    from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink

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
    link = VThermLink(hass, (LIVING, OFFICE))
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
                link.zone_from_state(entity_id, new).reported is True,
            )
        )

    hass.bus.async_listen(EVENT_STATE_CHANGED, note)
    hass.set_state(CoreState.starting)
    central = vt_central()
    await setup(hass, central)
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
    phase[0] = "thermostat_reload"
    assert await hass.config_entries.async_reload(living.entry_id)
    await hass.async_block_till_done()
    phase[0] = "central_reload"
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()

    def shown(stage: str, entity_id: str) -> list[Shown]:
        return [s for s in seen if s.phase == stage and s.entity_id == entity_id]

    for entity_id in (LIVING, OFFICE):
        before = shown("before_start", entity_id)
        assert before, entity_id
        assert all(s.state == "off" and not s.reported for s in before)
        assert (before[0].is_ready, before[0].specific_states) == ("absent", False)
        assert all(s.is_ready is False and s.specific_states for s in before[1:])
        assert len(before) > 1, entity_id  # an underlying device reported: not ready yet
        after = shown("after_start", entity_id)
        assert after
        assert all(s.is_ready is True and s.specific_states and s.reported for s in after)
    reload = [(s.state, s.is_ready, s.specific_states) for s in shown("thermostat_reload", LIVING)]
    assert reload[:2] == [("unavailable", "absent", False), ("off", "absent", False)]
    assert reload[2:]
    assert all(item == ("heat", True, True) for item in reload[2:])
    assert shown("thermostat_reload", OFFICE) == []
    assert [s for s in seen if s.phase == "central_reload"] == []
    for entity_id in (LIVING, OFFICE):  # the plugin reads each zone as VT shows it now
        zone = link.zone(entity_id)
        assert zone.reported is True
        assert zone.started


async def test_a_vt_thermostat_whose_devices_never_report_stays_unknown(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Check C's F1 (SB-02): the devices' integration never sets up after a restart — Home
    Assistant shows their entities restored "unavailable", and no state event ever comes. VT
    10.4.0 keeps its placeholder "off", with neither ``is_ready`` nor ``specific_states``, for
    good — through 30 minutes of its cycles and room readings; the over_climate thermostat shows
    "off" with ``is_ready`` false. The plugin reads each as unknown after the recognition period
    too, never as the user's "off": demand is unknown, not "no"."""
    from custom_components.vtherm_smart_boiler.core.demand import DemandConfig, boiler_demand
    from custom_components.vtherm_smart_boiler.vtherm_link import VThermLink

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    for sensor in ("living", "office", "outdoor"):
        hass.states.async_set(f"sensor.{sensor}_temperature", "19.0", celsius)
    hass.states.async_set("input_boolean.living_valve", "unavailable", {"restored": True})
    hass.states.async_set("climate.office_trv", "unavailable", {"restored": True})
    hass.set_state(CoreState.starting)
    await setup(hass, vt_central())
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
    link = VThermLink(hass, (LIVING, OFFICE))
    for state in (living, office):
        zone = link.zone_from_state(state.entity_id, state)
        now = zone.reported_at or 0.0
        assert zone.heating_enabled is False
        assert not zone.is_known(now, None)
        result = boiler_demand([zone], now, None, DemandConfig())
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


async def test_a_vt_safety_mode_zone_follows_vt_and_is_flagged(
    hass: HomeAssistant, freezer: Any
) -> None:
    """T-44 (S-35): the room sensor goes quiet; VT enters its safety mode and runs the zone on
    its safety duty cycle. The plugin follows VT's pulses — the zone stays known and its demand
    counts — and flags it as a lost sensor, which the zone alarm reports after its limit."""
    entry = await started_with_the_plugin(hass, vt_thermostat())
    link = entry.runtime_data.link
    assert link.zone(LIVING).safety_on is False
    for _ in range(11):  # the sensor quiet: VT checks at its cycle, every five minutes
        await later(hass, freezer, 60.0)
    attributes = hass.states.get(LIVING).attributes
    assert attributes["safety_manager"]["safety_state"] == "on"
    zone = link.zone(LIVING)
    assert zone.safety_on
    assert zone.room_sensor_lost  # flagged: the zone alarm follows after its limit
    now = zone.reported_at or 0.0
    assert zone.is_known(now, None)  # VT runs it: its demand still counts
    assert zone.on_percent == pytest.approx(0.3)  # VT's safety duty cycle
    hass.states.async_set(
        "sensor.living_temperature",
        "19.1",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    hass.states.async_set(
        "sensor.outdoor_temperature",
        "5.1",
        {"unit_of_measurement": "°C", "device_class": "temperature"},
    )
    await later(hass, freezer, 300.0)
    assert not link.zone(LIVING).safety_on  # the sensor back: VT ends its safety mode


async def test_vt_power_shedding_removes_demand(hass: HomeAssistant, freezer: Any) -> None:
    """T-45: VT's power shedding holds the zone off: the zone stays known, with no demand and no
    power; once shedding ends, its demand is back. (A test first; the plugin reads VT's own
    ``overpowering_state``.)"""
    from custom_components.versatile_thermostat import const as vt

    from custom_components.vtherm_smart_boiler.core.demand import DemandConfig, boiler_demand

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
    config = DemandConfig(count_threshold=1, power_threshold_kw=1.0)

    def demand() -> Any:
        zone = link.zone(LIVING)
        return zone, boiler_demand([zone], zone.reported_at or 0.0, None, config)

    zone, before = demand()
    assert (zone.shedding, zone.mean_power) == (False, pytest.approx(1.52))  # 0.76 of 2 kW
    assert before.wanted is True
    assert before.power_kw == pytest.approx(1.52)
    hass.states.async_set("sensor.house_power", "7000", watts)
    await later(hass, freezer, 30.0)
    zone, shed = demand()
    assert zone.shedding
    assert zone.is_known(zone.reported_at or 0.0, None)
    assert shed.wanted is False
    assert shed.zones_wanting == 0
    assert shed.power_kw == 0.0
    hass.states.async_set("sensor.house_power", "500", watts)
    await later(hass, freezer, 30.0)
    zone, after = demand()
    assert not zone.shedding
    assert after.wanted is True


def vt_central_with_boiler() -> MockConfigEntry:
    """VT's central configuration with its central boiler on: a relay switched through two
    commands in VT 10.4.0's format."""
    from custom_components.versatile_thermostat import const as vt

    boiler = {
        vt.CONF_USE_CENTRAL_BOILER_FEATURE: True,
        vt.CONF_CENTRAL_BOILER_ACTIVATION_SRV: "input_boolean.boiler_relay/input_boolean.turn_on",
        vt.CONF_CENTRAL_BOILER_DEACTIVATION_SRV: (
            "input_boolean.boiler_relay/input_boolean.turn_off"
        ),
    }
    return MockConfigEntry(
        domain=vt.DOMAIN,
        title="Central",
        unique_id="central",
        data={**vt_central().data, **boiler},
    )


async def test_a_real_vt_central_entry_is_read_through_its_reload_and_its_untick(
    hass: HomeAssistant,
) -> None:
    """X7 against VT 10.4.0: its central boiler configured, the plugin reads it at every state
    change while VT sets its central entry up again — never unknown (P-105). The user unticks
    it (VT drops its two commands and reloads): VT's entry says "off", yet in this run the
    plugin keeps it as there — VT's manager may still switch the relay until Home Assistant
    restarts. The stand-in VT's untick leaves, written in this run, says so by itself (decision 9
    of plan 0.2.3)."""
    from custom_components.versatile_thermostat import const as vt
    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event, callback

    from custom_components.vtherm_smart_boiler.vtherm_link import (
        VT_CENTRAL_SEEN,
        VThermLink,
        vt_run,
    )

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hass.states.async_set("sensor.outdoor_temperature", "5.0", celsius)
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": {"boiler_relay": {}}}
    )
    central = vt_central_with_boiler()
    hass.set_state(CoreState.starting)
    run = vt_run(hass)  # the plugin set up while Home Assistant starts
    await setup(hass, central)
    hass.set_state(CoreState.running)
    hass.bus.async_fire(EVENT_HOMEASSISTANT_STARTED)
    await hass.async_block_till_done()
    assert run.started is not None  # taken once Home Assistant has started
    link = VThermLink(hass, [])
    sensor = er.async_get(hass).async_get_entity_id(
        "binary_sensor", vt.DOMAIN, "central_boiler_state"
    )
    assert sensor is not None  # VT's own sensor, registered and provided: what is read first
    shown = hass.states.get(sensor)
    assert shown is not None
    assert shown.attributes.get("is_central_boiler_configured") is True

    def now() -> bool | None:
        """What the plugin reads at this moment, this run's latch left aside."""
        latched = hass.data.pop(VT_CENTRAL_SEEN, None)
        try:
            return link.vt_central_boiler_configured()
        finally:
            if latched:
                hass.data[VT_CENTRAL_SEEN] = latched

    assert link.vt_central_boiler_configured() is True
    seen: list[bool | None] = []

    @callback
    def note(_event: Event) -> None:
        seen.append(now())

    hass.bus.async_listen(EVENT_STATE_CHANGED, note)
    assert await hass.config_entries.async_reload(central.entry_id)
    await hass.async_block_till_done()
    assert seen  # VT's entities went and came back
    assert set(seen) == {True}
    seen.clear()
    unticked = {
        key: value
        for key, value in central.data.items()
        if key
        not in (vt.CONF_CENTRAL_BOILER_ACTIVATION_SRV, vt.CONF_CENTRAL_BOILER_DEACTIVATION_SRV)
    } | {vt.CONF_USE_CENTRAL_BOILER_FEATURE: False}
    hass.config_entries.async_update_entry(central, data=unticked)  # VT reloads everything
    await hass.async_block_till_done()
    assert seen
    assert None not in seen
    stand_in = hass.states.get(sensor)
    assert stand_in is not None
    assert stand_in.attributes.get("restored") is True  # VT no longer provides the sensor
    assert stand_in.last_updated > run.started  # written in this run, after the start
    assert central.data[vt.CONF_USE_CENTRAL_BOILER_FEATURE] is False  # VT's entry says "off"...
    assert now() is True  # ...yet its stand-in tells VT ran its central boiler in this run
    assert link.vt_central_boiler_configured() is True  # not before the restart


# --- Control on, with VT's learning (TB-15) ------------------------------------------------

FLOW_NUMBER = "input_number.boiler_flow"
CH_SWITCH = "input_boolean.boiler_ch"


async def controlling_with_the_plugin(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    *thermostats: MockConfigEntry,
    smartpi: bool = False,
    office: bool = False,
) -> tuple[MockConfigEntry, FakeBoiler]:
    """VT's thermostats (and SmartPI) and the plugin set up through Home Assistant's start, the
    plugin controlling a boiler through a setpoint number and a heating switch, every zone
    heating towards 21 °C; ``office``: the over_climate zone too, over its own climate. The
    plugin's entry ran before and owes nothing."""

    celsius = {"unit_of_measurement": "°C", "device_class": "temperature"}
    hass.states.async_set("sensor.living_temperature", "19.0", celsius)
    hass.states.async_set("sensor.outdoor_temperature", "5.0", celsius)
    hass.states.async_set("sensor.office_temperature", "19.0", celsius)
    switches = {"living_valve": {}, "boiler_ch": {}, "office_heater": {}}
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
            "zones": [{"entity_id": zone} for zone in zones],
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
            },
        },
    )
    hass.set_state(CoreState.starting)
    for thermostat in thermostats:
        await setup(hass, thermostat)
    if smartpi:
        assert await async_setup_component(hass, "vtherm_smartpi", {})
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
    control = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_control")
    assert control is not None
    await hass.services.async_call("switch", "turn_on", {"entity_id": control}, blocking=True)
    await hass.async_block_till_done()
    assert hass.states.get(control).state == "on"
    return entry, boiler


async def test_a_hot_water_draw_pauses_and_resumes_a_real_smartpi_zones_learning(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any]
) -> None:
    """TB-15: with control on, a hot-water draw pauses the learning of a real SmartPI zone
    through SmartPI's own service, and its end switches it back on — read in VT's climate."""
    thermostat = vt_thermostat(proportional_function="smartpi")
    _, boiler = await controlling_with_the_plugin(hass, hass_storage, thermostat, smartpi=True)

    def learning() -> object:
        return hass.states.get(LIVING).attributes["specific_states"]["smartpi_learning_enabled"]

    await later(hass, freezer, 10.0)
    assert hass.states.get(LIVING).attributes["configuration"]["proportional_function"] == (
        "smartpi"
    )
    assert learning() is True
    boiler.set(Signal.DHW_ACTIVE, True)
    await later(hass, freezer, 10.0)
    assert learning() is False
    boiler.set(Signal.DHW_ACTIVE, False)
    for _ in range(120):  # the resume waits for the minimum pause
        await later(hass, freezer, 10.0)
        if learning() is True:
            break
    assert learning() is True


async def test_a_real_vt_auto_tpi_session_is_read_and_raises_the_learning_issue(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any]
) -> None:
    """TB-15: a VT TPI zone whose Auto-TPI session the user starts — VT publishes
    ``auto_tpi_state`` "on" — is learning the plugin cannot pause: with control on and learning
    pauses, its warning names the zone."""
    from homeassistant.helpers import issue_registry as ir

    thermostat = vt_thermostat(current=True, auto_tpi_mode=True)
    entry, _ = await controlling_with_the_plugin(hass, hass_storage, thermostat)
    issue_id = f"learning_not_paused_{entry.entry_id}"
    await later(hass, freezer, 10.0)
    specific = hass.states.get(LIVING).attributes["specific_states"]
    assert specific["auto_tpi_state"] == "off"
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    await hass.services.async_call(
        "versatile_thermostat",
        "set_auto_tpi_mode",
        {"entity_id": LIVING, "auto_tpi_mode": True, "reinitialise": False},
        blocking=True,
    )
    await hass.async_block_till_done()
    for _ in range(6):  # the plugin looks again at its next five-minute analysis
        await later(hass, freezer, 60.0)
    specific = hass.states.get(LIVING).attributes["specific_states"]
    assert specific["auto_tpi_state"] == "on"
    found = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert found is not None
    assert found.translation_placeholders == {"zones": "Living"}


async def test_a_vt_central_entry_update_reloads_every_zone_without_a_hand_back(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any], monkeypatch: Any
) -> None:
    """TB-35: VT's central entry updated — VT reloads every entry at once. Each thermostat shows
    unavailable, then its placeholder, then ready. Its setups held back for two control steps
    (a slow reload: in-process VT 10.4.0 otherwise brings each zone back before the next one
    goes), every zone is gone at once: the recognition period begins again and keeps the
    command — no hand-back, heating neither switched off nor on — and ends once the zones are
    back."""
    import asyncio

    from homeassistant.const import EVENT_STATE_CHANGED
    from homeassistant.core import Event, callback
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    central = vt_central()
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
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_control")
    assert switch is not None
    assert hass.states.get(switch).state == "on"
    assert not entry.runtime_data.control.hand_back_owed
    assert writes == []  # no hand-back value, heating neither off nor on
    assert hass.states.get(CH_SWITCH).state == ch_before
    assert hass.states.get(FLOW_NUMBER).state == number_before
