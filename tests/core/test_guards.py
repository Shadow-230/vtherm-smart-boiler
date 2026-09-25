"""Write guards for the setpoint and for heating on/off."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    GuardEvent,
    SetpointGuardConfig,
    SetpointGuardState,
    SwitchGuardConfig,
    SwitchGuardState,
    WriteAction,
    WriteKind,
    WriteType,
    plan_setpoint,
    plan_switch,
    setpoint_failed,
    switch_failed,
)

EXPIRING = SetpointGuardConfig(write_type=WriteType.EXPIRING)
HELD = SetpointGuardConfig(write_type=WriteType.HELD)


def step(state, desired, confirmed, now, config):
    result = plan_setpoint(state, desired, confirmed, now, config)
    return result.state, result.action, result.events


def test_first_write_and_expiring_keepalive() -> None:
    state, action, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.CHANGE)
    state, action, _ = step(state, 45.0, 45.0, 20.0, EXPIRING)
    assert action is None
    state, action, _ = step(state, 45.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)


def test_held_writes_on_change_only() -> None:
    state, action, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
    assert action is not None
    state, action, _ = step(state, 45.0, 45.0, 600.0, HELD)
    assert action is None  # no keep-alive


@pytest.mark.parametrize("write_type", [WriteType.PERSISTENT, WriteType.UNKNOWN])
def test_nothing_goes_to_the_boilers_persistent_memory(write_type: WriteType) -> None:
    """A target that stores what it is given (or might) is never written, whatever is asked."""
    config = SetpointGuardConfig(write_type=write_type)
    state, action, events = step(SetpointGuardState(), 45.0, None, 0.0, config)
    assert (action, events) == (None, ())
    state = SetpointGuardState(written=45.0, written_at=0.0, sent_at=0.0, confirmed_at=5.0)
    for desired, confirmed in ((50.0, 45.0), (45.0, 60.0)):  # a change, an outside change
        _, action, _ = step(state, desired, confirmed, 600.0, config)
        assert action is None
    assert not config.writable


def test_a_new_value_waits_at_most_one_step() -> None:
    """The write-rate guard against a runaway loop: a write repeated within one control step
    waits for the next one — nothing longer."""
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, action, _ = step(state, 50.0, 45.0, 3.0, EXPIRING)
    assert action is None  # a step run early (control switched on) within the same step
    _, action, _ = step(state, 50.0, 45.0, 10.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)


def test_a_runaway_loop_gets_one_write_per_step() -> None:
    state = SetpointGuardState()
    written = 0
    for t in range(60):  # a new value every second
        state, action, _ = step(state, 45.0 + t, None, float(t), EXPIRING)
        written += action is not None
    assert written == 12  # one per five seconds: at most two in a ten-second step


def test_ignored_write_is_reported_once_and_writing_continues() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, events = step(state, 45.0, 30.0, 60.0, EXPIRING)
    assert events == ()
    state, action, events = step(state, 45.0, 30.0, 150.0, EXPIRING)
    assert events == (GuardEvent.IGNORED,)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)
    _, _, events = step(state, 45.0, 30.0, 180.0, EXPIRING)
    assert events == ()


def test_outside_change_is_rewritten_once_then_blocked() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
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
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, config)
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
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, action, _ = step(state, 50.0, 45.0, 120.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state, action, events = step(state, 50.0, 45.0, 130.0, HELD)  # not confirmed yet
    assert action is None
    assert events == ()


def test_a_second_outside_change_within_a_day_blocks_even_after_our_change() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
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
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, _, _ = step(state, 45.0, 60.0, 20.0, HELD)  # rewrite used
    state, _, _ = step(state, 45.0, 45.0, 30.0, HELD)
    _, action, events = step(state, 45.0, 60.0, 20.0 + 86_400.0 + 1.0, HELD)
    assert action == WriteAction(45.0, WriteKind.REWRITE)
    assert events == ()


def test_a_failed_write_is_sent_again_at_the_next_step() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state = setpoint_failed(state)
    state, action, events = step(state, 45.0, None, 10.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    _, action, _ = step(state, 45.0, None, 20.0, EXPIRING)
    assert action is None  # sent; nothing more until the next keep-alive or change


def test_failed_attempts_count_toward_the_write_rate() -> None:
    """A target that keeps rejecting the value is tried again once a step, not hammered."""
    state = SetpointGuardState()
    attempts = 0
    for t in range(0, 60, 2):
        state, action, _ = step(state, 45.0, None, float(t), EXPIRING)
        attempts += action is not None
        if action is not None:
            state = setpoint_failed(state)
    assert attempts == 10  # every third call: six seconds apart


def test_a_failed_write_followed_by_a_new_value_writes_the_new_value() -> None:
    """P82: the retry branch with a change — the new value goes, not the failed one."""
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)
    state, action, _ = step(state, 50.0, 45.0, 20.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state = setpoint_failed(state)
    state, action, events = step(state, 55.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(55.0, WriteKind.CHANGE)
    assert events == ()
    assert not state.retry


def test_a_failed_change_is_retried_not_taken_for_an_outside_change() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    state, action, _ = step(state, 50.0, 45.0, 120.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state = setpoint_failed(state)
    state, action, events = step(state, 50.0, 45.0, 130.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.RESEND)
    assert events == ()
    assert state.rewritten_at is None


def test_a_lapse_after_our_own_silence_is_resent_not_rewritten() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)  # confirmed
    for t in (40.0, 100.0, 160.0):  # stale data: nothing desired, nothing written
        state, action, _ = step(state, None, 45.0 if t < 60 else 40.0, t, EXPIRING)
        assert action is None
    state, action, events = step(state, 45.0, 40.0, 200.0, EXPIRING)  # the override lapsed
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    assert state.rewritten_at is None  # the one rewrite is still there for a real outside change


def test_nothing_desired_writes_nothing() -> None:
    _, action, _ = step(SetpointGuardState(), None, None, 0.0, EXPIRING)
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
        SetpointGuardConfig(**kwargs)


def test_the_switch_follows_every_change_at_once() -> None:
    """Nothing counted or timed holds heating on or off against VT."""
    state = SwitchGuardState()
    writes = []
    for t, desired in enumerate([True, False, True, False, True]):
        result = plan_switch(state, desired, t * 10.0, SwitchGuardConfig())
        state = result.state
        writes.append(result.write)
    assert writes == [True, False, True, False, True]
    assert plan_switch(state, True, 50.0, SwitchGuardConfig()).write is None  # unchanged


def test_switch_keepalive_for_expiring_overrides() -> None:
    config = SwitchGuardConfig(keepalive_s=30.0)
    first = plan_switch(SwitchGuardState(), True, 0.0, config)
    assert plan_switch(first.state, True, 10.0, config).write is None
    assert plan_switch(first.state, True, 30.0, config).write is True
    assert plan_switch(SwitchGuardState(), None, 0.0, config).write is None


def test_the_switch_waits_at_most_one_step() -> None:
    """The same write-rate guard: a change within one step of the last write waits for the next
    step — no longer."""
    first = plan_switch(SwitchGuardState(), True, 0.0, SwitchGuardConfig())
    early = plan_switch(first.state, False, 3.0, SwitchGuardConfig())
    assert early.write is None
    assert plan_switch(early.state, False, 10.0, SwitchGuardConfig()).write is False


@pytest.mark.parametrize("kwargs", [{"min_interval_s": 0.0}, {"keepalive_s": 5.0}])
def test_invalid_switch_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        SwitchGuardConfig(**kwargs)


def test_a_failed_switch_is_sent_again() -> None:
    first = plan_switch(SwitchGuardState(), True, 0.0, SwitchGuardConfig())
    retried = plan_switch(switch_failed(first.state), True, 10.0, SwitchGuardConfig())
    assert retried.write is True
    assert plan_switch(retried.state, True, 20.0, SwitchGuardConfig()).write is None


def test_the_one_rewrite_ends_in_an_outside_change_even_after_an_ignore() -> None:
    """P07: a value reported ignored once, confirmed later, then changed from outside — the one
    rewrite still ends in an outside change when it does not hold, and the writes stop."""
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
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
    state, action, _ = step(SetpointGuardState(), 45.0, 60.0, 0.0, EXPIRING)
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
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, action, events = step(state, 45.0, None, 130.0, EXPIRING)
    assert events == (GuardEvent.IGNORED,)
    assert action is not None  # the keep-alive goes on: nothing says another controller
    assert state.blocked is None


def test_a_drop_to_the_value_without_our_override_is_sent_again_not_fought() -> None:
    """a2: the gateway drops our override (a boiler's Data-Invalid answer, a lapse): the
    read-back shows the value from before the session, not another controller's."""
    state, _, _ = step(SetpointGuardState(), 45.0, 40.0, 0.0, EXPIRING)  # 40: the thermostat
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
    state, _, _ = step(SetpointGuardState(), 45.0, 30.0, 0.0, HELD)
    state, _, _ = step(state, 45.0, 45.0, 10.0, HELD)
    state, action, _ = step(state, 50.0, 45.0, 20.0, HELD)
    assert action == WriteAction(50.0, WriteKind.CHANGE)
    state, action, events = step(state, 50.0, 45.0, 150.0, HELD)
    assert (action, events) == (None, (GuardEvent.IGNORED,))
    assert state.blocked is None


def test_a_moving_read_back_is_not_another_controller() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, 60.0, 0.0, HELD)
    state, _, _ = step(state, 45.0, 58.0, 60.0, HELD)  # it moved: nothing steady
    state, action, events = step(state, 45.0, 60.0, 130.0, HELD)
    assert (action, events) == (None, (GuardEvent.IGNORED,))


def test_an_ignored_report_ends_once_the_value_holds() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, HELD)
    state, _, _ = step(state, 45.0, None, 130.0, HELD)
    assert state.ignored_reported
    state, _, _ = step(state, 45.0, 45.0, 140.0, HELD)
    assert state.ignored_reported  # confirmed, but not held yet
    state, _, _ = step(state, 45.0, 45.0, 260.0, HELD)
    assert not state.ignored_reported


def test_a_foreign_value_is_judged_even_across_a_step_without_data() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, 60.0, 0.0, EXPIRING)
    state, _, _ = step(state, None, 60.0, 130.0, EXPIRING)  # stale data: nothing desired
    _, action, _ = step(state, 45.0, 60.0, 140.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.REWRITE)


def test_a_drop_once_is_not_reported() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, 40.0, 0.0, EXPIRING)
    state, _, _ = step(state, 45.0, 45.0, 10.0, EXPIRING)
    state, _, _ = step(state, 45.0, 40.0, 20.0, EXPIRING)  # dropped once
    for t in range(30, 400, 10):  # held, with its keep-alives
        state, _, _ = step(state, 45.0, 45.0, float(t), EXPIRING)
    state, action, events = step(state, 45.0, 40.0, 400.0, EXPIRING)  # much later: again once
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    assert state.dropped_at == 400.0
