"""The controller state machine: precedence, hand-back, data problems, heating decisions."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.controller import (
    BoilerCommand,
    ControlConfig,
    ControlInputs,
    ControlMode,
    ControlState,
    Reason,
    decide,
    fallback_setpoint,
)
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

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
    assert [d.mode for d in decisions[1:]] == [
        ControlMode.HANDED_BACK,
        ControlMode.HANDED_BACK,
        ControlMode.NOT_ALLOWED,
        ControlMode.HANDED_BACK,
    ]
    assert state.latched_by == ("pressure_low",)  # the cause stays with the latch
    # Control being off does not clear it (e.g. a switch not restored after a restart): only the
    # user switching control off and on again, which starts a new session.
    state, decisions = run([inputs(150.0, enabled=False), inputs(180.0)], state=state)
    assert decisions[1].mode is ControlMode.HANDED_BACK
    assert state.latched_by == ("pressure_low",)
    _state, decisions = run([inputs(210.0)], state=ControlState())
    assert decisions[0].mode is ControlMode.HEATING


def test_vt_modes_act_through_the_zones() -> None:
    """VT applies its central mode to the zones; the plugin sees only their demand. With every
    zone stopped there is no demand: heating off and no hand-back — control goes on, and frost
    protection still watches."""

    def stopped(t: float, **kw: float) -> tuple[ZoneState, ...]:
        return (zone(t, heating_enabled=False, **kw),)

    _state, decisions = run(
        [
            inputs(0.0),
            inputs(10.0, zones=stopped(10.0)),
            inputs(20.0, zones=stopped(20.0, temperature=4.0)),
        ]
    )
    assert [d.hand_back for d in decisions] == [False, False, False]
    assert decisions[1].mode is ControlMode.IDLE
    assert decisions[1].command is not None
    assert not decisions[1].command.ch_enable
    assert decisions[2].mode is ControlMode.FROST
    assert decisions[2].command is not None
    assert decisions[2].command.ch_enable


def test_stale_boiler_link_writes_nothing_and_keeps_control() -> None:
    state, decisions = run([inputs(0.0), inputs(30.0, boiler_link=False), inputs(60.0)])
    assert decisions[1].mode is ControlMode.WAITING_DATA
    assert decisions[1].command is None
    assert not decisions[1].hand_back
    assert decisions[2].command is not None  # decided again at once
    assert state.controlling


def test_no_demand_is_idle() -> None:
    _state, [decision] = run([inputs(0.0, zones=(zone(0.0, valve_open=0.0),))])
    assert decision.mode is ControlMode.IDLE
    assert decision.command is not None
    assert not decision.command.ch_enable
    assert Reason.NO_DEMAND in decision.reasons


def test_unknown_zones_mean_heat() -> None:
    stale = zone(-10 * 3600.0)
    _state, [decision] = run([inputs(0.0, zones=(stale,))])
    assert decision.mode is ControlMode.HEATING
    assert Reason.ZONES_UNKNOWN in decision.reasons
    _state, [none] = run([inputs(0.0, zones=())])
    assert Reason.ZONES_UNKNOWN in none.reasons


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
    steps = [
        inputs(0.0),
        inputs(1800.0, outdoor_sensor=None),
        inputs(2 * 3600.0, outdoor_sensor=None),
    ]
    config = replace(CONFIG, decision_interval_s=60.0)
    _state, decisions = run(steps, config)
    assert Reason.OUTDOOR_HELD in decisions[1].reasons
    assert decisions[2].mode is ControlMode.FALLBACK
    assert decisions[2].command == BoilerCommand(True, pytest.approx(CURVE.flow(0.0)))
    assert fallback_setpoint(replace(CONFIG, fallback_setpoint=48.0)) == 48.0


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
            inputs(30.0, zones=(zone(30.0, temperature=4.0, valve_open=0.0),)),
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
    def zones(t: float) -> tuple[ZoneState, ...]:
        return (short(t), ZoneState("b", 22.5, 21.0, True, reported_at=t, valve_open=0.0))

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
    config = replace(CONFIG, stale_hand_back_s=300.0)
    state, decisions = run(
        [
            inputs(0.0),
            inputs(30.0, boiler_link=False),
            inputs(200.0, boiler_link=False),
            inputs(330.0, boiler_link=False),
            inputs(360.0, boiler_link=False),
            inputs(400.0),
        ],
        config,
    )
    assert [d.hand_back for d in decisions] == [False, False, False, True, False, False]
    assert decisions[3].mode is ControlMode.HANDED_BACK
    assert Reason.BOILER_LINK_STALE in decisions[3].reasons
    assert decisions[4].mode is ControlMode.HANDED_BACK  # stays shown until data returns
    assert decisions[4].command is None
    assert decisions[5].mode is ControlMode.HEATING
    assert state.waiting_since is None
    never = replace(CONFIG, stale_hand_back_s=None)
    _state, decisions = run(
        [inputs(0.0), inputs(30.0, boiler_link=False), inputs(9999.0, boiler_link=False)], never
    )
    assert not any(d.hand_back for d in decisions)


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
