"""Learning pauses for the zone algorithms."""

from __future__ import annotations

from custom_components.vtherm_smart_boiler.core.learning import (
    LearningConfig,
    LearningState,
    PauseCause,
    ZoneLearning,
    plan_learning,
    release_all,
)

MIN = 60.0
CONFIG = LearningConfig(min_pause_s=10 * MIN, swing_k=5.0, swing_window_s=30 * MIN)


def zone(
    zid: str = "a", learning: bool | None = True, valve_open: bool = True, foreign: bool = False
):
    return ZoneLearning(zid, learning, valve_open, foreign)


def plan(state, zones, t, dhw=False, flow=45.0, setpoint=45.0):
    return plan_learning(state, zones, dhw, flow, setpoint, t * MIN, CONFIG)


def test_dhw_pauses_only_zones_with_an_open_valve() -> None:
    result = plan(LearningState(), [zone("a"), zone("b", valve_open=False)], 0, dhw=True)
    assert result.pause == ("a",)
    assert result.causes["a"] == (PauseCause.DHW,)
    assert result.causes["b"] == ()


def test_resume_after_the_minimum_pause_and_once_the_flow_is_back() -> None:
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    early = plan(state, [zone("a", learning=False)], 5, dhw=False)
    assert early.resume == ()
    cold = plan(state, [zone("a", learning=False)], 12, dhw=False, flow=30.0, setpoint=45.0)
    assert cold.resume == ()  # the flow has not recovered yet
    done = plan(state, [zone("a", learning=False)], 12, dhw=False, flow=44.0, setpoint=45.0)
    assert done.resume == ("a",)
    assert done.state.paused == {}


def test_the_users_own_pause_is_never_touched() -> None:
    result = plan(LearningState(), [zone("a", learning=False)], 0, dhw=True)
    assert result.pause == ()
    later = plan(result.state, [zone("a", learning=False)], 20, dhw=False)
    assert later.resume == ()


def test_foreign_heat_pauses_its_zone() -> None:
    result = plan(LearningState(), [zone("a", foreign=True), zone("b")], 0)
    assert result.pause == ("a",)
    assert result.causes["a"] == (PauseCause.FOREIGN_HEAT,)


def test_a_water_swing_pauses_every_zone() -> None:
    state = plan(LearningState(), [zone("a")], 0, setpoint=35.0).state
    result = plan(state, [zone("a"), zone("b")], 10, setpoint=45.0, flow=40.0)
    assert set(result.pause) == {"a", "b"}
    assert PauseCause.WATER_SWING in result.causes["a"]


def test_no_toggling_faster_than_the_minimum_pause() -> None:
    state = plan(LearningState(), [zone("a", foreign=True)], 0).state
    state = plan(state, [zone("a", learning=False)], 11).state  # resumed
    again = plan(state, [zone("a", foreign=True)], 12)
    assert again.pause == ()  # toggled only a minute ago


def test_unknown_flag_is_not_paused_but_resumed_when_ours() -> None:
    assert plan(LearningState(), [zone("a", learning=None)], 0, dhw=True).pause == ()
    state = LearningState(paused={"a": 0.0}, last_toggle={"a": 0.0})
    assert plan(state, [zone("a", learning=None)], 20).resume == ("a",)


def test_release_all_resumes_what_the_plugin_paused() -> None:
    state = LearningState(paused={"a": 0.0, "b": 60.0})
    released, zones = release_all(state, 2 * MIN)
    assert set(zones) == {"a", "b"}
    assert released.paused == {}


def test_a_release_counts_as_a_toggle() -> None:
    state = plan(LearningState(), [zone("a", foreign=True)], 0).state
    released, _ = release_all(state, 11 * MIN)
    again = plan(released, [zone("a", foreign=True)], 12)
    assert again.pause == ()  # resumed only a minute ago
    assert plan(released, [zone("a", foreign=True)], 22).pause == ("a",)


def test_pauses_can_be_switched_off() -> None:
    config = LearningConfig(
        pause_on_dhw=False, pause_on_foreign_heat=False, pause_on_water_swing=False
    )
    result = plan_learning(
        LearningState(), [zone("a", foreign=True)], True, 45.0, 45.0, 0.0, config
    )
    assert result.pause == ()
