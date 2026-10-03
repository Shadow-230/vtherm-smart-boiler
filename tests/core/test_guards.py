"""Write guards: one per target — the setpoint, and heating on/off as 1 and 0 — and decision 6's
four classes of a change seen in the read-back (lost command, ignored from the start, clipped,
another controller), with the user's answers E, H and O of 2026-09-27."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    DAY,
    HELD_REFRESH_S,
    HOUR,
    PREVIOUS_EXEMPT_S,
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
    value_not_shown,
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
        left=((9000.0, 40.0),),
        missed=(9000.0,),
        change_at=9000.0,
        draw_at=9000.0,
    )
    result = result_of(state, 45.0, 45.0, 500.0, HELD)
    assert result.state.fallbacks == (500.0,)
    assert result.state.recent == ((500.0, 45.0),)
    assert result.state.left == ((500.0, 40.0),)  # K4.3: a replaced value's moment, not its value
    assert result.state.missed == (500.0,)  # KD-01: a missed send's moment
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
    [(HELD, 0.0, 45.0, 50.0), (EXPIRING, 0.0, 45.0, 50.0)],
    ids=["held", "expiring"],
)
def test_a_late_echo_of_the_previous_value_is_not_judged_until_the_new_one_is_read_back(
    config: GuardConfig, first: float, previous: float, new: float
) -> None:
    """Z4-01's negative for the setpoint, as Z4R-01 corrects it (M8: "its previous one", until
    the plugin's new value has been read back): the plugin's previous value still read back after
    the plugin sent a new one is a late echo or the device's own limit, not judged however long
    it lasts — no rewrite, no event, shown waiting, then not confirmed once the timeout has
    passed. Once the new value has been read back, a return to the previous one is judged like
    any other value: held two steps, the one rewrite. (Heating on/off's previous state is exempt
    only within the timeout: Z4R2-03,
    ``test_a_heating_switch_never_showing_its_new_state_is_judged_within_minutes``.)"""
    state = held(config, first=first, value=previous)
    state = keep(state, config, 160.0, 990.0, previous, previous)
    state, action, _ = step(state, new, previous, 1000.0, config)
    assert action == WriteAction(new, WriteKind.CHANGE)
    for t in range(1010, 1610, 10):  # ten minutes, far past the timeout
        result = result_of(state, new, previous, float(t), config)
        state = result.state
        assert result.judged is ChangeClass.NOT_JUDGED
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    assert confirmation(state, config) is Confirmation.NOT_CONFIRMED
    assert state.rewritten_at is None
    assert state.blocked is None
    state = keep(state, config, 1610.0, 1650.0, new, new)  # the new value read back at last
    assert confirmation(state, config) is Confirmation.CONFIRMED
    result = result_of(state, new, previous, 1660.0, config)  # back to the previous one
    assert result.judged is ChangeClass.NOT_JUDGED  # one step (M10)
    result = result_of(result.state, new, previous, 1670.0, config)  # held two steps
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(new, WriteKind.REWRITE)


@pytest.mark.parametrize("config", [HELD, EXPIRING], ids=["held", "expiring"])
def test_a_boiler_limit_at_the_previous_value_is_clipped_not_another_controller(
    config: GuardConfig,
) -> None:
    """Z4R-01 (decision 6's "clipped"): a read-back on a whole-degree grid that shows the
    boiler's own selected water temperature, held at its dial of 55 °C (EMS-ESP's
    ``selflowtemp``, say). 55 confirmed; the curve rises and the plugin sends 56: the read-back
    stays at 55, the plugin's previous value — not judged for ten minutes, no rewrite, no event;
    then 57: one lower value across sent values 1 K apart — clipped, information only, never
    another controller."""
    state = keep(held(config, value=55.0), config, 160.0, 590.0, 55.0, 55.0)
    state, action, _ = step(state, 56.0, 55.0, 600.0, config)
    assert action == WriteAction(56.0, WriteKind.CHANGE)
    for t in range(610, 1210, 10):
        result = result_of(state, 56.0, 55.0, float(t), config)
        state = result.state
        assert result.judged is ChangeClass.NOT_JUDGED
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    state, action, _ = step(state, 57.0, 55.0, 1210.0, config)
    assert action == WriteAction(57.0, WriteKind.CHANGE)
    judged = []
    for t in range(1220, 1400, 10):
        result = result_of(state, 57.0, 55.0, float(t), config)
        state = result.state
        judged.append(result.judged)
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    assert ChangeClass.CLIPPED in judged
    assert ChangeClass.ANOTHER_CONTROLLER not in judged
    assert state.clip == 55.0
    assert confirmation(state, config) is Confirmation.CLIPPED
    assert state.rewritten_at is None
    assert state.blocked is None


@pytest.mark.parametrize(
    ("config", "lag"),
    [(HELD, 150.0), (HELD, 200.0), (EXPIRING, 260.0), (ECHOED, 100.0), (ECHOED, 240.0)],
    ids=[
        "setpoint_150s",
        "setpoint_200s",
        "setpoint_260s_expiring",
        "heating_switch_100s",
        "heating_switch_240s",
    ],
)
def test_a_slow_read_back_showing_the_previous_value_is_not_another_controller(
    config: GuardConfig, lag: float
) -> None:
    """Z4R-01: a setpoint read-back that shows each value 150-260 s late — an integration that
    polls the device every few minutes — while the plugin's value moves 2 K every 5 minutes: for
    six hours it shows the plugin's previous value after each change, then the new one. Never
    another controller: no rewrite, no block, no event. A heating echo within 5 minutes (100 s,
    240 s) alike — its previous state is exempt that long (K4.3); one slower than that is judged
    (``test_a_two_valued_echo_slower_than_five_minutes_is_judged``)."""
    if config.two_valued:

        def desired(t: float) -> float:
            return ON if int(t // 300) % 2 == 0 else OFF

        before = OFF
    else:

        def desired(t: float) -> float:
            return 40.0 + 2.0 * (int(t // 300) % 5)

        before = 0.0
    state = GuardState()
    t = 0.0
    while t <= 6 * HOUR:
        shown = desired(t - lag) if t >= lag else before
        result = result_of(state, desired(t), shown, t, config)
        state = result.state
        assert result.events == (), t
        assert result.action is None or result.action.kind is not WriteKind.REWRITE, t
        assert result.judged is not ChangeClass.ANOTHER_CONTROLLER, t
        t += 10.0
    assert state.rewritten_at is None
    assert state.blocked is None
    assert not state.ignored


def test_a_two_valued_echo_slower_than_five_minutes_is_judged() -> None:
    """K4.3's known limit (decided by the user 2026-10-03): a heating echo that shows each state
    330 s late, heating switched every 10 minutes. Its previous state is exempt only for 5 minutes
    after the send (``PREVIOUS_EXEMPT_S``), so the late echo is judged: back at the value from
    before the plugin, a lost command; away from it, another controller — the one rewrite, then,
    the echo still late, the guard blocks."""
    assert PREVIOUS_EXEMPT_S == 300.0
    judged = []
    state = GuardState()
    t = 0.0
    while t <= 2 * HOUR:
        desired = ON if int(t // 600) % 2 == 0 else OFF
        late = t - 330.0
        shown = (ON if int(late // 600) % 2 == 0 else OFF) if late >= 0.0 else ON
        reported = (late // 600) * 600 + 330.0 if late >= 0.0 else -HOUR
        result = result_of(state, desired, shown, t, ECHOED, reported_at=reported)
        state = result.state
        judged.append(result.judged)
        if state.blocked is not None:
            break
        t += 10.0
    assert ChangeClass.ANOTHER_CONTROLLER in judged
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    assert t < 1 * HOUR


@pytest.mark.parametrize("case", ["stuck_on", "stuck_on_echo_unknown", "stuck_off", "reverted"])
def test_a_heating_switch_never_showing_its_new_state_is_judged_within_minutes(case: str) -> None:
    """Z4R2-03: heating on/off whose new state no step ever sees — the device stuck at the
    plugin's previous state, or an automation putting it back within a step of every write — is
    judged once 5 minutes after the send have passed (K4.3, decided by the user 2026-10-03; the
    confirmation timeout before), as decision 6 says: here the previous state is not the value
    from before the plugin, so another controller — the one rewrite at 5 min 20 s, and with it
    still not taken, the guard blocks at 7 min 20 s: the plugin steps aside within minutes.
    Stuck on (answer O's case: "off" before the plugin, or its echo unknown, the session's first
    "on" taken, then "off" never taken): heating without demand. Stuck off (its cold twin):
    "on" never taken while the plugin holds the boiler. Reverted: the OTGW's 30-s refresh writes
    "on" again and again, put back every time — no longer for good."""
    otgw = GuardConfig(write_type=WriteType.HELD, two_valued=True, refresh_s=30.0)
    config = otgw if case == "reverted" else ECHOED
    if case.startswith("stuck_on"):
        first = None if case == "stuck_on_echo_unknown" else OFF
        state, _, _ = step(GuardState(), ON, first, 0.0, config)
        state = keep(state, config, 10.0, 50.0, ON, ON)  # "on" taken, the start phase not over
        changed, new, stuck = 60.0, OFF, ON
    else:
        state = keep(held(config, first=ON, value=ON), config, 160.0, 990.0, ON, ON)
        state, _, _ = step(state, OFF, ON, 1000.0, config)
        state = keep(state, config, 1010.0, 1990.0, OFF, OFF)  # "off" taken
        changed, new, stuck = 2000.0, ON, OFF
    state, action, _ = step(state, new, stuck, changed, config)
    assert action == WriteAction(new, WriteKind.CHANGE)
    seen = []
    t = changed + 10.0
    while t <= changed + 600.0:
        result = result_of(state, new, stuck, t, config)
        state = result.state
        seen.append((t, result.judged, result.action, result.events))
        if state.blocked is not None:
            break
        t += 10.0
    rewrites = [at for at, _j, action, _e in seen if action == WriteAction(new, WriteKind.REWRITE)]
    # Nothing before the 5 minutes and two steps; with the echo unknown at the first send, that
    # unknown is a trace for 5 min, in which the other state is the device's own (uncounted).
    first_judged = changed + PREVIOUS_EXEMPT_S + 20.0
    assert rewrites == [first_judged]
    assert all(not events for at, _j, _a, events in seen if at < first_judged)
    assert seen[-1][3] == (GuardEvent.OUTSIDE_CHANGE,)
    assert seen[-1][0] == first_judged + 120.0  # the rewrite not read back: within minutes
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    if case == "reverted":
        refreshes = [
            at for at, _j, action, _e in seen if action == WriteAction(new, WriteKind.KEEPALIVE)
        ]
        assert refreshes  # written again meanwhile, then never more: blocked


@pytest.mark.parametrize("cause", ["unknown", "draw"])
def test_a_heating_switch_previous_state_is_not_judged_while_unknown_or_during_a_draw(
    cause: str,
) -> None:
    """Z4R2-03's negatives, past the previous state's 5 minutes (K4.3): an unknown read-back is
    never judged — nothing written over it, no rewrite, no block; a hot-water draw (and the 2 min
    after it) is not judged either, the previous state shown or not. The draw over, the previous
    state still shown is judged as usual."""
    state = keep(held(ECHOED, first=ON, value=ON), ECHOED, 160.0, 990.0, ON, ON)
    state, _, _ = step(state, OFF, ON, 1000.0, ECHOED)
    state = keep(state, ECHOED, 1010.0, 1990.0, OFF, OFF)
    state, _, _ = step(state, ON, OFF, 2000.0, ECHOED)
    for t in range(2010, 2400, 10):
        if cause == "unknown":
            result = result_of(state, ON, None, float(t), ECHOED)
        else:
            result = result_of(state, ON, OFF, float(t), ECHOED, dhw=t < 2270)
        state = result.state
        assert result.judged is ChangeClass.NOT_JUDGED, t
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    assert state.rewritten_at is None
    assert state.blocked is None
    if cause == "draw":  # 2 min after the draw: judged
        result = result_of(state, ON, OFF, 2400.0, ECHOED)
        assert result.judged is ChangeClass.ANOTHER_CONTROLLER
        assert result.action == WriteAction(ON, WriteKind.REWRITE)


def _tpi_demand(seed: int) -> Callable[[float], float]:
    """VT's TPI pulses for heating on/off: a 10-min cycle, its duty drawn for each cycle — off,
    short pulses, long ones, full."""
    rng = random.Random(seed)
    duties = [rng.choice((0.0, 0.1, 0.2, 0.35, 0.5, 0.65, 0.8, 0.9, 1.0)) for _ in range(80)]

    def demand(t: float) -> float:
        cycle = int(t // 600.0)
        return ON if t - cycle * 600.0 < duties[cycle] * 600.0 else OFF

    return demand


@pytest.mark.parametrize("poll_s", [150.0, 240.0], ids=["150s", "240s"])
def test_a_polled_heating_read_back_is_never_judged(poll_s: float) -> None:
    """K4.3 (decided by the user 2026-10-03; Z4R3-03): a heating read-back polled every 150 s or
    240 s — some ebusd or cloud set-ups — while VT's TPI pulses switch heating for 12 hours, from
    the session's first send, at three poll phases. The device takes each write at once; the
    read-back shows it at the next poll. The previous state is exempt for 5 minutes after the
    send that replaced it — the value from before the plugin included — so a poll not yet made
    is never judged: no rewrite, no step aside, no "ignored from the start", and no lost command
    counted (before: another controller within hours)."""
    for seed in range(3):
        for phase in (0.0, 37.0, 113.0):
            demand = _tpi_demand(seed)
            device = shown = OFF
            shown_at = -HOUR  # from before the plugin
            next_poll = phase
            state = GuardState()
            t = 0.0
            while t <= 12 * HOUR:
                if t >= next_poll:
                    if device != shown:
                        shown, shown_at = device, next_poll
                    next_poll += poll_s
                result = result_of(state, demand(t), shown, t, ECHOED, reported_at=shown_at)
                state = result.state
                if result.action is not None:
                    device = result.action.value
                assert result.judged not in (
                    ChangeClass.ANOTHER_CONTROLLER,
                    ChangeClass.LOST_COMMAND,
                    ChangeClass.IGNORED_FROM_START,
                ), (seed, phase, t, result.judged)
                assert result.events == (), (seed, phase, t)
                t += 10.0
            assert state.rewritten_at is None
            assert state.blocked is None
            assert not state.ignored


def _zones_demand(offsets: tuple[float, ...], on_s: float) -> Callable[[float], float]:
    """Heating on while any zone's TPI pulse is on: each ``on_s`` long every 300 s, staggered."""

    def demand(t: float) -> float:
        return ON if any((t - offset) % 300.0 < on_s for offset in offsets) else OFF

    return demand


def _late_echo_patterns() -> list[Callable[[float], float]]:
    rng = random.Random(1)
    patterns = [_zones_demand((0.0,), 60.0), _zones_demand((0.0, 100.0, 200.0), 60.0)]
    for _ in range(6):
        offsets = tuple(round(rng.uniform(0.0, 300.0), -1) for _ in range(3))
        patterns.append(_zones_demand(offsets, round(rng.uniform(30.0, 120.0), -1)))
    return patterns


@pytest.mark.parametrize("lag", ["60s", "90s", "115s", "30_to_120s"])
def test_a_late_echo_beside_short_vt_pulses_is_never_judged(lag: str) -> None:
    """K4.3 (Z4R3-01): VT pulses heating "on" for 60 s every 300 s — or three zones' pulses
    staggered, heating switched both ways within a minute — while the heating switch's echo
    reaches Home Assistant 60 to 120 s late, in order (a scripted or cloud-backed switch), for 12
    hours. A stale report never counts as the read-back of a newer send: not one from before the
    send, nor one that may still be the echo of an earlier send of the same state (the state
    between not read back yet, within 5 minutes). So the plugin's own late echo is never judged:
    no rewrite, no step aside, no lost command (before: another controller within hours)."""
    rng = random.Random(7)
    for demand in _late_echo_patterns():
        device = shown = OFF
        shown_at = last = -HOUR
        reports: list[tuple[float, float]] = []  # (when Home Assistant shows it, the state)
        state = GuardState()
        t = 0.0
        while t <= 12 * HOUR:
            while reports and reports[0][0] <= t:
                shown_at, shown = reports.pop(0)
            result = result_of(state, demand(t), shown, t, ECHOED, reported_at=shown_at)
            state = result.state
            if result.action is not None and result.action.value != device:
                device = result.action.value
                delay = rng.uniform(30.0, 120.0) if lag == "30_to_120s" else float(lag[:-1])
                last = max(last, t + delay)
                reports.append((last, device))
            assert result.judged not in (
                ChangeClass.ANOTHER_CONTROLLER,
                ChangeClass.LOST_COMMAND,
            ), (t, result.judged)
            assert result.events == (), t
            t += 10.0
        assert state.rewritten_at is None
        assert state.blocked is None


def test_a_stale_report_is_never_the_read_back_of_a_newer_send() -> None:
    """Z4R3-01 at one toggle: "off" read back, then VT asks "on" at 1000 and "off" again at
    1060; the echo comes 90 s late. At 1060 the echo still shows "off" from before 1000 — a
    report older than the send: not its read-back, so the plugin's "on" arriving at 1090 is still
    its exempt previous state, not judged; the echo of "off" at 1150 is newer than the send, but
    may still be the echo of the "off" before 1000 while "on" was never read back: counted only
    once that earlier "off" can no longer be in flight (5 minutes). A switch to "on" after that
    is judged as usual: another controller, "on" not being the value from before the plugin."""
    state = keep(held(ECHOED, first=OFF, value=OFF), ECHOED, 160.0, 990.0, OFF, OFF)
    old = 10.0  # the echo has shown "off" since then — the value from before the plugin
    state, action, _ = step(state, ON, OFF, 1000.0, ECHOED, reported_at=old)
    assert action == WriteAction(ON, WriteKind.CHANGE)
    for t in range(1010, 1060, 10):
        state, _, events = step(state, ON, OFF, float(t), ECHOED, reported_at=old)
        assert events == ()
    state, action, _ = step(state, OFF, OFF, 1060.0, ECHOED, reported_at=old)
    assert action == WriteAction(OFF, WriteKind.CHANGE)
    assert not state.taken  # shown, but by a report from before the send
    for t in range(1070, 1150, 10):
        shown, at = (ON, 1090.0) if t >= 1090 else (OFF, old)
        result = result_of(state, OFF, shown, float(t), ECHOED, reported_at=at)
        state = result.state
        assert result.judged is not ChangeClass.ANOTHER_CONTROLLER, t
        assert result.events == ()
        assert result.action is None or result.action.kind is WriteKind.KEEPALIVE
    for t in range(1150, 1350, 10):
        state, _, events = step(state, OFF, OFF, float(t), ECHOED, reported_at=1150.0)
        assert events == ()
        assert state.taken is (t > 1000 + PREVIOUS_EXEMPT_S), t
    first = result_of(state, OFF, ON, 1350.0, ECHOED, reported_at=1350.0)  # switched from outside
    assert first.judged is ChangeClass.NOT_JUDGED  # one step
    result = result_of(first.state, OFF, ON, 1360.0, ECHOED, reported_at=1350.0)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(OFF, WriteKind.REWRITE)


def test_a_stale_setpoint_report_is_not_the_read_back_of_a_newer_send() -> None:
    """Z4R3-01 for the setpoint, a ramp reversed within the read-back's lag (Z4R2-04's family):
    45 read back; 50 sent at 1000, 45 again at 1060 — the read-back still shows 45 from before
    1000: not the read-back of the second send, so the late 50 is still the exempt previous
    value, not judged. Its own echo, later, is."""
    state = keep(held(HELD), HELD, 160.0, 990.0)
    old = 10.0
    state, action, _ = step(state, 50.0, 45.0, 1000.0, HELD, reported_at=old)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state, action, _ = step(state, 45.0, 45.0, 1060.0, HELD, reported_at=old)
    assert action == WriteAction(45.0, WriteKind.CHANGE)
    assert not state.taken
    for t in range(1070, 1700, 10):
        shown, at = (
            (50.0, 1090.0) if 1090 <= t < 1150 else ((45.0, 1150.0) if t >= 1150 else (45.0, old))
        )
        result = result_of(state, 45.0, shown, float(t), HELD, reported_at=at)
        state = result.state
        assert result.judged is not ChangeClass.ANOTHER_CONTROLLER, t
        assert result.events == ()
    assert state.taken  # its own echo, once the earlier 45 can no longer be in flight
    assert state.rewritten_at is None


MIN = 60.0
STUCK_AT = 2 * HOUR  # the switch works until then
# VT's pulses through the heating switch: a 2-, 5- or 10-min cycle at a duty.
STUCK_PULSES = [(120.0, 0.5), (300.0, 0.3), (300.0, 0.5), (300.0, 0.7), (600.0, 0.5)]
STUCK_PULSE_IDS = ["2min_50", "5min_30", "5min_50", "5min_70", "10min_50"]


def _pulses(cycle_s: float, duty: float) -> Callable[[float], float]:
    return lambda t: ON if t % cycle_s < duty * cycle_s else OFF


def _stuck_run(
    demand: Callable[[float], float],
    case: str,
    refresh_s: float,
    *,
    hours: float = 3.0,
    unknown: tuple[float, float] | None = None,
    draw: tuple[float, float] | None = None,
) -> tuple[float | None, list[tuple[float, ChangeClass, tuple[GuardEvent, ...]]], GuardState]:
    """VT's pulses through a heating switch, "off" before the plugin, whose read-back reports each
    change 5 s after it, in order. From ``STUCK_AT`` the switch sticks (``case``): "on" whatever
    it is told (stuck_on), "off" whatever it is told (stuck_off), or put back "on" by an
    automation 3 s after every "off" — between two steps, so no step shows the "off" (reverted).
    ``unknown``: the read-back unknown between the two moments; ``draw``: hot water then. Returns
    when the switch first ignored a command, the judgements from ``STUCK_AT`` on (when, class,
    events), and the guard's last state."""
    config = GuardConfig(write_type=WriteType.HELD, two_valued=True, refresh_s=refresh_s)
    state = GuardState()
    device = shown = OFF
    shown_at = -HOUR
    reports: list[tuple[float, float]] = []
    ignored: float | None = None
    judged: list[tuple[float, ChangeClass, tuple[GuardEvent, ...]]] = []
    t = 0.0
    while t <= hours * HOUR and state.blocked is None:
        reports.sort()
        while reports and reports[0][0] <= t:
            at, value = reports.pop(0)
            if value != shown:
                shown, shown_at = value, at
        gone = unknown is not None and unknown[0] <= t < unknown[1]
        dhw = draw is not None and draw[0] <= t < draw[1]
        result = result_of(
            state, demand(t), None if gone else shown, t, config, reported_at=shown_at, dhw=dhw
        )
        state = result.state
        stuck = t >= STUCK_AT
        if result.action is not None:
            value = result.action.value
            if stuck and case == "stuck_on" and value == OFF:
                value, ignored = ON, ignored if ignored is not None else t
            if stuck and case == "stuck_off" and value == ON:
                value, ignored = OFF, ignored if ignored is not None else t
            device = value
            reports.append((t + 5.0, device))
            if stuck and case == "reverted" and value == OFF:
                device, ignored = ON, ignored if ignored is not None else t
                reports.append((t + 8.0, ON))
        if stuck and result.judged in (ChangeClass.LOST_COMMAND, ChangeClass.ANOTHER_CONTROLLER):
            judged.append((t, result.judged, result.events))
        t += 10.0
    return ignored, judged, state


@pytest.mark.parametrize("refresh_s", [HELD_REFRESH_S, 30.0], ids=["entity", "otgw"])
@pytest.mark.parametrize(("cycle_s", "duty"), STUCK_PULSES, ids=STUCK_PULSE_IDS)
@pytest.mark.parametrize("case", ["stuck_on", "stuck_off", "reverted"])
def test_a_stuck_heating_switch_is_judged_whatever_vt_pulses(
    case: str, cycle_s: float, duty: float, refresh_s: float
) -> None:
    """KD-01: while VT pulses heating every 5 min or less, the previous state's 5 minutes start
    again at every send, so a switch stuck in one state — or put back by an automation no step
    sees — was never judged (heating without demand for hours, or no heat and nothing said).
    The stuck test, independent of those 5 minutes: the read-back has not changed while the
    plugin sent the other state at least twice, each time longer than this read-back takes to
    show a change, the first 5 minutes ago or more — then decision 6's classes judge it, here
    within 11 minutes of the first ignored command whatever the pulses. Stuck "on", or put back
    "on": another controller — the one rewrite, and the guard blocks within 14 minutes. Stuck
    "off", the value from before the plugin: answer E's fall-back rules — lost commands, sent
    again, "commands lost" within the half hour; never a block."""
    ignored, judged, state = _stuck_run(_pulses(cycle_s, duty), case, refresh_s)
    assert ignored is not None
    assert judged, "never judged"
    first, kind, _events = judged[0]
    assert first - ignored <= 11 * MIN, (first - ignored) / MIN
    if case == "stuck_off":
        assert kind is ChangeClass.LOST_COMMAND
        assert all(k is ChangeClass.LOST_COMMAND for _t, k, _e in judged)
        assert len([t for t, _k, _e in judged if t - ignored <= 30 * MIN]) >= 3
        assert state.blocked is None
        return
    assert kind is ChangeClass.ANOTHER_CONTROLLER
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    last, _kind, events = judged[-1]
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert last - ignored <= 14 * MIN, (last - ignored) / MIN


@pytest.mark.parametrize("poll_s", [150.0, 240.0], ids=["150s", "240s"])
def test_a_polled_read_back_of_a_working_switch_is_never_judged_stuck(poll_s: float) -> None:
    """KD-01's negative: a working switch whose read-back is polled every 150 s or 240 s, with
    the stuck test's pulses — 2-, 5- and 10-min cycles — for 12 hours, at six poll phases. Its
    read-back changes now and then, the delay of its echoes is learned (up to the poll
    interval, from three echoes on), and a pulse shorter than three times that delay plus 30 s
    never counts as missed: never judged.

    The remaining risk is aliasing: a poll locked to VT's cycle — its interval a divisor or a
    multiple of the cycle — samples the same phases of it for good, so every echo it shows comes
    the same short time after a send, and the delay it teaches is that short time, not its
    interval. If VT's duty then moves so that all those phases fall in one state, the other
    state's pulses are never shown, and the switch looks stuck and is judged as a stuck one would
    be — e.g. a 150-s poll 13 s into a 600-s cycle: at 50 % its four phases teach 13 s, at 80 %
    they all fall while heating is on, and the 120-s "off" pulses count as missed."""
    for cycle_s, duty in STUCK_PULSES:
        for phase in (0.0, 37.0, 61.0, 89.0, 113.0, 140.0):
            demand = _pulses(cycle_s, duty)
            device = shown = OFF
            shown_at = -HOUR
            next_poll = phase
            state = GuardState()
            t = 0.0
            while t <= 12 * HOUR:
                if t >= next_poll:
                    if device != shown:
                        shown, shown_at = device, next_poll
                    next_poll += poll_s
                result = result_of(state, demand(t), shown, t, ECHOED, reported_at=shown_at)
                state = result.state
                if result.action is not None:
                    device = result.action.value
                assert result.judged not in (
                    ChangeClass.ANOTHER_CONTROLLER,
                    ChangeClass.LOST_COMMAND,
                    ChangeClass.IGNORED_FROM_START,
                ), (cycle_s, duty, phase, t, result.judged)
                assert result.events == (), (cycle_s, duty, phase, t)
                t += 10.0
            assert state.blocked is None


def test_one_early_poll_does_not_make_a_slow_read_back_look_prompt() -> None:
    """KD-01's negative, from the check's probe: a working switch, its read-back polled every
    217 s, two zones' pulses of 245 s on a 15-min cycle. The first poll comes 3 s after a send —
    a 3-s echo delay, had one echo been trusted, would count the next two "off" pulses the polls
    miss as missed and judge another controller 14 minutes in. The delay is trusted only from
    three echoes on, by which time it has shown itself long: never judged in 12 hours."""
    offsets, on_s, poll_s, phase = (545.0, 202.0), 245.0, 216.8, 213.4

    def demand(t: float) -> float:
        return ON if any((t - offset) % 900.0 < on_s for offset in offsets) else OFF

    device = shown = OFF
    shown_at = -HOUR
    next_poll = phase
    state = GuardState()
    t = 0.0
    while t <= 12 * HOUR:
        while next_poll <= t:
            if device != shown:
                shown, shown_at = device, next_poll
            next_poll += poll_s
        result = result_of(state, demand(t), shown, t, ECHOED, reported_at=shown_at)
        state = result.state
        if result.action is not None:
            device = result.action.value
        assert result.judged is not ChangeClass.ANOTHER_CONTROLLER, t
        assert result.events == (), t
        t += 10.0
    assert state.echo_s is not None
    assert state.echo_s > 100.0  # learned: the poll interval shows
    assert state.rewritten_at is None


@pytest.mark.parametrize("cause", ["unknown", "draw"])
def test_a_stuck_heating_switch_is_not_judged_while_unknown_or_during_a_draw(cause: str) -> None:
    """KD-01's negatives: the switch stuck "on" under 5-min pulses at 30 %. Its read-back unknown
    for half an hour from the first ignored command — nothing judged meanwhile; a hot-water draw
    for as long — nothing judged during it or for 2 min after. Either way the missed sends are
    counted afresh once the read-back is known, or the draw over: another controller only after
    4 minutes or more, within 11. (Back from unknown, the read-back's outage is a trace for 5
    minutes, in which "on" is the device's own state: lost commands, sent again — answer C.)"""
    window = (STUCK_AT + 90.0, STUCK_AT + 90.0 + 30 * MIN)  # the first "off" ignored at +90 s
    keyword = {"unknown": window} if cause == "unknown" else {"draw": window}
    ignored, judged, state = _stuck_run(_pulses(300.0, 0.3), "stuck_on", HELD_REFRESH_S, **keyword)
    assert ignored == STUCK_AT + 90.0
    end = window[1] + (0.0 if cause == "unknown" else 120.0)
    assert [t for t, _k, _e in judged if t < end] == []
    others = [t for t, kind, _e in judged if kind is ChangeClass.ANOTHER_CONTROLLER]
    assert others, "never judged"
    assert 4 * MIN < others[0] - window[1] <= 11 * MIN  # counted afresh, not at once
    lost = [t for t, kind, _e in judged if kind is ChangeClass.LOST_COMMAND]
    assert all(t - window[1] <= 5 * MIN for t in lost)  # only within the outage's trace
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_a_setpoint_not_shown_for_five_minutes_raises_confirmation_missing() -> None:
    """Z4R2-03 for the setpoint, which keeps Z4R-01's rule: its new value not read back while
    the read-back is known and shows another value — here the plugin's previous one, held by the
    device — is never judged by itself; after 5 minutes it is "the boiler does not show the
    plugin's value": the information alarm "confirmation missing" and the repair issue
    (``value_not_shown``), never a rewrite or a block. Both end once the value is read back.
    Negatives: 4 min 50 s — neither; an unknown read-back — the alarm's own rule only, not
    "not shown"; a hot-water draw — not counted."""
    state = keep(held(HELD), HELD, 160.0, 990.0)
    state, _, _ = step(state, 50.0, 45.0, 1000.0, HELD)
    for t in range(1010, 1290, 10):
        state, _, events = step(state, 50.0, 45.0, float(t), HELD)
        assert events == ()
    assert not value_not_shown(state, 1290.0)
    assert not confirmation_missing(state, 1290.0)
    state, _, _ = step(state, 50.0, 45.0, 1300.0, HELD)  # the read-back since 1010
    assert value_not_shown(state, 1310.0)
    assert confirmation_missing(state, 1310.0)
    state = keep(state, HELD, 1310.0, 1900.0, 50.0, 45.0)  # never judged by itself
    assert state.rewritten_at is None
    assert state.blocked is None
    state, _, _ = step(state, 50.0, 50.0, 1910.0, HELD)  # read back at last
    assert not value_not_shown(state, 1910.0)
    assert not confirmation_missing(state, 1910.0)

    unknown = keep(held(HELD), HELD, 160.0, 990.0)
    unknown, _, _ = step(unknown, 50.0, 45.0, 1000.0, HELD)
    unknown = keep(unknown, HELD, 1010.0, 1400.0, 50.0, None)
    assert confirmation_missing(unknown, 1400.0)  # M11: the read-back unknown
    assert not value_not_shown(unknown, 1400.0)

    draw = keep(held(HELD), HELD, 160.0, 990.0)
    draw, _, _ = step(draw, 50.0, 45.0, 1000.0, HELD)
    for t in range(1010, 1400, 10):
        draw, _, _ = step(draw, 50.0, 45.0, float(t), HELD, dhw=True)
    assert not value_not_shown(draw, 1400.0)


def test_heating_switched_back_within_120_s_of_a_confirmed_toggle_is_judged() -> None:
    """Z4R-01: the OTGW's heating switch, its ``CH=`` refreshed every 30 s. "On" before the
    plugin; the plugin switched heating off, then on again — read back at once. A person switches
    heating off 40 s after that toggle: the plugin's previous state, but its new one was read back
    — judged at once: one step not judged and nothing written over it, the second the one rewrite.
    (Within 120 s of the toggle the refresh used to write over it, unjudged.)"""
    otgw = GuardConfig(write_type=WriteType.HELD, two_valued=True, refresh_s=30.0)
    state = keep(held(otgw, first=ON, value=ON), otgw, 160.0, 990.0, ON, ON)
    state, action, _ = step(state, OFF, ON, 1000.0, otgw)
    assert action == WriteAction(OFF, WriteKind.CHANGE)
    state = keep(state, otgw, 1010.0, 1990.0, OFF, OFF)
    state, action, _ = step(state, ON, OFF, 2000.0, otgw)
    assert action == WriteAction(ON, WriteKind.CHANGE)
    state = keep(state, otgw, 2010.0, 2030.0, ON, ON)  # read back; refreshed at 2030
    first = result_of(state, ON, OFF, 2040.0, otgw)  # switched off by a person
    assert first.judged is ChangeClass.NOT_JUDGED
    assert first.action is None  # no refresh over it
    result = result_of(first.state, ON, OFF, 2050.0, otgw)
    assert result.judged is ChangeClass.ANOTHER_CONTROLLER
    assert result.action == WriteAction(ON, WriteKind.REWRITE)


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
