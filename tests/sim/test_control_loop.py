"""Closed loop: the control step (controller + write guards) drives a simulated boiler."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace

import pytest
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, radiator_zones

from custom_components.vtherm_smart_boiler.core.controller import ControlConfig, ControlInputs
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.cycles import find_burns
from custom_components.vtherm_smart_boiler.core.guards import GuardConfig, WriteType
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits
from custom_components.vtherm_smart_boiler.core.loop import LoopConfig, LoopState, loop_step
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.signals import Signal
from sim.simulator import (
    DAY,
    HOUR,
    Scenario,
    SimCommand,
    SimView,
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

    def writes(self, start: float, end: float) -> list[tuple[float, object]]:
        """Every setpoint and heating write ``loop_step`` asked for in ``[start, end)``."""
        return sorted(
            (t, value) for t, value in [*self.setpoints, *self.switches] if start <= t < end
        )

    def __call__(self, t: float, view: SimView) -> SimCommand | None:
        link = self.link(t)
        inputs = ControlInputs(
            now=t,
            enabled=self.enabled(t),
            boiler_link=link,
            flame=view.flame if link else None,
            dhw=view.dhw if link else None,
            outdoor_sensor=view.outdoor if link else None,
            zones=tuple(
                ZoneState(
                    z.zone_id,
                    temperature=z.temperature,
                    target=z.target,
                    heating_enabled=True,
                    valve_open=z.opening,
                    reported_at=t,
                )
                for z in view.zones
            ),
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


@pytest.mark.parametrize("mean", [8.0, -5.0])
def test_rooms_hold_their_setpoints_under_control(mean: float) -> None:
    controller = LoopController(LOOP)
    result = simulate(scenario([mean, mean], controller))
    targets = {z.zone_id: z.target for z in radiator_zones()}
    for zid, temps in late_rooms(result, 12 * HOUR, 2 * DAY).items():
        assert min(temps) > targets[zid] - 1.0, zid
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
    assert own.min_setpoint <= later <= own.max_setpoint  # the boiler's own curve again


def test_summer_keeps_heating_off() -> None:
    controller = LoopController(LOOP)
    result = simulate(scenario([24.0], controller, without_override=WithoutOverride.OWN_CURVE))
    flame = result.history.signal(Signal.FLAME)
    assert not [b for b in find_burns(flame, HOUR, DAY) if b.start_seen]
