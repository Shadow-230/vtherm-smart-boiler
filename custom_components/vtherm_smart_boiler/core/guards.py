"""Write guards: what may actually be written, whatever the controller asks for.

The guards are fixed; their values are options. For a setpoint:

- how often it is written follows the write type: an expiring override is repeated every
  keep-alive period; a persistent write (or an unknown one) only on a change of at least the
  minimum change and within a daily cap; a value the gateway holds, on change only;
- a new value no sooner than the minimum change interval, and never more than a few writes a
  minute, repeats included (a guard against runaway loops);
- every write is read back: not confirmed within the timeout → reported as ignored, never assumed
  applied; changed from outside after it was confirmed → written again once, then blocked and
  reported, also when that one rewrite is not confirmed within the timeout — the plugin does not
  fight another controller.

For heating on/off: minimum on and off times and a cap on switchings per hour.

A hand-back write is not planned here: nothing holds it back.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

MINUTE = 60.0
HOUR = 3600.0
DAY = 86400.0


class WriteType(StrEnum):
    EXPIRING = "expiring"  # an override that lapses unless repeated
    PERSISTENT = "persistent"  # stored in the boiler's memory: every write wears it
    HELD = "held"  # kept by the gateway and sent on by itself: no repeat, no wear
    UNKNOWN = "unknown"  # treated as persistent


class WriteKind(StrEnum):
    CHANGE = "change"
    KEEPALIVE = "keepalive"
    REWRITE = "rewrite"


class GuardEvent(StrEnum):
    IGNORED = "ignored"
    OUTSIDE_CHANGE = "outside_change"
    DAILY_CAP = "daily_cap"


@dataclass(frozen=True, slots=True)
class SetpointGuardConfig:
    write_type: WriteType = WriteType.UNKNOWN
    keepalive_s: float = 30.0
    min_change_interval_s: float = MINUTE
    max_writes_per_minute: int = 4
    min_change: float = 1.0  # persistent and unknown writes only
    daily_cap: int = 48  # persistent and unknown writes only
    confirm_timeout_s: float = 2 * MINUTE
    tolerance: float = 0.5

    def __post_init__(self) -> None:
        if self.keepalive_s <= 0 or self.confirm_timeout_s <= 0:
            raise ValueError("keep-alive and confirmation timeout must be positive")
        if self.max_writes_per_minute < 2:
            raise ValueError("at least two writes a minute must be allowed (keep-alive)")
        if self.daily_cap < 1 or self.min_change < 0 or self.tolerance < 0:
            raise ValueError("daily cap, minimum change and tolerance must be sensible")

    @property
    def wears(self) -> bool:
        return self.write_type in (WriteType.PERSISTENT, WriteType.UNKNOWN)


@dataclass(frozen=True, slots=True)
class SetpointGuardState:
    written: float | None = None
    written_at: float | None = None
    sent_at: float | None = None  # when the current value was first sent (keep-alives aside)
    changed_at: float | None = None  # when a different value was last written
    confirmed_at: float | None = None  # when the device confirmed the written value
    history: tuple[float, ...] = ()  # write times of the last day
    rewritten: bool = False  # the one rewrite after an outside change is used
    ignored_reported: bool = False
    blocked: GuardEvent | None = None  # no more writes until the guard is reset


@dataclass(frozen=True, slots=True)
class WriteAction:
    value: float
    kind: WriteKind


@dataclass(frozen=True, slots=True)
class GuardResult:
    state: SetpointGuardState
    action: WriteAction | None = None
    events: tuple[GuardEvent, ...] = ()


def _matches(a: float | None, b: float | None, tolerance: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def plan_setpoint(
    state: SetpointGuardState,
    desired: float | None,
    confirmed: float | None,
    now: float,
    config: SetpointGuardConfig,
) -> GuardResult:
    """What to write for a setpoint now, given what the device confirms (``None``: unknown)."""
    window = DAY if config.wears else MINUTE
    history = tuple(t for t in state.history if now - t < window)
    state = replace(state, history=history)
    events: list[GuardEvent] = []

    if state.written is not None and _matches(confirmed, state.written, config.tolerance):
        if state.confirmed_at is None:
            state = replace(state, confirmed_at=now)
    elif (
        state.sent_at is not None
        and state.confirmed_at is None
        and not state.ignored_reported
        and now - state.sent_at > config.confirm_timeout_s
    ):
        if state.rewritten:
            # The one rewrite after an outside change did not hold: another controller keeps
            # its value. Stop and report rather than fight it.
            events.append(GuardEvent.OUTSIDE_CHANGE)
            state = replace(state, ignored_reported=True, blocked=GuardEvent.OUTSIDE_CHANGE)
        else:
            events.append(GuardEvent.IGNORED)
            state = replace(state, ignored_reported=True)

    if state.blocked is not None or desired is None:
        return GuardResult(state, None, tuple(events))

    outside = (
        state.confirmed_at is not None
        and confirmed is not None
        and not _matches(confirmed, state.written, config.tolerance)
    )
    if outside:
        if state.rewritten:
            events.append(GuardEvent.OUTSIDE_CHANGE)
            return GuardResult(
                replace(state, blocked=GuardEvent.OUTSIDE_CHANGE), None, tuple(events)
            )
        value = state.written
        assert value is not None
        return _write(replace(state, rewritten=True), value, WriteKind.REWRITE, now, config, events)

    if state.written is None:
        return _write(state, desired, WriteKind.CHANGE, now, config, events)
    differs = not _matches(desired, state.written, config.tolerance)
    if differs and config.wears and abs(desired - state.written) < config.min_change:
        differs = False
    too_soon = (
        state.changed_at is not None and now - state.changed_at < config.min_change_interval_s
    )
    if differs and not too_soon:
        if config.wears and len(history) >= config.daily_cap:
            events.append(GuardEvent.DAILY_CAP)
            return GuardResult(replace(state, blocked=GuardEvent.DAILY_CAP), None, tuple(events))
        return _write(state, desired, WriteKind.CHANGE, now, config, events)
    # No change now (none wanted, or it must wait): an expiring override still needs its
    # keep-alive, or it would lapse while the change waits.
    if (
        config.write_type is WriteType.EXPIRING
        and state.written_at is not None
        and now - state.written_at >= config.keepalive_s
    ):
        return _write(state, state.written, WriteKind.KEEPALIVE, now, config, events)
    return GuardResult(state, None, tuple(events))


def _write(
    state: SetpointGuardState,
    value: float,
    kind: WriteKind,
    now: float,
    config: SetpointGuardConfig,
    events: list[GuardEvent],
) -> GuardResult:
    recent = [t for t in state.history if now - t < MINUTE]
    if len(recent) >= config.max_writes_per_minute:
        return GuardResult(state, None, tuple(events))
    changed = kind is WriteKind.CHANGE and (
        state.written is None or not _matches(value, state.written, config.tolerance)
    )
    new_state = replace(
        state,
        written=value,
        written_at=now,
        sent_at=now if changed or kind is WriteKind.REWRITE else state.sent_at,
        changed_at=now if changed else state.changed_at,
        confirmed_at=None if changed or kind is WriteKind.REWRITE else state.confirmed_at,
        ignored_reported=False if changed else state.ignored_reported,
        rewritten=False if changed else state.rewritten,
        history=(*state.history, now),
    )
    return GuardResult(new_state, WriteAction(value, kind), tuple(events))


class SwitchHold(StrEnum):
    MIN_ON = "min_on"
    MIN_OFF = "min_off"
    SWITCH_BUDGET = "switch_budget"


@dataclass(frozen=True, slots=True)
class SwitchGuardConfig:
    min_on_s: float = 5 * MINUTE
    min_off_s: float = 5 * MINUTE
    max_switches_per_hour: int = 6
    keepalive_s: float | None = None  # repeat the same state this often, for expiring overrides

    def __post_init__(self) -> None:
        if self.min_on_s < 0 or self.min_off_s < 0 or self.max_switches_per_hour < 1:
            raise ValueError("minimum times must not be negative and one switch an hour allowed")


@dataclass(frozen=True, slots=True)
class SwitchGuardState:
    written: bool | None = None
    written_at: float | None = None
    changed_at: float | None = None
    switches: tuple[float, ...] = ()


@dataclass(frozen=True, slots=True)
class SwitchResult:
    state: SwitchGuardState
    write: bool | None = None  # the state to write now, if any
    hold: SwitchHold | None = None


def plan_switch(
    state: SwitchGuardState, desired: bool | None, now: float, config: SwitchGuardConfig
) -> SwitchResult:
    """Whether to switch heating on or off now."""
    switches = tuple(t for t in state.switches if now - t < HOUR)
    state = replace(state, switches=switches)
    if desired is None:
        return SwitchResult(state)
    if state.written is None:
        return SwitchResult(
            replace(state, written=desired, written_at=now, changed_at=now), desired
        )
    if desired == state.written:
        if (
            config.keepalive_s is not None
            and state.written_at is not None
            and now - state.written_at >= config.keepalive_s
        ):
            return SwitchResult(replace(state, written_at=now), desired)
        return SwitchResult(state)
    since = now - state.changed_at if state.changed_at is not None else None
    if since is not None:
        if state.written and since < config.min_on_s:
            return SwitchResult(state, None, SwitchHold.MIN_ON)
        if not state.written and since < config.min_off_s:
            return SwitchResult(state, None, SwitchHold.MIN_OFF)
    if len(switches) >= config.max_switches_per_hour:
        return SwitchResult(state, None, SwitchHold.SWITCH_BUDGET)
    new_state = SwitchGuardState(desired, now, now, (*switches, now))
    return SwitchResult(new_state, desired)
