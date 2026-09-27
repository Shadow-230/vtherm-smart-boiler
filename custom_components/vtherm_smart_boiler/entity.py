"""Base of the plugin's entities: one device per installation, translated names."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .control import ControlUnit
from .coordinator import SmartBoilerCoordinator


def zone_key(hass: HomeAssistant, zone: str) -> str:
    """What a zone's entities are keyed on: the thermostat's registry entry, which stays when
    its entity ID is renamed; the entity ID only for a thermostat outside the registry."""
    entry = er.async_get(hass).async_get(zone)
    return entry.id if entry is not None else zone


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
        scope = zone_key(coordinator.hass, zone) if zone is not None else circuit
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


class ControlEntity(SmartBoilerEntity):
    """An entity showing control; it updates whenever control's status changes."""

    def __init__(self, coordinator: SmartBoilerCoordinator, key: str) -> None:
        super().__init__(coordinator, key)
        control = coordinator.control
        if control is None:
            raise ValueError("control is not set up")
        self.control: ControlUnit = control

    @property
    def available(self) -> bool:
        """Available while the control unit runs, whatever the monitor's refresh does: the
        control switch must stop the plugin exactly when something is wrong (P-02)."""
        return not self.control.stopping

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self.control.async_add_listener(self.async_write_ha_state))
