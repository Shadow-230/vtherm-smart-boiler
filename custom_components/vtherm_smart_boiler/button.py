"""The "Reset comfort correction" button (answer J of 2026-09-27): the comfort correction, a
value the running session learns, set to 0 by the user — nothing saved, reloaded or handed back."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartBoilerCoordinator
from .entity import ControlEntity

PARALLEL_UPDATES = 1  # one press at a time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: SmartBoilerCoordinator = entry.runtime_data
    if coordinator.control is not None:
        entities = [ResetCorrectionButton(coordinator)]
        coordinator.expect_entities(entities)
        async_add_entities(entities)


class ResetCorrectionButton(ControlEntity, ButtonEntity):
    """Sets the comfort correction to 0 in the running session (principle 13 (7)): the rise
    may start again under its rules. With control not holding the boiler the correction is
    already 0, and a press changes nothing. Unavailable while the control unit is not running,
    whatever the monitor does (P-02)."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "reset_comfort_correction")

    async def async_press(self) -> None:
        await self.control.async_reset_correction()
