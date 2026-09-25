"""Write guards: one per target — the setpoint, and heating on/off as 1 and 0."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    Confirmation,
    GuardConfig,
    GuardEvent,
    GuardState,
    WriteAction,
    WriteKind,
    WriteType,
    confirmation,
    plan_write,
    write_failed,
)

EXPIRING = GuardConfig(write_type=WriteType.EXPIRING)
HELD = GuardConfig(write_type=WriteType.HELD)


def step(state, desired, confirmed, now, config):
    result = plan_write(state, desired, confirmed, now, config)
    return result.state, result.action, result.events


def test_first_write_and_expiring_keepalive() -> None:
    state, action, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.CHANGE)
    state, action, _ = step(state, 45.0, 45.0, 20.0, EXPIRING)
    assert action is None
    state, action, _ = step(state, 45.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)


def test_held_writes_on_change_only() -> None:
    state, action, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    assert action is not None
    state, action, _ = step(state, 45.0, 45.0, 600.0, HELD)
    assert action is None  # no keep-alive


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


def test_ignored_write_is_reported_once_and_writing_continues() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, events = step(state, 45.0, 30.0, 60.0, EXPIRING)
    assert events == ()
    state, action, events = step(state, 45.0, 30.0, 150.0, EXPIRING)
    assert events == (GuardEvent.IGNORED,)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)
    _, _, events = step(state, 45.0, 30.0, 180.0, EXPIRING)
    assert events == ()


def test_outside_change_is_rewritten_once_then_blocked() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)  # confirmed
    state, action, events = step(state, 45.0, 60.0, 20.0, HELD)  # someone else wrote 60
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    assert events == ()
    state, _, _ = step(state, 45.0, 45.0, 30.0, HELD)  # our value is back
    state, action, events = step(state, 45.0, 60.0, 40.0, HELD)
    assert action is None
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


@pytest.mark.parametrize("config", [HELD, EXPIRING])
def test_a_rewrite_that_does_not_hold_is_an_outside_change(config) -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, config)
    state, _, _ = step(state, 45.0, 45.0, 10.0, config)  # confirmed
    state, action, _ = step(state, 45.0, 60.0, 20.0, config)  # another controller wrote 60
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    for t in (30.0, 60.0, 90.0, 120.0):  # it keeps its 60: no alarm before the timeout
        state, _, events = step(state, 45.0, 60.0, t, config)
        assert events == ()
    state, action, events = step(state, 45.0, 60.0, 150.0, config)
    assert action is None
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    _, action, events = step(state, 45.0, 60.0, 180.0, config)
    assert (action, events) == (None, ())  # blocked: no fight, no repeated alarm


def test_a_new_value_of_ours_is_not_an_outside_change() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, action, _ = step(state, 50.0, 45.0, 120.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state, action, events = step(state, 50.0, 45.0, 130.0, HELD)  # not confirmed yet
    assert action is None
    assert events == ()


def test_a_second_outside_change_within_a_day_blocks_even_after_our_change() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, _, _ = step(state, 45.0, 60.0, 20.0, HELD)  # rewrite used
    state, _, _ = step(state, 45.0, 45.0, 30.0, HELD)
    state, _, _ = step(state, 50.0, 45.0, 200.0, HELD)  # our new value
    state, _, _ = step(state, 50.0, 50.0, 210.0, HELD)
    state, action, events = step(state, 50.0, 60.0, 220.0, HELD)
    assert action is None  # a controller writing less often than we change is not fought
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_a_rewrite_is_allowed_again_a_day_later() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, _, _ = step(state, 45.0, 60.0, 20.0, HELD)  # rewrite used
    state, _, _ = step(state, 45.0, 45.0, 30.0, HELD)
    _, action, events = step(state, 45.0, 60.0, 20.0 + 86_400.0 + 1.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    assert events == ()


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
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    for t in (40.0, 100.0, 160.0):  # stale data: nothing desired, nothing written
        state, action, _ = step(state, None, 45.0 if t < 60 else 40.0, t, EXPIRING)
        assert action is None
    state, action, events = step(state, 45.0, 40.0, 200.0, EXPIRING)  # the override lapsed
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    assert state.rewritten_at is None  # the one rewrite is still there for a real outside change


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
    ],
)
def test_invalid_setpoint_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        GuardConfig(**kwargs)


SWITCH = GuardConfig(write_type=WriteType.HELD, read_back=False)  # a switch without an echo
ON, OFF = 1.0, 0.0


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
    for t in (130.0, 260.0, 400.0):
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


def test_heating_changed_from_outside_is_written_once_then_left() -> None:
    """With an echo, heating on/off falls under the one-rewrite rule too."""
    echoed = GuardConfig(write_type=WriteType.HELD, two_valued=True)
    state, action, _ = step(GuardState(), ON, OFF, 0.0, echoed)
    assert action == WriteAction(ON, WriteKind.CHANGE)
    state, _, _ = step(state, ON, ON, 10.0, echoed)  # confirmed
    state, action, _ = step(state, ON, OFF, 20.0, echoed)  # switched off from outside
    assert action == WriteAction(ON, WriteKind.REWRITE)
    state, _, _ = step(state, ON, ON, 30.0, echoed)
    state, action, events = step(state, ON, OFF, 40.0, echoed)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))
    assert confirmation(state, echoed) is Confirmation.CHANGED_FROM_OUTSIDE


def test_where_a_written_value_stands() -> None:
    state = GuardState()
    assert confirmation(state, HELD) is None
    state, _, _ = step(state, 45.0, None, 0.0, HELD)
    assert confirmation(state, HELD) is Confirmation.WAITING
    state, _, _ = step(state, 45.0, None, 130.0, HELD)
    assert confirmation(state, HELD) is Confirmation.NOT_CONFIRMED
    state, _, _ = step(state, 45.0, 45.0, 140.0, HELD)
    assert confirmation(state, HELD) is Confirmation.CONFIRMED


def test_the_one_rewrite_ends_in_an_outside_change_even_after_an_ignore() -> None:
    """P07: a value reported ignored once, confirmed later, then changed from outside — the one
    rewrite still ends in an outside change when it does not hold, and the writes stop."""
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, events = step(state, 45.0, None, 130.0, EXPIRING)
    assert events == (GuardEvent.IGNORED,)
    state, _, _ = step(state, 45.0, 45.0, 140.0, EXPIRING)  # confirmed after all
    state, action, _ = step(state, 45.0, 60.0, 150.0, EXPIRING)  # someone else wrote 60
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    state, action, events = step(state, 45.0, 60.0, 280.0, EXPIRING)
    assert action is None
    assert events == (GuardEvent.OUTSIDE_CHANGE,)
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE
    _, action, _ = step(state, 45.0, 60.0, 400.0, EXPIRING)
    assert action is None  # no keep-alive: no fight


def test_a_foreign_value_from_the_start_is_an_outside_change() -> None:
    """a1 (the user's decision): another controller holds its own value from the start of the
    session, so ours is never confirmed — one rewrite, then an outside change."""
    state, action, _ = step(GuardState(), 45.0, 60.0, 0.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.CHANGE)
    for t in (30.0, 60.0, 90.0, 120.0):
        state, _, events = step(state, 45.0, 60.0, t, EXPIRING)
        assert events == ()
    state, action, events = step(state, 45.0, 60.0, 130.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    state, action, events = step(state, 45.0, 60.0, 260.0, EXPIRING)
    assert (action, events) == (None, (GuardEvent.OUTSIDE_CHANGE,))
    assert state.blocked is GuardEvent.OUTSIDE_CHANGE


def test_an_unknown_read_back_is_only_ignored() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, EXPIRING)
    state, action, events = step(state, 45.0, None, 130.0, EXPIRING)
    assert events == (GuardEvent.IGNORED,)
    assert action is not None  # the keep-alive goes on: nothing says another controller
    assert state.blocked is None


def test_a_drop_to_the_value_without_our_override_is_sent_again_not_fought() -> None:
    """a2: the gateway drops our override (a boiler's Data-Invalid answer, a lapse): the
    read-back shows the value from before the session, not another controller's."""
    state, _, _ = step(GuardState(), 45.0, 40.0, 0.0, EXPIRING)  # 40: the thermostat
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    state, action, events = step(state, 45.0, 40.0, 20.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    assert state.rewritten_at is None  # the one rewrite is kept for a real outside change
    for t in (30.0, 40.0, 50.0, 60.0):  # it keeps dropping: the boiler does not take it
        state, _, _ = step(state, 45.0, 45.0, t, EXPIRING)
        state, action, events = step(state, 45.0, 40.0, t + 5.0, EXPIRING)
    assert GuardEvent.IGNORED in events or state.ignored_reported
    assert state.blocked is None


def test_our_previous_value_held_is_only_ignored() -> None:
    """A device still showing our last value has not taken the new one: ignored, not another
    controller."""
    state, _, _ = step(GuardState(), 45.0, 30.0, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, action, _ = step(state, 50.0, 45.0, 20.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state, action, events = step(state, 50.0, 45.0, 150.0, HELD)
    assert (action, events) == (None, (GuardEvent.IGNORED,))
    assert state.blocked is None


def test_a_moving_read_back_is_not_another_controller() -> None:
    state, _, _ = step(GuardState(), 45.0, 60.0, 0.0, HELD)
    state, _, _ = step(state, 45.0, 58.0, 60.0, HELD)  # it moved: nothing steady
    state, action, events = step(state, 45.0, 60.0, 130.0, HELD)
    assert (action, events) == (None, (GuardEvent.IGNORED,))


def test_an_ignored_report_ends_once_the_value_holds() -> None:
    state, _, _ = step(GuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, None, 130.0, HELD)
    assert state.ignored_reported
    state, _, _ = step(state, 45.0, 45.0, 140.0, HELD)
    assert state.ignored_reported  # confirmed, but not held yet
    state, _, _ = step(state, 45.0, 45.0, 260.0, HELD)
    assert not state.ignored_reported


def test_a_foreign_value_is_judged_even_across_a_step_without_data() -> None:
    state, _, _ = step(GuardState(), 45.0, 60.0, 0.0, EXPIRING)
    state, _, _ = step(state, None, 60.0, 130.0, EXPIRING)  # stale data: nothing desired
    _, action, _ = step(state, 45.0, 60.0, 140.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.REWRITE)


def test_a_drop_once_is_not_reported() -> None:
    state, _, _ = step(GuardState(), 45.0, 40.0, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)
    state, _, _ = step(state, 45.0, 40.0, 20.0, EXPIRING)  # dropped once
    for t in range(30, 400, 10):  # held, with its keep-alives
        state, _, _ = step(state, 45.0, 45.0, float(t), EXPIRING)
    state, action, events = step(state, 45.0, 40.0, 400.0, EXPIRING)  # much later: again once
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    assert state.dropped_at == 400.0
