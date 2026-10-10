"""The simulated installation behind the test component; no Home Assistant imports.

It wraps the plant (``plant``) with what a real installation adds around it:

- how writes reach the boiler: an OpenTherm-Gateway-like command path (``CS``, ``CH``, ``MM``,
  ``HW`` and transparent commands, a gateway reset), whose read-back shows what
  ``opentherm_gw`` shows — the gateway's acknowledgement at once, then what the boiler gets at
  the next exchange: a boiler that refuses ID 1 drops the override there (the PIC clears it
  without a message), so it reads "confirmed, then dropped" (Open after R6 #2); a writable
  setpoint of a given write type with an external-control switch; a heating switch with a write
  type of its own, which never renews the setpoint's override (an EMS-ESP-like device); a relay
  on an on/off boiler's room-thermostat terminals (``relay``);
- zone valves: thermostatic heads, switches driven from outside (VT's thermostats in the test
  Home Assistant), or switches driven by a TPI stand-in for VT (``tpi``, P-114); a zone VT
  switched off closes its valve, one in VT's "sleep" holds it open (S-05);
- a wall thermostat on the gateway, with its own setting and program (``thermostat``);
- hot water runs, faults the boiler reports as stopping it, and faults for scenarios — a failed
  signal, another controller writing, a boiler ignoring writes.

It records every command it receives; only writes of type persistent count as persistent, and
heating on/off writes have their own counter (P-113).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import StrEnum

from .plant import HOUR, Plant, PlantOutput, Request, WithoutOverride, boiler_setpoint
from .profiles import (
    BOILERS,
    HOUSES,
    ZoneProfile,
    radiator_zones,
    shared_loop_zones,
    underfloor_zones,
)
from .relay import RelayModel, StartUp
from .thermostat import WallKind, WallThermostat
from .tpi import TpiConfig, TpiZone

GATEWAY_MIN_EXPIRING = 8.0  # an OTGW control setpoint below this (and above 0) never lapses
GATEWAY_RESET_S = 10.0  # a gateway restarting is out of reach this long (test-only)
# After a reset the gateway shows the water pressure as 0.0 until its own poll reads it again
# (L3: a PIC reset zeroes its stored values). The poll's interval is assumed (test-only).
GATEWAY_PRESSURE_POLL_S = 60.0
MAX_STEP_S = 10.0
# A clock that jumps further than this (a test's frozen clock released at its end, a host waking
# up) is not stepped through in full: only its last ``MAX_CATCH_UP_S`` is simulated.
MAX_CATCH_UP_S = 6 * HOUR
ZONE_LAYOUTS: dict[str, Callable[[], tuple[ZoneProfile, ...]]] = {
    "radiators": radiator_zones,
    "underfloor": underfloor_zones,
    "shared_loop": shared_loop_zones,
}
FAULTS = ("low_pressure_fault", "boiler_lockout")  # each stops the boiler while it holds
# PB-93: the boiler's signals an OpenTherm Gateway carries (its boiler and thermostat devices);
# the failed signal "gateway_all" takes them with the gateway, as a lost gateway link does. The
# weather, the pump and the relay are not read through it.
GATEWAY_CARRIED = frozenset(
    {
        "flame",
        "flow",
        "return",
        "modulation",
        "ch_setpoint",
        "dhw_active",
        "pressure",
        "outdoor",
        "ch_active",
        "thermostat_setpoint",
        *FAULTS,
        "fault_indication",
    }
)


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
    TPI = "tpi"  # a switch per zone driven by a TPI stand-in for VT


class ZoneMode(StrEnum):
    """A zone as VT has it: heating, off — its valve closed (S-05) — or VT's "sleep", which shows
    off with its valve held open."""

    HEAT = "heat"
    OFF = "off"
    SLEEP = "sleep"


@dataclass(frozen=True, slots=True)
class RelaySetup:
    """The relay's own settings in the model (``relay.RelayModel``)."""

    start_up: StartUp = StartUp.OFF
    off_timer_s: float | None = None
    timer_restarts_on_repeat: bool = True
    assumed_state: bool = False


@dataclass(frozen=True, slots=True)
class SimConfig:
    boiler: str = "condensing_small"
    house: str = "average"
    zones: str = "radiators"
    valves: Valves = Valves.THERMOSTATIC
    topology: Topology = Topology.WITH_THERMOSTAT
    write_type: WriteType = WriteType.EXPIRING
    # The heating switch's own write type: a device keeps it (ESPHome's switch, EMS-ESP's
    # "heating off") — Open after R6 #2.
    ch_write_type: WriteType = WriteType.HELD
    outdoor: float = 3.0
    override_expires_s: float = 60.0
    hand_back_value: float = 0.0  # a write of this value to the setpoint entity hands back
    wall_thermostat: WallKind | None = None  # a wall thermostat on the gateway's terminals
    relay: RelaySetup | None = None  # an on/off boiler switched by a relay
    restart_lockout_s: float | None = None  # the boiler profile's own, unless given
    tpi: TpiConfig = field(default_factory=TpiConfig)


@dataclass
class Commands:
    """Every command the boiler received, by path, with its time."""

    gateway: list[tuple[float, str, object]] = field(default_factory=list)
    entity: list[tuple[float, str, object]] = field(default_factory=list)
    persistent_writes: int = 0  # writes of type persistent only (P-113)
    ch_writes: int = 0  # heating on/off writes, through the gateway or an entity (P-113)
    dhw_enable_writes: int = 0


class Simulation:
    def __init__(self, config: SimConfig, now: float) -> None:
        self.config = config
        self.topology = config.topology  # switched by ``set_topology`` (PB-89)
        self.zones = ZONE_LAYOUTS[config.zones]()
        self._index = {z.zone_id: i for i, z in enumerate(self.zones)}
        boiler = BOILERS[config.boiler]
        if config.restart_lockout_s is not None:
            boiler = replace(boiler, anti_cycle_s=config.restart_lockout_s)
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
        self.plant.settle(config.outdoor)
        self.outdoor = config.outdoor
        self.valves = {z.zone_id: False for z in self.zones}
        self.modes = {z.zone_id: ZoneMode.HEAT for z in self.zones}
        self.tpi = {z.zone_id: TpiZone(config.tpi) for z in self.zones}
        self.failed: set[str] = set()
        self.forced: float | None = None  # another controller keeps writing this setpoint
        self.ignore_writes = False  # every write dropped before the boiler, unacknowledged
        self.refuses_id1 = False  # the boiler answers ID 1 with Data-Invalid: the PIC drops CS
        # No setpoint above this, shown in the acknowledgement (a device's own limit); a limit in
        # the boiler behind a gateway is ``plant.boiler_clip`` (PB-91).
        self.clip: float | None = None
        self.device_away_until: float | None = None  # a held device restarting (entity path)
        self.device_restarts = 0  # each loses what the device was given
        self.external_control = True  # the switch that lets writes through
        self.dhw_until: float | None = None
        self.dhw_enable = True
        self.faults: set[str] = set()
        self.gateway_ack: float | None = None  # the gateway's acknowledgement, until the exchange
        self.gateway_away_until: float | None = None  # a gateway reset in progress
        self.gateway_pressure_from: float | None = None  # 0.0 bar shown before this, after a reset
        self.gateway_fault_flags: set[str] = set()  # the fault flags the gateway last read
        relay = config.relay
        self.relay = (
            None
            if relay is None
            else RelayModel(
                start_up=relay.start_up,
                off_timer_s=relay.off_timer_s,
                timer_restarts_on_repeat=relay.timer_restarts_on_repeat,
                assumed_state=relay.assumed_state,
            )
        )
        wall = config.wall_thermostat
        self.wall = None if wall is None else WallThermostat(wall)
        self.commands = Commands()
        self.t = now
        self.last: PlantOutput = self._run(0.0)

    # --- time -----------------------------------------------------------------------------

    def advance(self, now: float) -> PlantOutput:
        """Step the plant up to ``now`` in steps of at most ``MAX_STEP_S``; without time passing,
        a step of zero length takes in a command at once, as a gateway reports it back. A jump
        beyond ``MAX_CATCH_UP_S`` is simulated for its last ``MAX_CATCH_UP_S`` only."""
        if now - self.t <= 1e-9:
            self._step(0.0)
        if now - self.t > MAX_CATCH_UP_S:
            self.t = now - MAX_CATCH_UP_S
        while now - self.t > 1e-9:
            dt = min(MAX_STEP_S, now - self.t)
            self.t += dt
            self._step(dt)
        return self.last

    def _step(self, dt: float) -> None:
        if dt > 0:
            self._exchange()
        self.last = self._run(dt)

    def _exchange(self) -> None:
        """The next OpenTherm exchange: what the boiler gets replaces the gateway's
        acknowledgement; a boiler that refuses ID 1 makes the gateway drop its override (the PIC
        "zaps" it, with no message)."""
        if self.refuses_id1 and self.plant.override_active(self.t):
            self.plant.clear_override()
        self.gateway_ack = None

    def _run(self, dt: float) -> PlantOutput:
        t = self.t
        if self.gateway_away_until is not None and t >= self.gateway_away_until:
            self.gateway_away_until = None
        if self.device_away_until is not None and t >= self.device_away_until:
            self.device_away_until = None
        if self.forced is not None:
            self.plant.set_setpoint(t, self.forced)
        if self.relay is not None:
            self.relay.advance(t)
        self.plant.fault = bool(self.faults)
        dhw = self.dhw_until is not None and t < self.dhw_until
        openings = self._openings(t)
        return self.plant.step(t, dt, self.outdoor, dhw, openings, self._request(t))

    def _openings(self, t: float) -> list[float]:
        plant = self.plant
        valves = self.config.valves
        if valves is Valves.THERMOSTATIC:
            base = plant.thermostatic_openings()
        elif valves is Valves.SWITCH:
            base = [1.0 if self.valves[z.zone_id] else 0.0 for z in self.zones]
        else:
            base = [
                self.tpi[z.zone_id].advance(t, plant.targets[i], plant.room[i], self.outdoor)
                if self.modes[z.zone_id] is ZoneMode.HEAT
                else 0.0
                for i, z in enumerate(self.zones)
            ]
        modes = [self.modes[z.zone_id] for z in self.zones]
        return [
            0.0 if mode is ZoneMode.OFF else 1.0 if mode is ZoneMode.SLEEP else opening
            for opening, mode in zip(base, modes, strict=True)
        ]

    def _request(self, t: float) -> Request | None:
        """What asks the boiler for heat without an override: the relay's contact, or the wall
        thermostat; ``None``: the boiler's own regulation."""
        if self.relay is not None:
            return Request(self.relay.contact, None, masked=False)
        if self.wall is not None:
            plant = self.plant
            self.wall.update(t, plant.room[self.wall.zone])
            curve = boiler_setpoint(plant.boiler, self.outdoor)
            return self.wall.request(curve, plant.boiler.max_setpoint)
        return None

    # --- what the gateway shows (``opentherm_gw``'s boiler device) -------------------------

    def gateway_reachable(self) -> bool:
        return not {"gateway", "gateway_all"} & self.failed and self.gateway_away_until is None

    def signal_failed(self, key: str) -> bool:
        """A signal failed by a scenario, or carried by a gateway whose whole link is lost."""
        return key in self.failed or ("gateway_all" in self.failed and key in GATEWAY_CARRIED)

    def gateway_read_back(self) -> float | None:
        """The boiler's "Control setpoint 1" as ``opentherm_gw`` shows it: the acknowledgement of
        a command at once, then what the gateway sends the boiler — the override while it holds,
        else what passes from the thermostat side. ``None``: the gateway is out of reach."""
        if not self.gateway_reachable():
            return None
        if self.gateway_ack is not None:
            return self.gateway_ack
        plant = self.plant
        if plant.override_active(self.t) and plant.override_setpoint is not None:
            return plant.override_setpoint
        return self.passed_setpoint()

    def passed_setpoint(self) -> float:
        """ID 1 with no override: the wall thermostat's request, a stand-alone gateway's zero, or
        — without a wall thermostat modelled — the boiler's own curve."""
        if self.relay is None and self.wall is not None:
            curve = boiler_setpoint(self.plant.boiler, self.outdoor)
            request = self.wall.request(curve, self.plant.boiler.max_setpoint)
            return request.setpoint if request.setpoint is not None else curve
        if self.topology is Topology.STANDALONE:
            return 0.0
        return boiler_setpoint(self.plant.boiler, self.outdoor)

    def gateway_ch_enable(self) -> bool | None:
        """The CH enable the gateway sends the boiler ("Central heating 1" on its boiler
        device)."""
        return self.last.demand if self.gateway_reachable() else None

    def gateway_pressure(self) -> float | None:
        """The boiler's water pressure as ``opentherm_gw`` shows it (ID 18): 0.0 from a gateway
        reset until the gateway's own poll reads it again; ``None`` while out of reach."""
        if not self.gateway_reachable():
            return None
        if self.gateway_pressure_from is not None and self.t < self.gateway_pressure_from:
            return 0.0
        return self.last.pressure

    def gateway_fault(self, fault: str | None = None) -> bool | None:
        """The boiler's fault indication (ID 0, in every status report) — or, with ``fault``,
        that fault's own flag (ID 5, read once per new fault and kept after it clears) — as
        ``opentherm_gw`` shows it; ``None`` while out of reach."""
        if not self.gateway_reachable():
            return None
        return bool(self.faults) if fault is None else fault in self.gateway_fault_flags

    def wall_setpoint(self) -> float | None:
        """The wall thermostat's room setpoint, as an OpenTherm thermostat sends it (ID 16)."""
        if self.wall is None or self.wall.kind is not WallKind.OPENTHERM:
            return None
        return self.wall.setpoint(self.t)

    def wall_room(self) -> float | None:
        if self.wall is None or self.wall.kind is not WallKind.OPENTHERM:
            return None
        return self.wall.room

    # --- command paths ----------------------------------------------------------------------

    def _catch_up(self, now: float) -> None:
        """A command arrives at ``now``: the plant is stepped up to then first, so the
        acknowledgement it gets is not taken over by an exchange that came before it."""
        if now - self.t > 1e-9:
            self.advance(now)

    def _gateway_takes(self) -> bool:
        """The gateway's commands are dropped while it is out of reach (``opentherm_gw``'s
        services return all the same) or every write is dropped before the boiler
        (``ignore_writes``; a boiler that ignores what the gateway sends is
        ``plant.boiler_ignores_override``, PB-91)."""
        return self.gateway_reachable() and not self.ignore_writes

    def gateway_setpoint(self, now: float, value: float) -> None:
        """``CS=``: 0 cancels; 8 °C or more lapses unless repeated; below 8 °C never lapses.
        The gateway acknowledges it at once."""
        self._catch_up(now)
        self.commands.gateway.append((now, "setpoint", value))
        if not self._gateway_takes():
            return
        if value == 0:
            self.gateway_ack = value
            self.plant.clear_override()
        else:
            taken = self._clipped(value)
            self.gateway_ack = taken
            self.plant.set_setpoint(now, taken, holds=value < GATEWAY_MIN_EXPIRING)

    def gateway_heating(self, now: float, on: bool) -> None:
        """``CH=``: sets or clears the gateway's CH-off flag (PIC 6.6), which survives ``CS=0``
        until ``CH=1`` or a reset; it does not renew the control setpoint's one-minute
        vigilance."""
        self._catch_up(now)
        self.commands.gateway.append((now, "ch", on))
        self.commands.ch_writes += 1
        if not self._gateway_takes():
            return
        self.plant.gateway_ch_off = not on

    def gateway_hot_water(self, now: float, value: object) -> None:
        """``HW=``: stored in the gateway's memory; the plugin must never send it."""
        self._catch_up(now)
        self.commands.gateway.append((now, "hot_water", value))
        self.commands.dhw_enable_writes += 1
        if self.gateway_reachable():
            self.dhw_enable = value not in (0, "0", False)

    def gateway_max_modulation(self, now: float, level: int) -> None:
        """``MM=``: the boiler's modulation capped, 0–100 %; −1 clears it."""
        self._catch_up(now)
        self.commands.gateway.append((now, "max_modulation", level))
        if self._gateway_takes():
            self.plant.max_modulation = None if level < 0 else float(level)

    def gateway_command(self, now: float, command: str, argument: str) -> None:
        """A transparent command, recorded; ``CS``, ``CH``, ``MM`` and ``HW`` act as their own
        services do, and ``GW=R`` resets the gateway."""
        self._catch_up(now)
        self.commands.gateway.append((now, "command", f"{command}={argument}"))
        try:
            if command == "CS":
                self.gateway_setpoint(now, float(argument))
            elif command == "CH":
                self.gateway_heating(now, argument.strip() not in ("0", ""))
            elif command == "MM":
                self.gateway_max_modulation(now, int(argument))
            elif command == "HW":
                self.gateway_hot_water(now, argument)
            elif command == "GW" and argument.upper() == "R":
                self.reset_gateway(now)
        except ValueError:
            return  # the gateway answers a bad argument with an error and does nothing

    def reset_gateway(self, now: float) -> None:
        """The gateway restarts: out of reach for ``GATEWAY_RESET_S``, its overrides lost."""
        self._catch_up(now)
        self.commands.gateway.append((now, "reset", None))
        self.plant.reset_gateway()
        self.gateway_ack = None
        self.gateway_away_until = now + GATEWAY_RESET_S
        self.gateway_pressure_from = now + GATEWAY_RESET_S + GATEWAY_PRESSURE_POLL_S

    def _clipped(self, value: float) -> float:
        """The setpoint the boiler takes: its own limit, where a scenario set one."""
        return value if self.clip is None else min(value, self.clip)

    def device_reachable(self) -> bool:
        """The writable setpoint's device (entity path) is up — not restarting."""
        return self.device_away_until is None

    def entity_setpoint(self, now: float, value: float) -> None:
        self._catch_up(now)
        self.commands.entity.append((now, "setpoint", value))
        if self.config.write_type is WriteType.PERSISTENT:
            self.commands.persistent_writes += 1
        if self.ignore_writes or not self.external_control or not self.device_reachable():
            return
        if value == self.config.hand_back_value:
            self.plant.clear_override()
        else:
            holds = self.config.write_type is not WriteType.EXPIRING
            self.plant.set_setpoint(now, self._clipped(value), holds=holds)

    def entity_heating(self, now: float, on: bool) -> None:
        """The heating switch, with its own write type; it never renews the setpoint's
        override."""
        self._catch_up(now)
        self.commands.entity.append((now, "ch", on))
        self.commands.ch_writes += 1
        if self.config.ch_write_type is WriteType.PERSISTENT:
            self.commands.persistent_writes += 1
        if self.ignore_writes or not self.external_control or not self.device_reachable():
            return
        holds = self.config.ch_write_type is not WriteType.EXPIRING
        self.plant.set_heating(now, on, holds=holds)

    def set_external_control(self, now: float, on: bool) -> None:
        self._catch_up(now)
        self.commands.entity.append((now, "external_control", on))
        self.external_control = on
        if not on:
            self.plant.clear_override()

    def relay_command(self, now: float, on: bool) -> None:
        """The relay switched by Home Assistant (the plugin, or the test itself)."""
        self._catch_up(now)
        if self.relay is None:
            raise ValueError("no relay in this installation")
        self.relay.command(now, on)

    # --- scenarios --------------------------------------------------------------------------

    def drop_override(self) -> None:
        """The boiler drops the override once, with no trace of an outage (decision 6's single
        untraced fall-back): back on its own regulation until the next write."""
        self.plant.clear_override()
        self.gateway_ack = None

    def restart_device(self, now: float, seconds: float = GATEWAY_RESET_S) -> None:
        """The writable setpoint's device restarts (an ESPHome-like master, S-13): out of reach
        for ``seconds``, then back with what it was given lost — the setpoint and its heating
        switch at their own defaults."""
        self._catch_up(now)
        self.plant.clear_override()
        self.plant.heating = self.plant.heating_at = None
        self.device_away_until = now + seconds
        self.device_restarts += 1

    def start_dhw(self, now: float, minutes: float) -> None:
        self.dhw_until = now + minutes * 60.0

    def set_topology(self, topology: Topology) -> None:
        """A gateway with or without a thermostat behind it (J4). A wall thermostat or relay
        decides what passes without an override, so there the switch is refused (PB-89)."""
        if self.relay is not None or self.wall is not None:
            raise ValueError("the topology cannot change with a wall thermostat or relay")
        self.topology = topology
        self.plant.without_override = (
            WithoutOverride.OFF if topology is Topology.STANDALONE else WithoutOverride.OWN_CURVE
        )

    def set_zone_target(self, zone_id: str, target: float) -> None:
        self.plant.targets[self._index[zone_id]] = target

    def set_zone_mode(self, zone_id: str, mode: ZoneMode) -> None:
        self.modes[zone_id] = mode

    def set_room(self, zone_id: str, temperature: float) -> None:
        """A room's temperature set at once — a window left open in frost, say — from which the
        plant goes on as before (J4's frost scenarios in the test Home Assistant)."""
        self.plant.room[self._index[zone_id]] = temperature

    def set_fault(self, fault: str, on: bool) -> None:
        if fault not in FAULTS:
            raise ValueError(f"unknown fault {fault}")
        if on:
            self.faults.add(fault)
            # The gateway reads a fault's flags once per new fault and keeps them after it clears
            # (Q3.9): its flags show the last fault's, not the boiler's state now.
            self.gateway_fault_flags = set(self.faults)
        else:
            self.faults.discard(fault)

    def room(self, zone_id: str) -> float:
        return self.plant.room[self._index[zone_id]]

    def opening(self, zone_id: str) -> float:
        return self.last.openings[self._index[zone_id]]

    def on_percent(self, zone_id: str) -> float | None:
        """A TPI zone's on-percent of its current cycle; ``None`` for other valves."""
        if self.config.valves is not Valves.TPI:
            return None
        if self.modes[zone_id] is not ZoneMode.HEAT:
            return 0.0
        return self.tpi[zone_id].percent
