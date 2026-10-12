"""The control step: controller through the write guards."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.comfort_rules import StartsBaseline
from custom_components.vtherm_smart_boiler.core.controller import (
    ControlConfig,
    ControlInputs,
    ControlState,
)
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
    add_loss,
)
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits, Grid
from custom_components.vtherm_smart_boiler.core.loop import (
    HEATING_OFF_IGNORED,
    HEATING_ON_IGNORED,
    RELAY,
    RELAY_OFF_NOT_TAKEN,
    SETPOINT,
    LastCommand,
    LoopConfig,
    LoopState,
    loop_step,
    new_session,
    parse_last_command,
    remember_command,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.relay import (
    RelayConfig,
    RelayPowerOn,
    RelayReports,
    RelaySeen,
    RelayState,
    RelayTimer,
    RelayWrite,
)
from custom_components.vtherm_smart_boiler.core.zone_watch import graced, in_recognition

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
    kw.setdefault("flame", False)
    return ControlInputs(now=t, dhw=False, **kw)


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
    state, outs = run(state, CONFIG, 510.0, 690.0, value)  # control resumes after a minute
    written = [(t, out.setpoint) for t, out in outs if out.setpoint is not None]
    assert written[0] == (570.0, WriteAction(value, WriteKind.CHANGE))
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


def test_a_new_session_keeps_the_comfort_corrections_weather_and_starts() -> None:
    """Decision 11 of 0.2.3: the outdoor readings (rule 5) and the starts baseline (rule 3)
    are kept through a new session; the correction itself starts afresh."""
    baseline = StartsBaseline(100.0, (50.0,), zero_since=200.0)
    control = ControlState(
        correction=2.0, starts_baseline=baseline, outdoor_seen=((0.0, 5.0), (300.0, 5.0))
    )
    fresh = new_session(LoopState(control=control), 400.0).control
    assert fresh.starts_baseline == baseline
    assert fresh.outdoor_seen == control.outdoor_seen
    assert fresh.correction == 0.0


def test_a_new_session_keeps_the_boiler_link_window() -> None:
    """X2: the link's samples are a fact about the link, not the session — switching control
    off and on while the link is lost does not make it fresh: still lost, nothing written,
    until it has been fresh for a minute. Everything else of the session starts afresh."""
    state, _ = run(LoopState(), CONFIG, 0.0, 0.0, None)
    state, outs = run(state, CONFIG, 10.0, 310.0, None, boiler_link=False)
    assert outs[-1][1].hand_back  # lost at 310 s
    fresh = new_session(state, 320.0)
    assert fresh.control.link == state.control.link
    assert fresh.control.link.lost
    assert not fresh.control.controlling
    assert fresh.control.mode.value == "disabled"
    fresh, outs = run(fresh, CONFIG, 320.0, 370.0, None)  # fresh again, not yet a minute
    assert all(out.decision.link_lost and out.setpoint is None for _t, out in outs)
    fresh, outs = run(fresh, CONFIG, 380.0, 380.0, None)
    assert not outs[0][1].decision.link_lost
    assert outs[0][1].setpoint is not None


def test_a_new_session_keeps_the_zone_watch() -> None:
    """Decision 3: the recognition period and each zone's grace are facts about the zones, not
    the session — switching control off and on neither starts the recognition period again nor
    drops the last answer of a zone in its grace (a dead zone would otherwise hold every new
    decision back for up to ten minutes after control is switched on)."""
    two = (
        ZoneState("a", 20.0, 21.0, True, reported_at=0.0, valve_open=0.6),
        ZoneState("b", 20.0, 21.0, True, reported_at=0.0, valve_open=0.6),
    )
    state, _ = loop_step(LoopState(), inputs(0.0, zones=two), None, CONFIG)
    assert not in_recognition(state.control.zones)  # both reported at the first step
    b_gone = (
        ZoneState("a", 20.0, 21.0, True, reported_at=10.0, valve_open=0.6),
        ZoneState("b"),  # unavailable: its mode is not known
    )
    state, _ = loop_step(state, inputs(10.0, zones=b_gone), None, CONFIG)
    assert set(graced(state.control.zones)) == {"b"}  # b keeps its last answer
    fresh = new_session(state, 20.0)
    assert fresh.control.zones == state.control.zones
    assert not in_recognition(fresh.control.zones)
    assert set(graced(fresh.control.zones)) == {"b"}
    fresh, out = loop_step(fresh, inputs(20.0, zones=b_gone), None, CONFIG)
    assert out.setpoint is not None  # a decision at once, no new recognition period


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
    # Its valve a little open: frost heat can reach it (decision 4), and it does not call.
    cold = ZoneState("z", 4.0, 21.0, True, reported_at=410.0, valve_open=0.04)
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
    Decision 4 of 0.2.3 (SB-03): only "on" ignored (the switch, or its read-back, stays off) —
    latched with ``heating_on_ignored`` and handed back alike; before, control went on with the
    switch never written again, so VT's later "off" was never written either. Nothing more is
    written while the latch holds."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    opening = 0.6 if only_on else 0.0  # demand asks "on", no demand "off"
    echo = not only_on  # the switch stays where it was before the plugin
    state, out = loop_step(LoopState(), inputs(0.0, opening=opening), 0.0, config, echo)
    value = out.setpoint.value
    state, outs = run(state, config, 10.0, 360.0, value, echo, opening=opening)
    assert outs[-1][1].ignored == ("heating",)
    state, out = loop_step(state, inputs(370.0, opening=opening), value, config, echo)
    assert out.hand_back
    assert state.control.latched
    cause = HEATING_ON_IGNORED if only_on else HEATING_OFF_IGNORED
    assert state.control.latched_by == (cause,)
    # VT's next command, the other way: nothing written, the latch holds.
    state, outs = run(state, config, 380.0, 600.0, value, echo, opening=0.6 - opening)
    assert all(out.setpoint is None and out.heating is None for _t, out in outs)
    assert state.control.latched_by == (cause,)


def test_off_as_a_low_setpoint_ignored_from_the_start_hands_back() -> None:
    """I6 (decision 4, EMS-ESP's "off" at setpoint 0): without a heating switch "off" is the
    setpoint; the boiler ignoring that "off" from the start leaves the plugin unable to switch
    heating off — latched with ``heating_off_ignored`` and handed back at the next step, as
    answer O does for a heating switch. Nothing more is written while the latch holds."""
    config = replace(CONFIG, ch_writes=False, off_setpoint=0.0)
    own = 45.0  # the boiler's own setting, shown before the plugin and kept
    state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), own, config)
    assert out.setpoint is not None
    assert out.setpoint.value == 0.0
    state, outs = run(state, config, 10.0, 360.0, own, opening=0.0)
    assert outs[-1][1].ignored == ("setpoint",)
    state, out = loop_step(state, inputs(370.0, opening=0.0), own, config)
    assert out.hand_back
    assert state.control.latched_by == (HEATING_OFF_IGNORED,)
    state, outs = run(state, config, 380.0, 600.0, own)  # VT calls again: the latch holds
    assert all(out.setpoint is None for _t, out in outs)
    assert state.control.latched_by == (HEATING_OFF_IGNORED,)


def test_a_low_setpoint_path_ignoring_only_heat_does_not_latch() -> None:
    """The negative: the boiler ignores a heating setpoint from the start — "off" was never
    among what it did not take — so it is the ignored write it was before, not answer O: no
    latch, no hand-back."""
    config = replace(CONFIG, ch_writes=False, off_setpoint=0.0)
    own = 30.0
    state, out = loop_step(LoopState(), inputs(0.0), own, config)
    assert out.setpoint is not None
    assert out.setpoint.value > own
    state, outs = run(state, config, 10.0, 360.0, own)
    assert outs[-1][1].ignored == ("setpoint",)
    state, out = loop_step(state, inputs(370.0), own, config)
    assert not out.hand_back
    assert not state.control.latched


@pytest.mark.parametrize("case", ["unknown", "once_taken"])
def test_heating_on_not_judged_or_lost_later_never_latches(case: str) -> None:
    """Decision 4 of 0.2.3 (SB-03), negatives: the heating read-back unknown or unavailable
    throughout is never judged — "on" is not taken for ignored and nothing latches; "on" taken
    and held once, then never shown again, is a lost command sent again, not "ignored from the
    start" — nothing latches either."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    echo: bool | None = None if case == "unknown" else True
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config, False)
    value = out.setpoint.value
    state, _outs = run(state, config, 10.0, 200.0, value, echo)
    if case == "once_taken":
        assert state.switch.start_done
        echo = False  # from now on the read-back never shows "on"
    state, outs = run(state, config, 210.0, 1200.0, value, echo)
    assert not any(out.hand_back for _t, out in outs)
    assert not state.control.latched
    assert not state.switch.ignored
    if case == "once_taken":
        assert any(out.heating is not None for _t, out in outs)  # sent again
        assert state.losses


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
    control = ControlConfig(
        curve=HeatingCurve(), ramp_k_per_min=None, decision_interval_s=60.0, comfort_correction=True
    )
    config = replace(CONFIG, control=control)

    def short_zone(t: float) -> ZoneState:
        return ZoneState("z", 19.0, 21.0, True, reported_at=t, valve_open=1.0)

    for clip, rises in ((40.0, False), (None, True)):
        state = LoopState(setpoint=GuardState(clip=clip))
        t = 0.0
        while t <= 7200.0:
            # Heat flows (S-24); no start (rule 3); the first hour reads the outdoor (rule 5).
            step = inputs(t, zones=(short_zone(t),), flame=True, starts=())
            state, _ = loop_step(state, step, None, config)
            t += 10.0
        assert (state.control.correction > 0.0) is rises
        assert config.control.limits == FlowLimits()


def test_a_setpoint_not_shown_for_five_minutes_is_reported_not_judged() -> None:
    """Z4R2-03: the setpoint moves once; the read-back keeps the plugin's previous value — the
    device holds it. Nothing is judged and nothing blocked; after 5 minutes the output names the
    setpoint as not shown (the repair issue) and as unconfirmed ("confirmation missing"). It ends
    once the value is read back. Negative: 4 min 50 s — neither."""
    state, out = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    assert out.setpoint is not None
    first = out.setpoint.value
    t = 10.0
    while t <= 600.0:
        state, out = loop_step(state, inputs(t), first, CONFIG)
        t += 10.0
    changed = None
    while changed is None and t <= 2000.0:
        state, out = loop_step(state, inputs(t, outdoor_sensor=-5.0), first, CONFIG)
        if out.setpoint is not None and out.setpoint.value != first:
            changed = t
        t += 10.0
    assert changed is not None  # colder: one new value, no ramp
    new = state.setpoint.written
    shown: dict[float, tuple[tuple[str, ...], tuple[str, ...]]] = {}
    while t <= changed + 400.0:
        state, out = loop_step(state, inputs(t, outdoor_sensor=-5.0), first, CONFIG)
        assert not out.blocked
        assert not out.events
        shown[t] = (out.not_shown, out.unconfirmed)
        t += 10.0
    seen_from = changed + 10.0  # the first step that read the previous value back
    assert shown[seen_from + 290.0] == ((), ())
    assert shown[seen_from + 300.0] == (("setpoint",), ("setpoint",))
    state, out = loop_step(state, inputs(t, outdoor_sensor=-5.0), new, CONFIG)
    assert (out.not_shown, out.unconfirmed) == ((), ())


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
    """An expiring heating switch lapses with the setpoint (on the gateway both are lost at a
    reset): the recovery write carries the heating state too, not only the next keep-alive. (The
    drop comes in the start phase: a failed attempt, sent again — decision 6.)"""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), None, config)
    assert out.setpoint is not None
    sent = out.setpoint.value
    assert out.heating == WriteAction(1.0, WriteKind.CHANGE)
    state, confirmed = loop_step(state, inputs(10.0), sent, config)
    assert (confirmed.setpoint, confirmed.heating) == (None, None)  # nothing due yet
    state, out = loop_step(state, inputs(20.0), 30.0, config)  # the gateway dropped it
    # P-121: exactly the same value and heating on, both sent again at once — no rewrite, no
    # event, the one rewrite of the day kept.
    assert out.setpoint == WriteAction(sent, WriteKind.RESEND)
    assert out.heating == WriteAction(1.0, WriteKind.RESEND)
    assert out.ch_enable is True
    assert out.events == ()
    assert not out.hand_back
    assert state.setpoint.rewritten_at is None


HELD_SWITCH = GuardConfig(write_type=WriteType.HELD, read_back=False, two_valued=True)


@pytest.mark.parametrize("heating", [True, False], ids=["on", "off"])
@pytest.mark.parametrize("switch", [HELD_SWITCH, ECHOED_SWITCH], ids=["no_echo", "echo"])
def test_a_recovered_setpoint_still_resends_the_heating_override(
    heating: bool, switch: GuardConfig
) -> None:
    """X6: a held heating override — the OTGW's ``CH=``, kept until ``CH=1`` or a reset — is
    lost together with the setpoint at a PIC reset: when the setpoint is back at its value from
    before the session and is sent again, heating on/off is sent again with it, "off" above all
    (after a reset the gateway would enable heating under the plugin's setpoint). Negative: with
    X1's 5-minute held refresh, a plain keep-alive of the setpoint carries no heating write (the
    OTGW's own refresh with every keep-alive is its guard's option: ``test_control_config``)."""
    config = replace(CONFIG, switch_guard=switch)
    opening = 0.6 if heating else 0.0
    echo = heating if switch.read_back else None
    state, out = loop_step(LoopState(), inputs(0.0, opening=opening), 0.0, config, echo)
    assert out.ch_enable is heating
    value = out.setpoint.value
    state, outs = run(state, config, 10.0, 200.0, value, echo, opening=opening)
    assert all(o.heating is None for _t, o in outs if o.setpoint is not None)  # keep-alives only
    context = GuardContext(outage_at=205.0)  # the gateway reset, before the held refresh is due
    reset_echo = True if switch.read_back else None  # a reset clears the PIC's CH=0 flag
    state, out = loop_step(
        state,
        inputs(210.0, opening=opening),
        0.0,
        config,
        reset_echo,
        setpoint_context=context,
        heating_context=context,
    )
    assert out.setpoint == WriteAction(value, WriteKind.RESEND)
    assert out.heating is not None
    assert out.heating.value == (1.0 if heating else 0.0)
    assert out.heating.kind is WriteKind.RESEND
    assert len(state.losses) == 1  # one gateway reset, one lost command


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


# --- X8: on/off control through a relay ---------------------------------------------------------

RELAY_LOOP = LoopConfig(
    control=ControlConfig(
        curve=HeatingCurve(), ramp_k_per_min=None, on_off=True, stale_hand_back_s=None
    ),
    ch_writes=False,
    relay=RelayConfig(reports=RelayReports.YES, power_on=RelayPowerOn.ON, timer=RelayTimer.NONE),
)


def test_a_relay_has_no_setpoint_guard() -> None:
    """R5: the loop plans no setpoint or heating-switch write on the relay path; heating on/off
    goes to the relay rule, and the guards stay untouched."""
    seen = RelaySeen(on=False, known=True, available=True)
    state, out = loop_step(LoopState(), inputs(0.0), None, RELAY_LOOP, relay_seen=seen)
    assert out.setpoint is None
    assert out.heating is None
    assert out.relay == RelayWrite(True, WriteKind.CHANGE)
    assert out.heating_on is True
    assert state.setpoint == GuardState()
    assert state.switch == GuardState()
    assert out.decision.command is not None
    assert out.decision.command.setpoint is None
    # Without an outdoor temperature too: never FALLBACK.
    _state, out = loop_step(
        LoopState(), inputs(0.0, outdoor_sensor=None), None, RELAY_LOOP, relay_seen=seen
    )
    assert out.relay == RelayWrite(True, WriteKind.CHANGE)
    assert out.decision.mode.value == "heating"


def test_a_relay_loss_counts_toward_commands_lost_and_a_step_aside_hands_back() -> None:
    """A relay's lost commands feed "commands lost"; another controller stops every write, and
    the next step hands back (the unit then latches and makes the relay's hand-back)."""
    on = RelaySeen(on=True, known=True, available=True)
    state, out = loop_step(LoopState(), inputs(0.0), None, RELAY_LOOP, relay_seen=on)
    assert out.relay is None  # it already shows the command: nothing written
    for n, t in enumerate((1000.0, 2000.0, 3000.0), start=1):
        back = RelaySeen(on=False, known=True, available=True, trace=True, changed_at=t)
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=back)
        assert out.relay == RelayWrite(True, WriteKind.RESEND)
        assert out.commands_lost is (n == 3)
        state, out = loop_step(state, inputs(t + 10), None, RELAY_LOOP, relay_seen=on)
    switched = RelaySeen(on=False, known=True, available=True, changed_at=4000.0)
    state, out = loop_step(state, inputs(4000.0), None, RELAY_LOOP, relay_seen=switched)
    assert out.relay == RelayWrite(True, WriteKind.REWRITE)  # answer C: rewritten once
    state, out = loop_step(state, inputs(4010.0), None, RELAY_LOOP, relay_seen=on)
    switched = RelaySeen(on=False, known=True, available=True, changed_at=5000.0)
    state, out = loop_step(state, inputs(5000.0), None, RELAY_LOOP, relay_seen=switched)
    assert out.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert out.relay is None
    assert out.blocked
    # The unit turns the event into the always-hand-back alarm: the next step hands back.
    state, out = loop_step(
        state,
        inputs(5010.0, hand_back_alarms=("outside_change",)),
        None,
        RELAY_LOOP,
        relay_seen=switched,
    )
    assert out.hand_back
    assert state.relay.written is None
    assert state.relay.blocked  # the session's memory stays


@pytest.mark.parametrize("command", [False, True], ids=["off", "on"])
def test_a_relay_that_ignores_off_from_the_start_blocks_control(command: bool) -> None:
    """Answer O applied to relays: "off" ignored from the start — the next step latches with
    ``heating_off_ignored`` and hands back, whatever reaction is stored. Decision 4 of 0.2.3
    (SB-03, R7): "on" ignored from the start — latched with ``heating_on_ignored`` alike; before,
    reported only, the relay never written again. Nothing more is planned while it holds."""
    stuck = RelaySeen(on=not command, known=True, available=True)
    zones = (ZoneState("z", 20.0, 21.0, True, reported_at=0.0, valve_open=0.6 * command),)
    state = LoopState()
    out = None
    for t in [10.0 * n for n in range(0, 80)]:
        state, out = loop_step(state, inputs(t, zones=zones), None, RELAY_LOOP, relay_seen=stuck)
        if out.hand_back:
            break
    assert out is not None
    assert out.hand_back
    assert state.control.latched
    cause = HEATING_ON_IGNORED if command else HEATING_OFF_IGNORED
    assert state.control.latched_by == (cause,)
    assert out.ignored == ("relay",)
    calls = 0.6 * (not command)
    for t in [800.0 + 10.0 * n for n in range(60)]:  # VT's next command, the other way
        step = inputs(t, opening=calls)
        state, out = loop_step(state, step, None, RELAY_LOOP, relay_seen=stuck)
        assert out.relay is None
    assert state.control.latched_by == (cause,)


def test_a_relay_that_stops_taking_off_mid_session_blocks_control() -> None:
    """Decision 6 of 0.2.3 (SB-06): a relay that held "on" — the start phase over — and then
    does not show "off" over three checks running: the next step latches with
    ``relay_off_not_taken`` and hands back, whatever reaction is stored, as answer O does; the
    relay stays named among the ignored targets. Negative: "on" not taken never blocks."""
    stuck = RelaySeen(on=True, known=True, available=True)
    state = LoopState()
    for t in [10.0 * n for n in range(30)]:  # the rooms call: "on", shown and held
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=stuck)
    assert state.relay.start_done
    out = None
    for t in [300.0 + 10.0 * n for n in range(150)]:  # they stop calling: "off", never shown
        state, out = loop_step(state, inputs(t, opening=0.0), None, RELAY_LOOP, relay_seen=stuck)
        if out.hand_back:
            break
    assert out is not None
    assert out.hand_back
    assert out.decision.command is None
    assert state.control.latched
    assert state.control.latched_by == (RELAY_OFF_NOT_TAKEN,)
    assert out.ignored == ("relay",)
    assert state.relay.off_not_taken
    # "On" not taken: reported, sent again, never a block.
    off = RelaySeen(on=False, known=True, available=True)
    state = LoopState()
    for t in [10.0 * n for n in range(30)]:
        state, out = loop_step(state, inputs(t, opening=0.0), None, RELAY_LOOP, relay_seen=off)
    for t in [300.0 + 10.0 * n for n in range(150)]:
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=off)
        assert not out.hand_back
    assert state.relay.not_taken
    assert not state.control.latched


def test_a_new_session_keeps_the_relays_rewrite_and_restarts_for_their_day() -> None:
    relay = RelayState(rewritten_at=100.0, restarts=(50.0,), blocked=True, ignored=True)
    kept = new_session(LoopState(relay=relay), 1000.0).relay
    assert kept.rewritten_at == 100.0
    assert kept.restarts == (50.0,)
    assert not kept.blocked
    assert not kept.ignored


def test_a_relays_own_timer_lapses_never_raise_commands_lost() -> None:
    """R5 (SCOPE §5 class 3): a relay whose declared 10-min timer a repeated "on" does not
    restart lapses every 10 minutes through a whole day. Each lapse is its own: "on" goes out
    again at the same step, no loss is counted, and "commands lost" never rises."""
    relay = RelayConfig(
        reports=RelayReports.YES,
        power_on=RelayPowerOn.OFF,
        timer=RelayTimer.MINUTES,
        timer_s=600.0,
    )
    config = replace(RELAY_LOOP, relay=relay)
    state = LoopState()
    on, on_at, changed_at = False, None, None
    lapses = resent = 0
    t = 0.0
    while t <= DAY:
        if on and on_at is not None and t - on_at >= 600.0:  # the relay's own timer
            on, changed_at = False, on_at + 600.0
            lapses += 1
        seen = RelaySeen(on=on, known=True, available=True, changed_at=changed_at)
        state, out = loop_step(state, inputs(t), None, config, relay_seen=seen)
        assert not out.commands_lost, t
        if out.relay is not None:
            if out.relay.on and not on:
                on_at, changed_at = t, t
                resent += 1
            on = out.relay.on
        t += 10.0
    assert lapses == 144
    assert resent == lapses + 1  # the first "on", then one at each lapse
    assert state.losses == ()
    assert on


# --- Mutation testing (2026-10-12): defaults, grids, outputs of every step, the warning's day ---

GRID = Grid(step=0.5, minimum=0.25, maximum=90.0)  # 70 on it is 69.75: never above, never below


def test_the_default_heating_switch_is_held_and_never_judged() -> None:
    """Negative: by default heating on/off has no echo — held: written, refreshed every 5 minutes
    with no echo required, and never judged; a read-back showing the other state throughout makes
    it neither "ignored from the start" nor a latch."""
    config = LoopConfig(control=CONFIG.control, setpoint_guard=CONFIG.setpoint_guard)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config, False)
    assert out.heating == WriteAction(1.0, WriteKind.CHANGE)
    state, outs = run(state, config, 10.0, 1200.0, out.setpoint.value, False)
    assert [t for t, o in outs if o.heating is not None] == [300.0, 600.0, 900.0, 1200.0]
    assert not any(o.hand_back or o.ignored for _t, o in outs)
    assert not state.switch.ignored
    assert not state.control.latched


def test_a_new_session_keeps_the_heating_switchs_one_rewrite() -> None:
    """The heating switch's one rewrite is kept through a new session for its day, as the
    setpoint's; everything else of it starts afresh."""
    state = LoopState(switch=GuardState(written=1.0, rewritten_at=0.0, ignored=True))
    assert new_session(state, 100.0).switch == GuardState(rewritten_at=0.0)
    assert new_session(state, DAY).switch == GuardState()


def test_a_new_session_keeps_the_wait_for_a_link_not_yet_reported() -> None:
    """Negative (X2, X3): the boiler link silent while the restore waits for its first report is
    no staleness; control switched off and on during that wait still knows it, so the link
    reporting at the next step is fresh — not lost at once for the silence before."""
    wait = {"boiler_link": False, "link_unreported": True}
    state, outs = run(LoopState(), CONFIG, 0.0, 400.0, None, **wait)
    assert not any(out.decision.link_lost for _t, out in outs)
    fresh = new_session(state, 410.0)
    _state, out = loop_step(fresh, inputs(410.0), None, CONFIG)
    assert not out.decision.link_lost


@pytest.mark.parametrize("ch_writes", [True, False], ids=["switch", "low_setpoint"])
@pytest.mark.parametrize(
    ("bounds", "outdoor", "sent"),
    [
        ({"circuit_max": 60.0}, -30.0, 59.75),
        ({"boiler_max": 60.0}, -30.0, 59.75),
        ({"circuit_floor": 40.4}, 20.0, 40.75),
        ({}, 20.0, 25.25),
    ],
    ids=["circuit_max", "boiler_max", "circuit_floor", "hard_min"],
)
def test_a_setpoint_on_a_grid_stays_inside_every_bound(
    ch_writes: bool, bounds: dict, outdoor: float, sent: float
) -> None:
    """P-98, P-15: on an entity's grid of 0.5 from 0.25, a circuit's or the boiler's maximum of 60
    is sent as 59.75, never 60.25; a fixed circuit's floor of 40.4 as 40.75, never 40.25; the hard
    minimum 25 as 25.25, never 24.75 — with a heating switch and with "off" as a low setpoint."""
    control = ControlConfig(curve=HeatingCurve(design_flow=75.0), ramp_k_per_min=None, **bounds)
    config = replace(CONFIG, control=control, ch_writes=ch_writes)
    step = inputs(0.0, outdoor_sensor=outdoor)
    _state, out = loop_step(LoopState(), step, 0.0, config, grid=GRID)
    assert out.setpoint == WriteAction(sent, WriteKind.CHANGE)
    assert out.heating_on is True


def test_off_on_a_grid_is_never_above_itself_and_ignored_it_hands_back() -> None:
    """P-15, I6: "off" as a low setpoint of 10 on an entity's grid of 0.5 from 0.25 is sent as
    9.75 — the grid value at or below it, never 10.25 nor raised to the heating limits — and known
    as "off". The boiler ignoring it from the start is recognised as "off" ignored: latched with
    ``heating_off_ignored`` and handed back at the next step."""
    config = replace(CONFIG, ch_writes=False, off_setpoint=10.0)
    own = 45.0  # the boiler's own setting, shown before the plugin and kept
    state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), own, config, grid=GRID)
    assert out.setpoint == WriteAction(9.75, WriteKind.CHANGE)
    assert out.heating_on is False
    t = 10.0
    while t <= 360.0:
        state, out = loop_step(state, inputs(t, opening=0.0), own, config, grid=GRID)
        t += 10.0
    assert out.ignored == ("setpoint",)
    state, out = loop_step(state, inputs(370.0, opening=0.0), own, config, grid=GRID)
    assert out.hand_back
    assert state.control.latched_by == (HEATING_OFF_IGNORED,)


def test_off_without_a_grid_value_at_or_below_it_is_not_written() -> None:
    """Negative (P-15): an entity whose lowest value lies above "off" as a low setpoint has no grid
    value for it — "off" is not written, and heating is shown neither on nor off."""
    config = replace(CONFIG, ch_writes=False, off_setpoint=10.0)
    grid = Grid(step=0.5, minimum=20.0, maximum=90.0)
    _state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), None, config, grid=grid)
    assert out.decision.command is not None
    assert out.decision.command.ch_enable is False
    assert out.setpoint is None
    assert out.heating_on is None


def test_a_water_path_command_without_a_setpoint_writes_nothing() -> None:
    """Negative: a command without a water temperature (on/off control) where "off" is a low
    setpoint writes no heating value — on an entity's grid too — and claims no heating state."""
    control = ControlConfig(
        curve=HeatingCurve(), ramp_k_per_min=None, on_off=True, stale_hand_back_s=None
    )
    config = replace(CONFIG, control=control, ch_writes=False)
    _state, out = loop_step(LoopState(), inputs(0.0), None, config, grid=GRID)
    assert out.decision.command is not None
    assert out.decision.command.ch_enable is True
    assert out.decision.command.setpoint is None
    assert out.setpoint is None
    assert out.heating_on is None


def test_heat_a_kelvin_above_off_ignored_from_the_start_does_not_latch() -> None:
    """Negative (I6, P-43): "off" as a low setpoint 1 K below the hard minimum — the closest
    allowed; the boiler ignores the heating setpoint (the hard minimum) from the start: "off" was
    never among what it did not take, so no latch and no hand-back."""
    config = replace(CONFIG, ch_writes=False, off_setpoint=24.0)
    own = 30.0
    warm = {"outdoor_sensor": 20.0}
    state, out = loop_step(LoopState(), inputs(0.0, **warm), own, config)
    assert out.setpoint == WriteAction(25.0, WriteKind.CHANGE)
    state, outs = run(state, config, 10.0, 360.0, own, **warm)
    assert outs[-1][1].ignored == ("setpoint",)
    state, out = loop_step(state, inputs(370.0, **warm), own, config)
    assert not out.hand_back
    assert not state.control.latched


def test_a_held_heating_switch_back_from_unavailable_is_written_again_at_once() -> None:
    """A held heating switch back from unavailable gets heating on/off again at once, not at the
    next 5-minute refresh. Negative: without the return, nothing is due yet."""
    state, out = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    value = out.setpoint.value
    back = GuardContext(returned=True)
    _state, out = loop_step(state, inputs(20.0), value, CONFIG, heating_context=back)
    assert out.heating == WriteAction(1.0, WriteKind.KEEPALIVE)
    _state, out = loop_step(state, inputs(20.0), value, CONFIG)
    assert out.heating is None
    assert out.hand_back is False


def test_a_hand_back_still_names_the_target_ignored_from_the_start() -> None:
    """Answer O: the step that hands back after heating on/off was ignored from the start still
    names it among the ignored targets; nothing is unconfirmed or not shown — a hand-back sends
    nothing — and no warning is raised."""
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0, opening=0.0), 0.0, config, True)
    value = out.setpoint.value
    state, _outs = run(state, config, 10.0, 360.0, value, True, opening=0.0)
    state, out = loop_step(state, inputs(370.0, opening=0.0), value, config, True)
    assert out.hand_back
    assert out.decision.hand_back
    assert (out.ignored, out.unconfirmed, out.not_shown) == (("heating",), (), ())
    assert out.commands_lost is False


def test_commands_lost_holds_for_a_day_after_the_last_loss() -> None:
    """The warning "commands lost" stays on until a day without a loss — not only while three
    losses fall within the day: with the first of them a day old and the last not, it holds while
    writing goes on, and clears a day after the last."""
    losses = ((0.0, SETPOINT), (1000.0, SETPOINT), (2000.0, SETPOINT))
    state, out = loop_step(LoopState(losses=losses), inputs(3000.0), None, CONFIG)
    assert out.commands_lost is True
    for t in (DAY + 100.0, DAY + 110.0):  # two within the day now
        state, out = loop_step(state, inputs(t), None, CONFIG)
        assert out.decision.command is not None
        assert not out.blocked
        assert out.commands_lost is True
    state, out = loop_step(state, inputs(DAY + 2000.0), None, CONFIG)
    assert out.commands_lost is False


def test_a_loss_recorded_between_steps_holds_the_warning_through_a_hand_back() -> None:
    """A lost command recorded between steps (as the unit records the external-control switch's)
    as the third within a day raises "commands lost" at the next step, even one that hands back;
    it then holds for a day after the last loss through steps with nothing to write."""
    losses = ((0.0, SETPOINT), (1000.0, SETPOINT))
    state, out = loop_step(LoopState(losses=losses), inputs(DAY - 40.0), None, CONFIG)
    assert out.commands_lost is False
    state = replace(state, losses=add_loss(state.losses, DAY - 30.0, "external"))
    alarm = ("pressure_low",)
    state, out = loop_step(state, inputs(DAY - 20.0, hand_back_alarms=alarm), None, CONFIG)
    assert out.hand_back
    assert out.commands_lost is True
    state, out = loop_step(state, inputs(DAY + 10.0), None, CONFIG)  # the first a day old
    assert out.decision.command is None
    assert out.commands_lost is True
    state, out = loop_step(state, inputs(2 * DAY - 20.0), None, CONFIG)
    assert out.commands_lost is False


@pytest.mark.parametrize("case", ["not_shown", "ignored"])
def test_a_step_with_nothing_to_write_still_reports_the_targets(case: str) -> None:
    """A step that writes nothing for want of fresh data still reports the setpoint: not shown for
    five minutes (and so unconfirmed), or ignored from the start."""
    state, out = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    value = out.setpoint.value
    if case == "not_shown":
        setpoint = replace(state.setpoint, unshown_since=0.0)
        expected = ((), ("setpoint",), ("setpoint",))
    else:
        setpoint = replace(state.setpoint, ignored=True, ignored_values=(value,))
        expected = (("setpoint",), (), ())
    state = replace(state, setpoint=setpoint)
    _state, out = loop_step(state, inputs(400.0, boiler_link=False), None, CONFIG)
    assert out.decision.command is None
    assert out.blocked is False
    assert (out.ignored, out.unconfirmed, out.not_shown) == expected


@pytest.mark.parametrize("target", ["setpoint", "switch"])
def test_a_target_held_by_another_controller_is_reported_while_waiting(target: str) -> None:
    """P53: another controller holds one target — the setpoint or heating on/off — and the step
    has no command (no fresh data): still reported blocked, nothing written."""
    state, _ = loop_step(LoopState(), inputs(0.0), None, CONFIG)
    guard = replace(getattr(state, target), blocked=GuardEvent.OUTSIDE_CHANGE)
    state = replace(state, **{target: guard})
    _state, out = loop_step(state, inputs(30.0, boiler_link=False), None, CONFIG)
    assert out.decision.command is None
    assert out.blocked is True
    assert (out.setpoint, out.heating) == (None, None)


def test_the_setpoint_found_held_by_another_controller_keeps_its_block() -> None:
    """Decision 6: the setpoint changed from outside again after its one rewrite — the guard keeps
    the block after the step, and the next step writes nothing."""
    config = replace(CONFIG, switch_guard=EXPIRING_SWITCH)
    state, out = loop_step(LoopState(), inputs(0.0), 0.0, config)
    setpoint = out.setpoint.value
    state, _ = loop_step(state, inputs(10.0), setpoint, config)  # confirmed
    state, _ = loop_step(state, inputs(20.0), 60.0, config)
    state, _ = loop_step(state, inputs(30.0), 60.0, config)  # the one rewrite
    state, _ = loop_step(state, inputs(40.0), setpoint, config)
    state, _ = loop_step(state, inputs(50.0), 60.0, config)
    state, out = loop_step(state, inputs(60.0), 60.0, config)
    assert out.blocked
    assert state.setpoint.blocked is GuardEvent.OUTSIDE_CHANGE
    _state, out = loop_step(state, inputs(70.0), 60.0, config)
    assert (out.setpoint, out.heating, out.blocked) == (None, None, True)


@pytest.mark.parametrize("case", ["not_shown", "ignored"])
def test_another_controller_found_still_reports_the_other_target(case: str) -> None:
    """P22, row 13: the step that finds heating on/off switched from outside again stops every
    write, keeps the block, leaves the setpoint as it was before the step and still reports it —
    not shown for five minutes, or ignored from the start — and "commands lost", which holds
    after it for a day after the last loss."""
    b = DAY  # a day of losses counted back from the start
    config = replace(CONFIG, switch_guard=ECHOED_SWITCH)
    state, out = loop_step(LoopState(), inputs(b), 0.0, config, True)  # "on" before
    value = out.setpoint.value
    state, _ = run(state, config, b + 10.0, b + 390.0, value, True)  # confirmed, past the start
    state, _ = loop_step(state, inputs(b + 400.0), value, config, False)  # switched off outside
    state, _ = loop_step(state, inputs(b + 410.0), value, config, False)  # the one rewrite
    state, _ = loop_step(state, inputs(b + 420.0), value, config, True)
    state, _ = loop_step(state, inputs(b + 500.0), value, config, False)
    if case == "not_shown":
        setpoint = replace(state.setpoint, unshown_since=b)
        expected = ((), ("setpoint",), ("setpoint",))
    else:
        setpoint = replace(state.setpoint, ignored=True, ignored_values=(value,))
        expected = (("setpoint",), (), ())
    losses = ((515.0, SETPOINT), (b, SETPOINT), (b + 100.0, SETPOINT))
    state = replace(state, setpoint=setpoint, losses=losses)
    state, out = loop_step(state, inputs(b + 510.0), value, config, False)  # again
    assert out.blocked
    assert out.events == (GuardEvent.OUTSIDE_CHANGE,)
    assert out.decision.command is not None
    assert (out.ignored, out.unconfirmed, out.not_shown) == expected
    assert out.commands_lost is True
    assert state.switch.blocked is GuardEvent.OUTSIDE_CHANGE
    assert state.setpoint == setpoint
    _state, out = loop_step(state, inputs(b + 520.0), value, config, False)  # 515 a day old
    assert (out.setpoint, out.heating, out.blocked) == (None, None, True)
    assert out.commands_lost is True


def test_a_relays_reach_is_followed_through_a_hand_back() -> None:
    """X8: the relay is followed at every step, a hand-back's included — out of reach from the
    step that hands back, its alarm comes five minutes later, not five minutes after the next
    step; a hand-back while it is out of reach still reports the alarm; a relay that takes its
    commands is never named ignored."""
    on = RelaySeen(on=True, known=True, available=True)
    gone = RelaySeen()
    alarm = ("pressure_low",)
    state, _ = loop_step(LoopState(), inputs(0.0), None, RELAY_LOOP, relay_seen=on)
    state, out = loop_step(
        state, inputs(10.0, hand_back_alarms=alarm), None, RELAY_LOOP, relay_seen=gone
    )
    assert out.hand_back
    assert out.ignored == ()
    assert out.relay_unreachable is False
    for t in (20.0, 300.0):
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=gone)
        assert out.relay_unreachable is False
    state, out = loop_step(state, inputs(310.0), None, RELAY_LOOP, relay_seen=gone)
    assert out.relay_unreachable is True
    # Out of reach while control goes on: the alarm after five minutes, and at a hand-back.
    state, _ = loop_step(LoopState(), inputs(0.0), None, RELAY_LOOP, relay_seen=on)
    for t in [10.0 * n for n in range(1, 40)]:
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=gone)
        assert not out.hand_back
        assert out.relay_unreachable is (t >= 310.0)
    state, out = loop_step(
        state, inputs(400.0, hand_back_alarms=alarm), None, RELAY_LOOP, relay_seen=gone
    )
    assert out.hand_back
    assert out.relay_unreachable is True


def test_an_untraced_relay_restart_is_answered_and_reported() -> None:
    """Answers D, N: a relay commanded "off" shows its power-on state "on" with no trace — a
    restart it did not report: "off" sent again at once, counted, and reported so that it is
    stored at once. Negative: before it, no restart is reported."""
    off = RelaySeen(on=False, known=True, available=True)
    state = LoopState()
    for t in [10.0 * n for n in range(10)]:
        step = inputs(t, opening=0.0)
        state, out = loop_step(state, step, None, RELAY_LOOP, relay_seen=off)
        assert out.relay_restart is False
    back_on = RelaySeen(on=True, known=True, available=True, changed_at=100.0)
    step = inputs(100.0, opening=0.0)
    state, out = loop_step(state, step, None, RELAY_LOOP, relay_seen=back_on)
    assert out.relay == RelayWrite(False, WriteKind.RESEND)
    assert out.relay_restart is True
    assert state.relay.restarts == (100.0,)


def test_a_relay_ignored_from_the_start_is_named_at_the_step_that_finds_it() -> None:
    """R7: the step that finds the relay ignoring "on" from the start names it among the ignored
    targets, before the next step latches and hands back; until then it is named nowhere."""
    stuck = RelaySeen(on=False, known=True, available=True)
    state = LoopState()
    outs = []
    for t in [10.0 * n for n in range(80)]:
        state, out = loop_step(state, inputs(t), None, RELAY_LOOP, relay_seen=stuck)
        outs.append(out)
        if out.hand_back:
            break
    assert outs[-1].hand_back
    found = next(n for n, out in enumerate(outs) if out.ignored)
    assert 0 < found < len(outs) - 1
    assert outs[found].ignored == ("relay",)
    assert all(out.ignored == () for out in outs[:found])


def test_relay_losses_hold_the_warning_for_a_day_after_the_last() -> None:
    """A relay's third lost command within a day raises "commands lost", which holds for a day
    after the last loss — with the first of the three a day old, and through a hand-back."""
    on = RelaySeen(on=True, known=True, available=True)
    losses = ((0.0, RELAY), (1000.0, RELAY))
    state = LoopState(losses=losses)
    state, out = loop_step(state, inputs(DAY - 1000.0), None, RELAY_LOOP, relay_seen=on)
    assert out.commands_lost is False
    back = RelaySeen(on=False, known=True, available=True, trace=True, changed_at=DAY - 20.0)
    state, out = loop_step(state, inputs(DAY - 20.0), None, RELAY_LOOP, relay_seen=back)
    assert out.relay == RelayWrite(True, WriteKind.RESEND)
    assert out.commands_lost is True
    state, out = loop_step(state, inputs(DAY + 10.0), None, RELAY_LOOP, relay_seen=on)
    assert out.commands_lost is True  # two within the day now
    alarm = ("pressure_low",)
    step = inputs(DAY + 20.0, hand_back_alarms=alarm)
    state, out = loop_step(state, step, None, RELAY_LOOP, relay_seen=on)
    assert out.hand_back
    assert out.commands_lost is True
    state, out = loop_step(state, inputs(DAY + 1010.0), None, RELAY_LOOP, relay_seen=on)
    assert out.commands_lost is True  # one within the day


def test_a_last_command_round_trips_with_its_setpoint() -> None:
    """V3: the setpoint written is stored under its own key and read back, so the next start gives
    the same command again."""
    command = LastCommand(True, 45.5, 12.5)
    assert command.as_dict() == {"heating": True, "setpoint": 45.5, "at": 12.5}
    assert parse_last_command(command.as_dict()) == command
