"""Closed loop: the control step (controller + write guards) drives a simulated boiler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cache

import pytest
from custom_components.boiler_sim.plant import boiler_setpoint
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, BoilerProfile, radiator_zones

from custom_components.vtherm_smart_boiler.control_config import parse_control
from custom_components.vtherm_smart_boiler.core.comfort_rules import STARTS_WINDOW_S
from custom_components.vtherm_smart_boiler.core.controller import ControlConfig, ControlInputs
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.cycles import find_burns
from custom_components.vtherm_smart_boiler.core.guards import GuardConfig, WriteType
from custom_components.vtherm_smart_boiler.core.history import History
from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    Installation,
    Zone,
)
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits
from custom_components.vtherm_smart_boiler.core.loop import LoopConfig, LoopState, loop_step
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.signals import Signal
from sim.simulator import (
    DAY,
    HOUR,
    Scenario,
    SimCommand,
    SimResult,
    SimView,
    SimZoneView,
    TpiConfig,
    WithoutOverride,
    daily_cycle,
    simulate,
)

CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)
LOOP = LoopConfig(
    control=ControlConfig(curve=CURVE, limits=FlowLimits(hard_min=25.0, hard_max=60.0)),
    setpoint_guard=GuardConfig(write_type=WriteType.EXPIRING),
)


@dataclass
class LoopController:
    """The plugin's control step wired to the simulator, as the integration will wire it.

    Every command ``loop_step`` returns is recorded before anything decides whether it reaches
    the boiler, so the tests judge the plugin's commands, not what the wiring let through.
    """

    config: LoopConfig
    enabled: Callable[[float], bool] = lambda _t: True
    link: Callable[[float], bool] = lambda _t: True
    state: LoopState = field(default_factory=LoopState)
    setpoints: list[tuple[float, float]] = field(default_factory=list)  # setpoint writes
    switches: list[tuple[float, bool]] = field(default_factory=list)  # heating on/off writes
    hand_backs: list[float] = field(default_factory=list)
    heating: list[tuple[float, bool | None, bool]] = field(default_factory=list)  # t, on, called
    # The heating starts seen (the comfort correction's rule 3), as the coordinator gives them:
    # the flame seen going on without hot water, within the window.
    flame_seen: bool | None = None
    started: list[float] = field(default_factory=list)

    def writes(self, start: float, end: float) -> list[tuple[float, object]]:
        """Every setpoint and heating write ``loop_step`` asked for in ``[start, end)``."""
        return sorted(
            (t, value) for t, value in [*self.setpoints, *self.switches] if start <= t < end
        )

    def _starts(self, t: float, view: SimView, link: bool) -> tuple[float, ...] | None:
        flame = view.flame if link else None
        if flame is True and self.flame_seen is False and not view.dhw:
            self.started.append(t)
        self.flame_seen = flame
        self.started = [s for s in self.started if t - s <= STARTS_WINDOW_S]
        return tuple(self.started) if link else None

    def __call__(self, t: float, view: SimView) -> SimCommand | None:
        link = self.link(t)
        inputs = ControlInputs(
            now=t,
            enabled=self.enabled(t),
            boiler_link=link,
            flame=view.flame if link else None,
            dhw=view.dhw if link else None,
            outdoor_sensor=view.outdoor if link else None,
            zones=tuple(zone_state(z, t) for z in view.zones),
            starts=self._starts(t, view, link),
        )
        confirmed = view.confirmed_setpoint if link else None
        self.state, out = loop_step(self.state, inputs, confirmed, self.config)
        called = any(z.opening > 0.05 for z in view.zones)
        self.heating.append((t, out.heating_on, called))
        if out.setpoint is not None:
            self.setpoints.append((t, out.setpoint.value))
        if out.ch_enable is not None:
            self.switches.append((t, out.ch_enable))
        if out.hand_back:
            self.hand_backs.append(t)
            return SimCommand(hand_back=True)
        if not link:
            return None  # the gateway the plugin cannot hear gets nothing either
        if out.setpoint is None and out.ch_enable is None:
            return None
        return SimCommand(
            ch_enable=out.ch_enable,
            setpoint=out.setpoint.value if out.setpoint is not None else None,
        )


def zone_state(zone: SimZoneView, t: float) -> ZoneState:
    """A zone as VT publishes it: a thermostatic valve's opening; a switch zone under TPI — VT's
    over_switch — its duty (``on_percent``) and whether its device is on now, no opening."""
    if zone.on_percent is not None:
        on = zone.opening > 0.5
        return ZoneState(
            zone.zone_id,
            temperature=zone.temperature,
            target=zone.target,
            heating_enabled=True,
            on_percent=zone.on_percent,
            device_active=on,
            calling=on,
            reported_at=t,
        )
    return ZoneState(
        zone.zone_id,
        temperature=zone.temperature,
        target=zone.target,
        heating_enabled=True,
        valve_open=zone.opening,
        reported_at=t,
    )


def scenario(means: list[float], controller: LoopController, **changes) -> Scenario:
    base = Scenario(
        BOILERS["condensing_large"],
        HOUSES["average"],
        radiator_zones(),
        daily_cycle(means),
        days=len(means),
        controller=controller,
        without_override=WithoutOverride.OFF,
    )
    return replace(base, **changes)


def late_rooms(result, start: float, end: float) -> dict[str, list[float]]:
    """Room temperatures sampled every 10 minutes (the series keeps only changes)."""
    times = [start + i * 600.0 for i in range(int((end - start) // 600.0))]
    return {
        zid: [v for t in times if (v := zone.temperature.value_at(t)) is not None]
        for zid, zone in result.history.zones.items()
    }


@pytest.mark.parametrize("correction", [False, True], ids=["defaults", "correction_on"])
@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_rooms_hold_their_setpoints_under_control(mean: float, correction: bool) -> None:
    """With the comfort correction on, every room holds its setpoint within a kelvin and none
    overheats. With the defaults — the correction off since the user's decision of 2026-10-03
    (K4.1) — the curve alone heats: the rooms near the curve's room temperature hold, and a room
    set 2 K above it (the bathroom, 22 °C) stays up to about 2 K short at −5 °C: the cost the
    option's text names (switch the correction on for such a room, or set the curve for it)."""
    loop = replace(LOOP, control=replace(LOOP.control, comfort_correction=correction))
    result = simulate(scenario([mean, mean], LoopController(loop)))
    targets = {z.zone_id: z.target for z in radiator_zones()}
    for zid, temps in late_rooms(result, 12 * HOUR, 2 * DAY).items():
        above_the_curve = targets[zid] - CURVE.room > 1.0
        short_by = 2.5 if above_the_curve and not correction else 1.0
        assert min(temps) > targets[zid] - short_by, zid
        assert max(temps) < targets[zid] + 1.5, zid
    assert result.override_s > 0.95 * 2 * DAY  # control held the boiler the whole time


def test_setpoints_stay_within_the_limits_even_in_deep_frost() -> None:
    controller = LoopController(LOOP)
    simulate(scenario([-20.0], controller))
    assert controller.setpoints
    assert max(v for _t, v in controller.setpoints) <= 60.0
    assert min(v for _t, v in controller.setpoints) >= 25.0


def test_a_cycling_boiler_is_never_held_off_while_the_zones_call() -> None:
    """A large boiler in mild weather cycles on its own: heating follows the zones at every step,
    whatever the starts per hour."""
    controller = LoopController(LOOP)
    result = simulate(scenario([12.0, 12.0], controller))
    flame = result.history.signal(Signal.FLAME)
    starts = [b.start for b in find_burns(flame, 0, 2 * DAY) if b.start_seen]
    assert len(starts) > 2 * 24  # it does cycle a lot
    assert all(on for _t, on, called in controller.heating if called)
    # The heating writes themselves: never "off" while a zone called at that step.
    called_at = {t: called for t, _on, called in controller.heating}
    assert controller.switches
    assert not [t for t, on in controller.switches if not on and called_at[t]]


def test_lost_link_writes_nothing_and_the_override_lapses() -> None:
    """Twenty minutes without the boiler's data: ``loop_step`` asks for no write at all, only
    for one hand-back once the data has been missing for five minutes."""
    outage = (10 * HOUR, 10 * HOUR + 20 * 60)
    controller = LoopController(LOOP, link=lambda t: not outage[0] <= t < outage[1])
    result = simulate(scenario([0.0], controller))
    assert controller.writes(0.0, outage[0])  # it was writing before
    assert controller.writes(*outage) == []
    during = [t for t in controller.hand_backs if outage[0] <= t < outage[1]]
    assert len(during) == 1
    assert during[0] >= outage[0] + 5 * 60 - 60.0
    assert controller.writes(outage[1], outage[1] + HOUR)  # and again once it is back
    flame = result.history.signal(Signal.FLAME)
    # Without a thermostat the boiler stops once the override lapses (about a minute) ...
    assert flame.value_at(outage[0] + 5 * 60) is False
    # ... and heating resumes after the link returns.
    resumed = [b for b in find_burns(flame, outage[1], outage[1] + HOUR) if b.start_seen]
    assert resumed


def test_hand_back_returns_the_boiler_to_its_own_control() -> None:
    switch_off = 12 * HOUR
    controller = LoopController(LOOP, enabled=lambda t: t < switch_off)
    result = simulate(scenario([2.0], controller, without_override=WithoutOverride.OWN_CURVE))
    assert len(controller.hand_backs) == 1
    assert switch_off <= controller.hand_backs[0] < switch_off + 60.0
    assert controller.writes(controller.hand_backs[0], 2 * DAY) == []  # nothing after it
    setpoint = result.history.signal(Signal.CH_SETPOINT)
    own = BOILERS["condensing_large"]
    later = setpoint.value_at(switch_off + HOUR)
    assert later is not None
    # PB-95: the boiler's own curve again, exactly — not merely within its range, which the
    # plugin's own setpoint also is — and no override after the hand-back.
    outdoor = result.history.signal(Signal.OUTDOOR).value_at(switch_off + HOUR)
    assert outdoor is not None
    assert later == pytest.approx(boiler_setpoint(own, outdoor), abs=0.05)
    assert result.override_s <= controller.hand_backs[0] + 60.0


def test_summer_heating_follows_vt_at_the_minimum_water_temperature() -> None:
    """Summer and winter come from VT (plan 0.2.1, decisions of 2026-09-25): there is no summer
    switch of the plugin's own. A day at 24 °C outside: heating is on at exactly the steps a
    zone calls — every call gives "on", nothing else does — at the lowest water temperature
    the curve allows, and the warm water that brings is enough: after the first hour the burner
    never lights (P-121: the name said "heating off", the test only counted ignitions)."""
    controller = LoopController(LOOP)
    result = simulate(scenario([24.0], controller, without_override=WithoutOverride.OWN_CURVE))
    assert [on for _t, on, _called in controller.heating] == [
        called for _t, _on, called in controller.heating
    ]
    assert any(called for _t, _on, called in controller.heating)  # the zones do call
    hard_min = LOOP.control.limits.hard_min
    assert {value for _t, value in controller.setpoints} == {hard_min}
    assert controller.hand_backs == []
    flame = result.history.signal(Signal.FLAME)
    assert not [b for b in find_burns(flame, HOUR, DAY) if b.start_seen]


# --- S-15, T-24: starts under control against the boiler's own regulation --------------------

STARTS_CRITERION = 1.10  # J4's criterion (Z3 rule 6; provisional, K4)
# J4's comfort parity (decision 8 of 0.2.3, SB-08): each room's mean temperature over the day at
# most this far below its mean under the boiler's own regulation (provisional, K4), so a cooler
# curve cannot meet the starts criterion by leaving the rooms colder.
COMFORT_PARITY_K = 0.3
SWING_K = 3.0  # J4's daily outdoor swing, ± (decision 8 of 0.2.3)


def own_curve_loop(
    boiler: BoilerProfile, comfort_correction: bool | None, flow_shift: float = 0.0
) -> LoopConfig:
    """The control the plugin runs on an OpenTherm Gateway (``parse_control``), its curve set to
    the boiler's own — linear (exponent 1) through the same points, shifted by the boiler's
    offset — and its lowest water temperature the boiler's own minimum, so that the comparison
    is of the control, not of two curves (research/2026-10-02-z3-starts-ratio.md).
    ``comfort_correction``: ``None`` leaves the option out — the parser's default.
    ``flow_shift``: K added to the curve's design flow, for a curve that is not the boiler's."""
    room = 20.0
    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main"),),
        tuple(Zone(z.zone_id, "main") for z in radiator_zones()),
    )
    control = {
        "write_path": "opentherm_gw",
        "gateway_id": "sim",
        "confirmed_entity": "sensor.gateway_control_setpoint",
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "curve": {
            "design_outdoor": -15.0,
            "design_flow": room + boiler.curve_slope * (room + 15.0) + flow_shift,
            "exponent": 1.0,
            "offset": boiler.curve_offset - room,
        },
        "hard_min": boiler.min_setpoint,
        "hard_max": boiler.max_setpoint,
    }
    if comfort_correction is not None:
        control["comfort_correction"] = comfort_correction
    return parse_control(control, installation, None).loop


def starts(result: SimResult, start: float, end: float) -> int:
    flame = result.history.signal(Signal.FLAME)
    return len([burn for burn in find_burns(flame, start, end) if burn.start_seen])


def comfort_shortfall(own: SimResult, controlled: SimResult) -> dict[str, float]:
    """Per room, how far its mean temperature over the compared day (sampled every 10 min)
    lies below its mean under the boiler's own regulation; J4's comfort parity allows at most
    ``COMFORT_PARITY_K``."""
    own_rooms, controlled_rooms = (
        late_rooms(own, DAY, 2 * DAY),
        late_rooms(controlled, DAY, 2 * DAY),
    )
    return {
        zid: sum(temps) / len(temps) - sum(controlled_rooms[zid]) / len(controlled_rooms[zid])
        for zid, temps in own_rooms.items()
    }


def comfort_parity(own: SimResult, controlled: SimResult) -> bool:
    shortfall = comfort_shortfall(own, controlled)
    return bool(shortfall) and all(short <= COMFORT_PARITY_K for short in shortfall.values())


def starts_both_ways(
    mean: float,
    comfort_correction: bool | None,
    swing: float = 0.0,
    flow_shift: float = 0.0,
) -> tuple[SimResult, SimResult]:
    return _starts_both_ways(mean, comfort_correction, swing, flow_shift)


@cache  # each pair runs once per session: the band test reads the xfail runs again (PB-94)
def _starts_both_ways(
    mean: float, comfort_correction: bool | None, swing: float, flow_shift: float
) -> tuple[SimResult, SimResult]:
    """24 h at an outdoor temperature around ``mean`` — steady, or with a daily swing of
    ±``swing`` K — after a day to settle, in the same simulated house: three radiator zones
    under TPI, the boiler on its own regulation — its own curve, heating whenever a zone valve
    is open, as VT's central boiler switches it — and under the plugin's control, stepped every
    10 s as the control unit is."""
    boiler = BOILERS["condensing_large"]
    base = Scenario(
        boiler,
        HOUSES["average"],
        radiator_zones(),
        daily_cycle([mean, mean], amplitude=swing),
        days=2,
        step_s=10.0,
        control_period_s=10.0,
        tpi=TpiConfig(),
    )
    own = simulate(base)
    controlled = simulate(
        replace(
            base,
            controller=LoopController(own_curve_loop(boiler, comfort_correction, flow_shift)),
        )
    )
    return own, controlled


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_tpi_switch_zones_starts_per_hour_under_control(mean: float) -> None:
    """S-15, T-24 (Z3 rule 6): switch zones on for their on-percent of each 5-minute TPI cycle;
    over 24 h at +8 °C and at −5 °C the plugin's control starts the burner no more than
    1.10 times as often per hour as the boiler's own regulation, and switches heating no more often
    than VT's central boiler would — the plugin's curve set to the boiler's own and its comfort
    correction off: the control path itself adds no start. (With the correction on, see the
    next test.)"""
    own, controlled = starts_both_ways(mean, comfort_correction=False)
    own_starts, controlled_starts = starts(own, DAY, 2 * DAY), starts(controlled, DAY, 2 * DAY)
    assert own_starts > 0, "the boiler must start for the comparison to mean anything"
    assert controlled_starts / 24.0 <= STARTS_CRITERION * own_starts / 24.0
    assert controlled.ch_switchings <= STARTS_CRITERION * own.ch_switchings
    assert controlled.override_s > 0.95 * 2 * DAY  # the control held the boiler throughout
    assert comfort_parity(own, controlled), comfort_shortfall(own, controlled)


def test_the_defaults_are_the_correction_off_run() -> None:
    """J4's criterion with the plugin's defaults — the comfort correction off since the user's
    decision of 2026-10-03 (K4.1): the defaults' loop is the one the correction-off test runs,
    so that test is J4's criterion with the defaults too (PB-94: no second run of the same).
    Negative: the correction on is another loop."""
    boiler = BOILERS["condensing_large"]
    assert own_curve_loop(boiler, None) == own_curve_loop(boiler, False)
    assert own_curve_loop(boiler, None) != own_curve_loop(boiler, True)


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_a_cooler_curve_meets_the_starts_but_not_comfort_parity(mean: float) -> None:
    """SB-08 (decision 8), negative: a curve 10 K cooler at the design point than the boiler's
    own starts the burner less often — the starts criterion alone would pass it — and leaves the
    rooms colder, which J4's comfort parity refuses."""
    own, controlled = starts_both_ways(mean, comfort_correction=None, flow_shift=-10.0)
    assert starts(controlled, DAY, 2 * DAY) <= STARTS_CRITERION * starts(own, DAY, 2 * DAY)
    assert not comfort_parity(own, controlled), comfort_shortfall(own, controlled)


def test_comfort_parity_without_rooms_is_not_met() -> None:
    """Negative: with no room temperatures to compare, parity is not taken as met."""
    empty = SimResult(History())
    assert comfort_shortfall(empty, empty) == {}
    assert not comfort_parity(empty, empty)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "K4 (S-15, decision 8 of 0.2.3): with the ±3 K daily outdoor swing the defaults on the "
        "boiler's own curve keep the rooms as warm (within 0.01 K) but start the burner x1.20 "
        "as often at +8 °C and x2.16 at -5 °C as the boiler's own regulation (open #27 of "
        "0.2.2; research/2026-10-06-p2-5b-report.md); the acceptable ratio is decided at K4"
    ),
)
@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_j4s_starts_criterion_with_the_daily_swing(mean: float) -> None:
    """J4's starts criterion with its conditions (SB-08, decision 8): 24 h at +8 °C and at
    −5 °C, each with a ±3 K daily outdoor swing, the plugin's defaults on the boiler's own curve:
    at most 1.10 times the boiler's own regulation's starts per hour, with every room as warm as
    under it (comfort parity)."""
    own, controlled = starts_both_ways(mean, comfort_correction=None, swing=SWING_K)
    assert controlled.override_s > 0.95 * 2 * DAY  # the control held the boiler throughout
    assert starts(own, DAY, 2 * DAY) > 0
    assert comfort_parity(own, controlled), comfort_shortfall(own, controlled)
    assert starts(controlled, DAY, 2 * DAY) <= STARTS_CRITERION * starts(own, DAY, 2 * DAY)


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "K4.1 (S-15): the comfort correction, when switched on, rises to +3 K while a TPI zone "
        "sits at full duty short of its target, and every zone's cycle then stops the burner: "
        "x1.75 at +8 °C, x5 at -5 °C (research/2026-10-02-z3-starts-ratio.md) — why it is off "
        "by default. Rule 3 (decision 11 of 0.2.3) leaves it so: the hours before the "
        "correction began, the house warming up, show as many starts as after "
        "(research/2026-10-06-p2-4-report.md)"
    ),
)
@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_tpi_switch_zones_starts_per_hour_with_the_correction_on(mean: float) -> None:
    """The cost the option's text names: with the comfort correction switched on, the same
    house fails J4's criterion."""
    own, controlled = starts_both_ways(mean, comfort_correction=True)
    assert starts(controlled, DAY, 2 * DAY) <= STARTS_CRITERION * starts(own, DAY, 2 * DAY)


@pytest.mark.parametrize(
    ("mean", "correction", "swing", "low", "high"),
    [
        (8.0, None, SWING_K, 1.15, 1.25),
        (-5.0, None, SWING_K, 2.0, 2.3),
        (8.0, True, 0.0, 1.65, 1.85),
        (-5.0, True, 0.0, 4.7, 5.5),
    ],
    ids=["swing_plus_8", "swing_minus_5", "correction_on_plus_8", "correction_on_minus_5"],
)
def test_the_documented_starts_ratios_hold(
    mean: float, correction: bool | None, swing: float, low: float, high: float
) -> None:
    """PB-94: the two strict xfails above fail on the starts criterion alone; this pins the
    ratios their reasons document (x1.20 and x2.16 with the daily swing, x1.75 and x5 with the
    correction on), so a far worse ratio — or a crash — shows here instead of passing as the
    expected failure. Comfort parity holds in each (within 0.05 K)."""
    own, controlled = starts_both_ways(mean, comfort_correction=correction, swing=swing)
    ratio = starts(controlled, DAY, 2 * DAY) / starts(own, DAY, 2 * DAY)
    assert low <= ratio <= high, ratio
    assert all(short <= 0.05 for short in comfort_shortfall(own, controlled).values())
