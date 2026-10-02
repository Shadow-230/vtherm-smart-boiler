"""The relay of an on/off boiler (class 3, X8): what is written to it, what its own reported state
means, and whether the boiler shows that it heats.

A boiler switched on and off by a relay is controlled as Versatile Thermostat's own central boiler
did, with the plugin's safeguards. The relay's own settings — whether it reports its state, what
it does after a power cut, whether it has a switch-off timer — are the user's declaration: the
plugin cannot read them, and each unanswered one takes its cautious reading ("I don't know").

What is written (R8):

- a new command at once — to a relay that reports its state only where it differs from what the
  relay shows (a relay with a switch-off timer, declared or not ruled out, gets "on" all the same:
  it renews the timer);
- a relay that reports its state is compared at every step, and at least every
  ``RELAY_CHECK_S`` even without an event; it is written only on a mismatch, and "on" is renewed
  while the command is on where its timer is declared (every min(timer ÷ 2, repeat interval)) or
  not ruled out (every repeat interval — every min(its length ÷ 2, repeat interval) once the
  relay's own timer has been recognised, Z4R2-05); "off" is not repeated;
- a relay that reports no state — declared so, not known, or an entity with ``assumed_state`` —
  gets its current command, on or off, every repeat interval, and nothing is judged from it;
- nothing is written while it is unavailable or missing: out of reach for
  ``RELAY_UNREACHABLE_S`` (unavailable, missing or unknown) it raises its alarm, and it is never
  handed back meanwhile — nothing could reach it; the command goes out at once on its return;
- writes stay ``MIN_WRITE_INTERVAL_S`` apart.

What its own state means (R7; decision 6 with the user's answers C, D, L, N and O), rows in this
order:

1. the command → confirmed;
2. another state within ``RELAY_CONFIRM_S`` of a send, or the previous command shown late →
   waiting;
3. another state with a trace of an outage (the relay, or another entity of its device, away
   within the trace window, or a restart seen), or at the first report after a start → a lost
   command: sent again at once and counted (answer C);
4. the one rewrite not read back within ``RELAY_CONFIRM_S`` → another controller holds the relay:
   the plugin steps aside (decision 6's M8, for a relay);
5. commanded on, found off inside the window of its switch-off timer — at or after
   max(timer − 60 s, timer ÷ 2) since the "on" that started the on-period for a declared length,
   one repeat interval for "I don't know". A declared timer's is the relay's own lapse: "on"
   again at once, not counted — no loss of any kind, so a timer that lapses all day never raises
   "commands lost" (``SCOPE.md`` §5 class 3; Q1's matrix row R5). With "I don't know" one such
   switch-off cannot be told from an automation, a person or the relay's own button: "on" again
   at once, but counted as answer N's restart — ``RESTARTS_ANSWERED`` within a day, the next one
   another controller, and the plugin steps aside at once (Z4-02). One that comes the same time
   into its on-period as an earlier one, within ``TIMER_TOLERANCE_S`` — or a whole multiple of
   it, up to ``TIMER_MULTIPLES``, where a renewal reaching the relay just after its timer had
   switched it off restarted that timer unseen — shows the relay's own timer of that length
   (Z4R-02): from then on a switch-off at that age, or a multiple of it, is its lapse — "on"
   again, not counted — and the control unit asks the user to declare the timer; a switch-off
   at another age still counts. An on-period is counted from the relay's own last "on" where
   Home Assistant shows one later than the plugin's;
6. never read back since a send, for longer than ``RELAY_CONFIRM_S`` → not confirmed ("write
   ignored"), sent again at the next check; after each of the session's first
   ``RELAY_START_SENDS`` sends → ignored from the start: not written again this session, repeats
   included (where "off" is what it ignores, the plugin can no longer switch heating off:
   answer O);
7. after a confirmation, a change with the plugin's own context → not judged: the next check
   sends the command again;
8. after a confirmation, with no trace: the state the user declared for after a power cut, or —
   with "last" or "I don't know" declared — any change → a restart the relay did not report
   (answers D, N): sent again and counted, ``RESTARTS_ANSWERED`` times within a day; the fourth
   is another controller, and the plugin steps aside at once, with no rewrite first;
9. otherwise → another controller (answer C): rewritten once; a second change within a day of
   that rewrite makes the plugin step aside.

Stepping aside stops every write; the control unit then makes the relay's hand-back — its rest
state, written once and then left alone (answers H, L). Restarts with a trace do not count toward
the fourth (this module's reading of N, to confirm at K4).

The proof that the boiler heats (R12) is information only: the flame, the flow risen by
``PROOF_FLOW_RISE_K`` since the "on", the gas meter moved on since it, or the boiler's electric
power at its threshold. Without any sign of heat for ``PROOF_WINDOW_S`` of the relay on — with
at least one such input known — the information alarm "no sign the boiler heats" rises.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from enum import StrEnum
from typing import Any

from .guards import MIN_WRITE_INTERVAL_S, ChangeClass, GuardEvent, WriteKind

DAY = 86400.0
# Decided (2026-09-26/27): a relay out of reach this long raises its alarm; no hand-back.
RELAY_UNREACHABLE_S = 300.0
# Decided (the user's answer N, 2026-09-27): untraced restarts answered within a day; the next one
# is another controller.
RESTARTS_ANSWERED = 3
RESTART_WINDOW_S = DAY
REWRITE_WINDOW_S = DAY  # decision 6: after the one rewrite, a second change this soon steps aside
# Provisional, K4 — each the most cautious value found, with its reason:
# compared even without an event this often: undoes a wrong state within one VT TPI cycle at its
# default, without writing to relays that may store each command.
RELAY_CHECK_S = 300.0
RELAY_CONFIRM_S = 120.0  # a send read back within this (X1's confirmation timeout)
RELAY_START_SENDS = 3  # the session's first sends that may all go unconfirmed (X1's attempts)
REPEAT_DEFAULT_S = 300.0  # the repeat interval without one entered or carried over from VT
REPEAT_MIN_S = 10.0
REPEAT_MAX_S = 300.0  # a relay restarted in the wrong state stays so at most this long
TIMER_MIN_S = 60.0  # a declared switch-off timer: 1 to 120 minutes
TIMER_MAX_S = 7200.0
# A declared timer's lapse at or after max(timer − 60 s, timer ÷ 2); with "I don't know", two
# switch-offs this close in age into their on-periods show the relay's own timer (Z4R-02).
TIMER_TOLERANCE_S = 60.0
# A lapse a renewal hid — it arrived a moment after the relay's timer had switched it off, and
# restarted the timer with no trace in Home Assistant — leaves the next one seen a whole multiple
# of the timer into the on-period: multiples up to this count as the same timer (Z4R-02), and
# only for a timer this long or longer, below which their tolerance windows would cover almost
# any time.
TIMER_MULTIPLES = 3
TIMER_MULTIPLE_MIN_S = 300.0
PROOF_WINDOW_S = 1800.0  # longer than a common 20-minute restart lockout
PROOF_FLOW_RISE_K = 5.0
CONTEXTS_KEPT = 20  # the plugin's own write contexts remembered, to tell its changes apart


class RelayReports(StrEnum):
    """Whether the relay reports its real state (the user's declaration)."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"  # read as "no": blind repeats, nothing judged


class RelayPowerOn(StrEnum):
    """What the relay does when its power returns (its own setting)."""

    OFF = "off"
    ON = "on"
    LAST = "last"
    UNKNOWN = "unknown"  # read as "maybe on"


class RelayTimer(StrEnum):
    """The relay's own switch-off timer."""

    NONE = "none"
    MINUTES = "minutes"  # a declared length
    UNKNOWN = "unknown"  # read as "it may have one": "on" repeated


class RelayRest(StrEnum):
    """What the relay is set to at every hand-back."""

    OFF = "off"
    ON = "on"


class RelayCheck(StrEnum):
    """Where the command stands with the relay, as shown."""

    CONFIRMED = "confirmed"
    WAITING = "waiting"
    NOT_CONFIRMED = "not_confirmed"
    IGNORED = "ignored"
    UNVERIFIED = "unverified"  # it reports no state: controlled without confirmation
    CHANGED_FROM_OUTSIDE = "changed_from_outside"


class HeatEvidence(StrEnum):
    """Whether the boiler shows that it heats while the relay is on (information only)."""

    HEATS = "heats"
    NOT_SEEN = "not_seen"
    UNVERIFIED = "unverified"  # no proof input mapped and known


@dataclass(frozen=True, slots=True)
class RelayConfig:
    """The relay's own settings as the user declared them; ``timer_s`` with a declared length."""

    reports: RelayReports = RelayReports.UNKNOWN
    power_on: RelayPowerOn = RelayPowerOn.UNKNOWN
    timer: RelayTimer = RelayTimer.UNKNOWN
    timer_s: float | None = None
    repeat_s: float = REPEAT_DEFAULT_S
    check_s: float = RELAY_CHECK_S

    def __post_init__(self) -> None:
        if not REPEAT_MIN_S <= self.repeat_s <= REPEAT_MAX_S:
            raise ValueError("the repeat interval must be 10 to 300 s")
        if self.timer is RelayTimer.MINUTES and (
            self.timer_s is None or not TIMER_MIN_S <= self.timer_s <= TIMER_MAX_S
        ):
            raise ValueError("a declared timer needs its length, 1 to 120 minutes")
        if self.check_s <= MIN_WRITE_INTERVAL_S:
            raise ValueError("the check must be longer than the write interval")

    @property
    def reports_state(self) -> bool:
        """Only a clear "yes": "no" and "I don't know" get blind repeats."""
        return self.reports is RelayReports.YES

    @property
    def renew_s(self) -> float | None:
        """How often "on" is sent again while commanded on: a declared timer at half its length,
        never less often than the repeat interval; one not ruled out at the repeat interval;
        ``None`` without one."""
        if self.timer is RelayTimer.MINUTES and self.timer_s is not None:
            return min(self.timer_s / 2.0, self.repeat_s)
        if self.timer is RelayTimer.UNKNOWN:
            return self.repeat_s
        return None

    @property
    def lapse_s(self) -> float | None:
        """How long after the "on" that started the on-period a switch-off is the timer's lapse:
        max(timer − 60 s, timer ÷ 2) for a declared length — the floor keeps a 1-minute timer
        from taking every switch-off for its lapse — one repeat interval for "I don't know";
        ``None`` without a timer."""
        if self.timer is RelayTimer.MINUTES and self.timer_s is not None:
            return max(self.timer_s - TIMER_TOLERANCE_S, self.timer_s / 2.0)
        if self.timer is RelayTimer.UNKNOWN:
            return self.repeat_s
        return None

    @property
    def power_cut_state(self) -> bool | None:
        """The state it takes after a power cut, where declared "off" or "on"."""
        return {RelayPowerOn.OFF: False, RelayPowerOn.ON: True}.get(self.power_on)


@dataclass(frozen=True, slots=True)
class RelaySeen:
    """The relay at a step, as Home Assistant shows it."""

    on: bool | None = None  # on (a switch on, a boiler thermostat heating) or off; None: neither
    known: bool = False  # it shows a state: on, off, or a boiler thermostat's other mode
    available: bool = False  # it can take a write: there, and not unavailable
    reports: bool = True  # False: an entity with ``assumed_state``, whose state confirms nothing
    trace: bool = False  # a trace of an outage within the trace window
    ours: bool = False  # its last change carried the plugin's own context
    first: bool = False  # the first state known since the unit started
    # When it last switched between on and off, as Home Assistant showed it — a return from
    # unavailable or unknown is no such switch (Z4R2-01); ``None``: none seen yet.
    changed_at: float | None = None


@dataclass(frozen=True, slots=True)
class RelayState:
    """The relay rule's memory."""

    # --- per send: reset at every hand-back (``after_hand_back_relay``) ---
    written: bool | None = None  # the command the relay was given (or found in, and taken as)
    written_at: float | None = None  # the last write attempt, repeats and failed ones included
    sent_at: float | None = None  # the last send awaiting confirmation: new, again, rewritten
    change_at: float | None = None  # the last send of a new command
    previous: bool | None = None  # the command before the current one: its late echo is none
    on_since: float | None = None  # the "on" that started the current on-period
    confirmed_at: float | None = None  # read back as commanded since the last send
    held_since: float | None = None  # reads the command since
    retry: bool = False  # the last write failed, or waited: sent again at the next step
    rewrite_pending: bool = False  # the one rewrite not read back yet
    unconfirmed: bool = False  # not read back within the timeout: "write ignored"
    attempt_at: float | None = None  # the start phase's running attempt
    # --- the session's memory: kept across hand-backs, reset at the session's end ---
    start_done: bool = False  # the relay held a command for the timeout
    failed_sends: int = 0  # counted failed attempts of the start phase
    ignored: bool = False  # ignored from the start: not written again this session
    ignored_values: tuple[bool, ...] = ()  # the commands it did not take
    blocked: bool = False  # another controller: the plugin steps aside, nothing more written
    # --- kept for their day, across sessions too (stored at once) ---
    rewritten_at: float | None = None  # the one rewrite (answer C)
    restarts: tuple[float, ...] = ()  # untraced restarts answered (answers D, N)
    # --- facts about the relay ---
    unreachable_since: float | None = None  # out of reach (unavailable, missing, unknown) since
    # With the timer "I don't know" (Z4R-02): the switch-offs counted as restarts, each with how
    # long into its on-period it came — (when, age), kept for their day — and the age at which two
    # of them agreed: the relay's own timer, undeclared (a length, not a moment).
    lapses: tuple[tuple[float, float], ...] = ()
    timer_seen_s: float | None = None

    @property
    def off_ignored(self) -> bool:
        """Ignored from the start with "off" among what it did not take: the plugin can no
        longer switch heating off (answer O)."""
        return self.ignored and False in self.ignored_values


@dataclass(frozen=True, slots=True)
class RelayWrite:
    on: bool
    kind: WriteKind


@dataclass(frozen=True, slots=True)
class RelayResult:
    state: RelayState
    write: RelayWrite | None = None
    events: tuple[GuardEvent, ...] = ()
    judged: ChangeClass = ChangeClass.NOT_JUDGED
    lost: bool = False  # a lost command this step: counted toward "commands lost"
    restart: bool = False  # an untraced restart answered (answers D, N): stored at once
    unreachable: bool = False  # out of reach for ``RELAY_UNREACHABLE_S``: the alarm


@dataclass(frozen=True, slots=True)
class _Verdict:
    judged: ChangeClass
    restart: bool = False  # rows of answers D and N
    age: float | None = None  # an unknown timer's switch-off: how long into its on-period
    timer: float | None = None  # the relay's own timer, seen at this switch-off (Z4R-02)


def plan_relay(
    state: RelayState,
    desired: bool | None,
    seen: RelaySeen,
    now: float,
    config: RelayConfig,
) -> RelayResult:
    """What to write to the relay now (``desired``: the command; ``None``: none), and what its
    state means."""
    state = _clock(state, now)
    if seen.known:
        state = replace(state, unreachable_since=None)
    elif state.unreachable_since is None:
        state = replace(state, unreachable_since=now)
    since = state.unreachable_since
    unreachable = since is not None and now - since >= RELAY_UNREACHABLE_S
    reports = config.reports_state and seen.reports
    verdict = _Verdict(ChangeClass.NOT_JUDGED)
    events: tuple[GuardEvent, ...] = ()
    lost = False
    if reports and seen.known and state.written is not None and not state.blocked:
        state = _observe(state, seen, now)
        if not state.ignored:
            verdict = _classify(state, seen, now, config)
            state, events, lost = _account(state, verdict, seen, now)
    result = RelayResult(
        state, None, events, verdict.judged, lost, verdict.restart and lost, unreachable
    )
    if state.blocked or state.ignored or desired is None or not seen.available:
        return result
    kind, adopt = _due(state, desired, seen, verdict.judged, reports, now, config)
    if adopt:
        return replace(result, state=_adopt(state, desired, now))
    if kind is None:
        return result
    state, write = _send(state, desired, kind, seen, now)
    return replace(result, state=state, write=write)


# --- what a step's state means (R7) ---------------------------------------------------------


def _classify(state: RelayState, seen: RelaySeen, now: float, config: RelayConfig) -> _Verdict:
    """R7's rows, in their order (the module's docstring)."""
    command = state.written
    if seen.on is command:
        return _Verdict(ChangeClass.CONFIRMED)
    if _waiting(state, seen, now):
        return _Verdict(ChangeClass.NOT_JUDGED)
    if seen.trace or seen.first:
        return _Verdict(ChangeClass.LOST_COMMAND)  # answer C: a power or link loss
    if state.rewrite_pending:
        return _Verdict(ChangeClass.ANOTHER_CONTROLLER)  # the one rewrite did not hold
    if command is True and seen.on is False and _lapsed(state, seen, now, config):
        if config.timer is not RelayTimer.UNKNOWN:
            return _Verdict(ChangeClass.OWN_LAPSE)
        start = state.on_since
        assert start is not None  # the lapse window counts from it
        age = _age(start, seen, now)
        timer = _timer_of(state, age, now)
        if timer is not None:
            # The same time into its on-period as before: the relay's own timer — answered, no
            # longer counted (Z4R-02).
            return _Verdict(ChangeClass.OWN_LAPSE, timer=timer)
        # Maybe its timer, maybe an automation or a person: answered, but bounded as a restart
        # the relay did not report (answer N), never without limit (Z4-02).
        return replace(_restart(state, now), age=age)
    if state.confirmed_at is None:
        if not state.start_done and state.attempt_at is not None:
            if state.failed_sends + 1 >= RELAY_START_SENDS:
                return _Verdict(ChangeClass.IGNORED_FROM_START)
            return _Verdict(ChangeClass.FAILED_ATTEMPT)
        return _Verdict(ChangeClass.NOT_CONFIRMED)
    if seen.ours:
        return _Verdict(ChangeClass.NOT_JUDGED)  # its own context: left to the next check
    power_cut = config.power_cut_state
    if power_cut is None or seen.on is power_cut:
        # Answers D and N: a restart the relay did not report — or, with "last" or "I don't
        # know" declared, any change while it stayed available — up to three a day.
        return _restart(state, now)
    return _Verdict(ChangeClass.ANOTHER_CONTROLLER)  # answer C


def _restart(state: RelayState, now: float) -> _Verdict:
    """A possible restart the relay did not report (answers D, N): a lost command, sent again
    and counted, ``RESTARTS_ANSWERED`` times within a day; the next one is another controller."""
    recent = [t for t in state.restarts if now - t < RESTART_WINDOW_S]
    judged = (
        ChangeClass.ANOTHER_CONTROLLER
        if len(recent) >= RESTARTS_ANSWERED
        else ChangeClass.LOST_COMMAND
    )
    return _Verdict(judged, restart=True)


def _waiting(state: RelayState, seen: RelaySeen, now: float) -> bool:
    """Within the timeout of a send, or the previous command shown late."""
    if state.sent_at is not None and now - state.sent_at < RELAY_CONFIRM_S:
        return True
    return (
        state.previous is not None
        and seen.on is state.previous
        and state.change_at is not None
        and now - state.change_at < RELAY_CONFIRM_S
    )


def _lapsed(state: RelayState, seen: RelaySeen, now: float, config: RelayConfig) -> bool:
    """The switch-off came inside the timer's lapse window, counted from the start of the
    on-period — not from the last "on" sent, so a relay that does not restart its timer on a
    repeated "on" is recognised too."""
    lapse = config.lapse_s
    start = state.on_since
    if lapse is None or start is None:
        return False
    return _age(start, seen, now) >= lapse


def _age(start: float, seen: RelaySeen, now: float) -> float:
    """How long into its on-period, begun at ``start``, the relay went off: to the moment Home
    Assistant shows for the change — this step's, where it shows none."""
    off_at = seen.changed_at if seen.changed_at is not None else now
    return off_at - start


def _timer_of(state: RelayState, age: float, now: float) -> float | None:
    """The relay's own timer, where this switch-off came the same time into its on-period as one
    before it — within ``TIMER_TOLERANCE_S``, or a whole multiple of it where a renewal hid a
    lapse in between (Z4R-02): the timer seen already (or this age, where that one was a multiple
    of it), the two ages' mean, or the shorter of two a multiple apart; ``None`` for an irregular
    switch-off."""
    seen = state.timer_seen_s
    if seen is not None:
        if _times(age, seen) is not None:
            return seen
        return age if _times(seen, age) is not None else None  # shorter than seen
    for at, earlier in state.lapses:
        if now - at >= RESTART_WINDOW_S:
            continue
        short, long = sorted((age, earlier))
        times = _times(long, short)
        if times is not None:
            return (age + earlier) / 2.0 if times == 1 else short
    return None


def _times(age: float, timer: float) -> int | None:
    """How many timer lengths ``age`` is, where it is a whole number of them within
    ``TIMER_TOLERANCE_S``: one, or up to ``TIMER_MULTIPLES`` for a timer of at least
    ``TIMER_MULTIPLE_MIN_S``; ``None`` otherwise."""
    times = round(age / timer)
    if times < 1 or abs(age - times * timer) > TIMER_TOLERANCE_S:
        return None
    if times > 1 and (times > TIMER_MULTIPLES or timer < TIMER_MULTIPLE_MIN_S):
        return None
    return times


def _observe(state: RelayState, seen: RelaySeen, now: float) -> RelayState:
    """The relay shows the command: confirmed, held since; held for the timeout, the start phase
    is over and "write ignored" clears (not after "ignored from the start"). Shown on since a
    moment later than the "on" the on-period counts from, the on-period began then (Z4R-02)."""
    if seen.on is not state.written:
        return replace(state, held_since=None)
    start, changed = state.on_since, seen.changed_at
    if seen.on and start is not None and changed is not None and changed > start:
        # On again since the "on" its on-period was counted from — a renewal that reached it just
        # after its own timer had switched it off restarts that timer: the on-period began then.
        state = replace(state, on_since=min(changed, now))
    held = now if state.held_since is None else state.held_since
    state = replace(
        state,
        confirmed_at=now if state.confirmed_at is None else state.confirmed_at,
        held_since=held,
        rewrite_pending=False,
        attempt_at=None,
    )
    if now - held >= RELAY_CONFIRM_S and not state.ignored:
        state = replace(state, start_done=True, unconfirmed=False)
    return state


def _account(
    state: RelayState, verdict: _Verdict, seen: RelaySeen, now: float
) -> tuple[RelayState, tuple[GuardEvent, ...], bool]:
    """A verdict's bookkeeping: the restarts and the one rewrite (stored at once by the caller),
    the start phase, the block. Returns the events and whether a command was lost."""
    judged = verdict.judged
    if judged is ChangeClass.OWN_LAPSE:
        if verdict.timer is not None and verdict.timer != state.timer_seen_s:
            state = replace(state, timer_seen_s=verdict.timer)  # an undeclared timer (Z4R-02)
        return state, (), False  # the relay's own timer: "on" again, never counted (R5)
    if judged is ChangeClass.LOST_COMMAND:
        if verdict.restart:
            kept = tuple(t for t in state.restarts if now - t < RESTART_WINDOW_S)
            state = replace(state, restarts=(*kept, now))
        if verdict.age is not None:
            lapses = tuple(lapse for lapse in state.lapses if now - lapse[0] < RESTART_WINDOW_S)
            state = replace(state, lapses=(*lapses, (now, verdict.age)))
        return state, (), True
    if judged is ChangeClass.ANOTHER_CONTROLLER:
        recent = state.rewritten_at is not None and now - state.rewritten_at < REWRITE_WINDOW_S
        if verdict.restart or state.rewrite_pending or recent:
            # Never fighting: stop and report; the control unit steps aside.
            return replace(state, blocked=True), (GuardEvent.OUTSIDE_CHANGE,), False
        return replace(state, rewritten_at=now, rewrite_pending=True), (), False
    if judged is ChangeClass.FAILED_ATTEMPT:
        failed = replace(
            state, failed_sends=state.failed_sends + 1, attempt_at=None, unconfirmed=True
        )
        return failed, (), False
    if judged is ChangeClass.IGNORED_FROM_START:
        written = state.written
        values = state.ignored_values
        if written is not None and written not in values:
            values = (*values, written)
        state = replace(
            state,
            ignored=True,
            ignored_values=values,
            failed_sends=state.failed_sends + 1,
            attempt_at=None,
            unconfirmed=True,
        )
        return state, (GuardEvent.IGNORED,), False
    if judged is ChangeClass.NOT_CONFIRMED:
        return replace(state, unconfirmed=True), (), False
    return state, (), False


# --- what is written (R8) --------------------------------------------------------------------

_RESENDING = frozenset({ChangeClass.LOST_COMMAND, ChangeClass.OWN_LAPSE})
_CHECKED = frozenset(
    {ChangeClass.NOT_JUDGED, ChangeClass.NOT_CONFIRMED, ChangeClass.FAILED_ATTEMPT}
)


def _due(
    state: RelayState,
    desired: bool,
    seen: RelaySeen,
    judged: ChangeClass,
    reports: bool,
    now: float,
    config: RelayConfig,
) -> tuple[WriteKind | None, bool]:
    """The write this step needs, if any, and whether a new command is instead taken as it is —
    the relay reports its state and already shows it, and no switch-off timer needs the "on"."""
    written = state.written
    if state.retry and written is not None:
        return WriteKind.RESEND, False
    if written is None or desired != written:
        shows = reports and seen.known and seen.on is desired
        timer = desired and config.renew_s is not None
        return WriteKind.CHANGE, shows and not timer
    if not reports:
        # Blind: the current command, on or off, every repeat interval.
        return (WriteKind.KEEPALIVE if _elapsed(state, now, config.repeat_s) else None), False
    if judged in _RESENDING:
        return WriteKind.RESEND, False
    if judged is ChangeClass.ANOTHER_CONTROLLER:
        return WriteKind.REWRITE, False
    mismatch = seen.known and seen.on is not desired
    if mismatch and judged in _CHECKED and _elapsed(state, now, config.check_s):
        return WriteKind.RESEND, False  # the check: a mismatch nothing else answered
    renew = _renew_s(state, config)
    if desired and renew is not None and _elapsed(state, now, renew):
        return WriteKind.KEEPALIVE, False  # renews the relay's own timer; "off" not repeated
    return None, False


def _renew_s(state: RelayState, config: RelayConfig) -> float | None:
    """How often "on" is renewed while commanded on: as the configuration says, and for the
    relay's own timer recognised while declared "I don't know", as for a declared one — every
    min(its length ÷ 2, repeat interval), so a timer that a repeated "on" restarts no longer
    races the renewal and lapses (Z4R2-05)."""
    seen = state.timer_seen_s
    if config.timer is RelayTimer.UNKNOWN and seen is not None:
        return min(seen / 2.0, config.repeat_s)
    return config.renew_s


def _elapsed(state: RelayState, now: float, interval: float) -> bool:
    return state.written_at is None or now - state.written_at >= interval


def _adopt(state: RelayState, desired: bool, now: float) -> RelayState:
    """A new command the relay already shows: taken as written and confirmed, with no write —
    a relay that reports its state is written on a mismatch only."""
    return replace(
        state,
        written=desired,
        previous=state.written,
        sent_at=None,
        change_at=None,
        confirmed_at=now,
        held_since=now,
        on_since=now if desired else None,
        retry=False,
        rewrite_pending=False,
        unconfirmed=state.unconfirmed and not state.start_done,
        attempt_at=None,
    )


def _send(
    state: RelayState, desired: bool, kind: WriteKind, seen: RelaySeen, now: float
) -> tuple[RelayState, RelayWrite | None]:
    """A write and its bookkeeping; one that must wait for the write-rate guard goes at the next
    step (a repeat is simply not due yet)."""
    if state.written_at is not None and now - state.written_at < MIN_WRITE_INTERVAL_S:
        if kind is WriteKind.KEEPALIVE:
            return state, None
        return replace(state, retry=True), None
    if kind is WriteKind.KEEPALIVE:
        return replace(state, written_at=now, retry=False), RelayWrite(desired, kind)
    new = state.written is None or desired != state.written
    if kind is WriteKind.RESEND and new:
        kind = WriteKind.CHANGE  # the command moved on: the new one goes
    # The "on" that starts an on-period: a new "on", or "on" again while the relay reads off.
    starts = desired and (new or seen.on is not True or state.on_since is None)
    state = replace(
        state,
        written=desired,
        written_at=now,
        sent_at=now,
        change_at=now if new else state.change_at,
        previous=state.written if new else state.previous,
        on_since=(now if starts else state.on_since) if desired else None,
        confirmed_at=None,
        held_since=None,
        retry=False,
        rewrite_pending=state.rewrite_pending if kind is WriteKind.REWRITE else False,
        attempt_at=now if not state.start_done else None,
    )
    return state, RelayWrite(desired, kind)


# --- the session's memory --------------------------------------------------------------------

_SESSION = (
    "start_done",
    "failed_sends",
    "ignored",
    "ignored_values",
    "blocked",
    "rewritten_at",
    "restarts",
    "unreachable_since",
    "lapses",
    "timer_seen_s",
)


def relay_write_failed(state: RelayState) -> RelayState:
    """The write did not go through: sent again at the next step."""
    return replace(state, retry=True)


def after_hand_back_relay(state: RelayState) -> RelayState:
    """A hand-back inside the session: the per-send fields go; the session's memory — the block,
    "ignored from the start", the start phase, the one rewrite, the restarts — stays, and so do
    the facts about the relay (its reachability, its own timer seen)."""
    kept: dict[str, Any] = {name: getattr(state, name) for name in _SESSION}
    return RelayState(**kept)


def relay_for_new_session(state: RelayState, now: float) -> RelayState:
    """A new session (control switched off and on): everything afresh but the one rewrite and the
    restarts, each kept for its day — so no relay is answered more than three untraced restarts a
    day (answer N) — with the switch-offs counted among them, and the facts about the relay: when
    it went out of reach, and its own timer seen (Z4R-02)."""
    rewritten = state.rewritten_at
    keep = rewritten is not None and now - rewritten < REWRITE_WINDOW_S
    return RelayState(
        rewritten_at=rewritten if keep else None,
        restarts=tuple(t for t in state.restarts if now - t < RESTART_WINDOW_S),
        unreachable_since=state.unreachable_since,
        lapses=tuple(lapse for lapse in state.lapses if now - lapse[0] < RESTART_WINDOW_S),
        timer_seen_s=state.timer_seen_s,
    )


def relay_write_ignored(state: RelayState) -> bool:
    """ "Write ignored": not read back within the timeout, until the relay has held the command
    for it — or ignored from the start, until the next session."""
    return state.ignored or state.unconfirmed


def relay_check(state: RelayState, config: RelayConfig, *, reports: bool) -> RelayCheck | None:
    """Where the command stands, as shown; ``None`` before the first command. ``reports``: the
    entity reports its state (no ``assumed_state``)."""
    if not (config.reports_state and reports):
        return RelayCheck.UNVERIFIED
    if state.blocked:
        return RelayCheck.CHANGED_FROM_OUTSIDE
    if state.ignored:
        return RelayCheck.IGNORED
    if state.written is None:
        return None
    if state.unconfirmed:
        return RelayCheck.NOT_CONFIRMED
    return RelayCheck.CONFIRMED if state.confirmed_at is not None else RelayCheck.WAITING


def _clock(state: RelayState, now: float) -> RelayState:
    """The wall clock went back (C9): every moment later than now counts as now."""
    moved: dict[str, Any] = {}
    for item in fields(state):
        value = getattr(state, item.name)
        if item.name == "timer_seen_s":
            continue  # a length, not a moment
        if isinstance(value, float) and value > now:
            moved[item.name] = now
    if any(t > now for t in state.restarts):
        moved["restarts"] = tuple(min(t, now) for t in state.restarts)
    if any(at > now for at, _length in state.lapses):
        moved["lapses"] = tuple((min(at, now), length) for at, length in state.lapses)
    return replace(state, **moved) if moved else state


# --- the proof that the boiler heats (R12) ---------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProofSeen:
    """The proof inputs now (``None``: not mapped, or not known): the flame, the flow (°C), the
    gas meter, the boiler's electric power (W) and the threshold the user gave it."""

    flame: bool | None = None
    flow: float | None = None
    gas: float | None = None
    power_w: float | None = None
    heats_above_w: float | None = None


@dataclass(frozen=True, slots=True)
class ProofState:
    on_since: float | None = None  # the relay on since
    flow_at_on: float | None = None  # the flow then (its first known value after it)
    gas_at_on: float | None = None  # the gas meter then (its first known value after it)
    seen: bool = False  # heat shown in this on-period


def heat_evidence(
    seen: ProofSeen, flow_at_on: float | None, gas_at_on: float | None
) -> HeatEvidence:
    """Heats: the flame on, the flow ``PROOF_FLOW_RISE_K`` above its value at the "on", the gas
    meter past its value at the "on", or the power at or above its threshold. Unverified: no
    proof input mapped and known. Otherwise not seen."""
    known = False
    if seen.flame is not None:
        known = True
        if seen.flame:
            return HeatEvidence.HEATS
    if seen.flow is not None:
        known = True
        if flow_at_on is not None and seen.flow - flow_at_on >= PROOF_FLOW_RISE_K:
            return HeatEvidence.HEATS
    if seen.gas is not None:
        known = True
        if gas_at_on is not None and seen.gas > gas_at_on:
            return HeatEvidence.HEATS
    if seen.power_w is not None and seen.heats_above_w is not None:
        known = True
        if seen.power_w >= seen.heats_above_w:
            return HeatEvidence.HEATS
    return HeatEvidence.NOT_SEEN if known else HeatEvidence.UNVERIFIED


def follow_proof(
    state: ProofState, on: bool, seen: ProofSeen, now: float
) -> tuple[ProofState, HeatEvidence | None, bool]:
    """The proof while the relay is on: what is shown (``None`` while it is off) and whether the
    information alarm "no sign the boiler heats" is on — ``PROOF_WINDOW_S`` of the relay on with
    a proof input known and no heat seen in this on-period (a boiler stopping on its own
    thermostat after it heated raises nothing); it clears on any proof or when the relay goes
    off. Nothing known: unverified, never an alarm."""
    if not on:
        return ProofState(), None, False
    if state.on_since is None or state.on_since > now:
        state = ProofState(on_since=now, flow_at_on=seen.flow, gas_at_on=seen.gas)
    if state.flow_at_on is None and seen.flow is not None:
        state = replace(state, flow_at_on=seen.flow)
    if state.gas_at_on is None and seen.gas is not None:
        state = replace(state, gas_at_on=seen.gas)
    evidence = heat_evidence(seen, state.flow_at_on, state.gas_at_on)
    if evidence is HeatEvidence.HEATS:
        state = replace(state, seen=True)
    shown = HeatEvidence.HEATS if state.seen else evidence
    since = state.on_since
    alarm = shown is HeatEvidence.NOT_SEEN and since is not None and now - since >= PROOF_WINDOW_S
    return state, shown, alarm
