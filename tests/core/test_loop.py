"""The control step: controller through the write guards."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.controller import ControlConfig, ControlInputs
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.guards import (
    GuardConfig,
    GuardEvent,
    GuardState,
    WriteKind,
    WriteType,
)
from custom_components.vtherm_smart_boiler.core.loop import (
    LastCommand,
    LoopConfig,
    LoopState,
    loop_step,
    parse_last_command,
    remember_command,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

CONFIG = LoopConfig(
    control=ControlConfig(curve=HeatingCurve(), ramp_k_per_min=None),
    setpoint_guard=GuardConfig(write_type=WriteType.EXPIRING),
)


EXPIRING_SWITCH = GuardConfig(write_type=WriteType.EXPIRING, read_back=False, two_valued=True)
ECHOED_SWITCH = GuardConfig(write_type=WriteType.HELD, two_valued=True)


def inputs(t: float, opening: float = 0.6, **kw) -> ControlInputs:
    kw.setdefault("enabled", True)
    zone = ZoneState("z", 20.0, 21.0, True, reported_at=t, valve_open=opening)
    return ControlInputs(now=t, flame=False, dhw=False, outdoor_sensor=5.0, zones=(zone,), **kw)


def test_first_step_writes_setpoint_and_heating_on() -> None:
    _state, out = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.CHANGE
    assert out.ch_enable is True
    assert out.heating_on is True


def test_keepalive_follows_between_decisions() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    state, out = loop_step(state, inputs(30.0), 45.0, CONFIG)
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.KEEPALIVE
    assert out.ch_enable is None  # unchanged, no keep-alive configured for the switch


def test_hand_back_passes_and_resets_the_guards() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    state, out = loop_step(state, inputs(30.0, enabled=False), 45.0, CONFIG)
    assert out.hand_back
    assert out.setpoint is None
    assert state.setpoint == GuardState()  # a later session starts afresh
    assert state.switch.written is None


def test_without_a_switch_off_is_a_low_setpoint() -> None:
    config = replace(CONFIG, ch_writes=False, off_setpoint=12.0)
    _state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), None, config)
    assert out.ch_enable is None
    assert out.setpoint is not None
    assert out.setpoint.value == 12.0
    assert out.heating_on is False


def test_nothing_is_written_while_waiting_for_data() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    _state, out = loop_step(state, inputs(30.0, boiler_link=False), None, CONFIG)
    assert out.setpoint is None
    assert out.ch_enable is None
    assert not out.hand_back


def test_an_expiring_heating_override_is_repeated() -> None:
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    assert out.ch_enable is True
    _state, out = loop_step(state, inputs(30.0), 45.0, config)
    assert out.ch_enable is True  # repeated with the setpoint's keep-alive


def test_heating_on_off_follows_a_recovered_setpoint_at_once() -> None:
    """After a lapse the gateway's heating override is gone with it: the recovery write carries
    the heating state too, not only the next keep-alive."""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    state, _ = loop_step(state, inputs(10.0), out.setpoint.value, config)  # confirmed
    state, out = loop_step(state, inputs(20.0), 30.0, config)  # the gateway dropped it
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.REWRITE
    assert out.ch_enable is True


def test_a_blocked_setpoint_stops_the_heating_writes_too() -> None:
    """P53: another controller has the boiler: every write stops, heating on/off included,
    whatever the alarm's reaction."""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    blocked = replace(state.setpoint, blocked=GuardEvent.OUTSIDE_CHANGE)
    state = replace(state, setpoint=blocked)
    _state, out = loop_step(state, inputs(30.0, opening=0.0), 60.0, config)
    assert out.setpoint is None
    assert out.ch_enable is None
    assert out.blocked


def test_heating_is_confirmed_by_its_echo() -> None:
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config, False)
    assert out.ch_enable is True
    state, out = loop_step(state, inputs(10.0), out.setpoint.value, config, True)
    assert state.switch.confirmed_at == 10.0


def test_heating_switched_from_outside_stops_every_write() -> None:
    """P22: with an echo, heating on/off falls under the one-rewrite rule; the second outside
    change stops the setpoint writes too."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config, False)
    setpoint = out.setpoint.value
    state, _ = loop_step(state, inputs(10.0), setpoint, config, True)  # confirmed
    state, out = loop_step(state, inputs(20.0), setpoint, config, False)  # switched off outside
    assert out.heating is not None
    assert out.heating.kind is WriteKind.REWRITE
    state, _ = loop_step(state, inputs(30.0), setpoint, config, True)
    state, out = loop_step(state, inputs(40.0), setpoint, config, False)  # again
    assert out.blocked
    assert out.events == (GuardEvent.OUTSIDE_CHANGE,)
    _state, out = loop_step(state, inputs(70.0), setpoint, config, False)
    assert (out.setpoint, out.heating, out.blocked) == (None, None, True)  # no keep-alive either


def test_a_blocked_setpoint_leaves_this_steps_heating_write_unmade() -> None:
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    setpoint = out.setpoint.value
    state, _ = loop_step(state, inputs(10.0), setpoint, config)  # confirmed
    state, _ = loop_step(state, inputs(20.0), 60.0, config)  # the one rewrite
    state, _ = loop_step(state, inputs(25.0), setpoint, config)
    before = state.switch
    state, out = loop_step(state, inputs(35.0, opening=0.0), 60.0, config)  # heating off asked
    assert out.blocked
    assert out.heating is None
    assert state.switch == before  # not recorded as written


# --- the last command (V3) ------------------------------------------------------------------


def test_the_first_command_is_saved_at_once() -> None:
    command, save_now = remember_command(None, True, 45.0, 10.0)
    assert command == LastCommand(True, 45.0, 10.0)
    assert save_now


def test_a_change_of_heating_is_saved_at_once() -> None:
    _, save_now = remember_command(LastCommand(True, 45.0, 0.0), False, 45.0, 10.0)
    assert save_now


def test_a_setpoint_change_of_a_kelvin_or_more_is_saved_at_once() -> None:
    before = LastCommand(True, 45.0, 0.0)
    assert remember_command(before, True, 46.0, 10.0)[1]
    assert remember_command(before, True, 44.0, 10.0)[1]
    assert remember_command(before, True, None, 10.0)[1]
    assert remember_command(LastCommand(True, None, 0.0), True, 45.0, 10.0)[1]


def test_a_small_setpoint_step_waits_for_the_next_save() -> None:
    command, save_now = remember_command(LastCommand(True, 45.0, 0.0), True, 45.5, 10.0)
    assert command == LastCommand(True, 45.5, 10.0)  # kept in memory, written with the next save
    assert not save_now


def test_a_last_command_round_trips() -> None:
    command = LastCommand(False, None, 12.5)
    assert parse_last_command(command.as_dict()) == command
    assert parse_last_command({"heating": True, "setpoint": 40, "at": 3}) == LastCommand(
        True, 40.0, 3.0
    )


@pytest.mark.parametrize(
    "raw",
    [
        "garbage",
        [],
        {},
        {"heating": "yes", "setpoint": 40.0, "at": 0.0},
        {"heating": 1, "setpoint": 40.0, "at": 0.0},
        {"heating": True, "setpoint": "40", "at": 0.0},
        {"heating": True, "setpoint": True, "at": 0.0},
        {"heating": True, "setpoint": float("nan"), "at": 0.0},
        {"heating": True, "setpoint": 40.0},
        {"heating": True, "setpoint": 40.0, "at": None},
        {"heating": True, "setpoint": 40.0, "at": float("inf")},
    ],
)
def test_an_unreadable_last_command_is_refused(raw: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_last_command(raw)


def test_small_steps_are_stored_at_once_as_they_add_up() -> None:
    stored = LastCommand(True, 45.0, 0.0)
    assert not remember_command(stored, True, 45.5, 10.0)[1]
    assert remember_command(stored, True, 46.0, 20.0)[1]  # a kelvin from the one stored
