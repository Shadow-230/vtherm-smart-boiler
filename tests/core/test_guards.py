"""Write guards: one per target — the setpoint, and heating on/off as 1 and 0 — and decision 6's
four classes of a change seen in the read-back (lost command, ignored from the start, clipped,
another controller), with the user's answers E, H and O of 2026-09-27."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    DAY,
    HOUR,
    REACTIONS,
    ChangeClass,
    Confirmation,
    GuardConfig,
    GuardContext,
    GuardEvent,
    GuardResult,
    GuardState,
    Reaction,
    WriteAction,
    WriteKind,
    WriteType,
    add_loss,
    after_hand_back,
    confirmation,
    confirmation_missing,
    for_new_session,
    losses_warning,
    plan_write,
    write_failed,
)

EXPIRING = GuardConfig(write_type=WriteType.EXPIRING)
HELD = GuardConfig(write_type=WriteType.HELD)
ON, OFF = 1.0, 0.0
ECHOED = GuardConfig(write_type=WriteType.HELD, two_valued=True)  # a heating switch with an echo
EXPIRING_ECHOED = GuardConfig(write_type=WriteType.EXPIRING, two_valued=True)
SWITCH = GuardConfig(write_type=WriteType.HELD, read_back=False, two_valued=True)  # no echo


def step(
    state: GuardState,
    desired: float | None,
    read_back: float | None,
    now: float,
    config: GuardConfig,
    **context: object,
) -> tuple[GuardState, WriteAction | None, tuple[GuardEvent, ...]]:
    result = plan_write(state, desired, read_back, now, config, GuardContext(**context))  # type: ignore[arg-type]
    return result.state, result.action, result.events


def result_of(
    state: GuardState,
    desired: float | None,
    read_back: float | None,
    now: float,
    config: GuardConfig,
    **context: object,
) -> GuardResult:
    return plan_write(state, desired, read_back, now, config, GuardContext(**context))  # type: ignore[arg-type]


def keep(
    state: GuardState,
    config: GuardConfig,
    start: float,
    end: float,
    value: float = 45.0,
    read_back: float | None = 45.0,
) -> GuardState:
    """Steps every 10 s from ``start`` up to ``end`` (included) with the value read back: the
    keep-alives go on, nothing is judged."""
    t = start
    while t <= end:
        state, _action, events = step(state, value, read_back, t, config)
        assert events == ()
        t += 10.0
    return state


def held(
    config: GuardConfig = HELD,
    first: float | None = 0.0,
    value: float = 45.0,
    until: float = 150.0,
) -> GuardState:
    """``value`` sent at 0 — the read-back then ``first``, the value from before the plugin — and
    read back from 10 s on, past the start phase (it held the confirmation timeout)."""
    state, action, _ = step(GuardState(), value, first, 0.0, config)
    assert action == WriteAction(value, WriteKind.CHANGE)
    state = keep(state, config, 10.0, until, value, value)
    assert state.start_done
    return state


# --- writing: what, when, how often ------------------------------------------------------------


def test_first_write_and_expiring_keepalive() -> None:
    state, action, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.CHANGE)
    state, action, _ = step(state, 45.0, 45.0, 20.0, EXPIRING)
    assert action is None
    state, action, _ = step(state, 45.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)


def test_held_values_are_sent_again_every_five_minutes_without_an_echo() -> None:
    """M3 (decision 6): a held value — the heating switch's too — is sent again every 300 s
    (provisional, K4) with no echo required; a keep-alive, not a change. One goes at once when the
    target comes back from unavailable."""
    for config, value in ((SWITCH, ON), (replace(HELD, read_back=False), 45.0)):
        state, action, _ = step(GuardState(), value, None, 0.0, config)
        assert action == WriteAction(value, WriteKind.CHANGE)
        writes = []
        for t in range(10, 1000, 10):
            returned = t == 650
            state, action, _ = step(state, value, None, float(t), config, returned=returned)
            if action is not None:
                writes.append((t, action.kind))
        assert writes == [
            (300, WriteKind.KEEPALIVE),
            (600, WriteKind.KEEPALIVE),
            (650, WriteKind.KEEPALIVE),  # back from unavailable: at once
            (950, WriteKind.KEEPALIVE),
        ]


def test_held_values_are_sent_again_when_the_device_returns() -> None:
    """M2: a held target back from unavailable or unknown gets every held value again at once,
    echo or not; the value it came back with is not judged."""
    state = held(HELD)
    state, action, _ = step(state, 45.0, None, 200.0, HELD)  # the device restarts
    assert action is None
    state, action, events = step(state, 45.0, 45.0, 210.0, HELD)  # back, holding our value
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)
    assert events == ()
    state, action, events = step(state, 45.0, None, 220.0, HELD)
    _state, action, events = step(state, 45.0, None, 230.0, HELD, returned=True)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)  # the target itself is back
    assert events == ()


@pytest.mark.parametrize("write_type", [WriteType.PERSISTENT, WriteType.UNKNOWN])
def test_nothing_goes_to_the_boilers_persistent_memory(write_type: WriteType) -> None:
    """A target that stores what it is given (or might) is never written, whatever is asked."""
    config = GuardConfig(write_type=write_type)
    state, action, events = step(GuardState(), 45.0, None, 0.0, config)
    assert (action, events) == (None, ())
    state = GuardState(written=45.0, written_at=0.0, sent_at=0.0, confirmed_at=5.0)
    for desired, confirmed in ((50.0, 45.0), (45.0, 60.0)):  # a change, an outside change
        _, action, _ = step(state, desired, confirmed, 600.0, config)
        assert action is None
    assert not config.writable


def test_a_new_value_waits_at_most_one_step() -> None:
    """The write-rate guard against a runaway loop: a write repeated within one control step
    waits for the next one — nothing longer."""
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, action, _ = step(state, 50.0, 45.0, 3.0, EXPIRING)
    assert action is None  # a step run early (control switched on) within the same step
    _, action, _ = step(state, 50.0, 45.0, 10.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)


def test_a_runaway_loop_gets_one_write_per_step() -> None:
    state = GuardState()
    written = 0
    for t in range(60):  # a new value every second
        state, action, _ = step(state, 45.0 + t, None, float(t), EXPIRING)
        written += action is not None
    assert written == 12  # one per five seconds: at most two in a ten-second step


def test_a_failed_write_is_sent_again_at_the_next_step() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state = write_failed(state)
    state, action, events = step(state, 45.0, None, 10.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    _, action, _ = step(state, 45.0, None, 20.0, EXPIRING)
    assert action is None  # sent; nothing more until the next keep-alive or change


def test_failed_attempts_count_toward_the_write_rate() -> None:
    """A target that keeps rejecting the value is tried again once a step, not hammered."""
    state = GuardState()
    attempts = 0
    for t in range(0, 60, 2):
        state, action, _ = step(state, 45.0, None, float(t), EXPIRING)
        attempts += action is not None
        if action is not None:
            state = write_failed(state)
    assert attempts == 10  # every third call: six seconds apart


def test_a_failed_write_followed_by_a_new_value_writes_the_new_value() -> None:
    """P82: the retry branch with a change — the new value goes, not the failed one."""
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)
    state, action, _ = step(state, 50.0, 45.0, 20.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state = write_failed(state)
    state, action, events = step(state, 55.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(55.0, WriteKind.CHANGE)
    assert events == ()
    assert not state.retry


def test_a_failed_change_is_retried_not_taken_for_an_outside_change() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    state, action, _ = step(state, 50.0, 45.0, 120.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state = write_failed(state)
    state, action, events = step(state, 50.0, 45.0, 130.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.RESEND)
    assert events == ()
    assert state.rewritten_at is None


def test_a_lapse_after_our_own_silence_is_resent_not_rewritten() -> None:
    """M17: the plugin's own expiring override lapsed while it was silent (stale data): sent
    again, not an outside change and not a lost command."""
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    for t in (40.0, 100.0, 160.0):  # stale data: nothing desired, nothing written
        state, action, _ = step(state, None, 45.0 if t < 60 else 40.0, t, EXPIRING)
        assert action is None
    result = result_of(state, 45.0, 40.0, 200.0, EXPIRING)  # the override lapsed
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.events == ()
    assert result.judged is ChangeClass.OWN_LAPSE
    assert not result.lost
    assert result.state.rewritten_at is None  # the one rewrite is kept for another controller


def test_nothing_desired_writes_nothing() -> None:
    _, action, _ = step(GuardState(), None, None, 0.0, EXPIRING)
    assert action is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"keepalive_s": 0.0},
        {"min_interval_s": 0.0},
        {"min_interval_s": 30.0},
        {"tolerance": -1.0},
        {"refresh_s": 5.0},
    ],
)
def test_invalid_setpoint_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        GuardConfig(**kwargs)


def test_heating_on_off_follows_every_change_at_once() -> None:
    """Nothing counted or timed holds heating on or off against VT."""
    state = GuardState()
    writes = []
    for t, desired in enumerate([ON, OFF, ON, OFF, ON]):
        result = plan_write(state, desired, None, t * 10.0, SWITCH)
        state = result.state
        writes.append(None if result.action is None else result.action.value)
    assert writes == [ON, OFF, ON, OFF, ON]
    assert plan_write(state, ON, None, 50.0, SWITCH).action is None  # unchanged


def test_without_an_echo_nothing_is_judged() -> None:
    state = plan_write(GuardState(), ON, OFF, 0.0, SWITCH).state
    for t in (130.0, 260.0, 290.0):
        result = plan_write(state, ON, OFF, t, SWITCH)
        state = result.state
        assert (result.action, result.events) == (None, ())
    assert confirmation(state, SWITCH) is Confirmation.UNVERIFIED


def test_an_expiring_heating_override_is_repeated() -> None:
    config = GuardConfig(write_type=WriteType.EXPIRING, read_back=False)
    first = plan_write(GuardState(), ON, None, 0.0, config)
    assert plan_write(first.state, ON, None, 10.0, config).action is None
    assert plan_write(first.state, ON, None, 30.0, config).action == WriteAction(
        ON, WriteKind.KEEPALIVE
    )


def test_a_failed_heating_write_is_sent_again() -> None:
    first = plan_write(GuardState(), ON, None, 0.0, SWITCH)
    retried = plan_write(write_failed(first.state), ON, None, 10.0, SWITCH)
    assert retried.action == WriteAction(ON, WriteKind.RESEND)
    assert plan_write(retried.state, ON, None, 20.0, SWITCH).action is None


def test_heating_waits_at_most_one_step() -> None:
    first = plan_write(GuardState(), ON, None, 0.0, SWITCH)
    early = plan_write(first.state, OFF, None, 3.0, SWITCH)
    assert early.action is None
    assert plan_write(early.state, OFF, None, 10.0, SWITCH).action == WriteAction(
        OFF, WriteKind.CHANGE
    )


def test_where_a_written_value_stands() -> None:
    state = GuardState()
    assert confirmation(state, HELD) is None
    state, _, _ = step(state, 45.0, None, 0.0, HELD)
    assert confirmation(state, HELD) is Confirmation.WAITING
    state, _, _ = step(state, 45.0, None, 130.0, HELD)
    assert confirmation(state, HELD) is Confirmation.WAITING  # unknown: nothing judged
    state, _, _ = step(state, 45.0, 30.0, 140.0, HELD)
    assert confirmation(state, HELD) is Confirmation.NOT_CONFIRMED  # a known value, not ours
    state, _, _ = step(state, 45.0, 45.0, 150.0, HELD)
    assert confirmation(state, HELD) is Confirmation.CONFIRMED


def test_a_clock_set_back_does_not_stop_the_keep_alive() -> None:
    """C9: the wall clock set back an hour (a correction, a wrong time server): the keep-alive
    — due every 30 s, or the gateway gives the boiler back — must not wait for an hour."""
    config = GuardConfig(write_type=WriteType.EXPIRING)
    first = plan_write(GuardState(), 50.0, None, 10_000.0, config)
    assert first.action is not None
    back = plan_write(first.state, 50.0, 50.0, 10_000.0 - 3600.0, config)
    assert back.action is not None
    assert back.action.kind is WriteKind.KEEPALIVE


def test_a_clock_set_back_moves_every_moment_to_now() -> None:
    """C9: moments later than now — the wall clock set back — count as now: a fall-back
    without a trace remembered "in the future" still counts within the hour, never longer."""
    state = replace(
        held(HELD),
        fallbacks=(9000.0,),
        recent=((9000.0, 45.0),),
        change_at=9000.0,
        draw_at=9000.0,
    )
    result = result_of(state, 45.0, 45.0, 500.0, HELD)
    assert result.state.fallbacks == (500.0,)
    assert result.state.recent == ((500.0, 45.0),)
    assert result.state.change_at == 500.0
    assert result.state.draw_at == 500.0


def test_the_reaction_table_names_one_reaction_per_class() -> None:
    assert set(REACTIONS) == set(ChangeClass)
    assert REACTIONS[ChangeClass.LOST_COMMAND] is Reaction.RESEND
    assert REACTIONS[ChangeClass.IGNORED_FROM_START] is Reaction.STOP
    assert REACTIONS[ChangeClass.CLIPPED] is Reaction.NONE
    assert REACTIONS[ChangeClass.ANOTHER_CONTROLLER] is Reaction.REWRITE_ONCE


# --- the baseline ----------------------------------------------------------------------------


def test_the_baseline_is_the_first_known_read_back_that_is_not_the_plugins() -> None:
    """P-07: seen before the first send; not the last command stored (V3), which a device may
    still hold after a restart. Negative: unknown at the first send and never read back as the
    plugin's — a steady value is then no baseline (M9: it hides no other controller)."""
    state, _, _ = step(GuardState(), 45.0, 30.0, 0.0, HELD)
    assert state.baseline == 30.0
    state, _, _ = step(GuardState(), 45.0, 45.0, 0.0, HELD, last_command=45.0)
    assert state.baseline is None  # the plugin's own last command, still held
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 60.0, 10.0, HELD)
    assert state.baseline is None


def test_an_unknown_read_back_at_the_first_write_still_tells_a_drop() -> None:
    """T-02 (P-07): the read-back unknown at the session's first write, then confirmed; it falls
    twice the same day, more than an hour apart, to the value from before the session: each is a
    lost command, sent again — no rewrite, no block."""
    state = held(EXPIRING, first=None)
    assert state.baseline is None
    state = keep(state, EXPIRING, 160.0, 390.0)
    result = result_of(state, 45.0, 0.0, 400.0, EXPIRING)
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.state.baseline == 0.0
    state = keep(result.state, EXPIRING, 410.0, 400.0 + 3700.0)
    result = result_of(state, 45.0, 0.0, 4110.0, EXPIRING)
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.events == ()
    assert result.state.blocked is None
    assert result.state.rewritten_at is None


def test_a_heating_echo_unknown_at_the_first_send_still_tells_a_fall_back() -> None:
    """Z4-03 (P-07, T-02 for heating on/off): the echo unknown at the session's first send of
    "off", then confirmed. The first known echo that is not a state the plugin sent is the value
    from before the plugin: untraced fall-backs to "on" three hours apart are each a lost
    command — sent again, counted, no rewrite, no block — and two within an hour another
    controller, as with a baseline seen before the send. Negative: the plugin sent both states
    before any known echo — none is the value from before the plugin, and the other state held
    two steps is another controller (row 13)."""
    state = held(ECHOED, first=None, value=OFF)
    assert state.baseline is None
    state = keep(state, ECHOED, 160.0, 990.0, OFF, OFF)
    for t in (1000.0, 1000.0 + 3 * HOUR):
        result = result_of(state, OFF, ON, t, ECHOED)
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.action == WriteAction(OFF, WriteKind.RESEND)
        assert result.lost
        assert result.events == ()
        assert result.state.baseline == ON  # learned at the first, kept
        state = keep(result.state, ECHOED, t + 10.0, t + 600.0, OFF, OFF)
    assert state.rewritten_at is None
    assert state.blocked is None
    result = result_of(state, OFF, ON, 1000.0 + 3 * HOUR + 1200.0, ECHOED)  # within the hour
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(OFF, WriteKind.REWRITE)

    state, _, _ = step(GuardState(), OFF, None, 0.0, ECHOED)  # unknown at the first send
    state, _, _ = step(state, ON, None, 10.0, ECHOED)  # both states sent, none read back yet
    state = keep(state, ECHOED, 20.0, 990.0, ON, ON)
    assert state.baseline is None
    state, _, _ = step(state, ON, OFF, 1000.0, ECHOED)
    assert state.baseline is None
    result = result_of(state, ON, OFF, 1010.0, ECHOED)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(ON, WriteKind.REWRITE)


# --- lost command ----------------------------------------------------------------------------


@pytest.mark.parametrize("first", [0.0, None], ids=["read_back_known", "read_back_none"])
def test_a_confirmed_value_that_falls_back_after_an_outage_is_a_lost_command(
    first: float | None,
) -> None:
    """M1: confirmed 45, held past the start phase; the value from before the plugin 0; an outage
    4 minutes before; the read-back shows 0 → sent again at once, one loss, no event. Negative:
    the outage 6 minutes before is no trace — the rows without one apply."""
    state = held(HELD, first)
    result = result_of(state, 45.0, 0.0, 400.0, HELD, outage_at=400.0 - 240.0)
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.lost
    assert result.events == ()
    assert result.state.fallbacks == ()  # with a trace: not a fall-back without one
    negative = result_of(state, 45.0, 0.0, 400.0, HELD, outage_at=400.0 - 360.0)
    assert negative.action == WriteAction(45.0, WriteKind.RESEND)
    assert negative.state.fallbacks == (400.0,)  # counted as one without a trace


@pytest.mark.parametrize("first", [0.0, None], ids=["read_back_known", "read_back_none"])
def test_a_first_fall_back_without_a_trace_is_a_lost_command(first: float | None) -> None:
    """M4 (answer E): one fall-back without a trace — a Data-Invalid reply, a lost EMS-ESP
    keep-alive, a PIC reset nobody saw — is a lost command: sent again, counted, no event."""
    state = held(HELD, first)
    result = result_of(state, 45.0, 0.0, 400.0, HELD)
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.lost
    assert result.events == ()
    assert result.state.fallbacks == (400.0,)


@pytest.mark.parametrize("first", [0.0, None], ids=["read_back_known", "read_back_none"])
def test_a_second_fall_back_within_an_hour_without_a_trace_is_another_controller(
    first: float | None,
) -> None:
    """M5 (answer E): a second fall-back without a trace within an hour that no send explains is
    another controller: written again once; the next within a day blocks."""
    state = held(HELD, first)
    state, action, _ = step(state, 45.0, 0.0, 400.0, HELD)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    state, _, _ = step(state, 45.0, 45.0, 410.0, HELD)  # read back again
    result = result_of(state, 45.0, 0.0, 1600.0, HELD)  # 20 minutes later
    assert result.action == WriteAction(45.0, WriteKind.REWRITE)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.events == ()
    state, _, _ = step(result.state, 45.0, 45.0, 1610.0, HELD)  # the rewrite holds
    state, action, events = step(state, 45.0, 0.0, 2200.0, HELD)  # a third within the day
    assert action is None
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_two_fall_backs_more_than_an_hour_apart_stay_lost_commands() -> None:
    state = held(HELD)
    for t in (400.0, 400.0 + 70 * 60.0):
        state, action, events = step(state, 45.0, 0.0, t, HELD)
        assert action == WriteAction(45.0, WriteKind.RESEND)
        assert events == ()
        state, _, _ = step(state, 45.0, 45.0, t + 10.0, HELD)
    assert state.rewritten_at is None


def test_a_fall_back_a_send_explains_is_not_another_controller() -> None:
    """Answer E: a fall-back that comes before the plugin's latest send was read back, or within
    120 s of a send of a new value, is a lost command, never another controller — here twice in
    20 minutes, the read-back still showing the previous value before it falls. Negative: a
    keep-alive or a resend of the same value explains nothing; the second such within an hour is
    written again once."""
    state = held(HELD)
    value = 45.0
    for t in (400.0, 1600.0):
        value += 5.0
        state, action, _ = step(state, value, value - 5.0, t, HELD)  # a new value; not read yet
        assert action == WriteAction(value, WriteKind.CHANGE)
        result = result_of(state, value, 0.0, t + 60.0, HELD)  # it falls before it is read
        assert result.action == WriteAction(value, WriteKind.RESEND)
        assert result.judged is ChangeClass.LOST_COMMAND
        assert result.events == ()
        state, _, _ = step(result.state, value, value, t + 70.0, HELD)
    assert state.rewritten_at is None

    state = held(HELD)
    state, action, _ = step(state, 45.0, 45.0, 300.0, HELD)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)  # the held refresh
    state, action, _ = step(state, 45.0, 0.0, 310.0, HELD)  # just after it: not explained
    assert action == WriteAction(45.0, WriteKind.RESEND)  # the first: a lost command
    state, _, _ = step(state, 45.0, 45.0, 320.0, HELD)
    state, action, _ = step(state, 45.0, 45.0, 610.0, HELD)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)
    result = result_of(state, 45.0, 0.0, 620.0, HELD)  # after a keep-alive and a resend
    assert result.action == WriteAction(45.0, WriteKind.REWRITE)


def test_a_fall_back_whose_resend_is_never_read_back_stays_a_lost_command() -> None:
    """The resend of a lost command not read back within the timeout — the fall-back came before
    the plugin's latest send was read back — is sent again as a lost command, counted, never
    another controller: frequent losses warn."""
    state = held(HELD)
    seen = []
    for t in range(400, 810, 10):  # it keeps dropping: the boiler does not take it (P-121)
        result = result_of(state, 45.0, 0.0, float(t), HELD)
        state = result.state
        seen.append((t, result.judged, result.action, result.lost, result.events))
    resent = (400, 520, 640, 760)  # at once, then its timeout after each send
    assert seen == [
        (t, ChangeClass.LOST_COMMAND, WriteAction(45.0, WriteKind.RESEND), True, ())
        if t in resent
        else (t, ChangeClass.NOT_JUDGED, None, False, ())
        for t in range(400, 810, 10)
    ]
    assert state.rewritten_at is None
    assert state.blocked is None


def test_the_thermostats_own_value_after_an_outage_is_a_lost_command() -> None:
    """With an OpenTherm thermostat, its own request is in the fall-back set where the optional
    field is mapped. Negative: without the field, 38 is another value."""
    state = keep(held(EXPIRING, first=40.0), EXPIRING, 160.0, 390.0)
    result = result_of(state, 45.0, 38.0, 400.0, EXPIRING, thermostat=38.0, outage_at=390.0)
    assert result.action == WriteAction(45.0, WriteKind.RESEND)
    assert result.judged is ChangeClass.LOST_COMMAND
    negative = result_of(state, 45.0, 38.0, 400.0, EXPIRING, outage_at=390.0)
    assert negative.judged is ChangeClass.NOT_JUDGED  # another value, one step only
    assert negative.action is None


# --- ignored from the start ------------------------------------------------------------------


def test_a_fall_back_after_every_send_from_the_start_is_ignored_from_the_start() -> None:
    """M6 (answer E): each of the session's first three sends is read back for less than 120 s,
    then falls back to the value from before the plugin: sent again after the first and the
    second; ignored from the start once, after the third; not written again, keep-alives
    included; never another controller."""
    state, action, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    kinds = []
    t = 10.0
    for _send in range(3):
        for _ in range(6):  # read back for 60 s
            state, _, events = step(state, 45.0, 45.0, t, EXPIRING)
            assert events == ()
            t += 10.0
        result = result_of(state, 45.0, 0.0, t, EXPIRING)  # it falls back
        state = result.state
        kinds.append((result.judged, None if result.action is None else result.action.kind))
        t += 10.0
    assert kinds == [
        (ChangeClass.FAILED_ATTEMPT, WriteKind.RESEND),
        (ChangeClass.FAILED_ATTEMPT, WriteKind.RESEND),
        (ChangeClass.IGNORED_FROM_START, None),
    ]
    assert result.events == (GuardEvent.IGNORED,)
    assert state.ignored
    assert confirmation(state, EXPIRING) is Confirmation.NOT_CONFIRMED
    for later in range(int(t), int(t) + 600, 10):
        state, action, events = step(state, 45.0, 0.0, float(later), EXPIRING)
        assert (action, events) == (None, ())  # nothing again this session
    assert state.blocked is None
    assert state.rewritten_at is None


@pytest.mark.parametrize("first", [0.0, None], ids=["read_back_known", "none_between"])
def test_a_baseline_held_from_the_first_send_is_ignored_not_another_controller(
    first: float | None,
) -> None:
    """S-48: the read-back stays at the value from before the session after each of the first
    three sends (each sent 120 s after the one before): ignored from the start, no rewrite. With
    an unknown read-back for a step in between, nothing is judged at it."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    sends = []
    ignored_at = None
    for t in range(10, 400, 10):
        read_back = None if first is None and t == 50 else 0.0
        result = result_of(state, 45.0, read_back, float(t), EXPIRING)
        state = result.state
        if result.action is not None and result.action.kind is WriteKind.RESEND:
            sends.append(t)
        if GuardEvent.IGNORED in result.events:
            ignored_at = t
        assert GuardEvent.OUTSIDE_CHANGE not in result.events
        assert result.action is None or result.action.kind is not WriteKind.REWRITE
    if first is None:
        # The unknown read-back at 50 s is a trace in the first attempt: it does not count.
        assert sends == [120, 240, 360]
        assert ignored_at is None
    else:
        assert sends == [120, 240]
        assert ignored_at == 360
    assert state.rewritten_at is None


def test_an_attempt_with_an_outage_does_not_count_toward_ignored() -> None:
    """Provisional, K4: a trace of an outage within an attempt's 120 s — sent again, not counted;
    three counted failed attempts are still needed. Negative: without it, the third at 360 s."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    ignored_at = None
    for t in range(10, 900, 10):
        outage = 50.0 if t >= 50 else None
        result = result_of(state, 45.0, 0.0, float(t), EXPIRING, outage_at=outage)
        state = result.state
        if GuardEvent.IGNORED in result.events:
            ignored_at = t
            break
    # The attempts at 0, 120 and 240 s had the trace (until 350 s); those at 360, 480 and 600 s
    # count: the third fails at 720 s.
    assert ignored_at == 720


def test_heating_off_ignored_from_the_start_names_off() -> None:
    """Answer O: the heating switch stays on after each of the session's first three sends of
    "off" — ignored from the start, with "off" among the values it did not take. Negative: only
    "on" not taken — the switch stays off — is ignored from the start without it."""
    state, _, _ = step(GuardState(), OFF, ON, 0.0, ECHOED)  # on before the plugin
    for t in range(10, 400, 10):
        state, _, _ = step(state, OFF, ON, float(t), ECHOED)
    assert state.ignored
    assert state.off_ignored
    state, _, _ = step(GuardState(), ON, OFF, 0.0, ECHOED)
    for t in range(10, 400, 10):
        state, _, _ = step(state, ON, OFF, float(t), ECHOED)
    assert state.ignored
    assert not state.off_ignored


def test_ignored_from_the_start_ends_once_the_value_holds() -> None:
    """The class ends — the target is written again — once its read-back holds a sent value for
    the timeout; and at the next session."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    for t in range(10, 370, 10):
        state, _, _ = step(state, 45.0, 0.0, float(t), EXPIRING)
    assert state.ignored
    for t in range(370, 500, 10):  # the boiler takes the last value after all
        state, action, _ = step(state, 45.0, 45.0, float(t), EXPIRING)
        if not state.ignored:
            break
        assert action is None
    assert not state.ignored
    assert t == 490  # held 120 s from 370
    assert not for_new_session(replace(state, ignored=True), 500.0).ignored


# --- clipped ---------------------------------------------------------------------------------


def test_a_lower_value_whatever_the_plugin_sends_is_clipped() -> None:
    """M7: 45, then 50 sent; the read-back holds 40 throughout — the boiler's own limit: shown as
    clipped, no event, no rewrite; writing goes on. It ends once a read-back shows a sent value.
    Negative: one sent value only (a setpoint that stays flat) is not a clip — the steady row
    applies (a known limit, K4)."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, HELD)
    for t in range(10, 60, 10):
        state, _, _ = step(state, 45.0, 40.0, float(t), HELD)
    state, action, _ = step(state, 50.0, 40.0, 60.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    for t in range(70, 400, 10):
        result = result_of(state, 50.0, 40.0, float(t), HELD)
        state = result.state
        assert result.events == ()
        assert result.action is None or result.action.kind is not WriteKind.REWRITE
    assert state.clip == 40.0
    assert confirmation(state, HELD) is Confirmation.CLIPPED
    state, _, _ = step(state, 50.0, 50.0, 410.0, HELD)
    assert state.clip is None
    assert confirmation(state, HELD) is Confirmation.CONFIRMED

    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, HELD)
    for t in range(10, 120, 10):
        state, _, _ = step(state, 45.0, 40.0, float(t), HELD)
    _state, action, _ = step(state, 45.0, 40.0, 120.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)


def test_an_unknown_read_back_breaks_a_clip_until_it_holds_again() -> None:
    """Negative (a ``None`` read-back): an unknown step between is not judged and breaks the
    steady value; the clip is recognised once the lower value has held two steps again."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, HELD)
    state, _, _ = step(state, 50.0, 40.0, 10.0, HELD)
    state, _, _ = step(state, 50.0, None, 20.0, HELD)
    state, _, _ = step(state, 50.0, 40.0, 30.0, HELD)
    assert state.clip is None  # one step since the unknown one
    state, _, events = step(state, 50.0, 40.0, 40.0, HELD)
    assert events == ()
    assert state.clip == 40.0


def test_a_clip_needs_a_steady_value() -> None:
    """Negative: a read-back that moves is no clip — and never judged steady."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, HELD)
    state, _, _ = step(state, 50.0, 40.0, 10.0, HELD)
    for i, t in enumerate(range(20, 400, 10)):
        state, action, events = step(state, 50.0, 40.0 if i % 2 else 38.0, float(t), HELD)
        assert events == ()
        assert action is None or action.kind is not WriteKind.REWRITE
    assert state.clip is None


# --- another controller ----------------------------------------------------------------------


@pytest.mark.parametrize("unknown_between", [False, True], ids=["steady", "unknown_between"])
def test_a_steady_other_value_for_two_steps_is_another_controller(unknown_between: bool) -> None:
    """M8: after a confirmation, another value held for two steps: written again once; again
    within a day, the guard blocks. An unknown read-back between two steps of it breaks the two
    steps (a trace, nothing judged). (A held target's first value after an unknown one is sent
    again instead: ``test_a_held_target_device_restart_is_not_an_outside_change``.)"""
    config = EXPIRING
    state = keep(held(config), config, 160.0, 290.0)
    state, _, _ = step(state, 45.0, 60.0, 300.0, config)
    if unknown_between:
        state, action, _ = step(state, 45.0, None, 310.0, config)
        assert action is None or action.kind is WriteKind.KEEPALIVE
        state, action, _ = step(state, 45.0, 60.0, 320.0, config)
        assert action is None or action.kind is WriteKind.KEEPALIVE
        t = 330.0
    else:
        t = 310.0
    result = result_of(state, 45.0, 60.0, t, config)
    assert result.action == WriteAction(45.0, WriteKind.REWRITE)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.events == ()
    state = keep(result.state, config, t + 10.0, t + 590.0)  # our value is back
    state, _, _ = step(state, 45.0, 60.0, t + 600.0, config)
    state, action, events = step(state, 45.0, 60.0, t + 610.0, config)
    assert action is None
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    assert confirmation(state, config) is Confirmation.CHANGED_FROM_OUTSIDE
    _state, action, events = step(state, 45.0, 60.0, t + 700.0, config)
    assert (action, events) == (None, ())  # blocked: no fight, no repeated report


def test_a_one_step_difference_is_not_judged() -> None:
    """M10: another value for one step, then ours again: nothing."""
    state = held(HELD)
    for t, read_back in ((300.0, 60.0), (310.0, 45.0), (320.0, 60.0), (330.0, 45.0)):
        result = result_of(state, 45.0, read_back, t, HELD)
        state = result.state
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    assert state.rewritten_at is None


def test_a_rewrite_that_does_not_hold_is_an_outside_change() -> None:
    for config in (HELD, EXPIRING):
        state = keep(held(config), config, 160.0, 290.0)
        state, _, _ = step(state, 45.0, 60.0, 300.0, config)
        state, action, _ = step(state, 45.0, 60.0, 310.0, config)  # another controller wrote 60
        assert action == WriteAction(45.0, WriteKind.REWRITE)
        for t in range(320, 430, 10):  # it keeps its 60: no report before the timeout
            state, _, events = step(state, 45.0, 60.0, float(t), config)
            assert events == ()
        state, action, events = step(state, 45.0, 60.0, 430.0, config)
        assert action is None
        assert events == (GuardEvent.OUTSIDE_CHANGE,)
        assert state.blocked is GuardEvent.OUTSIDE_CHANGE


@pytest.mark.parametrize(
    ("config", "first", "previous", "new"),
    [(HELD, 0.0, 45.0, 50.0), (ECHOED, ON, OFF, ON)],
    ids=["setpoint", "heating_switch"],
)
def test_a_late_echo_of_the_previous_value_is_not_judged_within_the_timeout(
    config: GuardConfig, first: float, previous: float, new: float
) -> None:
    """Z4-01's negative (M8: "its previous one", within 120 s of the change): the plugin's
    previous value — written long before — still read back after the plugin sent a new one is a
    late echo, not judged while the change is at most 120 s old: no rewrite, no event, shown
    waiting, then not confirmed once the timeout has passed. Past that window it is judged like
    any other value: held two steps, the one rewrite."""
    state = held(config, first=first, value=previous)
    state = keep(state, config, 160.0, 990.0, previous, previous)
    state, action, _ = step(state, new, previous, 1000.0, config)
    assert action == WriteAction(new, WriteKind.CHANGE)
    for t in range(1010, 1130, 10):  # up to the change + 120 s
        result = result_of(state, new, previous, float(t), config)
        state = result.state
        assert result.judged is ChangeClass.NOT_JUDGED
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    assert confirmation(state, config) is Confirmation.NOT_CONFIRMED
    assert state.rewritten_at is None
    assert state.blocked is None
    result = result_of(state, new, previous, 1130.0, config)  # the window is over: one step
    assert result.judged is ChangeClass.NOT_JUDGED
    result = result_of(result.state, new, previous, 1140.0, config)  # held two steps
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(new, WriteKind.REWRITE)


def test_a_setpoint_back_at_the_plugins_previous_value_is_another_controller() -> None:
    """Z4-01 for the setpoint: something sets the setpoint back to the plugin's previous value —
    replaced more than 120 s before — and holds it: another controller, written again once; the
    next such change within a day blocks. The previous value is no longer exempt for good."""
    state = keep(held(HELD), HELD, 160.0, 990.0)
    state, action, _ = step(state, 50.0, 45.0, 1000.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state = keep(state, HELD, 1010.0, 1200.0, 50.0, 50.0)
    first = result_of(state, 50.0, 45.0, 1210.0, HELD)
    assert first.judged is ChangeClass.NOT_JUDGED  # one step (M10)
    assert confirmation(first.state, HELD) is Confirmation.NOT_CONFIRMED  # it shows another value
    result = result_of(first.state, 50.0, 45.0, 1220.0, HELD)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(50.0, WriteKind.REWRITE)
    assert result.events == ()
    state = keep(result.state, HELD, 1230.0, 1590.0, 50.0, 50.0)  # the rewrite holds
    state, _, _ = step(state, 50.0, 45.0, 1600.0, HELD)
    state, action, events = step(state, 50.0, 45.0, 1610.0, HELD)  # again within the day
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_a_second_outside_change_within_a_day_blocks_even_after_our_change() -> None:
    state = held(HELD)
    state, _, _ = step(state, 45.0, 60.0, 200.0, HELD)
    state, action, _ = step(state, 45.0, 60.0, 210.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    state, _, _ = step(state, 45.0, 45.0, 220.0, HELD)
    state, _, _ = step(state, 50.0, 45.0, 400.0, HELD)  # our new value
    state, _, _ = step(state, 50.0, 50.0, 410.0, HELD)
    state, _, _ = step(state, 50.0, 60.0, 420.0, HELD)
    state, action, events = step(state, 50.0, 60.0, 430.0, HELD)
    assert action is None  # a controller writing less often than we change is not fought
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_a_rewrite_is_allowed_again_a_day_later() -> None:
    state = held(HELD)
    state, _, _ = step(state, 45.0, 60.0, 200.0, HELD)
    state, _, _ = step(state, 45.0, 60.0, 210.0, HELD)  # the rewrite
    state, _, _ = step(state, 45.0, 45.0, 220.0, HELD)
    later = 210.0 + DAY + 10.0
    state, _, _ = step(state, 45.0, 60.0, later, HELD)
    _state, action, events = step(state, 45.0, 60.0, later + 10.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    assert events == ()


def test_another_controller_is_judged_while_the_plugins_value_keeps_changing() -> None:
    """M9: the desired value rises 0.2 K each step while the read-back holds 60 from the first
    send: written again once at the first send + 120 s — later changes neither delay nor clear it
    — and the guard blocks when the rewrite has not held 120 s later."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    desired = 45.0
    rewrite_at = blocked_at = None
    for i in range(1, 40):
        t = 10.0 * i
        desired += 0.2
        result = result_of(state, desired, 60.0, t, EXPIRING)
        state = result.state
        if result.action is not None and result.action.kind is WriteKind.REWRITE:
            rewrite_at = t
        if GuardEvent.OUTSIDE_CHANGE in result.events:
            blocked_at = t
            break
    assert rewrite_at == 120.0
    assert blocked_at == 240.0


def test_another_controller_is_judged_when_the_read_back_was_unknown_at_the_send() -> None:
    """M9: the read-back unknown at the send, then another value steadily: written again at the
    send + 120 s — not only reported as ignored."""
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    kinds = {}
    for t in range(10, 130, 10):
        result = result_of(state, 45.0, 60.0, float(t), EXPIRING)
        state = result.state
        assert GuardEvent.IGNORED not in result.events
        if result.action is not None:
            kinds[t] = result.action.kind
    assert kinds[120] is WriteKind.REWRITE
    assert WriteKind.REWRITE not in [kinds[t] for t in kinds if t < 120]


def test_a_failed_rewrite_is_judged_after_a_new_value_too() -> None:
    """The one rewrite, then a new value; the read-back holds the other controller's value: the
    guard blocks at the rewrite + 120 s — the new value does not move that."""
    state = held(HELD)
    state, _, _ = step(state, 45.0, 60.0, 300.0, HELD)
    state, action, _ = step(state, 45.0, 60.0, 310.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    state, action, _ = step(state, 50.0, 60.0, 320.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    for t in range(330, 430, 10):
        state, _, events = step(state, 50.0, 60.0, float(t), HELD)
        assert events == ()
    state, action, events = step(state, 50.0, 60.0, 430.0, HELD)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))


def test_the_one_rewrite_ends_in_an_outside_change_even_after_a_late_confirmation() -> None:
    """P07: a value confirmed only late, then changed from outside — the one rewrite still ends
    in an outside change when it does not hold, and the writes stop."""
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    state = keep(state, EXPIRING, 10.0, 120.0, read_back=None)
    state, _, events = step(state, 45.0, None, 130.0, EXPIRING)
    assert events == ()  # unknown: nothing judged
    state, _, _ = step(state, 45.0, 45.0, 140.0, EXPIRING)  # confirmed after all
    state, _, _ = step(state, 45.0, 60.0, 150.0, EXPIRING)
    state, action, _ = step(state, 45.0, 60.0, 160.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    state = keep(state, EXPIRING, 170.0, 270.0, read_back=60.0)
    state, action, events = step(state, 45.0, 60.0, 280.0, EXPIRING)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))
    _, action, _ = step(state, 45.0, 60.0, 400.0, EXPIRING)
    assert action is None  # no keep-alive: no fight


def test_a_moving_read_back_is_not_another_controller() -> None:
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, HELD)
    for i, t in enumerate(range(10, 400, 10)):
        state, action, events = step(state, 45.0, 60.0 if i % 2 else 57.0, float(t), HELD)
        assert events == ()
        assert action is None or action.kind is not WriteKind.REWRITE


def test_a_foreign_value_is_judged_even_across_a_step_without_data() -> None:
    state, _, _ = step(GuardState(), 45.0, 0.0, 0.0, EXPIRING)
    state = keep(state, EXPIRING, 10.0, 110.0, read_back=60.0)
    state, action, _ = step(state, None, 60.0, 120.0, EXPIRING)  # stale data: nothing desired
    assert action is None
    _, action, _ = step(state, 45.0, 60.0, 130.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.REWRITE)


# --- heating on/off: the same classes (S-40, answer E) ------------------------------------------


def test_heating_switched_back_without_a_trace_is_first_a_lost_command() -> None:
    """S-40, answer E: after the start phase the echo flips back to its value from before the
    plugin while it stayed available: sent again, one fall-back without a trace counted; a second
    within an hour that no send explains is written again once; the next within a day blocks."""
    state = held(ECHOED, first=OFF, value=ON)
    result = result_of(state, ON, OFF, 400.0, ECHOED)
    assert result.action == WriteAction(ON, WriteKind.RESEND)
    assert result.judged is ChangeClass.LOST_COMMAND
    assert result.state.fallbacks == (400.0,)
    state, _, _ = step(result.state, ON, ON, 410.0, ECHOED)
    state, action, events = step(state, ON, OFF, 1000.0, ECHOED)
    assert action == WriteAction(ON, WriteKind.REWRITE)
    assert events == ()
    state, _, _ = step(state, ON, ON, 1010.0, ECHOED)
    state, action, events = step(state, ON, OFF, 1600.0, ECHOED)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))


def test_heating_switched_away_from_its_baseline_is_another_controller() -> None:
    """Row 13: the value from before the plugin "on", the plugin commands "on", the echo shows
    "off" at two consecutive steps with no trace: written again once; again within a day, the
    guard blocks. (With the echo unknown at the first send, the first other state seen is the
    value from before the plugin — Z4-03:
    ``test_a_heating_echo_unknown_at_the_first_send_still_tells_a_fall_back``.)"""
    state = held(ECHOED, first=ON, value=ON)
    state, action, _ = step(state, ON, OFF, 400.0, ECHOED)
    assert action is None or action.kind is WriteKind.KEEPALIVE  # one step: not judged
    state, action, events = step(state, ON, OFF, 410.0, ECHOED)
    assert action == WriteAction(ON, WriteKind.REWRITE)
    assert events == ()
    state, _, _ = step(state, ON, ON, 420.0, ECHOED)
    state, _, _ = step(state, ON, OFF, 500.0, ECHOED)
    state, action, events = step(state, ON, OFF, 510.0, ECHOED)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))


@pytest.mark.parametrize(("baseline", "other"), [(ON, OFF), (OFF, ON)], ids=["on", "off"])
def test_heating_switched_away_after_a_toggle_is_another_controller(
    baseline: float, other: float
) -> None:
    """Z4-01 (decision 6, answer E, row 13): the plugin has switched heating both ways in the
    session — its previous state is then the only other one — and commands the state from before
    the plugin. Something switches heating to the other state more than 120 s after the plugin's
    last change: shown not confirmed at once; held two steps, another controller — written again
    once; the next such change within a day blocks. Before, the previous state was never judged,
    and the held refresh wrote the command back silently, for good."""
    state = keep(
        held(ECHOED, first=baseline, value=baseline), ECHOED, 160.0, 990.0, baseline, baseline
    )
    state, action, _ = step(state, other, baseline, 1000.0, ECHOED)  # the plugin: one way
    assert action == WriteAction(other, WriteKind.CHANGE)
    state = keep(state, ECHOED, 1010.0, 1990.0, other, other)
    state, action, _ = step(state, baseline, other, 2000.0, ECHOED)  # ... and back
    assert action == WriteAction(baseline, WriteKind.CHANGE)
    state = keep(state, ECHOED, 2010.0, 2200.0, baseline, baseline)
    assert state.baseline == baseline
    assert confirmation(state, ECHOED) is Confirmation.CONFIRMED
    first = result_of(state, baseline, other, 2210.0, ECHOED)  # switched from outside
    assert first.judged is ChangeClass.NOT_JUDGED  # one step (M10)
    assert first.action is None
    assert confirmation(first.state, ECHOED) is Confirmation.NOT_CONFIRMED
    result = result_of(first.state, baseline, other, 2220.0, ECHOED)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(baseline, WriteKind.REWRITE)
    assert result.events == ()
    assert confirmation(result.state, ECHOED) is not Confirmation.CONFIRMED
    state = keep(result.state, ECHOED, 2230.0, 2590.0, baseline, baseline)  # the rewrite holds
    state, _, _ = step(state, baseline, other, 2600.0, ECHOED)
    state, action, events = step(state, baseline, other, 2610.0, ECHOED)  # again within the day
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


@pytest.mark.parametrize("config", [ECHOED, EXPIRING_ECHOED], ids=["held", "expiring"])
def test_heating_switched_back_after_an_outage_is_a_lost_command(config: GuardConfig) -> None:
    """The echo unavailable, then back at its state from before the plugin: sent again, no
    event, not counted as a fall-back without a trace. With a trace, the other state is the
    device's own even where it is not the baseline (more cautious than row 13)."""
    state = keep(held(config, first=OFF, value=ON), config, 160.0, 390.0, ON, ON)
    state, action, _ = step(state, ON, None, 400.0, config)
    assert action is None or action.kind is WriteKind.KEEPALIVE
    result = result_of(state, ON, OFF, 410.0, config)
    assert result.action == WriteAction(ON, WriteKind.RESEND)
    assert result.events == ()
    assert result.lost
    assert result.state.fallbacks == ()
    state = keep(held(config, first=ON, value=ON), config, 160.0, 390.0, ON, ON)
    result = result_of(state, ON, OFF, 400.0, config, outage_at=380.0)
    assert result.action == WriteAction(ON, WriteKind.RESEND)  # baseline "on": not another
    assert result.judged is ChangeClass.LOST_COMMAND


# --- a held device's restart (S-13, T-47) --------------------------------------------------------


@pytest.mark.parametrize("how", ["read_back", "target"])
def test_a_held_target_device_restart_is_not_an_outside_change(how: str) -> None:
    """T-47: a held target (ESPHome), 0 before the plugin, 45 confirmed; the target goes
    unavailable and comes back with its initial value 40, twice in a day: sent again each time,
    no outside change, no block — whether its read-back or the target itself was seen away."""
    state = held(HELD)
    for base in (400.0, 400.0 + 12 * 3600.0):
        if how == "read_back":
            state, action, _ = step(state, 45.0, None, base, HELD)
            assert action is None or action.kind is WriteKind.KEEPALIVE  # the held refresh
            result = result_of(state, 45.0, 40.0, base + 60.0, HELD)
        else:
            result = result_of(state, 45.0, 40.0, base + 60.0, HELD, returned=True)
        assert result.action == WriteAction(45.0, WriteKind.RESEND)
        assert result.events == ()
        assert result.state.blocked is None
        state, _, _ = step(result.state, 45.0, 45.0, base + 70.0, HELD)
    assert state.rewritten_at is None


# --- not judged: a hot-water draw, an unknown read-back --------------------------------------


def test_a_draw_is_not_judged() -> None:
    """Provisional, K4: during a hot-water draw, and for 120 s after it, a change is not judged
    (a boiler-state echo goes off during a draw). Negative: hot water unknown — judged."""
    state = held(HELD)
    for t in range(300, 410, 10):
        state, action, events = step(state, 45.0, 60.0, float(t), HELD, dhw=True)
        assert events == ()
        assert action is None or action.kind is not WriteKind.REWRITE
    rewrite_at = None
    for t in range(410, 600, 10):
        state, action, _ = step(state, 45.0, 60.0, float(t), HELD, dhw=False)
        if action is not None and action.kind is WriteKind.REWRITE:
            rewrite_at = t
            break
    assert rewrite_at == 540  # the draw ended at 400: judged from 530, held two steps
    state = held(HELD)
    state, _, _ = step(state, 45.0, 60.0, 300.0, HELD, dhw=None)
    _state, action, _ = step(state, 45.0, 60.0, 310.0, HELD, dhw=None)
    assert action == WriteAction(45.0, WriteKind.REWRITE)


def test_an_unknown_read_back_is_not_judged_and_informs_after_five_minutes() -> None:
    """M11: while the plugin writes, the read-back unknown for five minutes: "confirmation
    missing", information only — nothing judged, no hand-back; it clears at the first known
    read-back. Negative: 4 minutes 50 seconds — off."""
    state = held(EXPIRING)
    state = keep(state, EXPIRING, 160.0, 290.0)
    for t in range(300, 600, 10):
        state, action, events = step(state, 45.0, None, float(t), EXPIRING)
        assert events == ()
        assert action is None or action.kind is WriteKind.KEEPALIVE  # writing goes on
    assert not confirmation_missing(state, 590.0)
    state, _, _ = step(state, 45.0, None, 600.0, EXPIRING)
    assert confirmation_missing(state, 600.0)
    assert state.blocked is None
    state, _, _ = step(state, 45.0, 45.0, 610.0, EXPIRING)
    assert not confirmation_missing(state, 610.0)


# --- the session's memory -----------------------------------------------------------------------


def test_a_hand_back_keeps_the_sessions_memory_and_drops_what_was_sent() -> None:
    """P-06: a hand-back inside a session keeps the baseline, the block, the one rewrite, the
    counters and the class "ignored from the start"; what was sent goes. A new session keeps only
    the one rewrite, for its day."""
    state = held(HELD)
    state = replace(
        state,
        blocked=GuardEvent.OUTSIDE_CHANGE,
        rewritten_at=100.0,
        fallbacks=(90.0,),
        ignored=True,
        ignored_values=(OFF,),
        clip=40.0,
    )
    kept = after_hand_back(state)
    assert kept.baseline == 0.0
    assert kept.blocked is GuardEvent.OUTSIDE_CHANGE
    assert kept.rewritten_at == 100.0
    assert kept.fallbacks == (90.0,)
    assert kept.ignored
    assert kept.clip == 40.0
    assert kept.start_done
    assert (kept.written, kept.written_at, kept.sent_at, kept.confirmed_at) == (None,) * 4
    assert (kept.previous, kept.foreign, kept.retry) == (None, None, False)
    fresh = for_new_session(state, 100.0 + DAY - 1.0)
    assert fresh == GuardState(rewritten_at=100.0)
    assert for_new_session(state, 100.0 + DAY) == GuardState()


# --- losses ----------------------------------------------------------------------------------


def test_frequent_losses_raise_a_warning_never_a_hold() -> None:
    """Three losses within 24 h (provisional, K4) raise "commands lost", information only; it
    clears after 24 h without a loss. Negative: two losses in 24 h — off. Both targets losing
    their overrides together are one loss."""
    losses = add_loss((), 0.0, "setpoint")
    losses = add_loss(losses, 10.0, "heating")  # the same gateway reset: one loss
    assert len(losses) == 1
    losses = add_loss(losses, 3600.0, "setpoint")
    assert not losses_warning(losses, 3600.0, False)
    losses = add_loss(losses, 7200.0, "setpoint")
    assert losses_warning(losses, 7200.0, False)
    assert losses_warning(losses, 7200.0 + DAY - 1.0, True)  # stays on
    assert not losses_warning(losses, 7200.0 + DAY, True)  # a day without a loss
    assert not losses_warning(add_loss((), 0.0, "setpoint"), 1.0, False)


# --- P-115: what ``plan_write`` does when several things hold at once, as a table -------------
# A target the plugin may not write, then a block, "ignored from the start" or nothing desired,
# then the plugin's own failed write, then decision 6's class and its reaction, then the
# ordinary plan (a change, a keep-alive, nothing). Each row: the step's action, events, class,
# whether it counts a loss, and the block it leaves.

_PERSISTENT = GuardConfig(write_type=WriteType.PERSISTENT)
_UNDECLARED = GuardConfig(write_type=WriteType.UNKNOWN)


def _after_foreign_step() -> GuardState:
    """Held, then one step of another value read back, then the plugin's own write failing."""
    state, _, _ = step(held(HELD), 45.0, 60.0, 400.0, HELD)
    return write_failed(state)


def _second_fall_back() -> GuardState:
    """A first fall-back, sent again and read back: the next within the hour is another
    controller."""
    state, _, _ = step(held(HELD), 45.0, 0.0, 400.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 410.0, HELD)
    return state


def _rewritten() -> GuardState:
    """The one rewrite made and read back."""
    state = plan_write(_second_fall_back(), 45.0, 0.0, 1600.0, HELD).state
    state, _, _ = step(state, 45.0, 45.0, 1610.0, HELD)
    return state


def _switched_on_without_echo() -> GuardState:
    state, _, _ = step(GuardState(), 1.0, None, 0.0, SWITCH)
    return state


_OUTSIDE = GuardEvent.OUTSIDE_CHANGE
PLAN_PRECEDENCE = [
    # (what the row shows, state, desired, read-back, now, config, expected)
    (
        "a target declared persistent: nothing, whatever else holds",
        lambda: write_failed(held(HELD)),
        50.0,
        0.0,
        400.0,
        _PERSISTENT,
        (None, (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "a target of unknown write type: nothing",
        lambda: write_failed(held(HELD)),
        50.0,
        0.0,
        400.0,
        _UNDECLARED,
        (None, (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "a block beats a failed write and a new value",
        lambda: write_failed(replace(held(HELD), blocked=_OUTSIDE)),
        50.0,
        60.0,
        400.0,
        HELD,
        (None, (), ChangeClass.NOT_JUDGED, False, _OUTSIDE),
    ),
    (
        '"ignored from the start" beats a failed write and a new value',
        lambda: write_failed(replace(held(HELD), ignored=True)),
        50.0,
        60.0,
        400.0,
        HELD,
        (None, (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "nothing desired beats a failed write",
        lambda: write_failed(held(HELD)),
        None,
        60.0,
        400.0,
        HELD,
        (None, (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "the plugin's own failed write is sent again before anything is judged",
        _after_foreign_step,
        45.0,
        60.0,
        410.0,
        HELD,
        (WriteAction(45.0, WriteKind.RESEND), (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "a lost command: sent again, counted",
        lambda: held(HELD),
        45.0,
        0.0,
        400.0,
        HELD,
        (WriteAction(45.0, WriteKind.RESEND), (), ChangeClass.LOST_COMMAND, True, None),
    ),
    (
        "another controller: the one rewrite",
        _second_fall_back,
        45.0,
        0.0,
        1600.0,
        HELD,
        (WriteAction(45.0, WriteKind.REWRITE), (), ChangeClass.ANOTHER_CONTROLLER, False, None),
    ),
    (
        "another controller again within the day: blocked, nothing written",
        _rewritten,
        45.0,
        0.0,
        2200.0,
        HELD,
        (None, (_OUTSIDE,), ChangeClass.ANOTHER_CONTROLLER, False, _OUTSIDE),
    ),
    (
        "a new value of the plugin's own",
        lambda: held(HELD),
        50.0,
        45.0,
        160.0,
        HELD,
        (WriteAction(50.0, WriteKind.CHANGE), (), ChangeClass.CONFIRMED, False, None),
    ),
    (
        "nothing new, nothing due",
        lambda: held(HELD),
        45.0,
        45.0,
        160.0,
        HELD,
        (None, (), ChangeClass.CONFIRMED, False, None),
    ),
    (
        "a held value's refresh",
        lambda: keep(held(HELD), HELD, 160.0, 290.0),
        45.0,
        45.0,
        300.0,
        HELD,
        (WriteAction(45.0, WriteKind.KEEPALIVE), (), ChangeClass.CONFIRMED, False, None),
    ),
    (
        "without an echo, another value is never judged",
        _switched_on_without_echo,
        1.0,
        0.0,
        20.0,
        SWITCH,
        (None, (), ChangeClass.NOT_JUDGED, False, None),
    ),
    (
        "without an echo, the refresh still goes out",
        _switched_on_without_echo,
        1.0,
        0.0,
        300.0,
        SWITCH,
        (WriteAction(1.0, WriteKind.KEEPALIVE), (), ChangeClass.NOT_JUDGED, False, None),
    ),
]


@pytest.mark.parametrize(
    ("given", "desired", "read_back", "now", "config", "expected"),
    [row[1:] for row in PLAN_PRECEDENCE],
    ids=[row[0] for row in PLAN_PRECEDENCE],
)
def test_the_precedence_of_a_write_plan(
    given: Callable[[], GuardState],
    desired: float | None,
    read_back: float | None,
    now: float,
    config: GuardConfig,
    expected: tuple,
) -> None:
    """P-115: exactly this action, these events, this class, this loss and this block."""
    result = plan_write(given(), desired, read_back, now, config)
    assert (
        result.action,
        result.events,
        result.judged,
        result.lost,
        result.state.blocked,
    ) == expected
