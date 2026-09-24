"""Heating on/off, the external-control switch, and one valve per zone for VT's thermostats."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
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
    async_add_entities(entities)


class HeatingSwitch(SimEntity, SwitchEntity):
    platform_domain = "switch"

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "ch_enable", "heating")
        self._on: bool | None = None

    @property
    def is_on(self) -> bool | None:
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
