"""The boiler device's "Central heating 1": the CH enable the gateway sends the boiler."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import Hub, SimGatewayEntry
from .entity import StubEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SimGatewayEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([ChEnable(entry.runtime_data, str(entry.data["id"]))])


class ChEnable(StubEntity, BinarySensorEntity):
    platform_domain = "binary_sensor"

    def __init__(self, hub: Hub, gateway_id: str) -> None:
        super().__init__(hub, gateway_id, "boiler", "master_ch_enabled", "Central heating 1")

    @property
    def is_on(self) -> bool | None:
        return self.hub.sim.gateway_ch_enable()
