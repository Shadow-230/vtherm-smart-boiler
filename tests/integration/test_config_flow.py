"""Config flow and options flow: simple and advanced paths, errors, level switch."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.vtherm_smart_boiler.config import EntryConfig
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import WEATHER_ENTITY, FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


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


async def test_simple_flow_creates_an_entry(hass: HomeAssistant, entities: dict[str, str]) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
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
        {
            "class": "read_only",
            "dhw": "storage",
            "condensing": True,
            "boiler_min_power": 4.0,
            "boiler_max_power": 24.0,
        },
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
    await hass.async_block_till_done()


async def test_advanced_flow_with_two_circuits(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
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
        {
            "class": "flow_setpoint",
            "dhw": "combi",
            "condensing": True,
            "modulation_scale": "capacity",
            "boiler_min_power": 30.0,
            "boiler_max_power": 20.0,
        },
    )
    assert result["errors"] == {"base": "min_power_not_below_max"}
    result = await step(
        hass,
        result,
        {
            "class": "flow_setpoint",
            "dhw": "combi",
            "condensing": True,
            "modulation_scale": "capacity",
        },
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
    hass: HomeAssistant, entities: dict[str, str], level: str, zones: tuple[str, ...] = ()
) -> str:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    for data in (
        {"name": "Boiler", "level": level},
        {"flame": entities["flame"], "flow": entities["flow"]},
        {"class": "read_only", "dhw": "none", "condensing": True}
        | ({"modulation_scale": "capacity"} if level == "advanced" else {}),
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
    return result["result"].entry_id


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
    assert "monitor" not in entry.options  # tuning: back to its defaults
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
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(domain="opentherm_gw", data={"id": "living_room_gw"}).add_to_hass(hass)
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
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert control == {
        "write_path": "opentherm_gw",
        "topology": "gateway_with_thermostat",
        "confirmed_entity": "sensor.gw_control_setpoint",
        "ch_confirmed_entity": "binary_sensor.gw_central_heating",
        "gateway_id": "living_room_gw",
        "curve": {"design_outdoor": -18, "design_flow": 52},
        "hard_min": 25,
        "hard_max": 65,
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
    result = await options_step(hass, result, {"off_setpoint": 30})  # hard minimum 25
    assert result["errors"] == {"off_setpoint": "off_setpoint_not_below_hard_min"}
    result = await options_step(hass, result, {"ramp_k_per_min": 0.5, "off_setpoint": 12})
    assert result["step_id"] == "control_alarms"
    # Another controller always makes the plugin step aside: no reaction to choose (S-11).
    assert "outside_change" not in result["data_schema"].schema
    result = await options_step(hass, result, {"pressure_low": "hand_back"})
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
    assert control["alarm_reactions"]["pressure_low"] == "hand_back"
    assert "outside_change" not in control["alarm_reactions"]
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
    """S-11: another controller writing to the boiler always makes the plugin step aside. The
    alarm reactions step offers no choice for it, even where an earlier version stored one, and
    its description says so; saving the step drops the stored reaction and keeps the others."""
    import json
    from pathlib import Path

    from custom_components.vtherm_smart_boiler import config_flow as flow

    options: dict[str, Any] = {
        "level": "advanced",
        "control": {
            "write_path": "opentherm_gw",
            "alarm_reactions": {"outside_change": "info", "pressure_low": "hand_back"},
        },
    }
    schema = flow.control_alarms_schema(options)
    assert "outside_change" not in {str(marker) for marker in schema.schema}
    shown = schema({})
    assert "outside_change" not in shown
    assert shown["pressure_low"] == "hand_back"  # the others keep what the user chose
    assert shown["write_ignored"] == "info"  # and inform by default
    flow.apply_control_alarms(options, shown)
    assert "outside_change" not in options["control"]["alarm_reactions"]
    assert options["control"]["alarm_reactions"]["pressure_low"] == "hand_back"
    translations = Path(flow.__file__).parent / "translations"
    for language, sentence in (
        (
            "en",
            "Another controller writing to the boiler always makes the plugin step aside; it "
            "never fights it.",
        ),
        (
            "pl",
            "Inny sterownik piszący do kotła zawsze sprawia, że wtyczka ustępuje; nigdy z nim "
            "nie walczy.",
        ),
    ):
        texts = json.loads((translations / f"{language}.json").read_text(encoding="utf-8"))
        step = texts["options"]["step"]["control_alarms"]
        assert "outside_change" not in step["data"]
        assert "outside_change" not in step["data_description"]
        assert step["description"].endswith(sentence)


MQTT_CONTROL = {
    "write_path": "otgw_mqtt",
    "topology": "gateway_standalone",
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
    """P-43: "off" sent as a low setpoint within a kelvin of the lowest water temperature would
    not be seen as a change — refused: 24.5 against 25; 24 is allowed."""
    entry_id = await create_entry(hass, entities, "advanced", ("living",))
    result = await to_control_behaviour(hass, entry_id)
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


async def test_the_thermostats_own_setpoint_is_not_the_read_back(
    hass: HomeAssistant, entities: dict[str, str]
) -> None:
    """The optional field for an OpenTherm thermostat's own request is refused where it is the
    setpoint read-back; the optional restart indicator is kept (Q3.7)."""
    hass.states.async_set("sensor.thermostat_ch_setpoint", "40", {"device_class": "temperature"})
    hass.states.async_set("sensor.gateway_reboot_count", "3")
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    result = await open_control(hass, entry_id)
    control = MQTT_CONTROL | {"topology": "gateway_with_thermostat"}
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
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    for data in (
        {"name": "Boiler", "level": "advanced"},
        {"flame": entities["flame"], "flow": entities["flow"]},
        {"class": "read_only", "dhw": "none", "condensing": True,
         "modulation_scale": "range"},
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
    from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    assert "monitor" not in options  # tuning


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
    would make every write fail."""
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    MockConfigEntry(domain="opentherm_gw", data={"id": "living_room_gw"}).add_to_hass(hass)
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry_id = await create_entry(hass, entities, "simple", ("living",))
    base = {"topology": "gateway_with_thermostat", "confirmed_entity": "sensor.gw_control_setpoint"}
    result = await open_control(hass, entry_id)
    result = await options_step(hass, result, {"write_path": "opentherm_gw"} | base)
    result = await options_step(hass, result, {"gateway_id": "no_such_gateway"})
    assert result["errors"] == {"gateway_id": "gateway_unknown"}
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
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
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
    from pytest_homeassistant_custom_component.common import MockConfigEntry

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
    for topology in ("gateway_standalone", "gateway_with_thermostat"):
        shown = await fields({"write_path": "entity", "topology": topology} | read_back)
        assert "own_room_controller" not in shown
        for path in ("opentherm_gw", "otgw_mqtt"):
            shown = await fields({"write_path": path, "topology": topology} | read_back)
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
            "confirmed_entity": "number.boiler_flow",
        },
    )
    result = await options_step(hass, result, details | own)
    assert result["step_id"] == "control_curve"
    result = await options_step(
        hass, result, {"design_outdoor": -15, "design_flow": 50, "hard_min": 25, "hard_max": 60}
    )
    await hass.async_block_till_done()
    control = hass.config_entries.async_get_entry(entry_id).options["control"]
    assert "own_room_controller" not in control
