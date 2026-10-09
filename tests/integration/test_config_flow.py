"""Config flow and options flow: simple and advanced paths, errors, level switch."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.config import EntryConfig
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import WEATHER_ENTITY, FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@pytest.fixture(autouse=True)
async def _mocked_integrations_stop_unloaded(hass: HomeAssistant):
    """The MQTT and OpenTherm Gateway entries a test marks as running are only marks: they are
    not running when Home Assistant stops, so it does not try to unload them. First, the reload
    a saved options flow starts is let finish: one still running when Home Assistant's own
    teardown unloads the entries would set the entry up again behind it, and its control clock
    would outlive the test — how fast the machine is would decide (Z1)."""
    yield
    await hass.async_block_till_done()
    for entry in hass.config_entries.async_entries():
        if entry.domain in ("mqtt", "opentherm_gw") and entry.state is ConfigEntryState.LOADED:
            entry.mock_state(hass, ConfigEntryState.NOT_LOADED)


@pytest.fixture
def entities(hass: HomeAssistant, zones: FakeZones) -> dict[str, str]:
    boiler = FakeBoiler(hass)
    boiler.set_many(
        {
            Signal.FLAME: False,
            Signal.FLOW: 30.0,
            Signal.RETURN: 28.0,
            Signal.PRESSURE: 1.5,
            Signal.FLUE_GAS: 30.0,
        }
    )
    hass.states.async_set(WEATHER_ENTITY, "cloudy", {"temperature": 5.0})
    hass.states.async_set("switch.fireplace", "off")
    hass.states.async_set(
        "sensor.heater_power", "0", {"device_class": "power", "unit_of_measurement": "W"}
    )
    hass.states.async_set("sensor.humidity", "50", {"device_class": "humidity"})
    # The MQTT integration set up and running: the OTGW firmware's path needs it (P-69).
    MockConfigEntry(domain="mqtt", state=ConfigEntryState.LOADED).add_to_hass(hass)
    return {
        "living": zones.add("living"),
        "bedroom": zones.add("bedroom"),
        "flame": boiler.entity(Signal.FLAME),
        "flow": boiler.entity(Signal.FLOW),
        "return": boiler.entity(Signal.RETURN),
        "pressure": boiler.entity(Signal.PRESSURE),
        "flue_gas": boiler.entity(Signal.FLUE_GAS),
    }


async def step(hass: HomeAssistant, result: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return await hass.config_entries.flow.async_configure(result["flow_id"], data)


# The setup's first panels (I6.1) answered for an installation as the tests before them had it.
PANEL_FOR_CLASS = {
    "flow_setpoint": ("other_entity", "full"),
    "on_off": ("relay", "on_off"),
    "read_only": ("read_only", "monitor"),
    # Never derived by the panels: an entry made before them may still have it.
    "curve_only": ("read_only", "monitor"),
}
PANEL_KEYS = ("connection", "control_mode", "heat_source", "type", "dhw_priority")


async def start_setup(
    hass: HomeAssistant,
    connection: str = "read_only",
    mode: str = "monitor",
    *,
    source: str = "gas",
    kind: str = "single",
    condensing: bool = True,
) -> dict[str, Any]:
    """A setup started, its first panels answered (I6.1): the name and level come next."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "connection"
    result = await step(
        hass, result, {"connection": connection, "heat_source": source, "type": kind}
    )
    assert result["step_id"] == "mode"
    answers: dict[str, Any] = {"control_mode": mode}
    if "condensing" in result["data_schema"].schema:
        answers["condensing"] = condensing
    result = await step(hass, result, answers)
    assert result["step_id"] == "name"
    return result


@pytest.mark.parametrize(
    ("language", "name"), [("en", "Boiler"), ("pl", "Kocioł"), ("xx", "Boiler")]
)
async def test_the_default_name_is_in_home_assistants_language(
    hass: HomeAssistant, language: str, name: str
) -> None:
    """PB-83: the device's default name comes from a translated text, so Polish entity names and
    IDs do not start with the English "Boiler". Negative: a language without a translation
    falls back to English."""
    hass.config.language = language
    result = await start_setup(hass)
    assert form_default(result, "name") == name


async def test_simple_flow_creates_an_entry(hass: HomeAssistant, entities: dict[str, str]) -> None:
    result = await start_setup(hass, kind="single_tank")
    assert result["type"] is FlowResultType.FORM
    result = await step(hass, result, {"name": "My boiler", "level": "simple"})
    assert result["step_id"] == "signals"
    assert "flue_gas" not in result["data_schema"].schema  # advanced only
    result = await step(
        hass,
        result,
        {
            "flame": entities["flame"],
            "flow": entities["flow"],
            "return": entities["return"],
            "weather": WEATHER_ENTITY,
        },
    )
    assert result["step_id"] == "boiler"
    result = await step(
        hass,
        result,
        {"boiler_min_power": 4.0, "boiler_max_power": 24.0},
    )
    assert result["step_id"] == "circuit"
    result = await step(hass, result, {"control": "unmixed_shared"})
    assert result["step_id"] == "zones"
    result = await step(hass, result, {"zones": [entities["living"]]})
    assert result["step_id"] == "zone"
    result = await step(hass, result, {"emitter": "radiator", "foreign_heat": ["switch.fireplace"]})
    assert result["step_id"] == "building"
    result = await step(hass, result, {"floor_area": 120, "insulation": "average"})
    assert result["step_id"] == "reference"
    result = await step(hass, result, {"strategy": "largest_deficit"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "My boiler"
    options = result["options"]
    assert options["level"] == "simple"
    assert options["signals"] == {
        "flame": entities["flame"],
        "flow": entities["flow"],
        "return": entities["return"],
    }
    assert options["weather"] == WEATHER_ENTITY
    assert options["parameters"] == {"boiler_min_power": 4.0, "boiler_max_power": 24.0}
    assert options["circuits"] == [{"id": "main", "control": "unmixed_shared"}]
    assert options["zones"] == [
        {
            "entity_id": entities["living"],
            "emitter": "radiator",
            "circuit": "main",
            "foreign_heat": [{"entity_id": "switch.fireplace", "kind": "switch"}],
        }
    ]
    assert options["building"] == {"floor_area": 120, "insulation": "average"}
    assert "monitor" not in options
    # I6.1: the panels' answers, the class and the hot-water kind following from them.
    assert options["boiler"] == {
        "connection": "read_only",
        "heat_source": "gas",
        "type": "single_tank",
        "dhw": "storage",
        "control_mode": "monitor",
        "condensing": True,
        "dhw_priority": True,
        "class": "read_only",
    }
    await hass.async_block_till_done()


async def test_advanced_flow_with_two_circuits(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    result = await start_setup(hass, "other_entity", "full", kind="combi")
    result = await step(hass, result, {"name": "Boiler", "level": "advanced"})
    assert "flue_gas" in result["data_schema"].schema
    result = await step(
        hass,
        result,
        {"flame": entities["flame"], "flow": entities["flow"], "flue_gas": entities["flue_gas"]},
    )
    result = await step(
        hass,
        result,
        {"modulation_scale": "capacity", "boiler_min_power": 30.0, "boiler_max_power": 20.0},
    )
    assert result["errors"] == {"base": "min_power_not_below_max"}
    result = await step(
        hass,
        result,
        {"modulation_scale": "capacity"},
    )
    assert result["step_id"] == "circuit"
    result = await step(hass, result, {"control": "passive_fixed", "add_another": False})
    assert result["errors"] == {"fixed_temperature": "fixed_temperature_missing"}
    result = await step(
        hass, result, {"control": "unmixed_shared", "max_flow": 45, "add_another": True}
    )
    assert result["step_id"] == "circuit"
    assert result["description_placeholders"] == {"number": "2"}
    result = await step(
        hass,
        result,
        {"control": "separate", "flow_entity": entities["return"], "add_another": False},
    )
    result = await step(hass, result, {"zones": [entities["living"], entities["bedroom"]]})
    assert "circuit" in result["data_schema"].schema
    result = await step(
        hass,
        result,
        {"circuit": "main", "emitter": "radiator", "foreign_heat": ["sensor.humidity"]},
    )
    assert result["errors"] == {"foreign_heat": "foreign_heat_unsupported"}
    result = await step(
        hass,
        result,
        {
            "circuit": "main",
            "emitter": "radiator",
            "foreign_heat": ["sensor.heater_power"],
            "power_threshold": 300,
        },
    )
    assert result["step_id"] == "zone"
    result = await step(
        hass, result, {"circuit": "circuit_2", "emitter": "underfloor", "foreign_heat": []}
    )
    assert result["step_id"] == "building"
    result = await step(hass, result, {"design_load_kw": 8.0, "heating_threshold": 16})
    result = await step(hass, result, {"strategy": "chosen_zone", "switch_margin": 0.5})
    assert result["errors"] == {"zone": "reference_zone_unknown"}
    result = await step(
        hass, result, {"strategy": "chosen_zone", "zone": entities["bedroom"], "switch_margin": 0.5}
    )
    assert result["step_id"] == "monitor"
    result = await step(
        hass,
        result,
        {
            "condensing_return": 52,
            "short_burn_min": 8,
            "monitoring_days": 10,
            "near_room_k": 3,
            "foreign_heat_hold_min": 30,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = result["options"]
    assert [c["id"] for c in options["circuits"]] == ["main", "circuit_2"]
    assert options["circuits"][1]["flow_entity"] == entities["return"]
    assert options["zones"][0]["foreign_heat"] == [
        {"entity_id": "sensor.heater_power", "kind": "power", "threshold": 300}
    ]
    assert options["zones"][1]["circuit"] == "circuit_2"
    assert options["reference_room"]["zone"] == entities["bedroom"]
    assert options["monitor"]["monitoring_days"] == 10
    await hass.async_block_till_done()


async def create_entry(
    hass: HomeAssistant,
    entities: dict[str, str],
    level: str,
    zones: tuple[str, ...] = (),
    boiler_class: str = "flow_setpoint",
    *,
    panels: bool = False,
) -> str:
    """An entry made through the config flow; its boiler class decides which control paths the
    options offer (X8): the setpoint paths for a flow-setpoint boiler, the relay for on/off.
    ``panels``: keep the first panels' answers (I6.1); without, they are taken out afterwards,
    so the entry is one made before them — its control step offering the paths by class."""
    connection, mode = PANEL_FOR_CLASS[boiler_class]
    result = await start_setup(hass, connection, mode)
    for data in (
        {"name": "Boiler", "level": level},
        {"flame": entities["flame"], "flow": entities["flow"]},
        {"modulation_scale": "capacity"} if level == "advanced" else {},
        {"control": "unmixed_shared"} | ({"add_another": False} if level == "advanced" else {}),
        {"zones": [entities[zone] for zone in zones]},
        *({"emitter": "radiator"} for _zone in zones),
        {},
        {"strategy": "average"},
    ):
        result = await step(hass, result, data)
    if level == "advanced":
        result = await step(
            hass,
            result,
            {
                "condensing_return": 55,
                "short_burn_min": 10,
                "monitoring_days": 7,
                "near_room_k": 3,
                "foreign_heat_hold_min": 60,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = result["result"]
    if not panels:
        boiler = {k: v for k, v in entry.options["boiler"].items() if k not in PANEL_KEYS}
        boiler["class"] = boiler_class
        hass.config_entries.async_update_entry(entry, options={**entry.options, "boiler": boiler})
        await hass.async_block_till_done()
    return entry.entry_id


async def test_options_flow_edits_one_section(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "simple")
    result = await hass.config_entries.options.async_init(entry_id)
    assert result["type"] is FlowResultType.MENU
    assert "monitor" not in result["menu_options"]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "signals"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"flame": entities["flame"], "flow": entities["flow"], "pressure": entities["pressure"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["signals"]["pressure"] == entities["pressure"]


async def test_switching_to_simple_can_restore_advanced_defaults(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "advanced")
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["boiler"]["modulation_scale"] == "capacity"

    async def switch(restore: bool) -> None:
        result = await hass.config_entries.options.async_init(entry_id)
        next_step = "level_hidden" if "level_hidden" in result["menu_options"] else "level"
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"next_step_id": next_step}
        )
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"level": "simple", "restore_defaults": restore}
        )
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    await switch(restore=False)
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["level"] == "simple"
    assert entry.options["boiler"]["modulation_scale"] == "capacity"  # kept, still active
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level_hidden" in menu["menu_options"]
    await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "level_hidden"}
    )
    await switch(restore=True)
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["boiler"]["modulation_scale"] == "capacity"  # a fact: kept
    # Tuning back to its defaults; the monitoring period stays (P-65).
    assert entry.options["monitor"] == {"monitoring_days": 7}
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level_hidden" in menu["menu_options"]  # the fact is still active, and hidden


def control_switch(hass: HomeAssistant, entry_id: str) -> str | None:
    from homeassistant.helpers import entity_registry as er

    return er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry_id}_control")


async def options_step(hass: HomeAssistant, result: dict[str, Any], data: dict[str, Any]):
    return await hass.config_entries.options.async_configure(result["flow_id"], data)


async def open_control(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "control" in menu["menu_options"]
    return await options_step(hass, menu, {"next_step_id": "control"})


async def test_control_through_the_gateway_at_the_simple_level(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    loaded_gateway(hass, "living_room_gw")
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    hass.states.async_set("binary_sensor.gw_central_heating", "on")
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    assert result["step_id"] == "control"
    result = await options_step(
        hass,
        result,
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "confirmed_entity": "sensor.gw_control_setpoint",
            "ch_confirmed_entity": "binary_sensor.gw_central_heating",
        },
    )
    assert result["step_id"] == "control_gateway"
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    assert result["step_id"] == "control_curve"
    assert "exponent" not in result["data_schema"].schema  # advanced only
    result = await options_step(
        hass,
        result,
        {
            "design_outdoor": -18,
            "design_flow": 52,
            "hard_min": 25,
            "hard_max": 65,
        },
    )
    # Y1 (decision 7): with a thermostat to take over, the reaction to an ignored write is
    # offered at the simple level too — alone: the return by itself is advanced.
    assert result["step_id"] == "control_alarms"
    assert {str(marker) for marker in result["data_schema"].schema} == {"write_ignored"}
    assert result["data_schema"]({})["write_ignored"] == "info"  # information by default
    result = await options_step(hass, result, {"write_ignored": "hand_back"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control == {
        "write_path": "opentherm_gw",
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "confirmed_entity": "sensor.gw_control_setpoint",
        "ch_confirmed_entity": "binary_sensor.gw_central_heating",
        "gateway_id": "living_room_gw",
        "curve": {"design_outdoor": -18, "design_flow": 52},
        "hard_min": 25,
        "hard_max": 65,
        "activation_delay_s": 0,  # VT's delay, confirmed by saving (decision 5)
        "alarm_reactions": {"write_ignored": "hand_back"},
    }
    switch = control_switch(hass, entry_id)
    assert switch is not None
    assert hass.states.get(switch).state == "off"  # off by default


async def test_control_with_an_entity_checks_the_hand_back(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    assert result["step_id"] == "control_entity"
    for write_type in ("unknown", "persistent"):  # nothing goes to the boiler's memory
        result = await options_step(
            hass,
            result,
            {"setpoint_entity": "number.boiler_flow", "write_type": write_type}
            | {"hand_back": "value", "hand_back_value": 0},
        )
        assert result["errors"] == {"write_type": "write_type_not_supported"}
    details = {"setpoint_entity": "number.boiler_flow", "write_type": "held"}
    result = await options_step(
        hass,
        result,
        details | {"hand_back": "value", "hand_back_value": 0, "ch_entity": "switch.heating"},
    )
    assert result["errors"] == {"ch_write_type": "ch_write_type_not_supported"}
    result = await options_step(hass, result, details | {"hand_back": "value"})
    assert result["errors"] == {"hand_back_value": "hand_back_value_missing"}
    result = await options_step(
        hass, result, details | {"hand_back": "value", "hand_back_value": 0}
    )  # 0 means different things on different devices: its effect is declared
    assert result["errors"] == {"hand_back_value_effect": "hand_back_value_effect_missing"}
    result = await options_step(hass, result, details | {"hand_back": "switch"})
    assert result["errors"] == {"hand_back_entity": "hand_back_entity_missing"}
    result = await options_step(
        hass,
        result,
        details
        | {"hand_back": "value", "hand_back_value": 0, "hand_back_value_effect": "own_control"},
    )
    assert result["step_id"] == "control_curve"
    curve = {"design_outdoor": -15, "design_flow": 50}
    result = await options_step(hass, result, curve | {"hard_min": 50, "hard_max": 40})
    assert result["errors"] == {"hard_max": "hard_limits_out_of_order"}
    result = await options_step(hass, result, curve | {"hard_min": 25, "hard_max": 60})
    assert result["step_id"] == "control_alarms"  # a value declared "own control" (Y1)
    result = await options_step(hass, result, {"write_ignored": "info"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["hand_back"] == "value"
    assert control["hand_back_value"] == 0
    assert control["hand_back_value_effect"] == "own_control"
    assert control["write_type"] == "held"


async def test_control_at_the_advanced_level_and_back(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {
            "write_path": "otgw_mqtt",
            "topology": "gateway_standalone",
            "thermostat_kind": "none",
            "confirmed_entity": "sensor.fake_boiler_ch_setpoint",
        },
    )
    assert result["step_id"] == "control_mqtt"
    result = await options_step(hass, result, {"mqtt_top": "OTGW", "mqtt_node": "otgw-1"})
    assert result["step_id"] == "control_curve"
    result = await options_step(
        hass,
        result,
        {
            "design_outdoor": -15,
            "design_flow": 55,
            "hard_min": 25,
            "hard_max": 70,
            "room": 21,
            "exponent": 1.25,
            "offset": 1,
            "ceiling_band": 8,
            "frost_limit": 5,
            "frost_release": 7,
        },
    )
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"count_threshold": 9})
    assert result["errors"] == {"count_threshold": "count_threshold_above_zones"}
    result = await options_step(hass, result, {"count_threshold": 0})
    assert result["errors"] == {"count_threshold": "no_demand_criterion"}
    result = await options_step(hass, result, {"ramp_k_per_min": 0.5, "off_setpoint": 12})
    assert result["step_id"] == "control_alarms"
    # Another controller always makes the plugin step aside: no reaction to choose (S-11); and
    # stand-alone an ignored write only informs (decision 7): the return by itself alone.
    assert {str(marker) for marker in result["data_schema"].schema} == {
        "return_after_outside_change"
    }
    result = await options_step(hass, result, {"return_after_outside_change": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    control = entry.options["control"]
    assert control["curve"] == {
        "design_outdoor": -15,
        "design_flow": 55,
        "room": 21,
        "exponent": 1.25,
        "offset": 1,
    }
    assert control["ramp_k_per_min"] == 0.5
    assert control["off_setpoint"] == 12
    assert "daily_cap" not in control  # nothing is written to the boiler's memory
    assert control["alarm_reactions"] == {}
    assert entry.runtime_data.config.control.loop.control.ramp_k_per_min == 0.5

    # Back to simple with defaults restored: only the simple control fields remain.
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "level"})
    result = await options_step(hass, result, {"level": "simple", "restore_defaults": True})
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "min_burn_min" not in control
    assert "alarm_reactions" not in control
    assert control["curve"] == {"design_outdoor": -15, "design_flow": 55}

    # "No control" removes the section.
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "none"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert "control" not in hass.config_entries.async_get_entry(entry_id).options
    assert control_switch(hass, entry_id) is None  # its entities are removed too


async def test_the_form_no_longer_offers_a_reaction_to_outside_changes(
    hass: HomeAssistant,
) -> None:
    """S-11, S-30, S-62 (decision 7): another controller writing to the boiler always makes the
    plugin step aside, and every monitor alarm only informs. The alarm step offers no choice for
    them, even where an earlier version stored one, and its description says so; saving the
    step drops them. Where a thermostat takes over, the ignored write's reaction is offered."""
    import json
    from pathlib import Path

    from custom_components.vtherm_smart_boiler import config_flow as flow

    options: dict[str, Any] = {
        "level": "advanced",
        "control": {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "alarm_reactions": {
                "outside_change": "info",
                "pressure_low": "hand_back",
                "write_ignored": "hand_back",
            },
        },
    }
    schema = flow.control_alarms_schema(options)
    shown_fields = {str(marker) for marker in schema.schema}
    assert shown_fields == {"write_ignored", "return_after_outside_change"}
    shown = schema({})
    assert shown["write_ignored"] == "hand_back"  # the user's choice, shown
    flow.apply_control_alarms(options, shown)
    assert options["control"]["alarm_reactions"] == {"write_ignored": "hand_back"}
    translations = Path(flow.__file__).parent / "translations"
    for language, sentences in (
        (
            "en",
            (
                "Another controller writing to the boiler always makes the plugin step aside; "
                "it never fights it.",
                "Other alarms only inform; the plugin stops heating only while the boiler "
                "itself reports a fault that stops it.",
            ),
        ),
        (
            "pl",
            (
                "Inny sterownik piszący do kotła zawsze sprawia, że wtyczka ustępuje; nigdy z "
                "nim nie walczy.",
                "Pozostałe alarmy tylko informują;",
            ),
        ),
    ):
        texts = json.loads((translations / f"{language}.json").read_text(encoding="utf-8"))
        step = texts["options"]["step"]["control_alarms"]
        assert set(step["data"]) == {
            "write_ignored",
            "return_after_outside_change",
            "return_after_switch_hand_back",  # SB-36: the switch method's own opt-in
        }
        assert set(step["data_description"]) == set(step["data"])
        for sentence in sentences:
            assert sentence in step["description"]


MQTT_CONTROL = {
    "write_path": "otgw_mqtt",
    "topology": "gateway_standalone",
    "thermostat_kind": "none",
    "confirmed_entity": "sensor.fake_boiler_ch_setpoint",
}
ADVANCED_CURVE = {
    "design_outdoor": -15,
    "design_flow": 55,
    "hard_min": 25,
    "hard_max": 70,
    "room": 20,
    "exponent": 1.3,
    "offset": 0,
    "ceiling_band": 10,
    "frost_limit": 5,
    "frost_release": 7,
}


async def to_control_behaviour(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, MQTT_CONTROL)
    result = await options_step(hass, result, {"mqtt_top": "OTGW", "mqtt_node": "otgw-1"})
    result = await options_step(hass, result, ADVANCED_CURVE)
    assert result["step_id"] == "control_behaviour"
    return result


async def test_off_must_be_at_least_1k_below_the_hard_minimum(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-43: "off" sent as a low setpoint — on the entity path without a heating switch —
    within a kelvin of the lowest water temperature would not be seen as a change — refused:
    24.5 against 25; 24 is allowed. A gateway switches heating with CH: no check there (PB-69)."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_behaviour(hass, entry_id)
    result = await options_step(hass, result, {"off_setpoint": 24.5})
    assert result["step_id"] == "control_alarms"  # the gateway's CH: "off" is no setpoint
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    result = await options_step(
        hass,
        result,
        {
            "setpoint_entity": "number.boiler_flow",
            "write_type": "expiring",
            "hand_back": "value",
            "hand_back_value_effect": "own_control",
            "hand_back_value": 40,
        },
    )
    result = await options_step(hass, result, ADVANCED_CURVE)
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"off_setpoint": 24.5})
    assert result["errors"] == {"off_setpoint": "off_setpoint_not_below_hard_min"}
    result = await options_step(hass, result, {"off_setpoint": 24})
    assert result["step_id"] == "control_alarms"


async def test_the_return_option_needs_a_second_confirmation(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 6: the return by itself after another controller is off by default and switched
    on only with a second confirmation — without the tick, an error; with it, saved. Switching
    it off again needs none."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_behaviour(hass, entry_id)
    result = await options_step(hass, result, {"off_setpoint": 10})
    assert result["step_id"] == "control_alarms"
    shown = result["data_schema"]({})
    assert shown["return_after_outside_change"] is False  # off by default
    result = await options_step(hass, result, {"return_after_outside_change": True})
    assert result["step_id"] == "control_return_confirm"
    result = await options_step(hass, result, {"understood": False})
    assert result["errors"] == {"understood": "return_needs_confirmation"}
    result = await options_step(hass, result, {"understood": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["control"]["return_after_outside_change"] is True
    assert entry.runtime_data.config.control.return_after_outside_change

    result = await to_control_behaviour(hass, entry_id)
    result = await options_step(hass, result, {"off_setpoint": 10})
    result = await options_step(hass, result, {"return_after_outside_change": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY  # off: no confirmation
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "return_after_outside_change" not in control


async def to_switch_alarms(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """The advanced control flow through an entity with the external-control switch's
    hand-back, up to the alarm step."""
    result = await to_control_entity(hass, entry_id)
    hass.states.async_set("switch.external_control", "off")
    details = {
        "setpoint_entity": BOILER_FLOW,
        "write_type": "held",
        "hand_back": "switch",
        "hand_back_entity": "switch.external_control",
        "hand_back_entity_write_type": "held",
    }
    result = await options_step(hass, result, details)
    assert result["step_id"] == "control_curve"
    result = await options_step(hass, result, ADVANCED_CURVE)
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"off_setpoint": 10})
    assert result["step_id"] == "control_alarms"
    return result


async def test_the_switch_hand_backs_return_is_its_own_opt_in(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """SB-36 (decision 10): with the external-control switch's hand-back the alarm step offers
    the return by itself after it as its own option, off by default; switched on, it is
    confirmed a second time like the general one, and saved; switched off, dropped. Negatives:
    a hand-back value offers no such option, and an earlier tick left from the switch is
    dropped once the method is no longer the switch."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_switch_alarms(hass, entry_id)
    shown = result["data_schema"]({})
    assert shown["return_after_switch_hand_back"] is False  # off by default
    assert shown["return_after_outside_change"] is False
    answers = {"return_after_outside_change": True, "return_after_switch_hand_back": True}
    result = await options_step(hass, result, answers)
    assert result["step_id"] == "control_return_confirm"
    result = await options_step(hass, result, {"understood": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["control"]["return_after_switch_hand_back"] is True
    assert entry.runtime_data.config.control.return_after_switch_hand_back

    # The general return already on: the switch's own opt-in still asks for the confirmation.
    result = await to_switch_alarms(hass, entry_id)
    off = {"return_after_outside_change": True, "return_after_switch_hand_back": False}
    result = await options_step(hass, result, off)
    assert result["type"] is FlowResultType.CREATE_ENTRY  # off: no confirmation
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "return_after_switch_hand_back" not in control
    result = await to_switch_alarms(hass, entry_id)
    result = await options_step(hass, result, answers)
    assert result["step_id"] == "control_return_confirm"
    result = await options_step(hass, result, {"understood": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    # Away from the switch: no such option, and the old tick goes.
    result = await to_control_behaviour(hass, entry_id)
    result = await options_step(hass, result, {"off_setpoint": 10})
    assert result["step_id"] == "control_alarms"
    assert "return_after_switch_hand_back" not in result["data_schema"]({})
    result = await options_step(hass, result, {"return_after_outside_change": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["return_after_outside_change"] is True
    assert "return_after_switch_hand_back" not in control


async def test_the_thermostats_own_setpoint_is_not_the_read_back(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The optional field for an OpenTherm thermostat's own request is refused where it is the
    setpoint read-back; the optional restart indicator is kept (Q3.7)."""
    hass.states.async_set("sensor.thermostat_ch_setpoint", "40", {"device_class": "temperature"})
    hass.states.async_set("sensor.gateway_reboot_count", "3")
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    control = MQTT_CONTROL | {
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
    }
    result = await options_step(
        hass, result, control | {"thermostat_setpoint_entity": control["confirmed_entity"]}
    )
    assert result["errors"] == {
        "thermostat_setpoint_entity": "thermostat_setpoint_same_as_read_back"
    }
    result = await options_step(
        hass,
        result,
        control
        | {
            "thermostat_setpoint_entity": "sensor.thermostat_ch_setpoint",
            "restart_entity": "sensor.gateway_reboot_count",
        },
    )
    assert result["step_id"] == "control_mqtt"
    result = await options_step(hass, result, {"mqtt_top": "OTGW", "mqtt_node": "otgw-1"})
    result = await options_step(
        hass, result, {"design_outdoor": -15, "design_flow": 55, "hard_min": 25, "hard_max": 70}
    )
    assert result["step_id"] == "control_alarms"  # a thermostat takes over (Y1)
    result = await options_step(hass, result, {"write_ignored": "info"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert options["thermostat_setpoint_entity"] == "sensor.thermostat_ch_setpoint"
    assert options["restart_entity"] == "sensor.gateway_reboot_count"


@pytest.mark.parametrize(
    ("attributes", "refused"),
    [
        ({"unit_of_measurement": "°C", "step": 5, "min": 20, "max": 80}, True),
        ({"unit_of_measurement": "°C", "step": 1, "min": 20, "max": 80}, False),
        ({"unit_of_measurement": "°F", "step": 2, "min": 50, "max": 190}, True),  # 1.1 K
        ({"unit_of_measurement": "°F", "step": 1, "min": 50, "max": 190}, False),  # 0.56 K
    ],
)
async def test_setpoint_step_over_1k_is_refused_in_the_form(
    hass: HomeAssistant, entities: dict[str, str], attributes: dict[str, Any], refused: bool
) -> None:
    """T-55 (P-15): a setpoint entity whose step is above 1 K (in its own unit: above 1.8 °F)
    is refused — a value rounded to it could read back beyond the tolerance, as ignored."""
    hass.states.async_set("number.boiler_flow", "40", attributes)
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    result = await options_step(
        hass,
        result,
        {
            "setpoint_entity": "number.boiler_flow",
            "write_type": "held",
            "ch_write_type": "unknown",
            "hand_back": "value",
            "hand_back_value": 30,
            "hand_back_value_effect": "own_control",
        },
    )
    if refused:
        assert result["errors"] == {"setpoint_entity": "setpoint_step_too_coarse"}
    else:
        assert result["step_id"] == "control_curve"


async def test_control_limits_must_suit_the_setpoint_entity(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    hass.states.async_set(
        "number.boiler_flow", "45", {"unit_of_measurement": "°C", "min": 20, "max": 60}
    )
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    details = {
        "setpoint_entity": "number.boiler_flow",
        "write_type": "expiring",
        "hand_back": "value",
        "hand_back_value_effect": "own_control",
    }
    result = await options_step(hass, result, details | {"hand_back_value": 5})
    assert result["errors"] == {"hand_back_value": "hand_back_value_out_of_range"}
    result = await options_step(hass, result, details | {"hand_back_value": 30})
    curve = {
        "design_outdoor": -15,
        "design_flow": 50,
        "room": 20,
        "offset": 0,
        "ceiling_band": 10,
        "frost_limit": 5,
        "frost_release": 7,
    }
    result = await options_step(hass, result, curve | {"hard_min": 25, "hard_max": 70})
    assert result["errors"] == {"hard_max": "limits_outside_entity_range"}
    result = await options_step(hass, result, curve | {"hard_min": 25, "hard_max": 60})
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"off_setpoint": 10})
    assert result["errors"] == {"off_setpoint": "off_setpoint_outside_entity_range"}
    result = await options_step(hass, result, {"off_setpoint": 20})
    assert result["step_id"] == "control_alarms"


async def test_off_is_not_checked_as_a_setpoint_with_a_heating_switch(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """PB-69: with a heating switch, "off" is never written as a setpoint, so the advanced
    behaviour step does not require it inside the entity's range or 1 K below the lowest water
    temperature — before, an entity whose minimum is the lowest (20 °C) left no "off" that
    passed, and control could not be saved at the advanced level. Negative: without the
    switch both checks stay (``test_control_limits_must_suit_the_setpoint_entity``)."""
    hass.states.async_set(
        "number.boiler_flow", "45", {"unit_of_measurement": "°C", "min": 20, "max": 60}
    )
    hass.states.async_set(CH_SWITCH, "on")
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    details = {
        "setpoint_entity": "number.boiler_flow",
        "write_type": "expiring",
        "ch_entity": CH_SWITCH,
        "ch_write_type": "held",
        "hand_back": "value",
        "hand_back_value_effect": "own_control",
        "hand_back_value": 30,
    }
    result = await options_step(hass, result, details)
    curve = {
        "design_outdoor": -15,
        "design_flow": 50,
        "room": 20,
        "offset": 0,
        "ceiling_band": 10,
        "frost_limit": 5,
        "frost_release": 7,
    }
    result = await options_step(hass, result, curve | {"hard_min": 20, "hard_max": 60})
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"off_setpoint": 20})
    assert result["step_id"] == "control_alarms"


async def test_freshness_limits_are_set_per_signal(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The one way to catch a source that freezes without going unavailable (an MQTT entity
    without availability): an age limit the user sets."""
    entry_id = await create_entry(hass, entities, "simple")
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "freshness" in menu["menu_options"]
    result = await options_step(hass, menu, {"next_step_id": "freshness"})
    assert result["step_id"] == "freshness"
    assert set(result["data_schema"].schema) == {"flame", "flow"}  # the mapped signals
    result = await options_step(hass, result, {"flow": 15})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["freshness"] == {"flow": 900.0}


async def test_the_weather_entity_gets_a_freshness_limit_of_its_own(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-41 (X2): with a weather entity set, the freshness step offers its own age limit, stored
    in seconds beside the signals' and read apart from them; none by default. Without a weather
    entity the field is not offered, and a limit left from before goes with the next save."""
    entry_id = await create_entry(hass, entities, "simple")
    signals = {"flame": entities["flame"], "flow": entities["flow"]}

    async def save(step_id: str, data: dict[str, Any]) -> dict[str, Any]:
        menu = await hass.config_entries.options.async_init(entry_id)
        result = await options_step(hass, menu, {"next_step_id": step_id})
        shown = result
        result = await options_step(hass, result, data)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        return shown

    await save("signals", signals | {"weather": WEATHER_ENTITY})
    form = await save("freshness", {"flow": 15, "weather": 90})
    assert set(form["data_schema"].schema) == {"flame", "flow", "weather"}
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry.options["freshness"] == {"flow": 900.0, "weather": 5400.0}
    config = EntryConfig.from_options(entry.options)
    assert config.freshness == {Signal.FLOW: 900.0}
    assert config.weather_max_age_s == 5400.0
    form = await save("freshness", {"flow": 15})
    assert EntryConfig.from_options(entry.options).weather_max_age_s is None  # emptied: none
    await save("signals", signals)  # the weather entity removed
    form = await save("freshness", {"flow": 15})
    assert set(form["data_schema"].schema) == {"flame", "flow"}
    assert entry.options["freshness"] == {"flow": 900.0}


async def test_a_setpoint_entity_must_be_in_a_temperature_unit(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    hass.states.async_set("number.boiler_flow", "40", {"unit_of_measurement": "%"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    assert result["step_id"] == "control_entity"
    result = await options_step(
        hass,
        result,
        {
            "setpoint_entity": "number.boiler_flow",
            "write_type": "held",
            "ch_write_type": "unknown",
            "hand_back": "timeout",
        },
    )
    assert result["errors"] == {"setpoint_entity": "setpoint_unit_not_supported"}


async def test_one_entry_per_home_assistant(hass: HomeAssistant, entities: dict[str, str]) -> None:
    """P36: two entries could control one boiler; the plugin serves one boiler per Home
    Assistant."""
    await create_entry(hass, entities, "simple")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"


async def test_a_problem_found_at_the_end_is_shown_on_its_step(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P37: a problem the last check finds keeps the wizard's answers: its step is shown again
    with the error, instead of an abort (or an unhandled error for an implausible building)."""
    result = await start_setup(hass)
    for data in (
        {"name": "Boiler", "level": "advanced"},
        {"flame": entities["flame"], "flow": entities["flow"]},
        {"modulation_scale": "range"},
        {"control": "unmixed_shared", "add_another": False},
        {"zones": []},
        {"design_load_kw": 200.0, "design_outdoor": -15.0},  # 5.7 kW/K: implausible
        {},
        {},
    ):  # fmt: skip
        result = await step(hass, result, data)
        if result["type"] is not FlowResultType.FORM or result.get("errors"):
            break
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "building"
    assert result["errors"] == {"base": "implausible_parameter"}
    result = await step(hass, result, {"design_load_kw": 12.0, "design_outdoor": -15.0})
    while result["type"] is FlowResultType.FORM:
        result = await step(hass, result, {})  # the rest as it was
    assert result["type"] is FlowResultType.CREATE_ENTRY


def _rich_options(entities: dict[str, str]) -> dict[str, Any]:
    """An installation set up at the advanced level, now shown at the simple one."""
    return {
        "level": "simple",
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {
            "class": "read_only", "dhw": "none", "condensing": True, "modulation_scale": "capacity"
        },
        "circuits": [
            {"id": "main", "control": "unmixed_shared", "flow_entity": entities["return"]},
            {"id": "circuit_2", "control": "unmixed_shared"},
        ],
        "zones": [
            {"entity_id": entities["living"], "emitter": "radiator", "circuit": "main",
             "reference_output_w": 1500, "foreign_heat": []},
            {"entity_id": entities["bedroom"], "emitter": "radiator", "circuit": "circuit_2",
             "foreign_heat": [
                 {"entity_id": "sensor.heater_power", "kind": "power", "threshold": 300}
             ]},
        ],
        "reference_room": {"strategy": "largest_deficit", "switch_margin": 0.8},
        "monitor": {"monitoring_days": 14.0, "near_room_k": 4.0},
    }  # fmt: skip


async def _entry(hass: HomeAssistant, options: dict[str, Any]) -> str:
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.entry_id


async def _section(hass: HomeAssistant, entry_id: str, section: str, *answers: dict):
    result = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, result, {"next_step_id": section})
    for answer in answers:
        result = await options_step(hass, result, answer)
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return hass.config_entries.async_get_entry(entry_id).options


async def test_the_simple_level_keeps_what_it_does_not_show(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P38: at the simple level an edit changes only what its form shows — the second circuit,
    a circuit's flow sensor, a zone's emitter size, a source's threshold and the reference
    room's margin stay."""
    entry_id = await _entry(hass, _rich_options(entities))
    options = await _section(hass, entry_id, "circuit", {"control": "unmixed_shared"})
    assert [c["id"] for c in options["circuits"]] == ["main", "circuit_2"]
    assert options["circuits"][0]["flow_entity"] == entities["return"]
    options = await _section(
        hass,
        entry_id,
        "zones",
        {"zones": [entities["living"], entities["bedroom"]]},
        {"circuit": "main", "emitter": "radiator", "foreign_heat": []},
        {"circuit": "circuit_2", "emitter": "radiator", "foreign_heat": ["sensor.heater_power"]},
    )
    living, bedroom = options["zones"]
    assert living["reference_output_w"] == 1500
    assert bedroom["foreign_heat"][0]["threshold"] == 300
    options = await _section(hass, entry_id, "reference", {"strategy": "largest_deficit"})
    assert options["reference_room"]["switch_margin"] == 0.8


async def test_restoring_defaults_keeps_the_installation(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P38: "restore defaults" resets tuning, never facts about the installation."""
    options = _rich_options(entities) | {"level": "advanced"}
    entry_id = await _entry(hass, options)
    options = await _section(hass, entry_id, "level", {"level": "simple", "restore_defaults": True})
    assert options["boiler"]["modulation_scale"] == "capacity"
    assert [c["id"] for c in options["circuits"]] == ["main", "circuit_2"]
    assert options["circuits"][0]["flow_entity"] == entities["return"]
    assert options["zones"][0]["reference_output_w"] == 1500
    assert options["zones"][1]["foreign_heat"][0]["threshold"] == 300
    assert "switch_margin" not in options["reference_room"]  # tuning
    assert options["monitor"] == {"monitoring_days": 14.0}  # the period stays (P-65)


async def test_hidden_settings_are_those_that_differ_from_defaults(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P74: a stored value equal to its default is nothing hidden."""
    options = _rich_options(entities)
    options["circuits"] = [{"id": "main", "control": "unmixed_shared"}]
    options["zones"] = [{"entity_id": entities["living"], "emitter": "radiator", "circuit": "main"}]
    options["boiler"]["modulation_scale"] = "range"
    options["reference_room"] = {"strategy": "largest_deficit", "switch_margin": 0.3}
    options["monitor"] = {"monitoring_days": 7.0, "near_room_k": 3.0}
    entry_id = await _entry(hass, options)
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level" in menu["menu_options"]
    assert "level_hidden" not in menu["menu_options"]


async def test_control_needs_a_read_back_and_a_topology_that_suits_the_path(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P74, P85: an incomplete control configuration is refused where it is entered."""
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    read_back = {"confirmed_entity": "sensor.gw_control_setpoint"}
    for answer, error in (
        ({"write_path": "opentherm_gw", "topology": "gateway_with_thermostat"},
         {"confirmed_entity": "confirmed_entity_missing"}),
        ({"write_path": "opentherm_gw"} | read_back, {"topology": "topology_missing"}),
        ({"write_path": "opentherm_gw", "topology": "virtual"} | read_back,
         {"topology": "topology_not_for_path"}),
        ({"write_path": "entity", "topology": "monitor_mode"} | read_back,
         {"topology": "topology_no_control"}),
    ):  # fmt: skip
        result = await open_control(hass, entry_id)
        result = await options_step(hass, result, answer)
        assert result["step_id"] == "control"
        assert result["errors"] == error, answer


async def test_the_gateway_and_the_mqtt_topics_are_checked(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P79: a gateway ID no OpenTherm Gateway has, or an MQTT topic with wildcards or spaces,
    would make every write fail. The gateway field offers the gateways set up, and takes no
    other value (P-106)."""
    from homeassistant.data_entry_flow import InvalidData

    loaded_gateway(hass, "living_room_gw")
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    base = {
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "confirmed_entity": "sensor.gw_control_setpoint",
    }
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "opentherm_gw"} | base)
    with pytest.raises(InvalidData):
        await options_step(hass, result, {"gateway_id": "no_such_gateway"})
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "otgw_mqtt"} | base)
    for answer, error in (
        ({"mqtt_top": "OTGW/#", "mqtt_node": "otgw-1"}, {"mqtt_top": "mqtt_topic_invalid"}),
        ({"mqtt_top": "OTGW", "mqtt_node": "otgw 1"}, {"mqtt_node": "mqtt_topic_invalid"}),
        ({"mqtt_top": "OTGW", "mqtt_node": " "}, {"mqtt_node": "mqtt_topic_invalid"}),
    ):
        result = await options_step(hass, result, answer)
        assert result["errors"] == error, answer
    # H10: spaces around a valid topic are dropped, not published to.
    result = await options_step(hass, result, {"mqtt_top": " OTGW ", "mqtt_node": "otgw-1 "})
    assert result["step_id"] == "control_curve"
    result = await options_step(hass, result, {"design_outdoor": -15, "design_flow": 55})
    while result["type"] == "form":
        result = await options_step(hass, result, {})
    await hass.async_block_till_done(wait_background_tasks=True)  # the reload it causes
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert (control["mqtt_top"], control["mqtt_node"]) == ("OTGW", "otgw-1")


def test_editing_a_circuit_offers_the_next_one() -> None:
    """H11: at the advanced level, editing the first of two circuits offers the second next;
    left as offered, no circuit is dropped."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    options = {"level": "advanced", "circuits": [{"id": "main"}, {"id": "second"}]}
    offered = flow.circuit_schema(options, options["circuits"][0], more=True)
    marker = next(m for m in offered.schema if str(m) == "add_another")
    assert marker.default() is True
    last = flow.circuit_schema(options, options["circuits"][1])
    assert next(m for m in last.schema if str(m) == "add_another").default() is False


def _filters(schema: Any, key: str) -> list[dict[str, Any]]:
    for marker, field in schema.schema.items():
        if str(marker) == key:
            return field.config["filter"]
    raise KeyError(key)


def test_signal_fields_follow_the_d2_table() -> None:
    """P99: a CH setpoint is a temperature; modulation is checked for its unit on submit."""
    from custom_components.vtherm_smart_boiler.config_flow import signals_schema

    schema = signals_schema({"level": "advanced"})
    assert _filters(schema, "ch_setpoint") == [
        {"domain": ["sensor", "number"], "device_class": ["temperature"]}
    ]


async def test_modulation_must_be_in_percent(hass: HomeAssistant, entities: dict[str, str]) -> None:
    hass.states.async_set("sensor.boiler_power", "12", {"unit_of_measurement": "kW"})
    hass.states.async_set("sensor.boiler_modulation", "40", {"unit_of_measurement": "%"})
    result = await start_setup(hass)
    result = await step(hass, result, {"name": "Boiler", "level": "simple"})
    signals = {"flame": entities["flame"], "flow": entities["flow"]}
    result = await step(hass, result, signals | {"modulation": "sensor.boiler_power"})
    assert result["errors"] == {"modulation": "modulation_not_percent"}
    result = await step(hass, result, signals | {"modulation": "sensor.boiler_modulation"})
    assert result["step_id"] == "boiler"


def test_a_temperature_sensor_as_foreign_heat_needs_the_advanced_level() -> None:
    """Its threshold is entered at the advanced level only, and it cannot work without one: at
    the simple level it is not offered."""
    from custom_components.vtherm_smart_boiler.config_flow import zone_schema

    temperature = {"domain": ["sensor"], "device_class": ["temperature"]}
    simple = _filters(zone_schema({"level": "simple"}, {}), "foreign_heat")
    advanced = _filters(zone_schema({"level": "advanced"}, {}), "foreign_heat")
    assert temperature not in simple
    assert temperature in advanced
    assert {"domain": ["sensor"], "device_class": ["power"]} in simple


# --- X3: control needs a zone (S-04); criteria a zone must feed (P-14); the own room controller -


async def test_control_needs_at_least_one_zone(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """S-04: without a VT zone nothing can ask for heat — the control form refuses; "no
    control" stays possible."""
    entry_id = await create_entry(hass, entities, "simple")
    result = await open_control(hass, entry_id)
    answer = {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.flow"}
    result = await options_step(hass, result, answer)
    assert result["errors"] == {"base": "no_zones"}
    result = await options_step(hass, result, {"write_path": "none"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def to_behaviour_with(
    hass: HomeAssistant, entities: dict[str, str], zones: tuple[str, ...]
) -> dict[str, Any]:
    entry_id = await create_entry(hass, entities, "advanced", zones)
    return await to_control_behaviour(hass, entry_id)


async def test_a_criterion_no_zone_can_feed_is_refused_in_the_form(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    """P-14: zones readable, and none publishes a device power (VT publishes 0 when none is set)
    or an opening: that threshold could never be reached — refused. Every zone unavailable: it
    cannot be told, so accepted."""
    for zone_id in ("living", "bedroom"):
        zones.set(zone_id, power_manager={"device_power": 0.0, "power_unit": "kW"})
    result = await to_behaviour_with(hass, entities, ("living", "bedroom"))
    result = await options_step(hass, result, {"count_threshold": 0, "power_threshold_kw": 1.0})
    assert result["errors"] == {"power_threshold_kw": "power_criterion_no_zone"}
    zones.set("bedroom", power_manager={"device_power": 1.5, "power_unit": "kW"})
    result = await options_step(hass, result, {"count_threshold": 1, "power_threshold_kw": 1.0})
    assert result["step_id"] == "control_alarms"


async def test_a_count_of_0_is_refused_while_a_zone_feeds_no_criterion(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    """PB-23 (a): a count of 0 with only a power threshold, the bedroom with a device power and
    the living room without one: the living room could never ask for heat — refused, naming it.
    With an opening threshold too it feeds the opening: accepted; so is a count of 1. Negative:
    a zone that cannot be read (unavailable) is not judged."""
    zones.set("living", power_manager={"device_power": 0.0, "power_unit": "kW"})
    zones.set("bedroom", power_manager={"device_power": 1.5, "power_unit": "kW"})
    result = await to_behaviour_with(hass, entities, ("living", "bedroom"))
    result = await options_step(hass, result, {"count_threshold": 0, "power_threshold_kw": 1.0})
    assert result["errors"] == {"count_threshold": "zone_feeds_no_criterion"}
    living = hass.states.get(zones.entities["living"])
    assert living is not None
    assert result["description_placeholders"] == {"zone": living.name}
    answer = {"count_threshold": 0, "power_threshold_kw": 1.0, "opening_threshold": 50}
    result = await options_step(hass, result, answer)
    assert result["step_id"] == "control_alarms"


async def test_a_count_of_0_skips_a_zone_that_cannot_be_read(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    zones.set("bedroom", power_manager={"device_power": 1.5, "power_unit": "kW"})
    result = await to_behaviour_with(hass, entities, ("living", "bedroom"))
    zones.set("living", "unavailable")
    result = await options_step(hass, result, {"count_threshold": 0, "power_threshold_kw": 1.0})
    assert result["step_id"] == "control_alarms"


async def test_an_opening_criterion_no_zone_can_feed_is_refused_in_the_form(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    for zone_id in ("living", "bedroom"):  # over_climate: no opening, no duty cycle
        zones.set(zone_id, on_percent=None, power_percent=None)
    result = await to_behaviour_with(hass, entities, ("living", "bedroom"))
    result = await options_step(hass, result, {"count_threshold": 1, "opening_threshold": 50})
    assert result["errors"] == {"opening_threshold": "opening_criterion_no_zone"}
    zones.set("living", on_percent=0.0)
    result = await options_step(hass, result, {"count_threshold": 1, "opening_threshold": 50})
    assert result["step_id"] == "control_alarms"


async def test_a_criterion_is_accepted_while_no_zone_can_be_read(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    """Negative: with every zone unavailable — or not started by VT yet — nothing can be told:
    the threshold is kept, and the run-time alarm tells if no zone feeds it."""
    result = await to_behaviour_with(hass, entities, ("living", "bedroom"))
    zones.set("living", "unavailable")
    zones.set("bedroom", "off", is_ready=None, specific_states=None)  # VT's placeholder
    result = await options_step(
        hass, result, {"count_threshold": 0, "power_threshold_kw": 1.0, "opening_threshold": 50}
    )
    assert result["step_id"] == "control_alarms"


async def test_the_own_room_controller_tick_is_offered_on_the_entity_and_relay_paths_only(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Answers F and M: shown on the entity path with the virtual topology (X8 adds the relay
    path); not on either gateway path, nor on the entity path with a gateway topology."""
    MockConfigEntry(domain="opentherm_gw", data={"id": "gw"}).add_to_hass(hass)
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))

    async def fields(answer: dict[str, Any]) -> set[str]:
        result = await open_control(hass, entry_id)
        result = await options_step(hass, result, answer)
        return {str(marker) for marker in result["data_schema"].schema}

    read_back = {"confirmed_entity": "number.boiler_flow"}
    entity = await fields({"write_path": "entity", "topology": "virtual"} | read_back)
    assert "own_room_controller" in entity
    from custom_components.vtherm_smart_boiler.config_flow import control_entity_schema

    for control in ({}, {"write_path": "entity"}, {"write_path": "relay?", "topology": "virtual"}):
        schema = control_entity_schema({"control": control})
        assert "own_room_controller" not in {str(marker) for marker in schema.schema}
    for topology, kind in (
        ("gateway_standalone", "none"),
        ("gateway_with_thermostat", "opentherm"),
    ):
        answer = {"topology": topology, "thermostat_kind": kind} | read_back
        shown = await fields({"write_path": "entity"} | answer)
        assert "setpoint_entity" in shown  # the writable-entity step, reached
        assert "own_room_controller" not in shown
        for path in ("opentherm_gw", "otgw_mqtt"):
            shown = await fields({"write_path": path} | answer)
            assert "own_room_controller" not in shown


async def test_the_tick_is_refused_with_a_hand_back_value_that_stops_heating(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """A hand-back value that stops heating leaves nothing for the boiler's own room controller
    to take over. Accepted with a hand-back that does not; left out, it is not ticked."""
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    details = {"setpoint_entity": "number.boiler_flow", "write_type": "held"}
    stops = {"hand_back": "value", "hand_back_value": 0, "hand_back_value_effect": "heating_stops"}
    result = await options_step(hass, result, details | stops | {"own_room_controller": True})
    assert result["errors"] == {"own_room_controller": "own_room_controller_but_heating_stops"}
    own = stops | {"hand_back_value_effect": "own_control"}
    result = await options_step(hass, result, details | own | {"own_room_controller": True})
    assert result["step_id"] == "control_curve"
    result = await options_step(
        hass, result, {"design_outdoor": -15, "design_flow": 50, "hard_min": 25, "hard_max": 60}
    )
    assert result["step_id"] == "control_alarms"  # the boiler's own control takes over (Y1)
    result = await options_step(hass, result, {"write_ignored": "info"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["own_room_controller"] is True
    # Another topology: the step no longer shows it, and saving it drops the tick.
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {
            "write_path": "entity",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "confirmed_entity": "number.boiler_flow",
        },
    )
    result = await options_step(hass, result, details | own)
    assert result["step_id"] == "control_curve"
    result = await options_step(
        hass, result, {"design_outdoor": -15, "design_flow": 50, "hard_min": 25, "hard_max": 60}
    )
    assert result["step_id"] == "control_alarms"  # a value declared "own control" (Y1)
    result = await options_step(hass, result, {"write_ignored": "info"})
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "own_room_controller" not in control


# --- X4: VT's activation delay (decision 5), the circuit alarm (decision 10), a zone's
# "closes when off" kept (decision 4) ------------------------------------------------------------


def form_default(result: dict[str, Any], key: str) -> Any:
    """What a form offers for a field: its default, else its suggested value."""
    for marker in result["data_schema"].schema:
        if str(marker) == key:
            if callable(marker.default):
                return marker.default()
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"{key} is not in the form")


async def to_control_curve(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """The gateway path up to its curve step — stand-alone, so no alarm step follows at the
    simple level (Y1: the reaction to an ignored write is offered only where a thermostat or
    the boiler's own control takes over)."""
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_standalone",
            "thermostat_kind": "none",
            "confirmed_entity": "sensor.gw_control_setpoint",
        },
    )
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    assert result["step_id"] == "control_curve"
    return result


def loaded_gateway(hass: HomeAssistant, gateway_id: str) -> MockConfigEntry:
    """An OpenTherm Gateway set up and running in Home Assistant."""
    entry = MockConfigEntry(
        domain="opentherm_gw", data={"id": gateway_id}, state=ConfigEntryState.LOADED
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def gateway(hass: HomeAssistant) -> None:
    loaded_gateway(hass, "living_room_gw")
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})


CURVE_ANSWERS = {"design_outdoor": -15, "design_flow": 55, "hard_min": 25, "hard_max": 70}


@pytest.mark.parametrize(
    ("vt", "offered"),
    [
        ({"central_boiler_activation_delay_sec": 120}, 120),
        ({}, 0),  # the key missing
        (None, 0),  # VT not there
        ({"central_boiler_activation_delay_sec": "a lot"}, 0),  # not a number
        ({"central_boiler_activation_delay_sec": 900}, 0),  # outside VT's own range
    ],
    ids=["vt_120", "no_key", "no_vt", "not_a_number", "out_of_range"],
)
@pytest.mark.usefixtures("gateway")
async def test_the_delay_is_pre_filled_from_vts_central_entry(
    hass: HomeAssistant, entities: dict[str, str], vt: dict[str, Any] | None, offered: int
) -> None:
    """Decision 5: the curve step — shown at the simple level — offers VT's stored delay, else
    0; the user confirms it by saving, and a stored value of the plugin's wins afterwards."""
    if vt is not None:
        central = {"thermostat_type": "thermostat_central_config"}
        MockConfigEntry(domain="versatile_thermostat", data=central | vt).add_to_hass(hass)
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await to_control_curve(hass, entry_id)
    assert "exponent" not in result["data_schema"].schema  # the simple level
    assert form_default(result, "activation_delay_s") == offered
    result = await options_step(hass, result, CURVE_ANSWERS | {"activation_delay_s": offered})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["activation_delay_s"] == offered
    # The plugin's own stored value wins over VT's.
    result = await to_control_curve(hass, entry_id)
    result = await options_step(hass, result, CURVE_ANSWERS | {"activation_delay_s": 30})
    await hass.async_block_till_done()
    result = await to_control_curve(hass, entry_id)
    assert form_default(result, "activation_delay_s") == 30


@pytest.mark.usefixtures("gateway")
async def test_the_delay_is_refused_outside_0_to_600(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    from homeassistant.data_entry_flow import InvalidData

    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await to_control_curve(hass, entry_id)
    for bad in (-10, 610):
        with pytest.raises(InvalidData):
            await options_step(hass, result, CURVE_ANSWERS | {"activation_delay_s": bad})
    result = await options_step(hass, result, CURVE_ANSWERS | {"activation_delay_s": 600})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options
    assert EntryConfig.from_options(options).control.loop.control.activation_delay_s == 600.0


@pytest.mark.usefixtures("gateway")
async def test_restoring_defaults_keeps_the_activation_delay(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Not an advanced setting: "restore defaults" keeps it."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_curve(hass, entry_id)
    result = await options_step(hass, result, CURVE_ANSWERS | {"activation_delay_s": 120})
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {})
    result = await options_step(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "level"})
    await options_step(hass, result, {"level": "simple", "restore_defaults": True})
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["activation_delay_s"] == 120


async def open_circuit(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    menu = await hass.config_entries.options.async_init(entry_id)
    return await options_step(hass, menu, {"next_step_id": "circuit"})


def circuits_of(hass: HomeAssistant, entry_id: str) -> list[dict[str, Any]]:
    return hass.config_entries.async_get_entry(entry_id).options["circuits"]


async def test_the_circuit_alarm_is_pre_filled_and_must_be_above_the_maximum(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 10, advanced level: the alarm temperature and time are pre-filled when the
    maximum is first entered — the maximum + 5 K and 10 min — never empty, and not changed by
    themselves later; the alarm must be above the maximum."""
    entry_id = await create_entry(hass, entities, "advanced")
    result = await open_circuit(hass, entry_id)
    assert "max_flow_alarm" in result["data_schema"].schema
    assert "max_flow_alarm_min" in result["data_schema"].schema
    answer = {"control": "unmixed_shared", "add_another": False}
    await options_step(hass, result, answer | {"max_flow": 40})
    await hass.async_block_till_done()
    assert circuits_of(hass, entry_id)[0] | {} == {
        "id": "main",
        "control": "unmixed_shared",
        "max_flow": 40,
        "max_flow_alarm": 45,
        "max_flow_alarm_min": 10,
    }
    result = await open_circuit(hass, entry_id)
    assert form_default(result, "max_flow_alarm") == 45
    assert form_default(result, "max_flow_alarm_min") == 10
    result = await options_step(hass, result, answer | {"max_flow": 40, "max_flow_alarm": 40})
    assert result["errors"] == {"max_flow_alarm": "max_flow_alarm_not_above_max"}
    result = await options_step(
        hass, result, answer | {"max_flow": 40, "max_flow_alarm": 48, "max_flow_alarm_min": 20}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    circuit = circuits_of(hass, entry_id)[0]
    assert (circuit["max_flow_alarm"], circuit["max_flow_alarm_min"]) == (48, 20)
    # A new maximum leaves the alarm as the user set it; one not above it is refused.
    result = await open_circuit(hass, entry_id)
    kept = answer | {"max_flow_alarm": 48, "max_flow_alarm_min": 20}
    result = await options_step(hass, result, kept | {"max_flow": 48})
    assert result["errors"] == {"max_flow_alarm": "max_flow_alarm_not_above_max"}
    result = await options_step(hass, result, kept | {"max_flow": 42})
    await hass.async_block_till_done()
    assert circuits_of(hass, entry_id)[0]["max_flow_alarm"] == 48
    # Without a maximum there is no alarm.
    result = await open_circuit(hass, entry_id)
    await options_step(hass, result, answer)
    await hass.async_block_till_done()
    assert circuits_of(hass, entry_id)[0] == {"id": "main", "control": "unmixed_shared"}


async def test_the_simple_level_pre_fills_the_circuit_alarm_it_does_not_show(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """At the simple level the alarm's fields are hidden: the pre-fill is stored with the
    maximum, kept as it is, and a maximum that reaches the hidden alarm temperature is refused
    on the maximum's field; the level shows hidden settings only once they differ from it."""
    entry_id = await create_entry(hass, entities, "simple")
    result = await open_circuit(hass, entry_id)
    assert "max_flow_alarm" not in result["data_schema"].schema
    await options_step(hass, result, {"control": "unmixed_shared", "max_flow": 40})
    await hass.async_block_till_done()
    circuit = circuits_of(hass, entry_id)[0]
    assert (circuit["max_flow_alarm"], circuit["max_flow_alarm_min"]) == (45, 10)
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level" in menu["menu_options"]  # the pre-fill is no hidden setting
    result = await open_circuit(hass, entry_id)
    result = await options_step(hass, result, {"control": "unmixed_shared", "max_flow": 44})
    await hass.async_block_till_done()
    assert circuits_of(hass, entry_id)[0]["max_flow_alarm"] == 45  # not changed by itself
    result = await open_circuit(hass, entry_id)
    result = await options_step(hass, result, {"control": "unmixed_shared", "max_flow": 45})
    assert result["errors"] == {"max_flow": "max_flow_alarm_not_above_max"}


async def test_the_zone_step_keeps_a_stored_closes_when_off(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 4's per-zone option: saving the zone step without touching it keeps it."""
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    entry = hass.config_entries.async_get_entry(entry_id)
    zones = [dict(zone) | {"closes_when_off": True} for zone in entry.options["zones"]]
    hass.config_entries.async_update_entry(entry, options=dict(entry.options) | {"zones": zones})
    await hass.async_block_till_done()
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "zones"})
    result = await options_step(hass, result, {"zones": [entities["living"]]})
    result = await options_step(hass, result, {"emitter": "radiator", "foreign_heat": []})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    zone = hass.config_entries.async_get_entry(entry_id).options["zones"][0]
    assert zone["closes_when_off"] is True


# --- X5: configuration refused in the form --------------------------------------------------------

BOILER_FLOW = "number.boiler_flow"
CH_SWITCH = "switch.boiler_ch"


async def to_control_entity(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    """The entity path, with the virtual topology, up to its writable-entity step."""
    hass.states.async_set(BOILER_FLOW, "45", {"unit_of_measurement": "°C"})
    hass.states.async_set(CH_SWITCH, "on")
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": BOILER_FLOW},
    )
    assert result["step_id"] == "control_entity"
    return result


async def test_same_switch_for_heating_and_external_control_is_refused(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """T-38 (P-03): the heating switch picked again as the external-control switch would be
    switched on and off by every hand-back for ever — refused on the later field. Negative: the
    external switch left empty is "missing", as before."""
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await to_control_entity(hass, entry_id)
    details = {
        "setpoint_entity": BOILER_FLOW,
        "write_type": "held",
        "ch_entity": CH_SWITCH,
        "ch_write_type": "held",
        "hand_back": "switch",
        "hand_back_entity_write_type": "held",
    }
    result = await options_step(hass, result, details | {"hand_back_entity": CH_SWITCH})
    assert result["errors"] == {"hand_back_entity": "hand_back_switch_is_heating_switch"}
    result = await options_step(hass, result, details)
    assert result["errors"] == {"hand_back_entity": "hand_back_entity_missing"}
    hass.states.async_set("switch.external_control", "off")
    result = await options_step(
        hass, result, details | {"hand_back_entity": "switch.external_control"}
    )
    assert result["step_id"] == "control_curve"


@pytest.mark.parametrize("field", ["ch_entity", "hand_back_entity"])
async def test_a_switch_a_vt_zone_drives_is_refused_on_the_entity_path(
    hass: HomeAssistant, entities: dict[str, str], field: str
) -> None:
    """PB-54: on the entity path the heating switch and the external-control switch are checked
    against the switches VT thermostats drive, as the relay is — VT's toggles would read as
    another controller. Negative: a switch no zone drives is accepted."""
    from homeassistant.helpers import entity_registry as er

    entry_id = await create_entry(hass, entities, "simple", ("living",))
    vt = MockConfigEntry(
        domain="versatile_thermostat", data={"underlying_entity_ids": ["switch.room_heater"]}
    )
    vt.add_to_hass(hass)
    er.async_get(hass).async_update_entity(entities["bedroom"], config_entry_id=vt.entry_id)
    hass.states.async_set("switch.room_heater", "off")
    hass.states.async_set("switch.external_control", "off")
    result = await to_control_entity(hass, entry_id)
    details = {
        "setpoint_entity": BOILER_FLOW,
        "write_type": "held",
        "ch_entity": CH_SWITCH,
        "ch_write_type": "held",
        "hand_back": "switch",
        "hand_back_entity": "switch.external_control",
        "hand_back_entity_write_type": "held",
    }
    result = await options_step(hass, result, details | {field: "switch.room_heater"})
    assert result["errors"] == {field: "entity_used_by_zone"}
    result = await options_step(hass, result, details)
    assert result["step_id"] == "control_curve"


async def test_one_entity_for_two_signals_is_refused(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """T-32 (P-16): one entity for two signals is refused on the later field in the form's
    order; at the simple level, a clash with a stored advanced signal shows on the field that
    is shown. Negative: the optional fields left empty are accepted."""
    result = await start_setup(hass)
    result = await step(hass, result, {"name": "Boiler", "level": "advanced"})
    signals = {"flame": entities["flame"], "flow": entities["flow"]}
    result = await step(hass, result, signals | {"ch_active": entities["flame"]})
    assert result["errors"] == {"ch_active": "entity_for_two_signals"}
    result = await step(hass, result, signals | {"return": entities["flow"]})
    assert result["errors"] == {"return": "entity_for_two_signals"}
    result = await step(hass, result, signals)
    assert result["step_id"] == "boiler"
    # A signal the simple level does not show keeps what is stored.
    hass.states.async_set("binary_sensor.boiler_ch", "off")
    options = _rich_options(entities) | {
        "signals": signals | {"ch_active": "binary_sensor.boiler_ch"}
    }
    entry_id = await _entry(hass, options)
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "signals"})
    result = await options_step(hass, result, signals | {"flame": "binary_sensor.boiler_ch"})
    assert result["errors"] == {"flame": "entity_for_two_signals"}


async def test_options_save_problem_returns_to_its_step(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """T-12: the reference room is zone A; zone A removed and saved — the reference form shows
    ``reference_zone_unknown``; another strategy saves."""
    options = _rich_options(entities) | {
        "reference_room": {"strategy": "chosen_zone", "zone": entities["living"]}
    }
    entry_id = await _entry(hass, options)
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "zones"})
    result = await options_step(hass, result, {"zones": [entities["bedroom"]]})
    result = await options_step(
        hass, result, {"circuit": "circuit_2", "emitter": "radiator", "foreign_heat": []}
    )
    assert result["step_id"] == "reference"
    assert result["errors"] == {"base": "reference_zone_unknown"}
    result = await options_step(hass, result, {"strategy": "largest_deficit"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    saved = hass.config_entries.async_get_entry(entry_id).options
    assert [zone["entity_id"] for zone in saved["zones"]] == [entities["bedroom"]]
    assert saved["reference_room"]["strategy"] == "largest_deficit"


@pytest.mark.usefixtures("gateway")
async def test_frost_release_must_be_above_the_limit(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """T-37: at the advanced level on a gateway path, a release no warmer than the limit."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_curve(hass, entry_id)
    result = await options_step(
        hass, result, ADVANCED_CURVE | {"frost_limit": 7, "frost_release": 7}
    )
    assert result["errors"] == {"frost_release": "frost_release_not_above_limit"}
    result = await options_step(
        hass, result, ADVANCED_CURVE | {"frost_limit": 7, "frost_release": 7.5}
    )
    assert result["step_id"] == "control_behaviour"


async def test_off_must_stay_below_the_lowest_water_temperature_at_every_level(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-25: without a heating switch "off" is a low setpoint, at least 1 K below the lowest
    water temperature — checked on the curve step at the simple level, against the default
    "off" and a stored one, and on the level form after "restore defaults". Negative: with a
    heating switch "off" is no setpoint, and nothing is checked."""
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    details = {
        "setpoint_entity": BOILER_FLOW,
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value": 30,
        "hand_back_value_effect": "own_control",
    }
    curve = {"design_outdoor": -15, "design_flow": 50, "hard_max": 60}
    result = await to_control_entity(hass, entry_id)
    result = await options_step(hass, result, details)
    result = await options_step(hass, result, curve | {"hard_min": 10.5})  # "off": 10 °C
    assert result["errors"] == {"hard_min": "off_setpoint_not_below_hard_min"}
    result = await options_step(hass, result, curve | {"hard_min": 11})
    assert result["step_id"] == "control_alarms"  # the boiler's own control takes over (Y1)
    result = await options_step(hass, result, {"write_ignored": "info"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    control = dict(entry.options["control"]) | {"off_setpoint": 12}  # stored at advanced
    hass.config_entries.async_update_entry(
        entry, options=dict(entry.options) | {"control": control}
    )
    await hass.async_block_till_done()
    result = await to_control_entity(hass, entry_id)
    result = await options_step(hass, result, details)
    result = await options_step(hass, result, curve | {"hard_min": 12.5})
    assert result["errors"] == {"hard_min": "off_setpoint_not_below_hard_min"}
    # After "restore defaults": "off" back at 10 °C next to a lowest water temperature of 10.5.
    control = dict(entry.options["control"]) | {"off_setpoint": 5, "hard_min": 10.5}
    options = dict(entry.options) | {"level": "advanced", "control": control}
    hass.config_entries.async_update_entry(entry, options=options)
    await hass.async_block_till_done()
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "level"})
    result = await options_step(hass, result, {"level": "simple", "restore_defaults": True})
    assert result["step_id"] == "level"
    assert result["errors"] == {"base": "off_setpoint_not_below_hard_min"}
    assert hass.config_entries.async_get_entry(entry_id).options["control"]["off_setpoint"] == 5
    # Negative: with a heating switch nothing is checked, at either place.
    switched = details | {"ch_entity": CH_SWITCH, "ch_write_type": "held"}
    result = await to_control_entity(hass, entry_id)
    result = await options_step(hass, result, switched)
    result = await options_step(
        hass,
        result,
        ADVANCED_CURVE | curve | {"hard_min": 10.5, "frost_limit": 5, "frost_release": 7},
    )
    assert result["step_id"] == "control_behaviour"
    result = await options_step(hass, result, {"off_setpoint": 5})
    result = await options_step(hass, result, {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "level"})
    result = await options_step(hass, result, {"level": "simple", "restore_defaults": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_a_disabled_gateway_is_not_offered_and_mqtt_must_be_set_up(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-69: a disabled ``opentherm_gw`` entry is not offered, and its ID typed gives
    ``gateway_unknown``; one not running gives ``gateway_not_set_up``; the MQTT path needs the
    MQTT integration running."""
    from homeassistant.config_entries import ConfigEntryDisabler

    MockConfigEntry(
        domain="opentherm_gw", data={"id": "disabled_gw"}, disabled_by=ConfigEntryDisabler.USER
    ).add_to_hass(hass)
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    base = {
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "confirmed_entity": "sensor.gw_control_setpoint",
    }
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "opentherm_gw"} | base)
    assert result["step_id"] == "control_gateway"
    offered = next(v for m, v in result["data_schema"].schema.items() if str(m) == "gateway_id")
    assert offered is str  # nothing offered: the disabled gateway is not
    result = await options_step(hass, result, {"gateway_id": "disabled_gw"})
    assert result["errors"] == {"gateway_id": "gateway_unknown"}
    idle = MockConfigEntry(domain="opentherm_gw", data={"id": "idle_gw"})  # not loaded
    idle.add_to_hass(hass)
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "opentherm_gw"} | base)
    offered = next(v for m, v in result["data_schema"].schema.items() if str(m) == "gateway_id")
    assert offered.config["options"] == ["idle_gw"]
    result = await options_step(hass, result, {"gateway_id": "idle_gw"})
    assert result["errors"] == {"gateway_id": "gateway_not_set_up"}
    idle.mock_state(hass, ConfigEntryState.LOADED)
    result = await options_step(hass, result, {"gateway_id": "idle_gw"})
    assert result["step_id"] == "control_curve"
    mqtt = hass.config_entries.async_entries("mqtt")[0]
    mqtt.mock_state(hass, ConfigEntryState.NOT_LOADED)
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "otgw_mqtt"} | base)
    answer = {"mqtt_top": "OTGW", "mqtt_node": "otgw-1"}
    result = await options_step(hass, result, answer)
    assert result["errors"] == {"base": "mqtt_not_set_up"}
    mqtt.mock_state(hass, ConfigEntryState.LOADED)
    result = await options_step(hass, result, answer)
    assert result["step_id"] == "control_curve"


@pytest.mark.parametrize("section", ["building", "reference", "signals"])
async def test_an_unknown_stored_value_is_a_form_error(
    hass: HomeAssistant, entities: dict[str, str], section: str
) -> None:
    """P-70: options holding a boiler class this version does not know; saving any section
    shows the first panel with ``invalid_boiler`` — no exception — where the connection is
    chosen again, which decides the class (I6.1; not passed off as a known one); then the options
    save."""
    options = {
        "level": "simple",
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {"class": "steam", "dhw": "none", "condensing": True},
        "reference_room": {"strategy": "average"},
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    answers = {
        "building": {},
        "reference": {"strategy": "average"},
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
    }
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": section})
    result = await options_step(hass, result, answers[section])
    assert result["step_id"] == "connection"
    assert result["errors"] == {"base": "invalid_boiler"}
    assert form_default(result, "connection") is None
    result = await options_step(
        hass, result, {"connection": "read_only", "heat_source": "gas", "type": "single"}
    )
    assert result["step_id"] == "mode"
    result = await options_step(hass, result, {"control_mode": "monitor", "condensing": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["boiler"]["class"] == "read_only"


async def test_options_that_cannot_be_read_are_a_form_error(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-70, PB-06: a section of another shape entirely is named (``invalid_signals``) on its
    step, never an exception; the signals step shows and saves."""
    options = {"level": "simple", "signals": "flame and flow"}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "building"})
    result = await options_step(hass, result, {})
    assert result["step_id"] == "signals"
    assert result["errors"] == {"base": "invalid_signals"}
    result = await options_step(
        hass, result, {"flame": entities["flame"], "flow": entities["flow"]}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    ("level", "section", "value", "step", "code"),
    [
        ("advanced", "monitor", [], "monitor", "invalid_monitor"),
        ("simple", "control", ["opentherm_gw"], "control", "invalid_control"),
        ("simple", "zones", "climate.living", "zones", "invalid_zone"),
        ("simple", "circuits", {"id": "main", "max_flow": 40}, "circuit", "invalid_circuit"),
    ],
)
async def test_a_section_of_another_shape_is_shown_from_empty_first(
    hass: HomeAssistant,
    entities: dict[str, str],
    level: str,
    section: str,
    value: object,
    step: str,
    code: str,
) -> None:
    """PB-06: a section stored in another shape (``monitor: []``, a list as the control section)
    neither breaks the menu nor its step: the save first shows that step, from empty, with its
    reason — the section is never dropped unseen; the next save goes through."""
    signals = {"flame": entities["flame"], "flow": entities["flow"]}
    options = {"level": level, "signals": signals, section: value}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    assert menu["type"] is FlowResultType.MENU
    result = await options_step(hass, menu, {"next_step_id": "freshness"})
    result = await options_step(hass, result, {})
    assert result["step_id"] == step
    assert result["errors"] == {"base": code}
    if section == "monitor":
        result = await options_step(hass, result, {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert isinstance(entry.options["monitor"], dict)


async def test_a_value_of_another_shape_inside_a_section_is_a_form_error(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-70: a value of another shape inside a section that no section check names — a list as
    a parameter — is ``unreadable_options`` on the signals step, never an exception at a save."""
    signals = {"flame": entities["flame"], "flow": entities["flow"]}
    options = {"level": "simple", "signals": signals, "parameters": {"loss_coefficient": [1]}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "freshness"})
    result = await options_step(hass, result, {})
    assert result["step_id"] == "signals"
    assert result["errors"] == {"base": "unreadable_options"}


async def test_entities_are_checked_on_the_server(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-79: what the selectors filter in the browser is checked again on submit — a sensor as
    the flame, a climate of another integration as a zone, a switch as the reference room.
    Negative: an entity of the right domain that has not reported yet is accepted."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    other = registry.async_get_or_create(
        "climate", "generic_thermostat", "hall", suggested_object_id="hall"
    ).entity_id
    hass.states.async_set(other, "heat")
    result = await start_setup(hass)
    result = await step(hass, result, {"name": "Boiler", "level": "simple"})
    result = await step(hass, result, {"flame": entities["flow"], "flow": entities["flow"]})
    assert result["errors"] == {"flame": "entity_not_suitable"}
    result = await step(hass, result, {"flame": entities["flame"], "flow": "sensor.humidity"})
    assert result["errors"] == {"flow": "entity_not_suitable"}  # reported, not a temperature
    result = await step(
        hass, result, {"flame": entities["flame"], "flow": "sensor.not_reported_yet"}
    )
    assert result["step_id"] == "boiler"  # no state yet: its domain suffices
    result = await step(hass, result, {})
    result = await step(hass, result, {"control": "unmixed_shared"})
    assert result["step_id"] == "zones"
    result = await step(hass, result, {"zones": [entities["living"], other]})
    assert result["errors"] == {"zones": "zone_not_vt"}
    result = await step(hass, result, {"zones": [entities["living"]]})
    result = await step(hass, result, {"emitter": "radiator", "foreign_heat": ["sensor.humidity"]})
    assert result["errors"] == {"foreign_heat": "foreign_heat_unsupported"}
    result = await step(hass, result, {"emitter": "radiator", "foreign_heat": []})
    result = await step(hass, result, {})
    assert result["step_id"] == "reference"
    result = await step(hass, result, {"strategy": "chosen_zone", "zone": other})
    assert result["errors"] == {"zone": "zone_not_vt"}
    result = await step(hass, result, {"strategy": "chosen_zone", "zone": entities["living"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["options"]["signals"]["flow"] == "sensor.not_reported_yet"


@pytest.mark.parametrize(
    ("answers", "errors"),
    [
        ({"room": 22, "design_flow": 26}, {"design_flow": "design_flow_too_low"}),
        ({"design_flow": 75}, {"design_flow": "design_flow_above_hard_max"}),
        ({"room": 18, "design_outdoor": 9}, {"design_outdoor": "design_outdoor_too_warm"}),
        ({"hard_min": 50, "design_flow": 50}, {"hard_min": "hard_min_not_below_design_flow"}),
        ({}, None),  # the defaults with a design flow of 55 °C pass
    ],
    ids=["flow_over_room", "flow_over_max", "outdoor_under_room", "min_under_flow", "defaults"],
)
@pytest.mark.usefixtures("gateway")
async def test_curve_cross_field_checks(
    hass: HomeAssistant,
    entities: dict[str, str],
    answers: dict[str, Any],
    errors: dict[str, str] | None,
) -> None:
    """P-68 (provisional, K4): the design flow at least 5 K above the curve's room and not
    above the highest water temperature, the design outdoor temperature at least 10 K below the
    room, the lowest water temperature below the design flow."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_curve(hass, entry_id)
    result = await options_step(hass, result, ADVANCED_CURVE | answers)
    if errors is None:
        assert result["step_id"] == "control_behaviour"
    else:
        assert result["errors"] == errors


def test_the_gateway_field_takes_no_custom_value() -> None:
    """P-106: a gateway the integration does not know was always refused: none can be typed."""
    from custom_components.vtherm_smart_boiler.config_flow import control_gateway_schema

    schema = control_gateway_schema({}, ["gw"])
    field = next(v for m, v in schema.schema.items() if str(m) == "gateway_id")
    assert field.config["custom_value"] is False
    assert field.config["options"] == ["gw"]


async def test_a_circuit_with_zones_cannot_be_removed(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-64: two circuits, a zone on the second; the advanced circuit step ended after the
    first is refused with ``circuit_has_zones`` and nothing saved; adding the second again
    saves."""
    options = _rich_options(entities) | {"level": "advanced"}
    entry_id = await _entry(hass, options)
    result = await open_circuit(hass, entry_id)
    first = {"control": "unmixed_shared", "flow_entity": entities["return"]}
    result = await options_step(hass, result, first | {"add_another": False})
    assert result["step_id"] == "circuit"
    assert result["errors"] == {"base": "circuit_has_zones"}
    assert result["description_placeholders"] == {"number": "1"}
    assert circuits_of(hass, entry_id) == options["circuits"]  # nothing saved
    result = await options_step(hass, result, first | {"add_another": True})
    assert result["description_placeholders"] == {"number": "2"}
    result = await options_step(hass, result, {"control": "unmixed_shared", "add_another": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert [c["id"] for c in circuits_of(hass, entry_id)] == ["main", "circuit_2"]


async def test_restoring_defaults_keeps_the_monitoring_days(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-65: "restore defaults" resets the monitor's thresholds but keeps its periods."""
    monitor = {"monitoring_days": 14.0, "verdict_window_days": 30, "near_room_k": 4.0}
    options = _rich_options(entities) | {"level": "advanced", "monitor": monitor}
    entry_id = await _entry(hass, options)
    options = await _section(hass, entry_id, "level", {"level": "simple", "restore_defaults": True})
    assert options["monitor"] == {"monitoring_days": 14.0, "verdict_window_days": 30}
    config = EntryConfig.from_options(options).monitor
    assert (config.monitoring_days, config.monitor.verdict_window_days) == (14.0, 30)
    assert config.near_room_k == 3.0  # a threshold: back to its default


def controlled_options(entities: dict[str, str]) -> dict[str, Any]:
    """Options with control configured, and nothing in them blocking it."""
    return {
        "level": "simple",
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {"class": "flow_setpoint", "dhw": "none", "condensing": True},
        "circuits": [{"id": "main", "control": "unmixed_shared"}],
        "zones": [{"entity_id": entities["living"], "emitter": "radiator", "circuit": "main"}],
        "reference_room": {"strategy": "average"},
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "living_room_gw",
            "confirmed_entity": "sensor.gw_control_setpoint",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "curve": {"design_outdoor": -15, "design_flow": 55},
        },
    }


async def test_an_edit_that_would_block_control_is_confirmed_first(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Open after R6 #3: control configured and allowed; the first panels answered "another
    integration, read only" (I6.1: the class and the mode follow) asks first, with the blocker's
    text. Not confirmed: back to the menu, nothing saved; confirmed: saved. Negative: an edit
    that adds no blocker saves at once."""
    from custom_components.vtherm_smart_boiler.config_flow import options_blockers

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=controlled_options(entities)
    )
    entry.add_to_hass(hass)
    assert options_blockers(entry.options) == []
    read_only = {"connection": "read_only", "heat_source": "gas", "type": "single"}
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "connection"})
    assert form_default(result, "connection") == "opentherm_gw"  # its write path names it
    result = await options_step(hass, result, read_only)
    assert result["step_id"] == "mode"
    result = await options_step(hass, result, {"control_mode": "monitor"})
    assert result["step_id"] == "confirm_blocking"
    shown = result["description_placeholders"]
    assert shown["first"] == (
        'Monitoring only is chosen under "Boiler, connection and control mode": the plugin '
        "writes nothing to the boiler. Choose a control mode there to set up control."
    )
    assert shown["more"] == "0"
    assert form_default(result, "save_anyway") is False
    result = await options_step(hass, result, {"save_anyway": False})
    assert result["type"] is FlowResultType.MENU
    assert entry.options["boiler"]["class"] == "flow_setpoint"  # nothing saved
    assert "connection" not in entry.options["boiler"]
    result = await options_step(hass, result, {"next_step_id": "connection"})
    assert form_default(result, "connection") == "opentherm_gw"  # the edit went with it
    result = await options_step(hass, result, read_only)
    result = await options_step(hass, result, {"control_mode": "monitor"})
    result = await options_step(hass, result, {"save_anyway": True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["boiler"]["class"] == "read_only"
    assert entry.options["boiler"]["control_mode"] == "monitor"
    # Negative: control already blocked by the mode; a building edit adds nothing.
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "building"})
    result = await options_step(hass, result, {"floor_area": 100})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_confirming_names_the_new_blocker_and_asks_nothing_without_control(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The first new blocker's text, for a zones and a circuit edit; with no control section
    in the stored options nothing is asked (adding or taking out control stops nothing)."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=controlled_options(entities)
    )
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "zones"})
    result = await options_step(hass, result, {"zones": []})
    assert result["step_id"] == "confirm_blocking"
    assert result["description_placeholders"]["more"] == "0"
    assert result["description_placeholders"]["first"].startswith("Control needs at least one")
    result = await options_step(hass, result, {"save_anyway": False})
    result = await options_step(hass, result, {"next_step_id": "circuit"})
    result = await options_step(hass, result, {"control": "separate"})
    assert result["step_id"] == "confirm_blocking"
    assert result["description_placeholders"]["first"].startswith("This version controls only")
    options = {k: v for k, v in controlled_options(entities).items() if k != "control"}
    hass.config_entries.async_update_entry(entry, options=options)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "zones"})
    result = await options_step(hass, result, {"zones": []})
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_the_confirmation_text_is_the_blockers_own(hass: HomeAssistant) -> None:
    """The blocker's text as the control switch gives it, in Home Assistant's language, without
    its sentence naming the other reasons (the form counts them); a blocker without a text shows
    its key."""
    from custom_components.vtherm_smart_boiler.config_flow import SmartBoilerOptionsFlow

    flow = SmartBoilerOptionsFlow()
    flow.hass = hass
    text = await flow._async_blocker_text("no_zones")
    assert text == "Control needs at least one Versatile Thermostat zone: add them in the options."
    assert await flow._async_blocker_text("not_a_blocker") == "not_a_blocker"
    hass.config.language = "pl"
    text = await flow._async_blocker_text("no_zones")
    assert (
        text
        == "Sterowanie wymaga co najmniej jednej strefy Versatile Thermostat: dodaj je w opcjach."
    )


RELOAD_SENTENCE = {
    "en": (
        "Saving reloads the integration: while control holds the boiler, it is handed back and "
        "taken again (a relay goes to its rest state and back)."
    ),
    "pl": (
        "Zapisanie przeładowuje integrację: gdy sterowanie trzyma kocioł, zostaje on oddany i "
        "przejęty ponownie (przekaźnik przechodzi w stan spoczynkowy i z powrotem)."
    ),
}


@pytest.mark.parametrize("language", ["en", "pl"])
def test_every_options_section_says_saving_hands_back(language: str) -> None:
    """P-67 (review question 10, provisional, K4): every options save but the level's reloads
    and hands the boiler back while control holds it — the menu and every step say so. The
    level step reloads only with the defaults restored and says so; the confirmation step says
    what its save does itself."""
    import json
    from pathlib import Path

    from custom_components.vtherm_smart_boiler import config_flow as flow

    path = Path(flow.__file__).parent / "translations" / f"{language}.json"
    steps = json.loads(path.read_text(encoding="utf-8"))["options"]["step"]
    sentence = RELOAD_SENTENCE[language]
    tail = sentence.split(": ", 1)[1]
    for step_id, texts in steps.items():
        if step_id == "confirm_blocking":
            continue
        if step_id == "level":
            assert texts["description"].endswith(tail), step_id
            continue
        assert texts["description"].endswith(sentence), step_id


async def test_a_zone_built_on_the_boilers_thermostat_is_refused(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """X5.19: a VT zone whose entry lists the gateway's own thermostat climate — registered by
    ``opentherm_gw``, or on the same device as a mapped boiler signal (the firmware's MQTT
    climate) — would ask for heat whenever the flame burns: refused, named. Negative: a zone
    whose VT entry cannot be read, or that lists no such climate, is accepted."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    gateway = registry.async_get_or_create(
        "climate", "opentherm_gw", "gw-thermostat", suggested_object_id="gateway_thermostat"
    ).entity_id
    mqtt = hass.config_entries.async_entries("mqtt")[0]
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=mqtt.entry_id, identifiers={("mqtt", "otgw-boiler")}
    )
    flame = registry.async_get_or_create(
        "binary_sensor", "mqtt", "otgw-flame", suggested_object_id="otgw_flame", device_id=device.id
    ).entity_id
    hass.states.async_set(flame, "off")
    firmware = registry.async_get_or_create(
        "climate", "mqtt", "otgw-thermostat", suggested_object_id="otgw", device_id=device.id
    ).entity_id

    def built_on(zone: str, *underlying: str) -> None:
        vt = MockConfigEntry(
            domain="versatile_thermostat", data={"underlying_entity_ids": list(underlying)}
        )
        vt.add_to_hass(hass)
        registry.async_update_entity(zone, config_entry_id=vt.entry_id)

    built_on(entities["living"], "switch.living_valve", gateway)
    result = await start_setup(hass)
    for data in (
        {"name": "Boiler", "level": "simple"},
        {"flame": flame, "flow": entities["flow"]},
        {},
        {"control": "unmixed_shared"},
    ):
        result = await step(hass, result, data)
    result = await step(hass, result, {"zones": [entities["living"], entities["bedroom"]]})
    assert result["errors"] == {"zones": "zone_on_boiler_thermostat"}
    assert result["description_placeholders"] == {"zone": "fake living"}
    built_on(entities["living"], firmware)  # the firmware's climate, on the flame's device
    result = await step(hass, result, {"zones": [entities["living"]]})
    assert result["errors"] == {"zones": "zone_on_boiler_thermostat"}
    built_on(entities["living"], "switch.living_valve")
    result = await step(hass, result, {"zones": [entities["living"], entities["bedroom"]]})
    assert result["step_id"] == "zone"  # bedroom's VT entry cannot be read: accepted


async def test_the_zone_step_offers_closes_when_off(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 4: "closes when VT switches it off" is shown at both levels, off by default,
    stored per zone, and kept when the step is saved again."""
    from custom_components.vtherm_smart_boiler.config_flow import zone_schema

    for level in ("simple", "advanced"):
        schema = zone_schema({"level": level}, {})
        marker = next(m for m in schema.schema if str(m) == "closes_when_off")
        assert marker.default() is False
    entry_id = await create_entry(hass, entities, "simple", ("living", "bedroom"))
    plain = {"emitter": "radiator", "foreign_heat": []}

    async def open_zones(*picked: str) -> dict[str, Any]:
        menu = await hass.config_entries.options.async_init(entry_id)
        result = await options_step(hass, menu, {"next_step_id": "zones"})
        return await options_step(hass, result, {"zones": [entities[z] for z in picked]})

    result = await open_zones("living", "bedroom")
    assert form_default(result, "closes_when_off") is False
    result = await options_step(hass, result, plain | {"closes_when_off": True})
    result = await options_step(hass, result, plain)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    saved = hass.config_entries.async_get_entry(entry_id).options["zones"]
    assert saved[0]["closes_when_off"] is True
    assert "closes_when_off" not in saved[1]  # off: the default
    result = await open_zones("living")
    assert form_default(result, "closes_when_off") is True  # shown as stored
    result = await options_step(hass, result, plain)  # saved again, untouched
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options
    assert options["zones"][0]["closes_when_off"] is True  # kept
    assert EntryConfig.from_options(options).installation.zones[0].closes_when_off
    result = await open_zones("living")
    result = await options_step(hass, result, plain | {"closes_when_off": False})
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options
    assert "closes_when_off" not in options["zones"][0]


def test_the_form_helpers_read_missing_parts_as_nothing() -> None:
    """Negatives for the helpers: a zone naming no circuit takes the one there is (P-64);
    "restore defaults" without stored periods leaves no monitor section (P-65); options that
    cannot be read, or hold no control section, give no blockers to confirm (Open after
    R6 #3)."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    zones = {"zones": [{"entity_id": "climate.a"}, {"entity_id": "climate.b", "circuit": ""}]}
    assert not flow.circuit_left_with_zones(zones, [{"id": "other"}])
    assert flow.circuit_left_with_zones({"zones": [{"circuit": "gone"}]}, [{"id": "main"}])
    options: dict[str, Any] = {"monitor": {"near_room_k": 4.0}}
    flow.restore_advanced_defaults(options)
    assert "monitor" not in options
    options = {}
    flow.restore_advanced_defaults(options)
    assert options == {}
    assert flow.options_blockers({"signals": "unreadable"}) is None
    assert flow.options_blockers({"signals": {"flame": "b.f", "flow": "s.f"}}) is None
    assert flow.boiler_side_entities({"signals": "unreadable", "control": None}) == []
    assert not flow.off_too_close_in({"control": {"write_path": "entity", "off_setpoint": "x"}})
    assert not flow.off_too_close_in({"control": None})


async def test_an_entity_is_checked_as_its_selector_filters_it(hass: HomeAssistant) -> None:
    """P-79's one helper: the domain from the entity ID, the integration from the registry, the
    device class only once the entity has reported. Negative: no entity ID at all."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.vtherm_smart_boiler.config_flow import entity_suitable

    registry = er.async_get(hass)
    vt = registry.async_get_or_create("climate", "versatile_thermostat", "room").entity_id
    other = registry.async_get_or_create("climate", "generic_thermostat", "hall").entity_id
    zone = {"domain": "climate", "integration": "versatile_thermostat"}
    assert entity_suitable(hass, vt, zone)
    assert not entity_suitable(hass, other, zone)
    assert not entity_suitable(hass, "climate.unregistered", zone)
    temperature = {"domain": "sensor", "device_class": "temperature"}
    assert entity_suitable(hass, "sensor.not_reported", temperature)
    hass.states.async_set("sensor.away", "unavailable")
    assert entity_suitable(hass, "sensor.away", temperature)  # has not reported a class yet
    hass.states.async_set("sensor.power", "5", {"device_class": "power"})
    assert not entity_suitable(hass, "sensor.power", temperature)
    assert entity_suitable(hass, "sensor.power", [temperature, {"domain": "sensor"}])
    for bad in (None, 7, "", "no_domain"):
        assert not entity_suitable(hass, bad, {"domain": "sensor"})


async def test_a_problem_in_a_section_the_setup_lacks_shows_on_the_signals_step(
    hass: HomeAssistant,
) -> None:
    """The setup has no freshness step: a problem there shows on the signals step."""
    from custom_components.vtherm_smart_boiler.config_flow import SmartBoilerConfigFlow

    flow = SmartBoilerConfigFlow()
    flow.hass = hass
    flow.context = {"source": SOURCE_USER}
    result = await flow._back_to_problem("invalid_freshness", "flow")
    assert result["step_id"] == "signals"
    assert result["errors"] == {"base": "invalid_freshness"}


async def test_a_circuits_flow_sensor_is_checked_on_the_server(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-79 on the circuit step: a mixed circuit's flow sensor must be a temperature."""
    entry_id = await create_entry(hass, entities, "advanced")
    result = await open_circuit(hass, entry_id)
    answer = {"control": "separate", "add_another": False}
    result = await options_step(hass, result, answer | {"flow_entity": "sensor.humidity"})
    assert result["errors"] == {"flow_entity": "entity_not_suitable"}
    result = await options_step(hass, result, answer | {"flow_entity": entities["return"]})
    assert result["type"] is FlowResultType.CREATE_ENTRY


# --- X6: what is wired to the gateway's thermostat terminals (decision 1) ------------------------

NEXT_STEP = {
    "opentherm_gw": "control_gateway",
    "otgw_mqtt": "control_mqtt",
    "entity": "control_entity",
}


@pytest.mark.parametrize("path", sorted(NEXT_STEP))
async def test_the_thermostat_kind_is_asked_for_a_gateway(
    hass: HomeAssistant, entities: dict[str, str], path: str
) -> None:
    """Decision 1: both gateway topologies ask what is wired to the gateway's thermostat
    terminals, on every write path that takes them — no answer is a form error, an answer that
    contradicts the topology is refused with the hint to pick the other connection. An on/off
    contact and "I don't know" are taken: control is then blocked, the monitor runs."""
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    first = {"write_path": path, "confirmed_entity": "sensor.gw_control_setpoint"}
    missing = {"thermostat_kind": "thermostat_kind_missing"}
    contradicts = {"thermostat_kind": "thermostat_kind_contradicts_topology"}
    for answer, error in (
        ({"topology": "gateway_with_thermostat"}, missing),
        ({"topology": "gateway_standalone"}, missing),
        ({"topology": "gateway_standalone", "thermostat_kind": "opentherm"}, contradicts),
        ({"topology": "gateway_with_thermostat", "thermostat_kind": "none"}, contradicts),
    ):
        result = await open_control(hass, entry_id)
        result = await options_step(hass, result, first | answer)
        assert result["step_id"] == "control", answer
        assert result["errors"] == error, answer
    for topology, kind in (
        ("gateway_with_thermostat", "opentherm"),
        ("gateway_standalone", "none"),
        ("gateway_with_thermostat", "on_off"),
        ("gateway_standalone", "unknown"),
    ):
        result = await open_control(hass, entry_id)
        answer = first | {"topology": topology, "thermostat_kind": kind}
        result = await options_step(hass, result, answer)
        assert result["step_id"] == NEXT_STEP[path], answer


@pytest.mark.usefixtures("gateway")
async def test_the_thermostat_kind_is_stored_with_a_gateway_and_offered_again(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The answer is stored in the control section and offered again as it was; one this version
    cannot read is not offered (it must be answered again)."""
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    first = {
        "write_path": "opentherm_gw",
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "confirmed_entity": "sensor.gw_control_setpoint",
    }
    result = await options_step(hass, result, first)
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    result = await options_step(hass, result, CURVE_ANSWERS)
    assert result["step_id"] == "control_alarms"  # Y1: offered with a thermostat, at both levels
    result = await options_step(hass, result, {"write_ignored": "info"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    assert entry.options["control"]["thermostat_kind"] == "opentherm"
    result = await open_control(hass, entry_id)
    assert form_default(result, "thermostat_kind") == "opentherm"
    from custom_components.vtherm_smart_boiler.config_flow import control_schema

    garbled = {"control": {**entry.options["control"], "thermostat_kind": "a newer answer"}}
    marker = next(m for m in control_schema(garbled).schema if str(m) == "thermostat_kind")
    assert not (marker.description or {}).get("suggested_value")


@pytest.mark.parametrize(
    ("topology", "kept"),
    [
        ("gateway_with_thermostat", True),
        ("gateway_standalone", True),
        ("virtual", False),
        ("monitor_mode", False),
        (None, False),  # left empty: no topology, no terminals
        ("a topology this version does not know", False),
    ],
)
def test_a_topology_without_thermostat_terminals_drops_the_kind(
    topology: str | None, kept: bool
) -> None:
    """The virtual topology (and X8's relay path) has no thermostat terminals: an answer left
    from a gateway topology is dropped when the step is saved."""
    from custom_components.vtherm_smart_boiler.config_flow import apply_control

    options: dict[str, Any] = {
        "control": {
            "write_path": "entity",
            "topology": "gateway_standalone",
            "thermostat_kind": "none",
        }
    }
    apply_control(
        options,
        {
            "write_path": "entity",
            "topology": topology,
            "thermostat_kind": "none",
            "confirmed_entity": "sensor.x",
        },
    )
    assert ("thermostat_kind" in options["control"]) is kept


# --- X8: the relay path ------------------------------------------------------------------------

RELAY = "switch.boiler_relay"
RELAY_ANSWERS = {
    "relay_entity": RELAY,
    "relay_is_separate_contact": True,
    "relay_reports_state": "yes",
    "relay_power_on_state": "off",
    "relay_off_timer": "none",
    "relay_rest_state": "off",
    "own_room_controller": False,
}


async def to_relay_step(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    hass.states.async_set(RELAY, "off")
    result = await open_control(hass, entry_id)
    return await options_step(hass, result, {"write_path": "relay"})


def path_options(result: dict[str, Any]) -> list[str]:
    for marker, validator in result["data_schema"].schema.items():
        if str(marker) == "write_path":
            return list(validator.config["options"])
    raise AssertionError("no write path in the form")


@pytest.mark.parametrize(
    ("boiler_class", "offered"),
    [
        ("on_off", ["none", "relay"]),
        ("flow_setpoint", ["none", "entity", "opentherm_gw", "otgw_mqtt"]),
        ("curve_only", ["none"]),
        ("read_only", ["none"]),
    ],
)
async def test_the_relay_path_is_offered_only_for_on_off_boilers(
    hass: HomeAssistant, entities: dict[str, str], boiler_class: str, offered: list[str]
) -> None:
    """R1: the path select offers what the boiler class suits; a path it does not suit is
    refused on submit."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), boiler_class)
    result = await open_control(hass, entry_id)
    assert path_options(result) == offered
    wrong = "entity" if boiler_class == "on_off" else "relay"
    with pytest.raises(InvalidData):  # the select does not offer it
        await options_step(hass, result, {"write_path": wrong})


async def test_a_path_the_class_does_not_suit_is_refused_by_the_first_step() -> None:
    from custom_components.vtherm_smart_boiler.config_flow import control_error

    on_off = {"boiler": {"class": "on_off"}}
    assert control_error({"write_path": "entity"}, on_off) == {
        "write_path": "path_not_for_boiler_class"
    }
    assert control_error({"write_path": "relay"}, on_off) == {}  # no read-back or topology
    flow = {"boiler": {"class": "flow_setpoint"}}
    assert control_error({"write_path": "relay"}, flow) == {
        "write_path": "path_not_for_boiler_class"
    }


async def test_the_relay_step_asks_the_relays_own_settings(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """R3: the relay's own settings, each with its cautious default — its state report,
    after a power cut and timer "I don't know", the rest state "off" — and the separate-contact
    tick, off by default and never pre-filled (answer G). The relay path needs no read-back,
    topology or thermostat kind; the answers go to the options as given."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    assert result["step_id"] == "control_relay"
    assert form_default(result, "relay_is_separate_contact") is False
    assert form_default(result, "relay_reports_state") == "unknown"
    assert form_default(result, "relay_power_on_state") == "unknown"
    assert form_default(result, "relay_off_timer") == "unknown"
    assert form_default(result, "relay_rest_state") == "off"
    assert form_default(result, "own_room_controller") is False
    assert form_default(result, "relay_repeat_s") is None
    assert "boiler_heats_above_w" not in result["data_schema"].schema  # advanced only
    result = await options_step(hass, result, RELAY_ANSWERS)
    assert result["step_id"] == "control_relay_behaviour"
    result = await options_step(hass, result, {"activation_delay_s": 0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control == {"write_path": "relay", "activation_delay_s": 0} | RELAY_ANSWERS
    config = EntryConfig.from_options(hass.config_entries.async_get_entry(entry_id).options)
    assert config.control.relay.separate_contact


async def test_a_new_relay_asks_the_separate_contact_tick_again(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """PB-45: the separate-contact declaration was about one entity; when the relay changes,
    the step asks for the tick again before it saves, so the declaration does not carry over."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    result = await options_step(hass, result, {"activation_delay_s": 0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    hass.states.async_set("switch.other_relay", "off")
    other = RELAY_ANSWERS | {"relay_entity": "switch.other_relay"}
    result = await to_relay_step(hass, entry_id)
    assert form_default(result, "relay_is_separate_contact") is True  # the same relay's tick
    result = await options_step(hass, result, other)
    assert result["errors"] == {"relay_is_separate_contact": "relay_contact_confirm_again"}
    result = await options_step(hass, result, other)  # confirmed for the new relay
    assert result["step_id"] == "control_relay_behaviour"
    result = await options_step(hass, result, {"activation_delay_s": 0})
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["relay_entity"] == "switch.other_relay"
    assert control["relay_is_separate_contact"] is True
    # Unticked for a new relay: saved as given, no second question (control will not start).
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_is_separate_contact": False})
    assert result["step_id"] == "control_relay_behaviour"
    # The same relay, ticked again: no question.
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, other)
    assert result["step_id"] == "control_relay_behaviour"


@pytest.mark.parametrize("level", ["simple", "advanced"])
async def test_the_relay_path_shows_the_activation_delay(
    hass: HomeAssistant, entities: dict[str, str], level: str
) -> None:
    """Decision 5 on the relay path: its behaviour step shows VT's activation delay at the
    simple level (alone) and the advanced one (with the thresholds, learning pauses and frost),
    pre-filled from VT's stored value for confirmation; T-37's check applies there."""
    MockConfigEntry(
        domain="versatile_thermostat",
        data={
            "thermostat_type": "thermostat_central_config",
            "central_boiler_activation_delay_sec": 90,
        },
    ).add_to_hass(hass)
    entry_id = await create_entry(hass, entities, level, ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    assert result["step_id"] == "control_relay_behaviour"
    assert form_default(result, "activation_delay_s") == 90
    fields = {str(marker) for marker in result["data_schema"].schema}
    if level == "simple":
        assert fields == {"activation_delay_s"}
        return
    assert {"count_threshold", "learning_pauses", "frost_limit", "frost_release"} <= fields
    answer = {
        "activation_delay_s": 90,
        "count_threshold": 1,
        "learning_pauses": True,
        "frost_limit": 7,
        "frost_release": 7,
    }
    result = await options_step(hass, result, answer)
    assert result["errors"] == {"frost_release": "frost_release_not_above_limit"}  # T-37
    result = await options_step(hass, result, answer | {"frost_release": 9})
    assert result["type"] is FlowResultType.CREATE_ENTRY  # no alarm step for relays (Y1)


async def test_the_relay_path_offers_no_return_by_itself(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 6: the return by itself after another controller is not offered for relays; nor
    a reaction to an ignored write (decision 7: never on the relay path) — nor any other, after
    the allow-list (Y1): the relay path has no alarm step at all, and a reaction stored earlier
    only informs."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    entry_id = await create_entry(hass, entities, "advanced", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    result = await options_step(
        hass,
        result,
        {"activation_delay_s": 0, "count_threshold": 1, "learning_pauses": True},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    options = {
        "level": "advanced",
        "control": {"write_path": "relay", "alarm_reactions": {"write_ignored": "hand_back"}},
    }
    assert flow.control_alarms_schema(options).schema == {}
    assert not flow.alarm_step_offered(options)


@pytest.mark.parametrize("rest", ["off", "on"])
async def test_the_relay_path_offers_the_own_room_controller_tick(
    hass: HomeAssistant, entities: dict[str, str], rest: str
) -> None:
    """Answer M: the tick is on the relay step; saved with the rest state "off" it is kept, and
    does not count as a working thermostat."""
    from custom_components.vtherm_smart_boiler.control_config import working_thermostat

    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    assert "own_room_controller" in {str(m) for m in result["data_schema"].schema}
    answers = RELAY_ANSWERS | {"own_room_controller": True, "relay_rest_state": rest}
    result = await options_step(hass, result, answers)
    result = await options_step(hass, result, {"activation_delay_s": 0})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options
    assert options["control"]["own_room_controller"] is True
    assert working_thermostat(EntryConfig.from_options(options).control) is (rest == "on")


async def test_a_declared_timer_needs_its_length(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_off_timer": "minutes"})
    assert result["errors"] == {"relay_off_timer_min": "relay_off_timer_min_missing"}
    answers = RELAY_ANSWERS | {"relay_off_timer": "minutes", "relay_off_timer_min": 15}
    result = await options_step(hass, result, answers)
    assert result["step_id"] == "control_relay_behaviour"


@pytest.mark.parametrize("length", [5, 9, 9.5, 1])
async def test_a_declared_timer_shorter_than_ten_minutes_is_refused(
    hass: HomeAssistant, entities: dict[str, str], length: float
) -> None:
    """K4.2 (decided by the user 2026-10-03): the shortest switch-off timer the plugin takes for
    the relay's own is 10 min — a shorter one would start the boiler again at every lapse. The
    form refuses a declared length below it with its own translated error, and takes 10."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    answers = RELAY_ANSWERS | {"relay_off_timer": "minutes", "relay_off_timer_min": length}
    result = await options_step(hass, result, answers)
    assert result["step_id"] == "control_relay"
    assert result["errors"] == {"relay_off_timer_min": "relay_off_timer_min_short"}
    result = await options_step(hass, result, answers | {"relay_off_timer_min": 10})
    assert result["step_id"] == "control_relay_behaviour"


async def test_a_relay_used_by_a_vt_zone_or_the_gateway_is_refused(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """R2: a switch a VT thermostat drives for a room, an entity of the boiler's gateway
    integration or of VT, a boiler thermostat entity without both heat and off, and one the
    options already use in another role."""
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    vt = MockConfigEntry(
        domain="versatile_thermostat", data={"underlying_entity_ids": ["switch.room_heater"]}
    )
    vt.add_to_hass(hass)
    registry.async_update_entity(entities["bedroom"], config_entry_id=vt.entry_id)
    hass.states.async_set("switch.room_heater", "off")
    gateway = registry.async_get_or_create("switch", "opentherm_gw", "gw-ch-override").entity_id
    hass.states.async_set(gateway, "off")
    hass.states.async_set("climate.boiler", "heat", {"hvac_modes": ["heat", "auto"]})
    cases = [
        ("switch.room_heater", "relay_used_by_zone"),
        (gateway, "relay_of_boiler_interface"),
        ("climate.boiler", "relay_climate_modes"),
    ]
    for relay, error in cases:
        result = await to_relay_step(hass, entry_id)
        result = await options_step(hass, result, RELAY_ANSWERS | {"relay_entity": relay})
        assert result["errors"] == {"relay_entity": error}, relay
    hass.states.async_set("climate.boiler", "heat", {"hvac_modes": ["heat", "off"]})
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_entity": "climate.boiler"})
    assert result["step_id"] == "control_relay_behaviour"


async def test_a_relay_in_another_role_is_refused(hass: HomeAssistant) -> None:
    from custom_components.vtherm_smart_boiler.config_flow import relay_entity_error

    options = {
        "zones": [{"entity_id": "climate.a", "foreign_heat": [{"entity_id": "switch.stove"}]}],
        "control": {"write_path": "relay", "relay_entity": "switch.stove"},
    }
    assert relay_entity_error(hass, options, "switch.stove") == "relay_in_another_role"
    assert relay_entity_error(hass, options, "switch.other") is None
    alone = {"control": {"write_path": "relay", "relay_entity": "switch.other"}}
    assert relay_entity_error(hass, alone, "switch.other") is None  # its own field
    assert relay_entity_error(hass, alone, None) == "entity_not_suitable"


@pytest.mark.parametrize("relay", ["input_boolean.boiler", "light.boiler"])
async def test_an_input_boolean_relay_is_refused(
    hass: HomeAssistant, entities: dict[str, str], relay: str
) -> None:
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    hass.states.async_set(relay, "off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_entity": relay})
    assert result["errors"] == {"relay_entity": "relay_domain_not_supported"}


def vt_central(hass: HomeAssistant, **data: Any) -> MockConfigEntry:
    """VT's central entry with VT 10.4.0's keys."""
    entry = MockConfigEntry(
        domain="versatile_thermostat",
        data={"thermostat_type": "thermostat_central_config"} | data,
    )
    entry.add_to_hass(hass)
    return entry


def vt_threshold(hass: HomeAssistant, unique_id: str, value: str, unit: str | None = None) -> None:
    from homeassistant.helpers import entity_registry as er

    number = er.async_get(hass).async_get_or_create("number", "versatile_thermostat", unique_id)
    hass.states.async_set(number.entity_id, value, {"unit_of_measurement": unit} if unit else {})


@pytest.mark.parametrize(
    ("commands", "relay", "note"),
    [
        (
            ("switch.boiler_relay/switch.turn_on", "switch.boiler_relay/switch.turn_off"),
            RELAY,
            None,
        ),
        (
            (
                "climate.boiler/climate.set_hvac_mode/hvac_mode:heat",
                "climate.boiler/climate.set_hvac_mode/hvac_mode:off",
            ),
            "climate.boiler",
            None,
        ),
        (
            (
                "input_boolean.boiler/input_boolean.turn_on",
                "input_boolean.boiler/input_boolean.turn_off",
            ),
            None,
            "vt_commands_not_supported",
        ),
        (
            ("script.boiler_on/script.turn_on", "script.boiler_off/script.turn_on"),
            None,
            "vt_commands_not_supported",
        ),
    ],
)
async def test_the_relay_step_is_prefilled_from_vts_central_boiler(
    hass: HomeAssistant,
    entities: dict[str, str],
    commands: tuple[str, str],
    relay: str | None,
    note: str | None,
) -> None:
    """R14: moving over from VT's central boiler — the relay from its commands (a switch pair,
    a boiler thermostat pair; a free-form command "not supported"), the delay, the repeat
    interval, and the thresholds as VT used them (``int()``; W → kW); shown for confirmation,
    the separate-contact tick never pre-filled; nothing written to VT."""
    hass.states.async_set("climate.boiler", "off", {"hvac_modes": ["heat", "off"]})
    central = vt_central(
        hass,
        use_central_boiler_feature=True,
        central_boiler_activation_service=commands[0],
        central_boiler_deactivation_service=commands[1],
        central_boiler_activation_delay_sec=60,
        keep_alive_boiler_delay_sec=120,
    )
    vt_threshold(hass, "boiler_power_activation_threshold", "1500.9", "W")
    before = dict(central.data)
    entry_id = await create_entry(hass, entities, "advanced", ("living",), "on_off")
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "relay"})
    assert result["step_id"] == "control_relay_from_vt"
    assert result["errors"] == ({} if note is None else {"base": note})
    assert form_default(result, "relay_entity") == relay
    assert form_default(result, "relay_repeat_s") == 120
    assert form_default(result, "relay_is_separate_contact") is False
    answers = RELAY_ANSWERS | {"relay_entity": relay or RELAY}
    hass.states.async_set(RELAY, "off")
    result = await options_step(hass, result, answers)
    assert result["step_id"] == "control_relay_behaviour"
    assert form_default(result, "activation_delay_s") == 60
    assert form_default(result, "power_threshold_kw") == 1.5  # 1500 W as VT used it
    assert form_default(result, "count_threshold") == 1  # VT's count missing: not carried over
    assert dict(central.data) == before  # nothing written to VT


async def test_the_count_and_long_keep_alive_prefill_rules(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """R14: the count only where every zone VT counts has one device, capped at the plugin's
    zones; a keep-alive above 300 s not pre-filled; both thresholds 0 — nothing."""
    from homeassistant.helpers import entity_registry as er

    from custom_components.vtherm_smart_boiler.vtherm_link import vt_central_boiler_settings

    registry = er.async_get(hass)
    vt_central(
        hass,
        use_central_boiler_feature=True,
        central_boiler_activation_service="switch.r/switch.turn_on",
        central_boiler_deactivation_service="switch.r/switch.turn_off",
        keep_alive_boiler_delay_sec=600,
    )
    vt_threshold(hass, "boiler_activation_threshold", "3.7")
    vt_threshold(hass, "boiler_power_activation_threshold", "2.2", "kW")
    zones = [entities["living"], entities["bedroom"]]
    for zone, devices in ((entities["living"], ["switch.a"]), (entities["bedroom"], ["switch.b"])):
        entry = MockConfigEntry(
            domain="versatile_thermostat", data={"underlying_entity_ids": devices}
        )
        entry.add_to_hass(hass)
        registry.async_update_entity(zone, config_entry_id=entry.entry_id)
        hass.states.async_set(zone, "heat", {"configuration": {"is_used_by_central_boiler": True}})
    settings = vt_central_boiler_settings(hass, zones)
    assert settings is not None
    assert settings.relay == "switch.r"
    assert settings.repeat_s is None  # 600 s: longer than the plugin's 300 s
    assert settings.keep_alive_s == 600
    assert settings.power_threshold_kw == 2.0  # int(2.2) in VT's kW
    assert settings.count_threshold == 2  # int(3.7) = 3, capped at the two zones
    assert vt_central_boiler_settings(hass, zones[:1]).count_threshold == 1  # type: ignore[union-attr]
    # A multi-device zone: VT counts devices, the plugin rooms — no count.
    entry = MockConfigEntry(
        domain="versatile_thermostat", data={"underlying_entity_ids": ["switch.b", "switch.c"]}
    )
    entry.add_to_hass(hass)
    registry.async_update_entity(entities["bedroom"], config_entry_id=entry.entry_id)
    settings = vt_central_boiler_settings(hass, zones)
    assert settings is not None
    assert settings.count_threshold is None
    vt_threshold(hass, "boiler_activation_threshold", "0")
    vt_threshold(hass, "boiler_power_activation_threshold", "0.4", "kW")  # int() → 0: off
    settings = vt_central_boiler_settings(hass, zones)
    assert settings is not None
    assert settings.count_threshold is None
    assert settings.power_threshold_kw is None


@pytest.mark.parametrize(
    ("count", "power", "unit", "expected"),
    [
        ("0", "1500.9", "W", 0),  # SB-07: VT's count off beside its power: carried as off
        ("0.6", "2", "kW", 0),  # int() as VT reads it
        ("0", "0", "W", None),  # no power threshold: no criterion to stand beside
        ("0", "1500", "BTU/h", None),  # the power not carried over: neither is the count
        (None, "1500", "W", None),  # VT's count missing
        ("unavailable", "1500", "W", None),  # VT's count unreadable
        ("-1", "1500", "W", None),  # below 0: not a value VT uses
    ],
)
async def test_vts_count_of_0_beside_a_power_threshold_is_prefilled_0(
    hass: HomeAssistant,
    entities: dict[str, str],
    count: str | None,
    power: str,
    unit: str,
    expected: int | None,
) -> None:
    """SB-07 (decision 7): VT 10.4.0 treats a count of 0 as off, so where it stands beside a
    power threshold the plugin carries it over as 0 — the power criterion alone, as VT used
    it, not an OR with a count of 1 that starts the boiler on any single call. A count
    missing or unreadable, or a power threshold not carried over, pre-fills nothing."""
    from custom_components.vtherm_smart_boiler.vtherm_link import vt_central_boiler_settings

    vt_central(
        hass,
        use_central_boiler_feature=True,
        central_boiler_activation_service="switch.r/switch.turn_on",
        central_boiler_deactivation_service="switch.r/switch.turn_off",
    )
    if count is not None:
        vt_threshold(hass, "boiler_activation_threshold", count)
    vt_threshold(hass, "boiler_power_activation_threshold", power, unit)
    settings = vt_central_boiler_settings(hass, [entities["living"]])
    assert settings is not None
    assert settings.count_threshold == expected


async def test_the_relay_behaviour_form_offers_vts_count_of_0(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """SB-07: the advanced relay behaviour form shows VT's count 0 beside its power threshold."""
    hass.states.async_set("climate.boiler", "off", {"hvac_modes": ["heat", "off"]})
    vt_central(
        hass,
        use_central_boiler_feature=True,
        central_boiler_activation_service=f"{RELAY}/switch.turn_on",
        central_boiler_deactivation_service=f"{RELAY}/switch.turn_off",
    )
    vt_threshold(hass, "boiler_activation_threshold", "0")
    vt_threshold(hass, "boiler_power_activation_threshold", "2", "kW")
    entry_id = await create_entry(hass, entities, "advanced", ("living",), "on_off")
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "relay"})
    assert result["step_id"] == "control_relay_from_vt"
    hass.states.async_set(RELAY, "off")
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_entity": RELAY})
    assert result["step_id"] == "control_relay_behaviour"
    assert form_default(result, "power_threshold_kw") == 2.0
    assert form_default(result, "count_threshold") == 0


async def test_prefill_without_a_vt_central_entry_leaves_the_fields_empty(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """No VT central entry, or one without its commands (unticked): the plain relay step, its
    fields empty but for the cautious defaults."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    assert result["step_id"] == "control_relay"
    assert result["errors"] == {}
    assert form_default(result, "relay_entity") is None  # no default: the user picks it
    assert form_default(result, "relay_repeat_s") is None
    vt_central(hass, central_boiler_activation_delay_sec=30)  # unticked: commands deleted
    result = await to_relay_step(hass, entry_id)
    assert result["step_id"] == "control_relay"


async def test_the_signals_step_accepts_no_signals(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """R4: nothing is required on the signals step — a home with only a relay."""
    result = await start_setup(hass)
    result = await step(hass, result, {"name": "Relay only", "level": "simple"})
    assert result["step_id"] == "signals"
    assert all(type(marker).__name__ == "Optional" for marker in result["data_schema"].schema)
    result = await step(hass, result, {})
    assert result["step_id"] == "boiler"


async def test_unmapping_the_flame_under_water_control_is_confirmed_first(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """R4: flame and flow are optional for the entry, but water-temperature control needs both:
    an edit that unmaps the flame asks first, naming the blocker."""
    from custom_components.vtherm_smart_boiler.config_flow import options_blockers

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=controlled_options(entities)
    )
    entry.add_to_hass(hass)
    assert options_blockers(entry.options) == []
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "signals"})
    result = await options_step(hass, result, {"flow": entities["flow"]})
    assert result["step_id"] == "confirm_blocking"
    assert result["description_placeholders"]["first"] == (
        "Water-temperature control needs the flame mapped in the signals."
    )


def test_the_relay_behaviour_step_offers_vts_count() -> None:
    """R14: VT's count, where it fits rooms, is the count threshold's default at the advanced
    level; the tick of the entity path's form is offered on the relay path too."""
    from custom_components.vtherm_smart_boiler.config_flow import (
        _offers_own_room_controller,
        control_relay_behaviour_schema,
    )
    from custom_components.vtherm_smart_boiler.vtherm_link import VtCentralBoiler, VtCommands

    prefill = VtCentralBoiler(configured=True, commands=VtCommands.NONE, count_threshold=2)
    options = {"level": "advanced", "control": {"write_path": "relay"}}
    result = {"data_schema": control_relay_behaviour_schema(options, prefill)}
    assert form_default(result, "count_threshold") == 2
    assert _offers_own_room_controller({"write_path": "relay"})


@pytest.mark.parametrize(
    ("answer", "error"),
    [
        ({"count_threshold": 5}, {"count_threshold": "count_threshold_above_zones"}),
        ({"count_threshold": 0}, {"count_threshold": "no_demand_criterion"}),
    ],
)
async def test_the_relay_behaviour_step_checks_its_answers(
    hass: HomeAssistant, entities: dict[str, str], answer: dict[str, Any], error: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "advanced", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    base = {"activation_delay_s": 0, "count_threshold": 1, "learning_pauses": True}
    result = await options_step(hass, result, base | answer)
    assert result["errors"] == error


async def test_the_relay_behaviour_step_refuses_a_criterion_no_zone_feeds(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    entry_id = await create_entry(hass, entities, "advanced", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    answer = {
        "activation_delay_s": 0,
        "count_threshold": 1,
        "learning_pauses": True,
        "power_threshold_kw": 2.0,
    }
    result = await options_step(hass, result, answer)
    assert result["errors"] == {"power_threshold_kw": "power_criterion_no_zone"}


async def test_the_relay_behaviour_step_refuses_a_count_of_0_a_zone_cannot_feed(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    """PB-23 (a) on the relay path: an over_climate zone without an opening and a count of 0
    with only an opening threshold — refused, naming the zone."""
    entry_id = await create_entry(hass, entities, "advanced", ("living", "bedroom"), "on_off")
    zones.set("living", on_percent=None, power_percent=None)
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    answer = {
        "activation_delay_s": 0,
        "count_threshold": 0,
        "learning_pauses": True,
        "opening_threshold": 50,
    }
    result = await options_step(hass, result, answer)
    assert result["errors"] == {"count_threshold": "zone_feeds_no_criterion"}
    living = hass.states.get(zones.entities["living"])
    assert living is not None
    assert result["description_placeholders"] == {"zone": living.name}


async def test_the_relay_cannot_change_while_control_holds_it(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-12 for the relay: what the hand-back goes through — the relay and its rest state — does
    not change while control holds the relay; switch control off first."""
    hass.states.async_set(RELAY, "off")
    options = {
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {"class": "on_off", "dhw": "none"},
        "zones": [{"entity_id": entities["living"]}],
        "monitor": {"monitoring_days": 0},
        "control": {"write_path": "relay"} | RELAY_ANSWERS,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    await entry.runtime_data.control.async_set_enabled(True)
    assert entry.runtime_data.control.holding
    result = await to_relay_step(hass, entry.entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS | {"relay_rest_state": "on"})
    assert result["errors"] == {"base": "control_holds_boiler"}
    await entry.runtime_data.control.async_set_enabled(False)
    await hass.async_block_till_done()


# --- Y1: the fault signals, the "add water" threshold, the one reaction decision 7 offers -----


async def test_the_monitor_step_offers_add_water_and_not_the_old_low_pressure_limits(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The monitor step (advanced) offers the optional "add water" threshold, empty by default,
    within 0.1–2.0 bar, and no longer 0.2.1's two low-pressure limits."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    fields = {str(marker) for marker in flow.monitor_schema({}).schema}
    assert "add_water_below" in fields
    assert not {"pressure_low_warning", "pressure_low_alarm"} & fields
    entry_id = await create_entry(hass, entities, "advanced")
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "monitor"})
    assert form_default(result, "add_water_below") is None  # optional, no value offered
    base = {
        "condensing_return": 55,
        "short_burn_min": 10,
        "monitoring_days": 7,
        "near_room_k": 3,
        "foreign_heat_hold_min": 60,
    }
    for bad in (0.05, 2.5):
        with pytest.raises(InvalidData):
            await options_step(hass, result, base | {"add_water_below": bad})
    result = await options_step(hass, result, base | {"add_water_below": 0.8})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    options = hass.config_entries.async_get_entry(entry_id).options
    assert options["monitor"]["add_water_below"] == 0.8
    assert EntryConfig.from_options(options).monitor.alarms.add_water_below == 0.8


async def test_the_monitor_step_offers_no_high_pressure_limits(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 13 (SB-18): the high-pressure warning and alarm are optional and offered empty —
    no default fits every safety valve. Left empty, none is stored and there is no such alarm;
    one alone is kept; both must be in order — the step says so — and are kept."""
    entry_id = await create_entry(hass, entities, "advanced")
    base = {
        "condensing_return": 55,
        "short_burn_min": 10,
        "monitoring_days": 7,
        "near_room_k": 3,
        "foreign_heat_hold_min": 60,
    }
    for limits, expected in (
        ({}, None),
        ({"pressure_high_alarm": 2.0}, (None, 2.0)),
        ({"pressure_high_warning": 2.2, "pressure_high_alarm": 2.0}, "alarm_limits_out_of_order"),
        ({"pressure_high_warning": 1.8, "pressure_high_alarm": 2.0}, (1.8, 2.0)),
    ):
        menu = await hass.config_entries.options.async_init(entry_id)
        result = await options_step(hass, menu, {"next_step_id": "monitor"})
        if not limits:
            assert form_default(result, "pressure_high_warning") is None
            assert form_default(result, "pressure_high_alarm") is None
        result = await options_step(hass, result, base | limits)
        if isinstance(expected, str):
            assert (result["step_id"], result["errors"]) == ("monitor", {"base": expected})
            continue
        assert result["type"] is FlowResultType.CREATE_ENTRY, limits
        await hass.async_block_till_done()
        options = hass.config_entries.async_get_entry(entry_id).options
        band = EntryConfig.from_options(options).monitor.alarms.pressure_high
        assert (None if band is None else (band.warning, band.alarm)) == expected


def _form_optional(result: dict[str, Any], key: str) -> bool:
    return any(str(marker) == key for marker in result["data_schema"].schema)


@pytest.mark.parametrize("level", ["simple", "advanced"])
async def test_the_signals_step_offers_the_boiler_fault_signals(
    hass: HomeAssistant, entities: dict[str, str], level: str
) -> None:
    """Boiler protection's optional signals: the low-water-pressure fault and the fault
    indication at every level, the lockout at the advanced one — binary sensors only; one
    entity for two of them is refused."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    assert flow.SIGNAL_FIELDS["low_pressure_fault"] == ({"domain": "binary_sensor"}, True)
    assert flow.SIGNAL_FIELDS["boiler_lockout"] == ({"domain": "binary_sensor"}, False)
    assert flow.SIGNAL_FIELDS["fault_indication"] == ({"domain": "binary_sensor"}, True)
    keys = list(flow.SIGNAL_FIELDS)
    assert keys.index("low_pressure_fault") < keys.index("boiler_lockout")
    hass.states.async_set("binary_sensor.boiler_low_water", "off")
    hass.states.async_set("binary_sensor.boiler_lockout", "off")
    hass.states.async_set("sensor.not_a_fault", "1")
    entry_id = await create_entry(hass, entities, level)
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "signals"})
    assert _form_optional(result, "low_pressure_fault")
    assert _form_optional(result, "fault_indication")
    assert _form_optional(result, "boiler_lockout") is (level == "advanced")
    base = {"flame": entities["flame"], "flow": entities["flow"]}
    result = await options_step(hass, result, base | {"low_pressure_fault": "sensor.not_a_fault"})
    assert result["errors"] == {"low_pressure_fault": "entity_not_suitable"}
    if level == "advanced":
        both = {
            "low_pressure_fault": "binary_sensor.boiler_low_water",
            "boiler_lockout": "binary_sensor.boiler_low_water",
        }
        result = await options_step(hass, result, base | both)
        assert result["errors"] == {"boiler_lockout": "entity_for_two_signals"}
    answer = base | {"low_pressure_fault": "binary_sensor.boiler_low_water"}
    if level == "advanced":
        answer["boiler_lockout"] = "binary_sensor.boiler_lockout"
    result = await options_step(hass, result, answer)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    signals = hass.config_entries.async_get_entry(entry_id).options["signals"]
    assert signals["low_pressure_fault"] == "binary_sensor.boiler_low_water"


def test_stored_fault_signals_on_one_entity_block_control() -> None:
    """In stored options one entity for both fault signals keeps the first; the later is
    dropped, named, and control gets its blocker (X5's rule)."""
    from custom_components.vtherm_smart_boiler.control_config import config_blockers

    options = {
        "signals": {
            "flame": "binary_sensor.flame",
            "flow": "sensor.flow",
            "low_pressure_fault": "binary_sensor.fault",
            "boiler_lockout": "binary_sensor.fault",
        },
        "zones": [{"entity_id": "climate.living"}],
        "boiler": {"class": "flow_setpoint"},
        "control": {
            "write_path": "opentherm_gw",
            "gateway_id": "gw",
            "confirmed_entity": "sensor.gw_control_setpoint",
            "topology": "gateway_standalone",
            "thermostat_kind": "none",
            "curve": {"design_outdoor": -15, "design_flow": 55},
        },
    }
    config = EntryConfig.from_options(options)
    assert config.signals[Signal.LOW_PRESSURE_FAULT] == "binary_sensor.fault"
    assert Signal.BOILER_LOCKOUT not in config.signals
    assert config.shared_signals == {Signal.BOILER_LOCKOUT: Signal.LOW_PRESSURE_FAULT}
    found = config_blockers(config.control, config.installation, config.shared_signals)
    assert found == ["entity_for_two_signals"]


@pytest.mark.parametrize(
    ("control", "offered"),
    [
        ({"topology": "gateway_with_thermostat", "thermostat_kind": "opentherm"}, True),
        ({"topology": "gateway_standalone", "thermostat_kind": "none"}, False),
    ],
    ids=["thermostat", "stand_alone"],
)
@pytest.mark.parametrize("level", ["simple", "advanced"])
async def test_the_reaction_is_offered_only_where_allowed_at_both_levels(
    hass: HomeAssistant,
    entities: dict[str, str],
    level: str,
    control: dict[str, str],
    offered: bool,
) -> None:
    """Decision 7: the reaction to an ignored write — the one left to choose — is offered where
    a thermostat takes over, at both levels (a reaction stored earlier is never hidden); stand-
    alone it is not. The return by itself stays advanced."""
    loaded_gateway(hass, "living_room_gw")
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, level, ("living",))
    result = await open_control(hass, entry_id)
    answer = {"write_path": "opentherm_gw", "confirmed_entity": "sensor.gw_control_setpoint"}
    result = await options_step(hass, result, answer | control)
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    curve = CURVE_ANSWERS if level == "simple" else ADVANCED_CURVE
    result = await options_step(hass, result, curve)
    if level == "advanced":
        result = await options_step(hass, result, {"off_setpoint": 10})
    if not offered and level == "simple":
        assert result["type"] is FlowResultType.CREATE_ENTRY  # nothing to ask
        return
    assert result["step_id"] == "control_alarms"
    fields = {str(marker) for marker in result["data_schema"].schema}
    assert ("write_ignored" in fields) is offered
    assert ("return_after_outside_change" in fields) is (level == "advanced")
    assert not {"pressure_low", "pressure_high", "flue_gas_high", "write_failed"} & fields


async def test_restoring_defaults_resets_the_reaction(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """ "Restore defaults" on the way to the simple level resets the ignored write's reaction
    to information; afterwards the simple level shows it again, at its default."""
    loaded_gateway(hass, "living_room_gw")
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await open_control(hass, entry_id)
    answer = {
        "write_path": "opentherm_gw",
        "confirmed_entity": "sensor.gw_control_setpoint",
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
    }
    result = await options_step(hass, result, answer)
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    result = await options_step(hass, result, ADVANCED_CURVE)
    result = await options_step(hass, result, {"off_setpoint": 10})
    result = await options_step(hass, result, {"write_ignored": "hand_back"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control["alarm_reactions"] == {"write_ignored": "hand_back"}
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level" in menu["menu_options"]  # shown at both levels: nothing hidden
    result = await options_step(hass, menu, {"next_step_id": "level"})
    result = await options_step(hass, result, {"level": "simple", "restore_defaults": True})
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "alarm_reactions" not in control
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, answer)
    result = await options_step(hass, result, {"gateway_id": "living_room_gw"})
    result = await options_step(hass, result, CURVE_ANSWERS)
    assert result["step_id"] == "control_alarms"
    assert form_default(result, "write_ignored") == "info"


def test_a_reaction_stored_at_the_simple_level_is_not_hidden() -> None:
    """The finding of the checks: a hand-back reaction stored earlier stayed active at the
    simple level, hidden. Now the one reaction left is shown at the simple level, and any other
    stored one only informs — the menu does not count it as a hidden setting."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    options = {
        "level": "simple",
        "control": {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "alarm_reactions": {"write_ignored": "hand_back", "pressure_low": "hand_back"},
        },
    }
    assert "write_ignored" in {str(m) for m in flow.control_alarms_schema(options).schema}
    assert not flow.has_hidden_advanced(options)


def test_the_relays_power_threshold_is_a_hidden_setting_kept_by_restore_defaults() -> None:
    """PB-71: the power above which the boiler counts as heating (advanced) stays active at the
    simple level, so the menu flags it as a hidden setting; it is a fact about the boiler, so
    "restore defaults" keeps it. Negative: without it nothing is hidden."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    control = {"write_path": "relay", "relay_entity": "switch.relay"}
    options: dict[str, Any] = {"level": "simple", "control": dict(control)}
    assert not flow.has_hidden_advanced(options)
    options["control"]["boiler_heats_above_w"] = 300
    assert flow.has_hidden_advanced(options)
    flow.restore_advanced_defaults(options)
    assert options["control"]["boiler_heats_above_w"] == 300


# --- Z1: the config and options flows at 100 % with branches (P-34, Appendix D) -----------------


def test_the_form_helpers_refuse_what_they_cannot_read() -> None:
    """Negatives for the helpers: a topic that is not a text is no topic; a missing value is
    inside any range (the form fills every field it shows, so only a hand edit lacks one); a
    control section that cannot be read names no entity of its own; the steps' base has no
    next step of its own."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    assert not flow.mqtt_topic_valid(None)
    assert not flow.mqtt_topic_valid(7)
    assert flow.mqtt_topic_valid(" OTGW/ ")
    assert not flow._outside(None, (20.0, 60.0))
    assert not flow._outside("", (20.0, 60.0))
    assert flow._outside(10.0, (20.0, 60.0))
    signals = {"signals": {"flame": "binary_sensor.flame"}}
    assert flow.boiler_side_entities(signals | {"control": "garbled"}) == ["binary_sensor.flame"]
    assert flow.boiler_side_entities(signals | {"control": {"confirmed_entity": "sensor.x"}}) == [
        "binary_sensor.flame",
        "sensor.x",
    ]
    with pytest.raises(NotImplementedError):
        flow._Steps._next_after(flow.SmartBoilerConfigFlow(), "zones")


async def test_a_timeout_hand_back_needs_expiring_writes(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Appendix D (``hand_back_timeout_not_expiring``): only a value that lapses goes back on
    its own — a held one would stay for good; declared expiring, the step passes."""
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    details = {"setpoint_entity": "number.boiler_flow", "hand_back": "timeout"}
    result = await options_step(hass, result, details | {"write_type": "held"})
    assert (result["step_id"], result["errors"]) == (
        "control_entity",
        {"hand_back": "hand_back_timeout_not_expiring"},
    )
    result = await options_step(hass, result, details | {"write_type": "expiring"})
    assert result["step_id"] == "control_curve"


async def test_the_timeout_method_asks_the_devices_own_timeout(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 5 (SB-04): the writable-entity step asks the device's own timeout, in minutes,
    offered at its cautious default of 1 and refused outside 1 to 60; kept with the timeout
    method, dropped with any other — and a stored one offered again."""
    from custom_components.vtherm_smart_boiler.config_flow import (
        apply_control_details,
        control_entity_schema,
    )

    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    assert result["step_id"] == "control_entity"
    assert form_default(result, "hand_back_timeout_min") == 1
    details = {"setpoint_entity": "number.boiler_flow", "write_type": "expiring"}
    for minutes in (0, 61):
        with pytest.raises(InvalidData):
            await options_step(
                hass, result, details | {"hand_back": "timeout", "hand_back_timeout_min": minutes}
            )
    result = await options_step(
        hass, result, details | {"hand_back": "timeout", "hand_back_timeout_min": 5}
    )
    assert result["step_id"] == "control_curve"
    options: dict[str, Any] = {"control": {"write_path": "entity"}}
    apply_control_details(options, details | {"hand_back": "timeout", "hand_back_timeout_min": 5})
    assert options["control"]["hand_back_timeout_min"] == 5
    stored = {"result": None, "data_schema": control_entity_schema(options)}
    assert form_default(stored, "hand_back_timeout_min") == 5
    apply_control_details(
        options,
        details
        | {"hand_back": "value", "hand_back_value": 30, "hand_back_timeout_min": 5}
        | {"hand_back_value_effect": "own_control"},
    )
    assert "hand_back_timeout_min" not in options["control"]


async def test_the_entity_steps_targets_are_checked_on_the_server(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """P-79 on the entity path: a setpoint target outside the field's filter — here the boiler's
    flow sensor, which takes no value — is refused before anything about it is judged."""
    hass.states.async_set("number.boiler_flow", "45", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    answer = {
        "write_type": "expiring",
        "hand_back": "value",
        "hand_back_value": 30,
        "hand_back_value_effect": "own_control",
    }
    result = await options_step(hass, result, answer | {"setpoint_entity": entities["flow"]})
    assert (result["step_id"], result["errors"]) == (
        "control_entity",
        {"setpoint_entity": "entity_not_suitable"},
    )
    result = await options_step(hass, result, answer | {"setpoint_entity": "number.boiler_flow"})
    assert result["step_id"] == "control_curve"


async def test_foreign_heat_sources_of_every_kind_and_the_zones_emitter_size(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Appendix D: the kinds a foreign heat source can be — a switch, a binary sensor, a power
    sensor, a temperature sensor — each stored with its kind; a temperature sensor needs its
    threshold (``temperature_threshold_missing``); at the advanced level the zone's emitter size
    and exponent are stored as entered."""
    hass.states.async_set("binary_sensor.stove", "off")
    hass.states.async_set(
        "sensor.stove_temperature",
        "22",
        {"device_class": "temperature", "unit_of_measurement": "°C"},
    )
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "zones"})
    assert result["step_id"] == "zones"
    result = await options_step(hass, result, {"zones": [entities["living"]]})
    assert result["step_id"] == "zone"
    sources = [
        "switch.fireplace",
        "binary_sensor.stove",
        "sensor.heater_power",
        "sensor.stove_temperature",
    ]
    zone = {"emitter": "radiator", "reference_output_w": 1500, "exponent": 1.25}
    result = await options_step(hass, result, zone | {"foreign_heat": sources})
    assert (result["step_id"], result["errors"]) == (
        "zone",
        {"foreign_heat": "temperature_threshold_missing"},
    )
    result = await options_step(
        hass, result, zone | {"foreign_heat": sources, "temperature_threshold": 30}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY  # the section saves at once
    await hass.async_block_till_done()
    (stored,) = hass.config_entries.async_get_entry(entry_id).options["zones"]
    assert stored["reference_output_w"] == 1500
    assert stored["exponent"] == 1.25
    assert stored["foreign_heat"] == [
        {"entity_id": "switch.fireplace", "kind": "switch"},
        {"entity_id": "binary_sensor.stove", "kind": "binary"},
        {"entity_id": "sensor.heater_power", "kind": "power"},
        {"entity_id": "sensor.stove_temperature", "kind": "temperature", "threshold": 30},
    ]


async def test_a_blocker_text_without_a_count_is_given_whole(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The confirmation takes a blocker's text as the switch gives it; one with no sentence
    counting the other reasons — a language whose text lacks it — is given whole."""
    from custom_components.vtherm_smart_boiler import config_flow as flow_module

    texts = {f"component.{DOMAIN}.exceptions.blocked_no_zones.message": "No zone at all."}

    async def translations(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        return texts

    monkeypatch.setattr(flow_module, "async_get_translations", translations)
    flow = flow_module.SmartBoilerOptionsFlow()
    flow.hass = hass
    assert await flow._async_blocker_text("no_zones") == "No zone at all."


async def test_the_relay_path_follows_the_allow_list_to_the_alarm_step(
    hass: HomeAssistant, entities: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay's behaviour step goes where the allow-list says: straight to the save today
    (decision 7 offers a relay no reaction), and to the alarm step should it ever offer one —
    the routing reads the allow-list, not the path."""
    from custom_components.vtherm_smart_boiler import config_flow as flow_module

    monkeypatch.setattr(flow_module, "alarm_step_offered", lambda _options: True)
    entry_id = await create_entry(hass, entities, "simple", ("living",), "on_off")
    result = await to_relay_step(hass, entry_id)
    result = await options_step(hass, result, RELAY_ANSWERS)
    assert result["step_id"] == "control_relay_behaviour"
    result = await options_step(hass, result, {"activation_delay_s": 0})
    assert result["step_id"] == "control_alarms"


async def test_a_frost_zone_must_be_a_configured_vt_zone(
    hass: HomeAssistant, entities: dict[str, str], zones: FakeZones
) -> None:
    """P-79 for the frost zone. The form's own selector offers the configured zones only, and
    Home Assistant refuses anything else before the step sees it; the step checks again on its
    own, on the curve step and on the relay's behaviour step, for an answer that reaches it
    unchecked (a stale form): a VT zone the options do not hold is not suitable, a climate that
    is not VT's is no zone at all, and a configured zone passes."""
    from homeassistant.data_entry_flow import InvalidData

    from custom_components.vtherm_smart_boiler.config_flow import SmartBoilerOptionsFlow

    other_vt = zones.add("attic")
    hass.states.async_set("climate.not_vt", "heat")
    loaded_gateway(hass, "living_room_gw")
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_curve(hass, entry_id)
    with pytest.raises(InvalidData):
        await options_step(hass, result, ADVANCED_CURVE | {"frost_zone": other_vt})
    result = await options_step(hass, result, ADVANCED_CURVE | {"frost_zone": entities["living"]})
    assert result["step_id"] == "control_behaviour"

    flow = SmartBoilerOptionsFlow()
    flow.hass = hass
    flow.handler = entry_id
    flow.flow_id = "unchecked"
    flow._options = {
        **hass.config_entries.async_get_entry(entry_id).options,
        "control": {"write_path": "opentherm_gw", "gateway_id": "living_room_gw"},
    }
    for zone, error in ((other_vt, "entity_not_suitable"), ("climate.not_vt", "zone_not_vt")):
        shown = await flow.async_step_control_curve(ADVANCED_CURVE | {"frost_zone": zone})
        assert (shown["step_id"], shown["errors"]) == ("control_curve", {"frost_zone": error})
    flow._options["control"] = {"write_path": "relay"}
    answer = {"activation_delay_s": 0, "count_threshold": 1, "frost_limit": 5, "frost_release": 7}
    shown = await flow.async_step_control_relay_behaviour(answer | {"frost_zone": "climate.not_vt"})
    assert (shown["step_id"], shown["errors"]) == (
        "control_relay_behaviour",
        {"frost_zone": "zone_not_vt"},
    )
    assert flow._frost_zone_error({"frost_zone": entities["living"]}) == {}


async def test_the_lowest_water_temperature_must_suit_the_setpoint_entity(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Appendix D (``limits_outside_entity_range``, the lowest): below what the setpoint entity
    accepts, refused on the curve step; within it, it passes."""
    hass.states.async_set(
        "number.boiler_flow", "45", {"unit_of_measurement": "°C", "min": 30, "max": 80}
    )
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "number.boiler_flow"},
    )
    result = await options_step(
        hass,
        result,
        {
            "setpoint_entity": "number.boiler_flow",
            "write_type": "expiring",
            "hand_back": "value",
            "hand_back_value": 30,
            "hand_back_value_effect": "own_control",
        },
    )
    curve = {"design_outdoor": -15, "design_flow": 55, "hard_max": 70}
    result = await options_step(hass, result, curve | {"hard_min": 25})
    assert (result["step_id"], result["errors"]) == (
        "control_curve",
        {"hard_min": "limits_outside_entity_range"},
    )
    result = await options_step(hass, result, curve | {"hard_min": 30})
    assert result["step_id"] == "control_alarms"  # a value declared "own control" (Y1)


@pytest.mark.usefixtures("gateway")
async def test_the_behaviour_step_follows_the_allow_list_to_the_save(
    hass: HomeAssistant, entities: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The behaviour step (advanced level) goes where the alarm step's content says: to the
    alarm step today, as the return by itself is offered at the advanced level on every path
    but the relay's; straight to the save should nothing be offered there — the routing reads
    the allow-list, not the level."""
    from custom_components.vtherm_smart_boiler import config_flow as flow_module

    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_curve(hass, entry_id)
    result = await options_step(hass, result, ADVANCED_CURVE)
    assert result["step_id"] == "control_behaviour"
    behaviour = {"off_setpoint": 10, "count_threshold": 1}
    shown = await options_step(hass, result, behaviour)
    assert shown["step_id"] == "control_alarms"
    monkeypatch.setattr(flow_module, "alarm_step_offered", lambda _options: False)
    result = await to_control_curve(hass, entry_id)
    result = await options_step(hass, result, ADVANCED_CURVE)
    result = await options_step(hass, result, behaviour)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert (control["topology"], control["off_setpoint"]) == ("gateway_standalone", 10)


# --- I6.1: the setup opens with how the boiler is connected -----------------------------------


def select_options(result: dict[str, Any], key: str) -> list[str]:
    for marker, validator in result["data_schema"].schema.items():
        if str(marker) == key:
            return list(validator.config["options"])
    raise AssertionError(f"no {key} in the form")


async def test_the_setup_opens_with_the_connection_and_asks_it_on_purpose(
    hass: HomeAssistant,
) -> None:
    """Decisions 1, 7, 8: the first panel asks how the boiler is connected, the heat source and
    the boiler type — every answer offered, none chosen for the user."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["step_id"] == "connection"
    assert select_options(result, "connection") == [
        "opentherm_gw", "otgw_mqtt", "esphome", "ems_esp", "relay", "boiler_module",
        "other_entity", "read_only",
    ]  # fmt: skip
    assert select_options(result, "heat_source") == ["gas", "oil", "electric", "other"]
    assert select_options(result, "type") == ["single", "single_tank", "combi", "combi_tank"]
    for key in ("connection", "heat_source", "type"):
        assert form_default(result, key) is None, key


@pytest.mark.parametrize(
    ("connection", "modes"),
    [
        ("relay", ["on_off", "monitor"]),
        ("read_only", ["monitor"]),
        ("esphome", ["full", "room_values", "monitor"]),
        ("opentherm_gw", ["full", "room_values", "monitor"]),
    ],
)
async def test_the_second_panel_offers_the_modes_the_connection_can_do(
    hass: HomeAssistant, connection: str, modes: list[str]
) -> None:
    """Decision 6: only the modes the connection can do, none chosen for the user."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await step(
        hass, result, {"connection": connection, "heat_source": "gas", "type": "single"}
    )
    assert result["step_id"] == "mode"
    assert select_options(result, "control_mode") == modes
    assert form_default(result, "control_mode") is None
    with pytest.raises(InvalidData):  # a mode the connection cannot do is not taken
        await step(hass, result, {"control_mode": "telepathy"})


@pytest.mark.parametrize(
    ("source", "kind", "shown", "stored"),
    [
        # A boiler that burns fuel is asked whether it condenses (ticked by default); one that
        # heats hot water whether hot water has priority (on by default).
        (
            "gas",
            "combi",
            {"condensing", "dhw_priority"},
            {"condensing": True, "dhw_priority": True},
        ),
        ("oil", "single", {"condensing"}, {"condensing": True}),
        # Electric: it burns nothing — not condensing, not asked.
        ("electric", "single_tank", {"dhw_priority"}, {"condensing": False, "dhw_priority": True}),
        ("electric", "single", set(), {"condensing": False}),
    ],
)
async def test_condensing_and_the_hot_water_priority_are_asked_where_they_apply(
    hass: HomeAssistant, source: str, kind: str, shown: set[str], stored: dict[str, Any]
) -> None:
    """Decisions 7, 8: the second panel asks condensing for a boiler that burns fuel and the
    hot-water priority for one that heats hot water, each with its default; what is not asked
    is stored as it must be — an electric boiler does not condense, one without hot water keeps
    no priority."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    answers = {"connection": "other_entity", "heat_source": source, "type": kind}
    result = await step(hass, result, answers)
    asked = {str(marker) for marker in result["data_schema"].schema} - {"control_mode"}
    assert asked == shown
    result = await step(hass, result, {"control_mode": "full"})
    for data in (
        {"name": "Boiler", "level": "simple"},
        {},
        {},
        {"control": "unmixed_shared"},
        {"zones": []},
        {},
        {"strategy": "average"},
    ):
        result = await step(hass, result, data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    boiler = result["options"]["boiler"]
    assert {key: boiler[key] for key in stored} == stored
    if "dhw_priority" not in stored:
        assert "dhw_priority" not in boiler
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("connection", "mode", "expected"),
    [
        ("boiler_module", "full", "flow_setpoint"),
        ("boiler_module", "monitor", "read_only"),  # decision 5: monitoring by default
        ("relay", "on_off", "on_off"),
        ("opentherm_gw", "monitor", "flow_setpoint"),  # what it can do, not what is wanted
    ],
)
async def test_the_class_follows_the_connection(
    hass: HomeAssistant, entities: dict[str, str], connection: str, mode: str, expected: str
) -> None:
    """Decision 2: the boiler class is no longer asked; the options' panels set it."""
    entry_id = await create_entry(hass, entities, "simple", panels=True)
    menu = await hass.config_entries.options.async_init(entry_id)
    assert menu["menu_options"][0] == "connection"
    result = await options_step(hass, menu, {"next_step_id": "connection"})
    answers = {"connection": connection, "heat_source": "gas", "type": "single"}
    result = await options_step(hass, result, answers)
    result = await options_step(hass, result, {"control_mode": mode})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    assert entry.options["boiler"]["class"] == expected
    assert "class" not in {str(m) for m in boiler_form(hass, entry)}
    await hass.async_block_till_done()


def boiler_form(hass: HomeAssistant, entry: Any) -> Any:
    from custom_components.vtherm_smart_boiler.config_flow import boiler_schema

    return boiler_schema(dict(entry.options)).schema


async def test_an_entry_from_before_the_panels_is_offered_its_answers(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 12: an entry made before the panels keeps working as it was; its panels offer
    what its stored options say — the relay its write path names, a combi from its hot water,
    on/off from its relay — and nothing they do not (the heat source)."""
    options = {
        "level": "simple",
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {"class": "on_off", "dhw": "combi", "condensing": True},
        "control": {"write_path": "relay", "relay_entity": "switch.boiler_relay"},
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "connection"})
    assert form_default(result, "connection") == "relay"
    assert form_default(result, "type") == "combi"
    assert form_default(result, "heat_source") is None
    result = await options_step(
        hass, result, {"connection": "relay", "heat_source": "gas", "type": "combi"}
    )
    assert form_default(result, "control_mode") == "on_off"
    # An entity path names no connection; a stored storage tank suggests the commoner type.
    options["boiler"] = {"class": "flow_setpoint", "dhw": "storage"}
    options["control"] = {"write_path": "entity"}
    other = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    other.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(other.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "connection"})
    assert form_default(result, "connection") is None
    assert form_default(result, "type") == "single_tank"
    result = await options_step(
        hass, result, {"connection": "other_entity", "heat_source": "gas", "type": "single"}
    )
    assert form_default(result, "control_mode") == "full"


async def test_monitoring_only_offers_no_control(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 6: with monitoring only, or room values until 0.3, the control step offers
    "no control" alone; a path given anyway is refused with the reason."""
    from custom_components.vtherm_smart_boiler.config_flow import control_error

    entry_id = await create_entry(hass, entities, "simple", ("living",), panels=True)
    for mode in ("monitor", "room_values"):
        menu = await hass.config_entries.options.async_init(entry_id)
        result = await options_step(hass, menu, {"next_step_id": "connection"})
        answers = {"connection": "opentherm_gw", "heat_source": "gas", "type": "single"}
        result = await options_step(hass, result, answers)
        result = await options_step(hass, result, {"control_mode": mode})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()
        result = await open_control(hass, entry_id)
        assert path_options(result) == ["none"]
        entry = hass.config_entries.async_get_entry(entry_id)
        assert entry is not None
        assert control_error({"write_path": "opentherm_gw"}, dict(entry.options)) == {
            "write_path": "path_not_for_control_mode"
        }
        await hass.config_entries.options.async_configure(result["flow_id"], {"write_path": "none"})
        await hass.async_block_till_done()


async def test_an_answer_this_version_cannot_read_is_shown_on_the_first_panel(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 12 (P-70): a stored answer this version does not know — from a later version,
    say — is shown on the first panel at the next save, never as an exception; answered, the
    options save."""
    options = {
        "level": "simple",
        "signals": {"flame": entities["flame"], "flow": entities["flow"]},
        "boiler": {"class": "read_only", "dhw": "none", "connection": "carrier_pigeon"},
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    menu = await hass.config_entries.options.async_init(entry.entry_id)
    result = await options_step(hass, menu, {"next_step_id": "building"})
    result = await options_step(hass, result, {})
    assert result["step_id"] == "connection"
    assert result["errors"] == {"base": "invalid_connection"}
    assert form_default(result, "connection") is None  # not passed off as a known one
    result = await options_step(
        hass, result, {"connection": "read_only", "heat_source": "other", "type": "single"}
    )
    result = await options_step(hass, result, {"control_mode": "monitor", "condensing": False})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["boiler"]["connection"] == "read_only"


def test_a_stored_answer_this_version_cannot_read_offers_everything_and_blocks_nothing() -> None:
    """Decision 12, negative: an unknown connection offers every mode (the panel asks it again
    first); an unknown mode does not keep the control step to "no control" — the save names the
    problem on the first panel instead; unknown heat source and type ask both questions."""
    from custom_components.vtherm_smart_boiler.config_flow import (
        control_mode_off,
        mode_schema,
        modes_offered,
    )

    assert modes_offered({"boiler": {"connection": "carrier_pigeon"}}) == [
        "full", "on_off", "room_values", "monitor",
    ]  # fmt: skip
    assert not control_mode_off({"boiler": {"control_mode": "telepathy"}})
    unknown = {"boiler": {"heat_source": "peat", "type": "triple"}}
    shown = {str(marker) for marker in mode_schema(unknown).schema}
    assert shown == {"control_mode", "condensing", "dhw_priority"}


# --- I6.2: what the connection sets in the control steps (decisions 2, 3, 4) -------------------


def gateway_entity(hass: HomeAssistant, gateway: str, domain: str, key: str, **kw: Any) -> str:
    """An entity registered by the OpenTherm Gateway integration under its own unique ID."""
    from homeassistant.helpers import entity_registry as er

    return (
        er.async_get(hass)
        .async_get_or_create(domain, "opentherm_gw", f"{gateway}-boiler-{key}", **kw)
        .entity_id
    )


async def answer_panels(
    hass: HomeAssistant, entry_id: str, connection: str, mode: str = "full"
) -> None:
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "connection"})
    answers = {"connection": connection, "heat_source": "gas", "type": "single"}
    result = await options_step(hass, result, answers)
    result = await options_step(hass, result, {"control_mode": mode})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()


@pytest.mark.parametrize(
    ("connection", "offered"),
    [
        ("opentherm_gw", ["none", "opentherm_gw"]),
        ("otgw_mqtt", ["none", "otgw_mqtt"]),
        ("esphome", ["none", "entity"]),
        ("ems_esp", ["none", "entity"]),
        ("boiler_module", ["none", "entity"]),
        ("other_entity", ["none", "entity"]),
    ],
)
async def test_the_control_step_offers_the_connections_path(
    hass: HomeAssistant, entities: dict[str, str], connection: str, offered: list[str]
) -> None:
    """Decision 2: where the connection is answered, the control step offers its path and "no
    control" — not every path the class could take."""
    entry_id = await create_entry(hass, entities, "simple", ("living",), panels=True)
    await answer_panels(hass, entry_id, connection)
    result = await open_control(hass, entry_id)
    assert path_options(result) == offered


async def test_a_path_the_connection_does_not_take_is_refused() -> None:
    """Decision 2 (P-79): checked again on submit, with the reason."""
    from custom_components.vtherm_smart_boiler.config_flow import control_error, paths_for_class

    esphome = {"boiler": {"class": "flow_setpoint", "connection": "esphome"}}
    assert control_error({"write_path": "opentherm_gw"}, esphome) == {
        "write_path": "path_not_for_connection"
    }
    read_only = {"boiler": {"class": "read_only", "connection": "read_only"}}
    assert paths_for_class(read_only) == ["none"]


@pytest.mark.parametrize("connection", ["esphome", "ems_esp"])
async def test_esphome_and_ems_esp_take_the_virtual_topology(
    hass: HomeAssistant, entities: dict[str, str], connection: str
) -> None:
    """Decision 2: the virtual topology is suggested for a controller on Home Assistant's side,
    and a gateway topology refused with the reason."""
    hass.states.async_set("sensor.read_back", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",), panels=True)
    await answer_panels(hass, entry_id, connection)
    result = await open_control(hass, entry_id)
    assert suggested(result, "topology") == "virtual"
    answer = {"write_path": "entity", "confirmed_entity": "sensor.read_back"}
    refused = await options_step(
        hass,
        result,
        answer | {"topology": "gateway_with_thermostat", "thermostat_kind": "opentherm"},
    )
    assert refused["errors"] == {"topology": "topology_not_for_connection"}
    result = await options_step(hass, refused, answer | {"topology": "virtual"})
    assert result["step_id"] == "control_entity"


def suggested(result: dict[str, Any], key: str) -> Any:
    for marker in result["data_schema"].schema:
        if str(marker) == key:
            return (marker.description or {}).get("suggested_value")
    raise AssertionError(f"no {key} in the form")


@pytest.mark.parametrize(
    ("connection", "defaults", "tick"),
    [
        # ESPHome holds both, and has no own control to return to: a hand-back value.
        ("esphome", ("held", "held", "value"), True),
        # EMS-ESP's setpoint lapses within about a minute: the device's timeout.
        ("ems_esp", ("expiring", "unknown", "timeout"), False),
        # Another device: nothing assumed.
        ("other_entity", ("unknown", "unknown", None), False),
    ],
)
async def test_the_writable_entity_step_offers_what_the_connection_does(
    hass: HomeAssistant,
    entities: dict[str, str],
    connection: str,
    defaults: tuple[str, str, str | None],
    tick: bool,
) -> None:
    """Decisions 2, 3: the write types and the hand-back the connection is known for, offered
    for the user to confirm; ESPHome's safe-start tick, never ticked for the user."""
    hass.states.async_set("sensor.read_back", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",), panels=True)
    await answer_panels(hass, entry_id, connection)
    result = await open_control(hass, entry_id)
    result = await options_step(
        hass,
        result,
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "sensor.read_back"},
    )
    assert result["step_id"] == "control_entity"
    shown = tuple(form_default(result, key) for key in ("write_type", "ch_write_type", "hand_back"))
    assert shown == defaults
    fields = {str(marker) for marker in result["data_schema"].schema}
    assert ("esphome_safe_start" in fields) is tick
    if tick:
        assert form_default(result, "esphome_safe_start") is False


async def test_ems_esp_without_a_heating_switch_does_not_ask_for_off(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 4: on EMS-ESP without a heating switch, "off" is its own setpoint 0 — the
    behaviour step does not ask it, nor checks it against the lowest water temperature; with a
    heating switch it is asked as anywhere else."""
    from custom_components.vtherm_smart_boiler.config_flow import (
        control_behaviour_schema,
        fixed_off,
        off_too_close_in,
    )

    control = {"write_path": "entity", "hard_min": 10.0, "off_setpoint": 10.0}
    ems = {"boiler": {"connection": "ems_esp"}, "control": control}
    assert fixed_off(ems)
    assert "off_setpoint" not in {str(m) for m in control_behaviour_schema(ems).schema}
    assert not off_too_close_in(ems)  # 10 next to 10 would be refused elsewhere
    other = {"boiler": {"connection": "other_entity"}, "control": control}
    assert not fixed_off(other)
    assert off_too_close_in(other)
    switched = {
        "boiler": {"connection": "ems_esp"},
        "control": control | {"ch_entity": "switch.heat", "ch_write_type": "held"},
    }
    assert not fixed_off(switched)
    assert "off_setpoint" in {str(m) for m in control_behaviour_schema(switched).schema}
    assert not fixed_off({"boiler": {"connection": "ems_esp"}})  # no control set up


async def test_the_behaviour_step_does_not_check_a_fixed_off(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 4: with "off" EMS-ESP's own 0, the advanced behaviour step saves without it,
    whatever the lowest water temperature."""
    hass.states.async_set("sensor.read_back", "40", {"unit_of_measurement": "°C"})
    hass.states.async_set(
        "number.ems_selflowtemp", "40", {"unit_of_measurement": "°C", "min": 0, "max": 90}
    )
    entry_id = await create_entry(hass, entities, "advanced", ("living",), panels=True)
    await answer_panels(hass, entry_id, "ems_esp")
    result = await open_control(hass, entry_id)
    for answer in (
        {"write_path": "entity", "topology": "virtual", "confirmed_entity": "sensor.read_back"},
        {
            "setpoint_entity": "number.ems_selflowtemp",
            "write_type": "expiring",
            "ch_write_type": "unknown",
            "hand_back": "timeout",
            "hand_back_entity_write_type": "unknown",
        },
        {"design_outdoor": -15, "design_flow": 55, "hard_min": 10, "hard_max": 70,
         "activation_delay_s": 0, "room": 20, "offset": 0, "ceiling_band": 10,
         "frost_limit": 5, "frost_release": 7},
    ):  # fmt: skip
        result = await options_step(hass, result, answer)
    assert result["step_id"] == "control_behaviour", result.get("errors")
    assert "off_setpoint" not in {str(m) for m in result["data_schema"].schema}
    result = await options_step(
        hass,
        result,
        {
            "ramp_k_per_min": 1.0,
            "decision_interval_min": 5,
            "count_threshold": 1,
            "learning_pauses": True,
            "comfort_correction": False,
        },
    )
    assert not result.get("errors"), result.get("errors")


async def test_the_gateways_own_entities_are_suggested(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 2: on the OpenTherm Gateway integration, with one gateway set up, its boiler
    device's entities are offered on the signals step — where nothing is mapped yet — and its
    read-backs on the control step, by the integration's own unique IDs; a disabled one is not.
    The hint for the connection is in the step's text."""
    loaded_gateway(hass, "gw")
    flame = gateway_entity(hass, "gw", "binary_sensor", "slave_flame_on")
    flow = gateway_entity(hass, "gw", "sensor", "ch_water_temp")
    gateway_entity(hass, "gw", "sensor", "return_water_temp", disabled_by=er_disabled_by_user())
    read_back = gateway_entity(hass, "gw", "sensor", "control_setpoint")
    echo = gateway_entity(hass, "gw", "binary_sensor", "master_ch_enabled")
    result = await start_setup(hass, "opentherm_gw", "full")
    result = await step(hass, result, {"name": "Boiler", "level": "simple"})
    assert result["step_id"] == "signals"
    assert suggested(result, "flame") == flame
    assert suggested(result, "flow") == flow
    assert suggested(result, "return") is None  # disabled: not offered
    hint = result["description_placeholders"]["hint"]
    assert hint.startswith("OpenTherm Gateway:")
    for data in (
        {"flame": flame, "flow": flow},
        {},
        {"control": "unmixed_shared"},
        {"zones": [entities["living"]]},
        {"emitter": "radiator"},
        {},
        {"strategy": "average"},
    ):
        result = await step(hass, result, data)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    entry_id = result["result"].entry_id
    result = await open_control(hass, entry_id)
    assert suggested(result, "confirmed_entity") == read_back
    assert suggested(result, "ch_confirmed_entity") == echo
    # The signals already mapped: nothing offered again.
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "signals"})
    assert suggested(result, "return") is None


def er_disabled_by_user() -> Any:
    from homeassistant.helpers import entity_registry as er

    return er.RegistryEntryDisabler.USER


async def test_nothing_is_suggested_without_exactly_one_gateway(hass: HomeAssistant) -> None:
    """Decision 2, negatives: no gateway, or two, suggest nothing; an entry from before the
    panels has no hint."""
    from custom_components.vtherm_smart_boiler.config_flow import (
        GATEWAY_SIGNALS,
        gateway_entities,
    )

    assert gateway_entities(hass, GATEWAY_SIGNALS) == {}
    loaded_gateway(hass, "a")
    gateway_entity(hass, "a", "binary_sensor", "slave_flame_on")
    assert set(gateway_entities(hass, GATEWAY_SIGNALS)) == {"flame"}
    loaded_gateway(hass, "b")
    assert gateway_entities(hass, GATEWAY_SIGNALS) == {}


async def test_an_entry_from_before_the_panels_has_no_signal_hint(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 12: no connection, no hint — the step's text as before."""
    entry_id = await create_entry(hass, entities, "simple")
    menu = await hass.config_entries.options.async_init(entry_id)
    result = await options_step(hass, menu, {"next_step_id": "signals"})
    assert result["description_placeholders"] == {"hint": ""}


# --- I6.3: the heat source decides which fields apply (decision 7) -----------------------------


@pytest.mark.parametrize(
    ("source", "hidden"),
    [
        ("electric", {"flue_gas"}),
        ("oil", {"gas_meter"}),
        ("gas", set()),
        ("other", set()),
        (None, set()),  # an entry from before the panels: every field, as before
    ],
)
def test_the_signals_step_shows_what_the_heat_source_has(
    source: str | None, hidden: set[str]
) -> None:
    """Decision 7: an electric boiler has no flue gas, an oil boiler no gas meter; every other
    signal is offered as before, at its level."""
    from custom_components.vtherm_smart_boiler.config_flow import SIGNAL_FIELDS, signals_schema

    boiler = {} if source is None else {"heat_source": source}
    shown = {str(m) for m in signals_schema({"level": "advanced", "boiler": boiler}).schema}
    assert set(SIGNAL_FIELDS) - shown == hidden


def test_a_signal_the_heat_source_hides_keeps_what_is_stored() -> None:
    """Decision 7: a signal not shown is not cleared by the save — as at the simple level."""
    from custom_components.vtherm_smart_boiler.config_flow import apply_signals

    options = {
        "level": "advanced",
        "boiler": {"heat_source": "electric"},
        "signals": {"flue_gas": "sensor.flue", "flame": "binary_sensor.flame"},
    }
    apply_signals(options, {"flame": "binary_sensor.elements"})
    assert options["signals"] == {"flue_gas": "sensor.flue", "flame": "binary_sensor.elements"}


@pytest.mark.parametrize(
    ("source", "rates"),
    [("gas", True), ("other", True), (None, True), ("oil", False), ("electric", False)],
)
def test_the_gas_rates_are_asked_for_a_gas_boiler_only(source: str | None, rates: bool) -> None:
    """Decision 7: gas per hour at minimum and maximum power — a gas boiler's, or one whose fuel
    is not said."""
    from custom_components.vtherm_smart_boiler.config_flow import boiler_schema

    boiler = {} if source is None else {"heat_source": source}
    shown = {str(m) for m in boiler_schema({"level": "advanced", "boiler": boiler}).schema}
    assert ({"gas_at_min_power", "gas_at_max_power"} <= shown) is rates
    assert "max_ch_setpoint" in shown


def test_the_flue_gas_limits_are_asked_for_a_condensing_boiler_only() -> None:
    """Decision 7: the flue-gas alarm judges a condensing boiler only — its limits are not asked
    for any other, and a stored one is kept for when it is condensing again."""
    from custom_components.vtherm_smart_boiler.config_flow import apply_monitor, monitor_schema

    condensing = {str(m) for m in monitor_schema({"boiler": {"condensing": True}}).schema}
    assert {"flue_gas_warning", "flue_gas_alarm"} <= condensing
    assert {"flue_gas_warning", "flue_gas_alarm"} <= {str(m) for m in monitor_schema({}).schema}
    other = {"boiler": {"condensing": False}, "monitor": {"flue_gas_warning": 70}}
    assert not {"flue_gas_warning", "flue_gas_alarm"} & {
        str(m) for m in monitor_schema(other).schema
    }
    apply_monitor(other, {"short_burn_min": 8})
    assert other["monitor"] == {"flue_gas_warning": 70, "short_burn_min": 8}


async def test_the_signals_hint_adds_the_heat_sources(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 7: an electric boiler's hint says to map its heating elements as the flame,
    after the connection's own."""
    result = await start_setup(hass, "other_entity", "full", source="electric")
    result = await step(hass, result, {"name": "Boiler", "level": "simple"})
    hint = result["description_placeholders"]["hint"]
    assert hint.startswith("Pick what the device shows")
    assert "Electric boiler: map the heating elements" in hint


async def test_an_electric_boiler_gets_no_unstable_ignition_alarm(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """Decision 7: an electric boiler's elements have no ignition — its unstable-ignition
    feature is inactive, naming why, and its alarm is not created; a gas boiler keeps it."""
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        FUEL_BURNER,
        Feature,
        FeatureStatus,
    )

    for source, inactive in (("electric", True), ("gas", False)):
        options = {
            "signals": {"flame": entities["flame"], "flow": entities["flow"]},
            "boiler": {
                "connection": "read_only",
                "control_mode": "monitor",
                "heat_source": source,
                "type": "single",
                "condensing": source != "electric",
            },
        }
        entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        state = entry.runtime_data.configured_features()[Feature.UNSTABLE_IGNITION]
        assert (state.status is FeatureStatus.INACTIVE) is inactive, source
        if inactive:
            assert state.missing == (FUEL_BURNER,)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
