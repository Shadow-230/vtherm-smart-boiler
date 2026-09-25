"""Control options and the configuration blockers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.control_config import (
    AlarmReaction,
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
    assert options.learning_pauses
    assert options.reaction("outside_change") is AlarmReaction.HAND_BACK
    assert options.reaction("pressure_low") is AlarmReaction.INFO
    assert config_blockers(options, RADIATORS) == []


ENTITY = {
    "write_path": "entity",
    "setpoint_entity": "number.boiler_flow",
    "write_type": "held",
    "hand_back": "value",
    "hand_back_value": 0,
    "hand_back_value_effect": "own_control",
    "confirmed_entity": "sensor.boiler_flow_setpoint",
    "topology": "virtual",
    "curve": CURVE,
}


def test_entity_path_with_a_held_setpoint() -> None:
    options = parse_control(ENTITY, RADIATORS, None)
    assert options.write_type is WriteType.HELD
    assert not options.loop.ch_writes  # no heating switch: "off" is a low setpoint
    assert options.hand_back is HandBack.VALUE
    assert options.entities == ("number.boiler_flow", "sensor.boiler_flow_setpoint")
    assert config_blockers(options, RADIATORS) == []


@pytest.mark.parametrize("write_type", ["persistent", "unknown"])
def test_nothing_goes_to_the_boilers_persistent_memory(write_type: str) -> None:
    """A setpoint the boiler stores, or might, keeps control off: it is never written."""
    options = parse_control(ENTITY | {"write_type": write_type}, RADIATORS, None)
    assert config_blockers(options, RADIATORS) == ["write_type_not_supported"]
    assert not options.loop.setpoint_guard.writable
    default = parse_control({k: v for k, v in ENTITY.items() if k != "write_type"}, RADIATORS, None)
    assert default.write_type is WriteType.UNKNOWN
    assert "write_type_not_supported" in config_blockers(default, RADIATORS)


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


def test_control_needs_a_flow_setpoint_boiler() -> None:
    for boiler_class in BoilerClass:
        installation = Installation(Boiler(boiler_class), (Circuit("main"),))
        blockers = config_blockers(parse_control(OTGW, installation, None), installation)
        assert ("boiler_not_flow_setpoint" in blockers) is (
            boiler_class is not BoilerClass.FLOW_SETPOINT
        )


def test_every_blocker_is_listed() -> None:
    from custom_components.vtherm_smart_boiler.control_config import CONFIG_BLOCKERS

    found: set[str] = set()
    cases = [
        ({}, RADIATORS),
        (OTGW | {"write_path": "entity", "curve": {}, "topology": ""}, RADIATORS),
        (OTGW | {"gateway_id": "", "confirmed_entity": "", "topology": "monitor_mode"}, RADIATORS),
        (OTGW | {"write_path": "otgw_mqtt"}, RADIATORS),
        (
            OTGW | {"write_path": "entity", "setpoint_entity": "number.x", "hand_back": "timeout"},
            RADIATORS,
        ),
    ]
    two = Installation(Boiler(BoilerClass.READ_ONLY), (Circuit("a"), Circuit("b")))
    floor = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main"),),
        (Zone("climate.a", "main", EmitterType.UNDERFLOOR),),
    )
    cases += [(OTGW, two), (OTGW, floor), (OTGW | {"count_threshold": 5}, RADIATORS)]
    for data, installation in cases:
        found |= set(config_blockers(parse_control(data, RADIATORS, None), installation))
    assert found == set(CONFIG_BLOCKERS)


@pytest.mark.parametrize(
    ("changes", "effect"),
    [
        ({"topology": "gateway_with_thermostat"}, "thermostat_takes_over"),
        ({"topology": "gateway_standalone"}, "heating_stops"),
        ({"topology": "virtual"}, "device_decides"),
        ({"topology": "monitor_mode"}, None),
        ({"topology": ""}, None),
    ],
)
def test_hand_back_effect_follows_the_topology(changes: dict, effect: str | None) -> None:
    from custom_components.vtherm_smart_boiler.control_config import hand_back_effect

    result = hand_back_effect(parse_control(OTGW | changes, RADIATORS, None))
    assert (None if result is None else result.value) == effect


@pytest.mark.parametrize(
    ("ch_write_type", "switched"),
    [("expiring", True), ("held", True), ("persistent", False), ("unknown", False), (None, False)],
)
def test_a_heating_switch_only_with_writes_that_do_not_wear(
    ch_write_type: str | None, switched: bool
) -> None:
    """The heating switch declares its own write type; one the boiler may store is left alone
    and "off" goes as a low setpoint instead."""
    data = ENTITY | {"ch_entity": "switch.ch"}
    if ch_write_type is not None:
        data["ch_write_type"] = ch_write_type
    options = parse_control(data, RADIATORS, None)
    assert options.loop.ch_writes is switched
    assert config_blockers(options, RADIATORS) == []


@pytest.mark.parametrize(
    ("write_type", "blocked"),
    [("expiring", False), ("held", True), ("persistent", True), ("unknown", True)],
)
def test_a_timeout_hand_back_needs_writes_that_lapse(write_type: str, blocked: bool) -> None:
    data = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": write_type,
        "hand_back": "timeout",
        "confirmed_entity": "sensor.flow_setpoint",
        "topology": "virtual",
        "curve": CURVE,
    }
    blockers = config_blockers(parse_control(data, RADIATORS, None), RADIATORS)
    # A value that never lapses would stay with the boiler for good.
    assert ("timeout_needs_expiring_writes" in blockers) is blocked


def test_an_expiring_heating_override_is_repeated_with_the_setpoint() -> None:
    otgw = parse_control(OTGW, RADIATORS, None)
    assert otgw.loop.switch_guard.keepalive_s == 30.0
    held = parse_control(
        ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "held"}, RADIATORS, None
    )
    assert held.loop.switch_guard.keepalive_s is None  # the device keeps it
    expiring = parse_control(
        ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "expiring"}, RADIATORS, None
    )
    assert expiring.loop.switch_guard.keepalive_s == 30.0


@pytest.mark.parametrize("missing", ["hand_back_value", "hand_back_value_effect"])
def test_a_value_hand_back_is_declared_with_its_effect(missing: str) -> None:
    """0 means "no heat" on one device and "own control" on another: neither the value nor what
    it does is ever assumed."""
    options = parse_control({k: v for k, v in ENTITY.items() if k != missing}, RADIATORS, None)
    assert "no_hand_back" in config_blockers(options, RADIATORS)


@pytest.mark.parametrize(
    ("effect", "shown"), [("own_control", "device_decides"), ("heating_stops", "heating_stops")]
)
def test_the_declared_effect_is_what_the_switch_shows(effect: str, shown: str) -> None:
    from custom_components.vtherm_smart_boiler.control_config import hand_back_effect

    options = parse_control(ENTITY | {"hand_back_value_effect": effect}, RADIATORS, None)
    assert options.hand_back_value == 0.0
    result = hand_back_effect(options)
    assert result is not None
    assert result.value == shown


def test_frequent_starts_are_information_only() -> None:
    """Nothing the plugin counts may hold heating against VT: the starts alarm never hands
    back, whatever an older configuration says."""
    options = parse_control(
        OTGW | {"alarm_reactions": {"frequent_starts": "hand_back"}}, RADIATORS, None
    )
    assert options.reaction("frequent_starts") is AlarmReaction.INFO


def test_the_count_threshold_must_fit_the_zones() -> None:
    options = parse_control(OTGW | {"count_threshold": 2}, RADIATORS, None)
    assert config_blockers(options, RADIATORS) == ["count_threshold_above_zones"]
    assert config_blockers(parse_control(OTGW, RADIATORS, None), RADIATORS) == []


def test_frost_protection_watches_the_zone_picked_or_every_zone() -> None:
    picked = parse_control(OTGW | {"frost_zone": "climate.a"}, RADIATORS, None)
    assert picked.loop.control.frost.zone == "climate.a"
    assert parse_control(OTGW, RADIATORS, None).loop.control.frost.zone is None
    # A zone no longer configured must not leave frost protection watching nothing.
    gone = parse_control(OTGW | {"frost_zone": "climate.gone"}, RADIATORS, None)
    assert gone.loop.control.frost.zone is None
