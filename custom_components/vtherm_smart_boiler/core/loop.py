"""One control step: the controller's decision through the write guards to what is written now.

The same step drives the simulator in tests and the real write path in Home Assistant. Heating
on/off goes through a guard of its own, as 1 and 0; when the write path cannot switch heating on
and off, "off" is written as a low setpoint. A setpoint entity with a step gets its value on its
grid inside the limits before the guard compares it (P-15, P-98).

Decision 6's classes are the guards'; the loop adds what spans both targets. Both falling back
together — a gateway reset loses both overrides — is one lost command; three within a day raise
"commands lost", never a hold. A target ignored from the start is not written again this
session, while the other goes on; but heating on/off ignored from the start with "off" among what
it did not take leaves the plugin unable to switch heating off: at the next step control is
latched and handed back (``HEATING_OFF_IGNORED``, the user's answer O), whatever alarm reaction is
stored — and so with "on" among what it did not take (``HEATING_ON_IGNORED``, decision 4 of
0.2.3): the plugin cannot make the boiler heat, and a switch never written again would leave VT's
later "off" unwritten too. Where "off" is the low setpoint itself (EMS-ESP's 0, I6), the setpoint
ignored from the start with "off" among what it did not take latches the same way. Once a guard
has found another controller, every write stops — the setpoint and heating on/off alike: the
plugin never fights it. That lasts one step: an outside
change always hands back (S-11), so the next step latches and steps aside. A hand-back is passed
on as it is — the guards never hold it back, and it names no target to leave out: the control
unit makes the whole safe hand-back, over the other controller's value too (the user's answer
H). The guards keep their memory across it (P-06): a hand-back inside a session resets only
what was sent.

On the relay path (class 3, X8) there is no setpoint and no heating switch: the loop plans no
guard write and hands heating on/off to the relay rule (``core.relay``), whose lost commands count
toward "commands lost" like the guards', whose "off" or "on" ignored from the start blocks control
as the heating switch's does (answer O applied to relays; decision 4 of 0.2.3) — and so does its
"off" no longer taken in the session (decision 6 of 0.2.3) — and whose finding another controller
stops every write until the next step steps aside.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace

from .controller import ControlConfig, ControlDecision, ControlInputs, ControlState, decide
from .guards import (
    NO_CONTEXT,
    GuardConfig,
    GuardContext,
    GuardEvent,
    GuardResult,
    GuardState,
    WriteAction,
    WriteKind,
    WriteType,
    add_loss,
    after_hand_back,
    confirmation_missing,
    for_new_session,
    losses_warning,
    plan_write,
    value_not_shown,
)
from .limits import Grid, write_bounds
from .relay import (
    RelayConfig,
    RelaySeen,
    RelayState,
    RelayWrite,
    after_hand_back_relay,
    plan_relay,
    relay_for_new_session,
    relay_write_ignored,
)

DEFAULT_OFF_SETPOINT = 10.0
ON, OFF = 1.0, 0.0  # heating on/off as the guard sees it
# The latch's cause when heating on/off was ignored from the start with "off" among what it did
# not take (answer O): blocked until the user switches control off and on.
HEATING_OFF_IGNORED = "heating_off_ignored"
# The latch's cause when heating on/off was ignored from the start with "on", not "off", among what
# it did not take (decision 4 of 0.2.3, SB-03): the plugin cannot make the boiler heat — blocked
# until the user switches control off and on, as answer O.
HEATING_ON_IGNORED = "heating_on_ignored"
# The latch's cause when a relay that had taken commands stopped taking "off" in the session
# (decision 6 of 0.2.3, SB-06): blocked until the user switches control off and on, as answer O.
RELAY_OFF_NOT_TAKEN = "relay_off_not_taken"
SETPOINT, HEATING, RELAY = "setpoint", "heating", "relay"  # the targets, as the alarms name them
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
    # The relay path (X8): heating on/off through the relay rule, and nothing else written.
    relay: RelayConfig | None = None


@dataclass(frozen=True, slots=True)
class LoopState:
    control: ControlState = field(default_factory=ControlState)
    setpoint: GuardState = field(default_factory=GuardState)
    switch: GuardState = field(default_factory=GuardState)
    # Lost commands within the last day, (time, target): the warning "commands lost".
    losses: tuple[tuple[float, str], ...] = ()
    losses_warned: bool = False
    relay: RelayState = field(default_factory=RelayState)  # the relay path's memory (X8)


@dataclass(frozen=True, slots=True)
class LoopOutput:
    decision: ControlDecision
    setpoint: WriteAction | None = None  # setpoint to write now
    heating: WriteAction | None = None  # heating on/off to write now, as 1 or 0
    hand_back: bool = False  # give control back now
    events: tuple[GuardEvent, ...] = ()
    heating_on: bool | None = None  # the logical heating state now commanded
    blocked: bool = False  # another controller has the boiler: nothing is written
    ignored: tuple[str, ...] = ()  # targets ignored from the start (``SETPOINT``, ``HEATING``)
    unconfirmed: tuple[str, ...] = ()  # targets whose read-back has been missing for long
    # Targets whose value the read-back has not shown for long, showing another (Z4R2-03): the
    # setpoint only — reported, never judged by itself.
    not_shown: tuple[str, ...] = ()
    commands_lost: bool = False  # the warning: commands keep getting lost
    relay: RelayWrite | None = None  # the relay path: what to write to the relay now
    relay_unreachable: bool = False  # the relay out of reach for five minutes (its alarm)
    relay_restart: bool = False  # an untraced restart answered: stored at once (answer N)

    @property
    def ch_enable(self) -> bool | None:
        """Heating on/off to write now."""
        return None if self.heating is None else self.heating.value == ON


def _level(on: bool | None) -> float | None:
    return None if on is None else (ON if on else OFF)


def after_hand_back_loop(state: LoopState, control: ControlState) -> LoopState:
    """A hand-back inside a session: the guards keep their memory (P-06), the losses too, and
    so does the relay rule."""
    return replace(
        state,
        control=control,
        setpoint=after_hand_back(state.setpoint),
        switch=after_hand_back(state.switch),
        relay=after_hand_back_relay(state.relay),
    )


def new_session(state: LoopState, now: float) -> LoopState:
    """A new session: everything afresh but each guard's one rewrite, kept for its day, the
    boiler link's window and the zones' watch — facts about the link and the zones, not the
    session: switching control off and on does not make a lost link fresh (X2), nor start the
    recognition period again or drop a zone's last answer in its grace (decision 3) — and the
    comfort correction's outdoor readings and starts baseline (rules 3 and 5, decision 11 of
    0.2.3): the weather's last hour stays known, and a new session's rise is judged against the
    hours before the last one began until it has stayed at 0 for the window."""
    control = state.control
    return LoopState(
        control=ControlState(
            link=control.link,
            link_unreported=control.link_unreported,
            zones=control.zones,
            starts_baseline=control.starts_baseline,
            outdoor_seen=control.outdoor_seen,
        ),
        setpoint=for_new_session(state.setpoint, now),
        switch=for_new_session(state.switch, now),
        # The relay's one rewrite and its restarts, each for its day (answers C, N).
        relay=relay_for_new_session(state.relay, now),
    )


def _outputs(
    state: LoopState, config: LoopConfig, now: float
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """The targets ignored from the start, those whose confirmation is missing, and those whose
    value the read-back does not show (Z4R2-03)."""
    guards = [(SETPOINT, state.setpoint)]
    if config.ch_writes:
        guards.append((HEATING, state.switch))
    ignored = tuple(name for name, guard in guards if guard.ignored)
    unconfirmed = tuple(name for name, guard in guards if confirmation_missing(guard, now))
    not_shown = tuple(name for name, guard in guards if value_not_shown(guard, now))
    return ignored, unconfirmed, not_shown


def _gridded(value: float, grid: Grid | None, config: LoopConfig, off: bool) -> float | None:
    """A setpoint on the entity's grid: inside the limits for heating, never above itself for
    "off" (it must stay below the lowest water temperature). ``None``: no grid value fits."""
    if grid is None:
        return value
    if off:
        return grid.put(value, None, value)
    control = config.control
    low, high = write_bounds(
        control.limits, control.circuit_max, control.boiler_max, control.circuit_floor
    )
    return grid.put(value, low, high)


def loop_step(
    state: LoopState,
    inputs: ControlInputs,
    confirmed_setpoint: float | None,
    config: LoopConfig,
    confirmed_heating: bool | None = None,
    *,
    setpoint_context: GuardContext = NO_CONTEXT,
    heating_context: GuardContext = NO_CONTEXT,
    grid: Grid | None = None,
    relay_seen: RelaySeen | None = None,
) -> tuple[LoopState, LoopOutput]:
    """One step. ``setpoint_context``, ``heating_context``: what each guard knows beside its
    read-back — the trace of an outage, the thermostat's own request, hot water, a target back
    from unavailable, the last command stored. ``grid``: the setpoint entity's grid, if any.
    ``relay_seen``: the relay as Home Assistant shows it (the relay path; none: not seen)."""
    if config.relay is not None:
        return _relay_step(state, inputs, config, config.relay, relay_seen or RelaySeen())
    now = inputs.now
    if config.ch_writes:
        # The plugin can no longer switch heating off (answer O), or cannot make the boiler heat
        # (decision 4 of 0.2.3): latched and handed back, whatever alarm reaction is stored.
        inputs = _ignored_latch(inputs, state.switch.off_ignored, state.switch.on_ignored)
    else:
        # "Off" is the setpoint itself (EMS-ESP's 0, I6): ignored from the start, the plugin
        # can no longer switch heating off either — answer O. Only heat ignored stays the
        # ignored write it was.
        off_value = _gridded(config.off_setpoint, grid, config, True)
        inputs = _ignored_latch(inputs, _off_among_ignored(state.setpoint, off_value), False)
    if state.setpoint.clip is not None and not inputs.clipped:
        inputs = replace(inputs, clipped=True)
    warned = losses_warning(state.losses, now, state.losses_warned)
    state = replace(state, losses_warned=warned)
    control, decision = decide(state.control, inputs, config.control)
    if decision.hand_back:
        # Whole, whatever a guard found: no target is left out, the one another controller
        # holds included (the user's answer H).
        kept = after_hand_back_loop(state, control)
        ignored, unconfirmed, not_shown = _outputs(kept, config, now)
        return kept, LoopOutput(
            decision,
            hand_back=True,
            ignored=ignored,
            unconfirmed=unconfirmed,
            not_shown=not_shown,
            commands_lost=warned,
        )
    blocked = state.setpoint.blocked is not None or state.switch.blocked is not None
    if decision.command is None or blocked:
        waiting = replace(state, control=control)
        ignored, unconfirmed, not_shown = _outputs(waiting, config, now)
        return waiting, LoopOutput(
            decision,
            blocked=blocked,
            ignored=ignored,
            unconfirmed=unconfirmed,
            not_shown=not_shown,
            commands_lost=warned,
        )

    command = decision.command
    off = command.ch_enable is False
    off_value = _gridded(config.off_setpoint, grid, config, True)
    if config.ch_writes:
        heat = plan_write(
            state.switch,
            _level(command.ch_enable),
            _level(confirmed_heating),
            now,
            config.switch_guard,
            heating_context,
        )
        desired: float | None = command.setpoint
        off = False
    else:
        heat = GuardResult(state.switch)
        # A water path's command always carries its setpoint; without one nothing is written.
        water = command.setpoint
        heating_value = None if water is None else _gridded(water, grid, config, False)
        desired = off_value if off else heating_value
    if config.ch_writes and desired is not None:
        desired = _gridded(desired, grid, config, False)
    planned = plan_write(
        state.setpoint, desired, confirmed_setpoint, now, config.setpoint_guard, setpoint_context
    )
    events = (*planned.events, *heat.events)
    losses = state.losses
    if planned.lost:
        losses = add_loss(losses, now, SETPOINT)
    if heat.lost:
        losses = add_loss(losses, now, HEATING)
    warned = losses_warning(losses, now, warned)
    if planned.state.blocked is not None or heat.state.blocked is not None:
        # Another controller: every write stops, and a write planned for the other target in
        # this step is not made. The outside change it reports steps aside at the next step.
        setpoint = planned.state if planned.state.blocked is not None else state.setpoint
        switch = heat.state if heat.state.blocked is not None else state.switch
        stopped = LoopState(control, setpoint, switch, losses, warned)
        ignored, unconfirmed, not_shown = _outputs(stopped, config, now)
        return stopped, LoopOutput(
            decision,
            events=events,
            blocked=True,
            ignored=ignored,
            unconfirmed=unconfirmed,
            not_shown=not_shown,
            commands_lost=warned,
        )

    heating = heat.action
    recovered = planned.action is not None and planned.action.kind in (
        WriteKind.REWRITE,
        WriteKind.RESEND,
    )
    if (
        config.ch_writes
        and recovered
        and heating is None
        and heat.state.written is not None
        and not heat.state.ignored
    ):
        # A setpoint recovered is sent with heating on/off: a PIC reset loses CS and CH
        # together (CH= is held, not lapsing — X6), and "off" above all must not stay lost.
        heating = WriteAction(heat.state.written, WriteKind.RESEND)
    if config.ch_writes:
        heating_on = None if heat.state.written is None else heat.state.written == ON
    else:
        written = planned.state.written
        heating_on = None if written is None else written != off_value
    new = LoopState(control, planned.state, heat.state, losses, warned)
    ignored, unconfirmed, not_shown = _outputs(new, config, now)
    return new, LoopOutput(
        decision,
        planned.action,
        heating,
        False,
        events,
        heating_on,
        ignored=ignored,
        unconfirmed=unconfirmed,
        not_shown=not_shown,
        commands_lost=warned,
    )


def _off_among_ignored(setpoint: GuardState, off_value: float | None) -> bool:
    """Whether the setpoint guard found its target ignoring writes from the start with "off" —
    sent as a low setpoint — among the values it did not take."""
    return (
        setpoint.ignored
        and off_value is not None
        and any(math.isclose(value, off_value, abs_tol=0.01) for value in setpoint.ignored_values)
    )


def _ignored_latch(inputs: ControlInputs, off: bool, on: bool) -> ControlInputs:
    """Heating on/off — the heating switch or the relay — ignored from the start: its cause among
    the alarms that hand back, "off" first (answer O: the plugin can no longer switch heating
    off), else "on" (decision 4 of 0.2.3: it cannot make the boiler heat); unchanged without
    either."""
    cause = HEATING_OFF_IGNORED if off else HEATING_ON_IGNORED if on else None
    alarms = inputs.hand_back_alarms
    if cause is None or cause in alarms:
        return inputs
    return replace(inputs, hand_back_alarms=(*alarms, cause))


def _relay_step(
    state: LoopState,
    inputs: ControlInputs,
    config: LoopConfig,
    relay: RelayConfig,
    seen: RelaySeen,
) -> tuple[LoopState, LoopOutput]:
    """The relay path's step: the controller's decision, then the relay rule — followed at every
    step, whatever holds control, for the relay's reachability and its alarm."""
    now = inputs.now
    # The plugin can no longer switch heating off — "off" ignored from the start (answer O
    # applied to relays), or no longer taken in the session (decision 6 of 0.2.3) — or cannot
    # make the boiler heat — "on" ignored from the start (decision 4 of 0.2.3): latched and
    # handed back, whatever alarm reaction is stored.
    inputs = _ignored_latch(inputs, state.relay.off_ignored, state.relay.on_ignored)
    if state.relay.off_not_taken and RELAY_OFF_NOT_TAKEN not in inputs.hand_back_alarms:
        inputs = replace(inputs, hand_back_alarms=(*inputs.hand_back_alarms, RELAY_OFF_NOT_TAKEN))
    warned = losses_warning(state.losses, now, state.losses_warned)
    state = replace(state, losses_warned=warned)
    control, decision = decide(state.control, inputs, config.control)
    if decision.hand_back:
        # Nothing new for the relay: its hand-back (the rest state) is the control unit's.
        followed = plan_relay(state.relay, None, seen, now, relay)
        kept = after_hand_back_loop(replace(state, relay=followed.state), control)
        return kept, LoopOutput(
            decision,
            hand_back=True,
            ignored=(RELAY,) if relay_write_ignored(kept.relay) else (),
            commands_lost=warned,
            relay_unreachable=followed.unreachable,
        )
    desired = None if decision.command is None else decision.command.ch_enable
    result = plan_relay(state.relay, desired, seen, now, relay)
    losses = add_loss(state.losses, now, RELAY) if result.lost else state.losses
    warned = losses_warning(losses, now, warned)
    new = replace(state, control=control, relay=result.state, losses=losses, losses_warned=warned)
    return new, LoopOutput(
        decision,
        events=result.events,
        heating_on=result.state.written,
        blocked=result.state.blocked,
        ignored=(RELAY,) if relay_write_ignored(result.state) else (),
        commands_lost=warned,
        relay=result.write,
        relay_unreachable=result.unreachable,
        relay_restart=result.restart,
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
