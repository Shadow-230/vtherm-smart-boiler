"""Base of the simulator's entities: pushed on every simulation step, unavailable when failed."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from . import DOMAIN, SimHub


class SimEntity(Entity):
    _attr_should_poll = False

    def __init__(self, hub: SimHub, key: str, name: str) -> None:
        self.hub = hub
        self.key = key
        self._attr_unique_id = f"{DOMAIN}_{key}"
        self._attr_name = f"Boiler sim {name}"
        self.entity_id = f"{self.platform_domain}.{DOMAIN}_{key}"

    platform_domain = "sensor"

    # The writable setpoint's device: its entities go while it restarts (S-13).
    _on_device = False

    @property
    def available(self) -> bool:
        if self._on_device and not self.hub.sim.device_reachable():
            return False
        return self.key not in self.hub.sim.failed

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.hub.add_listener(self.async_write_ha_state))
