"""A test-only stand-in for Home Assistant's OpenTherm Gateway integration, on the boiler
simulator — never part of a release (P-37; provisional, K4).

It lets the plugin's main write path run against the simulator, in-process and in the test Home
Assistant only, exactly as a user sets it up: its config flow makes an entry with the gateway's
ID (``boiler_sim``'s ``gateway_id``, ``sim`` by default); it registers the gateway services the
plugin may call — ``set_control_setpoint``, ``set_central_heating_ovrd``, ``set_max_modulation``
and ``send_transparent_command``, and ``set_hot_water_ovrd`` and ``reset_gateway`` so that a
call the plugin must never make is counted, and a gateway restart can be provoked — forwarding
them to the simulator's hub; and it creates the entities the plugin reads: the boiler device's
"Control setpoint 1" and "Central heating 1" (the CH enable the boiler gets), and the thermostat
device's "Room setpoint 1" and "Room temperature 1" of a wall thermostat. Like the real
integration, the services are registered once, when the integration is set up, and refuse a
gateway ID that is not set up; a service returns without an error while the gateway is out of
reach — the command is dropped — and the entities are then unavailable.

A custom integration of a built-in one's name overrides it in Home Assistant 2026.9.3: the
loader looks for custom integrations first (``homeassistant/loader.py``,
``async_get_integrations``: "First we look for custom components"), and a custom one needs a
``version`` in its manifest. So this stub is deployed to the test Home Assistant only
(``scripts/deploy_test.sh``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, Protocol

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

_LOGGER = logging.getLogger(__name__)
DOMAIN = "opentherm_gw"
SIMULATOR = "boiler_sim"
PLATFORMS = (Platform.SENSOR, Platform.BINARY_SENSOR)


class Gateway(Protocol):
    """What the stub uses of the simulated installation (``boiler_sim.simulation``)."""

    def gateway_setpoint(self, now: float, value: float) -> None: ...
    def gateway_heating(self, now: float, on: bool) -> None: ...
    def gateway_max_modulation(self, now: float, level: int) -> None: ...
    def gateway_command(self, now: float, command: str, argument: str) -> None: ...
    def gateway_hot_water(self, now: float, value: object) -> None: ...
    def reset_gateway(self, now: float) -> None: ...
    def gateway_reachable(self) -> bool: ...
    def gateway_read_back(self) -> float | None: ...
    def gateway_ch_enable(self) -> bool | None: ...
    def wall_setpoint(self) -> float | None: ...
    def wall_room(self) -> float | None: ...

    @property
    def failed(self) -> set[str]: ...


class Hub(Protocol):
    """The simulator's hub (``boiler_sim.SimHub``)."""

    @property
    def sim(self) -> Gateway: ...

    @property
    def gateway_id(self) -> str: ...

    def add_listener(self, update: Callable[[], None]) -> Callable[[], None]: ...
    def refresh(self) -> None: ...
    def now(self) -> float: ...


type SimGatewayEntry = ConfigEntry[Hub]


def hub_of(hass: HomeAssistant) -> Hub | None:
    hub: Hub | None = hass.data.get(SIMULATOR)
    return hub


def _gateways(hass: HomeAssistant) -> dict[str, Hub]:
    """The gateways set up now, by ID."""
    found: dict[str, Hub] = hass.data.setdefault(DOMAIN, {})
    return found


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Without the simulator there is no gateway: the integration does not set up, and
    registers nothing — as Home Assistant's own cannot without its gateway library — so it
    stands in for nothing anywhere the simulator does not run."""
    if hub_of(hass) is None:
        _LOGGER.warning("The simulated OpenTherm Gateway needs the boiler simulator (boiler_sim)")
        return False
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SimGatewayEntry) -> bool:
    hub = hub_of(hass)
    if hub is None:
        raise ConfigEntryNotReady("the boiler simulator (boiler_sim) is not set up")
    entry.runtime_data = hub
    _gateways(hass)[str(entry.data["id"])] = hub
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SimGatewayEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        _gateways(hass).pop(str(entry.data["id"]), None)
    return unloaded


def _register_services(hass: HomeAssistant) -> None:
    """The gateway services, with the real integration's fields; each forwarded to the hub of
    the gateway named, and refused for a gateway that is not set up."""

    def hub(call: ServiceCall) -> Hub:
        found = _gateways(hass).get(call.data["gateway_id"])
        if found is None:
            raise ServiceValidationError(f"unknown gateway {call.data['gateway_id']}")
        return found

    async def set_control_setpoint(call: ServiceCall) -> None:
        gateway = hub(call)
        gateway.sim.gateway_setpoint(gateway.now(), float(call.data["temperature"]))
        gateway.refresh()

    async def set_central_heating_ovrd(call: ServiceCall) -> None:
        gateway = hub(call)
        gateway.sim.gateway_heating(gateway.now(), bool(call.data["ch_override"]))
        gateway.refresh()

    async def set_max_modulation(call: ServiceCall) -> None:
        gateway = hub(call)
        gateway.sim.gateway_max_modulation(gateway.now(), int(call.data["level"]))
        gateway.refresh()

    async def send_transparent_command(call: ServiceCall) -> None:
        gateway = hub(call)
        command, argument = call.data["transp_cmd"], call.data["transp_arg"]
        gateway.sim.gateway_command(gateway.now(), command, argument)
        gateway.refresh()

    async def set_hot_water_ovrd(call: ServiceCall) -> None:
        gateway = hub(call)
        gateway.sim.gateway_hot_water(gateway.now(), call.data["dhw_override"])
        gateway.refresh()

    async def reset_gateway(call: ServiceCall) -> None:
        gateway = hub(call)
        gateway.sim.reset_gateway(gateway.now())
        gateway.refresh()

    gateway = {vol.Required("gateway_id"): cv.string}
    schemas: dict[str, tuple[Any, dict[Any, Any]]] = {
        "set_control_setpoint": (
            set_control_setpoint,
            {vol.Required("temperature"): vol.All(vol.Coerce(float), vol.Range(min=0, max=90))},
        ),
        "set_central_heating_ovrd": (
            set_central_heating_ovrd,
            {vol.Required("ch_override"): cv.boolean},
        ),
        "set_max_modulation": (
            set_max_modulation,
            {vol.Required("level"): vol.All(vol.Coerce(int), vol.Range(min=-1, max=100))},
        ),
        "send_transparent_command": (
            send_transparent_command,
            {
                vol.Required("transp_cmd"): vol.All(
                    cv.string, vol.Length(min=2, max=2), vol.Coerce(str.upper)
                ),
                vol.Required("transp_arg"): vol.All(cv.string, vol.Length(min=1, max=12)),
            },
        ),
        "set_hot_water_ovrd": (
            set_hot_water_ovrd,
            {
                vol.Required("dhw_override"): vol.Any(
                    vol.Equal("A"), vol.All(vol.Coerce(int), vol.Range(min=0, max=1))
                )
            },
        ),
        "reset_gateway": (reset_gateway, {}),
    }
    for name, (handler, fields) in schemas.items():
        hass.services.async_register(DOMAIN, name, handler, vol.Schema(gateway | fields))
