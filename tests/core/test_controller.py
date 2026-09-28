"""The controller state machine: precedence, hand-back, data problems, heating decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import replace
from itertools import pairwise

import pytest

from custom_components.vtherm_smart_boiler.core.controller import (
    _LIMIT_REASON,
    CORRECTION_DAY_K,
    CORRECTION_LIMIT_S,
    CORRECTION_MAX_K,
    FROST_ALARM_S,
    HA_STARTING,
    MAX_STEP_S,
    OUTAGE_BACK_S,
    OUTAGE_LOST_S,
    OUTAGE_WINDOW_S,
    BoilerCommand,
    ControlConfig,
    ControlDecision,
    ControlInputs,
    ControlMode,
    ControlState,
    OutageWindow,
    Reason,
    bad_time,
    clock_due,
    clock_start,
    decide,
    fallback_setpoint,
    follow_outage,
    reset_correction,
)
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.demand import DemandConfig
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits, FrostConfig, LimitCode
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.zone_watch import GRACE_S, RECOGNITION_S

MIN = 60.0
CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.0)
CONFIG = ControlConfig(curve=CURVE, ramp_k_per_min=None)


def zone(t: float, **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    kw.setdefault("temperature", 20.0)
    kw.setdefault("target", 21.0)
    kw.setdefault("valve_open", 0.6)
    return ZoneState("z", reported_at=t, **kw)


def inputs(t: float, **kw) -> ControlInputs:
    kw.setdefault("enabled", True)
    kw.setdefault("flame", False)
    kw.setdefault("dhw", False)
    kw.setdefault("outdoor_sensor", 5.0)
    kw.setdefault("zones", (zone(t),))
    return ControlInputs(now=t, **kw)


def run(steps, config: ControlConfig = CONFIG, state: ControlState | None = None):
    state = state or ControlState()
    decisions = []
    for step in steps:
        state, decision = decide(state, step, config)
        decisions.append(decision)
    return state, decisions


def stepped(start: float, stop: float, step: float = 10.0) -> list[float]:
    """Control's steps: every ``step`` seconds from ``start`` up to, not including, ``stop``."""
    return [start + i * step for i in range(round((stop - start) / step))]


def test_disabled_writes_nothing_and_hands_back_nothing() -> None:
    _state, [decision] = run([inputs(0.0, enabled=False)])
    assert decision.mode is ControlMode.DISABLED
    assert decision.command is None
    assert not decision.hand_back


def test_heating_follows_the_curve() -> None:
    state, [decision] = run([inputs(0.0)])
    assert decision.mode is ControlMode.HEATING
    assert decision.command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert Reason.DEMAND in decision.reasons
    assert Reason.OUTDOOR_SENSOR in decision.reasons
    assert state.controlling


def test_switching_off_hands_back_once() -> None:
    _state, decisions = run([inputs(0.0), inputs(30.0, enabled=False), inputs(60.0, enabled=False)])
    assert [d.hand_back for d in decisions] == [False, True, False]
    assert decisions[1].command is None


def test_missing_precondition_hands_back() -> None:
    _state, decisions = run([inputs(0.0), inputs(30.0, blockers=("no_hand_back",))])
    assert decisions[1].mode is ControlMode.NOT_ALLOWED
    assert decisions[1].hand_back


def test_alarm_hand_back_is_latched_until_a_new_session() -> None:
    state, decisions = run(
        [
            inputs(0.0),
            inputs(30.0, hand_back_alarms=("pressure_low",)),
            inputs(60.0),  # the alarm cleared: still handed back
            inputs(90.0, blockers=("x",)),
            inputs(120.0),
        ]
    )
    assert decisions[1].hand_back
    # P-48: the latch comes before a blocker — the status still lists the blocker.
    assert [d.mode for d in decisions[1:]] == [ControlMode.HANDED_BACK] * 4
    assert state.latched_by == ("pressure_low",)  # the cause stays with the latch
    # Control being off does not clear it (e.g. a switch not restored after a restart): only the
    # user switching control off and on again, which starts a new session.
    state, decisions = run([inputs(150.0, enabled=False), inputs(180.0)], state=state)
    assert decisions[1].mode is ControlMode.HANDED_BACK
    assert state.latched_by == ("pressure_low",)
    _state, decisions = run([inputs(210.0)], state=ControlState())
    assert decisions[0].mode is ControlMode.HEATING


def test_an_alarm_during_a_blocker_still_latches() -> None:
    """T-49 (P-48): a step with a transient blocker and an alarm set to hand back latches, with
    the alarm as its cause; the next step, the blocker gone, stays handed back."""
    state, decisions = run(
        [
            inputs(0.0),
            inputs(30.0, blockers=("vt_central_boiler_unknown",), hand_back_alarms=("x",)),
            inputs(60.0),
        ]
    )
    assert decisions[1].hand_back
    assert decisions[1].mode is ControlMode.HANDED_BACK
    assert state.latched
    assert state.latched_by == ("x",)
    assert decisions[2].mode is ControlMode.HANDED_BACK
    assert decisions[2].command is None


def test_a_clip_holds_the_comfort_correction() -> None:
    """While the boiler holds the water lower than asked (its own limit), the correction does
    not rise: a clip is never learned (X1, principle 13)."""
    config = ControlConfig(curve=CURVE, ramp_k_per_min=None, decision_interval_s=60.0)
    for clipped, rises in ((True, False), (False, True)):
        state = ControlState()
        t = 0.0
        while t <= 7200.0:
            short = zone(t, temperature=19.0, valve_open=1.0)
            step = inputs(t, zones=(short,), clipped=clipped, flame=True)
            state, _ = decide(state, step, config)
            t += 10.0
        assert (state.correction > 0.0) is rises


def test_vt_modes_act_through_the_zones() -> None:
    """VT applies its central mode to the zones; the plugin sees only their demand. With every
    zone stopped there is no demand: heating off and no hand-back — control goes on, and frost
    protection still watches: a stopped zone VT keeps closed is flagged, not heated (decision 4);
    one whose valve VT holds open (asleep) is heated."""

    def stopped(t: float, **kw: float) -> tuple[ZoneState, ...]:
        kw.setdefault("valve_open", 0.0)
        return (zone(t, heating_enabled=False, device_active=False, **kw),)

    _state, decisions = run(
        [
            inputs(0.0),
            inputs(10.0, zones=stopped(10.0)),
            inputs(20.0, zones=stopped(20.0, temperature=4.0)),
            inputs(30.0, zones=stopped(30.0, temperature=4.0, valve_open=1.0)),
        ]
    )
    assert [d.hand_back for d in decisions] == [False] * 4
    assert decisions[1].mode is ControlMode.IDLE
    assert decisions[1].command is not None
    assert not decisions[1].command.ch_enable
    assert decisions[2].mode is ControlMode.IDLE  # closed: frost heat could not reach it
    assert decisions[2].frost_closed == ("z",)
    assert decisions[3].mode is ControlMode.FROST
    assert decisions[3].command is not None
    assert decisions[3].command.ch_enable
    assert decisions[3].frost_closed == ()


def test_stale_boiler_link_writes_nothing_and_keeps_control() -> None:
    """A stale step writes nothing; a stale spell far short of the loss (X2) keeps control, and
    the next fresh step writes at once — the minute's wait is only for a link that was lost."""
    state, decisions = run([inputs(0.0), inputs(30.0, boiler_link=False), inputs(60.0)])
    assert decisions[1].mode is ControlMode.WAITING_DATA
    assert decisions[1].command is None
    assert not decisions[1].hand_back
    assert not any(d.link_lost for d in decisions)
    assert decisions[2].command is not None  # decided again at once
    assert state.controlling


def test_control_takes_the_boiler_only_with_a_read_back_value() -> None:
    """P-21 (V5): on a gateway path control takes the boiler only once the read-back that shows
    a hand-back got through holds a value — until then nothing is written, waiting for data;
    then control takes the boiler."""
    state, decisions = run(
        [inputs(0.0, read_back_known=False), inputs(10.0, read_back_known=False), inputs(20.0)]
    )
    assert [d.mode for d in decisions[:2]] == [ControlMode.WAITING_DATA] * 2
    assert all(d.command is None and not d.hand_back for d in decisions[:2])
    assert decisions[0].reasons == (Reason.READ_BACK_UNKNOWN,)
    assert decisions[2].command is not None
    assert state.controlling


def test_a_read_back_lost_while_controlling_is_no_hand_back_by_itself() -> None:
    """P-21, negative: once controlling, a read-back that turns unknown is not judged here —
    control goes on; the boiler link (flame, flow) decides a hand-back."""
    _state, decisions = run(
        [inputs(0.0), inputs(10.0, read_back_known=False), inputs(400.0, read_back_known=False)]
    )
    assert all(d.command is not None and not d.hand_back for d in decisions)
    config = replace(CONFIG, stale_hand_back_s=300.0)
    _state, decisions = run(
        [
            inputs(0.0),
            *(inputs(t, read_back_known=False, boiler_link=False) for t in stepped(10.0, 320.0)),
        ],
        config,
    )
    assert [d.hand_back for d in decisions].count(True) == 1  # the stale link's
    assert decisions[-1].hand_back
    assert Reason.BOILER_LINK_STALE in decisions[-1].reasons


def test_no_demand_is_idle() -> None:
    _state, [decision] = run([inputs(0.0, zones=(zone(0.0, valve_open=0.0),))])
    assert decision.mode is ControlMode.IDLE
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert Reason.NO_DEMAND in decision.reasons


def test_summer_and_winter_come_from_vt() -> None:
    """No summer switch of the plugin's own: a warm day with a zone calling heats; with VT's
    zones off it does not."""
    _state, [calling] = run([inputs(0.0, outdoor_sensor=25.0)])
    assert calling.command is not None
    assert calling.command.ch_enable
    off = (zone(0.0, heating_enabled=False),)
    _state, [idle] = run([inputs(0.0, outdoor_sensor=25.0, zones=off)])
    assert idle.command is not None
    assert not idle.command.ch_enable


def test_missing_outdoor_temperature_uses_the_fallback_setpoint() -> None:
    """The last effective outdoor temperature holds for three hours; then the curve's design
    point — never too little heat, the valves keep the rooms from overheating."""
    steps = [
        inputs(0.0),
        inputs(2 * 3600.0, outdoor_sensor=None),
        inputs(3 * 3600.0 + 60.0, outdoor_sensor=None),
    ]
    config = replace(CONFIG, decision_interval_s=60.0)
    _state, decisions = run(steps, config)
    assert Reason.OUTDOOR_HELD in decisions[1].reasons
    assert decisions[1].command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert decisions[2].mode is ControlMode.FALLBACK
    assert decisions[2].command == BoilerCommand(True, pytest.approx(CURVE.design_flow))
    assert fallback_setpoint(replace(CONFIG, fallback_setpoint=48.0)) == 48.0


def test_the_ramp_moves_at_every_step() -> None:
    """1 K a minute spread over the steps, not one jump per decision."""
    config = replace(CONFIG, ramp_k_per_min=1.0, decision_interval_s=300.0)
    steps = [inputs(0.0, outdoor_sensor=15.0)] + [
        inputs(t * 10.0, outdoor_sensor=-10.0) for t in range(30, 37)
    ]
    _state, decisions = run(steps, config)
    first = decisions[0].command.setpoint
    raised = [d.command.setpoint - first for d in decisions[1:]]
    # The colder curve arrives with the decision at 300 s; from there 1/6 K every 10 s step.
    assert raised == pytest.approx([k / 6.0 + 5.0 for k in range(7)], abs=1e-6)


def test_weather_entity_stands_in_for_the_sensor() -> None:
    _state, [decision] = run([inputs(0.0, outdoor_sensor=None, outdoor_weather=0.0)])
    assert Reason.OUTDOOR_WEATHER in decision.reasons
    assert decision.command == BoilerCommand(True, pytest.approx(CURVE.flow(0.0)))


def test_the_water_temperature_waits_for_the_interval_heating_does_not() -> None:
    _state, decisions = run(
        [
            inputs(0.0),
            inputs(60.0, outdoor_sensor=-5.0, zones=(zone(60.0, valve_open=0.0),)),
            inputs(300.0, outdoor_sensor=-5.0, zones=(zone(300.0, valve_open=0.0),)),
        ]
    )
    first, early, due = (d.command for d in decisions)
    assert first is not None
    assert early is not None
    assert due is not None
    assert not early.ch_enable  # the zones are satisfied: heating off at once
    assert early.setpoint == first.setpoint  # the colder curve waits for the next decision
    assert due.setpoint > first.setpoint


def test_frost_does_not_wait_for_the_interval() -> None:
    _state, decisions = run(
        [
            inputs(0.0, zones=(zone(0.0, valve_open=0.0),)),
            inputs(30.0, zones=(zone(30.0, temperature=4.0, valve_open=0.04),)),
        ]
    )
    assert decisions[1].mode is ControlMode.FROST


def test_ramp_limits_the_rise() -> None:
    config = replace(CONFIG, ramp_k_per_min=1.0, decision_interval_s=60.0)
    _state, decisions = run(
        [inputs(0.0, outdoor_sensor=15.0), inputs(60.0, outdoor_sensor=-10.0)], config
    )
    first = decisions[0].command
    second = decisions[1].command
    assert first is not None
    assert second is not None
    assert second.setpoint == pytest.approx(first.setpoint + 1.0)
    assert Reason.RAMP in decisions[1].reasons


def test_a_lowered_cap_applies_at_once() -> None:
    config = replace(CONFIG, ramp_k_per_min=0.1, decision_interval_s=60.0)
    state, decisions = run([inputs(0.0, outdoor_sensor=-10.0)], config)
    capped = replace(config, circuit_max=35.0)
    state, decisions = run([inputs(60.0, outdoor_sensor=-10.0)], capped, state)
    assert decisions[0].command.setpoint == 35.0
    assert Reason.LIMIT_CIRCUIT_MAX in decisions[0].reasons


def test_limits_apply_to_the_curve() -> None:
    config = replace(CONFIG, limits=FlowLimits(hard_min=30.0, hard_max=50.0))
    _state, [mild] = run([inputs(0.0, outdoor_sensor=15.0)], config)
    assert mild.command.setpoint == 30.0
    assert Reason.LIMIT_HARD_MIN in mild.reasons


@pytest.mark.parametrize("code", list(LimitCode))
def test_every_limit_is_shown_with_a_reason(code: LimitCode) -> None:
    assert code in _LIMIT_REASON


def test_a_fixed_circuit_keeps_the_flow_above_its_temperature() -> None:
    """A mixing valve set to 45 °C needs at least that from the boiler, whatever the curve."""
    config = replace(CONFIG, circuit_floor=45.0)
    _state, [mild] = run([inputs(0.0, outdoor_sensor=15.0)], config)
    assert mild.command.setpoint == 45.0
    assert Reason.LIMIT_FIXED_CIRCUIT in mild.reasons


@pytest.mark.parametrize("kwargs", [{"decision_interval_s": 0.0}, {"ramp_k_per_min": 0.0}])
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        replace(CONFIG, **kwargs)


WATER = replace(CONFIG, decision_interval_s=60.0)


def short(t: float, zone_id: str = "z", **kw: float) -> ZoneState:
    """A zone whose valve is fully open and whose room is still a kelvin short."""
    kw.setdefault("valve_open", 1.0)
    return ZoneState(zone_id, 20.0, 21.0, True, reported_at=t, **kw)


def satisfied(t: float, zone_id: str = "z", **kw: float) -> ZoneState:
    kw.setdefault("valve_open", 0.3)
    return ZoneState(zone_id, 21.0, 21.0, True, reported_at=t, **kw)


def minutes(start: float, count: int, zones, **kw):
    """A step a minute; the flame burns (heat flows, S-24) unless told otherwise."""
    kw.setdefault("flame", True)
    return [inputs(start + m * 60.0, zones=zones(start + m * 60.0), **kw) for m in range(count)]


def test_comfort_correction_rises_1k_per_30_min_while_heat_flows_up_to_3k() -> None:
    state, decisions = run(minutes(0.0, 31, lambda t: (short(t),)), WATER)
    assert state.correction == pytest.approx(1.0)
    assert decisions[-1].command.setpoint == pytest.approx(CURVE.flow(5.0) + 1.0)
    assert Reason.COMFORT_CORRECTION in decisions[-1].reasons
    state, _ = run(minutes(1860.0, 150, lambda t: (short(t),)), WATER, state)
    assert state.correction == 3.0  # the band is firm


def test_comfort_correction_does_not_grow_while_no_heat_flows() -> None:
    state, _ = run(minutes(0.0, 31, lambda t: (short(t),), dhw=True), WATER)
    assert state.correction == 0.0


def test_comfort_correction_falls_twice_as_fast() -> None:
    state, _ = run(minutes(0.0, 91, lambda t: (short(t),)), WATER)
    assert state.correction == pytest.approx(3.0)
    state, _ = run(minutes(5460.0, 30, lambda t: (satisfied(t),)), WATER, state)
    assert state.correction == pytest.approx(1.0)  # 2 K in 30 minutes


def test_a_zone_without_opening_data_does_not_block_the_fall() -> None:
    state, _ = run(minutes(0.0, 31, lambda t: (short(t),)), WATER)

    def zones(t: float) -> tuple[ZoneState, ...]:
        # an over_climate zone without valve regulation: no opening at all
        return (satisfied(t), ZoneState("b", 21.0, 21.0, True, reported_at=t))

    state, _ = run(minutes(1860.0, 16, zones), WATER, state)
    assert state.correction == pytest.approx(0.0)


def test_no_rise_while_another_zone_is_too_warm() -> None:
    """A zone more than 1 K over its setpoint while it takes heat (S-08: its valve open)."""

    def zones(t: float) -> tuple[ZoneState, ...]:
        return (short(t), ZoneState("b", 22.5, 21.0, True, reported_at=t, valve_open=0.3))

    state, _ = run(minutes(0.0, 31, zones), WATER)
    assert state.correction == 0.0


def test_comfort_correction_resets_at_hand_back() -> None:
    state, _ = run(minutes(0.0, 31, lambda t: (short(t),)), WATER)
    assert state.correction > 0.0
    state, _ = run([inputs(1900.0, enabled=False)], WATER, state)
    assert state.correction == 0.0


def test_comfort_correction_at_its_limit_for_hours_is_reported() -> None:
    state, decisions = run(minutes(0.0, 91, lambda t: (short(t),)), WATER)
    assert not decisions[-1].correction_at_limit
    _state, decisions = run(minutes(5460.0, 181, lambda t: (short(t),)), WATER, state)
    assert decisions[-1].correction_at_limit  # 3 K for three hours: the curve is probably low


def test_a_zone_capped_by_vt_counts_as_saturated() -> None:
    """VT's max_on_percent below full: that cap is as open as the zone gets."""
    capped = replace(WATER)
    state, _ = run(
        minutes(0.0, 31, lambda t: (short(t, valve_open=0.8, max_on_percent=0.8),)), capped
    )
    assert state.correction == pytest.approx(1.0)


def test_comfort_correction_can_be_off() -> None:
    state, _ = run(
        minutes(0.0, 31, lambda t: (short(t),)), replace(WATER, comfort_correction=False)
    )
    assert state.correction == 0.0


def test_long_data_loss_hands_back_once_and_resumes() -> None:
    """Stale from 30 s: lost once stale steps cover five minutes (330 s), handed back once and
    shown so; the data back at 400 s, control resumes only after a minute of it without a break
    (X2), with the window cleared. Negative: without a stale hand-back time, never."""
    config = replace(CONFIG, stale_hand_back_s=300.0)
    steps = [
        inputs(0.0),
        *(inputs(t, boiler_link=False) for t in stepped(30.0, 400.0)),
        *(inputs(t) for t in stepped(400.0, 470.0)),
    ]
    state, decisions = run(steps, config)
    at = {step.now: decision for step, decision in zip(steps, decisions, strict=True)}
    assert [step.now for step, d in zip(steps, decisions, strict=True) if d.hand_back] == [330.0]
    assert at[330.0].mode is ControlMode.HANDED_BACK
    assert Reason.BOILER_LINK_STALE in at[330.0].reasons
    assert at[330.0].link_lost
    assert not at[320.0].link_lost
    for t in (340.0, 400.0, 450.0):  # stays shown until the link is back
        assert at[t].mode is ControlMode.HANDED_BACK
        assert at[t].command is None
        assert at[t].link_lost
    assert at[460.0].mode is ControlMode.HEATING  # a minute of fresh data
    assert not at[460.0].link_lost
    assert state.controlling
    assert state.link.checks == ()  # the window starts afresh
    never = replace(CONFIG, stale_hand_back_s=None)
    _state, decisions = run(
        [inputs(0.0), *(inputs(t, boiler_link=False) for t in stepped(30.0, 1200.0))], never
    )
    assert not any(d.hand_back or d.link_lost for d in decisions)


def test_heating_follows_the_zones_at_every_step_both_ways() -> None:
    """VT decides whether to heat: off as soon as the zones are satisfied — even mid-burn — and
    on again as soon as one calls, with no minimum burn, pause or budget, and no waiting for the
    next water-temperature decision."""

    def idle(t: float) -> tuple[ZoneState, ...]:
        return (zone(t, valve_open=0.0),)

    _state, decisions = run(
        [
            inputs(0.0, flame=False),
            inputs(10.0, flame=True, zones=idle(10.0)),
            inputs(20.0, flame=False),
            inputs(30.0, flame=True, zones=idle(30.0)),
            inputs(40.0, flame=False),
        ],
        replace(CONFIG, decision_interval_s=300.0),
    )
    assert [d.command.ch_enable for d in decisions] == [True, False, True, False, True]
    assert [d.mode for d in decisions] == [ControlMode.HEATING, ControlMode.IDLE] * 2 + [
        ControlMode.HEATING
    ]


def test_a_short_cycling_boiler_is_never_held_off() -> None:
    """An old boiler with a high minimum output cycles a lot on its own: while the zones call,
    heating stays on, whatever the starts per hour."""
    steps = [inputs(t * 10.0, flame=t % 4 < 2) for t in range(360)]  # an hour of 20 s burns
    _state, decisions = run(steps)
    assert all(d.command is not None and d.command.ch_enable for d in decisions)


def test_frost_heating_that_does_not_warm_the_zone_is_reported_not_stopped() -> None:
    cold = (zone(0.0, temperature=3.0),)
    steps = [inputs(t * 600.0, zones=(zone(t * 600.0, temperature=3.0),)) for t in range(13)]
    steps[0] = inputs(0.0, zones=cold)
    _state, decisions = run(steps)
    assert all(d.mode is ControlMode.FROST for d in decisions)
    assert all(d.command is not None and d.command.ch_enable for d in decisions)
    assert not decisions[11].frost_stuck  # under two hours
    assert decisions[12].frost_stuck  # two hours on and the room no warmer


def test_frost_heating_that_warms_the_zone_is_not_reported() -> None:
    steps = [
        inputs(t * 600.0, zones=(zone(t * 600.0, temperature=3.0 + 0.1 * t),)) for t in range(13)
    ]
    _state, decisions = run(steps)
    assert decisions[12].mode is ControlMode.FROST
    assert not decisions[12].frost_stuck


HOUR = 3600.0


def test_a_steady_room_is_not_an_unknown_one() -> None:
    """T2: VT reports when its room sensor last changed (the sensor's ``last_updated``), and a
    steady room does not change for hours. With VT off in summer that must stay "no heat" —
    not "zones unknown", which heats against VT — as long as VT itself reports."""
    now = 10 * HOUR
    off = zone(now, heating_enabled=False, valve_open=0.0, temperature_at=now - 3 * HOUR)
    _state, [decision] = run([inputs(now, zones=(off,))])
    assert decision.mode is ControlMode.IDLE
    assert Reason.ZONES_UNKNOWN not in decision.reasons
    assert decision.command is not None
    assert decision.command.ch_enable is False


def test_frost_protection_sees_a_steady_cold_room() -> None:
    """T2: a room steady at 4 °C for hours is still a room at 4 °C."""
    now = 10 * HOUR
    cold = zone(
        now, heating_enabled=False, valve_open=None, temperature=4.0, temperature_at=now - 3 * HOUR
    )
    _state, [decision] = run([inputs(now, zones=(cold,))])
    assert decision.mode is ControlMode.FROST
    assert decision.command is not None
    assert decision.command.ch_enable is True


def test_a_clock_jumping_forward_does_not_raise_the_correction_at_once() -> None:
    """C9: an hour's jump of the wall clock counted as an hour of heat flow — +2 K of comfort
    correction in one step, past the ramp. A step counts for a minute at most."""
    cold = zone(0.0, valve_open=1.0, temperature=19.0, target=21.0)  # short, fully open
    burning = {"flame": True}
    state, _ = run([inputs(0.0, zones=(cold,), **burning), inputs(10.0, zones=(cold,), **burning)])
    jumped = zone(3610.0, valve_open=1.0, temperature=19.0, target=21.0)
    state, _ = run([inputs(3610.0, zones=(jumped,), **burning)], state=state)
    assert 0.0 < state.correction <= 0.1  # 70 s of heat flow, not an hour


# --- V4, R8 (C9): a wall clock set back holds nothing up ---------------------------------------


def test_a_clock_set_back_does_not_hold_up_the_stale_hand_back() -> None:
    """The boiler's data went stale, then the wall clock was set back an hour: the stale samples
    later than the clock go, and the stale hand-back comes five minutes after the set-back, not
    an hour and five (X2's window). Negative: a clock that only moves forward keeps the samples
    — the hand-back five minutes after the first stale step."""
    config = replace(CONFIG, stale_hand_back_s=300.0)
    state, _ = run([inputs(10000.0), inputs(10030.0, boiler_link=False)], config)
    assert state.link.checks[-1] == (10030.0, True)
    back = [inputs(t, boiler_link=False) for t in stepped(6430.0, 6740.0)]  # an hour back
    state, decisions = run(back, config, state)
    assert [step.now for step, d in zip(back, decisions, strict=True) if d.hand_back] == [6730.0]
    assert Reason.BOILER_LINK_STALE in decisions[-1].reasons
    state, _ = run([inputs(0.0), inputs(30.0, boiler_link=False)], config)
    forward = [inputs(t, boiler_link=False) for t in stepped(40.0, 340.0)]
    state, decisions = run(forward, config, state)
    assert state.link.checks[1] == (30.0, True)  # not reset
    assert [step.now for step, d in zip(forward, decisions, strict=True) if d.hand_back] == [330.0]


def test_a_clock_set_back_makes_the_water_decision_due() -> None:
    """A water decision stamped later than now — the wall clock was set back — is due now, not
    once the clock has caught up. Negative: within the interval, without a set-back, the water
    temperature waits (as ``test_the_water_temperature_waits_for_the_interval…``)."""
    state, [first] = run([inputs(10000.0)])
    state, [early] = run([inputs(10060.0, outdoor_sensor=-5.0)], state=state)
    assert first.command is not None
    assert early.command is not None
    assert early.command.setpoint == first.command.setpoint  # waits for the interval
    state, [back] = run([inputs(9000.0, outdoor_sensor=-5.0)], state=state)
    assert back.command is not None
    assert back.command.setpoint > first.command.setpoint  # decided again at once
    assert state.decided_at == 9000.0


def test_a_clock_set_back_does_not_move_the_comfort_correction() -> None:
    """The correction's fall counts the time since the last decision; with the clock set back
    that time would be negative, and the fall a rise. It counts as none."""
    state = replace(ControlState(), correction=2.0)
    state, _ = run([inputs(10000.0, zones=(satisfied(10000.0),))], WATER, state)
    assert state.correction == 2.0
    state, _ = run([inputs(8200.0, zones=(satisfied(8200.0),))], WATER, state)  # 30 min back
    assert state.decided_at == 8200.0  # decided again
    assert state.correction == 2.0  # neither risen by the negative time nor fallen


@pytest.mark.parametrize(
    ("since", "now", "expected"),
    [(None, 100.0, 100.0), (50.0, 100.0, 50.0), (100.0, 100.0, 100.0), (500.0, 100.0, 100.0)],
    ids=["none", "earlier", "same", "later"],
)
def test_a_start_later_than_now_counts_as_now(
    since: float | None, now: float, expected: float
) -> None:
    assert clock_start(since, now) == expected


@pytest.mark.parametrize(
    ("at", "expected"),
    [(160.0, 160.0), (100.0, 100.0), (40.0, 40.0), (161.0, 100.0), (3700.0, 100.0)],
    ids=["a_minute_ahead", "now", "past", "past_the_longest", "an_hour_ahead"],
)
def test_a_moment_further_ahead_than_planned_is_due_now(at: float, expected: float) -> None:
    assert clock_due(at, 100.0, 60.0) == expected


# --- V6: a lasting outage judged over a window (the plugin's monitor; X2's link reuses it) -----


def checks(window: OutageWindow, moments: Iterable[tuple[float, bool]]) -> OutageWindow:
    """The window after a check at each moment: (time, bad)."""
    for t, bad in moments:
        window = follow_outage(window, t, bad)
    return window


def failing(start: float, stop: float, step: float = 30.0) -> list[tuple[float, bool]]:
    """A failed check every ``step`` seconds from ``start`` up to, not including, ``stop``."""
    count = round((stop - start) / step)
    return [(start + i * step, True) for i in range(count)]


def test_the_outage_values() -> None:
    """Five minutes (the user's answer I) within ten; back after a minute (provisional, K4)."""
    assert (OUTAGE_LOST_S, OUTAGE_WINDOW_S, OUTAGE_BACK_S, MAX_STEP_S) == (300, 600, 60, 60)


def test_a_check_counts_until_the_next_one_at_most_a_minute() -> None:
    assert bad_time(((0.0, True), (45.0, False)), 100.0) == 45.0
    assert bad_time(((0.0, True),), 20.0) == 20.0  # the last one until now
    assert bad_time(((0.0, True),), 100.0) == MAX_STEP_S  # nothing since: a minute at most
    assert bad_time(((0.0, False), (30.0, True)), 50.0) == 20.0
    assert bad_time(((0.0, True), (30.0, True)), 620.0) == 70.0  # only what is in the window


def test_failed_checks_covering_five_minutes_within_ten_are_a_loss() -> None:
    """Checks every 30 s, all failed: 290 s of them is no loss yet, 300 s is — judged at any
    moment, not only at a check (control steps between the monitor's refreshes)."""
    window = checks(OutageWindow(), failing(0.0, 300.0))  # the last at 270 s
    assert not window.lost
    assert not follow_outage(window, 290.0).lost
    lost = follow_outage(window, 300.0)
    assert lost.lost
    assert lost.lost_from == 0.0


def test_a_flapping_outage_is_a_loss_by_its_window() -> None:
    """Nine checks in ten fail, every 30 s: no run of failures reaches five minutes (270 s at
    most), yet together they cover five minutes within ten — a loss, from the first failure."""
    window = OutageWindow()
    lost_at = None
    for i in range(40):
        window = follow_outage(window, 30.0 * i, i % 10 != 9)
        if window.lost and lost_at is None:
            lost_at = 30.0 * i
    assert lost_at == 330.0
    assert window.lost_from == 0.0


def test_one_failed_check_every_five_minutes_is_never_a_loss() -> None:
    window = OutageWindow()
    for i in range(240):  # two hours, a check every 30 s
        window = follow_outage(window, 30.0 * i, i % 10 == 0)
        assert not window.lost


def test_a_loss_ends_after_a_minute_without_a_failure_and_clears_the_window() -> None:
    """A single good check does not end a loss; a minute of good ones without a break does, and
    the window starts afresh: one failure afterwards is no loss, though the last ten minutes held
    five of them."""
    window = checks(OutageWindow(), failing(0.0, 330.0))
    assert window.lost
    window = checks(window, [(330.0, False), (360.0, True)])  # a single good check
    assert window.lost
    window = checks(window, [(390.0, False), (420.0, False)])
    assert follow_outage(window, 449.0).lost  # good for 59 s
    back = follow_outage(window, 450.0, False)
    assert not back.lost
    assert back.checks == ()
    assert back.lost_from is None
    assert back.good_since == 390.0
    again = checks(back, [(480.0, True)])
    assert not again.lost
    assert not follow_outage(again, 600.0).lost


def test_a_loss_ends_a_minute_after_the_last_good_check_without_a_new_one() -> None:
    """The monitor refreshes rarely where polling is off: a good check, then a minute without a
    failure, ends the loss."""
    window = checks(OutageWindow(), [*failing(0.0, 330.0), (330.0, False)])
    assert follow_outage(window, 389.0).lost
    assert not follow_outage(window, 390.0).lost


def test_no_checks_are_no_loss() -> None:
    """Missing input: no check yet (just after a start) counts as nothing failed."""
    assert bad_time((), 100.0) == 0.0
    assert follow_outage(OutageWindow(), 1e9) == OutageWindow()
    assert not follow_outage(OutageWindow(), 0.0, False).lost
    assert not follow_outage(OutageWindow(), 0.0, True).lost


def test_a_clock_set_back_does_not_stretch_the_window() -> None:
    """A check earlier than the last one means the wall clock was set back: the later checks go.
    A moment taken just before the last check is judged at that check."""
    window = checks(OutageWindow(), failing(10000.0, 10270.0))  # 240 s of failures
    back = follow_outage(window, 6400.0, True)  # an hour back
    assert back.checks == ((6400.0, True),)
    assert not follow_outage(back, 6430.0, True).lost
    assert follow_outage(window, 10200.0) == follow_outage(window, 10240.0)


def test_a_loss_starts_at_its_first_failure_in_the_window() -> None:
    """A failure long before does not count as the start of the loss."""
    moments = [(0.0, True), (30.0, False), *failing(700.0, 1030.0)]
    window = checks(OutageWindow(), moments)
    assert window.lost
    assert window.lost_from == 700.0
    assert window.checks[0][0] >= 1000.0 - OUTAGE_WINDOW_S - MAX_STEP_S  # old checks go


# --- X2: the boiler link judged over a window (P-08; T-26; Open after R6 #8) -------------------


def linked(start: float, stop: float, fresh: Callable[[float], bool], **kw) -> list[ControlInputs]:
    """A step every 10 s from ``start`` up to, not including, ``stop``; the link fresh at the
    steps where ``fresh(t)``."""
    return [inputs(t, boiler_link=fresh(t), **kw) for t in stepped(start, stop)]


def flapping(t: float) -> bool:
    """Fresh for one step in every 290 s: no stale run ever reaches five minutes."""
    return t % 290.0 == 0.0


def test_a_flapping_boiler_link_still_hands_back() -> None:
    """T-26 (P-08): controlling, the link fresh for one step in every 290 s for an hour. Its
    stale runs are 280 s at most, yet together they cover five minutes within ten: control hands
    back once, as soon as they do (the first stale step at 10 s; 280 s, the fresh step, then 20
    s more), says the link is lost, and stays handed back while the link keeps flapping."""
    steps = [inputs(0.0), *linked(10.0, HOUR, flapping)]
    state, decisions = run(steps)
    backs = [step.now for step, d in zip(steps, decisions, strict=True) if d.hand_back]
    assert backs == [320.0]
    first = [step.now for step in steps].index(320.0)
    assert decisions[first].link_lost
    assert decisions[first].mode is ControlMode.HANDED_BACK
    assert Reason.BOILER_LINK_STALE in decisions[first].reasons
    assert not any(d.link_lost for d in decisions[:first])
    later = decisions[first:]
    assert all(d.link_lost and d.command is None for d in later)  # no resume while it flaps
    assert all(d.mode is ControlMode.HANDED_BACK for d in later)
    assert not state.controlling


def test_one_stale_step_every_five_minutes_never_hands_back() -> None:
    """Negative: one stale step every 300 s covers 20 s within ten minutes — never lost, never
    handed back, and each fresh step writes at once (no write is held back before a loss)."""
    steps = [inputs(0.0), *linked(10.0, 2 * HOUR, lambda t: t % 300.0 != 0.0)]
    state, decisions = run(steps)
    assert not any(d.hand_back or d.link_lost for d in decisions)
    for step, decision in zip(steps, decisions, strict=True):
        assert (decision.command is None) is (not step.boiler_link)
    assert state.controlling


def test_after_a_stale_hand_back_control_resumes_after_a_minute_of_fresh_data() -> None:
    """Flapping as in T-26: handed back, and no resume. Then fresh without a break: for 59 s
    still handed back, nothing written; at 60 s the link is back, its window cleared, and
    control takes the boiler again by itself. A single stale step later is no loss."""
    state, decisions = run([inputs(0.0), *linked(10.0, 1200.0, flapping)])
    assert [d.hand_back for d in decisions].count(True) == 1
    assert not state.controlling
    state, decisions = run(linked(1200.0, 1260.0, lambda _t: True), state=state)
    assert all(d.link_lost and d.command is None and not d.hand_back for d in decisions)
    assert all(d.mode is ControlMode.HANDED_BACK for d in decisions)
    state, [back] = run([inputs(1260.0)], state=state)
    assert not back.link_lost
    assert back.command is not None
    assert back.mode is ControlMode.HEATING
    assert state.controlling
    assert state.link == OutageWindow(good_since=1200.0)  # cleared
    steps = [inputs(1270.0, boiler_link=False), *linked(1280.0, 1500.0, lambda _t: True)]
    state, decisions = run(steps, state=state)
    assert not any(d.hand_back or d.link_lost for d in decisions)
    assert decisions[0].command is None  # nothing written at the stale step
    assert all(d.command is not None for d in decisions[1:])  # at once again
    assert state.controlling


def test_a_clock_set_back_does_not_stretch_the_link_window() -> None:
    """Negative (C9, Open after R6 #8; V6's rule for the link): stale for 270 s, then the wall
    clock set back an hour and stale for 270 s more. The samples later than now go, so the two
    spells never add up to a loss — the loss needs five stale minutes after the set-back; and no
    sample later than now stays in the window."""
    state, _ = run([inputs(10000.0), *linked(10010.0, 10280.0, lambda _t: False)])
    assert not state.link.lost
    steps = linked(6400.0, 6710.0, lambda _t: False)
    state, decisions = run(steps, state=state)
    assert all(t <= 6700.0 for t, _stale in state.link.checks)
    backs = [step.now for step, d in zip(steps, decisions, strict=True) if d.hand_back]
    assert backs == [6700.0]  # not at 6430 s, where the spells would sum to five minutes
    assert not any(d.link_lost for d in decisions[:-1])
    assert decisions[-1].link_lost


@pytest.mark.parametrize(
    "blocked",
    [
        {"enabled": False},
        {"blockers": ("monitoring_period",)},
        {"hand_back_alarms": ("pressure_low",)},
    ],
    ids=["switched_off", "blocker", "latch"],
)
def test_the_link_is_judged_whatever_holds_control(blocked: dict) -> None:
    """P-08: the link's samples are taken at every step, before control switched off, a blocker
    or a latch is looked at — the decision says the link is lost there too, after five stale
    minutes. Negative: the same steps with a fresh link, or only 290 s stale, say nothing."""
    stale = [inputs(t, boiler_link=False, **blocked) for t in stepped(0.0, 310.0)]
    _state, decisions = run(stale)
    assert not any(d.link_lost for d in decisions[:-1])
    assert decisions[-1].link_lost  # at 300 s
    assert all(d.command is None for d in decisions)
    fresh = [inputs(t, **blocked) for t in stepped(0.0, 310.0)]
    _state, decisions = run(fresh)
    assert not any(d.link_lost for d in decisions)
    _state, decisions = run(stale[:-1])
    assert not any(d.link_lost for d in decisions)


def test_the_link_is_judged_from_the_first_step_after_a_start() -> None:
    """After a restart the samples start empty: a link down from the start is lost 300 s after
    it — no sooner, whatever came before the restart. Missing input: no sample yet is no loss."""
    assert ControlState().link == OutageWindow()
    steps = [inputs(t, boiler_link=False) for t in stepped(0.0, 310.0)]
    _state, decisions = run(steps)
    assert [step.now for step, d in zip(steps, decisions, strict=True) if d.link_lost] == [300.0]
    assert decisions[0].mode is ControlMode.WAITING_DATA
    assert decisions[0].reasons == (Reason.BOILER_LINK_STALE,)
    assert not any(d.hand_back for d in decisions)  # never controlled: nothing to hand back


def restored(t: float) -> ControlState:
    """X3's restore after a restart: the last command held again; the samples start empty."""
    return ControlState(controlling=True, command=BoilerCommand(True, 45.0), last_step_at=t)


def test_a_link_not_yet_reported_never_turns_a_restore_into_a_hand_back() -> None:
    """X3's hook: while the restore waits, within the recognition period, for a link that has not
    reported since the start, that silence is not counted as stale — no loss, no hand-back,
    nothing written. Still silent when the wait ends (600 s), the time since the start counts as
    stale: lost at once, and the restored boiler is handed back."""
    waiting = [inputs(t, boiler_link=False, link_unreported=True) for t in stepped(0.0, 600.0)]
    state, decisions = run(waiting, state=restored(0.0))
    assert not any(d.hand_back or d.link_lost for d in decisions)
    assert all(d.command is None for d in decisions)
    assert state.controlling
    state, [end] = run([inputs(600.0, boiler_link=False)], state=state)
    assert end.link_lost
    assert end.hand_back
    assert Reason.BOILER_LINK_STALE in end.reasons


def test_a_link_that_reports_during_the_wait_starts_its_window_afresh() -> None:
    """X3's hook: the link reports 180 s after the start — the three minutes of waiting are
    forgotten: a stale spell afterwards needs five minutes of its own (from 190 s: lost at
    490 s, not at 310 s). Negative: the flag unset from the start, the same silence counts."""
    waiting = [inputs(t, boiler_link=False, link_unreported=True) for t in stepped(0.0, 180.0)]
    steps = [*waiting, inputs(180.0), *linked(190.0, 500.0, lambda _t: False)]
    _state, decisions = run(steps, state=restored(0.0))
    lost = [step.now for step, d in zip(steps, decisions, strict=True) if d.hand_back]
    assert lost == [490.0]
    counted = [
        *(inputs(t, boiler_link=False) for t in stepped(0.0, 180.0)),
        inputs(180.0),
        *linked(190.0, 500.0, lambda _t: False),
    ]
    _state, decisions = run(counted, state=restored(0.0))
    lost = [step.now for step, d in zip(counted, decisions, strict=True) if d.hand_back]
    assert lost == [310.0]


def test_the_stale_hand_back_time_is_the_link_threshold() -> None:
    """``stale_hand_back_s`` (300 s, decided) is how much stale time within the window makes the
    link lost; a shorter one hands back sooner. ``None`` never does (the negative in
    ``test_long_data_loss_hands_back_once_and_resumes``)."""
    assert ControlConfig(curve=CURVE).stale_hand_back_s == OUTAGE_LOST_S == 300.0
    steps = [inputs(0.0), *linked(10.0, 200.0, lambda _t: False)]
    _state, decisions = run(steps, replace(CONFIG, stale_hand_back_s=120.0))
    assert [step.now for step, d in zip(steps, decisions, strict=True) if d.hand_back] == [130.0]


# --- decision 3: the recognition period, each zone's grace, every zone unknown (X3) -----------

THERMOSTAT = replace(CONFIG, working_thermostat=True)
KEPT = BoilerCommand(True, 45.0)


def started(zone_id: str, t: float, **kw) -> ZoneState:
    """A zone VT has started (``is_ready`` true): heating and calling unless told otherwise."""
    kw.setdefault("heating_enabled", True)
    kw.setdefault("temperature", 20.0)
    kw.setdefault("target", 21.0)
    kw.setdefault("valve_open", 0.6)
    kw.setdefault("reported", True)
    return ZoneState(zone_id, reported_at=t, **kw)


def placeholder(zone_id: str, t: float, **kw) -> ZoneState:
    """What VT shows before it has started a thermostat: "off", not reported."""
    return ZoneState(zone_id, heating_enabled=False, reported=False, reported_at=t, **kw)


def away(zone_id: str) -> ZoneState:
    """Unavailable: no mode, nothing reported."""
    return ZoneState(zone_id)


def during(
    start: float, stop: float, zones: Callable[[float], tuple[ZoneState, ...]], **kw
) -> list[ControlInputs]:
    return [inputs(t, zones=zones(t), **kw) for t in stepped(start, stop)]


def test_no_new_decision_during_recognition_without_a_last_command() -> None:
    """At the start, the zones not reported yet and nothing held before: nothing is written."""
    for zones in (lambda t: (placeholder("a", t),), lambda _t: (away("a"),)):
        _state, decisions = run(during(0.0, 120.0, zones))
        assert all(d.mode is ControlMode.WAITING_DATA for d in decisions)
        assert all(d.command is None and not d.hand_back for d in decisions)
        assert all(d.reasons == (Reason.ZONES_RECOGNITION,) for d in decisions)


@pytest.mark.parametrize(
    ("kept", "mode"), [(KEPT, ControlMode.HEATING), (BoilerCommand(False, 45.0), ControlMode.IDLE)]
)
def test_a_kept_command_goes_on_during_recognition(kept: BoilerCommand, mode: ControlMode) -> None:
    """A command restored after a restart (on, 45 °C) is given at every step, with its
    keep-alives, until the recognition period ends; then control decides anew."""
    steps = [
        *during(0.0, 120.0, lambda t: (placeholder("a", t),), restored_command=kept),
        inputs(120.0, zones=(started("a", 120.0),), restored_command=kept),
    ]
    state, decisions = run(steps)
    assert all(d.command == kept for d in decisions[:-1])
    assert all(d.mode is mode for d in decisions[:-1])
    assert all(d.reasons == (Reason.ZONES_RECOGNITION,) for d in decisions[:-1])
    assert not any(d.hand_back for d in decisions)
    assert decisions[-1].command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert Reason.DEMAND in decisions[-1].reasons
    assert state.controlling


def test_recognition_ends_when_every_zone_reported_or_after_ten_minutes() -> None:
    def reporting(t: float) -> tuple[ZoneState, ...]:
        first = started("a", t) if t >= 30.0 else placeholder("a", t)
        second = started("b", t) if t >= 90.0 else placeholder("b", t)
        return first, second

    steps = during(0.0, 100.0, reporting)
    _state, decisions = run(steps)
    first = next(s.now for s, d in zip(steps, decisions, strict=True) if d.command is not None)
    assert first == 90.0

    def one_never(t: float) -> tuple[ZoneState, ...]:
        return started("a", t), placeholder("b", t, temperature=20.0)

    steps = during(0.0, RECOGNITION_S + 10.0, one_never)
    _state, decisions = run(steps)
    first = next(s.now for s, d in zip(steps, decisions, strict=True) if d.command is not None)
    assert first == RECOGNITION_S
    assert decisions[-1].mode is ControlMode.HEATING  # "a" calls; "b" is "off"


def test_a_vt_reload_starts_a_recognition_period() -> None:
    """Every zone unknown at once after having been reported: the command held before is kept,
    nothing new is decided until they have reported again."""

    def zones(t: float) -> tuple[ZoneState, ...]:
        if 100.0 <= t < 130.0:
            return away("a"), away("b")
        if 130.0 <= t < 150.0:
            return placeholder("a", t), started("b", t, valve_open=0.0)
        return started("a", t), started("b", t, valve_open=0.0)

    steps = during(0.0, 170.0, zones, outdoor_sensor=5.0)
    steps[12:] = [replace(step, outdoor_sensor=-5.0) for step in steps[12:]]  # colder at 120 s
    _state, decisions = run(steps, replace(CONFIG, decision_interval_s=10.0))
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    held = at[90.0].command
    assert held == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    for t in (100.0, 120.0, 140.0):
        assert at[t].command == held  # kept: the colder outdoor temperature is not decided on
        assert at[t].reasons == (Reason.ZONES_RECOGNITION,)
    assert at[150.0].command == BoilerCommand(True, pytest.approx(CURVE.flow(-5.0)))
    assert not any(d.hand_back for d in decisions)


def test_a_zone_unknown_for_less_than_ten_minutes_keeps_its_last_answer() -> None:
    """ "a" called, then went unavailable: it still calls 9 min 50 s later and drops out at
    10 min, when the known zone, not calling, decides."""
    lost = 10.0

    def zones(t: float) -> tuple[ZoneState, ...]:
        first = started("a", t) if t < lost else away("a")
        return first, started("b", t, valve_open=0.0)

    steps = during(0.0, lost + GRACE_S + 10.0, zones)
    _state, decisions = run(steps)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert at[lost + GRACE_S - 10.0].command.ch_enable
    assert at[lost + GRACE_S - 10.0].mode is ControlMode.HEATING
    assert not at[lost + GRACE_S].command.ch_enable
    assert Reason.NO_DEMAND in at[lost + GRACE_S].reasons


def test_a_zone_never_known_this_session_gets_no_grace() -> None:
    """ "a" never answered since the start: once the recognition period is over it counts for
    nothing, and the known zone decides at once."""
    steps = during(0.0, RECOGNITION_S + 10.0, lambda t: (away("a"), started("b", t, valve_open=0)))
    _state, decisions = run(steps)
    assert decisions[-1].mode is ControlMode.IDLE
    assert Reason.NO_DEMAND in decisions[-1].reasons


def gone_after(lost: float) -> Callable[[float], tuple[ZoneState, ...]]:
    """Two zones calling that go away one after the other, from ``lost``: each gets its grace."""

    def zones(t: float) -> tuple[ZoneState, ...]:
        return (
            started("a", t) if t < lost else away("a"),
            started("b", t) if t < lost + 10.0 else away("b"),
        )

    return zones


def test_every_zone_unknown_after_the_grace_hands_back_to_a_thermostat() -> None:
    """A working thermostat (a gateway with an OpenTherm thermostat declared): once every zone
    has dropped out, a safe hand-back at once, once, without a latch; the decision says every
    zone is unknown."""
    steps = during(0.0, 10.0 + 10.0 + GRACE_S + 30.0, gone_after(10.0))
    state, decisions = run(steps, THERMOSTAT)
    backs = [s.now for s, d in zip(steps, decisions, strict=True) if d.hand_back]
    assert backs == [20.0 + GRACE_S]
    after = [d for s, d in zip(steps, decisions, strict=True) if s.now >= 20.0 + GRACE_S]
    assert all(d.mode is ControlMode.HANDED_BACK and d.command is None for d in after)
    assert all(d.reasons == (Reason.ZONES_UNKNOWN,) for d in after)
    assert all(d.zones_unknown for d in after)
    assert not any(d.zones_unknown for d in decisions if d not in after)
    assert not state.latched


def test_every_zone_unknown_hands_back_to_the_boilers_own_room_controller_where_ticked() -> None:
    """The entity path with the tick "the boiler has its own room controller" (answer F): the
    same hand-back, to the boiler's own control. The recognition period at a VT reload leads
    there too: the command held meanwhile, the hand-back when it ends."""
    from custom_components.vtherm_smart_boiler.control_config import parse_control
    from custom_components.vtherm_smart_boiler.core.installation import (
        Boiler,
        BoilerClass,
        Circuit,
        CircuitControl,
        EmitterType,
        Installation,
        Zone,
    )

    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", CircuitControl.UNMIXED_SHARED),),
        (Zone("a", "main", EmitterType.RADIATOR),),
    )
    options = parse_control(
        {
            "write_path": "entity",
            "setpoint_entity": "number.flow",
            "write_type": "expiring",
            "topology": "virtual",
            "hand_back": "timeout",
            "confirmed_entity": "sensor.flow_setpoint",
            "curve": {"design_flow": 55},
            "own_room_controller": True,
        },
        installation,
        None,
    )
    config = replace(options.loop.control, ramp_k_per_min=None)
    assert config.working_thermostat

    def zones(t: float) -> tuple[ZoneState, ...]:
        return (started("a", t) if t < 10.0 else away("a"),)

    steps = during(0.0, 10.0 + RECOGNITION_S + 20.0, zones)
    state, decisions = run(steps, config)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert at[10.0 + RECOGNITION_S - 10.0].reasons == (Reason.ZONES_RECOGNITION,)
    assert at[10.0 + RECOGNITION_S - 10.0].command == at[0.0].command  # held meanwhile
    assert [s.now for s, d in zip(steps, decisions, strict=True) if d.hand_back] == [
        10.0 + RECOGNITION_S
    ]
    assert at[10.0 + RECOGNITION_S].mode is ControlMode.HANDED_BACK
    assert at[10.0 + RECOGNITION_S].reasons == (Reason.ZONES_UNKNOWN,)
    assert not state.latched


def test_every_zone_unknown_without_a_thermostat_means_the_usual_off() -> None:
    """No working thermostat (stand-alone; "device decides"; a value declared "own control"
    without the tick): the usual "off" — heating off, no hand-back — while every zone is unknown."""
    steps = during(0.0, 10.0 + 10.0 + GRACE_S + 30.0, gone_after(10.0))
    _state, decisions = run(steps, CONFIG)
    assert not any(d.hand_back for d in decisions)
    after = [d for s, d in zip(steps, decisions, strict=True) if s.now >= 20.0 + GRACE_S]
    assert all(d.mode is ControlMode.IDLE for d in after)
    assert all(d.command is not None and not d.command.ch_enable for d in after)
    assert all(Reason.ZONES_UNKNOWN in d.reasons for d in after)
    assert all(d.zones_unknown for d in after)


@pytest.mark.parametrize("config", [CONFIG, THERMOSTAT], ids=["off", "handed_back"])
def test_heating_resumes_when_a_zone_answers_again(config: ControlConfig) -> None:
    """Not a latch: the step a zone answers again, control decides on it once more."""
    back = 20.0 + GRACE_S + 60.0

    def zones(t: float) -> tuple[ZoneState, ...]:
        if t >= back:
            return started("a", t), away("b")
        return gone_after(10.0)(t)

    steps = during(0.0, back + 20.0, zones)
    state, decisions = run(steps, config)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert Reason.ZONES_UNKNOWN in at[back - 10.0].reasons
    assert at[back].mode is ControlMode.HEATING
    assert at[back].command.ch_enable
    assert not at[back].zones_unknown
    assert state.controlling


def test_no_design_flow_heating_with_every_zone_and_the_outdoor_temperature_unknown() -> None:
    """The outdoor temperature gone for four hours and every zone unknown: no heat — never the
    design flow (the fallback serves only with zones known), and never FALLBACK."""
    config = replace(CONFIG, decision_interval_s=60.0)

    def zones(t: float) -> tuple[ZoneState, ...]:
        return (started("a", t) if t < 10.0 else away("a"),)

    steps = [
        inputs(0.0, zones=zones(0.0)),
        *(
            inputs(t, zones=zones(t), outdoor_sensor=None)
            for t in [*stepped(10.0, 700.0), *range(700, 4 * 3600 + 1, 60)]
        ),
    ]
    _state, decisions = run(steps, config)
    later = decisions[70:]  # after the recognition period
    assert all(d.command is not None and not d.command.ch_enable for d in later)
    assert all(d.mode is ControlMode.IDLE for d in later)
    assert all(d.command.setpoint != pytest.approx(CURVE.design_flow) for d in decisions)
    assert later[-1].command.setpoint == pytest.approx(config.limits.hard_min)
    assert not any(d.mode is ControlMode.FALLBACK for d in decisions)


def test_a_fallback_decided_with_zones_known_ends_with_them() -> None:
    """The outdoor temperature long gone, the zones known and calling: the fallback heats at the
    design flow (decision 9). Every zone gone at once: the recognition period keeps that command;
    the step it ends, heating goes off with the water at the lowest temperature at once — the
    design flow is not kept a moment longer."""
    config = replace(CONFIG, decision_interval_s=300.0)
    lost = 4 * 3600.0

    def zones(t: float) -> tuple[ZoneState, ...]:
        return (started("a", t) if t < lost else away("a"),)

    steps = [
        inputs(0.0, zones=zones(0.0)),
        *(inputs(t, zones=zones(t), outdoor_sensor=None) for t in range(60, int(lost), 60)),
        *(
            inputs(t, zones=zones(t), outdoor_sensor=None)
            for t in stepped(lost, lost + RECOGNITION_S + 20.0)
        ),
    ]
    _state, decisions = run(steps, config)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert at[lost - 60.0].mode is ControlMode.FALLBACK
    assert at[lost - 60.0].command == BoilerCommand(True, pytest.approx(CURVE.design_flow))
    assert at[lost + 10.0].reasons == (Reason.ZONES_RECOGNITION,)  # held meanwhile
    end = at[lost + RECOGNITION_S]
    assert end.mode is ControlMode.IDLE
    assert end.command == BoilerCommand(False, pytest.approx(config.limits.hard_min))
    assert Reason.ZONES_UNKNOWN in end.reasons


def test_a_transient_loss_of_every_zone_does_not_start_the_boiler() -> None:
    """T-28 (S-03): summer, the only zone off; VT reloads it — unavailable for three steps, then
    its placeholder: the recognition period keeps "off", and no step switches heating on."""

    def zones(t: float) -> tuple[ZoneState, ...]:
        if 30.0 <= t < 60.0:
            return (away("a"),)
        if 60.0 <= t < 70.0:
            return (placeholder("a", t),)
        return (started("a", t, heating_enabled=False, valve_open=0.0),)

    steps = during(0.0, 120.0, zones, outdoor_sensor=25.0)
    _state, decisions = run(steps)
    assert all(d.command is not None and not d.command.ch_enable for d in decisions)
    assert not any(d.hand_back for d in decisions)
    assert decisions[-1].mode is ControlMode.IDLE


def test_an_off_zone_not_ready_means_no_demand() -> None:
    """T-17 (S-34): the only zone "off", VT not having started it, its temperature fresh: no
    demand once the recognition period is over — IDLE with ``NO_DEMAND``, not unknown."""
    steps = during(
        0.0, RECOGNITION_S + 10.0, lambda t: (placeholder("a", t, ready=False, temperature=19.0),)
    )
    _state, decisions = run(steps)
    assert decisions[0].mode is ControlMode.WAITING_DATA  # not known during the recognition
    assert decisions[-1].mode is ControlMode.IDLE
    assert Reason.NO_DEMAND in decisions[-1].reasons
    assert not decisions[-1].zones_unknown


def test_home_assistant_starting_keeps_a_restored_command_but_decides_nothing_new() -> None:
    """``ha_starting`` does not stop a command being kept or restored; the recognition period
    cannot end before Home Assistant runs. Without a command held, it blocks as before; another
    blocker stops the restore."""
    starting = (HA_STARTING,)
    steps = [
        *during(0.0, 700.0, lambda t: (started("a", t),), blockers=starting, restored_command=KEPT),
        inputs(700.0, zones=(started("a", 700.0),), restored_command=KEPT),
    ]
    _state, decisions = run(steps)
    assert all(d.command == KEPT for d in decisions[:-1])
    assert all(d.reasons == (Reason.ZONES_RECOGNITION,) for d in decisions[:-1])
    assert decisions[-1].command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    _state, decisions = run(during(0.0, 60.0, lambda t: (started("a", t),), blockers=starting))
    assert all(d.mode is ControlMode.NOT_ALLOWED and d.command is None for d in decisions)
    other = (HA_STARTING, "monitoring_period")
    _state, decisions = run(
        during(0.0, 60.0, lambda t: (started("a", t),), blockers=other, restored_command=KEPT)
    )
    assert all(d.mode is ControlMode.NOT_ALLOWED and d.command is None for d in decisions)
    assert not any(d.hand_back for d in decisions)


def test_a_restore_waits_for_its_target_and_the_link_writing_nothing() -> None:
    """Until the write target and the boiler link are there, the restore waits and nothing is
    written; a link not yet reported declares no loss (X2's hook). Once both are there, the
    restored command goes out at once."""
    zones = (placeholder("a", 0.0),)
    steps = [
        inputs(0.0, zones=zones, restored_command=KEPT, target_ready=False),
        inputs(10.0, zones=zones, restored_command=KEPT, boiler_link=False, link_unreported=True),
        inputs(20.0, zones=zones, restored_command=KEPT),
    ]
    state, decisions = run(steps)
    assert [d.command for d in decisions] == [None, None, KEPT]
    assert not any(d.hand_back or d.link_lost for d in decisions)
    assert state.controlling


def test_a_restore_not_given_by_the_end_of_the_recognition_writes_nothing_then() -> None:
    """The restore still waiting when the recognition period ends: that step writes nothing new
    — the owed hand-back goes first (the control unit); the step after decides."""
    steps = [
        *during(
            0.0,
            RECOGNITION_S + 10.0,
            lambda t: (placeholder("a", t),),
            restored_command=KEPT,
            target_ready=False,
        ),
        inputs(RECOGNITION_S + 10.0, zones=(started("a", RECOGNITION_S + 10.0),)),
    ]
    state, decisions = run(steps)
    assert all(d.command is None and not d.hand_back for d in decisions[:-1])
    assert decisions[-2].reasons == (Reason.ZONES_RECOGNITION,)
    assert decisions[-1].command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert state.controlling


def test_a_restore_whose_zones_all_report_at_once_decides_anew_at_once() -> None:
    """Every zone reported at the first step: the recognition period is over at once, and
    control decides anew — no step is lost waiting, nothing handed back first."""
    steps = [inputs(0.0, zones=(started("a", 0.0),), restored_command=KEPT)]
    state, [decision] = run(steps)
    assert decision.command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
    assert not decision.hand_back
    assert state.controlling


def test_frost_heats_during_the_recognition_for_zones_already_known() -> None:
    """Frost protection only adds heat, so it acts in the recognition period — for a zone VT
    has started; one it has not started does not count yet (provisional, K4)."""
    cold_known = during(
        0.0, 30.0, lambda t: (started("a", t, temperature=3.0), placeholder("b", t))
    )
    _state, decisions = run(cold_known)
    assert all(d.mode is ControlMode.FROST and d.command.ch_enable for d in decisions)
    cold_unknown = during(0.0, 30.0, lambda t: (placeholder("a", t, temperature=3.0),))
    _state, decisions = run(cold_unknown)
    assert all(d.command is None for d in decisions)


def test_every_criterion_without_data_ends_like_every_zone_unknown() -> None:
    """T-27 (P-14): a count of 0 and only a power threshold no zone can feed: after the
    recognition period, decision 3's end state — with a thermostat, the hand-back; without,
    the usual "off" — and the decision names the criterion. Every zone is known meanwhile."""
    demand = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    steps = during(0.0, 30.0, lambda t: (started("a", t),))
    for config, handed_back in ((CONFIG, False), (THERMOSTAT, True)):
        _state, decisions = run(steps, replace(config, demand=demand))
        last = decisions[-1]
        assert last.criteria_without_data == ("power",)
        assert not last.zones_unknown
        assert Reason.ZONES_UNKNOWN in last.reasons
        if handed_back:
            assert last.mode is ControlMode.HANDED_BACK
        else:
            assert last.mode is ControlMode.IDLE
            assert not last.command.ch_enable


def test_a_steady_unknown_zone_with_an_age_limit_set_counts_as_unknown() -> None:
    """Age counts only against a limit that is set: then a zone not heard of longer is unknown,
    and alone it leads to decision 3's end state."""
    stale = started("a", -10 * 3600.0)
    config = replace(CONFIG, zone_max_age_s=7200.0)
    steps = [inputs(t, zones=(stale,)) for t in stepped(0.0, RECOGNITION_S + 10.0)]
    _state, decisions = run(steps, config)
    assert decisions[0].reasons == (Reason.ZONES_RECOGNITION,)
    assert Reason.ZONES_UNKNOWN in decisions[-1].reasons
    assert decisions[-1].zones_unknown


# --- X4, decision 4: frost heat only where the emitter can take it; P-45 ------------------------


def cold(zone_id: str, t: float, temperature: float = 4.0, **kw) -> ZoneState:
    """A started zone below the frost limit; VT's published state as given."""
    return started(zone_id, t, temperature=temperature, **kw)


def closed(zone_id: str, t: float, temperature: float = 4.0, **kw) -> ZoneState:
    """A cold zone VT has off, as VT 10.4.0 shows it: opening 0, device off."""
    kw.setdefault("heating_enabled", False)
    return cold(zone_id, t, temperature, valve_open=0.0, device_active=False, **kw)


def test_a_cold_off_zone_with_its_valve_closed_gets_no_frost_heat() -> None:
    """A off, opening 0, device off, 4 °C; B heating at 20 °C, not calling: heating stays off,
    A is flagged as closed, and nothing says frost."""
    zones = (closed("a", 0.0), started("b", 0.0, target=19.0, valve_open=0.0))
    _state, [decision] = run([inputs(0.0, zones=zones)])
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert decision.mode is ControlMode.IDLE
    assert decision.frost_closed == ("a",)
    assert Reason.FROST not in decision.reasons


def test_a_call_below_the_threshold_still_gets_frost_heat() -> None:
    """Two zones must call; one at 4.5 °C does, with its valve open: no demand, but frost
    heat reaches it."""
    config = replace(CONFIG, demand=DemandConfig(count_threshold=2))
    zones = (cold("a", 0.0, 4.5, valve_open=0.6), started("b", 0.0, valve_open=0.0))
    _state, [decision] = run([inputs(0.0, zones=zones)], config)
    assert decision.mode is ControlMode.FROST
    assert decision.command is not None
    assert decision.command.ch_enable
    assert Reason.FROST in decision.reasons
    assert decision.frost_closed == ()


def test_a_sleeping_valve_open_at_100_gets_frost_heat() -> None:
    """VT's SLEEP shows the zone off, its device off and its duty 0, with the valve at 100 %."""
    asleep = cold(
        "a", 0.0, heating_enabled=False, valve_open=1.0, on_percent=0.0, device_active=False
    )
    _state, [decision] = run([inputs(0.0, zones=(asleep,))])
    assert decision.mode is ControlMode.FROST
    assert decision.command.ch_enable
    assert decision.frost_closed == ()


def test_open_and_closed_cold_zones_together() -> None:
    """Frost heats for the open zone (its device off, its valve a little open: no demand) and
    flags the closed one; frost ends once the open one is at 7 °C, the closed one still
    flagged."""

    def zones(t: float, open_at: float) -> tuple[ZoneState, ...]:
        return (
            cold("a", t, open_at, valve_open=0.04, device_active=False),
            closed("c", t),
        )

    steps = [
        inputs(0.0, zones=zones(0.0, 4.0)),
        inputs(10.0, zones=zones(10.0, 6.0)),  # between the limit and the release: goes on
        inputs(20.0, zones=zones(20.0, 7.0)),
    ]
    _state, decisions = run(steps)
    assert [d.mode for d in decisions] == [ControlMode.FROST] * 2 + [ControlMode.IDLE]
    assert [d.command.ch_enable for d in decisions] == [True, True, False]
    assert all(d.frost_closed == ("c",) for d in decisions)


def test_vt_closing_the_zone_mid_frost_ends_frost_heating() -> None:
    """Frost heats for A; VT switches A off (opening 0): frost heating ends at that step, and A
    is flagged."""
    steps = [
        inputs(0.0, zones=(cold("a", 0.0, valve_open=0.4, device_active=False),)),
        inputs(10.0, zones=(closed("a", 10.0),)),
    ]
    _state, decisions = run(steps)
    assert decisions[0].mode is ControlMode.FROST
    assert decisions[1].mode is ControlMode.IDLE
    assert not decisions[1].command.ch_enable
    assert decisions[1].frost_closed == ("a",)


def test_a_zone_whose_valve_state_cannot_be_read_is_heated_as_today() -> None:
    """Negative: no opening and no device state published → frost heats; an over_climate zone
    off with its device off and no opening → frost heats (its device may open on its own)."""
    for zone_state in (
        cold("a", 0.0, valve_open=None),
        cold("a", 0.0, heating_enabled=False, valve_open=None, device_active=False),
    ):
        _state, [decision] = run([inputs(0.0, zones=(zone_state,))])
        assert decision.mode is ControlMode.FROST
        assert decision.command.ch_enable
        assert decision.frost_closed == ()


def test_a_heating_zone_with_a_closed_valve_cannot_take_heat() -> None:
    """Heat mode with a closed valve (a frost preset below the limit, a TPI threshold): the
    mode alone never counts — no frost heat, flagged."""
    _state, [decision] = run([inputs(0.0, zones=(closed("a", 0.0, heating_enabled=True),))])
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert decision.frost_closed == ("a",)


def test_closes_when_off_makes_an_off_zone_closed() -> None:
    """The per-zone option on, the zone off, no opening published: flagged, no heat. Negative:
    the option off, the same zone is heated as today."""
    zone_state = cold("a", 0.0, heating_enabled=False, valve_open=None)
    option = replace(CONFIG, frost=FrostConfig(closes_when_off=frozenset({"a"})))
    _state, [decision] = run([inputs(0.0, zones=(zone_state,))], option)
    assert not decision.command.ch_enable
    assert decision.frost_closed == ("a",)
    _state, [decision] = run([inputs(0.0, zones=(zone_state,))])
    assert decision.mode is ControlMode.FROST


def test_the_picked_frost_zone_closed_is_flagged() -> None:
    """The picked zone off and closed at 4 °C, another zone — not watched — at 3 °C with its
    valve open: no frost heating, and the picked zone is flagged."""
    config = replace(CONFIG, frost=FrostConfig(zone="a"))
    zones = (closed("a", 0.0), cold("b", 0.0, 3.0, valve_open=0.04, device_active=False))
    _state, [decision] = run([inputs(0.0, zones=zones)], config)
    assert decision.mode is not ControlMode.FROST
    assert not decision.command.ch_enable
    assert decision.frost_closed == ("a",)


def test_no_zone_is_flagged_during_the_recognition_period() -> None:
    """The closed-zone flag waits for the recognition period (the zones report one by one);
    frost protection acts meanwhile for the zones already known that can take heat."""
    steps = [
        inputs(0.0, zones=(closed("a", 0.0), placeholder("b", 0.0))),
        inputs(10.0, zones=(closed("a", 10.0), started("b", 10.0, valve_open=0.0))),
    ]
    _state, decisions = run(steps)
    assert decisions[0].frost_closed == ()
    assert decisions[0].command is None
    assert decisions[1].frost_closed == ("a",)


def test_frost_since_resets_at_hand_back() -> None:
    """P-45: frost for 90 min, a hand-back (control switched off), a resume: "frost not
    warming" only two hours after the new start — not at once for time the plugin did not
    heat."""
    config = replace(CONFIG, decision_interval_s=600.0)

    def frosty(t: float, **kw) -> ControlInputs:
        return inputs(t, zones=(zone(t, temperature=3.0),), **kw)

    state, decisions = run([frosty(t) for t in range(0, 5401, 600)], config)
    assert not any(d.frost_stuck for d in decisions)
    state, [off] = run([frosty(6000.0, enabled=False)], config, state)
    assert off.hand_back
    assert state.frost_since is None
    assert not state.frost
    restart = 6600.0
    later = [frosty(restart + k * 600.0) for k in range(13)]
    _state, decisions = run(later, config, state)
    stuck = [step.now for step, d in zip(later, decisions, strict=True) if d.frost_stuck]
    assert stuck[0] == restart + FROST_ALARM_S


# --- X4, decision 5: VT's activation delay ---------------------------------------------------

DELAY = replace(CONFIG, activation_delay_s=120.0)


def calling(t: float) -> ControlInputs:
    return inputs(t)


def quiet(t: float) -> ControlInputs:
    return inputs(t, zones=(zone(t, valve_open=0.0),))


def heating_at(steps: list[ControlInputs], decisions: list[ControlDecision]) -> list[float]:
    return [
        step.now
        for step, d in zip(steps, decisions, strict=True)
        if d.command is not None and d.command.ch_enable
    ]


def test_no_delay_by_default() -> None:
    """Regression: 0 s, as VT's default — heating on at the step the zone calls."""
    assert ControlConfig(curve=CURVE).activation_delay_s == 0.0
    steps = [quiet(0.0), calling(10.0)]
    _state, decisions = run(steps)
    assert heating_at(steps, decisions) == [10.0]
    assert decisions[1].activation_at is None


def test_the_delay_counts_from_the_first_call() -> None:
    """120 s: off with the reason ``activation_delay`` through t0 + 110, on at t0 + 120; the
    decision says when heating will start."""
    t0 = 30.0
    steps = [quiet(0.0), quiet(10.0), quiet(20.0), *(calling(t) for t in stepped(t0, t0 + 130))]
    _state, decisions = run(steps, DELAY)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    for t in stepped(t0, t0 + 120):
        assert at[t].command is not None
        assert not at[t].command.ch_enable  # mid-session: the current "off" goes on
        assert at[t].mode is ControlMode.IDLE
        assert Reason.ACTIVATION_DELAY in at[t].reasons
        assert at[t].activation_at == pytest.approx(t0 + 120.0)
    assert at[t0 + 120.0].command.ch_enable
    assert at[t0 + 120.0].mode is ControlMode.HEATING
    assert Reason.ACTIVATION_DELAY not in at[t0 + 120.0].reasons
    assert at[t0 + 120.0].activation_at is None


def test_a_gap_neither_cancels_nor_restarts_the_wait() -> None:
    """A call at t0, none at t0 + 60, back at t0 + 70: on at t0 + 120, as VT's timer."""
    t0 = 10.0
    steps = [quiet(0.0)]
    for t in stepped(t0, t0 + 130):
        steps.append(quiet(t) if t == t0 + 60 else calling(t))
    _state, decisions = run(steps, DELAY)
    assert heating_at(steps, decisions)[0] == t0 + 120.0


def test_no_demand_at_the_end_drops_the_start() -> None:
    """The call gone when the wait ends: no start — and a later call waits anew."""
    t0 = 10.0
    steps = [quiet(0.0), *(calling(t) for t in stepped(t0, t0 + 60))]
    steps += [quiet(t) for t in stepped(t0 + 60, t0 + 200)]
    steps += [calling(t) for t in stepped(t0 + 200, t0 + 330)]
    state, decisions = run(steps, DELAY)
    assert heating_at(steps, decisions) == [t0 + 320.0]
    assert state.activation_s is None


def test_stopping_is_never_delayed() -> None:
    """Heating on: the call ends — off at that step."""
    steps = [calling(t) for t in stepped(0.0, 130.0)] + [quiet(130.0)]
    _state, decisions = run(steps, DELAY)
    assert decisions[-2].command.ch_enable
    assert not decisions[-1].command.ch_enable
    assert Reason.ACTIVATION_DELAY not in decisions[-1].reasons


def test_frost_heating_waits_too() -> None:
    """Frost heating waits the delay like any start; "frost not warming" counts from the real
    start."""
    t0 = 10.0

    def frosty(t: float) -> ControlInputs:
        return inputs(t, zones=(zone(t, temperature=3.0, valve_open=0.04),))

    steps = [quiet(0.0), *(frosty(t) for t in stepped(t0, t0 + 130))]
    state, decisions = run(steps, DELAY)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert at[t0 + 110.0].mode is ControlMode.IDLE
    assert Reason.ACTIVATION_DELAY in at[t0 + 110.0].reasons
    assert not at[t0 + 110.0].command.ch_enable
    assert at[t0 + 120.0].mode is ControlMode.FROST
    assert at[t0 + 120.0].command.ch_enable
    assert state.frost_since == t0 + 120.0
    start = t0 + 120.0
    later = [frosty(start + k * 600.0) for k in range(1, 13)]
    _state, decisions = run(later, DELAY, state)
    stuck = [step.now for step, d in zip(later, decisions, strict=True) if d.frost_stuck]
    assert stuck[0] == start + FROST_ALARM_S


@pytest.mark.parametrize(
    "stop",
    [{"blockers": ("x",)}, {"enabled": False}, {"hand_back_alarms": ("pressure_low",)}],
    ids=["blocker", "switched_off", "hand_back"],
)
def test_a_hand_back_a_blocker_or_switching_off_cancels_a_pending_start(stop: dict) -> None:
    """A pending start is dropped at the release; once control resumes, the wait counts anew —
    and, taking the boiler afresh, nothing is written meanwhile (a latch never resumes)."""
    t0 = 10.0
    steps = [quiet(0.0), *(calling(t) for t in stepped(t0, t0 + 60))]
    steps.append(replace(calling(t0 + 60), **stop))
    steps += [calling(t) for t in stepped(t0 + 70, t0 + 200)]
    state, decisions = run(steps, DELAY)
    at = {step.now: d for step, d in zip(steps, decisions, strict=True)}
    assert at[t0 + 60].command is None
    if "hand_back_alarms" in stop:
        assert state.latched
        assert state.activation_s is None
        assert heating_at(steps, decisions) == []
        return
    assert heating_at(steps, decisions)[0] == t0 + 190.0  # 120 s from t0 + 70
    assert all(at[t].command is None for t in stepped(t0 + 70, t0 + 190))


def test_no_delay_for_a_command_restored_after_a_restart() -> None:
    """Decision 5: no delay where the plugin controlled the boiler before a restart — the
    restored "on" goes out at once and stays; a restored "off" with the zones calling at the
    first step turns on at once too."""
    steps = [
        *during(0.0, 60.0, lambda t: (placeholder("a", t),), restored_command=KEPT),
        *during(60.0, 90.0, lambda t: (started("a", t),), restored_command=KEPT),
    ]
    _state, decisions = run(steps, DELAY)
    assert all(d.command is not None and d.command.ch_enable for d in decisions)
    off = BoilerCommand(False, 45.0)
    steps = [inputs(0.0, zones=(started("a", 0.0),), restored_command=off)]
    _state, [decision] = run(steps, DELAY)
    assert decision.command.ch_enable
    assert Reason.ACTIVATION_DELAY not in decision.reasons


def test_at_a_new_session_nothing_is_written_while_waiting() -> None:
    """Zones calling when control is switched on: nothing is written while the delay runs —
    ``controlling`` stays false, so switching off meanwhile owes nothing."""
    steps = [calling(t) for t in stepped(0.0, 130.0)]
    state, decisions = run(steps, DELAY)
    assert all(d.command is None for d in decisions[:-1])
    assert all(Reason.ACTIVATION_DELAY in d.reasons for d in decisions[:-1])
    assert all(d.mode is ControlMode.IDLE for d in decisions[:-1])
    assert decisions[-1].command.ch_enable
    state, decisions = run(steps[:6], DELAY)
    assert not state.controlling
    state, [off] = run([replace(calling(60.0), enabled=False)], DELAY, state)
    assert not off.hand_back


def test_without_a_call_off_is_written_at_once_at_a_new_session() -> None:
    """The delay holds only a start: with nothing calling, "off" goes out at the first step."""
    _state, [decision] = run([quiet(0.0)], DELAY)
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert decision.activation_at is None


def test_a_clock_jump_does_not_end_or_stretch_the_wait() -> None:
    """Each step counts at most a minute (``MAX_STEP_S``): an hour's jump forward leaves the
    wait running; a jump back counts nothing."""
    assert MAX_STEP_S == 60.0
    state, _ = run([quiet(0.0), calling(10.0)], DELAY)
    state, [jumped] = run([calling(3610.0)], DELAY, state)
    assert not jumped.command.ch_enable  # 60 s counted, not an hour
    assert state.activation_s == 60.0
    state, [back] = run([calling(1000.0)], DELAY, state)
    assert not back.command.ch_enable
    assert state.activation_s == 60.0  # nothing counted backwards
    state, decisions = run([calling(1000.0 + k * 10.0) for k in range(1, 7)], DELAY, state)
    assert decisions[-1].command.ch_enable  # 60 + 60 s


def test_a_stale_link_pauses_the_wait() -> None:
    """Stale steps write nothing and do not count: the wait goes on once the data is fresh."""
    t0 = 10.0
    steps = [quiet(0.0), calling(t0), calling(t0 + 10), calling(t0 + 20)]
    steps += [replace(calling(t), boiler_link=False) for t in stepped(t0 + 30, t0 + 100)]
    steps += [calling(t) for t in stepped(t0 + 100, t0 + 200)]
    _state, decisions = run(steps, DELAY)
    assert heating_at(steps, decisions)[0] == t0 + 190.0  # 20 s before, 100 s after


def test_the_delay_waits_after_the_recognition_period() -> None:
    """At a start nothing is decided until the zones have reported; the wait begins then."""
    reported = 60.0
    steps = during(
        0.0,
        reported + 130.0,
        lambda t: (started("a", t) if t >= reported else placeholder("a", t),),
    )
    _state, decisions = run(steps, DELAY)
    assert heating_at(steps, decisions)[0] == reported + 120.0


def test_the_activation_delay_is_bounded_as_in_vt() -> None:
    """0 to 600 s (VT 10.4.0); anything else is refused."""
    for bad in (-10.0, 700.0):
        with pytest.raises(ValueError, match="activation delay"):
            replace(CONFIG, activation_delay_s=bad)
    assert replace(CONFIG, activation_delay_s=600.0).activation_delay_s == 600.0


# --- X4: fallback shown only while heating (P-47), the fixed fallback (S-26) -------------------

LOST = 3 * 3600.0 + 60.0  # past the three hours the last outdoor temperature holds


def test_fallback_is_shown_only_while_heating() -> None:
    """P-47: without any outdoor temperature, FALLBACK only while heating is wanted; with the
    zones satisfied the mode is IDLE."""
    steps = [
        inputs(0.0),
        replace(quiet(LOST), outdoor_sensor=None),
        replace(calling(LOST + 10.0), outdoor_sensor=None),
    ]
    _state, decisions = run(steps, replace(CONFIG, decision_interval_s=60.0))
    assert decisions[1].mode is ControlMode.IDLE
    assert Reason.OUTDOOR_UNKNOWN in decisions[1].reasons
    assert decisions[2].mode is ControlMode.FALLBACK


def test_the_fixed_fallback_applies_after_the_three_hour_hold() -> None:
    """S-26, decision 9: 48 °C set, the outdoor temperature lost — the curve's last value until
    three hours have passed, then 48 °C."""
    config = replace(CONFIG, fallback_setpoint=48.0, decision_interval_s=60.0)
    steps = [inputs(0.0)]
    steps += [inputs(t, outdoor_sensor=None) for t in (3600.0, 3 * 3600.0, LOST)]
    _state, decisions = run(steps, config)
    for held in decisions[1:3]:
        assert held.command == BoilerCommand(True, pytest.approx(CURVE.flow(5.0)))
        assert Reason.OUTDOOR_HELD in held.reasons
    assert decisions[3].command == BoilerCommand(True, 48.0)
    assert decisions[3].mode is ControlMode.FALLBACK


# --- X4: the ramp skipped only for installation caps (S-23) ------------------------------------


def test_a_falling_weather_ceiling_ramps_down() -> None:
    """S-23: the outdoor sensor back after hours at the design flow drops the curve — and its
    ceiling — by 24 K: the setpoint comes down at the ramp's rate, 1 K a minute, not at once."""
    config = replace(
        CONFIG, ramp_k_per_min=1.0, decision_interval_s=60.0, outdoor_time_constant_s=1.0
    )
    steps = [inputs(0.0, outdoor_sensor=-15.0)]
    steps += [inputs(t, outdoor_sensor=9.0) for t in stepped(60.0, 180.0)]
    _state, decisions = run(steps, config)
    assert decisions[0].command.setpoint == pytest.approx(55.0)
    assert decisions[1].target == pytest.approx(31.0)  # the ceiling now 41: 14 K below 55
    setpoints = [d.command.setpoint for d in decisions]
    drops = [a - b for a, b in pairwise(setpoints)]
    assert drops[0] == pytest.approx(1.0)  # a minute since the first step
    assert all(drop == pytest.approx(1.0 / 6.0) for drop in drops[1:])
    assert all(Reason.RAMP in d.reasons for d in decisions[1:])


@pytest.mark.parametrize(
    "cap",
    [
        {"limits": FlowLimits(hard_min=25.0, hard_max=40.0)},
        {"circuit_max": 40.0},
        {"boiler_max": 40.0},
    ],
    ids=["hard_max", "circuit_max", "boiler_max"],
)
def test_an_installation_cap_applies_at_once(cap: dict) -> None:
    """A setpoint above an installation cap — the highest water temperature, the circuit's,
    the boiler's — meets it at once, unramped."""
    config = replace(CONFIG, ramp_k_per_min=0.1, decision_interval_s=60.0)
    state, _ = run([inputs(0.0, outdoor_sensor=-10.0)], config)
    _state, [decision] = run([inputs(60.0, outdoor_sensor=-10.0)], replace(config, **cap), state)
    assert decision.command.setpoint == 40.0
    assert Reason.RAMP not in decision.reasons


# --- X4: the comfort correction (principle 13; S-08, S-24, S-25, P-46, P-38) ------------------


def test_heat_flows_by_the_flame_when_known() -> None:
    """S-24: the flame off while heating is commanded — no rise; the flame unknown — the
    command decides; hot water — no rise."""
    for kw, rises in (
        ({"flame": False}, False),
        ({"flame": None}, True),
        ({"flame": True}, True),
        ({"flame": True, "dhw": True}, False),
        ({"flame": True, "dhw": None}, True),
    ):
        state, _ = run(minutes(0.0, 31, lambda t: (short(t),), **kw), WATER)
        assert (state.correction == pytest.approx(1.0)) is rises, kw
        assert (state.correction == 0.0) is not rises, kw


def test_only_zones_taking_heat_stop_the_rise() -> None:
    """S-08: a zone 2 K too warm whose valve VT closed (eco) takes no heat: the rise goes on.
    One taking heat — its valve open, or its device on — stops it."""
    for other, rises in (
        ({"valve_open": 0.0}, True),
        ({"valve_open": 0.04}, True),  # below 5 %: not taking heat
        ({"valve_open": 0.5}, False),
        ({"valve_open": None, "device_active": True}, False),
    ):

        def zones(t: float, other: dict = other) -> tuple[ZoneState, ...]:
            return (short(t), ZoneState("b", 23.0, 21.0, True, reported_at=t, **other))

        state, _ = run(minutes(0.0, 31, zones), WATER)
        assert (state.correction > 0.0) is rises, other


def test_the_correction_stays_while_a_cap_holds_the_setpoint() -> None:
    """T-48 (S-25): the circuit maximum equal to the curve and a saturated cold zone: 200 min
    of steps — no rise, and no "at limit". At its edge already, a cap pauses the "at limit"
    timer. Negative: without the cap the correction rises, and at its edge the timer runs."""
    capped = replace(WATER, circuit_max=CURVE.flow(5.0))
    state, decisions = run(minutes(0.0, 200, lambda t: (short(t),)), capped)
    assert state.correction == 0.0
    assert not any(d.correction_at_limit for d in decisions)
    edge = replace(ControlState(), correction=CORRECTION_MAX_K)
    state, decisions = run(minutes(0.0, 241, lambda t: (short(t),)), capped, edge)
    assert state.correction == CORRECTION_MAX_K
    assert not any(d.correction_at_limit for d in decisions)
    assert state.correction_limit_s == 0.0  # paused while the cap held
    state, decisions = run(minutes(0.0, 241, lambda t: (short(t),)), WATER, edge)
    assert decisions[-1].correction_at_limit
    assert state.correction_limit_s >= CORRECTION_LIMIT_S


def test_the_correction_does_not_rise_when_the_clock_goes_back() -> None:
    """T-18 (P-46): after a decision at 10000 s (correction 0) — one zone 1.5 K too warm,
    another at 8 °C — a step at 6400 s with the second zone at 4.5 °C (frost starts): the
    correction stays 0, and no reason says comfort correction."""

    def zones(t: float, second: float) -> tuple[ZoneState, ...]:
        return (
            ZoneState("a", 22.5, 21.0, True, reported_at=t, valve_open=0.3),
            ZoneState("b", second, 21.0, True, reported_at=t, valve_open=1.0),
        )

    state, _ = run([inputs(10000.0, zones=zones(10000.0, 8.0), flame=True)], WATER)
    assert state.correction == 0.0
    state, [decision] = run([inputs(6400.0, zones=zones(6400.0, 4.5), flame=True)], WATER, state)
    assert decision.mode is ControlMode.FROST
    assert state.correction == 0.0
    assert Reason.COMFORT_CORRECTION not in decision.reasons


def test_the_correction_rises_at_most_3_k_a_day() -> None:
    """Principle 13's daily rate (provisional, K4): 3 K up, back down, and no more rise within
    24 h of the first; a day later it rises again."""
    assert CORRECTION_DAY_K == 3.0
    state, _ = run(minutes(0.0, 91, lambda t: (short(t),)), WATER)
    assert state.correction == pytest.approx(3.0)
    state, _ = run(minutes(5460.0, 46, lambda t: (satisfied(t),)), WATER, state)
    assert state.correction == pytest.approx(0.0)
    state, _ = run(minutes(8220.0, 60, lambda t: (short(t),)), WATER, state)
    assert state.correction == 0.0  # the day's rise is spent
    next_day = 86400.0 + 5460.0
    state, _ = run(minutes(next_day, 30, lambda t: (short(t),)), WATER, state)
    assert state.correction == pytest.approx(1.0)


def test_the_correction_freezes_during_hot_water_and_foreign_heat() -> None:
    """Principle 13 (5): neither rise nor fall while hot water runs or foreign heat warms a
    zone. Negative: foreign heat unknown freezes nothing."""
    start = replace(ControlState(), correction=2.0)
    for kw in ({"dhw": True}, {"foreign_heat": True}):
        state, _ = run(minutes(0.0, 30, lambda t: (satisfied(t),), **kw), WATER, start)
        assert state.correction == 2.0, kw  # no fall
        state, _ = run(minutes(0.0, 30, lambda t: (short(t),), **kw), WATER, start)
        assert state.correction == 2.0, kw  # no rise
    for kw in ({"foreign_heat": None}, {"foreign_heat": False}):
        state, _ = run(minutes(0.0, 31, lambda t: (satisfied(t),), **kw), WATER, start)
        assert state.correction == pytest.approx(0.0), kw


def test_the_correction_does_not_rise_while_the_boiler_clips() -> None:
    """A clipped read-back holds the setpoint as a cap does: no rise, and at the edge the "at
    limit" timer pauses."""
    state, _ = run(minutes(0.0, 60, lambda t: (short(t),), clipped=True), WATER)
    assert state.correction == 0.0
    edge = replace(ControlState(), correction=3.0)
    _state, decisions = run(minutes(0.0, 241, lambda t: (short(t),), clipped=True), WATER, edge)
    assert not any(d.correction_at_limit for d in decisions)


def test_reset_correction_clears_the_value_and_its_timers() -> None:
    """Answer J: the pure reset — correction 0, the "at limit" timer and the heat counted
    cleared, the water decided anew at the next step; the rise may start again under its
    rules (the day's 3 K counts what rose before)."""
    state, _ = run(minutes(0.0, 61, lambda t: (short(t),)), WATER)
    assert state.correction == pytest.approx(2.0)
    reset = reset_correction(replace(state, correction_limit_s=100.0, heat_s=50.0))
    assert reset.correction == 0.0
    assert reset.correction_limit_s == 0.0
    assert reset.heat_s == 0.0
    assert reset.decided_at is None
    assert reset.rises == state.rises
    state, decisions = run(minutes(3660.0, 1, lambda t: (short(t),)), WATER, reset)
    assert Reason.COMFORT_CORRECTION not in decisions[0].reasons  # the water decided anew
    state, _ = run(minutes(3720.0, 60, lambda t: (short(t),)), WATER, state)
    assert state.correction == pytest.approx(1.0)  # what is left of the day's 3 K


def test_the_decision_carries_the_correction() -> None:
    """P-38: the correction is published — each decision carries its value; a hand-back
    resets it."""
    state, decisions = run(minutes(0.0, 31, lambda t: (short(t),)), WATER)
    assert decisions[-1].correction == pytest.approx(1.0) == state.correction
    _state, [off] = run([inputs(1900.0, enabled=False)], WATER, state)
    assert off.correction == 0.0


# --- X8: on/off control through a relay (class 3) ---------------------------------------------

ON_OFF = ControlConfig(
    curve=CURVE, ramp_k_per_min=None, on_off=True, stale_hand_back_s=None, comfort_correction=False
)


def test_on_off_mode_heats_without_a_water_temperature() -> None:
    """R5: a calling zone and no outdoor temperature — heating on, no setpoint, HEATING; never
    FALLBACK, however long the outdoor temperature stays away; the curve, limits and ramp not
    used."""
    steps = [inputs(t, outdoor_sensor=None) for t in stepped(0.0, 5 * 3600.0, 60.0)]
    state, decisions = run(steps, ON_OFF)
    assert all(d.command == BoilerCommand(True, None) for d in decisions)
    assert all(d.mode is ControlMode.HEATING for d in decisions)
    assert all(d.target is None for d in decisions)
    assert all(Reason.DEMAND in d.reasons for d in decisions)
    assert not any(r.value.startswith("limit_") or r is Reason.RAMP for r in decisions[-1].reasons)
    assert state.controlling
    assert state.correction == 0.0


def test_on_off_mode_idle_and_frost() -> None:
    """No demand: IDLE, off. A cold zone that can take heat: FROST, on."""
    _state, [idle] = run([inputs(0.0, zones=(zone(0.0, valve_open=0.0),))], ON_OFF)
    assert idle.mode is ControlMode.IDLE
    assert idle.command == BoilerCommand(False, None)
    cold = zone(0.0, valve_open=0.05, temperature=4.0, heating_enabled=False)
    _state, [frost] = run([inputs(0.0, zones=(cold,))], ON_OFF)
    assert frost.mode is ControlMode.FROST
    assert frost.command == BoilerCommand(True, None)


def _relay_config(**control: object) -> ControlConfig:
    """The relay path's control, parsed as the plugin does (answers F, M)."""
    from custom_components.vtherm_smart_boiler.control_config import parse_control
    from custom_components.vtherm_smart_boiler.core.installation import (
        Boiler,
        BoilerClass,
        Circuit,
        Installation,
        Zone,
    )

    installation = Installation(
        Boiler(BoilerClass.ON_OFF), (Circuit("main"),), (Zone("a", "main"), Zone("b", "main"))
    )
    data = {"write_path": "relay", "relay_entity": "switch.boiler", **control}
    return parse_control(data, installation, None).loop.control


@pytest.mark.parametrize(
    ("control", "handed_back"),
    [
        ({}, False),
        ({"own_room_controller": True, "relay_rest_state": "on"}, True),
        ({"own_room_controller": True, "relay_rest_state": "off"}, False),  # answer M
        ({"relay_rest_state": "on"}, False),  # negative: resting "on" is no working thermostat
    ],
)
def test_on_off_mode_every_zone_unknown_after_the_grace_is_off(
    control: dict[str, object], handed_back: bool
) -> None:
    """Decision 3 on the relay path: every zone unknown after the grace — the relay off, reason
    ``zones_unknown``, never its rest state; with the tick "the boiler has its own room
    controller" and the rest state "on" (the relay is its heat-demand contact) handed back to it
    instead, without a latch (answers F, M)."""
    config = _relay_config(**control)
    assert config.on_off
    assert config.working_thermostat is handed_back
    steps = during(0.0, 10.0 + 10.0 + GRACE_S + 30.0, gone_after(10.0))
    state, decisions = run(steps, config)
    after = [d for s, d in zip(steps, decisions, strict=True) if s.now >= 20.0 + GRACE_S]
    assert all(d.zones_unknown for d in after)
    assert all(d.reasons == (Reason.ZONES_UNKNOWN,) for d in after)
    if handed_back:
        backs = [s.now for s, d in zip(steps, decisions, strict=True) if d.hand_back]
        assert backs == [20.0 + GRACE_S]
        assert all(d.mode is ControlMode.HANDED_BACK and d.command is None for d in after)
    else:
        assert not any(d.hand_back for d in decisions)
        assert all(d.command == BoilerCommand(False, None) for d in after)
        assert all(d.mode is ControlMode.IDLE for d in after)
    assert not state.latched


def test_on_off_mode_never_hands_back_for_a_lost_link() -> None:
    """R6: the link is the relay; the boiler's own signals never gate a relay (the control unit
    keeps ``boiler_link`` true there), and even an hour without them hands nothing back."""
    steps = [inputs(t, boiler_link=False) for t in stepped(0.0, 3600.0, 10.0)]
    _state, decisions = run([inputs(0.0), *steps[1:]], ON_OFF)
    assert not any(d.hand_back for d in decisions)
    assert not any(d.link_lost for d in decisions)
    _state, decisions = run([inputs(t) for t in stepped(0.0, 600.0)], ON_OFF)
    assert all(d.command == BoilerCommand(True, None) for d in decisions)


def test_on_off_mode_waits_the_activation_delay_and_restores_at_once() -> None:
    """Decision 5 on the relay path: a start waits VT's activation delay; a command restored
    after a restart, where the plugin held the relay, waits for nothing."""
    config = replace(ON_OFF, activation_delay_s=60.0)
    steps = [inputs(t) for t in stepped(0.0, 90.0)]
    _state, decisions = run(steps, config)
    at = {s.now: d for s, d in zip(steps, decisions, strict=True)}
    assert at[50.0].command is None
    assert Reason.ACTIVATION_DELAY in at[50.0].reasons
    assert at[60.0].command == BoilerCommand(True, None)
    restored = BoilerCommand(True, None)
    _state, [kept] = run(
        [inputs(0.0, zones=(placeholder("a", 0.0),), restored_command=restored)], config
    )
    assert kept.command == restored
    assert kept.reasons == (Reason.ZONES_RECOGNITION,)
