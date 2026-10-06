"""The boiler device's "Central heating 1" — the CH enable the gateway sends the boiler — and its
"Fault indication" (ID 0) and "Low water pressure" flag (ID 5), with pyotgw 2.2.3's keys
(TB-38)."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Hub, SimGatewayEntry
from .entity import StubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SimGatewayEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    gateway_id = str(entry.data["id"])
    async_add_entities(
        [
            ChEnable(hub, gateway_id),
            Fault(hub, gateway_id, "slave_fault_indication", "Fault indication", None),
            Fault(
                hub,
                gateway_id,
                "slave_low_water_pressure",
                "Low water pressure",
                "low_pressure_fault",
            ),
        ]
    )


class ChEnable(StubEntity, BinarySensorEntity):
    platform_domain = "binary_sensor"

    def __init__(self, hub: Hub, gateway_id: str) -> None:
        super().__init__(hub, gateway_id, "boiler", "master_ch_enabled", "Central heating 1")

    @property
    def is_on(self) -> bool | None:
        return self.hub.sim.gateway_ch_enable()


class Fault(StubEntity, BinarySensorEntity):
    """The boiler's fault indication (``fault`` ``None``) or one fault's own flag."""

    platform_domain = "binary_sensor"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, hub: Hub, gateway_id: str, key: str, name: str, fault: str | None) -> None:
        super().__init__(hub, gateway_id, "boiler", key, name)
        self._fault = fault

    @property
    def is_on(self) -> bool | None:
        return self.hub.sim.gateway_fault(self._fault)
