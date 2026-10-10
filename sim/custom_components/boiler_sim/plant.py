"""The simulated plant, one time step at a time: boiler, water loop, emitters and house.

Physics, deliberately simple:

- The water loop is one mass at mean temperature ``T_w``. Flow reads ``T_w + P / (2k)`` and
  return ``T_w − Q / (2k)``, with ``P`` the burner power, ``Q`` the heat the emitters take from
  the water and ``k`` the pump's flow times heat capacity.
- Each zone is a share of the house: its own heat capacity, loss to outdoors and internal gains.
- Emitters take heat from the water by EN 442 — ``Q = opening · P_ref · (excess / reference
  excess)^n`` — while the pump circulates, and pass it on to their room with first-order inertia
  (``EMITTER_TAU_S``: a radiator about 20 minutes, underfloor heating about 2 hours; test-only
  values): a room still gets heat for a while after its valve closed, and gets it late after the
  valve opened (P-112).
- Valves open proportionally below the setpoint (a thermostatic head), unless the openings come
  from outside (a zone thermostat driving the valve).
- The boiler holds its flow at the setpoint (P-112): it modulates between its minimum and maximum
  power so that the flow it reports reaches the setpoint — no auxiliary flow above it. Where the
  load is below its minimum power the flow rises at the minimum: the burner stops once the flow
  is ``hysteresis_off_k`` above the setpoint and starts again once the water is
  ``hysteresis_on_k`` below it, no sooner than ``anti_cycle_s`` after it stopped (its restart
  lockout). The pump runs on for ``pump_overrun_s`` after the heating demand ends. A DHW run stops
  the burner while the diverter switches, then takes it at full power with the heating
  circulation stopped; heating resumes after the restart lockout. A fault the boiler reports as
  stopping it keeps the burner off.
- An external controller may override the setpoint (a gateway's ``CS``, or a writable setpoint
  entity); the override lapses after ``override_expires_s`` unless repeated (``holds``: it holds
  until changed). A heating switch has a write type of its own and never renews the setpoint's
  override (an EMS-ESP-like device; Open after R6 #2). A gateway's ``CH=0`` is a flag of its own
  (PIC 6.6): it masks CH enable under any later override, and the demand of an on/off contact,
  until ``CH=1`` or a gateway reset — an OpenTherm thermostat's own CH bit passes again without an
  override.
- Without an override the boiler follows what asks it for heat (``Request``): a wall thermostat
  through a gateway, or a contact on its room-thermostat terminals (a relay); with none, its own
  curve and the valves' demand — or, a gateway acting as master without a thermostat, no heat.

Used by ``sim.simulator`` for whole scenarios and by the test-only Home Assistant component.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from custom_components.vtherm_smart_boiler.core.emitters import EMITTER_REFERENCE
from custom_components.vtherm_smart_boiler.core.installation import EmitterType

from .profiles import BoilerProfile, HouseProfile, ZoneProfile

HOUR = 3600.0
WATER_KWH_PER_L_K = 4.186 / 3600.0
DEMAND_OPENING = 0.05
MODULATION_TAU_S = 120.0
# Emitter inertia (P-112; test-only values): the time constant with which an emitter passes the
# heat it takes from the water on to its room. A convector is given a radiator's (assumed: the
# review names radiators and underfloor heating only).
EMITTER_TAU_S: dict[EmitterType, float] = {
    EmitterType.RADIATOR: 20 * 60.0,
    EmitterType.CONVECTOR: 20 * 60.0,
    EmitterType.UNDERFLOOR: 2 * HOUR,
}


class WithoutOverride(StrEnum):
    """What the boiler does when no control override is active."""

    OWN_CURVE = "own_curve"  # its own weather curve, as with a thermostat or on its own
    OFF = "off"  # no heat: a gateway acting as master without a thermostat


@dataclass(frozen=True, slots=True)
class Request:
    """What asks the boiler for heat when nothing overrides it: a wall thermostat through a
    gateway, or a contact on its room-thermostat terminals (a relay).

    ``setpoint``: the water temperature asked for (an OpenTherm thermostat's ``CS``, or a closed
    on/off contact's maximum); ``None``: the boiler's own curve, or its dial. ``masked``: the
    gateway's ``CH=0`` masks the demand — an on/off contact's; an OpenTherm thermostat's own CH
    bit passes (PIC 6.6)."""

    demand: bool
    setpoint: float | None = None
    masked: bool = True


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
    demand: bool  # heating demand the boiler acts on (the CH enable it gets)
    power_kw: float
    ch_power_kw: float
    emitted_kw: float  # the heat the emitters take from the water
    openings: tuple[float, ...]
    override: bool  # an external setpoint override is in force
    pump: bool = False  # the pump circulates the heating water (demand, or its overrun)
    room_kw: float = 0.0  # the heat the emitters pass on to the rooms
    lockout: bool = False  # the restart lockout holds the burner off

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
        # A gateway's CH=0 (PIC 6.6 CHModeOff): it survives CS=0 and the override's lapse until
        # CH=1 or a gateway reset, masking CH enable under a CS override and the demand of an
        # on/off contact; an OpenTherm thermostat's own CH bit passes (``Request.masked``).
        self.gateway_ch_off = False
        self.max_modulation: float | None = None  # a gateway's MM=, 0–100 % of the range
        self.fault = False  # a fault the boiler reports as stopping it
        # PB-91: the boiler itself ignoring an override it was sent, or taking none above its own
        # limit; a gateway in between still sends, and shows, the commanded value.
        self.boiler_ignores_override = False
        self.boiler_clip: float | None = None
        self.outputs = reference_outputs(house, self.zones)
        self.references = [EMITTER_REFERENCE[z.emitter] for z in self.zones]
        self.ref_excess = [(r.flow + r.return_) / 2.0 - r.room for r in self.references]
        self.taus = [EMITTER_TAU_S[z.emitter] / HOUR for z in self.zones]  # hours
        self.water_capacity = boiler.water_volume_l * WATER_KWH_PER_L_K  # kWh/K
        self.room = [z.target for z in self.zones]
        self.targets = [z.target for z in self.zones]
        self.stored = [0.0] * len(self.zones)  # heat in each emitter on its way to the room, kWh
        self.water = water
        self.burner = False
        self.power = 0.0
        self.last_stop = -math.inf
        self.had_demand = False
        self.demand_end: float | None = None  # when the heating demand last ended (pump overrun)
        self.dhw_since: float | None = None
        self.override_setpoint: float | None = None
        self.override_at: float | None = None
        self.override_holds = False
        self.heating: bool | None = None  # a heating switch's last value (its own write type)
        self.heating_at: float | None = None
        self.heating_holds = False

    # --- the external controller --------------------------------------------------------

    def set_setpoint(self, t: float, setpoint: float, holds: bool = False) -> None:
        """A setpoint override; each call renews it. ``holds``: it never lapses (a stored or held
        value, or an OTGW control setpoint below 8 °C)."""
        self.override_setpoint = setpoint
        self.override_at = t
        self.override_holds = holds

    def clear_override(self) -> None:
        """The setpoint override released (``CS=0``, a hand-back value, external control off)."""
        self.override_setpoint = self.override_at = None
        self.override_holds = False

    def override_active(self, t: float) -> bool:
        if self.override_at is None:
            return False
        return (
            self.override_holds
            or self.override_expires_s is None
            or t - self.override_at <= self.override_expires_s
        )

    def set_heating(self, t: float, on: bool, holds: bool) -> None:
        """A heating switch, with its own write type: ``holds`` — kept until changed (held, or
        stored) — or lapsing after ``override_expires_s`` unless repeated. It never renews the
        setpoint's override."""
        self.heating = on
        self.heating_at = t
        self.heating_holds = holds

    def heating_allowed(self, t: float) -> bool | None:
        """The heating switch in force: ``None`` when never written or lapsed."""
        if self.heating is None or self.heating_at is None:
            return None
        if (
            self.heating_holds
            or self.override_expires_s is None
            or t - self.heating_at <= self.override_expires_s
        ):
            return self.heating
        return None

    def reset_gateway(self) -> None:
        """A gateway reset: its overrides and flags are lost (``CS``, ``CH``, ``MM``)."""
        self.clear_override()
        self.gateway_ch_off = False
        self.max_modulation = None

    def settle(self, outdoor: float) -> None:
        """A neutral start: each emitter holds the heat that passes its room's loss at the
        room's temperature now, so no room warms or cools merely because the run began."""
        house = self.house
        for i, z in enumerate(self.zones):
            loss = house.loss_kw_per_k * z.share * (self.room[i] - outdoor)
            self.stored[i] = max(0.0, loss - house.gains_kw * z.share) * self.taus[i]

    # --- zones ----------------------------------------------------------------------------

    def thermostatic_openings(self) -> list[float]:
        """Valve openings of thermostatic heads at the zones' targets."""
        openings = []
        for i, z in enumerate(self.zones):
            opening = (self.targets[i] + z.valve_band_k / 2.0 - self.room[i]) / z.valve_band_k
            openings.append(min(1.0, max(0.0, opening)))
        return openings

    # --- one step -------------------------------------------------------------------------

    def _wanted(
        self, t: float, outdoor: float, opened: Sequence[float], request: Request | None
    ) -> tuple[float, bool, bool]:
        """The setpoint the boiler works to, its heating demand and whether an override holds."""
        boiler = self.boiler
        active = self.override_active(t)
        if active and self.override_setpoint is not None and not self.boiler_ignores_override:
            setpoint = self.override_setpoint
            if self.boiler_clip is not None:
                setpoint = min(setpoint, self.boiler_clip)
            demand = not self.gateway_ch_off
        elif request is not None:
            setpoint = (
                boiler_setpoint(boiler, outdoor) if request.setpoint is None else (request.setpoint)
            )
            demand = request.demand and not (request.masked and self.gateway_ch_off)
        elif self.without_override is WithoutOverride.OFF:
            setpoint = boiler_setpoint(boiler, outdoor)
            demand = False
        else:
            setpoint = boiler_setpoint(boiler, outdoor)
            demand = any(o > DEMAND_OPENING for o in opened) and not self.gateway_ch_off
        if self.heating_allowed(t) is False:
            demand = False  # the heating switch off: the boiler's heating disabled
        return setpoint, demand, active

    def _power_for(self, load: float, setpoint: float) -> float:
        """The power that brings the flow to the setpoint: the flow is ``T_w + P / (2k)``, and
        the regulation adds ``g`` kW per kelvin the flow lacks, so
        ``P = (Q + g (SP − T_w)) / (1 + g / 2k)`` — the flow reads the setpoint once the water
        has settled; clamped to the boiler's range and the gateway's modulation cap."""
        boiler = self.boiler
        k = boiler.pump_flow_kw_per_k
        gain = self.water_capacity * HOUR / MODULATION_TAU_S
        wanted = (load + gain * (setpoint - self.water)) / (1.0 + gain / (2.0 * k))
        top = boiler.max_power_kw
        if self.max_modulation is not None:
            span = boiler.max_power_kw - boiler.min_power_kw
            top = boiler.min_power_kw + span * max(0.0, min(100.0, self.max_modulation)) / 100.0
        return min(top, max(boiler.min_power_kw, wanted))

    def step(
        self,
        t: float,
        dt: float,
        outdoor: float,
        dhw: bool,
        openings: Sequence[float] | None = None,
        request: Request | None = None,
    ) -> PlantOutput:
        boiler, house, zones = self.boiler, self.house, self.zones
        k = boiler.pump_flow_kw_per_k
        dt_h = dt / HOUR
        opened = list(self.thermostatic_openings() if openings is None else openings)
        setpoint, demand, active = self._wanted(t, outdoor, opened, request)
        if demand:
            self.demand_end = None
        elif self.had_demand:
            self.demand_end = t  # the heating demand ends now: the pump runs on
        self.had_demand = demand
        overrun = self.demand_end is not None and t - self.demand_end < boiler.pump_overrun_s
        pump = demand or overrun

        taken = [0.0] * len(zones)
        ch_power = 0.0
        lockout = False
        if dhw:
            # The burner stops while the diverter switches, then heats the tank at full power;
            # heating resumes only after the restart lockout once the DHW run ends.
            if self.dhw_since is None:
                self.dhw_since = t
            burner_now = t - self.dhw_since >= boiler.dhw_changeover_s and not self.fault
            power = boiler.max_power_kw if burner_now else 0.0
            flow = boiler.dhw_flow if burner_now else self.water
            return_ = boiler.dhw_flow - 15.0 if burner_now else self.water
            modulation = 100.0 if burner_now else 0.0
            self.burner = False
            self.power = 0.0
            self.last_stop = t
            pump = False  # the circulation goes to the tank
        else:
            self.dhw_since = None
            water = self.water
            if pump:
                for i in range(len(zones)):
                    excess = max(0.0, water - self.room[i])
                    factor = (excess / self.ref_excess[i]) ** self.references[i].exponent
                    taken[i] = opened[i] * self.outputs[i] * factor
            load = sum(taken)
            if self.burner:
                power = self._power_for(load, setpoint)
                too_hot = (
                    power <= boiler.min_power_kw
                    and water + power / (2 * k) > setpoint + boiler.hysteresis_off_k
                )
                if not demand or self.fault or too_hot:
                    self.burner = False
                    self.last_stop = t
            elif demand and not self.fault and water < setpoint - boiler.hysteresis_on_k:
                if t - self.last_stop >= boiler.anti_cycle_s:
                    self.burner = True
                else:
                    lockout = True
            power = self._power_for(load, setpoint) if self.burner else 0.0
            self.power = power
            burner_now = self.burner
            self.water += (power - load) * dt_h / self.water_capacity
            flow = self.water + power / (2 * k)
            return_ = self.water - load / (2 * k)
            span = boiler.max_power_kw - boiler.min_power_kw
            modulation = (power - boiler.min_power_kw) / span * 100.0 if self.burner else 0.0
            ch_power = power

        given = [0.0] * len(zones)
        for i, z in enumerate(zones):
            # Into the emitter from the water, out of it into the room (first order).
            given[i] = self.stored[i] / self.taus[i]
            self.stored[i] = max(0.0, self.stored[i] + (taken[i] - given[i]) * dt_h)
            loss = house.loss_kw_per_k * z.share * (self.room[i] - outdoor)
            gains = house.gains_kw * z.share
            self.room[i] += (given[i] + gains - loss) * dt_h / (house.capacity_kwh_per_k * z.share)

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
            emitted_kw=sum(taken),
            openings=tuple(opened),
            override=active,
            pump=pump,
            room_kw=sum(given),
            lockout=lockout,
        )
