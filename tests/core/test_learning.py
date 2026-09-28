"""Learning pauses for the zone algorithms."""

from __future__ import annotations

from custom_components.vtherm_smart_boiler.core.learning import (
    LearningConfig,
    LearningState,
    PauseCause,
    ZoneLearning,
    follow_resumes,
    plan_learning,
    release_all,
    rename_zone,
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


def test_a_resume_is_followed_until_the_flag_reads_on() -> None:
    """P41: SmartPI skips a thermostat it cannot find without an error, and keeps its flag for
    good — a resume is done only once the flag reads on, and is sent again until it does."""
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    result = plan(state, [zone("a", learning=False)], 12)
    assert result.resume == ("a",)
    assert "a" in result.state.resuming
    lost = plan(result.state, [zone("a", learning=False)], 12.5)
    assert lost.resume == ()  # not yet: give it a minute
    again = plan(lost.state, [zone("a", learning=False)], 13.5)
    assert again.resume == ("a",)  # still off a minute later: sent again
    done = plan(again.state, [zone("a", learning=True)], 14)
    assert done.state.resuming == {}


def test_a_released_zone_is_followed_after_control_stops() -> None:
    state = LearningState(paused={"a": 0.0}, last_toggle={"a": 0.0})
    released, zones = release_all(state, 2 * MIN)
    assert zones == ("a",)
    assert released.resuming == {"a": 2 * MIN}
    state, again = follow_resumes(released, {"a": False}, 4 * MIN, CONFIG)
    assert again == ("a",)
    state, again = follow_resumes(state, {"a": True}, 5 * MIN, CONFIG)
    assert (state.resuming, again) == ({}, ())


def test_a_zone_gone_for_a_day_is_no_longer_followed() -> None:
    state = LearningState(resuming={"a": 0.0})
    state, again = follow_resumes(state, {}, 60 * MIN, CONFIG)
    assert (state.resuming, again) == ({"a": 0.0}, ())  # not seen: kept, not sent
    state, _ = follow_resumes(state, {}, 24 * 60 * MIN + 1, CONFIG)
    assert state.resuming == {}


def test_a_pause_that_did_not_take_is_not_the_plugins() -> None:
    """P41: the flag still reads on a minute after the pause — SmartPI skipped it, or the user
    switched learning back on: the zone is not the plugin's to resume."""
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    early = plan(state, [zone("a", learning=True)], 0.5, dhw=True)
    assert "a" in early.state.paused
    later = plan(early.state, [zone("a", learning=True)], 1.5, dhw=True)
    assert "a" not in later.state.paused
    ended = plan(later.state, [zone("a", learning=True)], 12)
    assert ended.resume == ()


def test_learning_switched_off_by_the_user_before_a_pause_is_never_resumed() -> None:
    state = LearningState()
    for t in (0, 5, 15, 30, 60):
        result = plan(state, [zone("a", learning=False)], t, dhw=t < 30)
        assert (result.pause, result.resume) == ((), ())
        state = result.state


def test_the_flow_must_come_back_within_a_tolerance_either_way() -> None:
    """S20: after hot water the flow must be back near its setpoint — from above too."""
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    hot = plan(state, [zone("a", learning=False)], 12, flow=52.0, setpoint=45.0)
    assert hot.resume == ()
    near = plan(state, [zone("a", learning=False)], 12, flow=47.0, setpoint=45.0)
    assert near.resume == ("a",)


def test_learning_resumes_after_the_longest_pause_whatever_the_flow() -> None:
    """S20, P-89: a boiler that cannot reach the setpoint must not keep learning paused for
    ever — an hour after the draw ended (provisional, K4), whatever the flow."""
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    state = plan(state, [zone("a", learning=False)], 30, flow=30.0, setpoint=45.0).state
    waiting = plan(state, [zone("a", learning=False)], 89, flow=30.0, setpoint=45.0)
    assert waiting.resume == ()  # 59 min after the draw ended at 30
    late = plan(waiting.state, [zone("a", learning=False)], 90, flow=30.0, setpoint=45.0)
    assert late.resume == ("a",)


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


def test_with_heating_off_a_hot_water_pause_ends_without_waiting_for_the_flow() -> None:
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    waiting = plan_learning(
        state, [zone("a", learning=False)], False, 30.0, 45.0, 12 * MIN, CONFIG, heating=True
    )
    assert waiting.resume == ()  # heating: the water must come back first
    off = plan_learning(
        state, [zone("a", learning=False)], False, 30.0, 45.0, 12 * MIN, CONFIG, heating=False
    )
    assert off.resume == ("a",)  # heating off: the flow will not come back, nothing to wait for


def test_a_resume_that_never_takes_is_given_up_after_a_day() -> None:
    """C15: a resume whose flag keeps reading off is sent again every minute, but for a day at
    most after the first one — then it is no longer followed (the user may have switched
    learning off on purpose)."""
    state = LearningState(paused={"a": 0.0}, last_toggle={"a": 0.0})
    state, _ = release_all(state, 0.0)
    assert state.resume_since == {"a": 0.0}
    sent = 0
    for minute in range(1, 24 * 60):
        state, again = follow_resumes(state, {"a": False}, minute * MIN, CONFIG)
        sent += len(again)
    assert sent == 24 * 60 - 1  # every minute
    assert state.resume_since == {"a": 0.0}  # a resend does not move the first resume
    state, again = follow_resumes(state, {"a": False}, 24 * 60 * MIN, CONFIG)
    assert (state.resuming, state.resume_since, again) == ({}, {}, ())


def test_a_resume_that_takes_is_forgotten_with_its_start() -> None:
    state, _ = release_all(LearningState(paused={"a": 0.0}), 0.0)
    state, again = follow_resumes(state, {"a": True}, MIN, CONFIG)
    assert (state.resuming, state.resume_since, again) == ({}, {}, ())


def test_a_resume_without_its_start_counts_from_its_last_send() -> None:
    """Negative: a resume stored before its start was kept (0.2.1) counts from the stored send."""
    state = LearningState(resuming={"a": 10 * MIN})
    state, _ = follow_resumes(state, {"a": False}, 24 * 60 * MIN, CONFIG)
    assert "a" in state.resuming
    state, again = follow_resumes(state, {"a": False}, 24 * 60 * MIN + 10 * MIN, CONFIG)
    assert (state.resuming, again) == ({}, ())


def test_a_resume_planned_by_a_step_keeps_its_start() -> None:
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    result = plan(state, [zone("a", learning=False)], 12)
    assert result.state.resume_since == {"a": 12 * MIN}
    again = plan(result.state, [zone("a", learning=False)], 14)
    assert again.resume == ("a",)
    assert again.state.resume_since == {"a": 12 * MIN}


# --- X4: learning pauses per cause (P-89, S-41) ------------------------------------------------


def test_the_flow_condition_applies_to_hot_water_only() -> None:
    """P-89: after foreign heat — or a water swing — learning resumes once the cause is gone
    and the minimum pause has passed, whatever the flow; after hot water the flow must be back
    first."""
    state = plan(LearningState(), [zone("a", foreign=True)], 0).state
    assert state.causes == {"a": (PauseCause.FOREIGN_HEAT,)}
    early = plan(state, [zone("a", learning=False)], 5, flow=30.0, setpoint=45.0)
    assert early.resume == ()  # the minimum pause
    done = plan(state, [zone("a", learning=False)], 10, flow=30.0, setpoint=45.0)
    assert done.resume == ("a",)
    assert done.state.causes == {}
    swing = plan(LearningState(), [zone("a")], 0, setpoint=35.0).state
    swing = plan(swing, [zone("a")], 1, setpoint=45.0, flow=40.0).state
    assert swing.causes == {"a": (PauseCause.WATER_SWING,)}
    after = plan(swing, [zone("a", learning=False)], 40, flow=30.0, setpoint=45.0)
    assert after.resume == ("a",)  # the swing is out of its window: no flow condition
    hot = plan(LearningState(), [zone("a")], 0, dhw=True).state
    cold = plan(hot, [zone("a", learning=False)], 12, flow=30.0, setpoint=45.0)
    assert cold.resume == ()


def test_the_hot_water_flow_wait_is_capped_an_hour_after_the_draw_ended() -> None:
    """A draw of 50 min, then the flow stays low: learning resumes 60 min after the draw ended
    — not 60 min after the pause began."""
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    for minute in range(1, 50):
        state = plan(state, [zone("a", learning=False)], minute, dhw=True, flow=30.0).state
    ended = 50
    for minute in range(ended, ended + 60):
        result = plan(state, [zone("a", learning=False)], minute, flow=30.0, setpoint=45.0)
        assert result.resume == (), minute
        state = result.state
    assert state.dhw_ended == {"a": ended * MIN}
    late = plan(state, [zone("a", learning=False)], ended + 60, flow=30.0, setpoint=45.0)
    assert late.resume == ("a",)
    assert late.state.dhw_ended == {}


def test_a_new_draw_during_the_flow_wait_starts_its_hour_again() -> None:
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    state = plan(state, [zone("a", learning=False)], 10, flow=30.0).state  # the draw ended
    state = plan(state, [zone("a", learning=False)], 40, dhw=True, flow=30.0).state
    assert state.dhw_ended == {}
    state = plan(state, [zone("a", learning=False)], 45, flow=30.0).state
    assert plan(state, [zone("a", learning=False)], 70, flow=30.0).resume == ()
    assert plan(state, [zone("a", learning=False)], 105, flow=30.0).resume == ("a",)


def test_hot_water_among_the_causes_keeps_its_flow_condition() -> None:
    """A pause for foreign heat that also saw a draw ends by the hot-water rules."""
    state = plan(LearningState(), [zone("a", foreign=True)], 0).state
    state = plan(state, [zone("a", learning=False, foreign=True)], 5, dhw=True).state
    assert set(state.causes["a"]) == {PauseCause.FOREIGN_HEAT, PauseCause.DHW}
    cold = plan(state, [zone("a", learning=False)], 20, flow=30.0, setpoint=45.0)
    assert cold.resume == ()


def test_unknown_causes_after_a_restart_are_treated_as_hot_water() -> None:
    """Negative: a pause stored without its causes (0.2.1, a damaged store) waits for the flow,
    at most an hour from the first step seen without a cause."""
    state = LearningState(paused={"a": 0.0}, last_toggle={"a": 0.0})
    cold = plan(state, [zone("a", learning=False)], 20, flow=30.0, setpoint=45.0)
    assert cold.resume == ()
    assert cold.state.dhw_ended == {"a": 20 * MIN}
    late = plan(cold.state, [zone("a", learning=False)], 80, flow=30.0, setpoint=45.0)
    assert late.resume == ("a",)


def test_a_short_draw_still_pauses_smartpi() -> None:
    """S-41: every draw pauses the zones calling for heat, however short and on a combi boiler
    too — they get no heat meanwhile."""
    result = plan(LearningState(), [zone("a")], 0, dhw=True)
    assert result.pause == ("a",)
    assert result.state.causes == {"a": (PauseCause.DHW,)}
    after = plan(result.state, [zone("a", learning=False)], 1, flow=45.0)
    assert "a" in after.state.paused  # the minimum pause holds


def test_a_release_forgets_the_causes() -> None:
    state = plan(LearningState(), [zone("a")], 0, dhw=True).state
    state = plan(state, [zone("a", learning=False)], 5, flow=30.0).state
    released, zones = release_all(state, 6 * MIN)
    assert zones == ("a",)
    assert released.causes == {}
    assert released.dhw_ended == {}


def test_a_renamed_zone_keeps_what_the_plugin_holds_for_it() -> None:
    """P-19: a VT climate renamed in Home Assistant keeps its pause, its resume, their causes
    and times under the new entity ID — the plugin still resumes what it paused itself."""
    state = LearningState(
        paused={"climate.a": 1.0, "climate.b": 2.0},
        setpoints=((1.0, 45.0),),
        last_toggle={"climate.a": 1.0, "climate.b": 2.0},
        resuming={"climate.a": 3.0},
        resume_since={"climate.a": 3.0},
        causes={"climate.a": (PauseCause.DHW,), "climate.b": ()},
        dhw_ended={"climate.a": 4.0},
    )
    renamed = rename_zone(state, "climate.a", "climate.c")
    assert renamed.paused == {"climate.c": 1.0, "climate.b": 2.0}
    assert renamed.last_toggle == {"climate.c": 1.0, "climate.b": 2.0}
    assert renamed.resuming == {"climate.c": 3.0}
    assert renamed.resume_since == {"climate.c": 3.0}
    assert renamed.causes == {"climate.c": (PauseCause.DHW,), "climate.b": ()}
    assert renamed.dhw_ended == {"climate.c": 4.0}
    assert renamed.setpoints == state.setpoints


def test_renaming_a_zone_the_plugin_holds_nothing_for_changes_nothing() -> None:
    """Negative: an entity the learning state does not name, or no state at all."""
    state = LearningState(paused={"climate.a": 1.0}, last_toggle={"climate.a": 1.0})
    assert rename_zone(state, "climate.x", "climate.y") is state
    empty = LearningState()
    assert rename_zone(empty, "climate.a", "climate.c") is empty
