"""The missing-data rule through Home Assistant (Y4): every feature whose input is missing is
shown inactive by the "Features" sensor, naming what it lacks in a translated text, and its
entities are not created — or are unavailable where its input goes while it runs."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import SIGNAL_SPECS, Signal, SignalKind
from custom_components.vtherm_smart_boiler.entity import FEATURE_ENTITIES

from .harness import BOILER_ENTITIES, WEATHER_ENTITY, FakeForecasts, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

TRANSLATIONS = (
    Path(__file__).resolve().parents[2] / "custom_components/vtherm_smart_boiler/translations"
)
TEXTS = {
    language: json.loads((TRANSLATIONS / f"{language}.json").read_text(encoding="utf-8"))
    for language in ("en", "pl")
}
ENTITIES: dict[Signal, str] = BOILER_ENTITIES | {
    Signal.BOILER_POWER: "sensor.fake_boiler_power",
    Signal.LOW_PRESSURE_FAULT: "binary_sensor.fake_boiler_low_pressure",
    Signal.BOILER_LOCKOUT: "binary_sensor.fake_boiler_lockout",
    Signal.FAULT_INDICATION: "binary_sensor.fake_boiler_fault",
}
VALUES: dict[Signal, tuple[str, dict[str, Any]]] = {
    Signal.FLOW: ("45", {"unit_of_measurement": "°C"}),
    Signal.RETURN: ("35", {"unit_of_measurement": "°C"}),
    Signal.MODULATION: ("20", {"unit_of_measurement": "%"}),
    Signal.CH_SETPOINT: ("50", {"unit_of_measurement": "°C"}),
    Signal.PRESSURE: ("1.5", {"unit_of_measurement": "bar"}),
    Signal.FLUE_GAS: ("50", {"unit_of_measurement": "°C"}),
    Signal.OUTDOOR: ("5", {"unit_of_measurement": "°C"}),
    Signal.ROOM_SETPOINT: ("20", {"unit_of_measurement": "°C"}),
    Signal.ROOM_TEMPERATURE: ("20", {"unit_of_measurement": "°C"}),
    Signal.GAS_METER: ("1000", {"unit_of_measurement": "m³", "state_class": "total_increasing"}),
    Signal.BOILER_POWER: ("100", {"unit_of_measurement": "W", "device_class": "power"}),
}
SETPOINT_READ_BACK = "sensor.fake_gateway_control_setpoint"
RELAY = "switch.fake_boiler_relay"


def set_signals(hass: HomeAssistant) -> None:
    """Every signal known: binary ones off, the others a plausible reading."""
    for signal, entity in ENTITIES.items():
        if SIGNAL_SPECS[signal].kind is SignalKind.BINARY:
            hass.states.async_set(entity, "off")
        else:
            state, attributes = VALUES[signal]
            hass.states.async_set(entity, state, attributes)
    hass.states.async_set(SETPOINT_READ_BACK, "40", {"unit_of_measurement": "°C"})
    hass.states.async_set(RELAY, "off")


def water_options(zone: str) -> dict[str, Any]:
    """Everything an installation can give, on a water-temperature path: every signal, the
    weather, a condensing combi with gas rates, a circuit with its maximum, a zone, the "add
    water" threshold, control through a gateway with an OpenTherm wall thermostat."""
    return {
        "signals": {signal.value: entity for signal, entity in ENTITIES.items()},
        "weather": WEATHER_ENTITY,
        "boiler": {"class": "flow_setpoint", "dhw": "combi", "condensing": True},
        "parameters": {"gas_at_min_power": 0.4, "gas_at_max_power": 2.5},
        "circuits": [{"id": "main", "max_flow": 60}],
        "zones": [{"entity_id": zone}],
        "monitor": {"monitoring_days": 0, "add_water_below": 1.0},
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "gw",
            "confirmed_entity": SETPOINT_READ_BACK,
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "curve": {"design_outdoor": -15, "design_flow": 55},
        },
    }


def relay_options(zone: str) -> dict[str, Any]:
    """The same installation with an on/off boiler controlled through a relay whose proof the
    boiler's power gives, above its threshold."""
    options = water_options(zone)
    options["boiler"] = {"class": "on_off", "dhw": "combi", "condensing": True}
    options["control"] = {
        "write_path": "relay",
        "relay_entity": RELAY,
        "relay_is_separate_contact": True,
        "relay_reports_state": "yes",
        "relay_power_on_state": "off",
        "relay_off_timer": "none",
        "boiler_heats_above_w": 50,
    }
    return options


type Change = Callable[[dict[str, Any]], None]


def without(*signals: Signal) -> Change:
    def change(options: dict[str, Any]) -> None:
        for signal in signals:
            options["signals"].pop(signal.value, None)

    return change


def setting(*path: str, value: Any) -> Change:
    def change(options: dict[str, Any]) -> None:
        target = options
        for key in path[:-1]:
            target = target[key]
        if value is None:
            target.pop(path[-1], None)
        else:
            target[path[-1]] = value

    return change


def both(*changes: Change) -> Change:
    def change(options: dict[str, Any]) -> None:
        for each in changes:
            each(options)

    return change


def no_control(options: dict[str, Any]) -> None:
    del options["control"]


def no_zones(options: dict[str, Any]) -> None:
    options["zones"] = []


# (feature, the base, what is taken away, the status then, the code it names). Every input of
# the feature table (plan-0.2.2-details, Y4 rule 21), each alone.
CASES: list[tuple[str, str, Change, str, str]] = [
    ("cycles", "water", without(Signal.FLAME), "inactive", "flame"),
    ("condensing", "water", without(Signal.FLAME), "inactive", "flame"),
    ("condensing", "water", without(Signal.RETURN), "inactive", "return"),
    (
        "dhw_detection",
        "water",
        without(Signal.DHW_ACTIVE, Signal.CH_ACTIVE, Signal.FLOW),
        "inactive",
        "dhw_active",
    ),
    (
        "gas",
        "water",
        both(without(Signal.GAS_METER), setting("parameters", value={})),
        "inactive",
        "gas_meter",
    ),
    (
        "degree_days",
        "water",
        both(without(Signal.OUTDOOR), setting("weather", value=None)),
        "inactive",
        "outdoor",
    ),
    (
        "degree_days",
        "water",
        both(without(Signal.OUTDOOR), setting("weather", value=None)),
        "inactive",
        "weather_entity",
    ),
    ("hot_water", "water", without(Signal.FLOW), "inactive", "flow"),
    ("emitter_factor", "water", without(Signal.FLOW), "inactive", "flow"),
    ("flue_gas_warning", "water", without(Signal.FLUE_GAS), "inactive", "flue_gas"),
    (
        "flue_gas_warning",
        "water",
        setting("boiler", "condensing", value=False),
        "inactive",
        "condensing_boiler",
    ),
    ("flue_gas_warning", "water", without(Signal.RETURN), "degraded", "return"),
    ("pressure_warning", "water", without(Signal.PRESSURE), "inactive", "pressure"),
    ("add_water", "water", without(Signal.PRESSURE), "inactive", "pressure"),
    (
        "add_water",
        "water",
        setting("monitor", "add_water_below", value=None),
        "inactive",
        "add_water_threshold",
    ),
    *(
        ("pressure_trend", "water", without(signal), "inactive", signal.value)
        for signal in (Signal.PRESSURE, Signal.FLAME, Signal.FLOW)
    ),
    *(
        ("hysteresis_drift", "water", without(signal), "inactive", signal.value)
        for signal in (Signal.FLOW, Signal.FLAME)
    ),
    ("hysteresis_drift", "water", no_zones, "inactive", "zone_data"),
    ("unstable_ignition", "water", without(Signal.FLAME), "inactive", "flame"),
    ("unstable_ignition", "water", without(Signal.CH_SETPOINT), "degraded", "ch_setpoint"),
    (
        "low_flow",
        "water",
        without(Signal.PUMP_RUNNING, Signal.CH_ACTIVE),
        "inactive",
        "pump_running",
    ),
    ("low_flow", "water", no_zones, "inactive", "valve_openings"),
    ("low_flow", "water", setting("boiler", "bypass", value=True), "inactive", "no_bypass"),
    ("low_flow", "water", without(Signal.DHW_ACTIVE), "inactive", "dhw_active"),
    ("outdoor_check", "water", without(Signal.OUTDOOR), "inactive", "outdoor"),
    ("outdoor_check", "water", setting("weather", value=None), "inactive", "weather_entity"),
    (
        "boiler_fault_stop",
        "water",
        without(Signal.LOW_PRESSURE_FAULT, Signal.BOILER_LOCKOUT),
        "inactive",
        "low_pressure_fault",
    ),
    ("boiler_fault_stop", "water", no_control, "inactive", "control"),
    ("verdict", "water", without(Signal.FLAME), "inactive", "flame"),
    ("comfort_correction", "water", no_control, "inactive", "control"),
    ("comfort_correction", "relay", lambda options: None, "inactive", "water_control"),
    ("comfort_correction", "water", no_zones, "inactive", "zone_data"),
    (
        "comfort_correction",
        "water",
        setting("control", "comfort_correction", value=False),
        "inactive",
        "turned_off",
    ),
    ("frost_protection", "water", no_control, "inactive", "control"),
    ("frost_protection", "water", no_zones, "inactive", "zone_data"),
    ("activation_delay", "water", no_control, "inactive", "control"),
    ("circuit_overshoot_alarm", "water", without(Signal.FLOW), "inactive", "flow"),
    (
        "circuit_overshoot_alarm",
        "water",
        setting("circuits", value=[{"id": "main"}]),
        "inactive",
        "circuit_maximum",
    ),
    ("lowest_water_suggestion", "water", without(Signal.FLAME), "inactive", "flame"),
    ("lowest_water_suggestion", "water", without(Signal.FLOW), "inactive", "flow"),
    (
        "lowest_water_suggestion",
        "water",
        both(without(Signal.CH_SETPOINT), no_control),
        "inactive",
        "ch_setpoint",
    ),
    ("wall_thermostat_fallback", "water", no_control, "inactive", "wall_thermostat"),
    (
        "wall_thermostat_fallback",
        "water",
        without(Signal.ROOM_SETPOINT),
        "inactive",
        "room_setpoint",
    ),
    ("relay_proof", "water", lambda options: None, "inactive", "relay_control"),
    (
        "relay_proof",
        "relay",
        without(Signal.FLAME, Signal.FLOW, Signal.GAS_METER, Signal.BOILER_POWER),
        "inactive",
        "flame",
    ),
    ("forecasts", "water", setting("weather", value=None), "inactive", "weather_entity"),
]


async def _setup(
    hass: HomeAssistant, zones: FakeZones, base: str, change: Change
) -> MockConfigEntry:
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw"}).add_to_hass(hass)
    zone = zones.add("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    set_signals(hass)
    options = copy.deepcopy(water_options(zone) if base == "water" else relay_options(zone))
    change(options)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def features_state(hass: HomeAssistant, entry: MockConfigEntry) -> State:
    registry = er.async_get(hass)
    entity = registry.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_features")
    assert entity is not None
    state = hass.states.get(entity)
    assert state is not None
    return state


def created(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """The keys of the entry's entities in the registry (a zone's without its zone)."""
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    return {
        e.unique_id.removeprefix(prefix)
        for e in er.async_entries_for_config_entry(registry, entry.entry_id)
    }


def missing_text(code: str, language: str) -> str:
    missing = TEXTS[language]["entity"]["sensor"]["features"]["state_attributes"]["missing"]
    return missing["state"][code]


@pytest.mark.parametrize(
    ("feature", "base", "change", "status", "code"),
    CASES,
    ids=[f"{case[0]}-{case[4]}-{index}" for index, case in enumerate(CASES)],
)
async def test_every_feature_names_its_missing_input(
    hass: HomeAssistant,
    zones: FakeZones,
    forecasts: FakeForecasts,
    feature: str,
    base: str,
    change: Change,
    status: str,
    code: str,
) -> None:
    """For each feature and each input it needs, taken away: the "Features" sensor shows the
    feature inactive (degraded where it works from less), names the input by its code and with
    its text in English — Home Assistant's language here — and Polish; the feature's entities
    are not created. Everything else given, the feature is available (the base)."""
    entry = await _setup(hass, zones, base, change)
    attributes = features_state(hass, entry).attributes
    assert attributes[feature] == status
    assert code in attributes[f"{feature}_missing"]
    assert missing_text(code, "en") in attributes[f"{feature}_missing_text"]
    assert missing_text(code, "pl")
    if status == "inactive" and feature != "verdict":  # the verdict says it itself (S-43)
        keys = created(hass, entry)
        for key in FEATURE_ENTITIES.get(_feature(feature), ()):
            assert not any(k == key or k.startswith(f"{key}_") for k in keys), key


def _feature(value: str) -> Any:
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature

    return Feature(value)


@pytest.mark.parametrize("base", ["water", "relay"])
async def test_with_every_input_every_feature_of_the_path_is_available(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts, base: str
) -> None:
    """The base of the table: everything given, each feature is available — except those of
    the other path (the relay's proof on a water path; the correction and a gateway's wall
    thermostat on the relay path) — and none is counted inactive but those."""
    entry = await _setup(hass, zones, base, lambda options: None)
    state = features_state(hass, entry)
    other = (
        {"relay_proof"} if base == "water" else {"comfort_correction", "wall_thermostat_fallback"}
    )
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature

    for feature in Feature:
        expected = "inactive" if feature.value in other else "available"
        assert state.attributes[feature.value] == expected, feature
    assert state.state == str(len(other))


async def test_a_signal_whose_entity_feeds_an_earlier_one_is_named_so(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """X5: the return mapped to the flow's entity is dropped; the features that need it name it
    with ``entity_for_two_signals``, and the text names the flow as the signal that kept it."""
    entry = await _setup(
        hass,
        zones,
        "water",
        setting("signals", "return", value=ENTITIES[Signal.FLOW]),
    )
    attributes = features_state(hass, entry).attributes
    assert attributes["condensing"] == "inactive"
    assert attributes["condensing_missing"] == ["entity_for_two_signals"]
    labels = TEXTS["en"]["options"]["step"]["freshness"]["data"]
    text = attributes["condensing_missing_text"]
    assert labels["return"] in text
    assert labels["flow"] in text
    phrase = missing_text("entity_for_two_signals", "en")
    assert text == f"{labels['return']}: {phrase} {labels['flow']}"
    assert "condensing_share" not in created(hass, entry)


async def test_an_input_unavailable_now_shows_its_feature_inactive(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """SCOPE §7: an input that is unavailable while the plugin runs makes its feature inactive
    on the "Features" sensor, named as unavailable now; its entities stay, showing unknown with
    their own reason — they come back with it. The weather entity unavailable: no forecast
    count."""
    entry = await _setup(hass, zones, "water", lambda options: None)
    registry = er.async_get(hass)
    snapshots = registry.async_get_entity_id(
        "sensor", DOMAIN, f"{entry.entry_id}_forecast_snapshots"
    )
    assert snapshots is not None  # created: a weather entity is configured
    registry.async_update_entity(snapshots, disabled_by=None)  # hidden by default
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    counted = hass.states.get(snapshots)
    assert counted is not None
    assert counted.state not in ("unknown", "unavailable")
    coordinator = entry.runtime_data
    hass.states.async_set(ENTITIES[Signal.FLOW], "unavailable")
    hass.states.async_set(WEATHER_ENTITY, "unavailable")
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = features_state(hass, entry)
    attributes = state.attributes
    assert attributes["hot_water"] == "inactive"
    assert attributes["hot_water_missing"] == ["flow"]
    flow = TEXTS["en"]["options"]["step"]["freshness"]["data"]["flow"]
    now = missing_text("unavailable_now", "en")
    assert attributes["hot_water_missing_text"] == f"{flow} ({now})"
    assert attributes["forecasts"] == "inactive"
    assert int(state.state) >= 2
    unknown = hass.states.get(snapshots)
    assert unknown is not None
    assert unknown.state == "unknown"  # the weather unavailable: no count shown
    hot = hass.states.get(
        registry.async_get_entity_id(
            "binary_sensor",
            DOMAIN,
            f"{entry.entry_id}_hot_water_{registry.async_get(zones.entities['living']).id}",
        )
        or ""
    )
    assert hot is not None
    assert hot.state == "unknown"  # the entity keeps its own rule: unknown, with its reason
    hass.states.async_set(ENTITIES[Signal.FLOW], "45", {"unit_of_measurement": "°C"})
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert features_state(hass, entry).attributes["hot_water"] == "available"


async def test_the_texts_follow_home_assistants_language(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """The texts are the instance's language, loaded at setup: Polish here; a language without
    a translation gets the English text."""
    hass.config.language = "pl"
    entry = await _setup(hass, zones, "water", without(Signal.FLAME))
    attributes = features_state(hass, entry).attributes
    assert attributes["cycles_missing_text"] == missing_text("flame", "pl")
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    hass.config.language = "de"
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    attributes = features_state(hass, entry).attributes
    assert attributes["cycles_missing_text"] == missing_text("flame", "en")


async def test_a_zone_without_its_valve_makes_the_low_flow_alarm_unavailable(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """While it runs: a zone that stops reporting its valve opening makes the low-flow warning
    inactive — its entity, created while the valves were known, unavailable; the opening back,
    it is available again."""
    entry = await _setup(hass, zones, "water", lambda options: None)
    registry = er.async_get(hass)
    alarm = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_alarm_low_flow"
    )
    assert alarm is not None
    state = hass.states.get(alarm)
    assert state is not None
    assert state.state != "unavailable"
    zones.set("living", hvac_action="heating", valve_open_percent=None, on_percent=0.6)
    hass.states.async_set(
        zones.entities["living"],
        "heat",
        {
            k: v
            for k, v in hass.states.get(zones.entities["living"]).attributes.items()  # type: ignore[union-attr]
            if k != "valve_open_percent"
        },
    )
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    assert features_state(hass, entry).attributes["low_flow_missing"] == ["valve_openings"]
    state = hass.states.get(alarm)
    assert state is not None
    assert state.state == "unavailable"
    zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(alarm)
    assert state is not None
    assert state.state != "unavailable"


async def test_a_zone_reporting_late_does_not_keep_an_entity_from_being_created(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    """Negative: at setup the zone does not report its valve opening yet (VT still starting).
    What only the running zones tell never keeps an entity from being created — nor removes it
    from the registry: the low-flow alarm is there, unavailable, and available once the valve
    reports."""
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw"}).add_to_hass(hass)
    zone = zones.add("living", hvac_action="heating", on_percent=0.6)  # no valve opening yet
    set_signals(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=water_options(zone))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert features_state(hass, entry).attributes["low_flow"] == "inactive"
    registry = er.async_get(hass)
    alarm = registry.async_get_entity_id(
        "binary_sensor", DOMAIN, f"{entry.entry_id}_alarm_low_flow"
    )
    assert alarm is not None
    state = hass.states.get(alarm)
    assert state is not None
    assert state.state == "unavailable"
    zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(alarm)
    assert state is not None
    assert state.state != "unavailable"
    assert features_state(hass, entry).attributes["low_flow"] == "available"
