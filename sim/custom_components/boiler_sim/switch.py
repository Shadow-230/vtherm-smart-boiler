"""Heating on/off, the external-control switch, one valve per zone for VT's thermostats, and
the relay of an on/off boiler."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import Context, HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SimHub
from .entity import SimEntity


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    if discovery_info is None:
        return
    hub: SimHub = hass.data[DOMAIN]
    entities: list[SwitchEntity] = [HeatingSwitch(hub), ExternalControl(hub)]
    entities += [ZoneValve(hub, zone.zone_id) for zone in hub.sim.zones]
    if hub.sim.relay is not None:
        entities.append(RelaySwitch(hub))
    async_add_entities(entities)


class HeatingSwitch(SimEntity, SwitchEntity):
    """The heating switch of the writable setpoint's device, with its own write type."""

    platform_domain = "switch"
    _on_device = True

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "ch_enable", "heating")
        self._on: bool | None = None
        self._restarts = hub.sim.device_restarts

    @property
    def is_on(self) -> bool | None:
        if self.hub.sim.device_restarts != self._restarts:
            self._restarts = self.hub.sim.device_restarts
            self._on = None  # lost in the device's restart
        return self._on

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._on = True
        self.hub.sim.entity_heating(self.hub.now(), True)
        self.hub.refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._on = False
        self.hub.sim.entity_heating(self.hub.now(), False)
        self.hub.refresh()


class ExternalControl(SimEntity, SwitchEntity):
    """Lets writes to the flow setpoint through; off hands back to the boiler."""

    platform_domain = "switch"

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "external_control", "external control")

    @property
    def is_on(self) -> bool:
        return self.hub.sim.external_control

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.sim.set_external_control(self.hub.now(), True)
        self.hub.refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.sim.set_external_control(self.hub.now(), False)
        self.hub.refresh()


class ZoneValve(SimEntity, SwitchEntity):
    """A zone's valve, driven by a thermostat (VT's underlying heater)."""

    platform_domain = "switch"

    def __init__(self, hub: SimHub, zone: str) -> None:
        super().__init__(hub, f"{zone}_valve", f"{zone} valve")
        self.zone = zone

    @property
    def is_on(self) -> bool:
        return self.hub.sim.valves[self.zone]

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.sim.valves[self.zone] = True
        self.hub.refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.sim.valves[self.zone] = False
        self.hub.refresh()


class RelaySwitch(SimEntity, SwitchEntity):
    """The relay on an on/off boiler's room-thermostat terminals (X8): switched by Home
    Assistant, by its own timer, a restart or another controller; out of reach while it restarts
    or has lost its Wi-Fi; its state "unknown" while it reports none (``fail_signal: relay``).
    Each change the relay makes itself carries a context of its own, never the last caller's."""

    platform_domain = "switch"

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "relay", "relay")
        self._seen = 0

    @property
    def available(self) -> bool:
        relay = self.hub.sim.relay
        return relay is not None and relay.available

    @property
    def is_on(self) -> bool | None:
        relay = self.hub.sim.relay
        if relay is None or "relay" in self.hub.sim.failed:
            return None
        return relay.on

    @property
    def assumed_state(self) -> bool:
        relay = self.hub.sim.relay
        return relay is not None and relay.assumed_state

    async def async_turn_on(self, **kwargs: Any) -> None:
        self.hub.sim.relay_command(self.hub.now(), True)
        self.hub.refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self.hub.sim.relay_command(self.hub.now(), False)
        self.hub.refresh()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_listener(self._update))

    @callback
    def _update(self) -> None:
        relay = self.hub.sim.relay
        if relay is not None and relay.own_changes != self._seen:
            self._seen = relay.own_changes
            self.async_set_context(Context())  # its own change: not the last caller's
        self.async_write_ha_state()
