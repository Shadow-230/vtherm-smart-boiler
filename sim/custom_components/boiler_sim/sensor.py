"""Boiler signals, room temperatures and valve openings, and command counters."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import DOMAIN, SimHub
from .entity import SimEntity
from .simulation import Simulation

_TEMPERATURE = (SensorDeviceClass.TEMPERATURE, UnitOfTemperature.CELSIUS)

BOILER_SENSORS: dict[str, tuple[str, Any, Callable[[Simulation], float]]] = {
    "flow": ("flow", _TEMPERATURE, lambda s: round(s.last.flow, 1)),
    "return": ("return", _TEMPERATURE, lambda s: round(s.last.return_, 1)),
    "ch_setpoint": ("control setpoint", _TEMPERATURE, lambda s: round(s.last.setpoint, 1)),
    "outdoor": ("outdoor", _TEMPERATURE, lambda s: round(s.outdoor, 1)),
    "modulation": ("modulation", (None, PERCENTAGE), lambda s: round(s.last.modulation)),
    "pressure": (
        "pressure",
        (SensorDeviceClass.PRESSURE, UnitOfPressure.BAR),
        lambda s: round(s.last.pressure, 2),
    ),
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
    entities: list[SensorEntity] = [
        BoilerSensor(hub, key, name, kind, value)
        for key, (name, kind, value) in BOILER_SENSORS.items()
    ]
    for zone in hub.sim.zones:
        entities += [RoomSensor(hub, zone.zone_id), OpeningSensor(hub, zone.zone_id)]
    entities.append(CounterSensor(hub))
    async_add_entities(entities)


class BoilerSensor(SimEntity, SensorEntity):
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hub: SimHub,
        key: str,
        name: str,
        kind: tuple[SensorDeviceClass | None, str],
        value: Callable[[Simulation], float],
    ) -> None:
        super().__init__(hub, key, name)
        self._attr_device_class, self._attr_native_unit_of_measurement = kind
        self._value = value

    @property
    def native_value(self) -> float:
        return self._value(self.hub.sim)


class RoomSensor(SimEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hub: SimHub, zone: str) -> None:
        super().__init__(hub, f"{zone}_temperature", f"{zone} temperature")
        self.zone = zone

    @property
    def native_value(self) -> float:
        return round(self.hub.sim.room(self.zone), 2)


class OpeningSensor(SimEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, hub: SimHub, zone: str) -> None:
        super().__init__(hub, f"{zone}_opening", f"{zone} valve opening")
        self.zone = zone

    @property
    def native_value(self) -> int:
        return round(self.hub.sim.opening(self.zone) * 100)


class CounterSensor(SimEntity, SensorEntity):
    """Commands the boiler received: persistent writes wear its memory."""

    _attr_state_class = SensorStateClass.TOTAL_INCREASING

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "persistent_writes", "persistent writes")

    @property
    def native_value(self) -> int:
        return self.hub.sim.commands.persistent_writes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        commands = self.hub.sim.commands
        return {
            "gateway_commands": len(commands.gateway),
            "entity_commands": len(commands.entity),
            "dhw_enable_writes": commands.dhw_enable_writes,
            "override_active": self.hub.sim.plant.override_active(self.hub.now()),
        }
