"""One control step: the controller's decision through the write guards to what is written now.

The same step drives the simulator in tests and the real write path in Home Assistant. When the
write path cannot switch heating on and off, "off" is written as a low setpoint. A hand-back is
passed on as it is — the guards never hold it back — and resets the guards, so a later control
session starts fresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .controller import ControlConfig, ControlDecision, ControlInputs, ControlState, decide
from .guards import (
    GuardEvent,
    SetpointGuardConfig,
    SetpointGuardState,
    SwitchGuardConfig,
    SwitchGuardState,
    WriteAction,
    WriteKind,
    plan_setpoint,
    plan_switch,
)

DEFAULT_OFF_SETPOINT = 10.0


@dataclass(frozen=True, slots=True)
class LoopConfig:
    control: ControlConfig
    setpoint_guard: SetpointGuardConfig = field(default_factory=SetpointGuardConfig)
    switch_guard: SwitchGuardConfig = field(default_factory=SwitchGuardConfig)
    ch_writes: bool = True  # the write path can switch heating on and off
    off_setpoint: float = DEFAULT_OFF_SETPOINT  # written for "off" when it cannot


@dataclass(frozen=True, slots=True)
class LoopState:
    control: ControlState = field(default_factory=ControlState)
    setpoint: SetpointGuardState = field(default_factory=SetpointGuardState)
    switch: SwitchGuardState = field(default_factory=SwitchGuardState)


@dataclass(frozen=True, slots=True)
class LoopOutput:
    decision: ControlDecision
    setpoint: WriteAction | None = None  # setpoint to write now
    ch_enable: bool | None = None  # heating on/off to write now
    hand_back: bool = False  # give control back now
    events: tuple[GuardEvent, ...] = ()
    heating_on: bool | None = None  # the logical heating state now commanded


def loop_step(
    state: LoopState,
    inputs: ControlInputs,
    confirmed_setpoint: float | None,
    config: LoopConfig,
) -> tuple[LoopState, LoopOutput]:
    control, decision = decide(state.control, inputs, config.control)
    if decision.hand_back:
        return LoopState(control), LoopOutput(decision, hand_back=True)
    if decision.command is None:
        return replace(state, control=control), LoopOutput(decision)

    now = inputs.now
    switched = plan_switch(state.switch, decision.command.ch_enable, now, config.switch_guard)
    heating_on = switched.state.written
    if config.ch_writes:
        desired = decision.command.setpoint
        ch_write = switched.write
    else:
        off = heating_on is False  # "off" is a low setpoint
        desired = config.off_setpoint if off else decision.command.setpoint
        heating_on = not off
        ch_write = None
    planned = plan_setpoint(state.setpoint, desired, confirmed_setpoint, now, config.setpoint_guard)
    recovered = planned.action is not None and planned.action.kind in (
        WriteKind.REWRITE,
        WriteKind.RESEND,
    )
    if config.ch_writes and recovered and ch_write is None and heating_on is not None:
        # A setpoint override that had lapsed took the heating override with it: send both.
        ch_write = heating_on
    new_state = LoopState(control, planned.state, switched.state)
    return new_state, LoopOutput(
        decision,
        planned.action,
        ch_write,
        False,
        planned.events,
        heating_on,
    )
