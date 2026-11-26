"""Closed loop: the control step (controller + write guards) drives a simulated boiler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from functools import cache

import pytest
from custom_components.boiler_sim.plant import boiler_setpoint
from custom_components.boiler_sim.profiles import (
    BOILERS,
    HOUSES,
    BoilerProfile,
    light_bedroom_zones,
    radiator_zones,
    underfloor_zones,
)

from custom_components.vtherm_smart_boiler.control_config import parse_control
from custom_components.vtherm_smart_boiler.core.comfort_rules import STARTS_WINDOW_S
from custom_components.vtherm_smart_boiler.core.controller import (
    OVERHEAT_K,
    ControlConfig,
    ControlInputs,
)
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.cycles import find_burns
from custom_components.vtherm_smart_boiler.core.demand import zone_wants_heat
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
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal
from sim.simulator import (
    DAY,
    HOUR,
    LEARNING_PHASES,
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
    corrections: list[tuple[float, float]] = field(default_factory=list)  # the comfort correction

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
        zones = tuple(zone_state(z, t) for z in view.zones)
        inputs = ControlInputs(
            now=t,
            enabled=self.enabled(t),
            boiler_link=link,
            flame=view.flame if link else None,
            dhw=view.dhw if link else None,
            outdoor_sensor=view.outdoor if link else None,
            zones=zones,
            starts=self._starts(t, view, link),
            # I12: VT's central boiler with its count of 1 switches the helper.
            vt_heat=any(z.is_known(t, None) and zone_wants_heat(z) for z in zones),
        )
        confirmed = view.confirmed_setpoint if link else None
        self.state, out = loop_step(self.state, inputs, confirmed, self.config)
        self.corrections.append((t, self.state.control.correction))
        called = any(z.opening > 0.0 for z in view.zones)  # VT's rule (2026-10-14)
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
    over_switch — or SmartPI, its duty (``on_percent``) and whether its device is on now, no
    opening. Nothing of SmartPI's phase (I12.9)."""
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
    (K4.1) — the curve alone heats: the rooms near the curve's room temperature hold, within
    1.2 K at the coldest hour of the ±3 K daily swing (the living room, 0.5 K above the curve's
    room, 19.4 °C at −5 °C in the house of 22 h — 19.6 °C in the heavier one before L16), and a
    room set 2 K above it (the bathroom, 22 °C) stays up to about 2.5 K short at −5 °C (19.5 °C;
    19.9 °C before L16): the cost the option's text names (switch the correction on for such a
    room, or set the curve for it)."""
    loop = replace(LOOP, control=replace(LOOP.control, comfort_correction=correction))
    result = simulate(scenario([mean, mean], LoopController(loop)))
    targets = {z.zone_id: z.target for z in radiator_zones()}
    for zid, temps in late_rooms(result, 12 * HOUR, 2 * DAY).items():
        above_the_curve = targets[zid] - CURVE.room > 1.0
        short_by = 1.0 if correction else 2.8 if above_the_curve else 1.2
        assert min(temps) > targets[zid] - short_by, zid
        assert max(temps) < targets[zid] + 1.5, zid
    assert result.override_s > 0.95 * 2 * DAY  # control held the boiler the whole time


# L19 (J4 of 2026-11-22/24): the light bedroom learning SmartPI from scratch, the comfort correction
# on, at the weather the gateway's instance learned in (+3 °C, the daily swing).
CORRECTION_ON = replace(LOOP, control=replace(LOOP.control, comfort_correction=True))


def learning_bedroom(zones) -> tuple[SimResult, LoopController]:
    controller = LoopController(CORRECTION_ON)
    result = simulate(
        scenario([3.0], controller, zones=zones, learning=frozenset({"zone_bedroom"}))
    )
    return result, controller


def test_smartpi_learns_in_the_light_bedroom_with_the_correction_on_and_no_room_too_warm() -> None:
    """Learning, the bedroom's valve is fully open down to the bottom of its band, 0.3 K under
    its setpoint — short against VT's setpoint (I12.9: no learning band of the plugin's) — so the
    correction rises for it; SmartPI's ten phases still end within 14 h, and no room is ever
    ``OVERHEAT_K`` over its setpoint."""
    result, controller = learning_bedroom(light_bedroom_zones())
    phases = result.learning_phases["zone_bedroom"]
    assert len(phases) == LEARNING_PHASES, phases
    assert phases[-1][1] < 14 * HOUR
    assert max(k for _t, k in controller.corrections) > 1.0
    targets = {z.zone_id: z.target for z in light_bedroom_zones()}
    for zid, temps in late_rooms(result, 0.0, DAY).items():
        assert max(temps) < targets[zid] + OVERHEAT_K, zid


def test_the_correction_raised_for_the_learning_bedroom_falls_back_once_smartpi_has_learned() -> (
    None
):
    """With the other rooms at the curve's room temperature only the learning bedroom is short:
    the correction it raised is back at 0 within 3 h of SmartPI's last phase (about 2 h here)
    and stays there for the rest of the day — no lasting rise of the water for a room that has
    learned."""
    zones = tuple(
        z if z.zone_id == "zone_bedroom" else replace(z, target=CURVE.room)
        for z in light_bedroom_zones()
    )
    result, controller = learning_bedroom(zones)
    learned = result.learning_phases["zone_bedroom"][-1][1]
    assert max(k for t, k in controller.corrections if t < learned) > 1.0
    after = [k for t, k in controller.corrections if learned + 3 * HOUR <= t < DAY]
    assert after
    assert max(after) == 0.0


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

STARTS_CRITERION = 1.10  # J4's criterion (Z3 rule 6), relative to the boiler's own regulation
# K4 (the user's decision of 2026-11-17): the literature measures cycling in absolute terms — the
# starts per hour (gas boilers' TPI convention: 6 an hour) and the share of burns under 10 min
# (Bennett 2019, 221 boilers). J4 passes the ratio above, or at most this many starts per hour
# with a median complete burn of at least this long; comfort parity holds either way.
STARTS_PER_HOUR_LIMIT = 6.0
MEDIAN_BURN_S = 10 * 60.0
VT_DEFAULT_CYCLE_S = 300.0  # VT's default TPI cycle, 5 min
ADVISED_CYCLE_S = 900.0  # the plugin's advice for zones that call a boiler: 10 to 15 min
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
            # Through 20 °C, as the boiler's own curve: Auto would follow the rooms' setpoints
            # and make it another curve (G11 D).
            "room_mode": "manual",
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


def median_burn_s(result: SimResult, start: float, end: float) -> float:
    """The median of the complete burns within ``[start, end)``; 0 without one."""
    flame = result.history.signal(Signal.FLAME)
    burns = sorted(b.duration for b in find_burns(flame, start, end) if b.complete)
    if not burns:
        return 0.0
    middle = len(burns) // 2
    return burns[middle] if len(burns) % 2 else (burns[middle - 1] + burns[middle]) / 2.0


def meets_starts_criterion(own: SimResult, controlled: SimResult) -> bool:
    """J4's starts criterion on the compared day (K4, 2026-11-17): at most ``STARTS_CRITERION``
    times the boiler's own regulation's starts, or at most ``STARTS_PER_HOUR_LIMIT`` starts an
    hour with a median burn of at least ``MEDIAN_BURN_S``."""
    own_starts, controlled_starts = starts(own, DAY, 2 * DAY), starts(controlled, DAY, 2 * DAY)
    if controlled_starts <= STARTS_CRITERION * own_starts:
        return True
    return (
        controlled_starts / 24.0 <= STARTS_PER_HOUR_LIMIT
        and median_burn_s(controlled, DAY, 2 * DAY) >= MEDIAN_BURN_S
    )


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
    cycle_s: float = VT_DEFAULT_CYCLE_S,
) -> tuple[SimResult, SimResult]:
    return _starts_both_ways(mean, comfort_correction, swing, flow_shift, cycle_s)


@cache  # each pair runs once per session: the band test reads the xfail runs again (PB-94)
def _starts_both_ways(
    mean: float, comfort_correction: bool | None, swing: float, flow_shift: float, cycle_s: float
) -> tuple[SimResult, SimResult]:
    """24 h at an outdoor temperature around ``mean`` — steady, or with a daily swing of
    ±``swing`` K — after a day to settle, in the same simulated house: three radiator zones
    under TPI, the boiler on its own regulation — its own curve, heating whenever a zone valve
    is open, as VT's central boiler switches it — and under the plugin's control, stepped every
    10 s as the control unit is. ``cycle_s``: the zones' TPI cycle, VT's 5 min by default."""
    boiler = BOILERS["condensing_large"]
    base = Scenario(
        boiler,
        HOUSES["average"],
        radiator_zones(),
        daily_cycle([mean, mean], amplitude=swing),
        days=2,
        step_s=10.0,
        control_period_s=10.0,
        tpi=TpiConfig(cycle_s=cycle_s),
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
    """The plugin's defaults — the comfort correction off since K4 (the user's decision of
    2026-11-17, reversing G11 B): the defaults' loop is the one the correction-off tests run, so
    those are J4's criterion with the defaults (PB-94: no second run of the same). Negative: the
    correction on is another loop."""
    boiler = BOILERS["condensing_large"]
    assert own_curve_loop(boiler, None) == own_curve_loop(boiler, False)
    assert own_curve_loop(boiler, None) != own_curve_loop(boiler, True)


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_a_cooler_curve_meets_the_starts_but_not_comfort_parity(mean: float) -> None:
    """SB-08 (decision 8), negative: a curve 10 K cooler at the design point than the boiler's
    own starts the burner less often — the starts criterion alone would pass it — and leaves the
    rooms colder, which J4's comfort parity refuses."""
    # The correction off: on, it raises the cooler curve's water and meets parity (G11 B).
    own, controlled = starts_both_ways(mean, comfort_correction=False, flow_shift=-10.0)
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
        "K4 (S-15, decision 8 of 0.2.3; the criterion of 2026-11-17): with VT's default 5-min "
        "TPI cycle and the ±3 K daily outdoor swing, the rooms as warm (within 0.02 K), the "
        "burner starts x1.12 as often at +8 °C (6.5 an hour) and x2.04 at -5 °C as the boiler's "
        "own regulation, its median burn 2 min — every gap between the zones' pulses stops it "
        "(the house of 22 h, L16; x1.20 and x2.16 in the heavier one before). "
        "The plugin advises a 10–15 min cycle (the zone_cycle_short issue); with 15 min the "
        "criterion passes (the next test)"
    ),
)
@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_j4s_starts_criterion_with_the_daily_swing(mean: float) -> None:
    """J4's starts criterion with its conditions (SB-08, decision 8; K4): 24 h at +8 °C and at
    −5 °C, each with a ±3 K daily outdoor swing, on the boiler's own curve with the comfort
    correction off (the defaults), VT's default cycle: at most 1.10 times the boiler's own
    regulation's starts, or at most 6 starts an hour with a median burn of 10 min, with every
    room as warm as under it (comfort parity)."""
    own, controlled = starts_both_ways(mean, comfort_correction=False, swing=SWING_K)
    assert controlled.override_s > 0.95 * 2 * DAY  # the control held the boiler throughout
    assert starts(own, DAY, 2 * DAY) > 0
    assert comfort_parity(own, controlled), comfort_shortfall(own, controlled)
    assert meets_starts_criterion(own, controlled)


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_j4s_starts_criterion_with_the_advised_vt_cycle(mean: float) -> None:
    """K4 (2026-11-17): the same day with the zones' TPI cycle at 15 min, as the plugin advises
    for zones that call a boiler — at +8 °C the ratio holds (x0.98), at −5 °C the absolute
    measure (about 2 starts an hour, the median burn about 12 min); the rooms as warm."""
    own, controlled = starts_both_ways(
        mean, comfort_correction=False, swing=SWING_K, cycle_s=ADVISED_CYCLE_S
    )
    assert controlled.override_s > 0.95 * 2 * DAY
    assert starts(own, DAY, 2 * DAY) > 0
    assert comfort_parity(own, controlled), comfort_shortfall(own, controlled)
    assert meets_starts_criterion(own, controlled)


def test_the_starts_criterion_passes_on_either_measure() -> None:
    """The criterion's two measures, each alone: the ratio (a boiler that cycles on its own)
    and the absolute one (at most 6 starts an hour, the median burn 10 min) — and neither."""

    def burns(minutes: list[float]) -> SimResult:
        """Burns of these lengths one after the other on the compared day, a minute apart."""
        flame: Series[bool] = Series()
        at = DAY + 60.0
        for length in minutes:
            flame.append(at, True)
            flame.append(at + length * 60.0, False)
            at += (length + 1.0) * 60.0
        return SimResult(History(signals={Signal.FLAME: flame}))

    assert meets_starts_criterion(burns([3.0] * 200), burns([3.0] * 210))  # ratio x1.05
    assert meets_starts_criterion(burns([30.0] * 24), burns([12.0] * 100))  # 4.2 an hour, 12 min
    assert not meets_starts_criterion(burns([30.0] * 24), burns([5.0] * 100))  # short burns
    many = [10.5, 0.5] * 99 + [10.5, 10.5]  # 200 starts, 8.3 an hour, the median 10.5 min
    assert not meets_starts_criterion(burns([30.0] * 24), burns(many))


CORRECTION_ON_FAILS = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "K4.1 (S-15): the comfort correction, when switched on, rises to +3 K while a TPI zone "
        "sits at full duty short of its target, and every zone's cycle then stops the burner: "
        "x5.2 at -5 °C (x5 in the heavier house before L16; research/2026-10-02-z3-starts-"
        "ratio.md) — why it is off by default. Rule 3 (decision 11 of 0.2.3) leaves it so: the "
        "hours before the correction began, the house warming up, show as many starts as after "
        "(research/2026-10-06-p2-4-report.md)"
    ),
)


@pytest.mark.parametrize(
    "mean", [8.0, pytest.param(-5.0, marks=CORRECTION_ON_FAILS)], ids=["plus_8", "minus_5"]
)
def test_tpi_switch_zones_starts_per_hour_with_the_correction_on(mean: float) -> None:
    """The cost the option's text names: with the comfort correction switched on, the same
    house fails J4's criterion at −5 °C. At a steady +8 °C it passes in the house of 22 h
    (L16): the correction rises to about +1.2 K, the starts rise and rule 3 brings it back
    (x1.00); in the heavier house before, the warm-up's starts hid the rise (x1.75)."""
    own, controlled = starts_both_ways(mean, comfort_correction=True)
    assert meets_starts_criterion(own, controlled)


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_the_correction_buys_no_more_comfort_than_its_text_names(mean: float) -> None:
    """The option's text: "for under 0.15 K of comfort". With the daily swing, every room's mean
    over the compared day is that close to its mean with the correction off (at most 0.12 K,
    the bathroom at +8 °C), for the starts the next test pins."""
    _own, off = starts_both_ways(mean, comfort_correction=False, swing=SWING_K)
    _own, on = starts_both_ways(mean, comfort_correction=True, swing=SWING_K)
    assert all(warmer < 0.15 for warmer in comfort_shortfall(on, off).values())


@pytest.mark.parametrize(
    ("mean", "correction", "swing", "low", "high"),
    [
        (8.0, False, SWING_K, 1.07, 1.17),
        (-5.0, False, SWING_K, 1.95, 2.15),
        (8.0, True, 0.0, 0.95, 1.05),
        (-5.0, True, 0.0, 4.9, 5.4),
        # The correction on — with the daily swing, x1.93 and x5.96 (the "about 2 to 6 times"
        # the option's text names; x1.39 and x6.28 in the heavier house before L16): why it is
        # off by default since K4 (2026-11-17).
        (8.0, True, SWING_K, 1.8, 2.05),
        (-5.0, True, SWING_K, 5.7, 6.2),
    ],
    ids=[
        "swing_plus_8",
        "swing_minus_5",
        "correction_on_plus_8",
        "correction_on_minus_5",
        "correction_on_swing_plus_8",
        "correction_on_swing_minus_5",
    ],
)
def test_the_documented_starts_ratios_hold(
    mean: float, correction: bool | None, swing: float, low: float, high: float
) -> None:
    """PB-94: the two strict xfails above fail on the starts criterion alone; this pins the
    ratios their reasons document (x1.12 and x2.04 with the daily swing and the correction off,
    x1.00 and x5.2 with the correction on; the house of 22 h, L16), and those of the defaults
    since G11 — the correction on with the daily swing — so a far worse ratio, or a crash,
    shows here instead of passing as the expected failure. Comfort parity holds in each (within
    0.05 K)."""
    own, controlled = starts_both_ways(mean, comfort_correction=correction, swing=swing)
    ratio = starts(controlled, DAY, 2 * DAY) / starts(own, DAY, 2 * DAY)
    assert low <= ratio <= high, ratio
    assert all(short <= 0.05 for short in comfort_shortfall(own, controlled).values())


# --- I13.8: the slower outdoor mean of an underfloor circuit ---------------------------------


def underfloor_loop() -> LoopConfig:
    """The control the plugin runs for the underfloor house (``parse_control``): one circuit,
    every room underfloor, its highest water 45 °C; the curve's design flow 38 °C, its lowest
    20 °C, through 20 °C (Manual) — what its options give, the outdoor mean included."""
    installation = Installation(
        Boiler(BoilerClass.FLOW_SETPOINT),
        (Circuit("main", max_flow=45.0),),
        tuple(Zone(z.zone_id, "main", z.emitter) for z in underfloor_zones()),
    )
    control = {
        "write_path": "opentherm_gw",
        "gateway_id": "sim",
        "confirmed_entity": "sensor.gateway_control_setpoint",
        "topology": "gateway_standalone",
        "thermostat_kind": "none",
        "curve": {"design_outdoor": -15.0, "design_flow": 38.0, "room_mode": "manual"},
        "hard_min": 20.0,
    }
    return parse_control(control, installation, None).loop


def test_an_underfloor_house_on_the_slower_outdoor_mean_is_no_colder() -> None:
    """I13.8 on the simulator: the underfloor house (22 h) on sunny days at +3 °C, a ±6 K daily
    swing. Its options give the 12-hour outdoor mean; against the 3-hour mean the water keeps
    nearer the night's — its lowest about 1.4 K higher (28.7 °C against 27.3 °C) — no room is
    colder, the gas is within 1 % (185.5 kWh against 185.4 kWh over two days) and the burner
    starts under once an hour. The simulator shows no gain either: its floors pass their heat on
    within about 2 h (P-112), where real rooms with underfloor heating take 20–70 h (Kull et al.
    2017) — the reason for the slower mean."""
    slow = underfloor_loop()
    assert slow.control.outdoor_time_constant_s == 12 * HOUR
    assert slow.control.curve.exponent == 1.1
    fast = replace(slow, control=replace(slow.control, outdoor_time_constant_s=3 * HOUR))
    runs = {}
    for loop in (fast, slow):
        controller = LoopController(loop)
        result = simulate(
            scenario(
                [3.0, 3.0, 3.0],
                controller,
                boiler=BOILERS["condensing_small"],
                zones=underfloor_zones(),
                outdoor=daily_cycle([3.0, 3.0, 3.0], amplitude=6.0),
            )
        )
        lowest = min(v for t, v in controller.setpoints if t >= DAY)
        runs[loop.control.outdoor_time_constant_s] = (result, lowest)
    (fast_run, fast_lowest), (slow_run, slow_lowest) = runs[3 * HOUR], runs[12 * HOUR]
    assert slow_lowest >= fast_lowest + 1.0
    fast_rooms = late_rooms(fast_run, DAY, 3 * DAY)
    for zid, temps in late_rooms(slow_run, DAY, 3 * DAY).items():
        assert min(temps) >= min(fast_rooms[zid]) - 0.1, zid  # the rooms read to 0.1 K
    fast_gas, slow_gas = sum(fast_run.daily_ch_kwh[1:]), sum(slow_run.daily_ch_kwh[1:])
    assert abs(slow_gas / fast_gas - 1.0) <= 0.01
    assert starts(slow_run, DAY, 3 * DAY) / 48.0 <= 1.0
