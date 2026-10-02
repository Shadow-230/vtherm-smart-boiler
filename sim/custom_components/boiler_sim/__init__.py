"""Boiler simulator for the test Home Assistant only — never part of a release.

A simulated boiler, water loop, house and zones (``plant``) behind entities like a real
installation's: boiler signals, room temperatures, zone valve switches for VT's thermostats, a
weather entity, a writable flow setpoint with an external-control switch and a heating switch,
and optionally a relay on an on/off boiler's room-thermostat terminals. The OpenTherm Gateway
path is the test-only stub integration ``opentherm_gw`` beside this one (P-37), which forwards
its services to this hub and shows the gateway's read-back; optionally the OTGW firmware's MQTT
commands are taken too. Scenario services change the weather, fail a signal, start hot water,
let another controller write, make the boiler ignore writes, refuse ID 1, clip the setpoint or
drop the override once, switch a zone off, restart the gateway or the setpoint's device, restart
the relay, cut its Wi-Fi or switch it from outside, change the wall thermostat's setting by hand,
and raise a boiler fault — decision 6's classes and J4's scenarios, reachable in the test Home
Assistant (P-114). Set up from YAML (``boiler_sim:``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.typing import ConfigType
from homeassistant.util import dt as dt_util

from .relay import RelayModel, StartUp
from .simulation import (
    FAULTS,
    ZONE_LAYOUTS,
    RelaySetup,
    SimConfig,
    Simulation,
    Topology,
    Valves,
    WriteType,
    ZoneMode,
)
from .thermostat import WallKind

_LOGGER = logging.getLogger(__name__)
DOMAIN = "boiler_sim"
PLATFORMS = ("sensor", "binary_sensor", "number", "switch", "weather")
SIGNALS = (
    "flame",
    "flow",
    "return",
    "modulation",
    "ch_setpoint",
    "dhw_active",
    "pressure",
    "outdoor",
    "ch_active",
    "pump_running",
    "weather",
    # The gateway out of reach: the stub's entities unavailable, its commands dropped.
    "gateway",
    # The relay reports no state ("unknown") while it stays available.
    "relay",
    # The wall thermostat's room setpoint (ID 16), as the gateway's thermostat device shows it.
    "thermostat_setpoint",
    *FAULTS,
    "fault_indication",
)

_RELAY = vol.Schema(
    {
        vol.Optional("start_up", default=StartUp.OFF.value): vol.In([s.value for s in StartUp]),
        vol.Optional("off_timer_min"): vol.All(vol.Coerce(float), vol.Range(min=1, max=120)),
        vol.Optional("timer_restarts_on_repeat", default=True): cv.boolean,
        vol.Optional("assumed_state", default=False): cv.boolean,
    }
)

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Optional("boiler", default="condensing_small"): cv.string,
                vol.Optional("house", default="average"): cv.string,
                vol.Optional("zones", default="radiators"): vol.In(list(ZONE_LAYOUTS)),
                vol.Optional("valves", default=Valves.THERMOSTATIC.value): vol.In(
                    [v.value for v in Valves]
                ),
                vol.Optional("topology", default=Topology.WITH_THERMOSTAT.value): vol.In(
                    [t.value for t in Topology]
                ),
                vol.Optional("write_type", default=WriteType.EXPIRING.value): vol.In(
                    [w.value for w in WriteType]
                ),
                vol.Optional("ch_write_type", default=WriteType.HELD.value): vol.In(
                    [w.value for w in WriteType]
                ),
                vol.Optional("outdoor", default=3.0): vol.Coerce(float),
                vol.Optional("step_seconds", default=10): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=60)
                ),
                vol.Optional("gateway_id", default="sim"): cv.string,
                vol.Optional("mqtt_topic"): cv.string,
                vol.Optional("wall_thermostat"): vol.In([k.value for k in WallKind]),
                vol.Optional("relay"): _RELAY,
                vol.Optional("restart_lockout_s"): vol.All(
                    vol.Coerce(float), vol.Range(min=0, max=3600)
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def sim_config(conf: dict[str, Any]) -> SimConfig:
    """The simulated installation from the component's YAML."""
    relay_conf = conf.get("relay")
    relay = None
    if relay_conf is not None:
        timer = relay_conf.get("off_timer_min")
        relay = RelaySetup(
            start_up=StartUp(relay_conf["start_up"]),
            off_timer_s=None if timer is None else float(timer) * 60.0,
            timer_restarts_on_repeat=relay_conf["timer_restarts_on_repeat"],
            assumed_state=relay_conf["assumed_state"],
        )
    wall = conf.get("wall_thermostat")
    return SimConfig(
        boiler=conf["boiler"],
        house=conf["house"],
        zones=conf["zones"],
        valves=Valves(conf["valves"]),
        topology=Topology(conf["topology"]),
        write_type=WriteType(conf["write_type"]),
        ch_write_type=WriteType(conf["ch_write_type"]),
        outdoor=conf["outdoor"],
        wall_thermostat=None if wall is None else WallKind(wall),
        relay=relay,
        restart_lockout_s=conf.get("restart_lockout_s"),
    )


class SimHub:
    """The simulation in Home Assistant: its clock, services and entity updates."""

    def __init__(self, hass: HomeAssistant, simulation: Simulation, conf: dict[str, Any]) -> None:
        self.hass = hass
        self.sim = simulation
        self.conf = conf
        self._listeners: list[Callable[[], None]] = []

    @property
    def gateway_id(self) -> str:
        return str(self.conf.get("gateway_id", "sim"))

    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    @callback
    def refresh(self, _now: datetime | None = None) -> None:
        self.sim.advance(dt_util.utcnow().timestamp())
        for update in list(self._listeners):
            update()

    def now(self) -> float:
        return dt_util.utcnow().timestamp()


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    conf = config.get(DOMAIN)
    if conf is None:
        return True
    hub = SimHub(hass, Simulation(sim_config(conf), dt_util.utcnow().timestamp()), conf)
    hass.data[DOMAIN] = hub
    stop_clock = async_track_time_interval(
        hass, hub.refresh, timedelta(seconds=conf["step_seconds"])
    )

    @callback
    def stop(_event: Event) -> None:
        stop_clock()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    _register_scenario_services(hass, hub)
    if conf.get("mqtt_topic"):
        await _async_subscribe_mqtt(hass, hub, conf["mqtt_topic"])
    for platform in PLATFORMS:
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))
    return True


async def _async_subscribe_mqtt(hass: HomeAssistant, hub: SimHub, topic: str) -> None:
    """The OTGW firmware's commands on ``<topic>/ctrlsetpt``, ``<topic>/chenable`` and
    ``<topic>/maxmodulation``."""
    try:
        from homeassistant.components import mqtt
    except ImportError:
        _LOGGER.warning("MQTT is not available; the simulated firmware path is off")
        return

    @callback
    def on_message(message: Any) -> None:
        command = message.topic.rsplit("/", 1)[-1]
        payload = str(message.payload)
        try:
            if command == "ctrlsetpt":
                hub.sim.gateway_setpoint(hub.now(), float(payload))
            elif command == "chenable":
                hub.sim.gateway_heating(hub.now(), payload == "1")
            elif command == "maxmodulation":
                hub.sim.gateway_max_modulation(hub.now(), int(float(payload)))
        except ValueError:
            _LOGGER.warning("The simulated firmware ignores %s=%s", command, payload)
        hub.refresh()

    await mqtt.async_subscribe(hass, f"{topic.strip('/')}/+", on_message)


def _register_scenario_services(hass: HomeAssistant, hub: SimHub) -> None:
    sim = hub.sim

    async def set_outdoor(call: ServiceCall) -> None:
        sim.outdoor = float(call.data["temperature"])
        hub.refresh()

    async def fail_signal(call: ServiceCall) -> None:
        signal = call.data["signal"]
        if call.data.get("failed", True):
            sim.failed.add(signal)
        else:
            sim.failed.discard(signal)
        hub.refresh()

    async def force_setpoint(call: ServiceCall) -> None:
        value = call.data.get("value")
        sim.forced = None if value is None else float(value)
        if value is None:
            sim.plant.clear_override()
        hub.refresh()

    async def ignore_writes(call: ServiceCall) -> None:
        sim.ignore_writes = bool(call.data.get("enabled", True))
        hub.refresh()

    async def refuse_id1(call: ServiceCall) -> None:
        sim.refuses_id1 = bool(call.data.get("enabled", True))
        hub.refresh()

    async def start_dhw(call: ServiceCall) -> None:
        sim.start_dhw(hub.now(), float(call.data.get("minutes", 10)))
        hub.refresh()

    async def set_topology(call: ServiceCall) -> None:
        sim.set_topology(Topology(call.data["topology"]))
        hub.refresh()

    async def set_zone_mode(call: ServiceCall) -> None:
        sim.set_zone_mode(call.data["zone"], ZoneMode(call.data["mode"]))
        hub.refresh()

    async def reset_gateway(call: ServiceCall) -> None:
        sim.reset_gateway(hub.now())
        hub.refresh()

    async def drop_override(call: ServiceCall) -> None:
        sim.drop_override()
        hub.refresh()

    async def clip_setpoint(call: ServiceCall) -> None:
        value = call.data.get("value")
        sim.clip = None if value is None else float(value)
        hub.refresh()

    async def restart_device(call: ServiceCall) -> None:
        sim.restart_device(hub.now(), float(call.data.get("seconds", 10)))
        hub.refresh()

    def relay() -> RelayModel:
        if sim.relay is None:
            raise ServiceValidationError("no relay in this installation")
        return sim.relay

    async def relay_restart(call: ServiceCall) -> None:
        relay().restart(hub.now(), reported=bool(call.data.get("reported", True)))
        hub.refresh()

    async def relay_wifi_loss(call: ServiceCall) -> None:
        relay().wifi_loss(hub.now(), float(call.data["minutes"]) * 60.0)
        hub.refresh()

    async def relay_switch(call: ServiceCall) -> None:
        relay().switch(hub.now(), bool(call.data["on"]))
        hub.refresh()

    async def set_wall_setpoint(call: ServiceCall) -> None:
        if sim.wall is None:
            raise ServiceValidationError("no wall thermostat in this installation")
        sim.wall.set_manual(hub.now(), float(call.data["temperature"]))
        hub.refresh()

    async def set_fault(call: ServiceCall) -> None:
        sim.set_fault(call.data["fault"], bool(call.data.get("on", True)))
        hub.refresh()

    zone_ids = [zone.zone_id for zone in sim.zones]
    services = {
        "set_outdoor": (set_outdoor, {vol.Required("temperature"): vol.Coerce(float)}),
        "fail_signal": (
            fail_signal,
            {vol.Required("signal"): vol.In(SIGNALS), vol.Optional("failed"): cv.boolean},
        ),
        "force_setpoint": (
            force_setpoint,
            {vol.Optional("value"): vol.Any(None, vol.Coerce(float))},
        ),
        "ignore_writes": (ignore_writes, {vol.Optional("enabled"): cv.boolean}),
        "refuse_id1": (refuse_id1, {vol.Optional("enabled"): cv.boolean}),
        "start_dhw": (start_dhw, {vol.Optional("minutes"): vol.Coerce(float)}),
        "set_topology": (
            set_topology,
            {vol.Required("topology"): vol.In([t.value for t in Topology])},
        ),
        "set_zone_mode": (
            set_zone_mode,
            {
                vol.Required("zone"): vol.In(zone_ids),
                vol.Required("mode"): vol.In([m.value for m in ZoneMode]),
            },
        ),
        "reset_gateway": (reset_gateway, {}),
        "drop_override": (drop_override, {}),
        "clip_setpoint": (
            clip_setpoint,
            {vol.Optional("value"): vol.Any(None, vol.All(vol.Coerce(float), vol.Range(0, 90)))},
        ),
        "restart_device": (
            restart_device,
            {vol.Optional("seconds"): vol.All(vol.Coerce(float), vol.Range(min=1, max=3600))},
        ),
        "relay_restart": (relay_restart, {vol.Optional("reported"): cv.boolean}),
        "relay_wifi_loss": (
            relay_wifi_loss,
            {vol.Required("minutes"): vol.All(vol.Coerce(float), vol.Range(min=0, max=1440))},
        ),
        "relay_switch": (relay_switch, {vol.Required("on"): cv.boolean}),
        "set_wall_setpoint": (
            set_wall_setpoint,
            {vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=5, max=30))},
        ),
        "set_fault": (
            set_fault,
            {vol.Required("fault"): vol.In(FAULTS), vol.Optional("on"): cv.boolean},
        ),
    }
    for name, (handler, schema) in services.items():
        hass.services.async_register(DOMAIN, name, handler, vol.Schema(schema))
