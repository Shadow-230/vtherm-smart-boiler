"""Config flow and options flow: simple and advanced paths, errors, level switch."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

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
            "shared_return": False,
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
            "shared_return": False,
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
        | ({"modulation_scale": "range", "shared_return": True} if level == "advanced" else {}),
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
    assert entry.options["boiler"]["shared_return"] is True

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
    assert entry.options["boiler"]["shared_return"] is True  # kept, still active
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level_hidden" in menu["menu_options"]
    await hass.config_entries.options.async_configure(
        menu["flow_id"], {"next_step_id": "level_hidden"}
    )
    await switch(restore=True)
    entry = hass.config_entries.async_get_entry(entry_id)
    assert "shared_return" not in entry.options["boiler"]
    assert "monitor" not in entry.options
    menu = await hass.config_entries.options.async_init(entry_id)
    assert "level" in menu["menu_options"]


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
    entry_id = await create_entry(hass, entities, "simple")
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
    entry_id = await create_entry(hass, entities, "simple")
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
    assert result["data_schema"]({})["outside_change"] == "hand_back"  # the default
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
    assert control["alarm_reactions"]["outside_change"] == "hand_back"
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
