"""Decision 2 of 0.2.3 (SB-01): "no sign the boiler heats" on the water-temperature paths."""

from __future__ import annotations

from dataclasses import replace

from custom_components.vtherm_smart_boiler.core.guards import DRAW_QUIET_S
from custom_components.vtherm_smart_boiler.core.heat_sign import (
    HeatSignSeen,
    HeatSignState,
    follow_heat_sign,
)
from custom_components.vtherm_smart_boiler.core.relay import PROOF_FLOW_RISE_K, PROOF_WINDOW_S

STEP = 60.0
MINUTE = 60.0
# Heating commanded while a zone calls, the flame known off, the flow below the setpoint.
COLD = HeatSignSeen(commanded=True, calling=True, flame=False, flow=35.0, setpoint=50.0)


def run(
    state: HeatSignState, seen: HeatSignSeen, start: float, end: float
) -> tuple[HeatSignState, float]:
    """``seen`` at every step from ``start`` up to ``end``: the state, and the next moment."""
    now = start
    while now <= end:
        state = follow_heat_sign(state, seen, now)
        now += STEP
    return state, now


def test_the_flame_off_for_thirty_minutes_raises_the_alarm_and_the_flame_clears_it() -> None:
    """The review's case: a calling zone, heating on, the flame off — the alarm at 30 minutes
    (31 shown), not at 29; the flame on clears it and starts the count again."""
    state, _ = run(HeatSignState(), COLD, 0.0, 29 * MINUTE)
    assert not state.alarm
    state, now = run(state, COLD, 30 * MINUTE, 31 * MINUTE)
    assert state.alarm
    assert PROOF_WINDOW_S == 30 * MINUTE  # the relay's window (R12): one value, provisional, K4
    state = follow_heat_sign(state, replace(COLD, flame=True), now)
    assert state == HeatSignState()


def test_twenty_nine_minutes_raise_nothing() -> None:
    state, _ = run(HeatSignState(), COLD, 0.0, PROOF_WINDOW_S - MINUTE)
    assert not state.alarm
    assert state.since == 0.0


def test_neither_the_flame_nor_the_flow_known_judges_nothing() -> None:
    blind = replace(COLD, flame=None, flow=None)
    state, _ = run(HeatSignState(), blind, 0.0, 4 * PROOF_WINDOW_S)
    assert state == HeatSignState()


def test_the_flow_alone_raises_the_alarm_and_its_rise_clears_it() -> None:
    """The flame unknown: no rise of the flow of 5 K since the count began, for 30 minutes —
    the alarm; a rise of 5 K clears it, not one just short of it."""
    flow_only = replace(COLD, flame=None)
    state, now = run(HeatSignState(), flow_only, 0.0, 31 * MINUTE)
    assert state.alarm
    assert state.flow_from == 35.0
    short = replace(flow_only, flow=35.0 + PROOF_FLOW_RISE_K - 0.1)
    state = follow_heat_sign(state, short, now)
    assert state.alarm
    state = follow_heat_sign(state, replace(flow_only, flow=35.0 + PROOF_FLOW_RISE_K), now + STEP)
    assert state == HeatSignState()


def test_a_flow_rise_clears_it_with_the_flame_known_off_too() -> None:
    """As the relay's proof (R12): any sign of heat is one — a flow risen 5 K with the flame
    reading off clears the alarm."""
    state, now = run(HeatSignState(), COLD, 0.0, 31 * MINUTE)
    assert state.alarm
    state = follow_heat_sign(state, replace(COLD, flow=40.0), now)
    assert state == HeatSignState()


def test_the_flow_first_known_after_the_count_began_is_its_reference() -> None:
    state = follow_heat_sign(HeatSignState(), replace(COLD, flow=None), 0.0)
    assert (state.since, state.flow_from) == (0.0, None)
    state = follow_heat_sign(state, replace(COLD, flow=30.0), STEP)
    assert (state.since, state.flow_from) == (0.0, 30.0)


def test_the_flow_at_or_above_the_setpoint_raises_nothing() -> None:
    """A boiler resting because its water is as hot as asked is not judged."""
    for flow in (50.0, 55.0):
        state, _ = run(HeatSignState(), replace(COLD, flow=flow), 0.0, 2 * PROOF_WINDOW_S)
        assert state == HeatSignState(), flow


def test_without_a_setpoint_the_flow_is_not_compared() -> None:
    """The water paths always command a setpoint; without one the flame alone judges."""
    state, _ = run(HeatSignState(), replace(COLD, setpoint=None), 0.0, 31 * MINUTE)
    assert state.alarm


def test_the_flame_unknown_and_the_water_at_the_setpoint_clears_it() -> None:
    """The flame unknown, a raised alarm goes once the boiler holds the water at the plugin's
    setpoint while heating is commanded — a boiler that heats slowly is not left flagged; while
    heating is not commanded that says nothing."""
    flow_only = replace(COLD, flame=None, flow=47.0)  # 3 K short: no 5-K rise can show
    state, now = run(HeatSignState(), flow_only, 0.0, 31 * MINUTE)
    assert state.alarm
    resting = replace(flow_only, commanded=False, flow=50.0)
    state = follow_heat_sign(state, resting, now)
    assert state.alarm
    state = follow_heat_sign(state, replace(flow_only, flow=50.0), now + STEP)
    assert state == HeatSignState()


def test_the_zone_that_stops_calling_starts_the_count_again() -> None:
    state, now = run(HeatSignState(), COLD, 0.0, 20 * MINUTE)
    state = follow_heat_sign(state, replace(COLD, calling=False), now)
    assert state.since is None
    state, now = run(state, COLD, now + STEP, now + 21 * MINUTE)
    assert not state.alarm  # 41 minutes in all, 20 of them since the count began again
    state, _ = run(state, COLD, now, now + 10 * MINUTE)
    assert state.alarm


def test_a_hot_water_draw_starts_the_count_again() -> None:
    """During a draw and two minutes after it nothing is judged; the count begins again after."""
    state, now = run(HeatSignState(), COLD, 0.0, 20 * MINUTE)
    state = follow_heat_sign(state, replace(COLD, dhw=True), now)
    assert state.since is None
    state, now = run(state, COLD, now + STEP, now + DRAW_QUIET_S)
    assert state.since is None  # the after-draw window
    state, now = run(state, COLD, now, now + 29 * MINUTE)
    assert not state.alarm
    state, _ = run(state, COLD, now, now + 2 * MINUTE)
    assert state.alarm


def test_the_burner_of_a_draw_does_not_clear_the_alarm() -> None:
    """A panel set to summer heats hot water, not the house: the flame or the flow of a draw,
    and of the two minutes after it, is no sign that heating works."""
    state, now = run(HeatSignState(), COLD, 0.0, 31 * MINUTE)
    hot_water = replace(COLD, dhw=True, flame=True, flow=60.0)
    state = follow_heat_sign(state, hot_water, now)
    assert state.alarm
    after = replace(COLD, dhw=False, flame=True, flow=60.0)
    state = follow_heat_sign(state, after, now + DRAW_QUIET_S)
    assert state.alarm
    state = follow_heat_sign(state, after, now + DRAW_QUIET_S + STEP)
    assert state == HeatSignState(draw_at=now)  # after the window the flame clears it


def test_heating_not_commanded_raises_nothing() -> None:
    """Control's "off", a hand-back, a blocker, another controller or the boiler's own fault:
    heating is not commanded — nothing counts."""
    idle = replace(COLD, commanded=False)
    state, _ = run(HeatSignState(), idle, 0.0, 2 * PROOF_WINDOW_S)
    assert state == HeatSignState()


def test_a_raised_alarm_holds_until_a_sign_of_heat() -> None:
    """A boiler locked out stays so while no room calls, heating is off or hot water runs: the
    alarm holds through them, its count started again; only a sign of heat clears it."""
    state, now = run(HeatSignState(), COLD, 0.0, 31 * MINUTE)
    for pause in (
        replace(COLD, calling=False),
        replace(COLD, commanded=False),
        replace(COLD, flame=None, flow=None),
        replace(COLD, flow=50.0),
        replace(COLD, dhw=True),
    ):
        state = follow_heat_sign(state, pause, now)
        assert state.alarm, pause
        assert state.since is None, pause
        now += DRAW_QUIET_S + STEP
    state = follow_heat_sign(state, replace(COLD, calling=False, flame=True), now)
    assert not state.alarm


def test_a_clock_set_back_starts_the_count_again() -> None:
    state, _ = run(HeatSignState(), COLD, 10 * MINUTE, 20 * MINUTE)
    assert state.since == 10 * MINUTE
    state = follow_heat_sign(state, COLD, 5 * MINUTE)
    assert state.since == 5 * MINUTE
    later = follow_heat_sign(HeatSignState(draw_at=5 * MINUTE), COLD, 0.0)
    assert later.draw_at == 0.0  # a draw later than now counts as now
