"""The control switch: off by default, experimental, and refused while control is not allowed."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .control_config import hand_back_effect
from .coordinator import SmartBoilerCoordinator
from .entity import ControlEntity

# Blockers that pass on their own; control switched on waits for them instead of refusing.
TRANSIENT_BLOCKERS = frozenset({"ha_starting", "vt_central_boiler_unknown"})
# Blockers the switch change itself clears.
CLEARED_BY_SWITCHING = frozenset({"control_error"})


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: SmartBoilerCoordinator = entry.runtime_data
    if coordinator.control is not None:
        async_add_entities([ControlSwitch(coordinator)])


class ControlSwitch(ControlEntity, SwitchEntity, RestoreEntity):
    """The user's wish to control the boiler; control runs only while nothing blocks it.

    After a restart the switch comes back as it was; control then waits for its blockers (Home
    Assistant starting, missing data) to clear. Switching on by hand is refused while a blocker
    that needs the user remains.
    """

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control")

    @property
    def is_on(self) -> bool:
        return self.control.enabled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        effect = hand_back_effect(self.control.options)
        return {
            "experimental": True,
            "blockers": list(status.blockers),
            "hand_back_effect": None if effect is None else effect.value,
            "allowed_services": sorted(f"{d}.{s}" for d, s in self.control.allowed_services),
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state == STATE_ON:
            await self.control.async_set_enabled(True)
        self.control.mark_restored()

    async def async_turn_on(self, **kwargs: Any) -> None:
        blockers = [
            b
            for b in self.control.blockers(dt_util.utcnow().timestamp())
            if b not in TRANSIENT_BLOCKERS | CLEARED_BY_SWITCHING
        ]
        if blockers:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key=f"blocked_{blockers[0]}",
                translation_placeholders={"others": ", ".join(blockers[1:]) or "-"},
            )
        await self.control.async_set_enabled(True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.control.async_set_enabled(False)
        self.async_write_ha_state()
