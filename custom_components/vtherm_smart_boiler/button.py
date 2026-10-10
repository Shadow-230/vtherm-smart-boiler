"""Buttons that reset what the plugin learned or measured, nothing saved, reloaded or handed
back: the "Reset comfort correction" button (answer J of 2026-09-27) — a value the running
session learns, set to 0 — and the two building-model resets (P-90, Y3), which forget the
measured heat loss or heating threshold so that it is fitted again from later days only. The
building model feeds the monitor only (review question 11): its buttons exist with or without
control.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import SmartBoilerConfigEntry, SmartBoilerCoordinator
from .core.parameters import ParameterKey
from .entity import ControlEntity, SmartBoilerEntity, feature_configured

PARALLEL_UPDATES = 1  # one press at a time

# P-90: each reset button and the measured value it forgets.
RESET_BUTTONS = (
    ("reset_loss_coefficient", ParameterKey.LOSS_COEFFICIENT),
    ("reset_heating_threshold", ParameterKey.HEATING_THRESHOLD),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartBoilerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[ButtonEntity] = [
        ResetMeasuredButton(coordinator, key, parameter) for key, parameter in RESET_BUTTONS
    ]
    if coordinator.control is not None and feature_configured(
        coordinator, "reset_comfort_correction"
    ):
        # Only where there is a correction to reset: control that sets the water, with zones
        # and the correction on (the missing-data rule, Y4).
        entities.append(ResetCorrectionButton(coordinator))
    coordinator.expect_entities("button", entities)
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


class ResetMeasuredButton(SmartBoilerEntity, ButtonEntity):
    """Forgets one measured building value — the heat loss or the heating threshold — which is
    then fitted again from the days that start after the press only (P-90). An entered value
    stays, and wins as before; no option changes, so nothing is reloaded or handed back."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self, coordinator: SmartBoilerCoordinator, key: str, parameter: ParameterKey
    ) -> None:
        super().__init__(coordinator, key)
        self._parameter = parameter

    async def async_press(self) -> None:
        await self.coordinator.async_reset_measured(self._parameter)
