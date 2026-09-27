"""The control step: controller through the write guards."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.controller import ControlConfig, ControlInputs
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.guards import (
    DAY,
    GuardConfig,
    GuardContext,
    GuardEvent,
    GuardState,
    WriteAction,
    WriteKind,
    WriteType,
)
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits, Grid
from custom_components.vtherm_smart_boiler.core.loop import (
    HEATING_OFF_IGNORED,
    LastCommand,
    LoopConfig,
    LoopState,
    loop_step,
    new_session,
    parse_last_command,
    remember_command,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

CONFIG = LoopConfig(
    control=ControlConfig(curve=HeatingCurve(), ramp_k_per_min=None),
    setpoint_guard=GuardConfig(write_type=WriteType.EXPIRING),
)


EXPIRING_SWITCH = GuardConfig(write_type=WriteType.EXPIRING, read_back=False, two_valued=True)
ECHOED_SWITCH = GuardConfig(write_type=WriteType.HELD, two_valued=True)


def inputs(t: float, opening: float = 0.6, **kw) -> ControlInputs:
    kw.setdefault("enabled", True)
    kw.setdefault("zones", (ZoneState("z", 20.0, 21.0, True, reported_at=t, valve_open=opening),))
    kw.setdefault("outdoor_sensor", 5.0)
    return ControlInputs(now=t, flame=False, dhw=False, **kw)


def test_first_step_writes_setpoint_and_heating_on() -> None:
    _state, out = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.CHANGE
    assert out.ch_enable is True
    assert out.heating_on is True


def test_keepalive_follows_between_decisions() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    state, out = loop_step(state, inputs(30.0), 45.0, CONFIG)
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.KEEPALIVE
    assert out.ch_enable is None  # unchanged, no keep-alive configured for the switch


def run(
    state: LoopState,
    config: LoopConfig,
    start: float,
    end: float,
    setpoint: float | None,
    heating: bool | None = None,
    **kw,
) -> tuple[LoopState, list]:
    """Steps every 10 s from ``start`` to ``end`` (included), the read-backs given."""
    outs = []
    t = start
    while t <= end:
        state, out = loop_step(state, inputs(t, **kw), setpoint, config, heating)
        outs.append((t, out))
        t += 10.0
    return state, outs


def test_the_guards_keep_their_memory_across_a_hand_back_in_a_session() -> None:
    """T-01 (P-06; replaces 0.2.1's "the hand-back resets the guards"): rewritten once; a
    stale-link hand-back, control resuming, and another outside change the same day — no second
    rewrite: the guard blocks and reports."""
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, CONFIG)  # 0 before the plugin
    value = out.setpoint.value
    state, _ = run(state, CONFIG, 10.0, 150.0, value)
    state, _ = loop_step(state, inputs(160.0), 60.0, CONFIG)
    state, out = loop_step(state, inputs(170.0), 60.0, CONFIG)  # another controller: 60
    assert out.setpoint == WriteAction(value, WriteKind.REWRITE)
    state, _ = run(state, CONFIG, 180.0, 180.0, value)
    state, outs = run(state, CONFIG, 190.0, 500.0, None, boiler_link=False)  # stale
    assert [t for t, out in outs if out.hand_back] == [490.0]
    assert state.setpoint.rewritten_at == 170.0  # kept across the hand-back
    assert state.setpoint.baseline == 0.0
    state, outs = run(state, CONFIG, 510.0, 690.0, value)  # control resumes
    assert outs[0][1].setpoint == WriteAction(value, WriteKind.CHANGE)
    state, out = loop_step(state, inputs(700.0), 60.0, CONFIG)
    state, out = loop_step(state, inputs(710.0), 60.0, CONFIG)  # again, the same day
    assert out.setpoint is None
    assert out.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert out.blocked


@pytest.mark.parametrize(
    "kw", [{"enabled": False}, {"hand_back_alarms": ("pressure_low",)}], ids=["off", "alarm"]
)
def test_a_hand_back_passes_while_a_guard_is_blocked(kw: dict) -> None:
    """T-19: the setpoint guard blocked (another controller): a step switched off, or with an
    alarm set to hand back, still hands back and writes no setpoint. The block, the baseline and
    the one rewrite stay; what was sent goes."""
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, CONFIG)
    blocked = replace(state.setpoint, blocked=GuardEvent.OUTSIDE_CHANGE, rewritten_at=0.0)
    state = replace(state, setpoint=blocked)
    state, out = loop_step(state, inputs(30.0, **kw), 60.0, CONFIG)
    assert out.hand_back
    assert out.setpoint is None
    assert state.setpoint.blocked is GuardEvent.OUTSIDE_CHANGE
    assert state.setpoint.baseline == 0.0
    assert state.setpoint.rewritten_at == 0.0
    assert (state.setpoint.written, state.setpoint.sent_at, state.setpoint.confirmed_at) == (
        None,
        None,
        None,
    )
    assert state.switch.written is None


def test_a_new_session_keeps_only_the_one_rewrite() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), 0.0, CONFIG)
    state = replace(state, setpoint=replace(state.setpoint, rewritten_at=0.0, ignored=True))
    fresh = new_session(state, 100.0)
    assert fresh.setpoint == GuardState(rewritten_at=0.0)
    assert fresh.switch == GuardState()
    assert new_session(state, DAY).setpoint == GuardState()


def test_ignored_from_the_start_keeps_the_other_target_and_frost() -> None:
    """Decision 6: the setpoint ignored from the start — the heating switch is still written, and
    frost heating still switches it on; no block, no latch; the setpoint is not written again this
    session. A new session tries it again."""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config)  # 0 before the plugin
    state, outs = run(state, config, 10.0, 360.0, 0.0)  # never taken
    events = [e for _t, out in outs for e in out.events]
    assert events == [GuardEvent.IGNORED]
    assert outs[-1][1].ignored == ("setpoint",)
    state, outs = run(state, config, 370.0, 400.0, 0.0, opening=0.0)
    assert outs[0][1].ch_enable is False  # heating off goes
    assert all(out.setpoint is None for _t, out in outs)
    cold = ZoneState("z", 4.0, 21.0, True, reported_at=410.0, valve_open=0.0)
    state, out = loop_step(state, inputs(410.0, zones=(cold,)), 0.0, config)
    assert out.decision.mode.value == "frost"
    assert out.ch_enable is True  # frost heating switches it on
    assert out.setpoint is None
    assert not out.blocked
    assert not state.control.latched
    fresh = replace(new_session(state, 420.0), control=state.control)
    _state, out = loop_step(fresh, inputs(420.0), 0.0, config)
    assert out.setpoint is not None  # tried again


def test_a_gateway_reset_loses_both_overrides_as_one_lost_command() -> None:
    """M1: the setpoint and heating on/off back at their values from before the plugin in the
    same step, with no other trace: both sent again at once, one loss for the warning, each
    guard's first fall-back without a trace, no event."""
    echoed = GuardConfig(write_type=WriteType.EXPIRING, two_valued=True)
    config = replace(CONFIG, switch_guard=echoed)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config, False)
    value = out.setpoint.value
    state, _ = run(state, config, 10.0, 400.0, value, True)
    state, out = loop_step(state, inputs(410.0), 0.0, config, False)
    assert out.setpoint == WriteAction(value, WriteKind.RESEND)
    assert out.heating == WriteAction(1.0, WriteKind.RESEND)
    assert out.events == ()
    assert len(state.losses) == 1
    assert state.setpoint.fallbacks == (410.0,)
    assert state.switch.fallbacks == (410.0,)


@pytest.mark.parametrize("only_on", [False, True], ids=["off_ignored", "on_ignored"])
def test_heating_off_ignored_from_the_start_hands_back_at_the_next_step(only_on: bool) -> None:
    """Answer O: the heating switch's "off" ignored from the start — control is latched with
    ``heating_off_ignored`` and handed back at the next step, whatever alarm reaction is stored.
    Negative: only "on" ignored (the switch stays off) — reported, no hand-back, the setpoint
    still written."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    opening = 0.6 if only_on else 0.0  # demand asks "on", no demand "off"
    echo = not only_on  # the switch stays where it was before the plugin
    state, out = loop_step(LoopState(), inputs(0.0, opening=opening), 0.0, config, echo)
    value = out.setpoint.value
    state, outs = run(state, config, 10.0, 360.0, value, echo, opening=opening)
    assert outs[-1][1].ignored == ("heating",)
    state, out = loop_step(state, inputs(370.0, opening=opening), value, config, echo)
    if only_on:
        assert not out.hand_back
        assert not state.control.latched
        state, outs = run(state, config, 380.0, 420.0, value, echo, opening=opening)
        assert any(out.setpoint is not None for _t, out in outs)  # the setpoint's keep-alives
    else:
        assert out.hand_back
        assert state.control.latched
        assert state.control.latched_by == (HEATING_OFF_IGNORED,)


def test_the_setpoint_is_put_on_the_entitys_grid_inside_the_limits() -> None:
    """P-98, T-55: the hard maximum 70 on an entity's grid of 0.5 from 0.25 is sent as 69.75 —
    never above it — and read back as 69.75 it confirms. A °F entity gets its own grid."""
    control = ControlConfig(
        curve=HeatingCurve(design_flow=75.0),
        ramp_k_per_min=None,
        limits=FlowLimits(hard_min=25.0, hard_max=70.0),
    )
    config = replace(CONFIG, control=control)
    grid = Grid(step=0.5, minimum=0.25, maximum=90.0)
    cold = {"outdoor_sensor": -30.0}
    state, out = loop_step(LoopState(), replace(inputs(0.0), **cold), 0.0, config, grid=grid)
    assert out.setpoint == WriteAction(69.75, WriteKind.CHANGE)
    state, out = loop_step(state, replace(inputs(10.0), **cold), 69.75, config, grid=grid)
    assert state.setpoint.confirmed_at == 10.0
    fahrenheit = Grid(step=1.0, minimum=50.0, maximum=190.0, scale=1.8, offset=32.0)
    _state, out = loop_step(LoopState(), inputs(0.0), 0.0, CONFIG, grid=fahrenheit)
    sent = out.setpoint.value
    assert abs(sent * 1.8 + 32.0 - round(sent * 1.8 + 32.0)) < 1e-6  # a whole °F


def test_a_clip_is_never_learned_as_a_limit() -> None:
    """While the boiler holds the water lower than asked (clipped), the comfort correction does
    not rise and no limit changes (principle 13). Negative: without the clip it rises."""
    control = ControlConfig(curve=HeatingCurve(), ramp_k_per_min=None, decision_interval_s=60.0)
    config = replace(CONFIG, control=control)

    def short_zone(t: float) -> ZoneState:
        return ZoneState("z", 19.0, 21.0, True, reported_at=t, valve_open=1.0)

    for clip, rises in ((40.0, False), (None, True)):
        state = LoopState(setpoint=GuardState(clip=clip))
        t = 0.0
        while t <= 7200.0:
            state, _ = loop_step(state, inputs(t, zones=(short_zone(t),)), None, config)
            t += 10.0
        assert (state.control.correction > 0.0) is rises
        assert config.control.limits == FlowLimits()


def test_frequent_losses_raise_a_warning_while_writing_goes_on() -> None:
    """Three lost commands within a day raise "commands lost" — information: writing goes on;
    it clears after a day without a loss."""
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, CONFIG)
    value = out.setpoint.value
    state, _ = run(state, CONFIG, 10.0, 150.0, value)
    t = 160.0
    for _ in range(3):
        state, _ = run(state, CONFIG, t, t + 600.0, value)
        t += 610.0
        context = GuardContext(outage_at=t - 60.0)
        state, out = loop_step(state, inputs(t), 0.0, CONFIG, setpoint_context=context)
        assert out.setpoint == WriteAction(value, WriteKind.RESEND)
        t += 10.0
    assert out.commands_lost
    state, outs = run(state, CONFIG, t, t + 100.0, value)
    assert all(o.commands_lost for _t, o in outs)
    assert any(o.setpoint is not None for _t, o in outs)  # writing goes on
    state, out = loop_step(state, inputs(t + DAY), value, CONFIG)
    assert not out.commands_lost


def test_without_a_switch_off_is_a_low_setpoint() -> None:
    config = replace(CONFIG, ch_writes=False, off_setpoint=12.0)
    _state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), None, config)
    assert out.ch_enable is None
    assert out.setpoint is not None
    assert out.setpoint.value == 12.0
    assert out.heating_on is False


def test_nothing_is_written_while_waiting_for_data() -> None:
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    _state, out = loop_step(state, inputs(30.0, boiler_link=False), None, CONFIG)
    assert out.setpoint is None
    assert out.ch_enable is None
    assert not out.hand_back


def test_an_expiring_heating_override_is_repeated() -> None:
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    assert out.ch_enable is True
    _state, out = loop_step(state, inputs(30.0), 45.0, config)
    assert out.ch_enable is True  # repeated with the setpoint's keep-alive


def test_heating_on_off_follows_a_recovered_setpoint_at_once() -> None:
    """After a lapse the gateway's heating override is gone with it: the recovery write carries
    the heating state too, not only the next keep-alive. (The drop comes in the start phase: a
    failed attempt, sent again — decision 6.)"""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    state, _ = loop_step(state, inputs(10.0), out.setpoint.value, config)  # confirmed
    state, out = loop_step(state, inputs(20.0), 30.0, config)  # the gateway dropped it
    assert out.setpoint is not None
    assert out.setpoint.kind is WriteKind.RESEND
    assert out.ch_enable is True


def test_a_blocked_setpoint_stops_the_heating_writes_too() -> None:
    """P53: another controller has the boiler: every write stops, heating on/off included,
    whatever the alarm's reaction."""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    blocked = replace(state.setpoint, blocked=GuardEvent.OUTSIDE_CHANGE)
    state = replace(state, setpoint=blocked)
    _state, out = loop_step(state, inputs(30.0, opening=0.0), 60.0, config)
    assert out.setpoint is None
    assert out.ch_enable is None
    assert out.blocked


def test_heating_is_confirmed_by_its_echo() -> None:
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config, False)
    assert out.ch_enable is True
    state, out = loop_step(state, inputs(10.0), out.setpoint.value, config, True)
    assert state.switch.confirmed_at == 10.0


def test_heating_switched_from_outside_stops_every_write() -> None:
    """P22, row 13: with an echo, heating on/off falls under decision 6's classes — switched away
    from its value from before the plugin for two steps, written again once; the next time, the
    setpoint writes stop too."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config, True)  # "on" before
    setpoint = out.setpoint.value
    state, _ = run(state, config, 10.0, 390.0, setpoint, True)  # confirmed, past the start
    state, out = loop_step(state, inputs(400.0), setpoint, config, False)  # switched off outside
    assert out.heating is None or out.heating.kind is WriteKind.KEEPALIVE  # one step: nothing
    state, out = loop_step(state, inputs(410.0), setpoint, config, False)
    assert out.heating is not None
    assert out.heating.kind is WriteKind.REWRITE
    state, _ = loop_step(state, inputs(420.0), setpoint, config, True)
    state, _ = loop_step(state, inputs(500.0), setpoint, config, False)
    state, out = loop_step(state, inputs(510.0), setpoint, config, False)  # again
    assert out.blocked
    assert out.events == (GuardEvent.OUTSIDE_CHANGE,)
    _state, out = loop_step(state, inputs(540.0), setpoint, config, False)
    assert (out.setpoint, out.heating, out.blocked) == (None, None, True)  # no keep-alive either


def test_a_blocked_setpoint_leaves_this_steps_heating_write_unmade() -> None:
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config)
    setpoint = out.setpoint.value
    state, _ = loop_step(state, inputs(10.0), setpoint, config)  # confirmed
    state, _ = loop_step(state, inputs(20.0), 60.0, config)
    state, _ = loop_step(state, inputs(30.0), 60.0, config)  # the one rewrite
    state, _ = loop_step(state, inputs(40.0), setpoint, config)
    state, _ = loop_step(state, inputs(50.0), 60.0, config)
    before = state.switch
    state, out = loop_step(state, inputs(60.0, opening=0.0), 60.0, config)  # heating off asked
    assert out.blocked
    assert out.heating is None
    assert state.switch == before  # not recorded as written


# --- the last command (V3) ------------------------------------------------------------------


def test_the_first_command_is_saved_at_once() -> None:
    command, save_now = remember_command(None, True, 45.0, 10.0)
    assert command == LastCommand(True, 45.0, 10.0)
    assert save_now


def test_a_change_of_heating_is_saved_at_once() -> None:
    _, save_now = remember_command(LastCommand(True, 45.0, 0.0), False, 45.0, 10.0)
    assert save_now


def test_a_setpoint_change_of_a_kelvin_or_more_is_saved_at_once() -> None:
    before = LastCommand(True, 45.0, 0.0)
    assert remember_command(before, True, 46.0, 10.0)[1]
    assert remember_command(before, True, 44.0, 10.0)[1]
    assert remember_command(before, True, None, 10.0)[1]
    assert remember_command(LastCommand(True, None, 0.0), True, 45.0, 10.0)[1]


def test_a_small_setpoint_step_waits_for_the_next_save() -> None:
    command, save_now = remember_command(LastCommand(True, 45.0, 0.0), True, 45.5, 10.0)
    assert command == LastCommand(True, 45.5, 10.0)  # kept in memory, written with the next save
    assert not save_now


def test_a_last_command_round_trips() -> None:
    command = LastCommand(False, None, 12.5)
    assert parse_last_command(command.as_dict()) == command
    assert parse_last_command({"heating": True, "setpoint": 40, "at": 3}) == LastCommand(
        True, 40.0, 3.0
    )


@pytest.mark.parametrize(
    "raw",
    [
        "garbage",
        [],
        {},
        {"heating": "yes", "setpoint": 40.0, "at": 0.0},
        {"heating": 1, "setpoint": 40.0, "at": 0.0},
        {"heating": True, "setpoint": "40", "at": 0.0},
        {"heating": True, "setpoint": True, "at": 0.0},
        {"heating": True, "setpoint": float("nan"), "at": 0.0},
        {"heating": True, "setpoint": 40.0},
        {"heating": True, "setpoint": 40.0, "at": None},
        {"heating": True, "setpoint": 40.0, "at": float("inf")},
    ],
)
def test_an_unreadable_last_command_is_refused(raw: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        parse_last_command(raw)


def test_small_steps_are_stored_at_once_as_they_add_up() -> None:
    stored = LastCommand(True, 45.0, 0.0)
    assert not remember_command(stored, True, 45.5, 10.0)[1]
    assert remember_command(stored, True, 46.0, 20.0)[1]  # a kelvin from the one stored
