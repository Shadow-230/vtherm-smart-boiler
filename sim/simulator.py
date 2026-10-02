"""Whole scenarios on the simulated plant (``boiler_sim.plant``), producing the core's ``History``.

A scenario sets the plant, the weather, hot water runs, the zone valves — thermostatic heads, or
switches driven by a TPI stand-in for VT (on for ``on_percent`` of each cycle, P-114) — and
optionally an external controller called every control period with what it would see. The
controller's commands reach the boiler as through a gateway: a setpoint is ``CS`` (lapsing
unless repeated), heating on/off is the gateway's ``CH`` flag (kept until changed), a hand-back is
``CH=1`` then ``CS=0``. Without a controller the boiler runs on its own regulation — its own
curve, heating whenever a zone's valve is open, as VT's central boiler switches it. The result
holds the recorded signals, energy totals and the daily sums, kept whatever the step (P-112).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from custom_components.boiler_sim.plant import (
    DEMAND_OPENING,
    HOUR,
    WATER_KWH_PER_L_K,
    Plant,
    WithoutOverride,
    boiler_setpoint,
)
from custom_components.boiler_sim.plant import reference_outputs as _reference_outputs
from custom_components.boiler_sim.profiles import BoilerProfile, HouseProfile, ZoneProfile
from custom_components.boiler_sim.tpi import TpiConfig, TpiZone

from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal

__all__ = [
    "DAY",
    "DEFAULT_SIGNALS",
    "HOUR",
    "WATER_KWH_PER_L_K",
    "DhwSchedule",
    "Scenario",
    "SimCommand",
    "SimResult",
    "SimView",
    "SimZoneView",
    "TpiConfig",
    "WithoutOverride",
    "boiler_setpoint",
    "daily_cycle",
    "entered_parameters",
    "reference_outputs",
    "simulate",
]

DAY = 86400.0

DEFAULT_SIGNALS = frozenset(
    {
        Signal.FLAME,
        Signal.FLOW,
        Signal.RETURN,
        Signal.MODULATION,
        Signal.CH_SETPOINT,
        Signal.DHW_ACTIVE,
        Signal.PRESSURE,
        Signal.FLUE_GAS,
        Signal.OUTDOOR,
        Signal.CH_ACTIVE,
        Signal.PUMP_RUNNING,
    }
)


def daily_cycle(means: Sequence[float], amplitude: float = 3.0) -> Callable[[float], float]:
    """Outdoor temperature: a mean per day plus a daily swing, warmest at 15:00."""

    def outdoor(t: float) -> float:
        day = min(int(t // DAY), len(means) - 1)
        hour = (t % DAY) / HOUR
        return means[max(day, 0)] + amplitude * math.cos(2 * math.pi * (hour - 15.0) / 24.0)

    return outdoor


@dataclass(frozen=True, slots=True)
class DhwSchedule:
    times_of_day_s: tuple[float, ...] = (7 * HOUR, 19 * HOUR)
    duration_s: float = 15 * 60.0

    def active(self, t: float) -> bool:
        seconds = t % DAY
        return any(start <= seconds < start + self.duration_s for start in self.times_of_day_s)


@dataclass(frozen=True, slots=True)
class SimZoneView:
    zone_id: str
    temperature: float
    target: float
    opening: float
    on_percent: float | None = None  # a TPI zone's on-percent of its cycle


@dataclass(frozen=True, slots=True)
class SimView:
    """What an external controller sees, rounded like the recorded signals."""

    flame: bool
    flow: float
    return_: float
    dhw: bool
    outdoor: float
    confirmed_setpoint: float  # the setpoint the boiler works to now
    zones: tuple[SimZoneView, ...]


@dataclass(frozen=True, slots=True)
class SimCommand:
    ch_enable: bool | None = None
    setpoint: float | None = None
    hand_back: bool = False


type Controller = Callable[[float, SimView], SimCommand | None]


@dataclass(frozen=True, slots=True)
class Scenario:
    boiler: BoilerProfile
    house: HouseProfile
    zones: tuple[ZoneProfile, ...]
    outdoor: Callable[[float], float]
    days: float = 1.0
    start: float = 0.0
    step_s: float = 20.0
    dhw: DhwSchedule | None = None
    signals: frozenset[Signal] = DEFAULT_SIGNALS
    weather_bias_k: float = 0.5  # the weather entity reads slightly off the boiler's sensor
    controller: Controller | None = None
    control_period_s: float = 30.0
    override_expires_s: float | None = 60.0  # None: an override holds until changed
    without_override: WithoutOverride = WithoutOverride.OWN_CURVE
    tpi: TpiConfig | None = None  # switch valves driven by TPI; None: thermostatic heads


@dataclass
class SimResult:
    history: History
    burner_kwh: float = 0.0  # all burner output
    ch_kwh: float = 0.0  # burner output for heating
    emitted_kwh: float = 0.0  # taken from the water by the emitters
    room_kwh: float = 0.0  # passed on by the emitters to the rooms
    water_start: float = 0.0
    water_end: float = 0.0
    emitters_start_kwh: float = 0.0  # heat in the emitters on its way to the rooms
    emitters_end_kwh: float = 0.0
    # Burner output for heating per day of the run, the last one the day it ended in, complete
    # or not: their sum is ``ch_kwh`` whatever the step (P-112).
    daily_ch_kwh: list[float] = field(default_factory=list)
    override_s: float = 0.0  # time an external override was in force
    commands: int = 0
    ch_switchings: int = 0  # the CH enable the boiler gets turning on or off


def reference_outputs(scenario: Scenario) -> list[float]:
    return _reference_outputs(scenario.house, scenario.zones)


def simulate(scenario: Scenario) -> SimResult:
    boiler, zones = scenario.boiler, scenario.zones
    dt = scenario.step_s
    dt_h = dt / HOUR
    steps = round(scenario.days * DAY / dt)
    t0 = scenario.start
    plant = Plant(
        boiler,
        scenario.house,
        zones,
        water=boiler_setpoint(boiler, scenario.outdoor(t0)) - 5.0,
        override_expires_s=scenario.override_expires_s,
        without_override=scenario.without_override,
    )
    plant.settle(scenario.outdoor(0.0))
    tpi = None if scenario.tpi is None else {z.zone_id: TpiZone(scenario.tpi) for z in zones}

    record = scenario.signals
    signals: dict[Signal, Series] = {s: Series() for s in record}
    zone_series = {z.zone_id: ZoneSeries(z.zone_id) for z in zones}
    weather: Series[float] = Series()
    result = SimResult(
        History(signals, zone_series, weather),
        water_start=plant.water,
        emitters_start_kwh=sum(plant.stored),
    )
    day_ch = 0.0
    day = 0
    demand: bool | None = None

    next_control = t0
    water = plant.water
    view_flow, view_return, view_flame, view_setpoint = water, water, False, water

    for step in range(steps):
        t = t0 + step * dt
        if int((t - t0) // DAY) != day:
            result.daily_ch_kwh.append(day_ch)
            day_ch = 0.0
            day = int((t - t0) // DAY)
        outdoor = scenario.outdoor(t - t0)
        if tpi is None:
            openings = plant.thermostatic_openings()
        else:
            openings = [
                tpi[z.zone_id].advance(t, plant.targets[i], plant.room[i], outdoor)
                for i, z in enumerate(zones)
            ]
        dhw = scenario.dhw is not None and scenario.dhw.active(t - t0)
        if scenario.controller is not None and t >= next_control:
            next_control = t + scenario.control_period_s
            view = SimView(
                view_flame,
                round(view_flow, 1),
                round(view_return, 1),
                dhw,
                round(outdoor, 1),
                round(view_setpoint, 1),
                tuple(
                    SimZoneView(
                        z.zone_id,
                        round(plant.room[i], 1),
                        z.target,
                        round(openings[i], 2),
                        None if tpi is None else tpi[z.zone_id].percent,
                    )
                    for i, z in enumerate(zones)
                ),
            )
            command = scenario.controller(t, view)
            if command is not None:
                result.commands += 1
                if command.hand_back:
                    plant.gateway_ch_off = False  # CH=1, then CS=0
                    plant.clear_override()
                else:
                    if command.ch_enable is not None:
                        plant.gateway_ch_off = not command.ch_enable
                    if command.setpoint is not None:
                        plant.set_setpoint(t, command.setpoint)
        out = plant.step(t, dt, outdoor, dhw, openings)
        if out.override:
            result.override_s += dt
        if demand is not None and out.demand != demand:
            result.ch_switchings += 1
        demand = out.demand
        result.burner_kwh += out.power_kw * dt_h
        result.ch_kwh += out.ch_power_kw * dt_h
        day_ch += out.ch_power_kw * dt_h
        result.emitted_kwh += out.emitted_kw * dt_h
        result.room_kwh += out.room_kw * dt_h

        view_flow, view_return, view_flame, view_setpoint = (
            out.flow,
            out.return_,
            out.flame,
            out.setpoint,
        )
        values: dict[Signal, float | bool] = {
            Signal.FLAME: out.flame,
            Signal.FLOW: round(out.flow, 1),
            Signal.RETURN: round(out.return_, 1),
            Signal.MODULATION: round(out.modulation),
            Signal.CH_SETPOINT: round(out.setpoint, 1),
            Signal.DHW_ACTIVE: dhw,
            Signal.PRESSURE: round(out.pressure, 2),
            Signal.FLUE_GAS: round(
                (out.return_ + 5.0 + out.modulation / 10.0)
                if boiler.condensing
                else (120.0 + out.modulation / 2.0 if out.flame else out.return_),
                1,
            ),
            Signal.OUTDOOR: round(outdoor, 1),
            Signal.CH_ACTIVE: out.demand and not dhw,
            Signal.PUMP_RUNNING: out.pump or dhw,
        }
        for signal in record:
            signals[signal].append(t, values[signal])
        weather.append(t, round(outdoor + scenario.weather_bias_k, 1))
        for i, z in enumerate(zones):
            series = zone_series[z.zone_id]
            series.temperature.append(t, round(plant.room[i], 1))
            series.target.append(t, z.target)
            series.heating_enabled.append(t, True)
            series.calling.append(t, openings[i] > DEMAND_OPENING)
            series.valve_open.append(t, round(openings[i], 2))

    if steps:
        result.daily_ch_kwh.append(day_ch)
    result.water_end = plant.water
    result.emitters_end_kwh = sum(plant.stored)
    return result


def entered_parameters(
    boiler: BoilerProfile, heating_threshold: float | None = None
) -> ParameterSet:
    """What a user would enter for the simulated boiler (from its manual)."""
    params = (
        ParameterSet()
        .with_estimate(ParameterKey.BOILER_MIN_POWER, Estimate(boiler.min_power_kw, Source.ENTERED))
        .with_estimate(ParameterKey.BOILER_MAX_POWER, Estimate(boiler.max_power_kw, Source.ENTERED))
        .with_estimate(ParameterKey.MAX_CH_SETPOINT, Estimate(boiler.max_setpoint, Source.ENTERED))
    )
    if heating_threshold is not None:
        params = params.with_estimate(
            ParameterKey.HEATING_THRESHOLD, Estimate(heating_threshold, Source.ENTERED)
        )
    return params
