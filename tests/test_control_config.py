"""Control options and the configuration blockers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.control_config import (
    AlarmReaction,
    CapReaction,
    HandBack,
    Topology,
    WritePath,
    config_blockers,
    parse_control,
)
from custom_components.vtherm_smart_boiler.core.guards import WriteType
from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    CircuitControl,
    EmitterType,
    Installation,
    Zone,
)

RADIATORS = Installation(
    Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),), (Zone("climate.a", "main"),)
)
CURVE = {"design_outdoor": -15, "design_flow": 55}
OTGW = {
    "write_path": "opentherm_gw",
    "gateway_id": "otgw",
    "confirmed_entity": "sensor.otgw_control_setpoint",
    "topology": "gateway_standalone",
    "curve": CURVE,
}


def test_no_write_path_means_not_configured() -> None:
    options = parse_control({}, RADIATORS, None)
    assert not options.configured
    assert config_blockers(options, RADIATORS) == ["no_write_path"]


def test_otgw_defaults_are_cautious() -> None:
    options = parse_control(OTGW, RADIATORS, 65.0)
    assert options.write_path is WritePath.OPENTHERM_GW
    assert options.write_type is WriteType.EXPIRING  # CS must be repeated
    assert options.loop.ch_writes
    control = options.loop.control
    assert control.curve.design_flow == 55.0
    assert control.curve.exponent == 1.3
    assert control.boiler_max == 65.0
    assert control.limits.hard_min == 25.0
    assert control.anticycling.min_pause_s == 300.0
    assert control.min_step == 0.0  # expiring writes need no coarse steps
    assert options.learning_pauses
    assert options.cap_reaction is CapReaction.HOLD
    assert options.reaction("outside_change") is AlarmReaction.HAND_BACK
    assert options.reaction("pressure_low") is AlarmReaction.INFO
    assert config_blockers(options, RADIATORS) == []


def test_entity_path_with_persistent_writes() -> None:
    data = {
        "write_path": "entity",
        "setpoint_entity": "number.boiler_flow",
        "write_type": "persistent",
        "hand_back": "value",
        "hand_back_value": 0,
        "confirmed_entity": "sensor.boiler_flow_setpoint",
        "topology": "virtual",
        "curve": CURVE,
        "min_change": 2.0,
        "daily_cap": 24,
        "cap_reaction": "hand_back",
    }
    options = parse_control(data, RADIATORS, None)
    assert options.write_type is WriteType.PERSISTENT
    assert not options.loop.ch_writes  # no heating switch: "off" is a low setpoint
    assert options.loop.control.min_step == 2.0
    assert options.loop.setpoint_guard.daily_cap == 24
    assert options.hand_back is HandBack.VALUE
    assert options.cap_reaction is CapReaction.HAND_BACK
    assert options.entities == ("number.boiler_flow", "sensor.boiler_flow_setpoint")
    assert config_blockers(options, RADIATORS) == []


def test_underfloor_exponent_and_circuit_cap() -> None:
    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", max_flow=40.0),),
        (Zone("climate.a", "main", EmitterType.UNDERFLOOR),),
    )
    options = parse_control(OTGW, installation, None)
    assert options.loop.control.curve.exponent == 1.1
    assert options.loop.control.circuit_max == 40.0


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        ({"write_path": "entity"}, "no_setpoint_entity"),
        ({"write_path": "entity", "setpoint_entity": "number.x"}, "no_hand_back"),
        (
            {"write_path": "entity", "setpoint_entity": "number.x", "hand_back": "switch"},
            "no_hand_back",
        ),
        ({"gateway_id": ""}, "no_gateway"),
        ({"write_path": "otgw_mqtt"}, "no_mqtt_topic"),
        ({"confirmed_entity": ""}, "no_confirmed_setpoint"),
        ({"topology": ""}, "no_topology"),
        ({"topology": "monitor_mode"}, "topology_no_control"),
        ({"curve": {}}, "curve_not_entered"),
    ],
)
def test_blockers(changes: dict, blocker: str) -> None:
    options = parse_control(OTGW | changes, RADIATORS, None)
    assert blocker in config_blockers(options, RADIATORS)


def test_one_direct_circuit_only_and_underfloor_needs_a_cap() -> None:
    two = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("a"), Circuit("b", CircuitControl.SEPARATE)),
    )
    assert "one_direct_circuit_only" in config_blockers(parse_control(OTGW, two, None), two)
    mixed = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("a", CircuitControl.SEPARATE),)
    )
    assert "one_direct_circuit_only" in config_blockers(parse_control(OTGW, mixed, None), mixed)
    floor = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main"),),
        (Zone("climate.a", "main", EmitterType.UNDERFLOOR),),
    )
    assert "underfloor_without_max_flow" in config_blockers(parse_control(OTGW, floor, None), floor)


def test_topologies() -> None:
    for topology in Topology:
        options = parse_control(OTGW | {"topology": topology.value}, RADIATORS, None)
        blocked = "topology_no_control" in config_blockers(options, RADIATORS)
        assert blocked is (topology is Topology.MONITOR_MODE)
