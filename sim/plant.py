"""The simulated plant, one time step at a time: boiler, water loop, emitters and house.

Physics, deliberately simple:

- The water loop is one mass at mean temperature ``T_w``. Flow reads ``T_w + P / (2k)`` and
  return ``T_w − Q / (2k)``, with ``P`` the burner power, ``Q`` the emitters' output and ``k``
  the pump's flow times heat capacity.
- Each zone is a share of the house: its own heat capacity, loss to outdoors and internal gains.
- Emitters follow EN 442: ``Q = opening · P_ref · (excess / reference excess)^n``.
- Valves open proportionally below the setpoint (a thermostatic head), unless the openings come
  from outside (a zone thermostat driving the valve).
- The boiler follows its own weather curve, modulates towards the setpoint between its minimum
  and maximum power, stops at setpoint plus hysteresis and restarts at setpoint minus
  hysteresis after its anti-cycle time. A DHW run stops the burner while the diverter switches,
  then takes it at full power with the heating circulation stopped; heating resumes after the
  anti-cycle time.
- An external controller may override the setpoint and heating on/off; an override lapses
  after ``override_expires_s`` unless repeated (``None``: it holds until changed). Without an
  override the boiler follows its own curve and the valves' demand, or — a gateway acting as
  master without a thermostat — does not heat at all.

Used by ``sim.simulator`` for whole scenarios and by the test-only Home Assistant component.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from custom_components.vtherm_smart_boiler.core.emitters import EMITTER_REFERENCE

from .profiles import BoilerProfile, HouseProfile, ZoneProfile

HOUR = 3600.0
WATER_KWH_PER_L_K = 4.186 / 3600.0
DEMAND_OPENING = 0.05
MODULATION_TAU_S = 120.0


class WithoutOverride(StrEnum):
    """What the boiler does when no control override is active."""

    OWN_CURVE = "own_curve"  # its own weather curve, as with a thermostat or on its own
    OFF = "off"  # no heat: a gateway acting as master without a thermostat


@dataclass(frozen=True, slots=True)
class PlantOutput:
    """The plant after one step, unrounded."""

    flame: bool
    water: float  # mean loop temperature
    flow: float
    return_: float
    modulation: float
    setpoint: float  # the setpoint the boiler works to
    dhw: bool
    outdoor: float
    demand: bool  # heating demand the boiler acts on
    power_kw: float
    ch_power_kw: float
    emitted_kw: float
    openings: tuple[float, ...]
    override: bool  # an external override is in force

    @property
    def pressure(self) -> float:
        return 1.5 + 0.01 * (self.water - 20.0)


def boiler_setpoint(boiler: BoilerProfile, outdoor: float) -> float:
    raw = boiler.curve_offset + boiler.curve_slope * (20.0 - outdoor)
    return min(boiler.max_setpoint, max(boiler.min_setpoint, raw))


def reference_outputs(house: HouseProfile, zones: Sequence[ZoneProfile]) -> list[float]:
    design = house.design_load_kw()
    return [
        z.reference_output_kw
        if z.reference_output_kw is not None
        else z.share * design * z.oversize
        for z in zones
    ]


class Plant:
    """Boiler, water loop and house; advance it with ``step``."""

    def __init__(
        self,
        boiler: BoilerProfile,
        house: HouseProfile,
        zones: Sequence[ZoneProfile],
        water: float,
        override_expires_s: float | None = 60.0,
        without_override: WithoutOverride = WithoutOverride.OWN_CURVE,
    ) -> None:
        self.boiler = boiler
        self.house = house
        self.zones = tuple(zones)
        self.override_expires_s = override_expires_s
        self.without_override = without_override
        self.outputs = reference_outputs(house, self.zones)
        self.references = [EMITTER_REFERENCE[z.emitter] for z in self.zones]
        self.ref_excess = [(r.flow + r.return_) / 2.0 - r.room for r in self.references]
        self.water_capacity = boiler.water_volume_l * WATER_KWH_PER_L_K  # kWh/K
        self.room = [z.target for z in self.zones]
        self.targets = [z.target for z in self.zones]
        self.water = water
        self.burner = False
        self.last_stop = -math.inf
        self.dhw_since: float | None = None
        self.override_setpoint: float | None = None
        self.override_ch: bool | None = None
        self.override_at: float | None = None

    # --- the external controller --------------------------------------------------------

    def set_override(self, t: float, setpoint: float | None, ch_enable: bool | None) -> None:
        """An override from a controller; each call renews it."""
        if setpoint is not None:
            self.override_setpoint = setpoint
            self.override_at = t
        if ch_enable is not None:
            self.override_ch = ch_enable
            self.override_at = t

    def clear_override(self) -> None:
        self.override_setpoint = self.override_ch = self.override_at = None

    def override_active(self, t: float) -> bool:
        return self.override_at is not None and (
            self.override_expires_s is None or t - self.override_at <= self.override_expires_s
        )

    # --- zones ----------------------------------------------------------------------------

    def thermostatic_openings(self) -> list[float]:
        """Valve openings of thermostatic heads at the zones' targets."""
        openings = []
        for i, z in enumerate(self.zones):
            opening = (self.targets[i] + z.valve_band_k / 2.0 - self.room[i]) / z.valve_band_k
            openings.append(min(1.0, max(0.0, opening)))
        return openings

    # --- one step -------------------------------------------------------------------------

    def step(
        self,
        t: float,
        dt: float,
        outdoor: float,
        dhw: bool,
        openings: Sequence[float] | None = None,
    ) -> PlantOutput:
        boiler, house, zones = self.boiler, self.house, self.zones
        k = boiler.pump_flow_kw_per_k
        dt_h = dt / HOUR
        opened = list(self.thermostatic_openings() if openings is None else openings)
        active = self.override_active(t)
        if active:
            setpoint = (
                self.override_setpoint
                if self.override_setpoint is not None
                else boiler_setpoint(boiler, outdoor)
            )
            demand = self.override_ch if self.override_ch is not None else True
        elif self.without_override is WithoutOverride.OFF:
            setpoint = boiler_setpoint(boiler, outdoor)
            demand = False
        else:
            setpoint = boiler_setpoint(boiler, outdoor)
            demand = any(o > DEMAND_OPENING for o in opened)

        emitted = [0.0] * len(zones)
        ch_power = 0.0
        if dhw:
            # The burner stops while the diverter switches, then heats the tank at full power;
            # heating resumes only after the anti-cycle time once the DHW run ends.
            if self.dhw_since is None:
                self.dhw_since = t
            burner_now = t - self.dhw_since >= boiler.dhw_changeover_s
            power = boiler.max_power_kw if burner_now else 0.0
            flow = boiler.dhw_flow if burner_now else self.water
            return_ = boiler.dhw_flow - 15.0 if burner_now else self.water
            modulation = 100.0 if burner_now else 0.0
            self.burner = False
            self.last_stop = t
        else:
            self.dhw_since = None
            water = self.water
            if demand:
                for i in range(len(zones)):
                    excess = max(0.0, water - self.room[i])
                    factor = (excess / self.ref_excess[i]) ** self.references[i].exponent
                    emitted[i] = opened[i] * self.outputs[i] * factor
            total = sum(emitted)
            flow_now = water + (boiler.min_power_kw if self.burner else 0.0) / (2 * k)
            if self.burner and (not demand or flow_now > setpoint + boiler.hysteresis_off_k):
                self.burner = False
                self.last_stop = t
            elif (
                not self.burner
                and demand
                and water < setpoint - boiler.hysteresis_on_k
                and t - self.last_stop >= boiler.anti_cycle_s
            ):
                self.burner = True
            if self.burner:
                wanted = total + self.water_capacity * HOUR / MODULATION_TAU_S * (
                    setpoint - flow_now
                )
                power = min(boiler.max_power_kw, max(boiler.min_power_kw, wanted))
            else:
                power = 0.0
            burner_now = self.burner
            self.water += (power - total) * dt_h / self.water_capacity
            flow = self.water + power / (2 * k)
            return_ = self.water - total / (2 * k)
            span = boiler.max_power_kw - boiler.min_power_kw
            modulation = (power - boiler.min_power_kw) / span * 100.0 if self.burner else 0.0
            ch_power = power

        for i, z in enumerate(zones):
            loss = house.loss_kw_per_k * z.share * (self.room[i] - outdoor)
            gains = house.gains_kw * z.share
            self.room[i] += (
                (emitted[i] + gains - loss) * dt_h / (house.capacity_kwh_per_k * z.share)
            )

        return PlantOutput(
            flame=burner_now,
            water=self.water,
            flow=flow,
            return_=return_,
            modulation=modulation,
            setpoint=setpoint,
            dhw=dhw,
            outdoor=outdoor,
            demand=demand,
            power_kw=power,
            ch_power_kw=ch_power,
            emitted_kw=sum(emitted),
            openings=tuple(opened),
            override=active,
        )
