"""The writable flow setpoint (its write type set in the configuration) and zone targets."""

from __future__ import annotations

from typing import Any

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfTemperature
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
    entities: list[NumberEntity] = [FlowSetpoint(hub)]
    entities += [ZoneTarget(hub, zone.zone_id) for zone in hub.sim.zones]
    async_add_entities(entities)


class FlowSetpoint(SimEntity, NumberEntity):
    """What a controller writes; the boiler's own setpoint is the control setpoint sensor. Its
    device restarting, it is out of reach, and comes back with what it was given lost."""

    platform_domain = "number"
    _on_device = True
    _attr_device_class = NumberDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 0.0
    _attr_native_max_value = 90.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "flow_setpoint", "flow setpoint")
        self._written: float | None = None
        self._restarts = hub.sim.device_restarts

    @property
    def native_value(self) -> float | None:
        if self.hub.sim.device_restarts != self._restarts:
            self._restarts = self.hub.sim.device_restarts
            self._written = None  # lost in the device's restart
        return self._written

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"write_type": self.hub.sim.config.write_type.value}

    async def async_set_native_value(self, value: float) -> None:
        self._written = value
        self.hub.sim.entity_setpoint(self.hub.now(), value)
        self.hub.refresh()


class ZoneTarget(SimEntity, NumberEntity):
    """The target of a zone's thermostatic heads (when VT does not drive its valve)."""

    platform_domain = "number"
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_native_min_value = 5.0
    _attr_native_max_value = 30.0
    _attr_native_step = 0.5
    _attr_mode = NumberMode.BOX

    def __init__(self, hub: SimHub, zone: str) -> None:
        super().__init__(hub, f"{zone}_target", f"{zone} target")
        self.zone = zone

    @property
    def native_value(self) -> float:
        index = [z.zone_id for z in self.hub.sim.zones].index(self.zone)
        return self.hub.sim.plant.targets[index]

    async def async_set_native_value(self, value: float) -> None:
        self.hub.sim.set_zone_target(self.zone, value)
        self.hub.refresh()
