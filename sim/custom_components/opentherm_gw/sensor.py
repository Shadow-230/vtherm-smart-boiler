"""The boiler device's "Control setpoint 1" — the gateway's read-back: its acknowledgement of a
command at once, then what the boiler gets — and the thermostat device's "Room setpoint 1" and
"Room temperature 1" of a wall thermostat that sends them, and the boiler's water pressure, with
its 0.0 after a gateway reset (TB-38)."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import UnitOfPressure, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Gateway, Hub, SimGatewayEntry
from .entity import StubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SimGatewayEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    gateway_id = str(entry.data["id"])
    # Device, key, name, what it reads, and the scenario signal that fails it.
    readings = (
        ("boiler", "control_setpoint", "Control setpoint 1", read_back, None),
        ("thermostat", "room_setpoint", "Room setpoint 1", room_setpoint, "thermostat_setpoint"),
        ("thermostat", "room_temperature", "Room temperature 1", room_temperature, None),
    )
    async_add_entities(
        Temperature(hub, gateway_id, device, key, name, value, failable)
        for device, key, name, value, failable in readings
    )
    async_add_entities([Pressure(hub, gateway_id)])


def read_back(sim: Gateway) -> float | None:
    return sim.gateway_read_back()


def room_setpoint(sim: Gateway) -> float | None:
    return sim.wall_setpoint()


def room_temperature(sim: Gateway) -> float | None:
    return sim.wall_room()


class Temperature(StubEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        hub: Hub,
        gateway_id: str,
        device: str,
        key: str,
        name: str,
        value: Callable[[Gateway], float | None],
        failable: str | None = None,
    ) -> None:
        super().__init__(hub, gateway_id, device, key, name)
        self._value = value
        self._failable = failable

    @property
    def available(self) -> bool:
        failed = self._failable is not None and self.hub.sim.signal_failed(self._failable)
        return super().available and not failed

    @property
    def native_value(self) -> float | None:
        value = self._value(self.hub.sim)
        return None if value is None else round(value, 2)


class Pressure(StubEntity, SensorEntity):
    """The boiler's water pressure (pyotgw 2.2.3's ``ch_water_pressure``)."""

    _attr_device_class = SensorDeviceClass.PRESSURE
    _attr_native_unit_of_measurement = UnitOfPressure.BAR
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hub: Hub, gateway_id: str) -> None:
        super().__init__(hub, gateway_id, "boiler", "ch_water_pressure", "Water pressure")

    @property
    def available(self) -> bool:
        return super().available and not self.hub.sim.signal_failed("pressure")

    @property
    def native_value(self) -> float | None:
        value = self.hub.sim.gateway_pressure()
        return None if value is None else round(value, 2)
