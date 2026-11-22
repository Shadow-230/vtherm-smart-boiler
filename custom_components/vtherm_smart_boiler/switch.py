"""The control switch: off by default, experimental, and refused while control is not allowed —
the refusal naming the first blocker in its own text and counting the others (P-74). And the
switch that puts the Boiler page in Home Assistant's sidebar (``plan-0.2-i10.md``, I10.1)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .coordinator import SmartBoilerConfigEntry, SmartBoilerCoordinator
from .entity import SmartBoilerEntity
from .panel import async_hide_panel, async_show_panel

PARALLEL_UPDATES = 1  # one switch action at a time


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartBoilerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    # I11.3: control is switched in the settings and by automations; its state is the binary
    # sensor "Control" (plan-0.2-i11.md, the user's decisions of 2026-11-22).
    entities: list[SwitchEntity] = [SidebarPageSwitch(coordinator)]
    coordinator.expect_entities("switch", entities)
    async_add_entities(entities)


class SidebarPageSwitch(SmartBoilerEntity, SwitchEntity, RestoreEntity):
    """Whether the Boiler page is in Home Assistant's sidebar, for every user: on by default,
    an option to hide it (the user's decisions of 2026-11-18). It changes nothing else — no
    reload, nothing written to the boiler — and comes back after a restart as it was left.
    Without Home Assistant's frontend it keeps its state and shows nothing."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "sidebar_page")
        self._attr_is_on = True

    @property
    def available(self) -> bool:
        """The page does not depend on the monitor's refresh."""
        return True

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_OFF:
            self._attr_is_on = False
        if self._attr_is_on:
            await async_show_panel(self.hass, self.coordinator.config_entry.entry_id)

    async def async_will_remove_from_hass(self) -> None:
        """A reload keeps the page: taking it away throws a user on it off with an error, and
        the start registers it again in one step (J4 I10.10, F17). It goes with the entry
        disabled or this switch disabled; the entry removed takes it in ``async_remove_entry``."""
        registered = self.registry_entry
        if self.coordinator.config_entry.disabled_by is not None or (
            registered is not None and registered.disabled
        ):
            async_hide_panel(self.hass)
        await super().async_will_remove_from_hass()

    @callback
    def async_entity_id_changed(self, old_entity_id: str) -> None:
        """The user renamed the switch's ID: Home Assistant 2026.11 onward changes it in place,
        so the page stays; older versions remove the switch and add it again, which takes the
        page away and puts it back as the switch was."""
        changed = getattr(super(), "async_entity_id_changed", None)
        if changed is not None:
            changed(old_entity_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._attr_is_on = True
        await async_show_panel(self.hass, self.coordinator.config_entry.entry_id)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._attr_is_on = False
        async_hide_panel(self.hass)
        self.async_write_ha_state()
