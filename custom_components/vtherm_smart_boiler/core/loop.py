"""One control step: the controller's decision through the write guards to what is written now.

The same step drives the simulator in tests and the real write path in Home Assistant. Heating
on/off goes through a guard of its own, as 1 and 0; when the write path cannot switch heating on
and off, "off" is written as a low setpoint. Once a guard has found another controller, every
write stops — the setpoint and heating on/off alike, whatever the alarm's reaction: the plugin
never fights it. A hand-back is passed on as it is — the guards never hold it back — and resets
the guards, so a later control session starts fresh.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from .controller import ControlConfig, ControlDecision, ControlInputs, ControlState, decide
from .guards import (
    GuardConfig,
    GuardEvent,
    GuardResult,
    GuardState,
    WriteAction,
    WriteKind,
    WriteType,
    plan_write,
)

DEFAULT_OFF_SETPOINT = 10.0
ON, OFF = 1.0, 0.0  # heating on/off as the guard sees it
# A setpoint written this far from the last command stored is stored at once; a smaller step
# (a ramp's) waits for the next save (provisional, K4).
LAST_COMMAND_SAVE_K = 1.0


def _no_echo_switch() -> GuardConfig:
    return GuardConfig(write_type=WriteType.HELD, read_back=False, two_valued=True)


@dataclass(frozen=True, slots=True)
class LoopConfig:
    control: ControlConfig
    setpoint_guard: GuardConfig = field(default_factory=GuardConfig)
    switch_guard: GuardConfig = field(default_factory=_no_echo_switch)  # heating on/off
    ch_writes: bool = True  # the write path can switch heating on and off
    off_setpoint: float = DEFAULT_OFF_SETPOINT  # written for "off" when it cannot


@dataclass(frozen=True, slots=True)
class LoopState:
    control: ControlState = field(default_factory=ControlState)
    setpoint: GuardState = field(default_factory=GuardState)
    switch: GuardState = field(default_factory=GuardState)


@dataclass(frozen=True, slots=True)
class LoopOutput:
    decision: ControlDecision
    setpoint: WriteAction | None = None  # setpoint to write now
    heating: WriteAction | None = None  # heating on/off to write now, as 1 or 0
    hand_back: bool = False  # give control back now
    events: tuple[GuardEvent, ...] = ()
    heating_on: bool | None = None  # the logical heating state now commanded
    blocked: bool = False  # another controller has the boiler: nothing is written

    @property
    def ch_enable(self) -> bool | None:
        """Heating on/off to write now."""
        return None if self.heating is None else self.heating.value == ON


def _level(on: bool | None) -> float | None:
    return None if on is None else (ON if on else OFF)


def loop_step(
    state: LoopState,
    inputs: ControlInputs,
    confirmed_setpoint: float | None,
    config: LoopConfig,
    confirmed_heating: bool | None = None,
) -> tuple[LoopState, LoopOutput]:
    control, decision = decide(state.control, inputs, config.control)
    if decision.hand_back:
        return LoopState(control), LoopOutput(decision, hand_back=True)
    blocked = state.setpoint.blocked is not None or state.switch.blocked is not None
    if decision.command is None or blocked:
        return replace(state, control=control), LoopOutput(decision, blocked=blocked)

    now = inputs.now
    command = decision.command
    if config.ch_writes:
        heat = plan_write(
            state.switch,
            _level(command.ch_enable),
            _level(confirmed_heating),
            now,
            config.switch_guard,
        )
        desired = command.setpoint
    else:
        heat = GuardResult(state.switch)
        desired = config.off_setpoint if command.ch_enable is False else command.setpoint
    planned = plan_write(state.setpoint, desired, confirmed_setpoint, now, config.setpoint_guard)
    events = (*planned.events, *heat.events)
    if planned.state.blocked is not None or heat.state.blocked is not None:
        # Another controller: every write stops, and a write planned for the other target in
        # this step is not made.
        setpoint = planned.state if planned.state.blocked is not None else state.setpoint
        switch = heat.state if heat.state.blocked is not None else state.switch
        return LoopState(control, setpoint, switch), LoopOutput(
            decision, events=events, blocked=True
        )

    heating = heat.action
    recovered = planned.action is not None and planned.action.kind in (
        WriteKind.REWRITE,
        WriteKind.RESEND,
    )
    if config.ch_writes and recovered and heating is None and heat.state.written is not None:
        # A setpoint override that had lapsed took the heating override with it: send both.
        heating = WriteAction(heat.state.written, WriteKind.RESEND)
    if config.ch_writes:
        heating_on = None if heat.state.written is None else heat.state.written == ON
    else:
        written = planned.state.written
        heating_on = None if written is None else written != config.off_setpoint
    return LoopState(control, planned.state, heat.state), LoopOutput(
        decision, planned.action, heating, False, events, heating_on
    )


@dataclass(frozen=True, slots=True)
class LastCommand:
    """The last command given to the boiler: heating on/off as commanded and the setpoint as
    written (after the ramp; ``None`` before one got through), with when it was written. Kept
    across a restart so the next start can give it again (decision 3) or, for a relay, its
    state."""

    heating: bool
    setpoint: float | None
    at: float

    def as_dict(self) -> dict[str, bool | float | None]:
        return {"heating": self.heating, "setpoint": self.setpoint, "at": self.at}


def _finite(raw: object) -> float:
    if isinstance(raw, bool) or not isinstance(raw, int | float) or not math.isfinite(raw):
        raise ValueError(f"not a finite number: {raw!r}")
    return float(raw)


def parse_last_command(raw: object) -> LastCommand:
    """A stored last command; anything else raises ``ValueError`` or ``TypeError``."""
    if not isinstance(raw, Mapping):
        raise TypeError("the last command is not a mapping")
    heating = raw.get("heating")
    if not isinstance(heating, bool):
        raise ValueError(f"heating is not a flag: {heating!r}")
    setpoint = raw.get("setpoint")
    return LastCommand(
        heating, None if setpoint is None else _finite(setpoint), _finite(raw.get("at"))
    )


def remember_command(
    stored: LastCommand | None, heating: bool, setpoint: float | None, now: float
) -> tuple[LastCommand, bool]:
    """The last command after a write went through, and whether it is to be stored at once
    against the one last stored at once (``stored``): a first command, heating switched on or
    off, or a setpoint at least ``LAST_COMMAND_SAVE_K`` from it — so a ramp's small steps are
    stored at once only as they add up."""
    command = LastCommand(heating, setpoint, now)
    if stored is None or stored.heating != heating:
        return command, True
    if stored.setpoint is None or setpoint is None:
        return command, stored.setpoint != setpoint
    return command, abs(setpoint - stored.setpoint) >= LAST_COMMAND_SAVE_K
