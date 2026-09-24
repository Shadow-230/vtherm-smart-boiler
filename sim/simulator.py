"""Time-stepped simulation producing the core's ``History``.

Physics, deliberately simple:

- The water loop is one mass at mean temperature ``T_w``. Flow reads ``T_w + P / (2k)`` and
  return ``T_w − Q / (2k)``, with ``P`` the burner power, ``Q`` the emitters' output and ``k``
  the pump's flow times heat capacity.
- Each zone is a share of the house: its own heat capacity, loss to outdoors and internal gains.
- Emitters follow EN 442: ``Q = opening · P_ref · (excess / reference excess)^n``.
- Valves open proportionally below the setpoint (a thermostatic head).
- The boiler follows its own weather curve, modulates towards the setpoint between its minimum
  and maximum power, stops at setpoint plus hysteresis and restarts at setpoint minus
  hysteresis after its anti-cycle time. A DHW run stops the burner while the diverter switches,
  then takes it at full power with the heating circulation stopped; heating resumes after the
  anti-cycle time.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from custom_components.vtherm_smart_boiler.core.emitters import EMITTER_REFERENCE
from custom_components.vtherm_smart_boiler.core.history import History, ZoneSeries
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.series import Series
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .profiles import BoilerProfile, HouseProfile, ZoneProfile

HOUR = 3600.0
DAY = 86400.0
WATER_KWH_PER_L_K = 4.186 / 3600.0
DEMAND_OPENING = 0.05
MODULATION_TAU_S = 120.0

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


@dataclass
class SimResult:
    history: History
    burner_kwh: float = 0.0  # all burner output
    ch_kwh: float = 0.0  # burner output for heating
    emitted_kwh: float = 0.0  # delivered by the emitters
    water_start: float = 0.0
    water_end: float = 0.0
    daily_ch_kwh: list[float] = field(default_factory=list)


def reference_outputs(scenario: Scenario) -> list[float]:
    design = scenario.house.design_load_kw()
    return [
        z.reference_output_kw
        if z.reference_output_kw is not None
        else z.share * design * z.oversize
        for z in scenario.zones
    ]


def boiler_setpoint(boiler: BoilerProfile, outdoor: float) -> float:
    raw = boiler.curve_offset + boiler.curve_slope * (20.0 - outdoor)
    return min(boiler.max_setpoint, max(boiler.min_setpoint, raw))


def simulate(scenario: Scenario) -> SimResult:
    boiler, house, zones = scenario.boiler, scenario.house, scenario.zones
    k = boiler.pump_flow_kw_per_k
    water_capacity = boiler.water_volume_l * WATER_KWH_PER_L_K  # kWh/K
    outputs = reference_outputs(scenario)
    references = [EMITTER_REFERENCE[z.emitter] for z in zones]
    ref_excess = [(r.flow + r.return_) / 2.0 - r.room for r in references]

    dt = scenario.step_s
    dt_h = dt / HOUR
    steps = round(scenario.days * DAY / dt)
    t0 = scenario.start

    room = [z.target for z in zones]
    water = boiler_setpoint(boiler, scenario.outdoor(t0)) - 5.0
    burner = False
    last_stop = -math.inf
    dhw_since: float | None = None

    record = scenario.signals
    signals: dict[Signal, Series] = {s: Series() for s in record}
    zone_series = {z.zone_id: ZoneSeries(z.zone_id) for z in zones}
    weather: Series[float] = Series()
    result = SimResult(History(signals, zone_series, weather), water_start=water)
    day_ch = 0.0

    for step in range(steps):
        t = t0 + step * dt
        outdoor = scenario.outdoor(t - t0)
        setpoint = boiler_setpoint(boiler, outdoor)
        openings = [
            min(1.0, max(0.0, (z.target + z.valve_band_k / 2.0 - room[i]) / z.valve_band_k))
            for i, z in enumerate(zones)
        ]
        demand = any(o > DEMAND_OPENING for o in openings)
        dhw = scenario.dhw is not None and scenario.dhw.active(t - t0)

        emitted = [0.0] * len(zones)
        if dhw:
            # The burner stops while the diverter switches, then heats the tank at full power;
            # heating resumes only after the anti-cycle time once the DHW run ends.
            if dhw_since is None:
                dhw_since = t
            burner_now = t - dhw_since >= boiler.dhw_changeover_s
            power = boiler.max_power_kw if burner_now else 0.0
            flow = boiler.dhw_flow if burner_now else water
            return_ = boiler.dhw_flow - 15.0 if burner_now else water
            modulation = 100.0 if burner_now else 0.0
            burner = False
            last_stop = t
        else:
            dhw_since = None
            if demand:
                for i in range(len(zones)):
                    excess = max(0.0, water - room[i])
                    factor = (excess / ref_excess[i]) ** references[i].exponent
                    emitted[i] = openings[i] * outputs[i] * factor
            total = sum(emitted)
            flow_now = water + (boiler.min_power_kw if burner else 0.0) / (2 * k)
            if burner and (not demand or flow_now > setpoint + boiler.hysteresis_off_k):
                burner = False
                last_stop = t
            elif (
                not burner
                and demand
                and water < setpoint - boiler.hysteresis_on_k
                and t - last_stop >= boiler.anti_cycle_s
            ):
                burner = True
            if burner:
                wanted = total + water_capacity * HOUR / MODULATION_TAU_S * (setpoint - flow_now)
                power = min(boiler.max_power_kw, max(boiler.min_power_kw, wanted))
            else:
                power = 0.0
            burner_now = burner
            water += (power - total) * dt_h / water_capacity
            flow = water + power / (2 * k)
            return_ = water - total / (2 * k)
            span = boiler.max_power_kw - boiler.min_power_kw
            modulation = (power - boiler.min_power_kw) / span * 100.0 if burner else 0.0
            result.ch_kwh += power * dt_h
            day_ch += power * dt_h
        result.burner_kwh += power * dt_h
        result.emitted_kwh += sum(emitted) * dt_h

        for i, z in enumerate(zones):
            loss = house.loss_kw_per_k * z.share * (room[i] - outdoor)
            gains = house.gains_kw * z.share
            room[i] += (emitted[i] + gains - loss) * dt_h / (house.capacity_kwh_per_k * z.share)

        values: dict[Signal, float | bool] = {
            Signal.FLAME: burner_now,
            Signal.FLOW: round(flow, 1),
            Signal.RETURN: round(return_, 1),
            Signal.MODULATION: round(modulation),
            Signal.CH_SETPOINT: round(setpoint, 1),
            Signal.DHW_ACTIVE: dhw,
            Signal.PRESSURE: round(1.5 + 0.01 * (water - 20.0), 2),
            Signal.FLUE_GAS: round(
                (return_ + 5.0 + modulation / 10.0)
                if boiler.condensing
                else (120.0 + modulation / 2.0 if burner_now else return_),
                1,
            ),
            Signal.OUTDOOR: round(outdoor, 1),
            Signal.CH_ACTIVE: demand and not dhw,
            Signal.PUMP_RUNNING: demand or dhw,
        }
        for signal in record:
            signals[signal].append(t, values[signal])
        weather.append(t, round(outdoor + scenario.weather_bias_k, 1))
        for i, z in enumerate(zones):
            series = zone_series[z.zone_id]
            series.temperature.append(t, round(room[i], 1))
            series.target.append(t, z.target)
            series.heating_enabled.append(t, True)
            series.calling.append(t, openings[i] > DEMAND_OPENING)
            series.valve_open.append(t, round(openings[i], 2))

        if (step + 1) * dt % DAY == 0:
            result.daily_ch_kwh.append(day_ch)
            day_ch = 0.0

    result.water_end = water
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
