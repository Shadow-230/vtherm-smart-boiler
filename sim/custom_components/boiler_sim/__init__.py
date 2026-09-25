"""Boiler simulator for the test Home Assistant only — never part of a release.

A simulated boiler, water loop, house and zones (``plant``) behind entities like a real
installation's: boiler signals, room temperatures, zone valve switches for VT's thermostats, a
weather entity, a writable flow setpoint with an external-control switch, and an OpenTherm
Gateway-like command path — the ``opentherm_gw`` services, registered only while the real
integration is not loaded, and optionally the OTGW firmware's MQTT commands. Scenario services
change the weather, fail a signal, start hot water, let another controller write, or make the
boiler ignore writes. Set up from YAML (``boiler_sim:``).
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

from .simulation import ZONE_LAYOUTS, SimConfig, Simulation, Topology, Valves, WriteType

_LOGGER = logging.getLogger(__name__)
DOMAIN = "boiler_sim"
GATEWAY_DOMAIN = "opentherm_gw"
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
                vol.Optional("outdoor", default=3.0): vol.Coerce(float),
                vol.Optional("step_seconds", default=10): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=60)
                ),
                vol.Optional("gateway", default=True): cv.boolean,
                vol.Optional("gateway_id", default="sim"): cv.string,
                vol.Optional("mqtt_topic"): cv.string,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


class SimHub:
    """The simulation in Home Assistant: its clock, services and entity updates."""

    def __init__(self, hass: HomeAssistant, simulation: Simulation, conf: dict[str, Any]) -> None:
        self.hass = hass
        self.sim = simulation
        self.conf = conf
        self._listeners: list[Callable[[], None]] = []

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
    sim_config = SimConfig(
        boiler=conf["boiler"],
        house=conf["house"],
        zones=conf["zones"],
        valves=Valves(conf["valves"]),
        topology=Topology(conf["topology"]),
        write_type=WriteType(conf["write_type"]),
        outdoor=conf["outdoor"],
    )
    hub = SimHub(hass, Simulation(sim_config, dt_util.utcnow().timestamp()), conf)
    hass.data[DOMAIN] = hub
    stop_clock = async_track_time_interval(
        hass, hub.refresh, timedelta(seconds=conf["step_seconds"])
    )

    @callback
    def stop(_event: Event) -> None:
        stop_clock()

    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stop)
    _register_scenario_services(hass, hub)
    if conf["gateway"] and GATEWAY_DOMAIN not in hass.config.components:
        _register_gateway_services(hass, hub)
    if conf.get("mqtt_topic"):
        await _async_subscribe_mqtt(hass, hub, conf["mqtt_topic"])
    for platform in PLATFORMS:
        hass.async_create_task(async_load_platform(hass, platform, DOMAIN, {}, config))
    return True


def _register_gateway_services(hass: HomeAssistant, hub: SimHub) -> None:
    gateway_id = hub.conf["gateway_id"]

    def check(call: ServiceCall) -> None:
        if call.data.get("gateway_id") != gateway_id:
            raise ServiceValidationError(f"unknown gateway {call.data.get('gateway_id')}")

    async def setpoint(call: ServiceCall) -> None:
        check(call)
        hub.sim.gateway_setpoint(hub.now(), float(call.data["temperature"]))
        hub.refresh()

    async def heating(call: ServiceCall) -> None:
        check(call)
        hub.sim.gateway_heating(hub.now(), bool(call.data["ch_override"]))
        hub.refresh()

    async def hot_water(call: ServiceCall) -> None:
        check(call)
        hub.sim.gateway_hot_water(hub.now(), call.data.get("dhw_override"))
        hub.refresh()

    base = {vol.Required("gateway_id"): cv.string}
    temperature = vol.All(vol.Coerce(float), vol.Range(0, 90))
    hass.services.async_register(
        GATEWAY_DOMAIN,
        "set_control_setpoint",
        setpoint,
        vol.Schema(base | {vol.Required("temperature"): temperature}),
    )
    hass.services.async_register(
        GATEWAY_DOMAIN,
        "set_central_heating_ovrd",
        heating,
        vol.Schema(base | {vol.Required("ch_override"): cv.boolean}),
    )
    hass.services.async_register(
        GATEWAY_DOMAIN,
        "set_hot_water_ovrd",
        hot_water,
        vol.Schema(base | {vol.Required("dhw_override"): cv.string}),
    )


async def _async_subscribe_mqtt(hass: HomeAssistant, hub: SimHub, topic: str) -> None:
    """The OTGW firmware's commands on ``<topic>/ctrlsetpt`` and ``<topic>/chenable``."""
    try:
        from homeassistant.components import mqtt
    except ImportError:
        _LOGGER.warning("MQTT is not available; the simulated firmware path is off")
        return

    @callback
    def on_message(message: Any) -> None:
        command = message.topic.rsplit("/", 1)[-1]
        payload = str(message.payload)
        if command == "ctrlsetpt":
            hub.sim.gateway_setpoint(hub.now(), float(payload))
        elif command == "chenable":
            hub.sim.gateway_heating(hub.now(), payload == "1")
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

    async def start_dhw(call: ServiceCall) -> None:
        sim.start_dhw(hub.now(), float(call.data.get("minutes", 10)))
        hub.refresh()

    async def set_topology(call: ServiceCall) -> None:
        sim.set_topology(Topology(call.data["topology"]))
        hub.refresh()

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
        "start_dhw": (start_dhw, {vol.Optional("minutes"): vol.Coerce(float)}),
        "set_topology": (
            set_topology,
            {vol.Required("topology"): vol.In([t.value for t in Topology])},
        ),
    }
    for name, (handler, schema) in services.items():
        hass.services.async_register(DOMAIN, name, handler, vol.Schema(schema))
