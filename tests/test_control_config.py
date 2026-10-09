"""Control options and the configuration blockers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.control_config import (
    CONNECTION_MODES,
    AlarmReaction,
    Connection,
    ControlMode,
    HandBack,
    Topology,
    WritePath,
    boiler_class_for,
    config_blockers,
    connection_suggested_by,
    fixed_keys,
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
from custom_components.vtherm_smart_boiler.core.signals import Signal

RADIATORS = Installation(
    Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),), (Zone("climate.a", "main"),)
)
CURVE = {"design_outdoor": -15, "design_flow": 55}
OTGW = {
    "write_path": "opentherm_gw",
    "gateway_id": "otgw",
    "confirmed_entity": "sensor.otgw_control_setpoint",
    "topology": "gateway_standalone",
    "thermostat_kind": "none",  # nothing on the gateway's thermostat terminals (decision 1)
    "curve": CURVE,
}
# A gateway with an OpenTherm thermostat on its terminals.
WITH_THERMOSTAT = {"topology": "gateway_with_thermostat", "thermostat_kind": "opentherm"}
# X8: an on/off boiler switched through a relay, the separate-contact tick given (answer G).
ON_OFF = Installation(Boiler(BoilerClass.ON_OFF), (Circuit("main"),), (Zone("climate.a", "main"),))
RELAY = {
    "write_path": "relay",
    "relay_entity": "switch.boiler_relay",
    "relay_is_separate_contact": True,
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
    assert control.limits.hard_min == 20.0  # the lowest water temperature (decision 2)
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
# The entity path with the virtual topology and answer F's tick "the boiler has its own room
# controller".
TICKED = ENTITY | {"hand_back": "timeout", "write_type": "expiring", "own_room_controller": True}


def test_entity_path_with_a_held_setpoint() -> None:
    options = parse_control(ENTITY, RADIATORS, None)
    assert options.write_type is WriteType.HELD
    assert not options.loop.ch_writes  # no heating switch: "off" is a low setpoint
    assert options.hand_back is HandBack.VALUE
    assert options.entities == ("number.boiler_flow", "sensor.boiler_flow_setpoint")
    # Decision 11: without a heating switch control is blocked until K4 lifts it.
    assert config_blockers(options, RADIATORS) == ["no_heating_switch"]


@pytest.mark.parametrize("write_type", ["persistent", "unknown"])
def test_nothing_goes_to_the_boilers_persistent_memory(write_type: str) -> None:
    """A setpoint the boiler stores, or might, keeps control off: it is never written."""
    options = parse_control(ENTITY | {"write_type": write_type}, RADIATORS, None)
    assert config_blockers(options, RADIATORS) == ["write_type_not_supported", "no_heating_switch"]
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


def test_control_needs_a_boiler_it_can_control() -> None:
    """R1: a water-temperature path needs a flow-setpoint boiler, the relay an on/off one; the
    other classes are monitored only."""
    for boiler_class in BoilerClass:
        installation = Installation(Boiler(boiler_class), (Circuit("main"),))
        blockers = config_blockers(parse_control(OTGW, installation, None), installation)
        no_control = boiler_class in (BoilerClass.CURVE_ONLY, BoilerClass.READ_ONLY)
        assert ("boiler_class_no_control" in blockers) is no_control
        assert ("path_not_for_boiler_class" in blockers) is (boiler_class is BoilerClass.ON_OFF)
        assert "boiler_not_flow_setpoint" not in blockers


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
        # X5: one entity in two roles; a topology the path cannot use; the curve's checks.
        (ENTITY | {"ch_entity": "number.boiler_flow"}, RADIATORS),
        (OTGW | {"topology": "virtual"}, RADIATORS),
        (
            OTGW
            | {"curve": {"design_outdoor": -15, "design_flow": 25, "room": 20.5}, "hard_min": 25},
            RADIATORS,
        ),
        (OTGW | {"curve": {"design_outdoor": 10, "design_flow": 55, "room": 19.5}}, RADIATORS),
        (OTGW | {"curve": {"design_outdoor": -15, "design_flow": 75}}, RADIATORS),
        # X6: what is wired to the gateway's thermostat terminals (decision 1).
        (OTGW | {"thermostat_kind": "on_off"}, RADIATORS),
        (OTGW | {"thermostat_kind": "unknown"}, RADIATORS),
        (_without_kind(OTGW), RADIATORS),
        (OTGW | {"thermostat_kind": "opentherm"}, RADIATORS),
        # PB-70: what the form refuses, for options that bypass it.
        (OTGW | {"thermostat_setpoint_entity": OTGW["confirmed_entity"]}, RADIATORS),
        (OTGW | {"write_path": "otgw_mqtt", "mqtt_top": "OTGW/#", "mqtt_node": "x"}, RADIATORS),
    ]
    for data, installation in cases:
        found |= set(config_blockers(parse_control(data, RADIATORS, None), installation))
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    shared = {Signal.RETURN: Signal.FLOW}
    found |= set(config_blockers(parse_control(OTGW, RADIATORS, None), RADIATORS, shared))
    # PB-26: the lowest water temperature above the boiler's maximum.
    found |= set(
        config_blockers(parse_control(OTGW | {"hard_min": 45}, RADIATORS, 40.0), RADIATORS)
    )
    # X8: the relay path, and flame and flow optional for the entry.
    found |= set(config_blockers(parse_control(OTGW, RADIATORS, None), RADIATORS, signals=()))
    for data, installation in (
        (RELAY, ON_OFF),
        (RELAY, RADIATORS),
        ({"write_path": "relay"}, ON_OFF),
        (RELAY | {"relay_entity": "input_boolean.x"}, ON_OFF),
        (RELAY | {"relay_is_separate_contact": False}, ON_OFF),
        (RELAY | {"restart_entity": "switch.boiler_relay"}, ON_OFF),
        (RELAY, Installation(Boiler(BoilerClass.READ_ONLY), (Circuit("main"),))),
    ):
        found |= set(config_blockers(parse_control(data, installation, None), installation))
    # I6.1 (decision 6): monitoring only, or room values until 0.3.
    for mode in (ControlMode.MONITOR, ControlMode.ROOM_VALUES):
        control = parse_control(OTGW, RADIATORS, None, control_mode=mode)
        found |= set(config_blockers(control, RADIATORS))
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
    # Decision 11: a heating switch left alone is no heating switch — control is blocked.
    assert config_blockers(options, RADIATORS) == ([] if switched else ["no_heating_switch"])


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


@pytest.mark.parametrize(
    ("stored", "timeout_s", "logged"),
    [
        (5, 300.0, False),
        (60, 3600.0, False),
        (1, 60.0, False),
        ("30", 1800.0, False),
        (None, 60.0, False),  # an entry from before the field: the shortest, 1 min
        ("", 60.0, False),
        (0, 60.0, True),  # outside 1 to 60 min (a hand edit): the shortest
        (61, 60.0, True),
        (-5, 60.0, True),
        (float("nan"), 60.0, True),
        ("soon", 60.0, True),
        (True, 60.0, True),
    ],
)
def test_the_devices_timeout_is_read_cautiously(
    stored: object, timeout_s: float, logged: bool, caplog: pytest.LogCaptureFixture
) -> None:
    """Decision 5 (SB-04): the timeout hand-back's device timeout, asked in minutes; missing,
    out of range or not a number, the shortest — "hand-back failed" rather too early than too
    late. Only a given value outside the bounds is logged."""
    data = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "expiring",
        "hand_back": "timeout",
        "confirmed_entity": "sensor.flow_setpoint",
        "topology": "virtual",
        "curve": CURVE,
    }
    if stored is not None:
        data["hand_back_timeout_min"] = stored
    assert parse_control(data, RADIATORS, None).hand_back_timeout_s == timeout_s
    assert ("outside 1 to 60 min" in caplog.text) is logged
    caplog.clear()
    other = parse_control(ENTITY | {"hand_back_timeout_min": 0}, RADIATORS, None)
    assert other.hand_back_timeout_s == 60.0  # another method: not used, and not logged
    assert "outside 1 to 60 min" not in caplog.text


@pytest.mark.parametrize("path", ["opentherm_gw", "otgw_mqtt"])
def test_the_otgw_heating_override_is_held(path: str) -> None:
    """The PIC keeps ``CH=`` until ``CH=1`` or a reset, so heating on/off is held — sent on a
    change and when the gateway returns (X1's rule) — while ``CS`` lapses unless repeated within
    a minute. Not persistent: nothing is stored, so the heating switch stays in use. It lives in
    the PIC's RAM, so it is refreshed with every ``CS`` keep-alive (provisional, K4) rather than
    every 5 minutes: a reset nothing traces loses "heating off" for 30 s at most."""
    from custom_components.vtherm_smart_boiler.control_config import OTGW_CH_REFRESH_S

    data = OTGW | {"write_path": path, "mqtt_top": "OTGW", "mqtt_node": "otgw"}
    otgw = parse_control(data, RADIATORS, None)
    assert otgw.write_type is WriteType.EXPIRING
    assert otgw.loop.setpoint_guard.write_type is WriteType.EXPIRING
    assert otgw.ch_write_type is WriteType.HELD
    assert otgw.loop.switch_guard.write_type is WriteType.HELD
    assert OTGW_CH_REFRESH_S == otgw.loop.setpoint_guard.keepalive_s == 30.0
    assert otgw.loop.switch_guard.refresh_s == OTGW_CH_REFRESH_S
    assert otgw.loop.switch_guard.writable
    assert otgw.loop.ch_writes
    # Stored write types are the entity path's: never taken on a gateway path.
    stored = parse_control(data | {"ch_write_type": "expiring"}, RADIATORS, None)
    assert stored.loop.switch_guard.write_type is WriteType.HELD
    assert stored.loop.switch_guard.refresh_s == OTGW_CH_REFRESH_S


def _run_off(data: dict, seconds: float) -> list[tuple[float, object, object]]:
    """Control steps every 10 s with no zone asking for heat — "off" commanded — and no
    read-back: what each step writes, as (time, setpoint write, heating write)."""
    from dataclasses import replace

    from custom_components.vtherm_smart_boiler.core.controller import ControlInputs
    from custom_components.vtherm_smart_boiler.core.loop import LoopState, loop_step
    from custom_components.vtherm_smart_boiler.core.readings import ZoneState

    loop = parse_control(data, RADIATORS, None).loop
    loop = replace(loop, control=replace(loop.control, ramp_k_per_min=None))  # a steady value
    state, writes, t = LoopState(), [], 0.0
    while t <= seconds:
        zone = ZoneState("climate.a", 20.0, 21.0, True, reported_at=t, valve_open=0.0)
        inputs = ControlInputs(
            now=t, dhw=False, enabled=True, zones=(zone,), outdoor_sensor=5.0, flame=False
        )
        state, out = loop_step(state, inputs, None, loop)
        writes.append((t, out.setpoint, out.heating))
        t += 10.0
    return writes


@pytest.mark.parametrize("path", ["opentherm_gw", "otgw_mqtt"])
def test_on_the_gateway_heating_off_goes_out_with_every_keep_alive(path: str) -> None:
    """Follow-up to X6 (provisional, K4): with "off" commanded on either OTGW path, ``CH=0``
    goes out with every ``CS`` keep-alive — every 30 s — not only every 5 minutes; nothing else
    is written in between."""
    from custom_components.vtherm_smart_boiler.core.guards import WriteKind

    data = OTGW | {"write_path": path, "mqtt_top": "OTGW", "mqtt_node": "otgw"}
    writes = _run_off(data, 600.0)
    _t, first_setpoint, first_heating = writes[0]
    assert first_setpoint is not None
    assert first_setpoint.kind is WriteKind.CHANGE
    assert first_heating is not None
    assert first_heating.value == 0.0  # "off": CH=0
    keep_alives = [(t, h) for t, sp, h in writes[1:] if sp is not None]
    assert [t for t, _h in keep_alives] == [30.0 * k for k in range(1, 21)]  # CS every 30 s
    for t, heating in keep_alives:
        assert heating is not None, t
        assert (heating.value, heating.kind) == (0.0, WriteKind.KEEPALIVE), t
    assert all(h is None for t, sp, h in writes[1:] if sp is None)  # nothing in between


def test_an_entity_paths_held_switch_still_refreshes_every_5_minutes() -> None:
    """Negative: on the entity path a heating switch declared held keeps X1's refresh, every 5
    minutes, even beside a setpoint entity kept alive every 30 s — only the OTGW's CH= goes with
    the keep-alive."""
    from custom_components.vtherm_smart_boiler.core.guards import HELD_REFRESH_S, WriteKind

    data = ENTITY | {"write_type": "expiring", "ch_entity": "switch.ch", "ch_write_type": "held"}
    entity = parse_control(data, RADIATORS, None)
    assert entity.loop.switch_guard.refresh_s == HELD_REFRESH_S == 300.0
    writes = _run_off(data, 600.0)
    keep_alives = [t for t, sp, _h in writes[1:] if sp is not None]
    assert keep_alives == [30.0 * k for k in range(1, 21)]  # the setpoint's, every 30 s
    refreshes = [(t, h) for t, _sp, h in writes[1:] if h is not None]
    assert [t for t, _h in refreshes] == [300.0, 600.0]
    assert all((h.value, h.kind) == (0.0, WriteKind.KEEPALIVE) for _t, h in refreshes)


def test_the_entity_paths_heating_switch_follows_its_declared_write_type() -> None:
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
    ("effect", "shown"),
    [("own_control", "own_control_resumes"), ("heating_stops", "heating_stops")],
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
    assert not options.return_after_switch_hand_back  # SB-36: its own option, off by default
    for stored in ("yes", 1, None):
        parsed = parse_control(ENTITY | {"return_after_outside_change": stored}, RADIATORS, None)
        assert not parsed.return_after_outside_change
        parsed = parse_control(ENTITY | {"return_after_switch_hand_back": stored}, RADIATORS, None)
        assert not parsed.return_after_switch_hand_back
    switch = {"return_after_switch_hand_back": True}
    assert parse_control(ENTITY | switch, RADIATORS, None).return_after_switch_hand_back
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
    assert config_blockers(options, RADIATORS) == [
        "no_heating_switch",  # decision 11; the check stays for when K4 lifts it
        "off_setpoint_not_below_hard_min",
    ]
    otgw = parse_control(OTGW | {"off_setpoint": 30}, RADIATORS, None)
    assert config_blockers(otgw, RADIATORS) == []


def test_a_passive_fixed_circuit_sets_the_floor_and_keeps_its_maximum() -> None:
    fixed = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", CircuitControl.PASSIVE_FIXED, 40.0, 55.0),),
        (Zone("climate.a", "main"),),
    )
    control = parse_control(OTGW, fixed, None).loop.control
    assert control.circuit_floor == 45.0  # its temperature and the valve's margin (S-42)
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


# --- Y1: decision 7's allow-list (S-30, S-62) ---------------------------------------------------

# Every alarm but those decision 7 lets hand back, each stored as "hand back" — as 0.2.1's form,
# an older version or a hand edit could leave them.
NOT_ALLOWED = (
    "pressure_low",
    "pressure_high",
    "flue_gas_high",
    "frequent_starts",
    "unstable_ignition",
    "pressure_falling",
    "flue_gas_rising",
    "hysteresis_drift",
    "low_flow",
    "circuit_too_hot",
    "write_failed",
    "hand_back_failed",
    "zone_unknown",
    "frost_not_warming",
    "correction_at_limit",
    "outdoor_sensor_suspect",
    "handed_back_in_frost",
    "commands_lost",
    "confirmation_missing",
    "no_zone_known",
    "demand_criterion_no_data",
    "relay_unreachable",
    "boiler_not_responding",
    "an alarm this version does not know",
)
ALWAYS = ("control_error", "boiler_link_lost", "outside_change", "monitor_failed")
# The plugin can no longer switch heating off: "off" ignored from the start (answer O), or a
# relay's "off" no longer taken in the session (decision 6 of 0.2.3); or it cannot make the boiler
# heat: "on" ignored from the start (decision 4 of 0.2.3).
OFF_NOT_TAKEN = ("heating_off_ignored", "relay_off_not_taken", "heating_on_ignored")


@pytest.mark.parametrize("data", [OTGW, OTGW | WITH_THERMOSTAT, ENTITY])
def test_only_allow_listed_alarms_may_hand_back(data: dict) -> None:
    """Decision 7: an allow-list in the code. A stored "hand back" for any other alarm — low
    pressure, a failed write, an alarm this version does not know — gives information, whatever
    the hand-back's effect; it is not even kept. Always: an internal error, the lost boiler link,
    another controller, the monitor failing, heating off or on ignored from the start (answer O;
    decision 4 of 0.2.3), a relay's "off" no longer taken in the session (decision 6 of 0.2.3)."""
    from custom_components.vtherm_smart_boiler.control_config import (
        ALWAYS_HAND_BACK_ALARMS,
        OPTIONAL_HAND_BACK_ALARMS,
    )

    assert set(ALWAYS) | set(OFF_NOT_TAKEN) == ALWAYS_HAND_BACK_ALARMS
    assert OPTIONAL_HAND_BACK_ALARMS == {"write_ignored"}
    stored = dict.fromkeys(NOT_ALLOWED, "hand_back")
    options = parse_control(data | {"alarm_reactions": stored}, RADIATORS, None)
    for alarm in NOT_ALLOWED:
        assert options.reaction(alarm) is AlarmReaction.INFO, alarm
    for alarm in (*ALWAYS, *OFF_NOT_TAKEN):
        assert options.reaction(alarm) is AlarmReaction.HAND_BACK, alarm
    assert options.alarm_reactions == {}
    assert options.reaction("pressure_low") is AlarmReaction.INFO  # the default too


def test_a_relay_never_hands_back_for_its_link() -> None:
    """X8: a relay out of reach informs ("relay unreachable"); the lost boiler link hands back
    only on the setpoint paths."""
    options = parse_control(RELAY | {"alarm_reactions": {"boiler_link_lost": "info"}}, ON_OFF, None)
    assert options.reaction("boiler_link_lost") is AlarmReaction.INFO
    assert options.reaction("relay_unreachable") is AlarmReaction.INFO
    for alarm in ("control_error", "outside_change", "monitor_failed", *OFF_NOT_TAKEN):
        assert options.reaction(alarm) is AlarmReaction.HAND_BACK, alarm


def test_own_control_resumes_is_its_own_effect() -> None:
    """Y1 rule 2: a hand-back value declared "own control", or answer F's tick on the entity
    path — the boiler's own control resumes. A gateway with an OpenTherm thermostat stays
    "thermostat takes over", a tick stored there ignored (answer M); a relay goes by its rest
    state; an undeclared virtual topology is "device decides"; stand-alone, heating stops."""
    from custom_components.vtherm_smart_boiler.control_config import (
        HandBackEffect,
        hand_back_effect,
    )

    for data, effect in (
        (ENTITY, HandBackEffect.OWN_CONTROL_RESUMES),  # a value declared "own control"
        (TICKED, HandBackEffect.OWN_CONTROL_RESUMES),  # answer F's tick
        (OTGW | WITH_THERMOSTAT, HandBackEffect.THERMOSTAT_TAKES_OVER),
        (
            OTGW | WITH_THERMOSTAT | {"own_room_controller": True},
            HandBackEffect.THERMOSTAT_TAKES_OVER,
        ),
        (
            ENTITY | {"hand_back": "timeout", "write_type": "expiring"},
            HandBackEffect.DEVICE_DECIDES,
        ),
        (OTGW, HandBackEffect.HEATING_STOPS),
        (ENTITY | {"hand_back_value_effect": "heating_stops"}, HandBackEffect.HEATING_STOPS),
    ):
        assert hand_back_effect(parse_control(data, RADIATORS, None)) is effect, data
    for rest, effect in (
        ("off", HandBackEffect.RELAY_RESTS_OFF),
        ("on", HandBackEffect.RELAY_RESTS_ON),
    ):
        for tick in (False, True):
            data = RELAY | {"relay_rest_state": rest, "own_room_controller": tick}
            assert hand_back_effect(parse_control(data, ON_OFF, None)) is effect


@pytest.mark.parametrize(
    ("data", "installation", "reaction"),
    [
        (OTGW, RADIATORS, AlarmReaction.INFO),  # stand-alone: heating would stop
        (OTGW | WITH_THERMOSTAT, RADIATORS, AlarmReaction.HAND_BACK),
        (
            OTGW | {"topology": "gateway_with_thermostat", "thermostat_kind": "on_off"},
            RADIATORS,
            AlarmReaction.INFO,  # no OpenTherm thermostat declared (control is blocked too)
        ),
        (ENTITY, RADIATORS, AlarmReaction.HAND_BACK),  # a value declared "own control"
        (TICKED, RADIATORS, AlarmReaction.HAND_BACK),  # answer F's tick
        (
            ENTITY | {"hand_back": "timeout", "write_type": "expiring"},
            RADIATORS,
            AlarmReaction.INFO,
        ),
        (ENTITY | {"hand_back_value_effect": "heating_stops"}, RADIATORS, AlarmReaction.INFO),
        (RELAY, ON_OFF, AlarmReaction.INFO),
        (RELAY | {"relay_rest_state": "on"}, ON_OFF, AlarmReaction.INFO),
        (
            RELAY | {"relay_rest_state": "on", "own_room_controller": True},
            ON_OFF,
            AlarmReaction.INFO,
        ),
    ],
)
def test_write_ignored_may_hand_back_only_where_a_thermostat_or_own_control_takes_over(
    data: dict, installation: Installation, reaction: AlarmReaction
) -> None:
    """Decision 7's one optional reaction: a write the boiler ignores hands back only where
    the user chose it and a thermostat or the boiler's own control takes over; stand-alone, with
    an undeclared effect and on the relay path — either rest state — it informs, whatever is
    stored. Without a stored choice it informs everywhere."""
    from custom_components.vtherm_smart_boiler.control_config import write_ignored_offered

    stored = data | {"alarm_reactions": {"write_ignored": "hand_back"}}
    options = parse_control(stored, installation, None)
    assert options.reaction("write_ignored") is reaction
    assert write_ignored_offered(stored) is (reaction is AlarmReaction.HAND_BACK)
    assert parse_control(data, installation, None).reaction("write_ignored") is AlarmReaction.INFO


@pytest.mark.parametrize("cause", ["heating_off_ignored", "heating_on_ignored"])
@pytest.mark.parametrize("data", [OTGW, OTGW | WITH_THERMOSTAT, ENTITY, TICKED, RELAY])
def test_heating_off_ignored_from_the_start_always_hands_back(data: dict, cause: str) -> None:
    """Answer O: the heating switch's "off" ignored from the start hands back and latches
    whatever is stored — "information" included — and whatever the effect, stand-alone
    included; so does its "on" (decision 4 of 0.2.3, SB-03). Negative: any other ignored write
    is the optional rule above — stand-alone it informs."""
    installation = ON_OFF if data is RELAY else RADIATORS
    stored = data | {"alarm_reactions": {cause: "info", "write_ignored": "hand_back"}}
    options = parse_control(stored, installation, None)
    assert options.reaction(cause) is AlarmReaction.HAND_BACK
    assert cause not in options.alarm_reactions
    if data is OTGW:
        assert options.reaction("write_ignored") is AlarmReaction.INFO


def test_the_offered_reaction_is_read_from_raw_options() -> None:
    """The form's question: offered where the hand-back returns the boiler to a thermostat or
    its own control; never for a section it cannot read."""
    from custom_components.vtherm_smart_boiler.control_config import write_ignored_offered

    assert write_ignored_offered(OTGW | WITH_THERMOSTAT)
    assert not write_ignored_offered(OTGW)
    assert not write_ignored_offered({})
    assert not write_ignored_offered({"write_path": "no such path"})
    assert not write_ignored_offered(ENTITY | {"hand_back_value_effect": "no such effect"})


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
        assert config_blockers(options, RADIATORS) == ["no_heating_switch"]  # decision 11


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
    # Y1: a value declared "own control" is its own effect; still no working thermostat
    # without the tick (answer F).
    expected = (
        HandBackEffect.OWN_CONTROL_RESUMES
        if data.get("hand_back") == "value"
        else HandBackEffect.DEVICE_DECIDES
    )
    assert hand_back_effect(options) is expected
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
        (OTGW | WITH_THERMOSTAT, "thermostat_takes_over", True),
        (OTGW, "heating_stops", False),  # stand-alone
        (OTGW | WITH_THERMOSTAT | {"write_path": "otgw_mqtt"}, "thermostat_takes_over", True),
        (TICKED | WITH_THERMOSTAT, "thermostat_takes_over", True),
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
    unset = parse_control(OTGW | {"activation_delay_s": None}, RADIATORS, None)
    assert unset.loop.control.activation_delay_s == 0.0  # PB-95: the default, not just parsed
    for bad in (-10, 700):
        with pytest.raises(ValueError, match="activation_delay_s"):
            parse_control(OTGW | {"activation_delay_s": bad}, RADIATORS, None)


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"hard_min": ""}, "hard_min"),  # emptied by hand: no value to run on
        ({"hard_max": True}, "hard_max"),
        ({"curve": ["design_flow", 55]}, "curve"),
        ({"curve": CURVE | {"exponent": "inf"}}, "exponent"),
        ({"alarm_reactions": ["write_ignored"]}, "alarm_reactions"),
        ({"learning_pauses": "no"}, "learning_pauses"),
        ({"hand_back_value": "nan"}, "hand_back_value"),
        ({"count_threshold": float("inf")}, "count_threshold"),
        ({"off_setpoint": -1}, "off_setpoint"),
    ],
)
def test_stored_control_values_the_form_would_not_take_are_refused(changes: dict, key: str) -> None:
    """PB-06, PB-24: a control value not finite, outside the form's bounds, emptied, a flag
    that is not a yes or no, or a part of another shape raises ``ValueError`` naming it."""
    with pytest.raises(ValueError, match=key):
        parse_control(OTGW | changes, RADIATORS, None)


def test_stored_control_values_left_out_take_their_defaults() -> None:
    """The negative of PB-24: values not stored (``None``) take their cautious defaults."""
    stored = dict.fromkeys(("hard_min", "frost_limit", "hand_back_value", "curve"))
    control = parse_control(OTGW | stored | {"curve": CURVE}, RADIATORS, None).loop.control
    assert (control.limits.hard_min, control.frost.room_limit) == (20.0, 5.0)


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


# --- X5: configuration refused among the blockers (hand-edited options) --------------------------

SWITCHES = ENTITY | {
    "ch_entity": "switch.ch",
    "ch_write_type": "held",
    "hand_back": "switch",
    "hand_back_entity_write_type": "held",
}


@pytest.mark.parametrize(
    ("data", "blocked"),
    [
        (SWITCHES | {"hand_back_entity": "switch.ch"}, True),  # T-38: heating and external
        (ENTITY | {"hand_back": "switch", "hand_back_entity": "number.boiler_flow"}, True),
        (ENTITY | {"ch_entity": "number.boiler_flow", "ch_write_type": "held"}, True),
        (SWITCHES | {"hand_back_entity": "switch.external"}, False),
        (SWITCHES | {"hand_back_entity": "switch.ch", "ch_entity": ""}, False),  # left empty
        (SWITCHES | {"hand_back_entity": "switch.ch", "ch_entity": None}, False),
        (SWITCHES | {"hand_back_entity": ""}, False),  # missing: "no_hand_back", not a duplicate
        # A switch stored for another method is not used: no second role.
        (SWITCHES | {"hand_back_entity": "switch.ch", "hand_back": "value"}, False),
    ],
)
def test_a_hand_back_switch_that_is_the_heating_switch_blocks(data: dict, blocked: bool) -> None:
    """X5.1 (P-03, T-38): the heating switch, the external-control switch and the setpoint
    entity are pairwise different — one entity in two roles would be switched on and off by
    every hand-back for ever. Hand-edited options get the blocker; a role left empty or not in
    use is no duplicate."""
    from custom_components.vtherm_smart_boiler.control_config import one_entity_in_two_roles

    options = parse_control(data, RADIATORS, None)
    blockers = config_blockers(options, RADIATORS)
    assert ("hand_back_switch_is_heating_switch" in blockers) is blocked
    assert one_entity_in_two_roles(options) is blocked


@pytest.mark.parametrize(
    ("path", "topology", "blocked"),
    [
        ("opentherm_gw", "virtual", True),
        ("otgw_mqtt", "virtual", True),
        ("opentherm_gw", "gateway_standalone", False),
        ("otgw_mqtt", "gateway_with_thermostat", False),
        ("entity", "virtual", False),
        ("entity", "gateway_standalone", False),
        ("entity", "gateway_with_thermostat", False),
        ("opentherm_gw", "monitor_mode", False),  # "topology_no_control" says it
        ("opentherm_gw", "", False),  # "no_topology" says it
    ],
)
def test_the_topology_must_suit_the_path(path: str, topology: str, blocked: bool) -> None:
    """X5.4 (P-44): the pairing the form checks is a blocker too, from one table."""
    from custom_components.vtherm_smart_boiler.control_config import PATH_TOPOLOGIES

    assert set(PATH_TOPOLOGIES) == set(WritePath)  # every path has its topologies
    data = (
        (ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "held"}) if path == "entity" else OTGW
    )
    options = parse_control(data | {"write_path": path, "topology": topology}, RADIATORS, None)
    assert ("topology_not_for_path" in config_blockers(options, RADIATORS)) is blocked


@pytest.mark.parametrize(
    ("changes", "blocked"),
    [
        ({}, True),  # no heating switch: "off" would be a low setpoint
        ({"ch_entity": ""}, True),
        ({"ch_entity": None}, True),
        ({"ch_entity": "switch.ch"}, True),  # its write type not declared: unknown
        ({"ch_entity": "switch.ch", "ch_write_type": "unknown"}, True),
        ({"ch_entity": "switch.ch", "ch_write_type": "persistent"}, True),
        ({"ch_entity": "switch.ch", "ch_write_type": "held"}, False),
        ({"ch_entity": "switch.ch", "ch_write_type": "expiring"}, False),
    ],
)
def test_control_without_a_heating_switch_is_blocked(changes: dict, blocked: bool) -> None:
    """Decision 11 (S-39): until the user lifts it at K4, control needs a heating switch the
    boiler does not store; without one, "off" would be a low setpoint, and whether that stops
    the boiler and its pump is not known — such installations get the monitor. The gateway paths
    always switch heating with CH; the block is lifted in one place."""
    from custom_components.vtherm_smart_boiler import control_config

    options = parse_control(ENTITY | changes, RADIATORS, None)
    assert ("no_heating_switch" in config_blockers(options, RADIATORS)) is blocked
    for path in ("opentherm_gw", "otgw_mqtt"):
        data = OTGW | {"write_path": path, "mqtt_top": "t", "mqtt_node": "n"}
        gateway = parse_control(data, RADIATORS, None)
        assert "no_heating_switch" not in config_blockers(gateway, RADIATORS)
    assert control_config.OFF_AS_LOW_SETPOINT_ALLOWED is False  # K4 decides


def test_the_heating_switch_block_is_lifted_in_one_place(monkeypatch: pytest.MonkeyPatch) -> None:
    from custom_components.vtherm_smart_boiler import control_config

    monkeypatch.setattr(control_config, "OFF_AS_LOW_SETPOINT_ALLOWED", True)
    assert config_blockers(parse_control(ENTITY, RADIATORS, None), RADIATORS) == []


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        (
            {"curve": {"design_outdoor": -15, "design_flow": 25, "room": 20.5}},
            "design_flow_too_low",
        ),
        ({"curve": {"design_outdoor": -15, "design_flow": 26, "room": 22}}, "design_flow_too_low"),
        ({"curve": {"design_outdoor": -15, "design_flow": 72}}, "design_flow_above_hard_max"),
        ({"curve": CURVE, "hard_max": 50}, "design_flow_above_hard_max"),
        (
            {"curve": {"design_outdoor": 10, "design_flow": 55, "room": 19.5}},
            "design_outdoor_too_warm",
        ),
        (
            {"curve": {"design_outdoor": 9, "design_flow": 55, "room": 18}},
            "design_outdoor_too_warm",
        ),
        ({"curve": CURVE | {"design_flow": 50}, "hard_min": 50}, "hard_min_not_below_design_flow"),
        (
            {"curve": {"design_outdoor": -15, "design_flow": 40}, "hard_min": 45},
            "hard_min_not_below_design_flow",
        ),
    ],
)
def test_curve_cross_field_blockers(changes: dict, blocker: str) -> None:
    """X5.8 (P-68; provisional, K4): the design flow at least 5 K above the curve's room and not
    above the highest water temperature (the curve would be cut off in frost), the design
    outdoor temperature at least 10 K below the room, the lowest water temperature below the
    design flow."""
    options = parse_control(OTGW | changes, RADIATORS, None)
    assert blocker in config_blockers(options, RADIATORS)


def test_the_curve_defaults_pass_the_cross_field_checks() -> None:
    """Negative: the defaults with a design flow of 55 °C pass every check; a curve without a
    design flow keeps today's "curve_not_entered" alone."""
    from custom_components.vtherm_smart_boiler.control_config import curve_problems

    checks = {
        "design_flow_too_low",
        "design_flow_above_hard_max",
        "design_outdoor_too_warm",
        "hard_min_not_below_design_flow",
    }
    assert config_blockers(parse_control(OTGW, RADIATORS, None), RADIATORS) == []
    edges = OTGW | {"curve": {"design_outdoor": 10, "design_flow": 25}, "hard_min": 24.5}
    assert not checks & set(config_blockers(parse_control(edges, RADIATORS, None), RADIATORS))
    unset = config_blockers(parse_control(OTGW | {"curve": {}}, RADIATORS, None), RADIATORS)
    assert unset == ["curve_not_entered"]
    assert curve_problems(None, -15.0, 20.0, 25.0, 70.0) == []  # nothing entered: nothing checked


def test_a_passive_fixed_circuit_floor_has_a_margin() -> None:
    """S-42 (provisional, K4): the boiler's water at least 5 K above a thermostatic mixing
    valve's temperature, so the valve can reach it. Negative: no fixed temperature stays the
    configuration error it is today."""
    from custom_components.vtherm_smart_boiler.config import ConfigError, EntryConfig
    from custom_components.vtherm_smart_boiler.control_config import FIXED_CIRCUIT_MARGIN_K

    assert FIXED_CIRCUIT_MARGIN_K == 5.0
    fixed = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", CircuitControl.PASSIVE_FIXED, 45.0),),
        (Zone("climate.a", "main"),),
    )
    assert parse_control(OTGW, fixed, None).loop.control.circuit_floor == 50.0
    assert parse_control(OTGW, RADIATORS, None).loop.control.circuit_floor is None
    missing = {
        "signals": {"flame": "binary_sensor.flame", "flow": "sensor.flow"},
        "circuits": [{"id": "main", "control": "passive_fixed"}],
    }
    with pytest.raises(ConfigError) as err:
        EntryConfig.from_options(missing)
    assert err.value.code == "fixed_temperature_missing"


def test_one_entity_for_two_signals_is_a_blocker() -> None:
    """X5.2: a signal dropped because its entity feeds an earlier one blocks control."""
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    options = parse_control(OTGW, RADIATORS, None)
    assert config_blockers(options, RADIATORS, {Signal.RETURN: Signal.FLOW}) == [
        "entity_for_two_signals"
    ]
    assert config_blockers(options, RADIATORS, {}) == []


def test_the_option_key_lists_are_one_each() -> None:
    """P-71: the writable-entity step's answers and what a hand-back goes through are listed
    once, in the control options — with what judges it (PB-09)."""
    from custom_components.vtherm_smart_boiler import config_flow
    from custom_components.vtherm_smart_boiler.control_config import HAND_BACK_KEYS, TARGET_KEYS

    assert set(HAND_BACK_KEYS) <= set(TARGET_KEYS)
    assert config_flow.fixed_keys is fixed_keys
    assert config_flow.TARGET_KEYS is TARGET_KEYS
    assert not hasattr(config_flow, "ENTITY_STEP_KEYS")


@pytest.mark.parametrize(
    ("data", "writes"),
    [
        ({"write_path": "opentherm_gw"}, True),
        ({"write_path": "otgw_mqtt"}, True),
        ({"write_path": "entity", "ch_entity": "switch.ch", "ch_write_type": "held"}, True),
        ({"write_path": "entity", "ch_entity": "switch.ch", "ch_write_type": "sometimes"}, False),
        ({"write_path": "entity", "ch_entity": "switch.ch", "ch_write_type": None}, False),
        ({"write_path": "entity", "ch_write_type": "held"}, False),
    ],
)
def test_heating_writes_are_read_from_the_stored_options(data: dict, writes: bool) -> None:
    """The form's reading of whether "off" is a low setpoint (P-25): a write type this version
    does not know counts as none."""
    from custom_components.vtherm_smart_boiler.control_config import heating_writes

    assert heating_writes(data) is writes


# --- X6: what is wired to the gateway's thermostat terminals (decision 1, S-01, answer K); the
# lowest water temperature (decision 2, S-02); the wall thermostat on a gateway -------------------

GATEWAY_TOPOLOGIES = ("gateway_with_thermostat", "gateway_standalone")
# Every write path that takes a gateway topology asks the question.
GATEWAY_PATHS = {
    "opentherm_gw": OTGW,
    "otgw_mqtt": OTGW | {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "otgw"},
    "entity": ENTITY | {"ch_entity": "switch.ch", "ch_write_type": "held"},
}
KIND_BLOCKERS = {
    "thermostat_on_off",
    "thermostat_kind_unknown",
    "thermostat_kind_dont_know",
    "thermostat_kind_contradicts_topology",
}


def _kind_blockers(data: dict) -> list[str]:
    options = parse_control(data, RADIATORS, None)
    return [b for b in config_blockers(options, RADIATORS) if b in KIND_BLOCKERS]


def _without_kind(data: dict) -> dict:
    return {key: value for key, value in data.items() if key != "thermostat_kind"}


@pytest.mark.parametrize("path", sorted(GATEWAY_PATHS))
@pytest.mark.parametrize("topology", GATEWAY_TOPOLOGIES)
@pytest.mark.parametrize(
    ("kind", "blocker"),
    [
        ("on_off", "thermostat_on_off"),
        ("unknown", "thermostat_kind_dont_know"),  # its own text (PB-73)
        ("missing", "thermostat_kind_unknown"),  # an entry from before 0.2.2 (answer K)
        (None, "thermostat_kind_unknown"),
        ("", "thermostat_kind_unknown"),
        ("a kind this version does not know", "thermostat_kind_unknown"),
        (7, "thermostat_kind_unknown"),
    ],
)
def test_the_thermostat_kind_decides_whether_a_gateway_may_be_controlled(
    path: str, topology: str, kind: object, blocker: str
) -> None:
    """Decision 1 (S-01; T-07's core part): an on/off contact on the gateway's thermostat
    terminals would be masked by the gateway's ``CH=0`` after a crash while "off", so control is
    blocked for it; "I don't know", a missing answer or one that cannot be read block too — the
    parse never raises for it. The monitor is not concerned."""
    data = GATEWAY_PATHS[path] | {"topology": topology}
    data = _without_kind(data) if kind == "missing" else data | {"thermostat_kind": kind}
    assert _kind_blockers(data) == [blocker]


@pytest.mark.parametrize("path", sorted(GATEWAY_PATHS))
@pytest.mark.parametrize(
    ("topology", "kind"),
    [("gateway_with_thermostat", "opentherm"), ("gateway_standalone", "none")],
)
def test_a_kind_that_fits_the_topology_allows_control(path: str, topology: str, kind: str) -> None:
    """Negative: an OpenTherm thermostat with a thermostat, nothing stand-alone — no blocker of
    the kind, and none at all on the gateway paths."""
    data = GATEWAY_PATHS[path] | {"topology": topology, "thermostat_kind": kind}
    assert _kind_blockers(data) == []
    if path != "entity":
        assert config_blockers(parse_control(data, RADIATORS, None), RADIATORS) == []


@pytest.mark.parametrize("path", sorted(GATEWAY_PATHS))
@pytest.mark.parametrize(
    ("topology", "kind"),
    [("gateway_standalone", "opentherm"), ("gateway_with_thermostat", "none")],
)
def test_a_kind_that_contradicts_the_topology_blocks(path: str, topology: str, kind: str) -> None:
    """An OpenTherm thermostat with stand-alone, nothing with a thermostat: refused in the form,
    and a blocker for options that reach the plugin without it."""
    data = GATEWAY_PATHS[path] | {"topology": topology, "thermostat_kind": kind}
    assert _kind_blockers(data) == ["thermostat_kind_contradicts_topology"]


@pytest.mark.parametrize("kind", [None, "on_off", "unknown", "opentherm", "none", "garbage"])
def test_no_kind_is_needed_without_a_gateway_topology(kind: str | None) -> None:
    """The virtual topology (a controller on Home Assistant's side) has no thermostat terminals
    to ask about: no blocker of the kind, whatever a hand edit stored; nor with the monitor mode
    or no topology, which have their own blockers."""
    data = _without_kind(ENTITY) | {"ch_entity": "switch.ch", "ch_write_type": "held"}
    if kind is not None:
        data["thermostat_kind"] = kind
    assert _kind_blockers(data) == []
    assert config_blockers(parse_control(data, RADIATORS, None), RADIATORS) == []
    for topology, own in (("monitor_mode", "topology_no_control"), ("", "no_topology")):
        blockers = config_blockers(
            parse_control(OTGW | {"topology": topology, "thermostat_kind": kind}, RADIATORS, None),
            RADIATORS,
        )
        assert own in blockers
        assert not KIND_BLOCKERS & set(blockers)


def test_the_kind_is_read_and_a_missing_answer_is_told() -> None:
    """The kind as stored; missing or unreadable, no answer (``None``) — which, on a gateway
    topology, raises the repair issue asking for it (answer K). An explicit "I don't know" is an
    answer: blocked, no issue."""
    from custom_components.vtherm_smart_boiler.control_config import (
        ThermostatKind,
        thermostat_kind_missing,
    )

    assert parse_control(OTGW, RADIATORS, None).thermostat_kind is ThermostatKind.NONE
    for stored in (None, "", "garbage", 3):
        options = parse_control(OTGW | {"thermostat_kind": stored}, RADIATORS, None)
        assert options.thermostat_kind is None
        assert thermostat_kind_missing(options)
    options = parse_control(_without_kind(OTGW), RADIATORS, None)
    assert thermostat_kind_missing(options)
    unknown = parse_control(OTGW | {"thermostat_kind": "unknown"}, RADIATORS, None)
    assert unknown.thermostat_kind is ThermostatKind.UNKNOWN
    assert not thermostat_kind_missing(unknown)
    assert not thermostat_kind_missing(parse_control(OTGW, RADIATORS, None))
    virtual = parse_control(_without_kind(ENTITY), RADIATORS, None)
    assert not thermostat_kind_missing(virtual)
    assert not thermostat_kind_missing(parse_control({}, RADIATORS, None))  # no control


@pytest.mark.parametrize(
    ("kind", "working"),
    [("opentherm", True), ("on_off", False), ("unknown", False), (None, False)],
)
def test_a_working_thermostat_on_a_gateway_is_a_declared_opentherm_one(
    kind: str | None, working: bool
) -> None:
    """Decision 3 (answers F, M): with every zone unknown the boiler goes to a working
    thermostat — on a gateway only an OpenTherm thermostat declared on its terminals."""
    from custom_components.vtherm_smart_boiler.control_config import working_thermostat

    data = OTGW | {"topology": "gateway_with_thermostat", "thermostat_kind": kind}
    options = parse_control(data, RADIATORS, None)
    assert working_thermostat(options) is working
    assert options.loop.control.working_thermostat is working


def test_the_lowest_water_temperature_defaults_to_20() -> None:
    """Decision 2 (provisional, K4): one setting, the lowest water temperature (key ``hard_min``,
    10–50 °C), default 20 °C; a value stored is kept."""
    from custom_components.vtherm_smart_boiler.control_config import CONTROL_DEFAULTS

    assert CONTROL_DEFAULTS["hard_min"] == 20.0
    parsed = parse_control(_without_kind(OTGW) | {"thermostat_kind": "none"}, RADIATORS, None)
    assert parsed.loop.control.limits.hard_min == 20.0
    for stored, read in ((None, 20.0), (25, 25.0), (30.5, 30.5)):
        options = parse_control(OTGW | {"hard_min": stored}, RADIATORS, None)
        assert options.loop.control.limits.hard_min == read


@pytest.mark.parametrize(
    ("data", "applies"),
    [
        (OTGW | WITH_THERMOSTAT, True),
        (GATEWAY_PATHS["entity"] | WITH_THERMOSTAT, True),
        (OTGW | {"topology": "gateway_with_thermostat", "thermostat_kind": "on_off"}, False),
        (OTGW | {"topology": "gateway_with_thermostat", "thermostat_kind": None}, False),
        (OTGW, False),  # stand-alone
        (ENTITY, False),  # virtual
        ({}, False),
    ],
)
def test_the_wall_thermostat_is_shown_only_for_an_opentherm_thermostat_on_a_gateway(
    data: dict, applies: bool
) -> None:
    from custom_components.vtherm_smart_boiler.control_config import wall_thermostat_applies

    assert wall_thermostat_applies(parse_control(data, RADIATORS, None)) is applies


# --- X8: on/off control through a relay (class 3) ---------------------------------------------


def test_relay_control_needs_an_on_off_boiler() -> None:
    """R1: on/off + relay + an entity — none of the path's blockers; a flow-setpoint boiler with
    the relay, or an on/off boiler with a setpoint path — ``path_not_for_boiler_class``; curve
    only and read only — ``boiler_class_no_control``."""
    assert config_blockers(parse_control(RELAY, ON_OFF, None), ON_OFF) == []
    flow = parse_control(RELAY, RADIATORS, None)
    assert config_blockers(flow, RADIATORS) == ["path_not_for_boiler_class"]
    on_off_entity = parse_control(ENTITY, ON_OFF, None)
    assert "path_not_for_boiler_class" in config_blockers(on_off_entity, ON_OFF)
    for boiler_class in (BoilerClass.CURVE_ONLY, BoilerClass.READ_ONLY):
        installation = Installation(
            Boiler(boiler_class), (Circuit("main"),), (Zone("climate.a", "main"),)
        )
        blockers = config_blockers(parse_control(RELAY, installation, None), installation)
        assert "boiler_class_no_control" in blockers
        assert "path_not_for_boiler_class" not in blockers


@pytest.mark.parametrize(
    ("entity", "blocker"),
    [
        (None, "no_relay_entity"),
        ("", "no_relay_entity"),
        ("input_boolean.x", "relay_domain_not_supported"),
        ("light.x", "relay_domain_not_supported"),
        ("switch.x", None),
        ("climate.x", None),
    ],
)
def test_a_relay_is_a_switch_or_a_climate(entity: str | None, blocker: str | None) -> None:
    """R2: a switch, or a boiler thermostat entity; never a helper, which confirms nothing."""
    data = {**RELAY, "relay_entity": entity}
    blockers = config_blockers(parse_control(data, ON_OFF, None), ON_OFF)
    assert blockers == ([] if blocker is None else [blocker])


@pytest.mark.parametrize(
    ("tick", "blocked"), [(None, True), (False, True), ("yes", True), (True, False)]
)
def test_relay_control_needs_the_separate_contact_tick(tick: object, blocked: bool) -> None:
    """Answer G: without the tick "this is a separate relay contact, not a setting stored in the
    boiler's memory", control does not start; only a clear "yes" counts."""
    data = {**RELAY, "relay_is_separate_contact": tick}
    options = parse_control(data, ON_OFF, None)
    assert options.relay.separate_contact is (not blocked)
    blockers = config_blockers(options, ON_OFF)
    assert ("relay_contact_not_confirmed" in blockers) is blocked


def test_water_temperature_control_needs_flame_and_flow() -> None:
    """R4: flame and flow are optional for the entry; control of the water temperature needs
    both mapped — the relay path needs neither."""
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    water = parse_control(OTGW, RADIATORS, None)
    both = frozenset({Signal.FLAME, Signal.FLOW})
    assert config_blockers(water, RADIATORS, signals=both) == []
    assert config_blockers(water, RADIATORS, signals=()) == ["no_flame_signal", "no_flow_signal"]
    assert config_blockers(water, RADIATORS, signals={Signal.FLAME}) == ["no_flow_signal"]
    assert config_blockers(water, RADIATORS, signals={Signal.FLOW}) == ["no_flame_signal"]
    for data in (ENTITY, OTGW | {"write_path": "otgw_mqtt", "mqtt_top": "t", "mqtt_node": "n"}):
        found = config_blockers(parse_control(data, RADIATORS, None), RADIATORS, signals=())
        assert {"no_flame_signal", "no_flow_signal"} <= set(found)
    relay = parse_control(RELAY, ON_OFF, None)
    assert config_blockers(relay, ON_OFF, signals=()) == []


def test_relay_settings_have_cautious_defaults() -> None:
    """R3: unanswered, each setting takes its cautious reading — its state report "I don't
    know" (blind repeats), its state after a power cut "I don't know", a timer "I don't know",
    the repeat interval 300 s, the rest state "off", no power proof, the tick not given."""
    from custom_components.vtherm_smart_boiler.control_config import RelayOptions
    from custom_components.vtherm_smart_boiler.core.relay import (
        RelayPowerOn,
        RelayReports,
        RelayRest,
        RelayTimer,
    )

    options = parse_control({"write_path": "relay", "relay_entity": "switch.r"}, ON_OFF, None)
    relay = options.relay
    assert relay == RelayOptions(entity="switch.r")
    assert relay.reports is RelayReports.UNKNOWN
    assert relay.power_on is RelayPowerOn.UNKNOWN
    assert relay.timer is RelayTimer.UNKNOWN
    assert relay.timer_min is None
    assert relay.repeat_s == 300.0
    assert relay.rest is RelayRest.OFF
    assert relay.heats_above_w is None
    assert not relay.separate_contact
    assert not options.own_room_controller
    loop = options.loop
    assert loop.relay is not None
    assert not loop.relay.reports_state  # blind repeats
    assert loop.relay.renew_s == 300.0  # "it may have a timer": "on" repeated
    control = loop.control
    assert control.on_off
    assert control.stale_hand_back_s is None  # the link is the relay (R6)
    assert not control.comfort_correction
    assert not options.learning.pause_on_water_swing  # R13: no water swing on a relay
    assert not options.return_after_outside_change


@pytest.mark.parametrize("length", [None, "", 0, 121, "soon"])
def test_a_declared_timer_without_its_length_is_read_as_unknown(length: object) -> None:
    from custom_components.vtherm_smart_boiler.core.relay import RelayTimer

    data = {**RELAY, "relay_off_timer": "minutes", "relay_off_timer_min": length}
    options = parse_control(data, ON_OFF, None)
    assert options.relay.timer is RelayTimer.UNKNOWN
    assert options.loop.relay is not None
    assert options.loop.relay.renew_s == 300.0
    declared = parse_control({**data, "relay_off_timer_min": 10}, ON_OFF, None)
    assert declared.relay.timer is RelayTimer.MINUTES
    assert declared.loop.relay is not None
    assert declared.loop.relay.timer_s == 600.0


def _timer_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        record.getMessage()
        for record in caplog.records
        if record.levelname == "WARNING" and "switch-off timer" in record.getMessage()
    ]


@pytest.mark.parametrize("length", [5, 9, 9.9, "5", 1, 0])
def test_a_declared_timer_shorter_than_ten_minutes_is_read_as_unknown_and_logged(
    length: object, caplog: pytest.LogCaptureFixture
) -> None:
    """K4.2 (decided by the user 2026-10-03): the shortest timer the plugin takes for the relay's
    own is 10 min. A declared length below it — stored by an earlier build, or edited by hand —
    is read as "I don't know" (the cautious reading: "on" repeated, its switch-offs counted
    toward answer N), with a warning in the log naming it. 10 min itself is taken, silently."""
    from custom_components.vtherm_smart_boiler.core.relay import RelayTimer

    data = {**RELAY, "relay_off_timer": "minutes", "relay_off_timer_min": length}
    options = parse_control(data, ON_OFF, None)
    assert options.relay.timer is RelayTimer.UNKNOWN
    assert options.relay.timer_min is None
    assert options.loop.relay is not None
    assert options.loop.relay.timer is RelayTimer.UNKNOWN
    assert options.loop.relay.timer_s is None
    warnings = _timer_warnings(caplog)
    assert len(warnings) == 1
    assert repr(length) in warnings[0]
    assert "10" in warnings[0]
    caplog.clear()
    declared = parse_control({**data, "relay_off_timer_min": 10}, ON_OFF, None)
    assert declared.relay.timer is RelayTimer.MINUTES
    assert declared.loop.relay is not None
    assert declared.loop.relay.timer_s == 600.0
    assert _timer_warnings(caplog) == []


@pytest.mark.parametrize("timer", ["minutes", "unknown", "none"])
@pytest.mark.parametrize("length", ["missing", None, ""])
def test_no_timer_length_gives_no_short_timer_warning(
    timer: str, length: object, caplog: pytest.LogCaptureFixture
) -> None:
    """Negatives (K4.2): with no length stored — missing, ``None`` or empty — nothing is below
    10 min, so nothing is logged; a declared timer without its length is read as "I don't know"
    as before, and "I don't know" and "none" stay as they are."""
    from custom_components.vtherm_smart_boiler.core.relay import RelayTimer

    data = {**RELAY, "relay_off_timer": timer}
    if length != "missing":
        data["relay_off_timer_min"] = length
    options = parse_control(data, ON_OFF, None)
    expected = RelayTimer.NONE if timer == "none" else RelayTimer.UNKNOWN
    assert options.relay.timer is expected
    assert options.relay.timer_min is None
    assert _timer_warnings(caplog) == []


@pytest.mark.parametrize(
    ("raw", "read"),
    [
        (None, 300.0),
        ("", 300.0),
        (10, 10.0),
        (60, 60.0),
        (300, 300.0),
        (5, 300.0),
        (301, 300.0),
        ("x", 300.0),
    ],
)
def test_the_repeat_interval_stays_within_10_to_300_s(raw: object, read: float) -> None:
    """A hand-edited value outside 10–300 s is read as 300 s."""
    options = parse_control({**RELAY, "relay_repeat_s": raw}, ON_OFF, None)
    assert options.relay.repeat_s == read
    assert options.loop.relay is not None
    assert options.loop.relay.repeat_s == read


@pytest.mark.parametrize(
    ("rest", "effect", "heating_on", "frost_by"),
    [
        (None, "relay_rests_off", False, "boiler"),
        ("off", "relay_rests_off", False, "boiler"),
        ("on", "relay_rests_on", True, "device"),
    ],
)
def test_the_rest_state_decides_the_hand_back_effect(
    rest: str | None, effect: str, heating_on: bool, frost_by: str
) -> None:
    """R9: on the relay path the hand-back's effect is the rest state — with the tick too, which
    is read by itself there (answer M)."""
    from custom_components.vtherm_smart_boiler.control_config import (
        frost_protection_by,
        hand_back_effect,
        hand_back_heating_on,
    )

    for tick in (False, True):
        data = {**RELAY, "relay_rest_state": rest, "own_room_controller": tick}
        options = parse_control(data, ON_OFF, None)
        shown = hand_back_effect(options)
        assert shown is not None
        assert shown.value == effect
        assert hand_back_heating_on(options) is heating_on
        by = frost_protection_by(options, controlling=False)
        assert by is not None
        assert by.value == frost_by


def test_the_own_room_controller_tick_counts_on_the_relay_path_with_rest_state_on() -> None:
    """Answers F, M wired: the tick is offered on the relay path, and counts as a working
    thermostat only with the rest state "on"."""
    from custom_components.vtherm_smart_boiler.control_config import (
        own_room_controller_offered,
        working_thermostat,
    )

    assert own_room_controller_offered(WritePath.RELAY, None)
    for tick, rest, working in (
        (True, "on", True),
        (True, "off", False),
        (False, "on", False),
        (False, "off", False),
    ):
        data = {**RELAY, "own_room_controller": tick, "relay_rest_state": rest}
        options = parse_control(data, ON_OFF, None)
        assert options.own_room_controller is tick
        assert working_thermostat(options) is working
        assert options.loop.control.working_thermostat is working


def test_the_circuit_rules_do_not_apply_to_a_relay() -> None:
    """R1: the relay sets no water temperature — the circuit, curve, topology and read-back
    blockers do not apply; the demand thresholds do."""
    two = Installation(
        Boiler(BoilerClass.ON_OFF),
        (Circuit("a"), Circuit("b", CircuitControl.SEPARATE)),
        (Zone("climate.a", "a", EmitterType.UNDERFLOOR),),
    )
    assert config_blockers(parse_control(RELAY, two, None), two) == []
    many = parse_control({**RELAY, "count_threshold": 3}, ON_OFF, None)
    assert config_blockers(many, ON_OFF) == ["count_threshold_above_zones"]
    no_zones = Installation(Boiler(BoilerClass.ON_OFF), (Circuit("main"),))
    assert config_blockers(parse_control(RELAY, no_zones, None), no_zones) == ["no_zones"]


def test_the_relay_in_another_role_is_a_blocker() -> None:
    """R2: the relay is none of the entities the options use in another role."""
    data = {**RELAY, "restart_entity": "switch.boiler_relay"}
    assert config_blockers(parse_control(data, ON_OFF, None), ON_OFF) == ["relay_in_another_role"]
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    options = parse_control(RELAY, ON_OFF, None)
    mapped = {Signal.PUMP_RUNNING: "switch.boiler_relay"}
    assert config_blockers(options, ON_OFF, signals=mapped) == ["relay_in_another_role"]


def test_no_return_by_itself_and_no_hand_back_for_an_ignored_write_on_the_relay_path() -> None:
    """Decision 6: the return by itself is not offered for relays; decision 7: the reaction to an
    ignored write is never offered on the relay path — stored ones are neutralised."""
    data = {
        **RELAY,
        "return_after_outside_change": True,
        "alarm_reactions": {"write_ignored": "hand_back", "pressure_low": "hand_back"},
    }
    options = parse_control(data, ON_OFF, None)
    assert not options.return_after_outside_change
    assert options.reaction("write_ignored") is AlarmReaction.INFO
    assert options.reaction("pressure_low") is AlarmReaction.INFO  # Y1: not on the allow-list


def test_the_relay_is_named_among_the_entities_control_uses() -> None:
    from custom_components.vtherm_smart_boiler.control_config import (
        ENTITY_KEYS,
        HAND_BACK_KEYS,
        TARGET_KEYS,
        rename_in_control,
    )

    options = parse_control(RELAY, ON_OFF, None)
    assert "switch.boiler_relay" in options.entities
    assert "relay_entity" in ENTITY_KEYS
    assert {"relay_entity", "relay_rest_state"} <= set(HAND_BACK_KEYS)
    assert {
        "relay_entity",
        "relay_reports_state",
        "relay_power_on_state",
        "relay_off_timer",
        "relay_off_timer_min",
        "relay_repeat_s",
        "relay_rest_state",
        "boiler_heats_above_w",
        "relay_is_separate_contact",
        "hand_back_timeout_min",  # dropped with the write path, as every hand-back answer
    } <= set(TARGET_KEYS)
    renamed = rename_in_control(RELAY, "switch.boiler_relay", "switch.new")
    assert renamed["relay_entity"] == "switch.new"


@pytest.mark.parametrize(
    ("raw", "read"),
    [(None, None), ("", None), (9, None), (10, 10.0), (10000, 10000.0), (10001, None)],
)
def test_the_power_proof_threshold_is_read_within_its_range(
    raw: object, read: float | None
) -> None:
    options = parse_control({**RELAY, "boiler_heats_above_w": raw}, ON_OFF, None)
    assert options.relay.heats_above_w == read


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("relay_reports_state", "maybe"),
        ("relay_power_on_state", "sometimes"),
        ("relay_off_timer", "weekly"),
        ("relay_rest_state", "half"),
    ],
)
def test_a_relay_value_this_version_does_not_know_is_refused(key: str, value: str) -> None:
    """P-70: an option value this version does not know is not passed off as a known one."""
    with pytest.raises(ValueError, match="is not a valid"):
        parse_control({**RELAY, key: value}, ON_OFF, None)


def test_a_relay_not_picked_has_no_other_role() -> None:
    from custom_components.vtherm_smart_boiler.control_config import relay_in_another_role

    options = parse_control({"write_path": "relay"}, ON_OFF, None)
    assert not relay_in_another_role(options, {})


# --- P-115: the precedence of the configuration blockers, as a table ---------------------------
# Several lacks at once, and which of them the list names, in its order: the table the split of
# ``config_blockers`` must keep green.

_NO_ZONES = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))
_READ_ONLY = Installation(Boiler(BoilerClass.READ_ONLY), ())
_TWO_CIRCUITS = Installation(
    Boiler(BoilerClass.FLOW_SETPOINT),
    (Circuit("a"), Circuit("b", CircuitControl.SEPARATE)),
    (Zone("climate.a", "a"),),
)
_FLOOR = Installation(
    Boiler(BoilerClass.FLOW_SETPOINT),
    (Circuit("main"),),
    (Zone("climate.a", "main", EmitterType.UNDERFLOOR),),
)
_ON_OFF_NO_ZONES = Installation(Boiler(BoilerClass.ON_OFF), (Circuit("main"),))
_HEATING_SWITCH = {"ch_entity": "switch.heat", "ch_write_type": "held"}
# PB-26: a radiator circuit capped at 40 °C.
_CAPPED = Installation(
    Boiler(BoilerClass.FLOW_SETPOINT),
    (Circuit("main", max_flow=40.0),),
    (Zone("climate.a", "main"),),
)
_ALL_SIGNALS = None  # not given: flame and flow are not checked
_NO_SIGNALS: tuple = ()

BLOCKER_PRECEDENCE = [
    # (what the row shows, control section, installation, shared signals, signals, blockers)
    ("not configured beats every other lack", {}, _READ_ONLY, None, _NO_SIGNALS, ["no_write_path"]),
    (
        "a monitor-only class, the rest judged as usual",
        OTGW,
        _READ_ONLY,
        None,
        _ALL_SIGNALS,
        ["boiler_class_no_control", "one_direct_circuit_only", "no_zones"],
    ),
    (
        "the relay on a flow-setpoint boiler",
        RELAY,
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["path_not_for_boiler_class"],
    ),
    (
        "a gateway on an on/off boiler",
        OTGW,
        ON_OFF,
        None,
        _ALL_SIGNALS,
        ["path_not_for_boiler_class"],
    ),
    (
        "the relay: its own lacks and the zones', nothing about water",
        {"write_path": "relay"},
        _ON_OFF_NO_ZONES,
        {"flow": "flame"},
        _NO_SIGNALS,
        ["entity_for_two_signals", "no_relay_entity", "relay_contact_not_confirmed", "no_zones"],
    ),
    (
        "the entity path with everything missing, in the list's order",
        {"write_path": "entity"},
        _NO_ZONES,
        None,
        _NO_SIGNALS,
        [
            "no_flame_signal",
            "no_flow_signal",
            "no_setpoint_entity",
            "write_type_not_supported",
            "no_heating_switch",
            "no_hand_back",
            "no_confirmed_setpoint",
            "no_topology",
            "curve_not_entered",
            "no_zones",
        ],
    ),
    (
        "no hand-back before anything about its kind",
        ENTITY | {"hand_back": None, "write_type": "held"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["no_heating_switch", "no_hand_back"],
    ),
    (
        "a timeout hand-back with held writes",
        ENTITY | {"hand_back": "timeout", "write_type": "held"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["no_heating_switch", "timeout_needs_expiring_writes"],
    ),
    (
        "a switch hand-back the boiler may store",
        ENTITY | {"hand_back": "switch", "hand_back_entity": "switch.ext"} | _HEATING_SWITCH,
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["hand_back_switch_not_writable"],
    ),
    (
        "one entity as the hand-back and the heating switch",
        ENTITY
        | {"hand_back": "switch", "hand_back_entity": "switch.heat"}
        | {"hand_back_entity_write_type": "held"}
        | _HEATING_SWITCH,
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["hand_back_switch_is_heating_switch"],
    ),
    (
        "a hand-back value above the highest water temperature",
        ENTITY | {"hand_back_value": 75} | _HEATING_SWITCH,
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["hand_back_value_above_max"],
    ),
    (
        "a gateway lacking its id, read-back, topology and curve",
        {"write_path": "opentherm_gw"},
        RADIATORS,
        None,
        (Signal.FLAME, Signal.FLOW),
        ["no_gateway", "no_confirmed_setpoint", "no_topology", "curve_not_entered"],
    ),
    (
        "the firmware's topics missing, a monitor-mode topology",
        {
            "write_path": "otgw_mqtt",
            "topology": "monitor_mode",
            "confirmed_entity": "sensor.x",
            "curve": CURVE,
        },
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["no_mqtt_topic", "topology_no_control"],
    ),
    (
        "a topology the path does not suit",
        OTGW | {"topology": "virtual"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["topology_not_for_path"],
    ),
    (
        "an on/off contact on the terminals",
        OTGW | WITH_THERMOSTAT | {"thermostat_kind": "on_off"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["thermostat_on_off"],
    ),
    (
        "the terminals' answer contradicting the topology",
        OTGW | {"thermostat_kind": "opentherm"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["thermostat_kind_contradicts_topology"],
    ),
    (
        '"I don\'t know" on the terminals',
        OTGW | {"thermostat_kind": "unknown"},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["thermostat_kind_dont_know"],
    ),
    (
        "the curve's own problems only once it is entered",
        OTGW | {"curve": {"design_outdoor": -15, "design_flow": 25, "room": 20.5}},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["design_flow_too_low"],
    ),
    (
        "two circuits before the underfloor rule",
        OTGW,
        _TWO_CIRCUITS,
        None,
        _ALL_SIGNALS,
        ["one_direct_circuit_only"],
    ),
    (
        "underfloor without its maximum",
        OTGW,
        _FLOOR,
        None,
        _ALL_SIGNALS,
        ["underfloor_without_max_flow"],
    ),
    (
        "no zone before the count",
        OTGW | {"count_threshold": 3},
        _NO_ZONES,
        None,
        _ALL_SIGNALS,
        ["no_zones"],
    ),
    (
        "a count above the zones",
        OTGW | {"count_threshold": 3},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["count_threshold_above_zones"],
    ),
    (
        '"off" next to the lowest water temperature, without heating writes',
        ENTITY | {"off_setpoint": 19.5, "hard_min": 20},
        RADIATORS,
        None,
        _ALL_SIGNALS,
        ["no_heating_switch", "off_setpoint_not_below_hard_min"],
    ),
    (
        '"off" is no setpoint with heating writes',
        ENTITY | {"off_setpoint": 19.5, "hard_min": 20} | _HEATING_SWITCH,
        RADIATORS,
        None,
        _ALL_SIGNALS,
        [],
    ),
    (
        "the lowest above the circuit's maximum",
        OTGW | {"hard_min": 45},
        _CAPPED,
        None,
        _ALL_SIGNALS,
        ["hard_min_above_max"],
    ),
    (
        "the lowest at the circuit's maximum",
        OTGW | {"hard_min": 40},
        _CAPPED,
        None,
        _ALL_SIGNALS,
        [],
    ),
    (
        "flame and flow not mapped",
        OTGW,
        RADIATORS,
        None,
        _NO_SIGNALS,
        ["no_flame_signal", "no_flow_signal"],
    ),
    (
        "one entity for two signals",
        OTGW,
        RADIATORS,
        {"flow": "flame"},
        _ALL_SIGNALS,
        ["entity_for_two_signals"],
    ),
    ("nothing lacking", OTGW, RADIATORS, None, (Signal.FLAME, Signal.FLOW), []),
]


@pytest.mark.parametrize(
    ("section", "installation", "shared", "signals", "expected"),
    [row[1:] for row in BLOCKER_PRECEDENCE],
    ids=[row[0] for row in BLOCKER_PRECEDENCE],
)
def test_the_precedence_of_the_configuration_blockers(
    section: dict,
    installation: Installation,
    shared: dict[str, str] | None,
    signals: tuple | None,
    expected: list[str],
) -> None:
    """P-115: exactly these blockers, in this order, for each set of lacks at once."""
    control = parse_control(section, installation, None)
    pairs = None if shared is None else {Signal(k): Signal(v) for k, v in shared.items()}
    assert config_blockers(control, installation, pairs, signals=signals) == expected


# --- SB-10 (decision 12): a setup that fails where a hand-back stops heating -----------------

# A control section this version cannot read: a write path it does not know.
UNREADABLE_SECTION = {"write_path": "carrier_pigeon"}
NOT_HEATED, MAY_NOT_BE_HEATED = "setup_failed_not_heated", "setup_failed_may_not_be_heated"
MONITOR = OTGW | {"topology": "monitor_mode"}


@pytest.mark.parametrize(
    ("section", "state", "report"),
    [
        # The options' control section decides where it can be read.
        (OTGW, {"enabled": True}, NOT_HEATED),  # a gateway without a thermostat
        (OTGW, {"enabled": False}, None),  # control switched off: no heat from it either way
        (OTGW | WITH_THERMOSTAT, {"enabled": True}, None),  # the thermostat takes over
        (OTGW | {"topology": "virtual"}, {"enabled": True}, None),  # the device decides
        (RELAY, {"enabled": True}, NOT_HEATED),  # a relay resting "off"
        (RELAY | {"relay_rest_state": "on"}, {"enabled": True}, None),  # the boiler heats
        (OTGW | WITH_THERMOSTAT, {"enabled": True, "taken_with": OTGW}, None),  # options first
        # A wish never stored, one that cannot be read, a state not read at all: the cautious
        # side — only a clear "off" is off.
        (OTGW, {}, NOT_HEATED),
        (OTGW, {"enabled": None}, NOT_HEATED),
        (OTGW, {"enabled": "yes"}, NOT_HEATED),
        (OTGW, None, NOT_HEATED),
        # The options' section cannot be read: the options the control was taken with decide.
        (UNREADABLE_SECTION, {"enabled": True, "taken_with": OTGW}, NOT_HEATED),
        (UNREADABLE_SECTION, {"enabled": True, "taken_with": OTGW | WITH_THERMOSTAT}, None),
        (UNREADABLE_SECTION, {"enabled": False, "taken_with": OTGW}, None),
        # Neither tells what a hand-back does: the house may not be heated.
        (UNREADABLE_SECTION, {"enabled": True}, MAY_NOT_BE_HEATED),
        (UNREADABLE_SECTION, {"enabled": True, "taken_with": None}, MAY_NOT_BE_HEATED),
        (UNREADABLE_SECTION, {"taken_with": UNREADABLE_SECTION}, MAY_NOT_BE_HEATED),
        (UNREADABLE_SECTION, {"enabled": True, "taken_with": "damaged"}, MAY_NOT_BE_HEATED),
        (UNREADABLE_SECTION, None, MAY_NOT_BE_HEATED),
        # A stored monitor-only topology (refused by today's form): the plugin never takes the
        # boiler with it, so nothing where the stored state shows no earlier session holding
        # it (finding 6 of the part-1 check D); one taken with other options decides; a state
        # not read, or options taken with that cannot be read, tell nothing — the cautious side.
        (MONITOR, {"enabled": True}, None),
        (MONITOR, {"enabled": True, "taken_with": None}, None),
        (MONITOR, {"enabled": True, "taken_with": OTGW}, NOT_HEATED),
        (MONITOR, {"enabled": True, "taken_with": OTGW | WITH_THERMOSTAT}, None),
        (MONITOR, {"enabled": True, "taken_with": UNREADABLE_SECTION}, MAY_NOT_BE_HEATED),
        (MONITOR, None, MAY_NOT_BE_HEATED),
        # No control section: control is not configured, so a setup that worked would not heat
        # either — whatever the last run took the boiler with.
        (None, {"enabled": True, "taken_with": OTGW}, None),
        ({"write_path": ""}, {"enabled": True, "taken_with": OTGW}, None),
    ],
)
def test_a_failed_setup_tells_of_a_house_not_heated(
    section: dict | None, state: dict | None, report: str | None
) -> None:
    from custom_components.vtherm_smart_boiler.control_config import failed_setup_report

    options = {"signals": {}} if section is None else {"signals": {}, "control": section}
    found = failed_setup_report(options, state)
    assert (None if found is None else found.value) == report


def test_a_failed_setup_with_options_of_another_shape_tells_nothing() -> None:
    from custom_components.vtherm_smart_boiler.control_config import failed_setup_report

    assert failed_setup_report(None, {"enabled": True, "taken_with": OTGW}) is None
    assert failed_setup_report({"control": "damaged"}, {"enabled": True}) is None


@pytest.mark.parametrize(
    ("data", "stops"),
    [
        (OTGW, True),
        (OTGW | WITH_THERMOSTAT, False),
        (RELAY, True),
        (OTGW | {"topology": "monitor_mode"}, None),  # control cannot run: no effect known
        (UNREADABLE_SECTION, None),
        ({}, None),
        (None, None),
        ("damaged", None),
    ],
)
def test_a_stored_section_tells_whether_a_hand_back_stops_heating(
    data: object, stops: bool | None
) -> None:
    """Without the installation a bare one stands in: the effect needs the section alone."""
    from custom_components.vtherm_smart_boiler.control_config import section_stops_heating

    assert section_stops_heating(data) is stops


# --- PB-09: what cannot change while a hand-back is owed, or control holds the boiler ----------


@pytest.mark.parametrize(
    ("path", "judged"),
    [
        (
            "entity",
            {
                "confirmed_entity", "ch_confirmed_entity", "write_type", "ch_write_type",
                "hand_back_timeout_min",
            },
        ),
        ("opentherm_gw", {"confirmed_entity"}),
        ("otgw_mqtt", {"confirmed_entity"}),
        ("relay", set()),
        (None, set()),  # no control stored
        ("carrier_pigeon", set()),  # a path this version does not know
    ],
)  # fmt: skip
def test_what_judges_a_release_is_fixed_on_its_path(path: str | None, judged: set[str]) -> None:
    """PB-09: beside what a hand-back goes through, what judges its release on the path; the
    lowest water temperature only while one is owed — made after a change, a hand-back writes
    the new lowest first and is judged by it."""
    from custom_components.vtherm_smart_boiler.control_config import HAND_BACK_KEYS

    holding = set(fixed_keys(path, owed=False))
    owed = set(fixed_keys(path, owed=True))
    assert holding == set(HAND_BACK_KEYS) | judged
    lowest = {"hard_min"} if judged else set()
    request = {"thermostat_setpoint_entity"} if path in ("opentherm_gw", "otgw_mqtt") else set()
    assert owed == holding | lowest | request


@pytest.mark.parametrize(
    ("path", "fixed"),
    [
        ("opentherm_gw", True), ("otgw_mqtt", True),
        ("entity", False), ("relay", False), (None, False),
    ],
)  # fmt: skip
def test_the_thermostats_request_is_fixed_while_a_gateway_hand_back_is_owed(
    path: str | None, fixed: bool
) -> None:
    """L1 of the part-2 check: on a gateway the thermostat's request confirms a hand-back
    (PB-10), so it is fixed while one is owed (PB-09). Only then: while control holds the
    boiler it may be mapped or changed. Negative: on other paths it judges nothing."""
    assert "thermostat_setpoint_entity" not in fixed_keys(path, owed=False)
    assert ("thermostat_setpoint_entity" in fixed_keys(path, owed=True)) is fixed


@pytest.mark.parametrize(
    ("data", "others", "blocker"),
    [
        (RELAY, ("switch.boiler_relay",), "relay_in_another_role"),  # a zone's stove switch
        (OTGW | {"thermostat_setpoint_entity": "sensor.otgw_control_setpoint"}, (), None),
        (OTGW | {"write_path": "otgw_mqtt", "mqtt_top": "OTGW", "mqtt_node": "+"}, (), None),
        (OTGW | {"write_path": "otgw_mqtt", "mqtt_top": "my top", "mqtt_node": "n"}, (), None),
        (OTGW | {"write_path": "otgw_mqtt", "mqtt_top": " OTGW", "mqtt_node": "n"}, (), None),
    ],
)
def test_what_the_form_refuses_blocks_options_that_bypass_it(
    data: dict, others: tuple[str, ...], blocker: str | None
) -> None:
    """PB-70: the relay named elsewhere in the options — a zone's foreign-heat switch, which the
    plugin would switch as the boiler and read back as foreign heat; the thermostat's own
    setpoint picked as the read-back; an MQTT topic level with a wildcard or a space."""
    expected = {
        "relay_in_another_role",
        "thermostat_setpoint_same_as_read_back",
        "mqtt_topic_invalid",
    }
    installation = ON_OFF if data is RELAY else RADIATORS
    control = parse_control(data, installation, None)
    found = set(config_blockers(control, installation, others=others)) & expected
    if blocker is None:
        assert len(found) == 1
    else:
        assert found == {blocker}
    # Negative: nothing named elsewhere, the read-back not the thermostat's, valid topics.
    clean = {
        k: v
        for k, v in data.items()
        if k not in ("thermostat_setpoint_entity", "mqtt_top", "mqtt_node")
    }
    if data.get("write_path") == "otgw_mqtt":
        clean |= {"mqtt_top": "OTGW", "mqtt_node": "otgw"}
    control = parse_control(clean, installation, None)
    assert not set(config_blockers(control, installation, others=())) & expected


# --- I6.1: the connection and the control mode (decisions 1, 6) -----------------------------


@pytest.mark.parametrize(
    ("mode", "section", "expected"),
    [
        # Chosen on purpose: monitoring only, or room values (0.3) — the one reason, whatever
        # else the control section lacks or has.
        (ControlMode.MONITOR, {}, ["control_mode_monitor"]),
        (ControlMode.MONITOR, OTGW, ["control_mode_monitor"]),
        (ControlMode.ROOM_VALUES, {}, ["control_mode_room_values"]),
        (ControlMode.ROOM_VALUES, OTGW, ["control_mode_room_values"]),
        # Full control: judged as before.
        (ControlMode.FULL, {}, ["no_write_path"]),
        (ControlMode.FULL, OTGW, []),
        # An entry from before the panel (no mode): as before.
        (None, {}, ["no_write_path"]),
        (None, OTGW, []),
    ],
)
def test_a_control_mode_without_control_is_its_own_reason(
    mode: ControlMode | None, section: dict, expected: list[str]
) -> None:
    """I6.1 (decision 6): monitoring only, or room-temperature mode until 0.3, keeps control
    off with that reason alone — a control section stored beside it is not run, and its lacks
    are not listed; with full control, or no answer yet, the blockers are as before."""
    control = parse_control(section, RADIATORS, None, control_mode=mode)
    assert control.control_mode is mode
    signals = (Signal.FLAME, Signal.FLOW)
    assert config_blockers(control, RADIATORS, signals=signals) == expected


def test_the_connection_is_carried_without_a_control_section() -> None:
    """I6.1: the panel's answers reach the control options even where control is not set up,
    so the reason it is off can name them."""
    control = parse_control(
        {}, RADIATORS, None, connection=Connection.ESPHOME, control_mode=ControlMode.MONITOR
    )
    assert not control.configured
    assert control.connection is Connection.ESPHOME


def test_each_connection_offers_the_modes_it_can_do() -> None:
    """I6.1 (decisions 1, 6): a relay switches on and off; a read-only integration only
    monitors; every connection that can set a water temperature offers full control, room
    values (0.3) and monitoring. Monitoring is always offered."""
    water = (ControlMode.FULL, ControlMode.ROOM_VALUES, ControlMode.MONITOR)
    assert dict(CONNECTION_MODES) == {
        Connection.OPENTHERM_GW: water,
        Connection.OTGW_MQTT: water,
        Connection.ESPHOME: water,
        Connection.EMS_ESP: water,
        Connection.RELAY: (ControlMode.ON_OFF, ControlMode.MONITOR),
        Connection.BOILER_MODULE: water,
        Connection.OTHER_ENTITY: water,
        Connection.READ_ONLY: (ControlMode.MONITOR,),
    }


@pytest.mark.parametrize(
    ("connection", "mode", "expected"),
    [
        # What the connection can do, whatever the user wants now: the verdict can still say
        # "worth enabling" for a gateway that only monitors.
        (Connection.OPENTHERM_GW, ControlMode.FULL, BoilerClass.FLOW_SETPOINT),
        (Connection.OPENTHERM_GW, ControlMode.MONITOR, BoilerClass.FLOW_SETPOINT),
        (Connection.OTGW_MQTT, ControlMode.ROOM_VALUES, BoilerClass.FLOW_SETPOINT),
        (Connection.ESPHOME, ControlMode.FULL, BoilerClass.FLOW_SETPOINT),
        (Connection.EMS_ESP, ControlMode.MONITOR, BoilerClass.FLOW_SETPOINT),
        (Connection.OTHER_ENTITY, ControlMode.FULL, BoilerClass.FLOW_SETPOINT),
        (Connection.RELAY, ControlMode.ON_OFF, BoilerClass.ON_OFF),
        (Connection.RELAY, ControlMode.MONITOR, BoilerClass.ON_OFF),
        (Connection.READ_ONLY, ControlMode.MONITOR, BoilerClass.READ_ONLY),
        # Decision 5: the boiler's own module monitors by default; control only on purpose.
        (Connection.BOILER_MODULE, ControlMode.FULL, BoilerClass.FLOW_SETPOINT),
        (Connection.BOILER_MODULE, ControlMode.MONITOR, BoilerClass.READ_ONLY),
        (Connection.BOILER_MODULE, ControlMode.ROOM_VALUES, BoilerClass.READ_ONLY),
    ],
)
def test_the_boiler_class_follows_the_connection(
    connection: Connection, mode: ControlMode, expected: BoilerClass
) -> None:
    """I6.1 (decision 2): the class is no longer asked; it is what the connection can do."""
    assert boiler_class_for(connection, mode) is expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("opentherm_gw", Connection.OPENTHERM_GW),
        ("otgw_mqtt", Connection.OTGW_MQTT),
        ("relay", Connection.RELAY),
        # An entity may be ESPHome, EMS-ESP or another device: not guessed (decision 12).
        ("entity", None),
        (None, None),
        ("carrier_pigeon", None),
        (3, None),
    ],
)
def test_a_stored_write_path_suggests_its_connection(path: object, expected: object) -> None:
    """I6.1 (decision 12): an entry made before the panel is offered the connection its stored
    write path names; nothing where it does not."""
    assert connection_suggested_by(path) is expected
