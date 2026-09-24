"""Base of the plugin's entities: one device per installation, translated names."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SmartBoilerCoordinator


class SmartBoilerEntity(CoordinatorEntity[SmartBoilerCoordinator]):
    """An entity of the plugin; ``zone`` or ``circuit`` make it one per zone or circuit."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SmartBoilerCoordinator,
        key: str,
        *,
        zone: str | None = None,
        circuit: str | None = None,
    ) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.key = key
        self.zone = zone
        self.circuit = circuit
        scope = zone or circuit
        self._attr_unique_id = f"{entry.entry_id}_{key}" + (f"_{scope}" if scope else "")
        self._attr_translation_key = key
        if zone is not None:
            self._attr_translation_placeholders = {"zone": coordinator.link.zone_name(zone)}
        elif circuit is not None:
            self._attr_translation_placeholders = {"circuit": circuit}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="VTherm Smart Boiler",
            model="Boiler monitor",
            entry_type=DeviceEntryType.SERVICE,
        )
