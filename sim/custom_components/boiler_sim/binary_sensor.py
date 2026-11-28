"""Flame, hot water, heating demand, pump, the DHW-enable bit, the boiler's own faults, and a
window sensor per room."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SimHub
from .entity import SimEntity
from .simulation import Simulation

FLAGS: dict[str, tuple[str, Callable[[Simulation], bool]]] = {
    "flame": ("flame", lambda s: s.last.flame),
    "dhw_active": ("hot water", lambda s: s.last.dhw),
    "ch_active": ("heating demand", lambda s: s.last.demand and not s.last.dhw),
    # The pump: for heating, with its overrun after the demand ends, and for hot water.
    "pump_running": ("pump", lambda s: s.last.pump or s.last.dhw),
    "dhw_enable": ("DHW enable", lambda s: s.dhw_enable),
    # The boiler's own faults (boiler protection): each stops it while it holds.
    "low_pressure_fault": ("low water pressure fault", lambda s: "low_pressure_fault" in s.faults),
    "boiler_lockout": ("lockout", lambda s: "boiler_lockout" in s.faults),
    "fault_indication": ("fault indication", lambda s: bool(s.faults)),
}


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    if discovery_info is None:
        return
    hub: SimHub = hass.data[DOMAIN]
    entities: list[BinarySensorEntity] = [
        Flag(hub, key, name, value) for key, (name, value) in FLAGS.items()
    ]
    entities += [WindowSensor(hub, zone.zone_id) for zone in hub.sim.zones]
    async_add_entities(entities)


class Flag(SimEntity, BinarySensorEntity):
    platform_domain = "binary_sensor"

    def __init__(
        self, hub: SimHub, key: str, name: str, value: Callable[[Simulation], bool]
    ) -> None:
        super().__init__(hub, key, name)
        self._value = value

    @property
    def is_on(self) -> bool:
        return self._value(self.hub.sim)


class WindowSensor(SimEntity, BinarySensorEntity):
    """A room's window (I12.26), for VT's window detection by a sensor: on while open."""

    platform_domain = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.WINDOW

    def __init__(self, hub: SimHub, zone: str) -> None:
        super().__init__(hub, f"{zone}_window", f"{zone} window")
        self.zone = zone

    @property
    def is_on(self) -> bool:
        return self.hub.sim.window(self.zone)
