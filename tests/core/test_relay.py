"""The relay of an on/off boiler (class 3, X8): what is written to it, what its own reported
state means (the rows of R7's table, decision 6 with the user's answers C, D, L, N and O), its
repeats and renewals, and the proof that the boiler heats."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    DAY,
    ChangeClass,
    GuardEvent,
    WriteKind,
    add_loss,
    losses_warning,
)
from custom_components.vtherm_smart_boiler.core.relay import (
    PROOF_FLOW_RISE_K,
    PROOF_WINDOW_S,
    RELAY_CHECK_S,
    RELAY_CONFIRM_S,
    RELAY_NOT_TAKEN_CHECKS,
    RELAY_UNREACHABLE_S,
    RESTARTS_ANSWERED,
    HeatEvidence,
    ProofSeen,
    ProofState,
    RelayCheck,
    RelayConfig,
    RelayPowerOn,
    RelayReports,
    RelayResult,
    RelaySeen,
    RelayState,
    RelayTimer,
    RelayWrite,
    after_hand_back_relay,
    follow_proof,
    heat_evidence,
    plan_relay,
    relay_check,
    relay_for_new_session,
    relay_write_failed,
    relay_write_ignored,
    short_switch_off_s,
)

MIN = 60.0
HOUR_S = 3600.0
TRACE_S = 300.0
REPORTING = RelayConfig(reports=RelayReports.YES, timer=RelayTimer.NONE)


@dataclass
class Relay:
    """A relay in the test: it takes the plugin's writes (``takes``), may be switched by
    something else, may be out of reach, and may have its own switch-off timer, restarted by a
    repeated "on" or not (``restarts_timer``)."""

    on: bool | None = False
    available: bool = True
    takes: bool = True
    outage_at: float | None = None  # the trace of an outage: when it was last away
    changed_at: float | None = None
    ours: bool = False  # the last change was the plugin's
    timer_s: float | None = None
    restarts_timer: bool = True
    on_at: float | None = None  # when its timer started
    reports_change: bool = True  # False: Home Assistant shows no moment of its last change
    # Its timer, due at ``t``, fires just after the step looked and just before that step's
    # write lands — a renewal arriving a moment after the lapse turns it on again and restarts
    # its timer; ``masked_seen``: Home Assistant shows that brief change (its moment), or not.
    masks: Callable[[float], bool] | None = None
    masked_seen: bool = False
    # Another controller puts it back within a second of every write of the plugin's that
    # changed it: Home Assistant shows the plugin's state for that second, then the other one
    # (PB-01) — the next step never sees the plugin's state. ``reverts_ours``: it puts itself
    # back, within Home Assistant's few seconds in which a state still carries the caller's
    # context — an "inching" relay, a script on the device: the change shows as the plugin's.
    reverts: bool = False
    reverts_ours: bool = False
    writes: list[tuple[float, bool, WriteKind]] = field(default_factory=list)
    failed: list[tuple[float, bool, WriteKind]] = field(default_factory=list)  # never arrived
    starts: list[float] = field(default_factory=list)  # an "on" written while off: a boiler start

    def tick(self, t: float, *, due_now: bool = True) -> None:
        """Its own timer switches it off (``due_now``: also a lapse due exactly at ``t``)."""
        timer, since = self.timer_s, self.on_at
        if not self.on or timer is None or since is None:
            return
        if t - since > timer or (due_now and t - since >= timer):
            self.on, self.changed_at, self.ours = False, since + timer, False

    def masked_at(self, t: float) -> bool:
        return self.masks is not None and self.masks(t)

    def seen(
        self, t: float, *, reports: bool = True, first: bool = False, returned: bool = False
    ) -> RelaySeen:
        known = self.available and self.on is not None
        return RelaySeen(
            on=self.on if known else None,
            known=known,
            available=self.available,
            reports=reports,
            trace=self.outage_at is not None and t - self.outage_at <= TRACE_S,
            ours=self.ours,
            first=first,
            changed_at=self.changed_at if self.reports_change else None,
            returned=returned,
        )

    def write(self, t: float, write: RelayWrite) -> None:
        self.writes.append((t, write.on, write.kind))
        if not (self.available and self.takes):
            return
        foreign = self.on
        before = self.changed_at
        masked = False
        if self.masked_at(t) and self.on and write.on:
            self.tick(t)  # the lapse due now, a moment before the write
            masked = not self.on
        if write.on and self.on is False:
            self.starts.append(t)
        if write.on and (not self.on or self.restarts_timer):
            self.on_at = t
        if self.on != write.on:
            self.changed_at = t
        if masked and not self.masked_seen:
            self.changed_at = before  # off and on again with no trace in Home Assistant
        self.on, self.ours = write.on, True
        if self.reverts and foreign is not None and foreign is not write.on:
            self.on, self.changed_at, self.ours = foreign, t + 1.0, self.reverts_ours

    def switch(self, t: float, on: bool) -> None:
        """Something else switches it while it stays available."""
        self.on, self.changed_at, self.ours = on, t, False
        if on:
            self.on_at = t

    def away(self, t: float) -> None:
        self.available, self.outage_at = False, t

    def back(self, t: float, on: bool) -> None:
        """Back after a power or link loss, in ``on``: the return itself is a trace."""
        self.available, self.outage_at, self.on, self.changed_at = True, t, on, t
        self.ours = False
        self.on_at = t if on else None


def drive(
    relay: Relay,
    config: RelayConfig,
    desired: bool | Callable[[float], bool | None] | None,
    start: float,
    end: float,
    state: RelayState | None = None,
    *,
    reports: bool = True,
    step: float = 10.0,
    at: Callable[[float], None] | None = None,
    fails: Callable[[float], bool] | None = None,
) -> tuple[RelayState, list[tuple[float, RelayResult]]]:
    """Steps every ``step`` seconds from ``start`` to ``end`` (included); ``at(t)`` changes the
    relay before the step at ``t`` sees it; ``fails(t)``: the service call of the step at ``t``
    fails — nothing reaches the relay, and the control unit reports it (``relay_write_failed``).
    The relay is seen back within reach (``returned``) where it went through an outage since
    the step before, as the control unit notes it (PB-44)."""
    state = state or RelayState()
    results: list[tuple[float, RelayResult]] = []
    t = start
    last: float | None = None
    while t <= end + 1e-9:
        if at is not None:
            at(t)
        relay.tick(t, due_now=not relay.masked_at(t))
        want = desired(t) if callable(desired) else desired
        outage = relay.outage_at
        returned = relay.available and outage is not None and last is not None and outage > last
        seen = relay.seen(t, reports=reports, returned=returned)
        result = plan_relay(state, want, seen, t, config)
        state = result.state
        if result.write is not None:
            if fails is not None and fails(t):
                relay.failed.append((t, result.write.on, result.write.kind))
                state = relay_write_failed(state)
            else:
                relay.write(t, result.write)
        results.append((t, result))
        last = t
        t += step
    return state, results


def events(results: list[tuple[float, RelayResult]]) -> list[tuple[float, GuardEvent]]:
    return [(t, event) for t, result in results for event in result.events]


def lost(results: list[tuple[float, RelayResult]]) -> list[float]:
    return [t for t, result in results if result.lost]


def confirmed_on(config: RelayConfig = REPORTING) -> tuple[Relay, RelayState]:
    """A relay commanded on at 0 and confirmed since."""
    relay = Relay()
    state, _ = drive(relay, config, True, 0.0, 200.0)
    assert relay.on is True
    return relay, state


def test_a_new_command_is_written_at_once() -> None:
    relay = Relay()
    state, results = drive(relay, REPORTING, lambda t: t < 500, 0.0, 600.0)
    assert relay.writes == [(0.0, True, WriteKind.CHANGE), (500.0, False, WriteKind.CHANGE)]
    assert results[0][1].write == RelayWrite(True, WriteKind.CHANGE)
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.CONFIRMED


def test_a_confirmed_state_is_not_written_again() -> None:
    """A state-reporting relay declared without a timer gets no repeats: only a mismatch is
    written, and "off" is never repeated."""
    relay = Relay()
    drive(relay, REPORTING, lambda t: t < 7200, 0.0, 4 * 3600.0)
    assert relay.writes == [(0.0, True, WriteKind.CHANGE), (7200.0, False, WriteKind.CHANGE)]


def test_a_relay_back_from_unavailable_in_another_state_gets_the_command_again() -> None:
    """Answer C: a lost command — sent again at once, counted, and no rewrite spent. Nothing is
    written while it is away."""
    relay, state = confirmed_on()
    state, results = drive(
        relay,
        REPORTING,
        True,
        210.0,
        1500.0,
        state,
        at=lambda t: relay.away(t) if t == 600 else relay.back(t, False) if t == 900 else None,
    )
    away = [w for w in relay.writes if 600 <= w[0] < 900]
    assert away == []  # nothing written while it cannot arrive
    assert relay.writes[-1] == (900.0, True, WriteKind.RESEND)
    assert lost(results) == [900.0]
    judged = dict(results)[900.0].judged
    assert judged is ChangeClass.LOST_COMMAND
    assert state.rewritten_at is None
    assert state.restarts == ()  # a restart with a trace does not count toward the fourth
    assert events(results) == []


def test_a_relay_back_in_its_declared_power_cut_state_is_a_restart() -> None:
    """Answer D: declared "off after a power cut", commanded on, found off with no trace while
    it stayed available — a restart the relay did not report: sent again at once and counted,
    no rewrite spent; the third within a day raises "commands lost"."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay, state = confirmed_on(config)
    losses: tuple[tuple[float, str], ...] = ()
    warned = False
    for n, t in enumerate((1000.0, 2000.0, 3000.0), start=1):
        state, results = drive(
            relay,
            config,
            True,
            t - 10,
            t + 50,
            state,
            at=lambda s, t=t: relay.switch(s, False) if s == t else None,
        )
        result = dict(results)[t]
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.write == RelayWrite(True, WriteKind.RESEND)
        assert result.lost
        assert result.restart
        assert state.rewritten_at is None
        assert len(state.restarts) == n
        losses = add_loss(losses, t, "relay")
        warned = losses_warning(losses, t, warned)
        assert warned is (n == 3), n
    assert events(results) == []


@pytest.mark.parametrize("traced_between", [False, True])
def test_a_fourth_power_cut_state_restart_in_a_day_steps_aside(traced_between: bool) -> None:
    """Answer N: three such restarts within a day are each sent the command again; the fourth is
    another controller — the plugin steps aside at once, with no rewrite first. Restarts with a
    trace (R2) do not count toward the fourth."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay, state = confirmed_on(config)
    for t in (1000.0, 2000.0, 3000.0):
        state, _ = drive(
            relay,
            config,
            True,
            t,
            t + 50,
            state,
            at=lambda s, t=t: relay.switch(s, False) if s == t else None,
        )
    if traced_between:
        # A restart Home Assistant saw (the relay was away): R2, not counted toward the fourth.
        state, results = drive(
            relay,
            config,
            True,
            3500.0,
            3600.0,
            state,
            at=lambda s: (
                relay.away(s) if s == 3500 else relay.back(s, False) if s == 3520 else None
            ),
        )
        assert dict(results)[3520.0].judged is ChangeClass.LOST_COMMAND
        assert len(state.restarts) == RESTARTS_ANSWERED
        relay.outage_at = None  # its trace has passed by the fourth
    count = len(relay.writes)
    state, results = drive(
        relay,
        config,
        True,
        4000.0,
        4600.0,
        state,
        at=lambda s: relay.switch(s, False) if s in (4000, 4200) else None,
    )
    fourth = dict(results)[4000.0]
    assert fourth.judged is ChangeClass.ANOTHER_CONTROLLER
    assert fourth.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert fourth.write is None  # no rewrite first
    assert state.blocked
    assert relay.writes[count:] == []  # nothing more is written, whatever the relay does


def test_a_fourth_restart_more_than_a_day_after_the_first_is_a_restart_again() -> None:
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay, state = confirmed_on(config)
    for t in (1000.0, 2000.0, 3000.0, 1000.0 + DAY + 10):
        state, results = drive(
            relay,
            config,
            True,
            t,
            t + 20,
            state,
            at=lambda s, t=t: relay.switch(s, False) if s == t else None,
        )
        assert dict(results)[t].judged is ChangeClass.LOST_COMMAND, t
    assert not state.blocked
    assert len(state.restarts) == RESTARTS_ANSWERED  # the first has left the day


@pytest.mark.parametrize("power_on", [RelayPowerOn.LAST, RelayPowerOn.UNKNOWN])
def test_a_change_with_the_power_cut_state_last_or_unknown_is_a_possible_restart_three_times(
    power_on: RelayPowerOn,
) -> None:
    """Answer N: no power-cut state known — any change while the relay stayed available, with no
    trace and not the plugin's, is a possible restart: sent again, counted, no rewrite spent,
    three times within a day; the fourth steps aside."""
    config = replace(REPORTING, power_on=power_on)
    relay, state = confirmed_on(config)
    for n, (t, on) in enumerate(((1000.0, False), (2000.0, False), (3000.0, False)), start=1):
        state, results = drive(
            relay,
            config,
            True,
            t,
            t + 20,
            state,
            at=lambda s, t=t, on=on: relay.switch(s, on) if s == t else None,
        )
        result = dict(results)[t]
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.write == RelayWrite(True, WriteKind.RESEND)
        assert result.restart
        assert result.lost
        assert state.rewritten_at is None
        assert len(state.restarts) == n
    # Commanded off and switched on: a possible restart too — here the fourth: step aside.
    state, results = drive(
        relay,
        config,
        lambda s: s < 3500,
        3490.0,
        3700.0,
        state,
        at=lambda s: relay.switch(s, True) if s == 3650 else None,
    )
    result = dict(results)[3650.0]
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert result.write is None
    assert state.blocked


def test_a_relay_that_reports_no_state_is_never_judged() -> None:
    """Negative: declared "no" (or an entity with ``assumed_state``): nothing is judged from its
    state, only blind repeats."""
    for config, reports in (
        (replace(REPORTING, reports=RelayReports.NO, power_on=RelayPowerOn.UNKNOWN), True),
        (replace(REPORTING, power_on=RelayPowerOn.UNKNOWN), False),
    ):
        relay = Relay()

        def switched(s: float, relay: Relay = relay) -> None:
            if s in (1000, 1500, 2000, 2500):
                relay.switch(s, False)

        state, results = drive(relay, config, True, 0.0, 3000.0, reports=reports, at=switched)
        assert events(results) == []
        assert lost(results) == []
        assert all(r.judged is ChangeClass.NOT_JUDGED for _t, r in results)
        assert state.restarts == ()
        assert relay_check(state, config, reports=reports) is RelayCheck.UNVERIFIED
        assert not state.not_taken  # never judged as no longer taking commands either


def test_a_relay_out_of_reach_is_not_written_and_alarms_after_five_minutes() -> None:
    """R6: unavailable or missing — nothing is written; out of reach (unavailable, missing or
    unknown) for five minutes — the alarm; never a hand-back (the core keeps deciding)."""
    relay, state = confirmed_on()
    count = len(relay.writes)
    state, results = drive(
        relay,
        REPORTING,
        lambda t: t < 250,
        210.0,
        700.0,
        state,
        at=lambda s: relay.away(s) if s == 240 else None,
    )
    by_t = dict(results)
    assert relay.writes[count:] == []  # the new command waits for the relay
    assert not by_t[240.0 + RELAY_UNREACHABLE_S - 10].unreachable  # 4 min 50 s
    assert by_t[240.0 + RELAY_UNREACHABLE_S].unreachable  # 5 min
    assert by_t[700.0].unreachable
    state, results = drive(
        relay,
        REPORTING,
        False,
        710.0,
        730.0,
        state,
        at=lambda s: relay.back(s, True) if s == 710 else None,
    )
    assert relay.writes[count:] == [(710.0, False, WriteKind.CHANGE)]  # at once on its return
    assert not dict(results)[710.0].unreachable


def test_an_unknown_relay_is_written_but_not_confirmed_and_alarms() -> None:
    """``unknown`` — it is there, without a state: a new command is written, nothing judged, and
    it counts as out of reach for the alarm."""
    config = REPORTING
    state = RelayState()
    seen = RelaySeen(on=None, known=False, available=True)
    result = plan_relay(state, True, seen, 0.0, config)
    assert result.write == RelayWrite(True, WriteKind.CHANGE)
    result = plan_relay(result.state, True, seen, RELAY_UNREACHABLE_S, config)
    assert result.unreachable
    assert result.judged is ChangeClass.NOT_JUDGED
    assert result.events == ()


def test_a_change_while_available_is_rewritten_once_then_the_plugin_steps_aside() -> None:
    """Answers C, H and L: declared "off after a power cut", commanded off, switched on while it
    stayed available — rewritten once; a second change within a day of that rewrite: the plugin
    steps aside, and writes nothing more, whatever the relay then does."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay = Relay(on=True)
    state, _ = drive(relay, config, False, 0.0, 200.0)
    assert relay.on is False
    state, results = drive(
        relay,
        config,
        False,
        1000.0,
        1100.0,
        state,
        at=lambda s: relay.switch(s, True) if s == 1000 else None,
    )
    first = dict(results)[1000.0]
    assert first.judged is ChangeClass.ANOTHER_CONTROLLER
    assert first.write == RelayWrite(False, WriteKind.REWRITE)
    assert first.events == ()
    assert state.rewritten_at == 1000.0
    assert not first.lost
    count = len(relay.writes)
    state, results = drive(
        relay,
        config,
        False,
        2000.0,
        3000.0,
        state,
        at=lambda s: (
            relay.switch(s, True)
            if s == 2000
            else relay.switch(s, False)
            if s == 2010
            else (relay.switch(s, True) if s == 2020 else None)
        ),
    )
    second = dict(results)[2000.0]
    assert second.judged is ChangeClass.ANOTHER_CONTROLLER
    assert second.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert second.write is None
    assert state.blocked
    assert relay.writes[count:] == []
    assert relay_check(state, config, reports=True) is RelayCheck.CHANGED_FROM_OUTSIDE


def test_a_rewrite_that_does_not_hold_steps_aside() -> None:
    """Decision 6 (M8), for a relay: the one rewrite not read back within 120 s means the other
    controller holds the relay — the plugin steps aside rather than fight it."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay = Relay(on=True)
    state, _ = drive(relay, config, False, 0.0, 200.0)
    relay.takes = False  # the other controller holds it on
    state, results = drive(
        relay,
        config,
        False,
        1000.0,
        1200.0,
        state,
        at=lambda s: relay.switch(s, True) if s == 1000 else None,
    )
    assert dict(results)[1000.0].write == RelayWrite(False, WriteKind.REWRITE)
    assert dict(results)[1000.0 + RELAY_CONFIRM_S - 10].events == ()
    late = dict(results)[1000.0 + RELAY_CONFIRM_S]
    assert late.judged is ChangeClass.ANOTHER_CONTROLLER
    assert late.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked


def test_a_change_a_day_after_the_rewrite_is_rewritten_again() -> None:
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay = Relay(on=True)
    state, _ = drive(relay, config, False, 0.0, 200.0)
    state, _ = drive(
        relay,
        config,
        False,
        1000.0,
        1100.0,
        state,
        at=lambda s: relay.switch(s, True) if s == 1000 else None,
    )
    later = 1000.0 + DAY + 10
    state, results = drive(
        relay,
        config,
        False,
        later,
        later + 50,
        state,
        at=lambda s: relay.switch(s, True) if s == later else None,
    )
    result = dict(results)[later]
    assert result.write == RelayWrite(False, WriteKind.REWRITE)
    assert result.events == ()
    assert state.rewritten_at == later
    assert not state.blocked


@pytest.mark.parametrize("cause", ["service_fails", "write_rate"])
@pytest.mark.parametrize("held", [True, False], ids=["held", "let_go"])
def test_a_rewrite_that_could_not_go_out_at_once_is_still_the_one_rewrite(
    cause: str, held: bool
) -> None:
    """PB-01 (a), answer C: the one rewrite whose service call fails — or that must wait for the
    write-rate guard — goes out at the next step as the rewrite again, not as a plain resend
    that forgets it: where the other controller holds the relay, the plugin steps aside 120 s
    after the rewrite was decided, and writes nothing more (before: resent every 5 min for
    good). Negative: where the other controller has let go, the retried rewrite is read back —
    no step aside, the day's rewrite spent."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    relay = Relay(on=True)
    state, _ = drive(relay, config, False, 0.0, 200.0)
    assert relay.on is False
    if cause == "write_rate":
        state = replace(state, written_at=997.0)  # a write attempt 3 s before
    relay.takes = not held
    state, results = drive(
        relay,
        config,
        False,
        1000.0,
        1400.0,
        state,
        at=lambda s: relay.switch(s, True) if s == 1000 else None,
        fails=(lambda s: s == 1000) if cause == "service_fails" else None,
    )
    by_t = dict(results)
    assert by_t[1000.0].judged is ChangeClass.ANOTHER_CONTROLLER
    assert by_t[1010.0].write == RelayWrite(False, WriteKind.REWRITE)  # still the rewrite
    assert state.rewritten_at == 1000.0
    if not held:
        assert events(results) == []
        assert not state.blocked
        assert not state.rewrite_pending
        assert relay.on is False
        return
    assert by_t[1000.0 + RELAY_CONFIRM_S - 10].events == ()
    late = by_t[1000.0 + RELAY_CONFIRM_S]  # 120 s after the rewrite was decided
    assert late.judged is ChangeClass.ANOTHER_CONTROLLER
    assert late.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked
    assert [w for w in relay.writes if w[0] > 1010.0] == []  # left alone


@pytest.mark.parametrize(
    ("power_on", "command", "steps_aside_at", "kind"),
    [
        # Answer N: no power-cut state known — a possible restart, three a day, the fourth steps
        # aside (each resend shown for a second, then reverted: never a step's "not confirmed").
        (RelayPowerOn.UNKNOWN, True, 1000.0 + 3 * RELAY_CONFIRM_S, WriteKind.RESEND),
        (RelayPowerOn.LAST, True, 1000.0 + 3 * RELAY_CONFIRM_S, WriteKind.RESEND),
        # Reverted to the declared power-cut state: answer D's restart, the same count.
        (RelayPowerOn.OFF, True, 1000.0 + 3 * RELAY_CONFIRM_S, WriteKind.RESEND),
        # Answer C: another state than the declared one — rewritten once; the rewrite reverted
        # at once is not read back: a step aside 120 s later.
        (RelayPowerOn.OFF, False, 1000.0 + RELAY_CONFIRM_S, WriteKind.REWRITE),
        (RelayPowerOn.ON, True, 1000.0 + RELAY_CONFIRM_S, WriteKind.REWRITE),
    ],
)
def test_a_controller_reverting_every_write_at_once_makes_the_plugin_step_aside(
    power_on: RelayPowerOn, command: bool, steps_aside_at: float, kind: WriteKind
) -> None:
    """PB-01 (b), answers C and N: an old automation switches the relay back within a second of
    every write of the plugin's, so no step ever sees the plugin's state — Home Assistant shows
    it for that second. A command shown and then put back is a change seen on the relay, never
    "not confirmed": counted as a restart (answer N) or another controller (answer C), so the
    plugin steps aside within minutes — its rest state is then the control unit's, written once
    — instead of starting the boiler every 5 min for good (the review's probe: 73 resends in 6 h,
    one restart counted)."""
    config = replace(REPORTING, power_on=power_on)
    relay = Relay(on=command)
    state, _ = drive(relay, config, command, 0.0, 300.0)
    assert state.start_done  # taken as it is, then held: the start phase is over
    assert relay.writes == []

    def automation(s: float) -> None:
        if s == 1000:
            relay.switch(s, not command)
            relay.reverts = True  # from now on, every write of the plugin's put back at once

    state, results = drive(relay, config, command, 990.0, 1000.0 + DAY, state, at=automation)
    assert events(results) == [(steps_aside_at, GuardEvent.OUTSIDE_CHANGE)]
    assert state.blocked
    sends = [(t, on, k) for t, on, k in relay.writes]
    assert sends[0] == (1000.0, command, kind)
    assert all(t < steps_aside_at for t, _on, _k in sends)  # then left alone
    assert len(sends) <= RESTARTS_ANSWERED
    assert all(r.judged is not ChangeClass.NOT_CONFIRMED for _t, r in results)
    assert not state.not_taken
    assert relay_check(state, config, reports=True) is RelayCheck.CHANGED_FROM_OUTSIDE


def test_a_revert_home_assistant_never_shows_is_a_relay_not_taking_the_command() -> None:
    """PB-01's negative: where Home Assistant never shows the plugin's state between the writes
    and the reverts (no moment of a change known), nothing tells the relay took the command: it
    is not judged another controller, and is left to the relay that does not take commands
    (decision 6): "not confirmed" first, then, three checks on, "not taken" — never counted as a
    restart."""
    config = replace(REPORTING, power_on=RelayPowerOn.UNKNOWN)
    relay = Relay(on=True, reports_change=False)
    state, _ = drive(relay, config, True, 0.0, 300.0)

    def automation(s: float) -> None:
        if s == 1000:
            relay.switch(s, False)
            relay.reverts = True

    state, results = drive(relay, config, True, 990.0, 3000.0, state, at=automation)
    by_t = dict(results)
    assert by_t[1000.0].restart  # the switch-off itself, after a confirmation: answer N
    assert len(state.restarts) == 1  # the resends never shown: no restart counted for them
    assert by_t[1000.0 + RELAY_CONFIRM_S].judged is ChangeClass.NOT_CONFIRMED
    assert events(results) == []
    assert not state.blocked
    assert state.not_taken  # stopped taking commands, as far as anything shows


@pytest.mark.parametrize("command", [True, False])
def test_a_relay_that_puts_itself_back_at_once_is_not_taking_the_command(command: bool) -> None:
    """PB-01's other side: a relay that puts itself back within a second of every write, by its
    own logic — an "inching" relay, a script on the device — so that Home Assistant files the
    change under the plugin's own context. Not another controller (the plugin's own context is
    never judged one), yet never left unjudged for good either: shown only for that second, the
    command counts as not shown — "not confirmed", sent again at each check, and after three
    checks "not taken" (decision 6 of 0.2.3): "on" still sent, "off" no longer — never a restart
    counted, never a step aside."""
    config = replace(REPORTING, power_on=RelayPowerOn.UNKNOWN)
    relay = Relay(on=not command, reverts=True, reverts_ours=True)
    state, _ = drive(relay, config, not command, 0.0, 300.0)
    assert state.start_done
    state, results = drive(relay, config, command, 1000.0, 2500.0, state)
    sends = [t for t, _on, _kind in relay.writes]
    assert sends[:3] == [1000.0, 1000.0 + RELAY_CHECK_S, 1000.0 + 2 * RELAY_CHECK_S]
    by_t = dict(results)
    assert by_t[1000.0 + RELAY_CONFIRM_S].judged is ChangeClass.NOT_CONFIRMED
    assert by_t[1000.0 + NOT_TAKEN_S].judged is ChangeClass.NOT_TAKEN
    assert state.not_taken
    assert state.off_not_taken is (not command)
    assert (1000.0 + NOT_TAKEN_S in sends) is command  # "on" sent again; "off" no longer
    assert state.restarts == ()
    assert not state.blocked
    assert events(results) == []


def test_a_revert_while_the_relay_reads_unknown_is_not_judged() -> None:
    """PB-01's negative: the relay's state unknown at every step after the plugin's writes —
    nothing judged, nothing counted, no step aside."""
    config = replace(REPORTING, power_on=RelayPowerOn.UNKNOWN)
    _relay, state = confirmed_on(config)
    unknown = RelaySeen(on=None, known=False, available=True, changed_at=1001.0)
    for t in (1000.0, 1120.0, 1240.0, 1360.0, 1480.0):
        result = plan_relay(state, True, unknown, t, config)
        assert result.judged is ChangeClass.NOT_JUDGED
        assert result.events == ()
        state = result.state
    assert state.restarts == ()
    assert not state.blocked


def no_warning_from(results: list[tuple[float, RelayResult]]) -> bool:
    """Whether the losses a run counted leave "commands lost" off at every step."""
    losses: tuple[tuple[float, str], ...] = ()
    warned = False
    for t, result in results:
        if result.lost:
            losses = add_loss(losses, t, "relay")
        warned = losses_warning(losses, t, warned)
        if warned:
            return False
    return True


@pytest.mark.parametrize("restarts_timer", [True, False])
def test_the_declared_timer_switching_off_is_its_own_lapse_not_counted(
    restarts_timer: bool,
) -> None:
    """R5 (SCOPE §5 class 3; Q1 matrix R5): a declared 10-min timer, renewed every 5 min. One
    that restarts its timer on a repeated "on" never lapses. One that does not switches off 10
    min after the "on" that started the on-period, every time, all day: its own lapse — "on"
    sent again at once, and not counted: no loss of any kind, "commands lost" never on; never
    another controller or a restart."""
    config = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=RelayTimer.MINUTES,
        timer_s=10 * MIN,
    )
    relay = Relay(timer_s=10 * MIN, restarts_timer=restarts_timer)
    state, results = drive(relay, config, True, 0.0, DAY)
    renewals = [t for t, on, kind in relay.writes if kind is WriteKind.KEEPALIVE]
    assert renewals[:2] == [300.0, 600.0] if restarts_timer else renewals[:1] == [300.0]
    assert events(results) == []
    assert state.rewritten_at is None
    assert state.restarts == ()
    assert not state.blocked
    assert lost(results) == []  # not counted, lapse or not
    assert no_warning_from(results)
    lapses = [t for t, result in results if result.judged is ChangeClass.OWN_LAPSE]
    if restarts_timer:
        assert lapses == []
        return
    assert lapses == [600.0 * n for n in range(1, 145)]  # every 10 minutes, all day
    for t in lapses:
        lapse = dict(results)[t]
        assert lapse.write == RelayWrite(True, WriteKind.RESEND)  # "on" at once
        assert not lapse.lost
        assert not lapse.restart
    assert relay.on


@pytest.mark.parametrize(
    ("power_on", "judged", "restart"),
    [
        (RelayPowerOn.ON, ChangeClass.ANOTHER_CONTROLLER, False),
        (RelayPowerOn.OFF, ChangeClass.LOST_COMMAND, True),
        (RelayPowerOn.LAST, ChangeClass.LOST_COMMAND, True),
        (RelayPowerOn.UNKNOWN, ChangeClass.LOST_COMMAND, True),
    ],
)
def test_an_early_switch_off_with_a_timer_is_another_controller(
    power_on: RelayPowerOn, judged: ChangeClass, restart: bool
) -> None:
    """A switch-off 400 s into a declared 10-min timer's on-period — not within 60 s of its
    length — is judged as any change while the relay stayed available: with "on after a power
    cut" another controller (rewritten once); with "off", "last" or "I don't know" R2a's possible
    restart (answer N)."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=power_on, timer=RelayTimer.MINUTES, timer_s=10 * MIN
    )
    relay = Relay()
    _state, results = drive(
        relay, config, True, 0.0, 400.0, at=lambda s: relay.switch(s, False) if s == 400 else None
    )
    result = dict(results)[400.0]  # before 540 s since the "on" at 0
    assert result.judged is judged
    assert result.restart is restart
    # Still judged, not a lapse: a possible restart (R2a) is counted, another controller not.
    assert result.lost is restart
    expected = WriteKind.REWRITE if judged is ChangeClass.ANOTHER_CONTROLLER else WriteKind.RESEND
    assert result.write == RelayWrite(True, expected)


@pytest.mark.parametrize(
    ("timer", "off_age", "since_renewal", "lapse"),
    [
        # Decision 6 of 0.2.3 (SB-05): a declared 10-min timer's lapse within 60 s of 10, 20 or
        # 30 min into the on-period.
        (RelayTimer.MINUTES, 540.0, False, True),
        (RelayTimer.MINUTES, 539.0, False, False),
        (RelayTimer.MINUTES, 600.0, False, True),
        (RelayTimer.MINUTES, 660.0, False, True),
        (RelayTimer.MINUTES, 661.0, False, False),
        (RelayTimer.MINUTES, 900.0, False, False),  # half-way: a person, an automation
        (RelayTimer.MINUTES, 1200.0, False, True),  # twice: a renewal hid one lapse
        (RelayTimer.MINUTES, 1261.0, False, False),
        (RelayTimer.MINUTES, 1800.0, False, True),  # three times
        (RelayTimer.MINUTES, 2400.0, False, False),  # four times: beyond three
        (RelayTimer.MINUTES, 2700.0, False, False),  # 45 min into a long run (the probe)
        # Since the last renewal ("on" sent again), where it is not since the on-period's "on".
        (RelayTimer.MINUTES, 600.0, True, True),
        (RelayTimer.MINUTES, 450.0, True, False),
        # Negative: no timer declared — never a lapse, whatever the age.
        (RelayTimer.NONE, 600.0, False, False),
    ],
)
def test_a_declared_timer_lapses_only_near_a_whole_multiple_of_its_length(
    timer: RelayTimer, off_age: float, since_renewal: bool, lapse: bool
) -> None:
    """SB-05 (decision 6 of 0.2.3): a switch-off is a declared timer's lapse — "on" again, not
    counted — only within 60 s of a whole multiple of its length, at most three, since the "on"
    that started the on-period or since the last renewal; any other switch-off is a change seen
    on the relay, under answers C and N (here, found in its declared power-cut state, "off": a
    restart the relay did not report, counted). Before, anything from max(timer − 60 s, timer ÷
    2) on was the timer's — a person or an automation switching the boiler off 45 min into a
    run was overridden for good."""
    config = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=timer,
        timer_s=10 * MIN if timer is RelayTimer.MINUTES else None,
    )
    renewed = 1000.0  # the last "on" sent, at 1000 s into an on-period begun at 0
    off_at = (renewed if since_renewal else 0.0) + off_age
    state = RelayState(
        written=True,
        written_at=renewed if since_renewal else 0.0,
        sent_at=0.0,
        on_since=0.0,
        confirmed_at=10.0,
        held_since=10.0,
        start_done=True,
    )
    seen = RelaySeen(on=False, known=True, available=True, changed_at=off_at)
    result = plan_relay(state, True, seen, off_at + 5.0, config)
    assert result.write == RelayWrite(True, WriteKind.RESEND)  # "on" again at once, either way
    if lapse:
        assert result.judged is ChangeClass.OWN_LAPSE
        assert not result.lost
        assert result.state.restarts == ()
    else:
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.restart  # counted toward answer N
        assert result.state.restarts == (off_at + 5.0,)


@pytest.mark.parametrize("changed_at", [600.0, None], ids=["moment_shown", "no_moment"])
def test_a_switch_off_with_no_on_period_known_is_no_declared_timers_lapse(
    changed_at: float | None,
) -> None:
    """SB-05's negative: with no on-period start known — and Home Assistant showing the
    switch-off's moment or not — nothing can be measured against the declared timer: the
    switch-off is a change seen on the relay (here a restart counted), never taken for its
    lapse."""
    config = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=RelayTimer.MINUTES,
        timer_s=10 * MIN,
    )
    state = RelayState(
        written=True, written_at=0.0, sent_at=0.0, confirmed_at=10.0, start_done=True
    )
    seen = RelaySeen(on=False, known=True, available=True, changed_at=changed_at)
    result = plan_relay(state, True, seen, 605.0, config)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.restart


@pytest.mark.parametrize(
    ("power_on", "steps_aside_after"),
    [(RelayPowerOn.OFF, 4), (RelayPowerOn.ON, 2), (RelayPowerOn.UNKNOWN, 4)],
    ids=["off_answer_n", "on_answer_c", "unknown_answer_n"],
)
def test_late_switch_offs_with_a_declared_timer_make_the_plugin_step_aside(
    power_on: RelayPowerOn, steps_aside_after: int
) -> None:
    """SB-05's probe: a declared 30-min timer, and an automation switching the relay off 45 min
    into each on-period while the rooms call. Before, all 15 switch-offs in 12 h were taken for
    the timer's lapse and answered for good. Now each is a change seen on the relay: with the
    power-cut state "off" (or "I don't know") a restart the relay did not report — three a day
    answered, the fourth steps aside (answer N); with "on", another controller — rewritten once,
    the second steps aside (answer C). Then nothing more is written."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=power_on, timer=RelayTimer.MINUTES, timer_s=30 * MIN
    )
    relay = Relay(restarts_timer=False)  # ``on_at``: the start of its on-period
    offs: list[float] = []

    def automation(s: float) -> None:
        if relay.on and relay.on_at is not None and s - relay.on_at >= 45 * MIN:
            relay.switch(s, False)
            offs.append(s)

    state, results = drive(relay, config, True, 0.0, 12 * HOUR_S, at=automation)
    assert state.blocked
    assert len(offs) == steps_aside_after
    assert events(results) == [(offs[-1], GuardEvent.OUTSIDE_CHANGE)]
    assert all(r.judged is not ChangeClass.OWN_LAPSE for _t, r in results)
    assert [t for t, _on, _kind in relay.writes if t >= offs[-1]] == []  # left alone
    assert offs[-1] <= 3 * HOUR_S + 60.0


@pytest.mark.parametrize(("switch_at", "lapse"), [(300.0, True), (290.0, False)])
def test_an_unknown_timer_gets_on_repeats_and_a_late_switch_off_is_answered_and_counted(
    switch_at: float, lapse: bool
) -> None:
    """A timer "I don't know": "on" repeated every repeat interval while commanded on; a
    switch-off at least one repeat interval after the start of the on-period may be its lapse —
    "on" again at once, counted as answer N's restart (Z4-02); an earlier one is judged as any
    change while available — with "on after a power cut" another controller. "Off" is not
    repeated. A relay whose real timer lapses all day, the same time into each on-period, is
    answered every time: its first lapse is counted, the second shows the relay's own timer
    (Z4R-02)."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.ON, timer=RelayTimer.UNKNOWN
    )
    relay = Relay()
    state, results = drive(relay, config, True, 0.0, 280.0)
    assert [t for t, _on, kind in relay.writes if kind is WriteKind.KEEPALIVE] == []
    state, results = drive(
        relay,
        config,
        True,
        290.0,
        320.0,
        state,
        at=lambda s: relay.switch(s, False) if s == switch_at else None,
    )
    result = dict(results)[switch_at]
    assert result.lost is lapse  # a possible restart is counted; another controller is not
    assert result.restart is lapse
    if lapse:
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.write == RelayWrite(True, WriteKind.RESEND)
    else:
        assert result.judged is ChangeClass.ANOTHER_CONTROLLER
        assert result.write == RelayWrite(True, WriteKind.REWRITE)
    # "On" repeated at the repeat interval; "off" never.
    relay = Relay()
    drive(relay, config, lambda t: t < 1000, 0.0, 4000.0)
    repeats = [(t, on) for t, on, kind in relay.writes if kind is WriteKind.KEEPALIVE]
    assert repeats == [(300.0, True), (600.0, True), (900.0, True)]
    # A real 10-min timer the repeated "on" does not restart: it lapses 10 minutes into each
    # on-period — the first counted, then the relay's own timer: answered all day, uncounted.
    relay = Relay(timer_s=10 * MIN, restarts_timer=False)
    state, results = drive(relay, config, True, 0.0, DAY)
    assert lost(results) == [600.0]
    lapses = [t for t, r in results if r.judged is ChangeClass.OWN_LAPSE]
    assert lapses == [600.0 * n for n in range(2, 145)]
    assert all(dict(results)[t].write == RelayWrite(True, WriteKind.RESEND) for t in lapses)
    assert events(results) == []
    assert not state.blocked
    assert state.timer_seen_s == 600.0
    assert relay.on


@pytest.mark.parametrize("power_on", [RelayPowerOn.OFF, RelayPowerOn.ON])
@pytest.mark.parametrize(
    ("timer", "timer_s"),
    [(RelayTimer.UNKNOWN, None), (RelayTimer.MINUTES, 10 * MIN)],
    ids=["unknown", "declared"],
)
def test_an_unknown_timer_lapse_is_bounded_by_answer_n(
    power_on: RelayPowerOn, timer: RelayTimer, timer_s: float | None
) -> None:
    """Z4-02 (answers C, D, L, N), with Z4R-02's regularity rule: with the timer "I don't know",
    a switch-off at least one repeat interval into an on-period may be the timer's lapse — or an
    automation, a person, the relay's own button. Switch-offs at irregular times into their
    on-periods — 11, 17, 29 and 47 min — are answered with "on" at once, but counted as answer N's
    restarts: three within a day sent again and counted, the fourth is another controller — the
    plugin steps aside at once, with no rewrite, and writes nothing more; no timer is taken as
    seen. With a declared 10-min timer only the switch-offs within 60 s of a whole multiple of
    it, at most three, are its own lapses — "on" again, never counted — here 11 and 29 min in; 17,
    47 and 13 min in are changes seen on the relay, under answers C and N (decision 6 of
    0.2.3)."""
    config = RelayConfig(reports=RelayReports.YES, power_on=power_on, timer=timer, timer_s=timer_s)
    relay = Relay()
    offs = []
    start = 0.0
    for minutes in (11, 17, 29, 47, 13):  # into each on-period; "on" again at once each time
        start += minutes * MIN
        offs.append(start)
    state, results = drive(
        relay,
        config,
        True,
        0.0,
        offs[-1] + 120.0,
        at=lambda s: relay.switch(s, False) if s in offs else None,
    )
    seen = dict(results)
    if timer is RelayTimer.MINUTES:
        lapses = [offs[0], offs[2]]
        for t in lapses:
            assert seen[t].judged is ChangeClass.OWN_LAPSE
            assert seen[t].write == RelayWrite(True, WriteKind.RESEND)
            assert not seen[t].lost
            assert not seen[t].restart
        counted = [t for t in offs if t not in lapses]
        assert state.timer_seen_s is None  # declared: nothing to learn
        if power_on is RelayPowerOn.OFF:
            assert all(seen[t].restart for t in counted)  # answer N: three, no fourth yet
            assert state.restarts == tuple(counted)
            assert events(results) == []
            assert not state.blocked
            assert relay.on
            return
        assert seen[offs[1]].write == RelayWrite(True, WriteKind.REWRITE)  # answer C: once
        assert events(results) == [(offs[3], GuardEvent.OUTSIDE_CHANGE)]  # then a step aside
        assert state.blocked
        return
    for t in offs[:3]:
        assert seen[t].judged is ChangeClass.LOST_COMMAND
        assert seen[t].write == RelayWrite(True, WriteKind.RESEND)  # "on" again at once
        assert seen[t].lost
        assert seen[t].restart  # stored at once
    assert state.restarts == tuple(offs[:3])
    fourth = seen[offs[3]]
    assert fourth.judged is ChangeClass.ANOTHER_CONTROLLER
    assert fourth.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert fourth.write is None  # no rewrite first: it steps aside
    assert state.blocked
    assert state.rewritten_at is None
    assert state.timer_seen_s is None  # irregular: no timer of its own
    assert events(results) == [(offs[3], GuardEvent.OUTSIDE_CHANGE)]
    assert [t for t, on, _kind in relay.writes if t > offs[3]] == []  # left alone
    assert not relay.on


@pytest.mark.parametrize(
    ("timer_min", "reports_change"),
    [(30, True), (10, True), (30, False)],
    ids=["30_min", "10_min", "30_min_no_change_time"],
)
def test_an_undeclared_timer_lapsing_regularly_is_not_counted(
    timer_min: int, reports_change: bool
) -> None:
    """Z4R-02: the timer left at "I don't know"; a real timer that a repeated "on" does not
    restart (a Shelly's auto-off, say) switches the relay off the same time into every on-period
    while the rooms call for six hours. The first switch-off counts as a possible restart (answer
    N); the second, within 60 s of the first's age, shows the relay's own timer of that length:
    answered with "on" at once, no longer counted — never another controller, never a step aside
    (before: the fourth stepped aside, after 40 min to 2 h). Also where Home Assistant shows no
    moment of the change (the step's own time is taken)."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    period = timer_min * MIN
    relay = Relay(timer_s=period, restarts_timer=False, reports_change=reports_change)
    state, results = drive(relay, config, True, 0.0, 6 * HOUR_S)
    switch_offs = [
        t for t, r in results if r.judged in (ChangeClass.LOST_COMMAND, ChangeClass.OWN_LAPSE)
    ]
    assert len(switch_offs) == int(6 * HOUR_S // period)
    assert lost(results) == switch_offs[:1]  # the first only
    assert dict(results)[switch_offs[0]].restart
    assert all(dict(results)[t].judged is ChangeClass.OWN_LAPSE for t in switch_offs[1:])
    assert all(dict(results)[t].write == RelayWrite(True, WriteKind.RESEND) for t in switch_offs)
    assert events(results) == []
    assert not state.blocked
    assert state.restarts == tuple(switch_offs[:1])
    assert state.timer_seen_s is not None
    assert abs(state.timer_seen_s - period) <= 10.0
    assert relay.on


@pytest.mark.parametrize("seen_by_ha", [False, True], ids=["no_trace", "brief_off_shown"])
def test_a_lapse_a_renewal_hid_still_shows_the_relays_timer(seen_by_ha: bool) -> None:
    """Z4R-02 with the plugin's own renewals: a 30-min timer that a repeated "on" does not
    restart, renewed every 5 min — its first lapse comes the moment a renewal arrives, which
    turns it on again and restarts its timer before the plugin looks. Where Home Assistant shows
    that brief change, the on-period is counted from it, and the next lapse comes 30 min into
    it; where it shows nothing, the next is seen 60 min into the on-period — a whole multiple of
    the 30 min seen next. Either way, the second lapse seen shows the relay's own timer of 30
    min: one counted, then answered and uncounted, never a step aside."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(
        timer_s=30 * MIN,
        restarts_timer=False,
        masks=lambda t: t == 30 * MIN,  # the first lapse only
        masked_seen=seen_by_ha,
    )
    state, results = drive(relay, config, True, 0.0, 4 * HOUR_S)
    seen = [t for t, r in results if r.judged in (ChangeClass.LOST_COMMAND, ChangeClass.OWN_LAPSE)]
    assert seen[:3] == [60 * MIN, 90 * MIN, 120 * MIN]  # the one at 30 min hidden
    assert lost(results) == seen[:1]
    assert state.lapses[0][1] == (30 * MIN if seen_by_ha else 60 * MIN)
    assert state.timer_seen_s == 30 * MIN
    assert events(results) == []
    assert not state.blocked


def test_a_timer_first_seen_at_a_multiple_is_corrected_to_its_length() -> None:
    """Z4R-02: renewals hid every other lapse of a 30-min timer, with no trace — the plugin sees
    two lapses 60 min into their on-periods and takes 60 min for the relay's timer; the next
    lapse seen 30 min in shows the shorter length: answered, uncounted, and the timer seen is
    corrected to 30 min (the issue then names 30 min)."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(
        timer_s=30 * MIN,
        restarts_timer=False,
        masks=lambda t: t in (30 * MIN, 90 * MIN),
    )
    state, results = drive(relay, config, True, 0.0, 150 * MIN)
    seen = [t for t, r in results if r.judged in (ChangeClass.LOST_COMMAND, ChangeClass.OWN_LAPSE)]
    assert seen == [60 * MIN, 120 * MIN, 150 * MIN]
    assert lost(results) == seen[:1]
    assert state.lapses[0][1] == 60 * MIN
    assert state.timer_seen_s == 30 * MIN
    assert events(results) == []
    assert not state.blocked


def test_a_switch_off_like_one_a_day_before_shows_no_timer() -> None:
    """Z4R-02: the switch-offs kept to compare are those of the last day, as the restarts. A
    30-min timer's lapse, then no demand for a day, then its lapse again: the one a day before
    no longer counts, so this one is counted, and no timer is taken as seen yet."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(timer_s=30 * MIN, restarts_timer=False)
    back = DAY + 2000.0
    state, results = drive(relay, config, lambda t: t < 2000.0 or t >= back, 0.0, back + 1900.0)
    assert lost(results) == [30 * MIN, back + 30 * MIN]
    assert state.timer_seen_s is None
    assert state.lapses == ((back + 30 * MIN, 30 * MIN),)


def test_whole_multiples_count_only_for_a_timer_of_ten_minutes_or_more() -> None:
    """Z4R-02's bound on multiples, at K4.2's shortest timer recognised (10 min): switch-offs 8,
    16.5 and 23.5 min into their on-periods — one, two and three times 8 min, within 60 s — are
    not taken for one 8-min timer (before K4.2 the second showed it): each counts, and the fourth
    — 5 min in — steps aside."""
    config = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=RelayTimer.UNKNOWN,
        repeat_s=120.0,
    )
    relay = Relay()
    offs = []
    start = 0.0
    for minutes in (8, 16.5, 23.5, 5):
        start += minutes * MIN
        offs.append(start)
    state, results = drive(
        relay,
        config,
        True,
        0.0,
        offs[-1] + 60.0,
        at=lambda s: relay.switch(s, False) if s in offs else None,
    )
    seen = dict(results)
    assert [seen[t].judged for t in offs[:3]] == [ChangeClass.LOST_COMMAND] * 3
    assert seen[offs[3]].judged is ChangeClass.ANOTHER_CONTROLLER
    assert state.timer_seen_s is None
    assert short_switch_off_s(state, offs[-1]) is None  # irregular: no length to name
    assert state.blocked
    assert state.short_off_s is None


@pytest.mark.parametrize("restarts", [True, False], ids=["restarted_by_on", "not_restarted"])
def test_a_twelve_minute_timer_is_still_recognised_and_renewed(restarts: bool) -> None:
    """K4.2: a 12-min timer is long enough to be taken for the relay's own. One that "on" does
    not restart lapses 12 min into every on-period — the first counted, then recognised (720 s):
    answered, uncounted, and "on" renewed every min(length ÷ 2, repeat interval), here the repeat
    interval. One that "on" restarts never lapses under the renewals: nothing counted, nothing
    to recognise."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(timer_s=12 * MIN, restarts_timer=restarts)
    state, results = drive(relay, config, True, 0.0, 3 * HOUR_S)
    renewals = [t for t, _on, kind in relay.writes if kind is WriteKind.KEEPALIVE]
    assert events(results) == []
    assert not state.blocked
    assert relay.on
    if restarts:
        assert lost(results) == []
        assert state.timer_seen_s is None
        assert renewals[:3] == [300.0, 600.0, 900.0]
        return
    assert lost(results) == [12 * MIN]
    assert state.timer_seen_s == 12 * MIN
    lapses = [t for t, r in results if r.judged is ChangeClass.OWN_LAPSE]
    assert lapses == [12 * MIN * n for n in range(2, 16)]
    after = [t for t in renewals if t > lapses[0]]
    assert after[0] - lapses[0] == 300.0  # the repeat interval: min(360, 300)
    assert short_switch_off_s(state, 3 * HOUR_S) is None  # long enough: the relay's own


@pytest.mark.parametrize("repeat_s", [60.0, 300.0], ids=["repeat_60s", "repeat_300s"])
def test_a_short_regular_switch_off_counts_and_steps_aside_at_the_fourth(repeat_s: float) -> None:
    """K4.2 (Z4R3-02): a relay switching itself off 2 min after every "on" — an "inching" timer
    that "on" does not restart, or an automation — is regular, but shorter than 10 min: never
    taken for the relay's own timer. Each switch-off is answered with "on" and counted toward
    answer N, before the repeat interval as after it; the fourth within a day steps aside —
    about 8 minutes in, not ~30 boiler starts an hour for good — and the length seen is there
    for the latch issue to name. Also where Home Assistant shows no moment of the change."""
    config = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=RelayTimer.UNKNOWN,
        repeat_s=repeat_s,
    )
    for reports_change in (True, False):
        relay = Relay(timer_s=2 * MIN, restarts_timer=False, reports_change=reports_change)
        state, results = drive(relay, config, True, 0.0, 2 * HOUR_S)
        assert lost(results) == [120.0, 240.0, 360.0], reports_change
        assert events(results) == [(480.0, GuardEvent.OUTSIDE_CHANGE)]
        assert state.blocked
        assert state.timer_seen_s is None  # never taken for the relay's own
        assert [age for _at, age in state.lapses] == [120.0] * 3  # each kept with its age
        short = short_switch_off_s(state, 2 * HOUR_S)
        assert short is not None
        assert abs(short - 120.0) <= 10.0
        assert state.short_off_s == short  # noted with the step aside, for the latch issue
        ons = [t for t, on, _kind in relay.writes if on]
        assert len(ons) <= 8  # then left alone: no boiler start every 2 minutes


@pytest.mark.parametrize("timer_s", [599.0, 545.0])
def test_a_ten_minute_timer_measured_a_little_short_is_the_relays_own(timer_s: float) -> None:
    """KD-02: the shortest timer taken for the relay's own is 10 min, and a measured age may be a
    minute off: switch-offs recurring 599 s or 545 s into their on-periods — a 10-min timer
    measured short — are the relay's own (from 540 s on): the first counted, then answered and
    uncounted, never a step aside (before: counted at 10, 20 and 30 min, a step aside at 40, a
    cold house). The form's floor for a declared timer stays 10 min."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(timer_s=timer_s, restarts_timer=False)
    state, results = drive(relay, config, True, 0.0, 3 * HOUR_S)
    counted = lost(results)
    assert len(counted) == 1  # the first: nothing to compare it with yet
    assert timer_s <= counted[0] < timer_s + 10.0  # seen at the next step
    assert events(results) == []
    assert not state.blocked
    assert state.timer_seen_s is not None
    assert abs(state.timer_seen_s - timer_s) <= 10.0
    assert relay.on
    with pytest.raises(ValueError, match="10 to 120"):
        RelayConfig(timer=RelayTimer.MINUTES, timer_s=timer_s)  # declared: 10 min at least


@pytest.mark.parametrize("timer_s", [535.0, 120.0])
def test_a_regular_switch_off_under_nine_minutes_counts_toward_answer_n(timer_s: float) -> None:
    """KD-02's other side: switch-offs recurring 535 s or 120 s into their on-periods are short of
    10 min by more than a minute: counted toward answer N, the fourth within a day steps aside,
    and the length is noted for the latch issue."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(timer_s=timer_s, restarts_timer=False)
    state, results = drive(relay, config, True, 0.0, 3 * HOUR_S)
    assert len(lost(results)) == 3
    assert [event for _t, event in events(results)] == [GuardEvent.OUTSIDE_CHANGE]
    assert all(abs(age - timer_s) <= 10.0 for _at, age in state.lapses)
    assert state.blocked
    assert state.timer_seen_s is None
    assert state.short_off_s is not None
    assert abs(state.short_off_s - timer_s) <= 10.0


def test_a_short_regular_switch_off_is_named_only_where_two_agree() -> None:
    """The length the latch issue names (K4.2): two of the day's counted switch-offs the same
    time into their on-periods, within 60 s, and shorter than 10 min; none for irregular ones,
    for a length of 10 min or more (the relay's own timer), or for ones over a day old."""

    def named(*lapses: tuple[float, float], now: float = 5000.0) -> float | None:
        return short_switch_off_s(RelayState(lapses=lapses), now)

    assert named((100.0, 120.0), (400.0, 150.0)) == 135.0
    assert named((100.0, 120.0), (400.0, 300.0), (900.0, 290.0)) == 295.0
    assert named((100.0, 120.0)) is None
    assert named((100.0, 120.0), (400.0, 190.0)) is None  # 70 s apart
    assert named((100.0, 590.0), (900.0, 640.0)) is None  # 615 s: the relay's own
    assert named((100.0, 545.0), (900.0, 550.0)) is None  # 547.5 s: within a minute of 10 min
    assert named((100.0, 530.0), (900.0, 540.0)) == 535.0  # under 9 min: short (KD-02)
    assert named((100.0, 120.0), (400.0, 130.0), now=100.0 + DAY) is None  # the first expired
    assert named() is None


def test_an_irregular_switch_off_after_the_timer_was_seen_still_counts() -> None:
    """Z4R-02's other side: once the relay's own timer has been seen (about 10 min), a
    switch-off at another time into the on-period — an automation, a person — still counts
    toward answer N, and the fourth within a day steps aside; switch-offs at the timer's age stay
    answered and uncounted."""
    config = RelayConfig(
        reports=RelayReports.YES, power_on=RelayPowerOn.OFF, timer=RelayTimer.UNKNOWN
    )
    relay = Relay(timer_s=10 * MIN, restarts_timer=False)
    state, results = drive(relay, config, True, 0.0, 3000.0)
    assert state.timer_seen_s == 600.0
    assert len(state.restarts) == 1  # the first lapse
    # From now on, someone switches it off 6 min into each on-period, before the timer.
    on_since = state.on_since
    assert on_since is not None
    offs = [on_since + 360.0 * n for n in range(1, 4)]
    state, results = drive(
        relay,
        config,
        True,
        3010.0,
        offs[-1] + 60.0,
        state,
        at=lambda s: relay.switch(s, False) if s in offs else None,
    )
    seen = dict(results)
    assert [seen[t].judged for t in offs[:2]] == [ChangeClass.LOST_COMMAND] * 2
    assert seen[offs[2]].judged is ChangeClass.ANOTHER_CONTROLLER  # the fourth in the day
    assert seen[offs[2]].events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked
    assert state.timer_seen_s == 600.0


def test_three_losses_in_a_day_raise_commands_lost() -> None:
    """Two do not; the warning clears after a day without a loss; it never stops writing."""
    relay, state = confirmed_on()
    losses: tuple[tuple[float, str], ...] = ()
    warned = False
    moments = (1000.0, 2000.0, 3000.0)
    for t in moments:
        state, results = drive(
            relay,
            REPORTING,
            True,
            t,
            t + 20,
            state,
            at=lambda s, t=t: relay.back(s, False) if s == t else None,
        )
        assert lost(results) == [t]
        assert relay.writes[-1] == (t, True, WriteKind.RESEND)  # written at once, warning or not
        losses = add_loss(losses, t, "relay")
        warned = losses_warning(losses, t, warned)
        assert warned is (t == moments[-1])
    assert losses_warning(losses, moments[-1] + DAY - 10, warned)
    assert not losses_warning(losses, moments[-1] + DAY, warned)


@pytest.mark.parametrize(
    ("repeat_s", "expected"),
    [
        (300.0, [300.0, 750.0]),
        (60.0, [60.0 * n for n in range(1, 8)] + [450.0 + 60.0 * n for n in range(1, 9)]),
    ],
)
def test_a_relay_without_a_state_gets_blind_repeats(repeat_s: float, expected: list[float]) -> None:
    """Declared "no": its current command — on or off — every repeat interval (300 s, or the one
    carried over); never judged, a change at the relay undone at the next repeat."""
    config = RelayConfig(reports=RelayReports.NO, repeat_s=repeat_s)
    relay = Relay()
    _state, results = drive(
        relay,
        config,
        lambda t: t < 450,
        0.0,
        950.0,
        at=lambda s: relay.switch(s, False) if s == 100 else None,
    )
    repeats = [t for t, _on, kind in relay.writes if kind is WriteKind.KEEPALIVE]
    assert repeats == expected
    values = {t: on for t, on, _kind in relay.writes}
    assert values[450.0] is False  # the new command at once
    assert all(values[t] is (t < 450) for t in repeats)  # "off" repeated too
    assert events(results) == []
    assert lost(results) == []


@pytest.mark.parametrize("reports", [RelayReports.NO, RelayReports.UNKNOWN])
def test_a_relay_without_a_state_gets_its_command_at_once_when_it_returns(
    reports: RelayReports,
) -> None:
    """PB-44 (R6): a relay that reports no state — declared "no", or "I don't know", the default
    — gets its current command at once when it comes back within reach, as the issue's text
    says, not at the next blind repeat (before: back at 160 s, written at 300 s); the repeats
    count on from that write. Back between two steps (a blip the steps never saw) counts too.
    Negative: nothing is written while it is out of reach, and without a return the repeat
    interval holds."""
    config = RelayConfig(reports=reports)
    relay = Relay()

    def link(s: float) -> None:
        if s == 100:
            relay.away(s)
        elif s == 160:
            relay.back(s, False)  # its state after the outage: not the command
        elif s == 600:
            relay.away(s - 6)
            relay.back(s - 3, False)

    _state, results = drive(relay, config, True, 0.0, 950.0, at=link)
    assert relay.writes == [
        (0.0, True, WriteKind.CHANGE),
        (160.0, True, WriteKind.RESEND),  # at once on its return
        (460.0, True, WriteKind.KEEPALIVE),  # the repeat interval from that write
        (600.0, True, WriteKind.RESEND),  # back between two steps
        (900.0, True, WriteKind.KEEPALIVE),
    ]
    assert events(results) == []
    assert lost(results) == [160.0, 600.0]  # back off while commanded on: counted (M1)
    # A relay that reports its state, back in the commanded state: nothing to send.
    reporting, state = confirmed_on()
    state, _ = drive(
        reporting,
        REPORTING,
        True,
        1000.0,
        1300.0,
        state,
        at=lambda s: (
            reporting.away(s) if s == 1000 else reporting.back(s, True) if s == 1100 else None
        ),
    )
    assert reporting.writes == [(0.0, True, WriteKind.CHANGE)]


def drops_every_minute(relay: Relay, back_on: bool) -> Callable[[float], None]:
    """Out of reach for one step every minute, then back — off after a power loss, or on after a
    link loss alone."""

    def at(t: float) -> None:
        if t > 0 and t % 60 == 0:
            relay.away(t)
        elif t > 0 and t % 60 == 10:
            relay.back(t, back_on)

    return at


@pytest.mark.parametrize(
    ("reports", "back_on", "counted"),
    [
        (RelayReports.UNKNOWN, False, True),  # back in another state
        (RelayReports.NO, False, True),
        (RelayReports.UNKNOWN, True, False),  # back as commanded: nothing lost
        (RelayReports.NO, True, True),  # no state shown, commanded on
    ],
)
def test_a_relay_without_a_state_dropping_out_every_minute_is_written_as_its_repeat_would(
    reports: RelayReports, back_on: bool, counted: bool
) -> None:
    """M1 of the part-1 check (PB-44 bounded): a relay that reports no state, commanded on for an
    hour, drops out every minute. Before, every return got "on" at once — 60 boiler starts in the
    hour after a power loss each time, against 11 with the repeat alone, and no alarm. A return's
    command at once now comes at most once each check interval, and not within the confirmation
    timeout of a write; the returns between wait for the regular repeat — one write each 5 min,
    as the repeat alone gave. Each return in another state — or, with no state shown, any return
    while commanded on — counts toward "commands lost", so the flapping is shown."""
    relay = Relay(on=True)
    _state, results = drive(
        relay,
        RelayConfig(reports=reports),
        True,
        0.0,
        HOUR_S,
        at=drops_every_minute(relay, back_on),
    )
    assert relay.writes == [(0.0, True, WriteKind.CHANGE)] + [
        (130.0 + RELAY_CHECK_S * n, True, WriteKind.RESEND) for n in range(12)
    ]
    assert relay.starts == ([] if back_on else [t for t, _on, _kind in relay.writes[1:]])
    returns = [10.0 + MIN * n for n in range(60)]  # back at 10 s past every minute
    assert lost(results) == (returns if counted else [])
    assert events(results) == []


def test_a_relay_knocked_out_by_each_on_is_started_no_more_often_than_its_repeat() -> None:
    """M1 of the part-1 check: a relay that reports no state and drops out a few seconds after
    each "on" it is given — the boiler's start on its supply, or interference at the ignition —
    comes back off. Its command at once would start the boiler again at once; a return within
    the confirmation timeout of a write waits for the regular repeat, so the boiler starts once
    each repeat interval, as before PB-44, and the returns count toward "commands lost"."""
    relay = Relay(on=False)

    def knocked_out(t: float) -> None:
        if relay.writes and t - relay.writes[-1][0] == 10.0 and relay.on:
            relay.away(t - 6.0)
            relay.back(t - 3.0, False)

    _state, results = drive(relay, RelayConfig(), True, 0.0, HOUR_S, at=knocked_out)
    assert relay.starts == [300.0 * n for n in range(13)]
    assert [kind for _t, _on, kind in relay.writes[1:]] == [WriteKind.KEEPALIVE] * 12
    assert lost(results) == [10.0 + 300.0 * n for n in range(12)]


def test_a_relay_without_a_state_unknown_for_good_gets_only_its_repeats() -> None:
    """Negatives (M1): a relay that stays "unknown" is no return — only its regular repeats, no
    loss; a return with no command, or before any command, counts nothing and writes only a new
    command."""
    relay = Relay(on=None)  # within reach, its state unknown
    _state, results = drive(relay, RelayConfig(), True, 0.0, 950.0)
    assert relay.writes == [(0.0, True, WriteKind.CHANGE)] + [
        (300.0 * n, True, WriteKind.KEEPALIVE) for n in (1, 2, 3)
    ]
    assert lost(results) == []
    back = RelaySeen(on=False, known=True, available=True, returned=True)
    held = RelayState(written=True, written_at=0.0, on_since=0.0)
    none = plan_relay(held, None, back, 1000.0, RelayConfig())
    assert (none.write, none.lost) == (None, False)
    first = plan_relay(RelayState(), True, back, 1000.0, RelayConfig())
    assert first.write == RelayWrite(True, WriteKind.CHANGE)
    assert not first.lost
    unknown = replace(back, on=None, known=False)
    assert plan_relay(held, True, unknown, 1000.0, RelayConfig(reports=RelayReports.NO)).lost


@pytest.mark.parametrize(
    ("timer_min", "repeat_s", "every"), [(10, 300.0, 300.0), (10, 120.0, 120.0), (20, 300.0, 300.0)]
)
def test_a_timer_relay_is_renewed_at_half_its_timer(
    timer_min: int, repeat_s: float, every: float
) -> None:
    """ "On" renewed every min(timer ÷ 2, repeat interval) while commanded on — never less often
    than the repeat interval; nothing while off."""
    config = RelayConfig(
        reports=RelayReports.YES,
        timer=RelayTimer.MINUTES,
        timer_s=timer_min * MIN,
        repeat_s=repeat_s,
    )
    relay = Relay(timer_s=timer_min * MIN)
    drive(relay, config, lambda t: t < 1200, 0.0, 3000.0)
    renewals = [t for t, on, kind in relay.writes if kind is WriteKind.KEEPALIVE]
    assert renewals == [every * n for n in range(1, 20) if every * n < 1200]
    assert all(on for t, on, kind in relay.writes if kind is WriteKind.KEEPALIVE)


def test_an_unconfirmed_command_is_reported_and_clears_when_it_holds() -> None:
    """``write_ignored`` 120 s after a send not read back; cleared once the relay has held the
    command for 120 s."""
    relay = Relay(takes=False)
    state, results = drive(relay, REPORTING, True, 0.0, 110.0)
    assert not relay_write_ignored(state)
    state, results = drive(relay, REPORTING, True, 120.0, 250.0, state)
    assert dict(results)[120.0].judged is ChangeClass.FAILED_ATTEMPT
    assert relay_write_ignored(state)
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.NOT_CONFIRMED
    relay.takes = True
    state, results = drive(relay, REPORTING, True, 260.0, 410.0, state)
    assert relay.writes[-1] == (300.0, True, WriteKind.RESEND)  # sent again at the next check
    assert relay_write_ignored(state)  # held 110 s so far
    state, _ = drive(relay, REPORTING, True, 420.0, 430.0, state)
    assert not relay_write_ignored(state)
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.CONFIRMED


@pytest.mark.parametrize("command", [True, False])
def test_a_relay_that_never_takes_the_command_is_ignored_from_the_start(command: bool) -> None:
    """Never the commanded state for longer than 120 s after each of the session's first three
    sends: not written again this session, repeats included — "ignored from the start" (R7).
    Where it is "off" that it ignores, the plugin can no longer switch heating off (answer O);
    where it is "on", it cannot make the boiler heat (decision 4 of 0.2.3, SB-03)."""
    config = RelayConfig(reports=RelayReports.YES, timer=RelayTimer.UNKNOWN)
    relay = Relay(on=not command, takes=False)
    state, results = drive(relay, config, command, 0.0, 3600.0)
    assert [t for t, _on, _kind in relay.writes] == [0.0, 300.0, 600.0]
    assert events(results) == [(720.0, GuardEvent.IGNORED)]
    assert dict(results)[720.0].judged is ChangeClass.IGNORED_FROM_START
    assert state.ignored
    assert relay_write_ignored(state)
    assert relay_check(state, config, reports=True) is RelayCheck.IGNORED
    assert state.off_ignored is (not command)
    assert state.on_ignored is command
    # Never held a command: "ignored from the start", not a relay that stopped taking them.
    assert not state.not_taken
    assert not state.off_not_taken
    # It stays so for the session, even once the relay shows the command by itself.
    relay.switch(3610.0, command)
    state, _ = drive(relay, config, command, 3610.0, 4000.0, state)
    assert state.ignored
    assert relay_write_ignored(state)
    # The next session tries again.
    fresh = relay_for_new_session(state, 5000.0)
    assert not fresh.ignored


def test_a_relay_taken_after_the_second_send_is_not_ignored() -> None:
    """Negative: taken after the second send — nothing of "ignored from the start"."""
    config = RelayConfig(reports=RelayReports.YES, timer=RelayTimer.NONE)
    relay = Relay(takes=False)
    state, _ = drive(relay, config, True, 0.0, 290.0)
    relay.takes = True
    state, results = drive(relay, config, True, 300.0, 3600.0, state)
    assert events(results) == []
    assert not state.ignored
    assert not relay_write_ignored(state)
    assert [t for t, _on, _kind in relay.writes] == [0.0, 300.0]


def stopped_taking(command: bool) -> tuple[Relay, RelayState]:
    """A relay that held the other command — the start phase over — and then stops taking
    commands: a Zigbee link that delivers its reports but not the plugin's commands, a stuck
    contact."""
    relay = Relay(on=not command)
    state, _ = drive(relay, REPORTING, not command, 0.0, 300.0)
    assert state.start_done
    relay.takes = False
    return relay, state


NOT_TAKEN_S = RELAY_NOT_TAKEN_CHECKS * RELAY_CHECK_S  # about 15 min


def test_a_relay_that_stops_taking_off_mid_session_is_blocked_after_three_checks() -> None:
    """SB-06 (decision 6 of 0.2.3): after the start phase, a relay that does not show "off" — sent
    at 1000 s, again at the checks 300 s and 600 s later — over three checks running has stopped
    taking commands: at the third check, nothing more is written, and the session is marked so
    the loop blocks control and the unit hands the relay back (its rest state, once), as answer O
    does. "Write ignored" stays on; the status says "not taken". Before: "not confirmed" and the
    information alarm only, "off" resent every 5 min for good while the boiler kept heating."""
    relay, state = stopped_taking(False)
    state, results = drive(relay, REPORTING, False, 1000.0, 3000.0, state)
    assert relay.writes == [
        (1000.0, False, WriteKind.CHANGE),
        (1300.0, False, WriteKind.RESEND),
        (1600.0, False, WriteKind.RESEND),
    ]
    by_t = dict(results)
    assert by_t[1000.0 + RELAY_CONFIRM_S].judged is ChangeClass.NOT_CONFIRMED  # information
    assert not by_t[1000.0 + NOT_TAKEN_S - 10].state.not_taken
    stopped = by_t[1000.0 + NOT_TAKEN_S]
    assert stopped.judged is ChangeClass.NOT_TAKEN
    assert stopped.write is None
    assert stopped.state.off_not_taken
    assert state.not_taken
    assert state.off_not_taken
    assert relay_write_ignored(state)
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.NOT_TAKEN
    assert events(results) == []
    assert lost(results) == []
    assert not state.blocked
    # The block is the session's: kept through the hand-back, gone at the next session.
    kept = after_hand_back_relay(state)
    assert kept.written is None
    assert not kept.not_taken
    assert kept.off_not_taken
    assert relay_write_ignored(kept)
    assert relay_check(kept, REPORTING, reports=True) is RelayCheck.NOT_TAKEN
    result = plan_relay(kept, None, relay.seen(3010.0), 3010.0, REPORTING)
    assert result.write is None
    fresh = relay_for_new_session(state, 5000.0)
    assert not fresh.off_not_taken
    assert not fresh.not_taken


def test_a_relay_that_stops_taking_on_mid_session_is_reported_and_sent_on_at_each_check() -> None:
    """SB-06 (decision 6 of 0.2.3): "on" not shown over three checks running — the house is not
    heated: marked "not taken" (the unit's error-level issue), while "on" is still sent at every
    check; no block. Once the relay shows "on" again the mark goes at once."""
    relay, state = stopped_taking(True)
    state, results = drive(relay, REPORTING, True, 1000.0, 2500.0, state)
    assert [t for t, _on, _kind in relay.writes] == [1000.0, 1300.0, 1600.0, 1900.0, 2200.0, 2500.0]
    assert all(on for _t, on, _kind in relay.writes)
    by_t = dict(results)
    assert not by_t[1000.0 + NOT_TAKEN_S - 10].state.not_taken
    assert by_t[1000.0 + NOT_TAKEN_S].judged is ChangeClass.NOT_TAKEN
    assert by_t[1000.0 + NOT_TAKEN_S].write == RelayWrite(True, WriteKind.RESEND)
    assert state.not_taken
    assert not state.off_not_taken
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.NOT_TAKEN
    assert events(results) == []
    relay.takes = True
    state, _ = drive(relay, REPORTING, True, 2510.0, 2810.0, state)
    assert relay.on  # taken at the next check
    assert not state.not_taken
    state, _ = drive(relay, REPORTING, True, 2820.0, 2950.0, state)
    assert relay_check(state, REPORTING, reports=True) is RelayCheck.CONFIRMED


def test_checks_a_relay_out_of_reach_could_not_make_do_not_count() -> None:
    """SB-06's negative: the relay unavailable for ten minutes in the middle of the checks — the
    run of three checks starts again once it is back (its return is a lost command, sent again
    while its trace lasts); "not taken" comes 15 min after the first send it did not show since,
    not 15 min after the first send."""
    relay, state = stopped_taking(False)

    def outage(s: float) -> None:
        if s == 1200:
            relay.away(s)
        elif s == 1800:
            relay.back(s, True)  # still on: "off" not taken

    state, results = drive(relay, REPORTING, False, 1000.0, 4000.0, state, at=outage)
    # Back with a trace: lost commands, sent again every 120 s while the trace lasts (R2); the
    # run of checks starts at the last of them.
    assert [t for t, _on, _kind in relay.writes] == [
        1000.0,
        1800.0,
        1920.0,
        2040.0,
        2040.0 + RELAY_CHECK_S,
        2040.0 + 2 * RELAY_CHECK_S,
    ]
    stopped = [t for t, r in results if r.judged is ChangeClass.NOT_TAKEN]
    assert stopped[0] == 2040.0 + NOT_TAKEN_S  # not at 1000 + 15 min
    assert state.off_not_taken


def test_a_relay_never_read_cannot_be_judged_not_taking_commands() -> None:
    """SB-06's negative: unknown inputs — a relay that reads ``unknown`` throughout, and one with
    no send to time from — are never judged as no longer taking commands."""
    _relay, state = confirmed_on()
    unknown = RelaySeen(on=None, known=False, available=True)
    for t in (1000.0, 2000.0, 3000.0):
        result = plan_relay(state, False, unknown, t, REPORTING)
        state = result.state
        assert result.judged is ChangeClass.NOT_JUDGED
    assert not state.not_taken
    assert not state.off_not_taken
    # Never sent, never shown: nothing to time a run of checks from.
    unsent = RelayState(written=True, start_done=True)
    shows_off = RelaySeen(on=False, known=True, available=True)
    result = plan_relay(unsent, True, shows_off, 5000.0, REPORTING)
    assert result.judged is ChangeClass.NOT_CONFIRMED
    assert not result.state.not_taken


def test_a_late_echo_of_the_previous_command_is_not_a_change() -> None:
    """Within 120 s of a send, the previous command shown late is no change."""
    relay = Relay()
    state, _ = drive(relay, REPORTING, False, 0.0, 200.0)
    state, results = drive(
        relay,
        REPORTING,
        True,
        1000.0,
        1100.0,
        state,
        at=lambda s: (
            relay.switch(s, False) if s == 1010 else relay.switch(s, True) if s == 1030 else None
        ),
    )
    assert events(results) == []
    assert lost(results) == []
    assert all(r.judged in (ChangeClass.NOT_JUDGED, ChangeClass.CONFIRMED) for _t, r in results)
    # "Off" found off at the start was taken as it is: a mismatch only is written.
    assert relay.writes == [(1000.0, True, WriteKind.CHANGE)]


def test_the_periodic_check_resends_a_mismatch_no_event_explained() -> None:
    """R4, R8: a mismatch nothing judged — here a change that carried the plugin's own context —
    is sent again at the next check, every 300 s, not at once."""
    relay = Relay()
    state, _ = drive(relay, REPORTING, True, 0.0, 140.0)
    relay.on, relay.changed_at, relay.ours = False, 150.0, True
    state, results = drive(relay, REPORTING, True, 150.0, 320.0, state)
    assert all(r.events == () and not r.lost for _t, r in results)
    assert relay.writes == [(0.0, True, WriteKind.CHANGE), (RELAY_CHECK_S, True, WriteKind.RESEND)]


def test_unknown_inputs_change_nothing() -> None:
    """No command (``None``) writes nothing; a state not known, without an outage mark, is not
    judged; a known one without a command written is not judged either."""
    relay = Relay(on=True)
    state, results = drive(relay, REPORTING, None, 0.0, 600.0)
    assert relay.writes == []
    assert all(r.judged is ChangeClass.NOT_JUDGED and r.events == () for _t, r in results)
    relay, state = confirmed_on()
    unknown = RelaySeen(on=None, known=False, available=True)
    result = plan_relay(state, True, unknown, 1000.0, REPORTING)
    assert result.judged is ChangeClass.NOT_JUDGED
    assert result.events == ()
    assert not result.lost
    assert result.write is None
    missing = RelaySeen(on=None, known=False, available=False)
    result = plan_relay(state, False, missing, 1010.0, REPORTING)
    assert result.write is None  # a new command waits: it could not arrive


def test_a_failed_write_is_sent_again_at_the_next_step() -> None:
    relay = Relay()
    result = plan_relay(RelayState(), True, relay.seen(0.0), 0.0, REPORTING)
    state = relay_write_failed(result.state)
    result = plan_relay(state, True, relay.seen(10.0), 10.0, REPORTING)
    assert result.write == RelayWrite(True, WriteKind.RESEND)


def test_writes_stay_five_seconds_apart() -> None:
    relay = Relay()
    result = plan_relay(RelayState(), True, relay.seen(0.0), 0.0, REPORTING)
    assert result.write is not None
    relay.write(0.0, result.write)
    result = plan_relay(result.state, False, relay.seen(2.0), 2.0, REPORTING)
    assert result.write is None  # waits
    result = plan_relay(result.state, False, relay.seen(10.0), 10.0, REPORTING)
    assert result.write == RelayWrite(False, WriteKind.CHANGE)


def test_a_new_command_the_relay_already_shows_is_not_written() -> None:
    """Written on a mismatch only — unless a switch-off timer (declared or not ruled out) needs
    the "on" to renew it."""
    relay = Relay(on=True)
    result = plan_relay(RelayState(), True, relay.seen(0.0), 0.0, REPORTING)
    assert result.write is None
    assert result.state.written is True
    assert relay_check(result.state, REPORTING, reports=True) is RelayCheck.CONFIRMED
    timer = replace(REPORTING, timer=RelayTimer.UNKNOWN)
    result = plan_relay(RelayState(), True, relay.seen(0.0), 0.0, timer)
    assert result.write == RelayWrite(True, WriteKind.CHANGE)
    blind = replace(REPORTING, reports=RelayReports.NO)
    result = plan_relay(RelayState(), True, relay.seen(0.0), 0.0, blind)
    assert result.write == RelayWrite(True, WriteKind.CHANGE)  # it cannot be compared


def test_a_climate_in_another_mode_is_a_change() -> None:
    """A boiler thermostat entity in a mode that is neither heat nor off shows another state."""
    config = replace(REPORTING, power_on=RelayPowerOn.OFF)
    _relay, state = confirmed_on(config)
    other = RelaySeen(on=None, known=True, available=True, changed_at=1000.0)
    result = plan_relay(state, True, other, 1000.0, config)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.write == RelayWrite(True, WriteKind.REWRITE)


def test_the_first_report_after_a_start_is_a_lost_command() -> None:
    """Answer C: found in another state at the first report after Home Assistant starts."""
    relay, state = confirmed_on()
    relay.on, relay.changed_at, relay.ours = False, 1000.0, False
    result = plan_relay(state, True, relay.seen(1000.0, first=True), 1000.0, REPORTING)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.lost
    assert not result.restart


def test_the_memory_across_a_hand_back_and_a_new_session() -> None:
    """A hand-back inside the session keeps the session's memory — the block, "ignored", the one
    rewrite, the restarts; a new session keeps the rewrite and the restarts for their day (the
    answer-N count is never answered more than three times a day) and the reachability."""
    state = RelayState(
        written=True,
        written_at=10.0,
        sent_at=10.0,
        confirmed_at=20.0,
        blocked=True,
        ignored=True,
        ignored_values=(True,),
        rewritten_at=100.0,
        restarts=(50.0, 60.0),
        unreachable_since=90.0,
        lapses=((60.0, 1800.0),),
        timer_seen_s=600.0,
        short_off_s=120.0,
    )
    kept = after_hand_back_relay(state)
    assert kept.written is None
    assert kept.sent_at is None
    assert kept.confirmed_at is None
    assert kept.blocked
    assert kept.ignored
    assert kept.rewritten_at == 100.0
    assert kept.restarts == (50.0, 60.0)
    assert kept.lapses == ((60.0, 1800.0),)  # Z4R-02: facts about the relay
    assert kept.timer_seen_s == 600.0
    assert kept.short_off_s == 120.0  # K4.2: with the block it explains
    fresh = relay_for_new_session(state, 1000.0)
    assert not fresh.blocked
    assert not fresh.ignored
    assert fresh.written is None
    assert fresh.rewritten_at == 100.0
    assert fresh.restarts == (50.0, 60.0)
    assert fresh.unreachable_since == 90.0
    assert fresh.lapses == ((60.0, 1800.0),)
    assert fresh.timer_seen_s == 600.0
    assert fresh.short_off_s is None  # the block is gone with the session
    later = relay_for_new_session(state, 100.0 + DAY)
    assert later.rewritten_at is None
    assert later.restarts == ()
    assert later.lapses == ()  # for their day, like the restarts
    assert later.timer_seen_s == 600.0  # the relay's own timer stays known


def test_a_clock_set_back_counts_as_now() -> None:
    relay, state = confirmed_on()
    state = replace(
        state,
        written_at=5000.0,
        sent_at=5000.0,
        restarts=(6000.0,),
        lapses=((6000.0, 1800.0),),
        timer_seen_s=1800.0,
        short_off_s=1200.0,
    )
    result = plan_relay(state, True, relay.seen(300.0), 300.0, REPORTING)
    assert result.state.short_off_s == 1200.0  # a length, not a moment
    assert result.state.lapses == ((300.0, 1800.0),)  # the moment moves, the age stays
    assert result.state.timer_seen_s == 1800.0  # a length, not a moment
    assert result.state.written_at is not None
    assert result.state.written_at <= 300.0
    assert result.state.restarts == (300.0,)


def test_heat_evidence() -> None:
    """R12: heats — the flame on, the flow 5 K above its value at the "on", the gas meter past
    its value at the "on", or the power at or above the threshold; unknown — no proof input
    mapped and known; else not seen."""
    assert heat_evidence(ProofSeen(flame=True), None, None) is HeatEvidence.HEATS
    assert heat_evidence(ProofSeen(flame=False), None, None) is HeatEvidence.NOT_SEEN
    rise = PROOF_FLOW_RISE_K
    assert heat_evidence(ProofSeen(flow=40.0 + rise), 40.0, None) is HeatEvidence.HEATS
    assert heat_evidence(ProofSeen(flow=40.0 + rise - 0.1), 40.0, None) is HeatEvidence.NOT_SEEN
    assert heat_evidence(ProofSeen(gas=100.01), None, 100.0) is HeatEvidence.HEATS
    assert heat_evidence(ProofSeen(gas=100.0), None, 100.0) is HeatEvidence.NOT_SEEN
    power = ProofSeen(power_w=120.0, heats_above_w=100.0)
    assert heat_evidence(power, None, None) is HeatEvidence.HEATS
    assert heat_evidence(replace(power, power_w=80.0), None, None) is HeatEvidence.NOT_SEEN
    # The power without its threshold proves nothing.
    assert heat_evidence(ProofSeen(power_w=500.0), None, None) is HeatEvidence.UNVERIFIED
    assert heat_evidence(ProofSeen(), None, None) is HeatEvidence.UNVERIFIED
    assert heat_evidence(ProofSeen(flame=None, flow=None, gas=None), 40.0, 1.0) is (
        HeatEvidence.UNVERIFIED
    )


def test_no_sign_of_heat_for_thirty_minutes_raises_the_alarm() -> None:
    """After 30 min of the relay on with a proof input known and none showing heat: the
    information alarm; it clears on any proof, or when the relay goes off. Heat seen once in the
    on-period is enough (the boiler stops on its own thermostat). Nothing known: no alarm."""
    state = ProofState()
    seen = ProofSeen(flame=False, flow=40.0)
    for t in (0.0, PROOF_WINDOW_S - 10):
        state, shown, alarm = follow_proof(state, True, seen, t)
        assert shown is HeatEvidence.NOT_SEEN
        assert not alarm
    state, shown, alarm = follow_proof(state, True, seen, PROOF_WINDOW_S)
    assert alarm
    state, shown, alarm = follow_proof(state, True, replace(seen, flow=46.0), PROOF_WINDOW_S + 10)
    assert shown is HeatEvidence.HEATS
    assert not alarm
    state, shown, alarm = follow_proof(state, True, seen, PROOF_WINDOW_S + 600)
    assert shown is HeatEvidence.HEATS
    assert not alarm  # seen in this on-period
    state, shown, alarm = follow_proof(state, False, seen, PROOF_WINDOW_S + 610)
    assert shown is None
    assert not alarm
    assert state == ProofState()
    blind = ProofState()
    for t in (0.0, PROOF_WINDOW_S * 2):
        blind, shown, alarm = follow_proof(blind, True, ProofSeen(), t)
        assert shown is HeatEvidence.UNVERIFIED
        assert not alarm
    # A flow not known at the "on" takes its first known value as the start.
    late = ProofState()
    late, _shown, _alarm = follow_proof(late, True, ProofSeen(flame=False), 0.0)
    late, _shown, _alarm = follow_proof(late, True, ProofSeen(flame=False, flow=30.0), 10.0)
    assert late.flow_at_on == 30.0


@pytest.mark.parametrize(
    "bad",
    [
        {"repeat_s": 5.0},
        {"repeat_s": 301.0},
        {"timer": RelayTimer.MINUTES},
        {"timer": RelayTimer.MINUTES, "timer_s": 30.0},
        {"timer": RelayTimer.MINUTES, "timer_s": 540.0},  # 9 min: below the shortest (K4.2)
        {"timer": RelayTimer.MINUTES, "timer_s": 7300.0},
        {"check_s": 5.0},
    ],
)
def test_relay_settings_outside_their_range_are_refused(bad: dict) -> None:
    """The rule never runs on settings outside their range (the options parse reads them
    cautiously first)."""
    with pytest.raises(ValueError, match=r"must|needs"):
        RelayConfig(**bad)


def test_a_renewal_due_within_the_write_interval_waits_quietly() -> None:
    """A renewal due within five seconds of a write attempt is simply not due yet — no retry
    marked; the next step renews."""
    config = RelayConfig(reports=RelayReports.YES, timer=RelayTimer.UNKNOWN, repeat_s=10.0)
    relay, state = Relay(), RelayState()
    state, _ = drive(relay, config, True, 0.0, 0.0, state)
    state = replace(state, written_at=8.0)  # an attempt at 8 s
    result = plan_relay(state, True, relay.seen(10.0), 10.0, config)
    assert result.write is None
    assert not result.state.retry
    result = plan_relay(result.state, True, relay.seen(20.0), 20.0, config)
    assert result.write == RelayWrite(True, WriteKind.KEEPALIVE)


def test_a_gas_meter_not_known_at_the_on_takes_its_first_known_value() -> None:
    state, _shown, _alarm = follow_proof(ProofState(), True, ProofSeen(flame=False), 0.0)
    state, _shown, _alarm = follow_proof(state, True, ProofSeen(flame=False, gas=12.5), 10.0)
    assert state.gas_at_on == 12.5
    state, shown, _alarm = follow_proof(state, True, ProofSeen(flame=False, gas=12.6), 20.0)
    assert shown is HeatEvidence.HEATS
