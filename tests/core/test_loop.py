"""The control step: controller through the write guards."""

from __future__ import annotations

from dataclasses import replace

from custom_components.vtherm_smart_boiler.core.controller import ControlConfig, ControlInputs
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.guards import (
    SetpointGuardConfig,
    SwitchGuardConfig,
    WriteKind,
    WriteType,
)
from custom_components.vtherm_smart_boiler.core.loop import (
    LoopConfig,
    LoopState,
    loop_step,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

CONFIG = LoopConfig(
    control=ControlConfig(curve=HeatingCurve(), ramp_k_per_min=None),
    setpoint_guard=SetpointGuardConfig(write_type=WriteType.EXPIRING),
)


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
    assert state.setpoint.written is None
    assert state.switch.written is None


def test_hand_back_keeps_the_record_of_wearing_writes() -> None:
    config = replace(CONFIG, setpoint_guard=SetpointGuardConfig(write_type=WriteType.PERSISTENT))
    state, _ = loop_step(LoopState(), inputs(0.0), None, config)
    assert state.setpoint.history == (0.0,)
    state, out = loop_step(state, inputs(30.0, enabled=False), 45.0, config)
    assert out.hand_back
    assert state.setpoint.written is None
    assert state.setpoint.history == (0.0,)  # the daily cap still counts the earlier write


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


def test_near_the_daily_cap_a_wearing_setpoint_stops_switching_off() -> None:
    """The last writes before the cap return to heat, so the value held at the cap is never the
    low "off" setpoint (a cold house for the rest of the day)."""
    guard = SetpointGuardConfig(write_type=WriteType.PERSISTENT, daily_cap=4)
    config = replace(CONFIG, setpoint_guard=guard, ch_writes=False, off_setpoint=10.0)
    heat = inputs(0.0)
    state, out = loop_step(LoopState(), heat, None, config)
    heating = out.setpoint.value
    # Two writes left before the cap: off is no longer written.
    state = replace(state, setpoint=replace(state.setpoint, history=(0.0, 1.0, 2.0)))
    state = replace(state, switch=replace(state.switch, changed_at=-3600.0))
    _state, out = loop_step(state, inputs(4000.0, opening=0.0), heating, config)
    assert out.setpoint is None  # still heating: no write
    assert out.heating_on is True


def test_near_the_daily_cap_a_wearing_setpoint_returns_to_heat() -> None:
    guard = SetpointGuardConfig(write_type=WriteType.PERSISTENT, daily_cap=4)
    config = replace(CONFIG, setpoint_guard=guard, ch_writes=False, off_setpoint=10.0)
    state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), None, config)
    assert out.setpoint.value == 10.0  # off, far from the cap
    state = replace(state, setpoint=replace(state.setpoint, history=(0.0, 1.0, 2.0)))
    _state, out = loop_step(state, inputs(4000.0, opening=0.0), 10.0, config)
    assert out.setpoint is not None
    assert out.setpoint.value > 10.0  # back to heat with the last spare write
    assert out.heating_on is True


def test_an_expiring_heating_override_is_repeated() -> None:
    config = replace(CONFIG, switch_guard=SwitchGuardConfig(keepalive_s=30.0))
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    assert out.ch_enable is True
    _state, out = loop_step(state, inputs(30.0), 45.0, config)
    assert out.ch_enable is True  # repeated with the setpoint's keep-alive


def test_heating_on_off_follows_a_recovered_setpoint_at_once() -> None:
    """After a lapse the gateway's heating override is gone with it: the recovery write carries
    the heating state too, not only the next keep-alive."""
    config = replace(CONFIG, switch_guard=SwitchGuardConfig(keepalive_s=30.0))
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    state, _ = loop_step(state, inputs(10.0), out.setpoint.value, config)  # confirmed
    state, out = loop_step(state, inputs(20.0), 30.0, config)  # the gateway dropped it
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.REWRITE
    assert out.ch_enable is True
