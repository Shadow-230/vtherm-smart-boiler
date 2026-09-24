"""The controller state machine: precedence, hand-back, data problems, heating decisions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.anticycling import AntiCycleConfig
from custom_components.vtherm_smart_boiler.core.controller import (
    BoilerCommand,
    CentralMode,
    ControlConfig,
    ControlInputs,
    ControlMode,
    ControlState,
    Reason,
    decide,
    fallback_setpoint,
)
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

MIN = 60.0
CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.0)
CONFIG = ControlConfig(curve=CURVE, ramp_k_per_min=None)


def zone(t: float, **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    kw.setdefault("temperature", 20.0)
    kw.setdefault("target", 21.0)
    kw.setdefault("valve_open", 0.6)
    return ZoneState("z", reported_at=t, **kw)


def inputs(t: float, **kw) -> ControlInputs:
    kw.setdefault("enabled", True)
    kw.setdefault("flame", False)
    kw.setdefault("dhw", False)
    kw.setdefault("outdoor_sensor", 5.0)
    kw.setdefault("zones", (zone(t),))
    return ControlInputs(now=t, **kw)


def run(steps, config: ControlConfig = CONFIG, state: ControlState | None = None):
    state = state or ControlState()
    decisions = []
    for step in steps:
        state, decision = decide(state, step, config)
        decisions.append(decision)
    return state, decisions


def test_disabled_writes_nothing_and_hands_back_nothing() -> None:
    _state, [decision] = run([inputs(0.0, enabled=False)])
    assert decision.mode is ControlMode.DISABLED
    assert decision.command is None
    assert not decision.hand_back


def test_heating_follows_the_curve() -> None:
    state, [decision] = run([inputs(0.0)])
    assert decision.mode is ControlMode.HEATING
    assert decision.command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert Reason.DEMAND in decision.reasons
    assert Reason.OUTDOOR_SENSOR in decision.reasons
    assert state.controlling


def test_switching_off_hands_back_once() -> None:
    _state, decisions = run([inputs(0.0), inputs(30.0, enabled=False), inputs(60.0, enabled=False)])
    assert [d.hand_back for d in decisions] == [False, True, False]
    assert decisions[1].command is None


def test_missing_precondition_hands_back() -> None:
    _state, decisions = run([inputs(0.0), inputs(30.0, blockers=("no_hand_back",))])
    assert decisions[1].mode is ControlMode.NOT_ALLOWED
    assert decisions[1].hand_back


def test_alarm_hand_back_is_latched_until_control_is_switched_off() -> None:
    state, decisions = run(
        [
            inputs(0.0),
            inputs(30.0, hand_back_alarms=("pressure_low",)),
            inputs(60.0),  # the alarm cleared: still handed back
            inputs(90.0, blockers=("x",)),
            inputs(120.0),
        ]
    )
    assert decisions[1].hand_back
    assert [d.mode for d in decisions[1:]] == [
        ControlMode.HANDED_BACK,
        ControlMode.HANDED_BACK,
        ControlMode.NOT_ALLOWED,
        ControlMode.HANDED_BACK,
    ]
    state, decisions = run([inputs(150.0, enabled=False), inputs(180.0)], state=state)
    assert decisions[1].mode is ControlMode.HEATING


def test_central_stopped_hands_back_and_resumes_at_once() -> None:
    _state, decisions = run(
        [
            inputs(0.0),
            inputs(30.0, central_mode=CentralMode.STOPPED),
            inputs(60.0, central_mode=CentralMode.AUTO),
        ]
    )
    assert decisions[1].hand_back
    assert decisions[1].mode is ControlMode.HANDED_BACK
    assert decisions[2].mode is ControlMode.HEATING
    assert decisions[2].command is not None


def test_stale_boiler_link_writes_nothing_and_keeps_control() -> None:
    state, decisions = run([inputs(0.0), inputs(30.0, boiler_link=False), inputs(60.0)])
    assert decisions[1].mode is ControlMode.WAITING_DATA
    assert decisions[1].command is None
    assert not decisions[1].hand_back
    assert decisions[2].command is not None  # decided again at once
    assert state.controlling


def test_no_demand_is_idle() -> None:
    _state, [decision] = run([inputs(0.0, zones=(zone(0.0, valve_open=0.0),))])
    assert decision.mode is ControlMode.IDLE
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert Reason.NO_DEMAND in decision.reasons


def test_unknown_zones_mean_heat() -> None:
    stale = zone(-10 * 3600.0)
    _state, [decision] = run([inputs(0.0, zones=(stale,))])
    assert decision.mode is ControlMode.HEATING
    assert Reason.ZONES_UNKNOWN in decision.reasons
    _state, [none] = run([inputs(0.0, zones=())])
    assert Reason.ZONES_UNKNOWN in none.reasons


def test_summer_blocks_heating_but_frost_does_not() -> None:
    _state, [summer] = run([inputs(0.0, outdoor_sensor=25.0)])
    assert summer.mode is ControlMode.SUMMER
    assert summer.command is not None
    assert not summer.command.ch_enable
    cold_room = (zone(0.0, temperature=4.0),)
    _state, [frost] = run([inputs(0.0, outdoor_sensor=25.0, zones=cold_room)])
    assert frost.mode is ControlMode.FROST
    assert frost.command is not None
    assert frost.command.ch_enable


def test_cool_only_blocks_heating() -> None:
    _state, [decision] = run([inputs(0.0, central_mode=CentralMode.COOL_ONLY)])
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert Reason.CENTRAL_COOL_ONLY in decision.reasons


def test_missing_outdoor_temperature_uses_the_fallback_setpoint() -> None:
    steps = [
        inputs(0.0),
        inputs(1800.0, outdoor_sensor=None),
        inputs(2 * 3600.0, outdoor_sensor=None),
    ]
    config = replace(CONFIG, decision_interval_s=60.0)
    _state, decisions = run(steps, config)
    assert Reason.OUTDOOR_HELD in decisions[1].reasons
    assert decisions[2].mode is ControlMode.FALLBACK
    assert decisions[2].command == BoilerCommand(True, pytest.approx(CURVE.flow(0.0)))
    assert fallback_setpoint(replace(CONFIG, fallback_setpoint=48.0)) == 48.0


def test_weather_entity_stands_in_for_the_sensor() -> None:
    _state, [decision] = run([inputs(0.0, outdoor_sensor=None, outdoor_weather=0.0)])
    assert Reason.OUTDOOR_WEATHER in decision.reasons
    assert decision.command == BoilerCommand(True, pytest.approx(CURVE.flow(0.0)))


def test_decisions_wait_for_the_interval() -> None:
    _state, decisions = run(
        [
            inputs(0.0),
            inputs(60.0, zones=(zone(60.0, valve_open=0.0),)),  # demand gone, but too early
            inputs(300.0, zones=(zone(300.0, valve_open=0.0),)),
        ]
    )
    assert decisions[1].command == decisions[0].command
    assert decisions[2].command is not None
    assert not decisions[2].command.ch_enable


def test_frost_does_not_wait_for_the_interval() -> None:
    _state, decisions = run(
        [
            inputs(0.0, zones=(zone(0.0, valve_open=0.0),)),
            inputs(30.0, zones=(zone(30.0, temperature=4.0, valve_open=0.0),)),
        ]
    )
    assert decisions[1].mode is ControlMode.FROST


def test_ramp_limits_the_rise_and_min_step_coarsens_it() -> None:
    config = replace(CONFIG, ramp_k_per_min=1.0, decision_interval_s=60.0)
    _state, decisions = run(
        [inputs(0.0, outdoor_sensor=15.0), inputs(60.0, outdoor_sensor=-10.0)], config
    )
    first = decisions[0].command
    second = decisions[1].command
    assert first is not None
    assert second is not None
    assert second.setpoint == pytest.approx(first.setpoint + 1.0)
    assert Reason.RAMP in decisions[1].reasons
    coarse = replace(config, ramp_k_per_min=0.2, min_step=1.0)
    _state, decisions = run(
        [inputs(0.0, outdoor_sensor=15.0), inputs(60.0, outdoor_sensor=-10.0)], coarse
    )
    assert decisions[1].command.setpoint == pytest.approx(decisions[0].command.setpoint + 1.0)


def test_small_changes_below_the_min_step_are_not_written() -> None:
    config = replace(CONFIG, min_step=1.0, decision_interval_s=60.0)
    _state, decisions = run(
        [inputs(0.0, outdoor_sensor=5.0), inputs(60.0, outdoor_sensor=4.8)], config
    )
    assert decisions[1].command.setpoint == decisions[0].command.setpoint


def test_a_lowered_cap_applies_at_once() -> None:
    config = replace(CONFIG, ramp_k_per_min=0.1, decision_interval_s=60.0)
    state, decisions = run([inputs(0.0, outdoor_sensor=-10.0)], config)
    capped = replace(config, circuit_max=35.0)
    state, decisions = run([inputs(60.0, outdoor_sensor=-10.0)], capped, state)
    assert decisions[0].command.setpoint == 35.0
    assert Reason.LIMIT_CIRCUIT_MAX in decisions[0].reasons


def test_limits_apply_to_the_curve() -> None:
    config = replace(CONFIG, limits=FlowLimits(hard_min=30.0, hard_max=50.0))
    _state, [mild] = run([inputs(0.0, outdoor_sensor=15.0)], config)
    assert mild.command.setpoint == 30.0
    assert Reason.LIMIT_HARD_MIN in mild.reasons


def test_anti_cycling_pause_after_a_burn() -> None:
    config = replace(
        CONFIG, anticycling=AntiCycleConfig(min_pause_s=10 * MIN), decision_interval_s=60.0
    )
    _state, decisions = run(
        [
            inputs(0.0, flame=False),
            inputs(60.0, flame=True),
            inputs(300.0, flame=False),
            inputs(360.0, flame=False),
        ],
        config,
    )
    assert decisions[-1].mode is ControlMode.IDLE
    assert Reason.MIN_PAUSE in decisions[-1].reasons
    assert decisions[-1].hold_until == pytest.approx(300.0 + 600.0)


@pytest.mark.parametrize(
    "kwargs", [{"decision_interval_s": 0.0}, {"ramp_k_per_min": 0.0}, {"min_step": -1.0}]
)
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        replace(CONFIG, **kwargs)
