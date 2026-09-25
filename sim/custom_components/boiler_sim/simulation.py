"""The simulated installation behind the test component; no Home Assistant imports.

It wraps the plant (``plant``) with what a real installation adds around it: how writes
reach the boiler (an OpenTherm-Gateway-like command path or a writable setpoint of a given write
type, an external-control switch), zone valves driven by zone thermostats or thermostatic heads,
hot water runs, and faults for scenarios — a failed signal, another controller writing, a boiler
ignoring writes. It records every command it receives.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum

from .plant import Plant, PlantOutput, WithoutOverride
from .profiles import (
    BOILERS,
    HOUSES,
    ZoneProfile,
    radiator_zones,
    shared_loop_zones,
    underfloor_zones,
)

GATEWAY_MIN_EXPIRING = 8.0  # an OTGW control setpoint below this (and above 0) never lapses
MAX_STEP_S = 10.0
ZONE_LAYOUTS: dict[str, Callable[[], tuple[ZoneProfile, ...]]] = {
    "radiators": radiator_zones,
    "underfloor": underfloor_zones,
    "shared_loop": shared_loop_zones,
}


class Topology(StrEnum):
    WITH_THERMOSTAT = "with_thermostat"  # without an override the boiler follows its own curve
    STANDALONE = "standalone"  # without an override the boiler does not heat


class WriteType(StrEnum):
    EXPIRING = "expiring"
    PERSISTENT = "persistent"
    HELD = "held"


class Valves(StrEnum):
    THERMOSTATIC = "thermostatic"  # heads at each zone's target
    SWITCH = "switch"  # a switch per zone, e.g. VT's underlying heater


@dataclass(frozen=True, slots=True)
class SimConfig:
    boiler: str = "condensing_small"
    house: str = "average"
    zones: str = "radiators"
    valves: Valves = Valves.THERMOSTATIC
    topology: Topology = Topology.WITH_THERMOSTAT
    write_type: WriteType = WriteType.EXPIRING
    outdoor: float = 3.0
    override_expires_s: float = 60.0
    hand_back_value: float = 0.0  # a write of this value to the setpoint entity hands back


@dataclass
class Commands:
    """Every command the boiler received, by path, with its time."""

    gateway: list[tuple[float, str, object]] = field(default_factory=list)
    entity: list[tuple[float, str, object]] = field(default_factory=list)
    persistent_writes: int = 0
    dhw_enable_writes: int = 0


class Simulation:
    def __init__(self, config: SimConfig, now: float) -> None:
        self.config = config
        self.zones = ZONE_LAYOUTS[config.zones]()
        boiler = BOILERS[config.boiler]
        without = (
            WithoutOverride.OFF
            if config.topology is Topology.STANDALONE
            else WithoutOverride.OWN_CURVE
        )
        self.plant = Plant(
            boiler,
            HOUSES[config.house],
            self.zones,
            water=35.0,
            override_expires_s=config.override_expires_s,
            without_override=without,
        )
        self.outdoor = config.outdoor
        self.valves = {z.zone_id: False for z in self.zones}
        self.failed: set[str] = set()
        self.forced: float | None = None  # another controller keeps writing this setpoint
        self.ignore_writes = False  # the boiler ignores every write
        self.external_control = True  # the switch that lets writes through
        self.dhw_until: float | None = None
        self.dhw_enable = True
        self.commands = Commands()
        self.t = now
        self.last: PlantOutput = self.plant.step(now, 0.0, self.outdoor, False, self._openings())

    # --- time -----------------------------------------------------------------------------

    def advance(self, now: float) -> PlantOutput:
        """Step the plant up to ``now`` in steps of at most ``MAX_STEP_S``; without time passing,
        a step of zero length takes in a command at once, as a gateway reports it back."""
        if now - self.t <= 1e-9:
            self._step(0.0)
        while now - self.t > 1e-9:
            dt = min(MAX_STEP_S, now - self.t)
            self.t += dt
            self._step(dt)
        return self.last

    def _step(self, dt: float) -> None:
        if self.forced is not None:
            self.plant.set_override(self.t, self.forced, None)
        dhw = self.dhw_until is not None and self.t < self.dhw_until
        self.last = self.plant.step(self.t, dt, self.outdoor, dhw, self._openings())

    def _openings(self) -> list[float] | None:
        if self.config.valves is Valves.THERMOSTATIC:
            return None
        return [1.0 if self.valves[z.zone_id] else 0.0 for z in self.zones]

    # --- command paths ----------------------------------------------------------------------

    def gateway_setpoint(self, now: float, value: float) -> None:
        """``CS=``: 0 cancels; 8 °C or more lapses unless repeated; below 8 °C never lapses."""
        self.commands.gateway.append((now, "setpoint", value))
        if self.ignore_writes:
            return
        if value == 0:
            self.plant.clear_override()
        else:
            self.plant.set_override(now, value, None, holds=value < GATEWAY_MIN_EXPIRING)

    def gateway_heating(self, now: float, on: bool) -> None:
        """``CH=``: sets or clears the gateway's CH-off flag (PIC 6.6), which survives ``CS=0``
        until ``CH=1``; it does not renew the control setpoint's one-minute vigilance."""
        self.commands.gateway.append((now, "ch", on))
        if self.ignore_writes:
            return
        self.plant.gateway_ch_off = not on

    def gateway_hot_water(self, now: float, value: object) -> None:
        """``HW=``: stored in the gateway's memory; the plugin must never send it."""
        self.commands.gateway.append((now, "hot_water", value))
        self.commands.dhw_enable_writes += 1
        self.dhw_enable = value not in (0, "0", False)

    def entity_setpoint(self, now: float, value: float) -> None:
        self.commands.entity.append((now, "setpoint", value))
        if self.config.write_type is not WriteType.EXPIRING:
            self.commands.persistent_writes += 1
        if self.ignore_writes or not self.external_control:
            return
        if value == self.config.hand_back_value:
            self.plant.clear_override()
        else:
            holds = self.config.write_type is not WriteType.EXPIRING
            self.plant.set_override(now, value, None, holds=holds)

    def entity_heating(self, now: float, on: bool) -> None:
        self.commands.entity.append((now, "ch", on))
        if self.ignore_writes or not self.external_control:
            return
        holds = self.config.write_type is not WriteType.EXPIRING
        self.plant.set_override(now, None, on, holds=holds)

    def set_external_control(self, now: float, on: bool) -> None:
        self.commands.entity.append((now, "external_control", on))
        self.external_control = on
        if not on:
            self.plant.clear_override()

    # --- scenarios --------------------------------------------------------------------------

    def start_dhw(self, now: float, minutes: float) -> None:
        self.dhw_until = now + minutes * 60.0

    def set_topology(self, topology: Topology) -> None:
        self.plant.without_override = (
            WithoutOverride.OFF if topology is Topology.STANDALONE else WithoutOverride.OWN_CURVE
        )

    def set_zone_target(self, zone_id: str, target: float) -> None:
        index = [z.zone_id for z in self.zones].index(zone_id)
        self.plant.targets[index] = target

    def room(self, zone_id: str) -> float:
        return self.plant.room[[z.zone_id for z in self.zones].index(zone_id)]

    def opening(self, zone_id: str) -> float:
        index = [z.zone_id for z in self.zones].index(zone_id)
        return self.last.openings[index]
