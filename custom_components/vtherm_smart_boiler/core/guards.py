"""Write guards: what may actually be written, whatever the controller asks for, and what a change
the read-back shows means (decision 6, with the user's answers E, H and O of 2026-09-27).

One guard per write target — the flow setpoint, and heating on/off as 1 and 0. The guards are
fixed; their values are options:

- nothing goes to the boiler's persistent memory: a target declared persistent, or of unknown
  write type, is never written (the configuration keeps control off for it anyway);
- how often it is written follows the write type: an expiring override is repeated every
  keep-alive period; a value the device holds is sent on a change, again every five minutes with
  no echo required, and at once when the target comes back from unavailable or unknown;
- a write-rate guard against a runaway loop: a write repeated within one control step waits for
  the next one — failed attempts count too, and nothing waits longer;
- every write is read back where something echoes it; a target without an echo is never judged,
  only shown unverified. A read-back unknown, unavailable or missing is never judged either: it is
  a trace of an outage, and after five minutes while the plugin writes it is reported
  ("confirmation missing"), never a hand-back by itself.

Every change the read-back shows falls into one of four classes (``classify``), and each class has
one reaction (``REACTIONS``). The heating switch — two values — follows the same classes as the
setpoint (S-40, answer E):

- **lost command** — back at the value from before the plugin (the baseline: the first known
  read-back of the session that is not a value the plugin sent, nor its last command; with an
  OpenTherm thermostat, also the thermostat's own request where that field is mapped) with a trace
  of an outage within the five minutes before; a held target's first value after it came back;
  a single such fall-back without a trace, or one a send explains (it comes before the plugin's
  latest send was read back, or within 120 s of a new value). Sent again at once and counted:
  frequent losses raise a warning, never a hold;
- **ignored from the start** — never read back as the plugin's for longer than 120 s after each of
  the session's first three sends (an attempt with a trace of an outage in it does not count): the
  target is not written again this session, keep-alives included; the other target goes on; tried
  again at the next session. Where it is the heating switch and "off" is among the values it did
  not take, the loop blocks control and hands back (answer O);
- **clipped** — one lower value whatever the plugin sends, across at least two sent values 1 K
  apart: the boiler's own limit, shown, never learned as a limit;
- **another controller** — a second fall-back without a trace within an hour that no send
  explains, or any other value held for two steps after a confirmation, or 120 s after the first
  send not confirmed: written again once, then — a second such change within a day of it, or the
  rewrite not read back within 120 s — the guard blocks and reports; the plugin steps aside with
  the whole safe hand-back and never fights it. "Any other value" includes the plugin's previous
  one once the value that replaced it has been read back (Z4-01, Z4R-01): for heating on/off, the
  only other state once the plugin has switched both ways.

Not judged: a difference seen for one step; the plugin's previous value until the value that
replaced it has been read back — a late echo, or the device holding it, the boiler's own limit
(judged "clipped" once the plugin has sent values 1 K apart) — shown "not confirmed" once the
timeout has passed; a hot-water draw and the 120 s after it; the plugin's own expiring override
lapsing after more than 60 s of its silence (sent again); a write of the plugin's own that failed
(sent again). Keep-alive repeats and refreshes are not rewrites. A value shown as confirmed is one
the read-back still shows: another value seen, even for one step, shows "not confirmed".

The guard's memory — the baseline, the block, its counters, the class "ignored from the start",
the clip — lasts the session, across hand-backs inside it (``after_hand_back``); the one rewrite is
remembered for its day, across sessions too (``for_new_session``). Heating on/off follows what the
controller asks at once: nothing counted or timed holds it against VT (``SCOPE.md`` principle 12)
beyond the one-step write-rate guard.

A hand-back write is not planned here: nothing holds it back.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields, replace
from enum import StrEnum
from types import MappingProxyType
from typing import Any

DAY = 86400.0
HOUR = 3600.0
REWRITE_WINDOW_S = DAY  # after the one rewrite, another change this soon is not rewritten
# Writes to one target at least this far apart: one per control step (10 s), whatever the
# timer's jitter or a step run early (switching control on).
MIN_WRITE_INTERVAL_S = 5.0
CONFIRM_TIMEOUT_S = 120.0  # a send read back within this; kept as today (reason to confirm)
TOLERANCE_K = 0.5  # a read-back this close shows a value; kept as today
# Decision 6 with the user's answer E (2026-09-27), decided:
FALL_BACK_WINDOW_S = HOUR  # a second fall-back without a trace this soon: another controller
EXPLAINED_S = 120.0  # a fall-back this soon after a new value is explained by it
# Provisional, K4 — each the most cautious value found:
TRACE_WINDOW_S = 300.0  # an outage this recent is a trace
STEADY_STEPS = 2  # another value judged once held this many steps
CLIP_SPREAD_K = 1.0  # a clip needs sent values at least this far apart
START_ATTEMPTS = 3  # failed attempts of the start phase before "ignored from the start"
DRAW_QUIET_S = 120.0  # nothing judged during a hot-water draw and this long after it
CONFIRMATION_MISSING_S = 300.0  # a read-back unknown this long while writing is reported
HELD_REFRESH_S = 300.0  # a held value is sent again this often, with no echo required
JOINT_FALL_BACK_S = 20.0  # both targets falling back this close together: one loss
LOSSES_FOR_WARNING = 3  # lost commands within ``LOSS_WINDOW_S`` that raise "commands lost"
LOSS_WINDOW_S = DAY  # ... and the warning clears after this long without a loss


class WriteType(StrEnum):
    EXPIRING = "expiring"  # an override that lapses unless repeated
    PERSISTENT = "persistent"  # stored in the boiler's memory: every write wears it; never written
    HELD = "held"  # kept by the device: sent on a change, refreshed, no wear
    UNKNOWN = "unknown"  # may be persistent: never written


class WriteKind(StrEnum):
    CHANGE = "change"
    KEEPALIVE = "keepalive"  # a repeat or a held refresh: not a change, never judged
    REWRITE = "rewrite"
    RESEND = "resend"  # the same value again: after a failed write, a lost command or a lapse


class GuardEvent(StrEnum):
    IGNORED = "ignored"  # ignored from the start
    OUTSIDE_CHANGE = "outside_change"  # another controller: the guard blocks


class Confirmation(StrEnum):
    """Where the value last written stands with the device."""

    CONFIRMED = "confirmed"
    WAITING = "waiting"  # sent, not confirmed yet
    NOT_CONFIRMED = "not_confirmed"  # not confirmed within the timeout, or ignored from the start
    CHANGED_FROM_OUTSIDE = "changed_from_outside"  # another controller: writes stopped
    UNVERIFIED = "unverified"  # nothing echoes the value
    CLIPPED = "clipped"  # held lower by the boiler: its own limit


class ChangeClass(StrEnum):
    """What a step's read-back means (``classify``)."""

    NOT_JUDGED = "not_judged"
    CONFIRMED = "confirmed"
    OWN_LAPSE = "own_lapse"  # the plugin's own expiring override lapsed in its silence
    LOST_COMMAND = "lost_command"
    FAILED_ATTEMPT = "failed_attempt"  # the start phase: sent again, the next attempt
    IGNORED_FROM_START = "ignored_from_start"
    CLIPPED = "clipped"
    ANOTHER_CONTROLLER = "another_controller"
    # Never read back since a send, for longer than the timeout, after the start phase: a relay's
    # "not confirmed" (X8, ``core.relay``), sent again at its next check.
    NOT_CONFIRMED = "not_confirmed"


class Reaction(StrEnum):
    NONE = "none"  # nothing beyond the usual writes
    RESEND = "resend"  # sent again at once
    STOP = "stop"  # not written again this session
    REWRITE_ONCE = "rewrite_once"  # written again once a day; then the guard blocks


REACTIONS: Mapping[ChangeClass, Reaction] = MappingProxyType(
    {
        ChangeClass.NOT_JUDGED: Reaction.NONE,
        ChangeClass.CONFIRMED: Reaction.NONE,
        ChangeClass.CLIPPED: Reaction.NONE,
        ChangeClass.OWN_LAPSE: Reaction.RESEND,
        ChangeClass.LOST_COMMAND: Reaction.RESEND,
        ChangeClass.FAILED_ATTEMPT: Reaction.RESEND,
        ChangeClass.IGNORED_FROM_START: Reaction.STOP,
        ChangeClass.ANOTHER_CONTROLLER: Reaction.REWRITE_ONCE,
        ChangeClass.NOT_CONFIRMED: Reaction.NONE,  # a relay's next check sends it again
    }
)


class ReadKind(StrEnum):
    """What a known read-back shows, against the plugin's values and the fall-back set."""

    OURS = "ours"  # the value written, or one sent within the confirmation timeout
    FALL_BACK = "fall_back"  # the baseline, or the thermostat's own value
    # The value written before the current one, while the current one has not been read back
    # since it replaced it: a late echo or the device holding it, not judged. Once the current one
    # has been read back, it is another value like any other (Z4-01, Z4R-01).
    PREVIOUS = "previous"
    OTHER = "other"


@dataclass(frozen=True, slots=True)
class GuardConfig:
    write_type: WriteType = WriteType.UNKNOWN
    keepalive_s: float = 30.0
    confirm_timeout_s: float = CONFIRM_TIMEOUT_S
    tolerance: float = TOLERANCE_K  # on/off as 1 and 0: any tolerance below 1
    min_interval_s: float = MIN_WRITE_INTERVAL_S
    read_back: bool = True  # False: nothing echoes the value; it is never judged
    two_valued: bool = False  # heating on/off: no clip, no thermostat's own value
    refresh_s: float | None = HELD_REFRESH_S  # a held value sent again this often (None: never)

    def __post_init__(self) -> None:
        if self.keepalive_s <= 0 or self.confirm_timeout_s <= 0:
            raise ValueError("keep-alive and confirmation timeout must be positive")
        if not 0 < self.min_interval_s < self.keepalive_s:
            raise ValueError("the write interval must be positive and below the keep-alive")
        if self.tolerance < 0:
            raise ValueError("the tolerance must not be negative")
        if self.refresh_s is not None and self.refresh_s <= self.min_interval_s:
            raise ValueError("the held refresh must be longer than the write interval")

    @property
    def writable(self) -> bool:
        """Only values that expire or that the device holds; nothing the boiler stores."""
        return self.write_type in (WriteType.EXPIRING, WriteType.HELD)


@dataclass(frozen=True, slots=True)
class GuardContext:
    """What a guard knows beside its read-back at a step (``None``: not known)."""

    # When the target, its read-back or another entity of the same device or gateway was last
    # unavailable, unknown or missing, or the device was last seen restarting.
    outage_at: float | None = None
    thermostat: float | None = None  # the OpenTherm thermostat's own request (the setpoint only)
    dhw: bool | None = None  # hot water now; unknown: the draw rule does not apply
    returned: bool = False  # the target came back from unavailable or unknown since the last step
    last_command: float | None = None  # the last command stored (V3): never a baseline


NO_CONTEXT = GuardContext()


@dataclass(frozen=True, slots=True)
class GuardState:
    # --- per send: reset at every hand-back (``after_hand_back``) ---
    written: float | None = None
    written_at: float | None = None  # the last write attempt, failed ones included
    sent_at: float | None = None  # when the current value was last sent (keep-alives aside)
    confirmed_at: float | None = None  # read back as the plugin's since that send
    previous: float | None = None  # the value written before the current one
    taken: bool = False  # the current value read back itself since it replaced ``previous``
    retry: bool = False  # the last write failed, or waited: send it again
    recent: tuple[tuple[float, float], ...] = ()  # (time, value) of sends within the timeout
    change_at: float | None = None  # the latest send of a new value
    unconfirmed_since: float | None = None  # the first send not read back since
    sent_low: float | None = None  # the lowest and highest value sent since then (the clip)
    sent_high: float | None = None
    late: bool = False  # not read back within the timeout of that first send
    foreign: float | None = None  # another value the read-back holds ...
    foreign_steps: int = 0  # ... for this many steps in a row
    fallen_at: float | None = None  # a fall-back judged: the value is being sent again
    rewrite_pending: bool = False  # the one rewrite not read back yet
    attempt_at: float | None = None  # the start phase's running attempt
    attempt_values: tuple[float, ...] = ()
    attempt_trace: bool = False  # a trace of an outage within it: it does not count
    held_since: float | None = None  # the read-back shows the plugin's value since
    last_kind: ReadKind | None = None  # what the last known read-back showed
    unknown_since: float | None = None  # the read-back unknown since
    # --- the session's memory: kept across hand-backs, reset at the session's end ---
    baseline: float | None = None  # the value from before the plugin
    sent_values: tuple[float, ...] = ()  # values sent, while the baseline is not known
    ever_confirmed: bool = False  # a value of the plugin's was read back in this session
    blocked: GuardEvent | None = None  # another controller: no more writes this session
    rewritten_at: float | None = None  # the one rewrite: kept for its day, across sessions too
    fallbacks: tuple[float, ...] = ()  # fall-backs without a trace, within the last hour
    start_done: bool = False  # the read-back held a sent value for the timeout
    failed_attempts: int = 0  # counted failed attempts of the start phase
    failed_values: tuple[float, ...] = ()  # the values those attempts sent
    ignored: bool = False  # ignored from the start: not written again this session
    ignored_values: tuple[float, ...] = ()  # the values it did not take
    clip: float | None = None  # held lower by the boiler: its own limit, shown only
    unknown_at: float | None = None  # the read-back last unknown: a trace of an outage
    draw_at: float | None = None  # hot water last seen

    @property
    def off_ignored(self) -> bool:
        """Heating on/off ignored from the start with "off" among what it did not take: the
        plugin can no longer switch heating off (answer O)."""
        return self.ignored and any(value == 0.0 for value in self.ignored_values)


@dataclass(frozen=True, slots=True)
class WriteAction:
    value: float
    kind: WriteKind


@dataclass(frozen=True, slots=True)
class GuardResult:
    state: GuardState
    action: WriteAction | None = None
    events: tuple[GuardEvent, ...] = ()
    lost: bool = False  # a lost command this step (the loss count)
    judged: ChangeClass = ChangeClass.NOT_JUDGED


@dataclass(frozen=True, slots=True)
class Observation:
    """A step's read-back as a guard sees it: what it shows and what surrounds it."""

    kind: ReadKind | None  # None: unknown, unavailable or missing
    trace: bool  # a trace of an outage within the trace window
    quiet: bool  # a hot-water draw now or within ``DRAW_QUIET_S``
    returned: bool  # the target, or its read-back, came back from unavailable or unknown
    fell: bool  # the read-back came into the fall-back set at this step


def _near(a: float | None, b: float | None, tolerance: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def trace_seen(outage_at: float | None, now: float, window: float = TRACE_WINDOW_S) -> bool:
    """A trace of an outage within ``window`` before ``now``; one seen later than now (the wall
    clock set back) counts."""
    return outage_at is not None and now - outage_at <= window


def write_failed(state: GuardState) -> GuardState:
    """The planned write did not go through: it is sent again at the next step. The attempt
    still counts for the write-rate guard."""
    return replace(state, retry=True)


def confirmation(state: GuardState, config: GuardConfig) -> Confirmation | None:
    """Where the value last written stands; ``None`` before the first write."""
    if state.blocked is not None:
        return Confirmation.CHANGED_FROM_OUTSIDE
    if state.written is None:
        return None
    if not config.read_back:
        return Confirmation.UNVERIFIED
    if state.ignored:
        return Confirmation.NOT_CONFIRMED
    if state.clip is not None:
        return Confirmation.CLIPPED
    if state.confirmed_at is not None:
        # Confirmed only while the read-back still shows it: another value seen now — not yet
        # judged, held one step — is not the plugin's (Z4-01).
        another = state.foreign is not None or state.last_kind is ReadKind.PREVIOUS
        return Confirmation.NOT_CONFIRMED if another else Confirmation.CONFIRMED
    return Confirmation.NOT_CONFIRMED if state.late else Confirmation.WAITING


def confirmation_missing(state: GuardState, now: float) -> bool:
    """The read-back unknown, unavailable or missing for ``CONFIRMATION_MISSING_S`` while the
    plugin writes (M11): information only."""
    return (
        state.written is not None
        and not state.ignored
        and state.unknown_since is not None
        and now - state.unknown_since >= CONFIRMATION_MISSING_S
    )


def after_hand_back(state: GuardState) -> GuardState:
    """A hand-back inside the session: the per-send fields go; the session's memory — the
    baseline, the block, the counters, the class "ignored from the start", the clip — and the
    one rewrite stay (P-06)."""
    memory = {
        name: getattr(state, name)
        for name in (
            "baseline",
            "sent_values",
            "ever_confirmed",
            "blocked",
            "rewritten_at",
            "fallbacks",
            "start_done",
            "failed_attempts",
            "failed_values",
            "ignored",
            "ignored_values",
            "clip",
            "unknown_at",
            "draw_at",
        )
    }
    return GuardState(**memory)


def for_new_session(state: GuardState, now: float) -> GuardState:
    """A new session (control switched off and on, the return by itself): everything starts
    afresh but the one rewrite, remembered for its day (provisional, K4)."""
    rewritten = state.rewritten_at
    keep = rewritten is not None and now - rewritten < REWRITE_WINDOW_S
    return GuardState(rewritten_at=rewritten if keep else None)


def add_loss(
    losses: Sequence[tuple[float, str]], now: float, target: str
) -> tuple[tuple[float, str], ...]:
    """One more lost command of ``target``; one of the other target within
    ``JOINT_FALL_BACK_S`` is the same loss (a gateway reset loses both overrides). Losses older
    than ``LOSS_WINDOW_S`` go."""
    kept = tuple((t, who) for t, who in losses if now - t < LOSS_WINDOW_S)
    if any(who != target and abs(now - t) <= JOINT_FALL_BACK_S for t, who in kept):
        return kept
    return (*kept, (now, target))


def losses_warning(losses: Sequence[tuple[float, str]], now: float, active: bool) -> bool:
    """The information alarm "commands lost": on at ``LOSSES_FOR_WARNING`` losses within
    ``LOSS_WINDOW_S``, off after ``LOSS_WINDOW_S`` without a loss. Never a hold."""
    times = [t for t, _who in losses]
    if sum(1 for t in times if now - t < LOSS_WINDOW_S) >= LOSSES_FOR_WARNING:
        return True
    return active and bool(times) and now - max(times) < LOSS_WINDOW_S


# --- a step --------------------------------------------------------------------------------


def plan_write(
    state: GuardState,
    desired: float | None,
    read_back: float | None,
    now: float,
    config: GuardConfig,
    context: GuardContext = NO_CONTEXT,
) -> GuardResult:
    """What to write to one target now, given what the device reads back (``None``: unknown,
    unavailable or missing) and what surrounds it (``context``)."""
    if not config.writable:
        return GuardResult(state)
    state = _clock(state, now, config)
    if not config.read_back:
        read_back = None  # nothing to judge: never ignored, never another controller
    state, seen = _observe(state, read_back, context, now, config)
    if state.blocked is not None or state.ignored or desired is None:
        return GuardResult(state)
    if state.retry and state.written is not None:
        # Our own write failed, or waited: what the device shows says nothing about others.
        return _send(state, desired, WriteKind.RESEND, now, config, seen.trace)
    judged = classify(state, read_back, seen, now, config)
    state, events, lost = _account(state, judged, read_back, seen, now)
    reaction = REACTIONS[judged]
    if reaction is Reaction.STOP:
        return GuardResult(state, None, events, lost, judged)
    if reaction is Reaction.REWRITE_ONCE:
        if state.rewritten_at is not None and now - state.rewritten_at < REWRITE_WINDOW_S:
            # A second change within a day of the one rewrite, or the rewrite not read back:
            # another controller keeps writing. Stop and report rather than fight it.
            events = (*events, GuardEvent.OUTSIDE_CHANGE)
            blocked = replace(state, blocked=GuardEvent.OUTSIDE_CHANGE)
            return GuardResult(blocked, None, events, lost, judged)
        state = replace(state, rewritten_at=now, rewrite_pending=True)
        result = _send(state, desired, WriteKind.REWRITE, now, config, seen.trace)
        return replace(result, events=events, judged=judged)
    if reaction is Reaction.RESEND:
        result = _send(state, desired, WriteKind.RESEND, now, config, seen.trace)
        return replace(result, events=events, lost=lost, judged=judged)
    return _plan(state, desired, seen, now, config, events, judged)


def classify(
    state: GuardState,
    read_back: float | None,
    seen: Observation,
    now: float,
    config: GuardConfig,
) -> ChangeClass:
    """The class of a step's read-back — the one table of decision 6, in its order (``SCOPE.md``
    §7): unknown; confirmed; a draw; the plugin's own lapse; a held target back; the rewrite not
    read back; the fall-back set (the start phase's attempts, then lost command or another
    controller); the previous value while the value that replaced it has not been read back;
    clipped; another value held two steps — the previous one too, once its successor was read
    back."""
    if state.written is None or not config.read_back or read_back is None or seen.kind is None:
        return ChangeClass.NOT_JUDGED
    if seen.kind is ReadKind.OURS:
        return ChangeClass.CONFIRMED
    if seen.quiet:
        return ChangeClass.NOT_JUDGED
    if config.write_type is WriteType.EXPIRING and _lapsed(state, now, config):
        return ChangeClass.OWN_LAPSE
    if config.write_type is WriteType.HELD and seen.returned:
        return ChangeClass.LOST_COMMAND  # its first value after it came back is not judged
    if state.rewrite_pending and state.rewritten_at is not None:
        if now - state.rewritten_at >= config.confirm_timeout_s:
            return ChangeClass.ANOTHER_CONTROLLER  # the one rewrite did not hold
        if seen.kind is not ReadKind.FALL_BACK:
            return ChangeClass.NOT_JUDGED  # the rewrite may still take
    if seen.kind is ReadKind.FALL_BACK:
        if not state.start_done:
            return _start_phase(state, seen, now, config)
        return _fall_back(state, seen, now, config)
    if seen.kind is ReadKind.PREVIOUS:
        return ChangeClass.NOT_JUDGED
    if not config.two_valued and _clipped(state, read_back, config):
        return ChangeClass.CLIPPED
    if state.foreign_steps >= STEADY_STEPS and (
        state.confirmed_at is not None or _overdue(state, now, config)
    ):
        return ChangeClass.ANOTHER_CONTROLLER
    return ChangeClass.NOT_JUDGED


def _start_phase(
    state: GuardState, seen: Observation, now: float, config: GuardConfig
) -> ChangeClass:
    """The start phase: an attempt fails once the read-back fell back, or has not shown the
    plugin's value its timeout after the send; the third counted failure is "ignored from the
    start". An attempt with a trace of an outage in it does not count. Never another
    controller."""
    at = state.attempt_at
    overdue = at is not None and now - at >= config.confirm_timeout_s
    if not (seen.fell or overdue):
        return ChangeClass.NOT_JUDGED  # the send may still take
    counted = not (state.attempt_trace or seen.trace)
    if counted and state.failed_attempts + 1 >= START_ATTEMPTS:
        return ChangeClass.IGNORED_FROM_START
    return ChangeClass.FAILED_ATTEMPT


def _fall_back(
    state: GuardState, seen: Observation, now: float, config: GuardConfig
) -> ChangeClass:
    """After the start phase: a fall-back — it came into the fall-back set now, or the value
    sent has not been read back its timeout after the send — is a lost command with a trace of
    an outage; without one, the first within an hour or one a send explains is a lost command
    too, a second that no send explains is another controller (answer E)."""
    last = _latest(state.sent_at, state.fallen_at)
    waited = (
        state.confirmed_at is None and last is not None and now - last >= config.confirm_timeout_s
    )
    if not (seen.fell or waited):
        return ChangeClass.NOT_JUDGED
    if seen.trace or _explained(state, now) or not _recent_fall_back(state, now):
        return ChangeClass.LOST_COMMAND
    return ChangeClass.ANOTHER_CONTROLLER


def _explained(state: GuardState, now: float) -> bool:
    """A send explains a fall-back that comes before the plugin's latest send was read back, or
    within ``EXPLAINED_S`` of a send of a new value — not a keep-alive or a resend."""
    if state.confirmed_at is None:
        return True
    return state.change_at is not None and now - state.change_at <= EXPLAINED_S


def _recent_fall_back(state: GuardState, now: float) -> bool:
    return any(now - t <= FALL_BACK_WINDOW_S for t in state.fallbacks)


def _overdue(state: GuardState, now: float, config: GuardConfig) -> bool:
    """Not read back within the timeout of the first send not confirmed — later changes neither
    delay nor clear it (M9)."""
    since = state.unconfirmed_since
    return since is not None and now - since >= config.confirm_timeout_s


def _clipped(state: GuardState, read_back: float, config: GuardConfig) -> bool:
    """One value, held two steps, lower than every value sent since the first send not read
    back, across sent values at least ``CLIP_SPREAD_K`` apart: the boiler's own limit."""
    low, high = state.sent_low, state.sent_high
    return (
        state.confirmed_at is None
        and low is not None
        and high is not None
        and high - low >= CLIP_SPREAD_K
        and read_back < low - config.tolerance
        and state.foreign_steps >= STEADY_STEPS
    )


def _lapsed(state: GuardState, now: float, config: GuardConfig) -> bool:
    """An expiring override the plugin stopped repeating long enough for it to lapse."""
    return state.written_at is not None and now - state.written_at > 2 * config.keepalive_s


# --- what a step sees ------------------------------------------------------------------------


def _observe(
    state: GuardState,
    read_back: float | None,
    context: GuardContext,
    now: float,
    config: GuardConfig,
) -> tuple[GuardState, Observation]:
    """Follow the read-back: hot water, an unknown read-back, the baseline, a confirmation, the
    start phase's hold, another value held, a trace within the running attempt."""
    tolerance = config.tolerance
    if context.dhw:
        state = replace(state, draw_at=now)
    quiet = context.dhw is True or (
        state.draw_at is not None and now - state.draw_at <= DRAW_QUIET_S
    )
    if read_back is None:
        if config.read_back:
            state = replace(
                state,
                unknown_since=now if state.unknown_since is None else state.unknown_since,
                unknown_at=now,
                foreign=None,
                foreign_steps=0,
            )
        trace = trace_seen(_latest(context.outage_at, state.unknown_at), now)
        state = _note_attempt_trace(state, trace)
        return state, Observation(None, trace, quiet, context.returned, False)
    returned = context.returned or state.unknown_since is not None
    state = replace(state, unknown_since=None)
    trace = trace_seen(_latest(context.outage_at, state.unknown_at), now)
    ours = state.written is not None and _shows_ours(state, read_back, now, config)
    if not ours:
        state = _learn_baseline(state, read_back, context, quiet, config)
    kind = _kind(state, read_back, ours, context, trace, config)
    last = state.last_kind
    fell = kind is ReadKind.FALL_BACK and last is not None and last is not ReadKind.FALL_BACK
    if kind is ReadKind.OURS:
        held_since = now if state.held_since is None else state.held_since
        state = replace(
            state,
            confirmed_at=now if state.confirmed_at is None else state.confirmed_at,
            ever_confirmed=True,
            unconfirmed_since=None,
            sent_low=None,
            sent_high=None,
            late=False,
            clip=None,
            fallen_at=None,
            rewrite_pending=False,
            held_since=held_since,
            foreign=None,
            foreign_steps=0,
            # The value written itself, not an older one still within the timeout (``recent``).
            taken=state.taken or _near(read_back, state.written, tolerance),
        )
        if now - held_since >= config.confirm_timeout_s:
            # The value held: the start phase is over, and a target ignored from the start takes
            # it after all.
            state = replace(state, start_done=True, ignored=False, ignored_values=())
    else:
        state = replace(state, held_since=None)
        if kind is ReadKind.OTHER and not quiet:
            if _near(read_back, state.foreign, tolerance):
                state = replace(state, foreign_steps=state.foreign_steps + 1)
            else:
                state = replace(state, foreign=read_back, foreign_steps=1)
        else:
            state = replace(state, foreign=None, foreign_steps=0)
    since = state.unconfirmed_since
    late = (
        state.confirmed_at is None
        and since is not None
        and now - since >= (config.confirm_timeout_s)
    )
    state = replace(state, last_kind=kind, late=late)
    state = _note_attempt_trace(state, trace)
    return state, Observation(kind, trace, quiet, returned, fell)


def _note_attempt_trace(state: GuardState, trace: bool) -> GuardState:
    if trace and state.attempt_at is not None and not state.attempt_trace:
        return replace(state, attempt_trace=True)
    return state


def _latest(*moments: float | None) -> float | None:
    known = [t for t in moments if t is not None]
    return max(known) if known else None


def _shows_ours(state: GuardState, value: float, now: float, config: GuardConfig) -> bool:
    """Within the tolerance of the value written, or of one sent within the timeout."""
    if _near(value, state.written, config.tolerance):
        return True
    return any(
        now - t <= config.confirm_timeout_s and _near(value, sent, config.tolerance)
        for t, sent in state.recent
    )


def _learn_baseline(
    state: GuardState,
    value: float,
    context: GuardContext,
    quiet: bool,
    config: GuardConfig,
) -> GuardState:
    """The baseline (P-07): the first known read-back of the session that is not within the
    tolerance of a value the plugin sent in this session, nor of its last command stored — seen
    before the session's first send, or after the plugin's value was read back once. Heating
    on/off alike (Z4-03): with its echo unknown at the first send, the first other state seen
    later is the one from before the plugin, as long as the plugin has sent only one state;
    once it has sent both, none is learned, and the other state is judged as such (row 13). Not
    during a hot-water draw."""
    if state.baseline is not None or quiet:
        return state
    if _near(value, context.last_command, config.tolerance):
        return state
    if any(_near(value, sent, config.tolerance) for sent in state.sent_values):
        return state
    before_any_send = not state.sent_values and state.written is None
    if before_any_send or state.ever_confirmed:
        return replace(state, baseline=value, sent_values=())
    return state


def _kind(
    state: GuardState,
    value: float,
    ours: bool,
    context: GuardContext,
    trace: bool,
    config: GuardConfig,
) -> ReadKind:
    if ours:
        return ReadKind.OURS
    tolerance = config.tolerance
    if _near(value, state.baseline, tolerance):
        return ReadKind.FALL_BACK
    if not config.two_valued and _near(value, context.thermostat, tolerance):
        return ReadKind.FALL_BACK  # the OpenTherm thermostat's own request
    if config.two_valued and trace and state.written is not None:
        # Two values: with a trace of an outage, the other state is the device's own — a lost
        # command, not another controller (more cautious than the table's row 13).
        return ReadKind.FALL_BACK
    if _near(value, state.previous, tolerance) and not state.taken:
        # The value the current one replaced, the current one not read back yet: a late echo, or
        # the device holding it (a boiler limit, a slow read-back) — never judged for a fixed
        # time alone (Z4R-01). Once the current one has been read back, a return to it is judged:
        # a two-valued target's other state too, once the plugin has switched both ways (Z4-01).
        return ReadKind.PREVIOUS
    return ReadKind.OTHER


# --- what a class does -----------------------------------------------------------------------


def _account(
    state: GuardState,
    judged: ChangeClass,
    read_back: float | None,
    seen: Observation,
    now: float,
) -> tuple[GuardState, tuple[GuardEvent, ...], bool]:
    """The class's bookkeeping: counters, the fall-backs without a trace, the class "ignored
    from the start", the clip. Returns the events and whether a command was lost."""
    traced = seen.trace or seen.returned
    if (
        seen.kind is ReadKind.FALL_BACK
        and judged
        in (
            ChangeClass.LOST_COMMAND,
            ChangeClass.ANOTHER_CONTROLLER,
        )
        and not traced
        and not state.rewrite_pending
    ):
        kept = tuple(t for t in state.fallbacks if now - t <= FALL_BACK_WINDOW_S)
        state = replace(state, fallbacks=(*kept, now))
    if judged is ChangeClass.LOST_COMMAND:
        return replace(state, fallen_at=now, confirmed_at=None), (), True
    if judged is ChangeClass.FAILED_ATTEMPT:
        counted = not (state.attempt_trace or seen.trace)
        state = replace(
            state,
            failed_attempts=state.failed_attempts + (1 if counted else 0),
            failed_values=_union(state.failed_values, state.attempt_values)
            if counted
            else state.failed_values,
            attempt_at=None,
            confirmed_at=None,
        )
        return state, (), False
    if judged is ChangeClass.IGNORED_FROM_START:
        values = _union(state.failed_values, state.attempt_values)
        state = replace(
            state,
            ignored=True,
            ignored_values=values,
            failed_values=values,
            failed_attempts=state.failed_attempts + 1,
            attempt_at=None,
        )
        return state, (GuardEvent.IGNORED,), False
    if judged is ChangeClass.CLIPPED:
        return replace(state, clip=read_back), (), False
    return state, (), False


def _union(values: tuple[float, ...], more: tuple[float, ...]) -> tuple[float, ...]:
    return (*values, *(v for v in more if v not in values))


def _plan(
    state: GuardState,
    desired: float,
    seen: Observation,
    now: float,
    config: GuardConfig,
    events: tuple[GuardEvent, ...],
    judged: ChangeClass,
) -> GuardResult:
    """Nothing to react to: a new value, a keep-alive or a held refresh — or nothing."""
    if state.written is None or not _near(desired, state.written, config.tolerance):
        result = _send(state, desired, WriteKind.CHANGE, now, config, seen.trace)
        return replace(result, events=events, judged=judged)
    written_at = state.written_at if state.written_at is not None else now
    if config.write_type is WriteType.EXPIRING:
        due = now - written_at >= config.keepalive_s
    else:  # held: refreshed with no echo required, and at once when the target is back
        refresh = config.refresh_s
        due = seen.returned or (refresh is not None and now - written_at >= refresh)
    if due:
        result = _send(state, state.written, WriteKind.KEEPALIVE, now, config, seen.trace)
        return replace(result, events=events, judged=judged)
    return GuardResult(state, None, events, judged=judged)


def _send(
    state: GuardState,
    desired: float,
    kind: WriteKind,
    now: float,
    config: GuardConfig,
    trace: bool,
) -> GuardResult:
    """A write and its bookkeeping. A resend or a rewrite is of the value asked for now — the
    one written, unless the controller moved on. One that must wait for the write-rate guard is
    sent at the next step."""
    written = state.written
    value = written if kind is WriteKind.KEEPALIVE and written is not None else desired
    if state.written_at is not None and now - state.written_at < config.min_interval_s:
        waiting = kind in (WriteKind.RESEND, WriteKind.REWRITE)
        return GuardResult(replace(state, retry=True) if waiting else state)
    if kind is WriteKind.KEEPALIVE:
        return GuardResult(replace(state, written_at=now, retry=False), WriteAction(value, kind))
    new_value = written is None or not _near(value, written, config.tolerance)
    if kind is WriteKind.RESEND and new_value:
        kind = WriteKind.CHANGE  # the controller moved on: the new value goes
    # A new window for the first send not read back: after a confirmation, and for the one
    # rewrite, which has its own timeout; otherwise later sends neither delay nor clear it (M9).
    fresh = (
        state.confirmed_at is not None
        or state.unconfirmed_since is None
        or kind is WriteKind.REWRITE
    )
    low = value if fresh or state.sent_low is None else min(state.sent_low, value)
    high = value if fresh or state.sent_high is None else max(state.sent_high, value)
    recent = tuple((t, sent) for t, sent in state.recent if now - t <= config.confirm_timeout_s)
    sent_values = state.sent_values
    if state.baseline is None and all(not _near(value, v, config.tolerance) for v in sent_values):
        sent_values = (*sent_values, value)
    state = replace(
        state,
        written=value,
        written_at=now,
        sent_at=now,
        confirmed_at=None,
        previous=written if new_value else state.previous,
        taken=False if new_value else state.taken,
        retry=False,
        recent=(*recent, (now, value)),
        change_at=now if kind is WriteKind.CHANGE and new_value else state.change_at,
        unconfirmed_since=now if fresh else state.unconfirmed_since,
        sent_low=low,
        sent_high=high,
        sent_values=sent_values,
    )
    state = _attempt(state, kind, value, now, config, trace)
    return GuardResult(state, WriteAction(value, kind))


def _attempt(
    state: GuardState,
    kind: WriteKind,
    value: float,
    now: float,
    config: GuardConfig,
    trace: bool,
) -> GuardState:
    """The start phase's attempts: every send (a change or a resend) starts one; a change within
    a running attempt's timeout belongs to it."""
    if state.start_done:
        return state
    running = state.attempt_at is not None and now - state.attempt_at < config.confirm_timeout_s
    if running and kind is WriteKind.CHANGE:
        return replace(state, attempt_values=_union(state.attempt_values, (value,)))
    return replace(state, attempt_at=now, attempt_values=(value,), attempt_trace=trace)


def _clock(state: GuardState, now: float, config: GuardConfig) -> GuardState:
    """The wall clock went back (C9): the keep-alive is due now, not once the clock catches up
    (the gateway gives the boiler back after a minute without it), and every other moment later
    than now counts as now."""
    if state.written_at is not None and now < state.written_at:
        earlier = now - config.keepalive_s
        state = replace(state, written_at=earlier, sent_at=min(state.sent_at or earlier, earlier))
    moved: dict[str, Any] = {}
    for item in fields(state):
        value = getattr(state, item.name)
        if item.name in ("written", "previous", "sent_low", "sent_high", "baseline", "clip"):
            continue  # values, not moments
        if item.name == "foreign":
            continue
        if isinstance(value, float) and value > now:
            moved[item.name] = now
    if any(t > now for t in state.fallbacks):
        moved["fallbacks"] = tuple(min(t, now) for t in state.fallbacks)
    if any(t > now for t, _v in state.recent):
        moved["recent"] = tuple((min(t, now), v) for t, v in state.recent)
    return replace(state, **moved) if moved else state
