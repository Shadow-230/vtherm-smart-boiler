"""The stub gateway's entities: pushed on every simulator step, unavailable while the simulated
gateway is out of reach, on a boiler device and a thermostat device as the real integration's
are, with unique IDs of the same form (``<gateway ID>-<device>-<key>``)."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity

from . import DOMAIN, Hub


class StubEntity(Entity):
    _attr_should_poll = False
    platform_domain = "sensor"

    def __init__(self, hub: Hub, gateway_id: str, device: str, key: str, name: str) -> None:
        self.hub = hub
        self.key = key
        self._attr_unique_id = f"{gateway_id}-{device}-{key}"
        self._attr_name = name
        self.entity_id = f"{self.platform_domain}.otgw_{gateway_id}_{device}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"{gateway_id}-{device}")},
            name=f"Simulated OpenTherm {device} {gateway_id}",
        )

    @property
    def available(self) -> bool:
        return self.hub.sim.gateway_reachable()

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_listener(self.async_write_ha_state))
