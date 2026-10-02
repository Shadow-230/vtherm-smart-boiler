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
)

MIN = 60.0
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
    writes: list[tuple[float, bool, WriteKind]] = field(default_factory=list)

    def tick(self, t: float) -> None:
        """Its own timer switches it off."""
        timer, since = self.timer_s, self.on_at
        if self.on and timer is not None and since is not None and t - since >= timer:
            self.on, self.changed_at, self.ours = False, since + timer, False

    def seen(self, t: float, *, reports: bool = True, first: bool = False) -> RelaySeen:
        known = self.available and self.on is not None
        return RelaySeen(
            on=self.on if known else None,
            known=known,
            available=self.available,
            reports=reports,
            trace=self.outage_at is not None and t - self.outage_at <= TRACE_S,
            ours=self.ours,
            first=first,
            changed_at=self.changed_at,
        )

    def write(self, t: float, write: RelayWrite) -> None:
        self.writes.append((t, write.on, write.kind))
        if not (self.available and self.takes):
            return
        if write.on and (not self.on or self.restarts_timer):
            self.on_at = t
        if self.on != write.on:
            self.changed_at = t
        self.on, self.ours = write.on, True

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
) -> tuple[RelayState, list[tuple[float, RelayResult]]]:
    """Steps every ``step`` seconds from ``start`` to ``end`` (included); ``at(t)`` changes the
    relay before the step at ``t`` sees it."""
    state = state or RelayState()
    results: list[tuple[float, RelayResult]] = []
    t = start
    while t <= end + 1e-9:
        if at is not None:
            at(t)
        relay.tick(t)
        want = desired(t) if callable(desired) else desired
        result = plan_relay(state, want, relay.seen(t, reports=reports), t, config)
        if result.write is not None:
            relay.write(t, result.write)
        state = result.state
        results.append((t, result))
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
    """A switch-off before max(timer − 60 s, timer ÷ 2) is judged as any change while the relay
    stayed available: with "on after a power cut" another controller (rewritten once); with
    "off", "last" or "I don't know" R2a's possible restart (answer N)."""
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


@pytest.mark.parametrize(("switch_at", "lapse"), [(300.0, True), (290.0, False)])
def test_an_unknown_timer_gets_on_repeats_and_a_late_switch_off_is_answered_and_counted(
    switch_at: float, lapse: bool
) -> None:
    """A timer "I don't know": "on" repeated every repeat interval while commanded on; a
    switch-off at least one repeat interval after the start of the on-period may be its lapse —
    "on" again at once, counted as answer N's restart (Z4-02); an earlier one is judged as any
    change while available — with "on after a power cut" another controller. "Off" is not
    repeated. A relay whose real timer lapses all day is answered three times within the day;
    the fourth lapse makes the plugin step aside: declare the timer's length to avoid it."""
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
    # on-period — answered three times, each counted; the fourth steps aside, and nothing more
    # is written.
    relay = Relay(timer_s=10 * MIN, restarts_timer=False)
    state, results = drive(relay, config, True, 0.0, DAY)
    answered = [t for t, r in results if r.judged is ChangeClass.LOST_COMMAND]
    assert answered == [600.0, 1200.0, 1800.0]
    assert all(dict(results)[t].write == RelayWrite(True, WriteKind.RESEND) for t in answered)
    assert lost(results) == answered
    assert events(results) == [(2400.0, GuardEvent.OUTSIDE_CHANGE)]
    assert state.blocked
    assert state.restarts == tuple(answered)
    assert [t for t, _on, _kind in relay.writes if t >= 2400.0] == []


@pytest.mark.parametrize("power_on", [RelayPowerOn.OFF, RelayPowerOn.ON])
@pytest.mark.parametrize(
    ("timer", "timer_s"),
    [(RelayTimer.UNKNOWN, None), (RelayTimer.MINUTES, 6 * MIN)],
    ids=["unknown", "declared"],
)
def test_an_unknown_timer_lapse_is_bounded_by_answer_n(
    power_on: RelayPowerOn, timer: RelayTimer, timer_s: float | None
) -> None:
    """Z4-02 (answers C, D, L, N): with the timer "I don't know", a switch-off at least one
    repeat interval into an on-period may be the timer's lapse — or an automation, a person, the
    relay's own button. It is answered with "on" at once, but counted as answer N's restart:
    three within a day sent again and counted, the fourth is another controller — the plugin
    steps aside at once, with no rewrite, and writes nothing more. Negative: a declared timer's
    lapse stays the relay's own — "on" again, never counted, all five times."""
    config = RelayConfig(reports=RelayReports.YES, power_on=power_on, timer=timer, timer_s=timer_s)
    relay = Relay()
    offs = [360.0 * n for n in range(1, 6)]  # 6 min into each on-period, five times
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
        for t in offs:
            assert seen[t].judged is ChangeClass.OWN_LAPSE
            assert seen[t].write == RelayWrite(True, WriteKind.RESEND)
            assert not seen[t].lost
            assert not seen[t].restart
        assert state.restarts == ()
        assert events(results) == []
        assert not state.blocked
        assert relay.on
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
    assert events(results) == [(offs[3], GuardEvent.OUTSIDE_CHANGE)]
    assert [t for t, on, _kind in relay.writes if t > offs[3]] == []  # left alone
    assert not relay.on


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


@pytest.mark.parametrize(
    ("timer_min", "repeat_s", "every"), [(10, 300.0, 300.0), (4, 300.0, 120.0), (20, 300.0, 300.0)]
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
    Where it is "off" that it ignores, the plugin can no longer switch heating off (answer O)."""
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
    )
    kept = after_hand_back_relay(state)
    assert kept.written is None
    assert kept.sent_at is None
    assert kept.confirmed_at is None
    assert kept.blocked
    assert kept.ignored
    assert kept.rewritten_at == 100.0
    assert kept.restarts == (50.0, 60.0)
    fresh = relay_for_new_session(state, 1000.0)
    assert not fresh.blocked
    assert not fresh.ignored
    assert fresh.written is None
    assert fresh.rewritten_at == 100.0
    assert fresh.restarts == (50.0, 60.0)
    assert fresh.unreachable_since == 90.0
    later = relay_for_new_session(state, 100.0 + DAY)
    assert later.rewritten_at is None
    assert later.restarts == ()


def test_a_clock_set_back_counts_as_now() -> None:
    relay, state = confirmed_on()
    state = replace(state, written_at=5000.0, sent_at=5000.0, restarts=(6000.0,))
    result = plan_relay(state, True, relay.seen(300.0), 300.0, REPORTING)
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
