"""Write guards for the setpoint and for heating on/off."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.guards import (
    GuardEvent,
    SetpointGuardConfig,
    SetpointGuardState,
    SwitchGuardConfig,
    SwitchGuardState,
    SwitchHold,
    WriteAction,
    WriteKind,
    WriteType,
    plan_setpoint,
    plan_switch,
    setpoint_failed,
    switch_failed,
)

EXPIRING = SetpointGuardConfig(write_type=WriteType.EXPIRING)
PERSISTENT = SetpointGuardConfig(write_type=WriteType.PERSISTENT, daily_cap=3)
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


def test_held_and_persistent_write_on_change_only() -> None:
    for config in (HELD, PERSISTENT):
        state, action, _ = step(SetpointGuardState(), 45.0, None, 0.0, config)
        assert action is not None
        state, action, _ = step(state, 45.0, 45.0, 600.0, config)
        assert action is None  # no keep-alive


def test_persistent_minimum_change_and_daily_cap() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, PERSISTENT)
    state, action, _ = step(state, 45.6, 45.0, 120.0, PERSISTENT)
    assert action is None  # below the 1 K minimum change
    state, action, _ = step(state, 47.0, 45.0, 240.0, PERSISTENT)
    assert action == WriteAction(47.0, WriteKind.CHANGE)
    state, action, _ = step(state, 49.0, 47.0, 360.0, PERSISTENT)
    assert action is not None
    state, action, events = step(state, 51.0, 49.0, 480.0, PERSISTENT)
    assert action is None
    assert events == (GuardEvent.DAILY_CAP,)
    assert state.blocked is GuardEvent.DAILY_CAP
    _, action, events = step(state, 40.0, 49.0, 600.0, PERSISTENT)
    assert action is None
    assert events == ()  # reported once


def test_daily_cap_counts_one_day() -> None:
    state = SetpointGuardState(
        written=45.0, written_at=0.0, changed_at=0.0, history=(0.0, 1.0, 2.0)
    )
    _, action, _ = step(state, 50.0, 45.0, 86_400.0 + 3.0, PERSISTENT)
    assert action is not None


def test_minimum_change_interval() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state, action, _ = step(state, 50.0, 45.0, 30.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.KEEPALIVE)  # the change waits, the old value lives
    _, action, _ = step(state, 50.0, 45.0, 60.0, EXPIRING)
    assert action == WriteAction(50.0, WriteKind.CHANGE)


def test_writes_per_minute_are_capped() -> None:
    config = SetpointGuardConfig(
        write_type=WriteType.EXPIRING,
        keepalive_s=1.0,
        min_change_interval_s=0.0,
        max_writes_per_minute=3,
    )
    state = SetpointGuardState()
    written = 0
    for t in range(10):
        state, action, _ = step(state, 45.0 + t, None, float(t), config)
        written += action is not None
    assert written == 3


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


def test_the_daily_cap_applies_to_the_first_write_of_a_session() -> None:
    state = SetpointGuardState(history=(0.0, 1.0, 2.0))  # three wearing writes today
    state, action, events = step(state, 45.0, None, 10.0, PERSISTENT)
    assert action is None
    assert events == (GuardEvent.DAILY_CAP,)
    assert state.blocked is GuardEvent.DAILY_CAP


def test_the_daily_cap_applies_to_rewrites() -> None:
    state, _, _ = step(SetpointGuardState(history=(0.0, 1.0)), 45.0, None, 10.0, PERSISTENT)
    state, _, _ = step(state, 45.0, 45.0, 20.0, PERSISTENT)  # confirmed; three writes today
    state, action, events = step(state, 45.0, 60.0, 30.0, PERSISTENT)
    assert action is None
    assert events == (GuardEvent.DAILY_CAP,)


def test_a_failed_write_is_sent_again_at_the_next_step() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, EXPIRING)
    state = setpoint_failed(state)
    state, action, events = step(state, 45.0, None, 10.0, EXPIRING)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert events == ()
    _, action, _ = step(state, 45.0, None, 20.0, EXPIRING)
    assert action is None  # sent; nothing more until the next keep-alive or change


def test_a_failed_wearing_write_is_retried_once_a_minute_and_not_counted() -> None:
    state, _, _ = step(SetpointGuardState(), 45.0, None, 0.0, PERSISTENT)
    for t in (10.0, 20.0, 30.0):
        state = setpoint_failed(state)
        state, action, _ = step(state, 45.0, None, t, PERSISTENT)
        assert action is None  # a rejected wearing write is not hammered
    state, action, _ = step(state, 45.0, None, 60.0, PERSISTENT)
    assert action == WriteAction(45.0, WriteKind.RESEND)
    assert state.history == (60.0,)  # the failed attempts do not count toward the cap


def test_failed_attempts_never_use_up_the_daily_cap() -> None:
    state = SetpointGuardState()
    for minute in range(10):  # the entity keeps rejecting the value
        state, action, events = step(state, 45.0, None, minute * 60.0, PERSISTENT)
        assert action is not None
        assert events == ()
        state = setpoint_failed(state)
    assert state.history == ()


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
    [{"keepalive_s": 0.0}, {"max_writes_per_minute": 1}, {"daily_cap": 0}, {"min_change": -1.0}],
)
def test_invalid_setpoint_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        SetpointGuardConfig(**kwargs)


SWITCH = SwitchGuardConfig(min_on_s=300.0, min_off_s=300.0, max_switches_per_hour=3)


def test_switch_minimum_on_and_off_times() -> None:
    result = plan_switch(SwitchGuardState(), True, 0.0, SWITCH)
    assert result.write is True
    held = plan_switch(result.state, False, 100.0, SWITCH)
    assert held.write is None
    assert held.hold is SwitchHold.MIN_ON
    off = plan_switch(held.state, False, 300.0, SWITCH)
    assert off.write is False
    again = plan_switch(off.state, True, 400.0, SWITCH)
    assert again.hold is SwitchHold.MIN_OFF


def test_switch_budget_per_hour() -> None:
    state = SwitchGuardState()
    writes = 0
    for i in range(6):
        result = plan_switch(state, i % 2 == 0, i * 400.0, SWITCH)
        state = result.state
        writes += result.write is not None
    assert writes == 4  # the first write and three switches
    assert plan_switch(state, True, 2400.0, SWITCH).hold is SwitchHold.SWITCH_BUDGET


def test_switch_keepalive_for_expiring_overrides() -> None:
    config = SwitchGuardConfig(keepalive_s=30.0)
    first = plan_switch(SwitchGuardState(), True, 0.0, config)
    assert plan_switch(first.state, True, 10.0, config).write is None
    assert plan_switch(first.state, True, 30.0, config).write is True
    assert plan_switch(SwitchGuardState(), None, 0.0, config).write is None


def test_a_failed_switch_is_sent_again() -> None:
    first = plan_switch(SwitchGuardState(), True, 0.0, SWITCH)
    retried = plan_switch(switch_failed(first.state), True, 10.0, SWITCH)
    assert retried.write is True
    assert retried.state.switches == first.state.switches  # not a new switching
    assert plan_switch(retried.state, True, 20.0, SWITCH).write is None


def test_invalid_switch_config() -> None:
    with pytest.raises(ValueError, match="must"):
        SwitchGuardConfig(max_switches_per_hour=0)
