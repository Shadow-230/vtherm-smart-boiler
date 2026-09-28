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
    no_zones = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))
    cases += [
        (OTGW, two),
        (OTGW, floor),
        (OTGW, no_zones),
        (OTGW | {"count_threshold": 5}, RADIATORS),
        (ENTITY | {"off_setpoint": 30}, RADIATORS),
        (ENTITY | {"hand_back": "switch", "hand_back_entity": "switch.external"}, RADIATORS),
        (ENTITY | {"hand_back_value": 75}, RADIATORS),
        (ENTITY | {"hand_back_value": 10}, RADIATORS),
    ]
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
    assert otgw.loop.switch_guard.write_type is WriteType.EXPIRING
    assert otgw.loop.switch_guard.keepalive_s == otgw.loop.setpoint_guard.keepalive_s == 30.0
    held = parse_control(
        ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "held"}, RADIATORS, None
    )
    assert held.loop.switch_guard.write_type is WriteType.HELD  # the device keeps it: no repeat
    expiring = parse_control(
        ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "expiring"}, RADIATORS, None
    )
    assert expiring.loop.switch_guard.write_type is WriteType.EXPIRING


def test_heating_on_off_is_judged_only_with_an_echo() -> None:
    """Without an echo heating on/off is never judged, only shown unverified; with one it falls
    under the one-rewrite rule, as a two-valued target."""
    assert not parse_control(OTGW, RADIATORS, None).loop.switch_guard.read_back
    echoed = parse_control(OTGW | {"ch_confirmed_entity": "binary_sensor.ch"}, RADIATORS, None)
    assert echoed.loop.switch_guard.read_back
    assert echoed.loop.switch_guard.two_valued
    assert "binary_sensor.ch" in echoed.entities


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


@pytest.mark.parametrize(("off", "blocked"), [(24.5, True), (24.0, False), (25.0, True)])
def test_off_must_be_at_least_1k_below_the_hard_minimum(off: float, blocked: bool) -> None:
    """P-43 (decided): "off" as a low setpoint at least 1 K below the lowest water temperature,
    or the boiler would not see a change — the guard's 0.5 K tolerance could not tell them
    apart."""
    options = parse_control(ENTITY | {"off_setpoint": off, "hard_min": 25}, RADIATORS, None)
    assert ("off_setpoint_not_below_hard_min" in config_blockers(options, RADIATORS)) is blocked


def test_the_new_options_are_read_with_cautious_defaults() -> None:
    """X1: the return by itself is off unless stored as a clear true; the thermostat's own
    request and the restart indicator are read (both none by default) and belong to what control
    reads."""
    options = parse_control(ENTITY, RADIATORS, None)
    assert not options.return_after_outside_change
    assert options.thermostat_setpoint_entity is None
    assert options.restart_entity is None
    for stored in ("yes", 1, None):
        parsed = parse_control(ENTITY | {"return_after_outside_change": stored}, RADIATORS, None)
        assert not parsed.return_after_outside_change
    extra = {
        "return_after_outside_change": True,
        "thermostat_setpoint_entity": "sensor.thermostat_setpoint",
        "restart_entity": "sensor.uptime",
    }
    options = parse_control(ENTITY | extra, RADIATORS, None)
    assert options.return_after_outside_change
    assert {"sensor.thermostat_setpoint", "sensor.uptime"} <= set(options.entities)
    assert options.reaction("heating_off_ignored").value == "hand_back"  # fixed (answer O)


def test_off_as_a_low_setpoint_must_be_below_the_hard_minimum() -> None:
    """Else "off" would heat; with a heating switch the low setpoint is not used for "off"."""
    options = parse_control(ENTITY | {"off_setpoint": 30}, RADIATORS, None)
    assert config_blockers(options, RADIATORS) == ["off_setpoint_not_below_hard_min"]
    otgw = parse_control(OTGW | {"off_setpoint": 30}, RADIATORS, None)
    assert config_blockers(otgw, RADIATORS) == []


def test_a_passive_fixed_circuit_sets_the_floor_and_keeps_its_maximum() -> None:
    fixed = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", CircuitControl.PASSIVE_FIXED, 40.0, 55.0),),
        (Zone("climate.a", "main"),),
    )
    control = parse_control(OTGW, fixed, None).loop.control
    assert control.circuit_floor == 40.0
    assert control.circuit_max == 55.0


# --- V5: the safe hand-back's options -----------------------------------------------------------


@pytest.mark.parametrize(
    ("write_type", "blocked"),
    [
        ("expiring", False),
        ("held", False),
        ("persistent", True),
        ("unknown", True),
        (None, True),  # no migration: an entry without it is blocked until declared
        ("", True),
    ],
)
def test_an_external_switch_of_unknown_write_type_blocks_control(
    write_type: str | None, blocked: bool
) -> None:
    """P-40: the external-control switch declares its write type like every other target; one
    the boiler may store is never written, so control is blocked with it."""
    data = ENTITY | {"hand_back": "switch", "hand_back_entity": "switch.external"}
    if write_type is not None:
        data["hand_back_entity_write_type"] = write_type
    options = parse_control(data, RADIATORS, None)
    expected = WriteType(write_type) if write_type else WriteType.UNKNOWN
    assert options.hand_back_entity_write_type is expected
    blockers = config_blockers(options, RADIATORS)
    assert ("hand_back_switch_not_writable" in blockers) is blocked
    # Not asked of the other methods.
    value = parse_control(ENTITY | {"hand_back_entity_write_type": "persistent"}, RADIATORS, None)
    assert "hand_back_switch_not_writable" not in config_blockers(value, RADIATORS)


@pytest.mark.parametrize(
    ("value", "circuit_max", "boiler_max", "blocked"),
    [
        (70.0, None, None, False),  # at the hard maximum (default 70 °C)
        (70.5, None, None, True),
        (45.0, 40.0, None, True),  # the circuit's maximum
        (40.0, 40.0, None, False),
        (62.0, None, 60.0, True),  # the boiler's maximum
        (0.0, 40.0, 60.0, False),  # exempt from the hard minimum only
    ],
)
def test_a_hand_back_value_above_the_maximum_blocks_control(
    value: float, circuit_max: float | None, boiler_max: float | None, blocked: bool
) -> None:
    """S-21: the hand-back value is exempt only from the lowest water temperature; above the
    highest the boiler, the circuit or the plugin allows it blocks control, and it is never
    clamped. Without a circuit maximum only the hard and the boiler maximum bound it."""
    from custom_components.vtherm_smart_boiler.control_config import hand_back_value_problems

    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", max_flow=circuit_max),),
        (Zone("climate.a", "main"),),
    )
    options = parse_control(ENTITY | {"hand_back_value": value}, installation, boiler_max)
    assert options.hand_back_value == value  # never clamped
    blockers = config_blockers(options, installation)
    assert ("hand_back_value_above_max" in blockers) is blocked
    assert ("hand_back_value_above_max" in hand_back_value_problems(options)) is blocked


@pytest.mark.parametrize(
    ("changes", "blocked"),
    [
        ({"hand_back_value": 10.0}, True),  # "off" at 10 °C: within 0.5 K
        ({"hand_back_value": 10.5}, True),
        ({"hand_back_value": 10.6}, False),
        ({"hand_back_value": 9.5}, True),
        ({"hand_back_value": 10.0, "hand_back_value_effect": "heating_stops"}, False),
        ({"hand_back_value": 10.0, "ch_entity": "switch.ch", "ch_write_type": "held"}, False),
        # A heating switch the boiler may store is not used: "off" goes as a low setpoint.
        ({"hand_back_value": 10.0, "ch_entity": "switch.ch", "ch_write_type": "unknown"}, True),
        ({"hand_back": "timeout", "write_type": "expiring"}, False),
    ],
)
def test_off_near_an_own_control_hand_back_value_blocks_control(
    changes: dict, blocked: bool
) -> None:
    """S-49: "off" sent as a low setpoint within 0.5 K of a hand-back value declared "the
    device's own control resumes" would hand the boiler back instead of stopping heating."""
    from custom_components.vtherm_smart_boiler.control_config import hand_back_value_problems

    options = parse_control(ENTITY | changes, RADIATORS, None)
    assert options.loop.off_setpoint == 10.0
    blockers = config_blockers(options, RADIATORS)
    assert ("off_setpoint_near_hand_back_value" in blockers) is blocked
    assert ("off_setpoint_near_hand_back_value" in hand_back_value_problems(options)) is blocked


@pytest.mark.parametrize(
    ("changes", "on"),
    [
        ({"topology": "gateway_with_thermostat", "hand_back": "switch"}, True),
        ({"topology": "gateway_standalone", "hand_back": "switch"}, False),
        ({"topology": "virtual", "hand_back": "timeout"}, True),  # the device decides
        ({"hand_back_value_effect": "own_control"}, True),
        ({"hand_back_value_effect": "heating_stops"}, False),
        ({"topology": "", "hand_back": "timeout"}, True),  # unknown: never off by itself
    ],
)
def test_heating_goes_back_on_where_the_boiler_returns_to_its_own_control(
    changes: dict, on: bool
) -> None:
    """S-27: the hand-back's heating part follows its effect — on where a thermostat or the
    boiler's own control takes over, left as it is where the hand-back stops heating."""
    from custom_components.vtherm_smart_boiler.control_config import hand_back_heating_on

    options = parse_control(ENTITY | changes, RADIATORS, None)
    assert hand_back_heating_on(options) is on


# --- V7: an outside change always steps aside (S-11); who keeps frost protection (S-57) ----------


@pytest.mark.parametrize(
    "reactions",
    [
        {"outside_change": "info"},  # stored by 0.2.1's form
        {"outside_change": "hand_back"},
        {"outside_change": "no longer a reaction"},  # a hand edit: neutralised, not refused
        {"outside_change": None},
        {},
        None,
    ],
)
def test_an_outside_change_always_hands_back_whatever_is_stored(reactions: object) -> None:
    """S-11 (decision 6, the user's answer H): another controller always makes the plugin step
    aside — there is no reaction to choose, and a stored "information" is neutralised."""
    data = OTGW | {"alarm_reactions": reactions}
    options = parse_control(data, RADIATORS, None)
    assert options.reaction("outside_change") is AlarmReaction.HAND_BACK
    assert "outside_change" not in options.alarm_reactions
    assert config_blockers(options, RADIATORS) == []


def test_other_alarms_keep_their_stored_reaction_beside_the_outside_change() -> None:
    """Negative: only the outside change is fixed; the others keep what the user chose, and an
    alarm without a stored reaction informs."""
    data = OTGW | {
        "alarm_reactions": {
            "outside_change": "info",
            "pressure_low": "hand_back",
            "write_ignored": "info",
        }
    }
    options = parse_control(data, RADIATORS, None)
    assert options.reaction("pressure_low") is AlarmReaction.HAND_BACK
    assert options.reaction("write_ignored") is AlarmReaction.INFO
    assert options.reaction("pressure_high") is AlarmReaction.INFO
    assert options.reaction("an alarm this version does not know") is AlarmReaction.INFO


@pytest.mark.parametrize(
    ("data", "after_hand_back"),
    [
        (OTGW, "boiler"),  # stand-alone: the hand-back stops heating
        (OTGW | {"topology": "gateway_with_thermostat"}, "thermostat"),
        (ENTITY | {"hand_back_value_effect": "heating_stops"}, "boiler"),
        (ENTITY | {"hand_back_value_effect": "own_control"}, "device"),
        (ENTITY | {"hand_back": "timeout", "write_type": "expiring"}, "device"),  # virtual
        (OTGW | {"topology": "monitor_mode"}, None),  # control cannot run: nothing to say
        (OTGW | {"topology": ""}, None),  # the effect unknown
    ],
)
def test_the_switch_says_who_keeps_frost_protection_after_a_hand_back(
    data: dict, after_hand_back: str | None
) -> None:
    """S-57: while the session controls, the plugin keeps frost protection; otherwise whoever
    the hand-back's effect leaves it with — the thermostat, the boiler's own (if it has one)
    where the hand-back stops heating, or the boiler's or the device's own control."""
    from custom_components.vtherm_smart_boiler.control_config import (
        FrostProtection,
        frost_protection_by,
    )

    options = parse_control(data, RADIATORS, None)
    assert frost_protection_by(options, controlling=True) is FrostProtection.PLUGIN
    shown = frost_protection_by(options, controlling=False)
    assert (None if shown is None else shown.value) == after_hand_back


# --- X3: control needs a zone (S-04); the boiler's own room controller (answers F, M) -----------


def test_control_needs_at_least_one_zone() -> None:
    """S-04: without a VT zone nothing can ask for heat — a blocker that names it alone."""
    none = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))
    assert config_blockers(parse_control(OTGW, none, None), none) == ["no_zones"]
    assert "no_zones" not in config_blockers(parse_control(OTGW, RADIATORS, None), RADIATORS)


TICKED = ENTITY | {"hand_back": "timeout", "write_type": "expiring", "own_room_controller": True}


def test_the_own_room_controller_tick_makes_a_working_thermostat() -> None:
    """Answer F: the entity path with the virtual topology and the tick — every hand-back goes
    to the boiler's own control, and with every zone unknown the boiler is handed to it."""
    from custom_components.vtherm_smart_boiler.control_config import (
        FrostProtection,
        HandBackEffect,
        frost_protection_by,
        hand_back_effect,
        hand_back_heating_on,
        working_thermostat,
    )

    for data in (TICKED, ENTITY | {"own_room_controller": True}):
        options = parse_control(data, RADIATORS, None)
        assert options.own_room_controller
        assert hand_back_effect(options) is HandBackEffect.OWN_CONTROL_RESUMES
        assert working_thermostat(options)
        assert options.loop.control.working_thermostat
        assert hand_back_heating_on(options)  # like "device decides": the heating switch on
        assert frost_protection_by(options, controlling=False) is FrostProtection.DEVICE
        assert config_blockers(options, RADIATORS) == []


@pytest.mark.parametrize(
    "data",
    [
        ENTITY,  # a hand-back value declared "own control", without the tick
        ENTITY | {"hand_back": "timeout", "write_type": "expiring"},  # "device decides"
        TICKED | {"own_room_controller": False},
        TICKED | {"own_room_controller": "yes"},  # only a stored true ticks it
        TICKED | {"own_room_controller": None},
        {k: v for k, v in TICKED.items() if k != "own_room_controller"},  # missing: not ticked
    ],
)
def test_an_own_control_hand_back_value_without_the_tick_is_not_a_working_thermostat(
    data: dict,
) -> None:
    from custom_components.vtherm_smart_boiler.control_config import (
        HandBackEffect,
        hand_back_effect,
        working_thermostat,
    )

    options = parse_control(data, RADIATORS, None)
    assert hand_back_effect(options) is HandBackEffect.DEVICE_DECIDES
    assert not working_thermostat(options)
    assert not options.loop.control.working_thermostat


def test_the_tick_on_the_relay_path_counts_only_with_rest_state_on() -> None:
    """Answer M, the rule X8 wires to the relay path: the tick counts as a working thermostat
    only where the relay rests "on" (the boiler's heat-demand contact); a relay resting "on"
    without the tick does not count, nor the tick with the rest state "off"."""
    from custom_components.vtherm_smart_boiler.control_config import relay_working_thermostat

    assert relay_working_thermostat(ticked=True, rests_on=True)
    assert not relay_working_thermostat(ticked=True, rests_on=False)
    assert not relay_working_thermostat(ticked=False, rests_on=True)
    assert not relay_working_thermostat(ticked=False, rests_on=False)


@pytest.mark.parametrize(
    ("data", "effect", "working"),
    [
        (OTGW | {"topology": "gateway_with_thermostat"}, "thermostat_takes_over", True),
        (OTGW, "heating_stops", False),  # stand-alone
        (
            OTGW | {"write_path": "otgw_mqtt", "topology": "gateway_with_thermostat"},
            "thermostat_takes_over",
            True,
        ),
        (TICKED | {"topology": "gateway_with_thermostat"}, "thermostat_takes_over", True),
        (TICKED | {"topology": "gateway_standalone"}, "heating_stops", False),
    ],
)
def test_a_tick_stored_with_a_gateway_is_ignored(data: dict, effect: str, working: bool) -> None:
    """Answer M: the tick is not offered with a gateway — the thermostat on its terminals
    already counts, and with nothing on them a hand-back stops heating anyway. A tick stored
    there (hand-edited, left from another path or topology) changes nothing."""
    from custom_components.vtherm_smart_boiler.control_config import (
        hand_back_effect,
        working_thermostat,
    )

    ticked = parse_control(data | {"own_room_controller": True}, RADIATORS, None)
    plain = parse_control(data, RADIATORS, None)
    for options in (ticked, plain):
        shown = hand_back_effect(options)
        assert shown is not None
        assert shown.value == effect
        assert working_thermostat(options) is working
        assert options.loop.control.working_thermostat is working


def test_a_tick_with_a_hand_back_value_that_stops_heating_is_ignored() -> None:
    """Refused in the form; hand-edited, the cautious reading: heating stops, no working
    thermostat."""
    from custom_components.vtherm_smart_boiler.control_config import (
        HandBackEffect,
        hand_back_effect,
        working_thermostat,
    )

    data = ENTITY | {"hand_back_value_effect": "heating_stops", "own_room_controller": True}
    options = parse_control(data, RADIATORS, None)
    assert hand_back_effect(options) is HandBackEffect.HEATING_STOPS
    assert not working_thermostat(options)


# --- X4: VT's activation delay (decision 5), frost's closed zones (decision 4), the circuit
# alarm information only (decision 10) ----------------------------------------------------------


def test_the_activation_delay_is_read_with_its_cautious_default() -> None:
    """0 s by default (VT's), the stored value otherwise; outside 0–600 s the parser raises.
    Never taken from VT at parse time: only what the user saved counts."""
    from custom_components.vtherm_smart_boiler.control_config import CONTROL_DEFAULTS

    assert CONTROL_DEFAULTS["activation_delay_s"] == 0
    assert parse_control(OTGW, RADIATORS, None).loop.control.activation_delay_s == 0.0
    stored = parse_control(OTGW | {"activation_delay_s": 120}, RADIATORS, None)
    assert stored.loop.control.activation_delay_s == 120.0
    assert parse_control(OTGW | {"activation_delay_s": None}, RADIATORS, None).loop.control
    for bad in (-10, 700):
        with pytest.raises(ValueError, match="activation delay"):
            parse_control(OTGW | {"activation_delay_s": bad}, RADIATORS, None)


def test_zones_declared_closed_when_off_reach_frost_protection() -> None:
    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main"),),
        (Zone("climate.a", "main", closes_when_off=True), Zone("climate.b", "main")),
    )
    frost = parse_control(OTGW, installation, None).loop.control.frost
    assert frost.closes_when_off == frozenset({"climate.a"})
    assert parse_control(OTGW, RADIATORS, None).loop.control.frost.closes_when_off == frozenset()


def test_the_circuit_too_hot_alarm_is_information_only() -> None:
    """Decision 10: an information alarm — no hand-back, whatever an edited option says."""
    options = parse_control(
        OTGW | {"alarm_reactions": {"circuit_too_hot": "hand_back"}}, RADIATORS, None
    )
    assert options.reaction("circuit_too_hot") is AlarmReaction.INFO
