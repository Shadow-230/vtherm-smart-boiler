"""Repair flows: the user settles what the plugin cannot."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class ReturnedByHandFlow(RepairsFlow):
    """A hand-back is owed that cannot get through — its target replaced or gone for good. The
    user confirms that the boiler runs on its own control again; the plugin then forgets what
    it owed, stops retrying, and lets the options change the target."""

    def __init__(self, entry_id: str) -> None:
        self._entry_id = entry_id

    async def async_step_init(self, user_input: dict[str, str] | None = None) -> FlowResult:
        return await self.async_step_confirm()

    async def async_step_confirm(self, user_input: dict[str, str] | None = None) -> FlowResult:
        if user_input is not None:
            await async_release(self.hass, self._entry_id)
            return self.async_create_entry(data={})
        return self.async_show_form(step_id="confirm", data_schema=vol.Schema({}))


async def async_release(hass: HomeAssistant, entry_id: str) -> None:
    """Forget an owed hand-back: in the running unit, or in the store the last run left."""
    entry = hass.config_entries.async_get_entry(entry_id)
    if entry is None:
        return
    if entry.state is not ConfigEntryState.LOADED:
        await _async_release_stored(hass, entry_id)  # disabled, or its options unreadable
        return
    coordinator = entry.runtime_data
    unit = coordinator.control or coordinator.hand_back_unit
    if unit is not None:
        unit.release_owed_hand_back()
        return
    # No unit: the options that took the boiler are gone; the store keeps what was owed.
    _LOGGER.warning("The owed hand-back is settled by hand, as the user confirmed")
    coordinator.stored_control = {
        **coordinator.stored_control,
        "controlling": False,
        "hand_back_pending": False,
    }
    await coordinator.async_save_now()


async def _async_release_stored(hass: HomeAssistant, entry_id: str) -> None:
    from homeassistant.helpers.storage import Store

    from .const import STORAGE_VERSION

    store = Store[dict[str, Any]](hass, STORAGE_VERSION, f"{DOMAIN}.{entry_id}")
    data = await store.async_load()
    if not isinstance(data, dict) or not isinstance(data.get("control"), dict):
        return
    _LOGGER.warning("The owed hand-back is settled by hand, as the user confirmed")
    control = {**data["control"], "controlling": False, "hand_back_pending": False}
    await store.async_save({**data, "control": control})


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None
) -> RepairsFlow:
    entry_id = (data or {}).get("entry_id")
    if issue_id.startswith("hand_back_owed_") and isinstance(entry_id, str):
        return ReturnedByHandFlow(entry_id)
    return ConfirmRepairFlow()
