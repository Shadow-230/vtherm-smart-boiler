"""The repair flows: settling an owed hand-back by hand (S-45), and every other issue."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.components.repairs import ConfirmRepairFlow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.repairs import (
    ReturnedByHandFlow,
    async_create_fix_flow,
    async_release,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_only_an_owed_hand_back_with_its_entry_gets_the_release_flow(
    hass: HomeAssistant,
) -> None:
    """Any other issue, or one whose entry is not named, gets Home Assistant's plain
    confirmation: nothing is released by it."""
    owed = await async_create_fix_flow(hass, "hand_back_owed_abc", {"entry_id": "abc"})
    assert isinstance(owed, ReturnedByHandFlow)
    for issue_id, data in (
        ("auto_tpi_blocked_abc", {"entry_id": "abc"}),
        ("hand_back_owed_abc", None),
        ("hand_back_owed_abc", {"entry_id": 5}),
    ):
        assert isinstance(await async_create_fix_flow(hass, issue_id, data), ConfirmRepairFlow)


async def test_releasing_an_entry_that_is_gone_changes_nothing(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    await async_release(hass, "no_such_entry")
    assert not [key for key in hass_storage if key.startswith(DOMAIN)]


async def test_a_release_by_hand_without_an_entry_store_writes_the_control_store_only(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """S-45 with the entry not loaded and its main store lost: the control store says nothing
    is owed any more, and no main store is made up."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", options={})
    entry.add_to_hass(hass)
    key = f"{DOMAIN}.{entry.entry_id}.control"
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {"controlling": True, "hand_back_pending": True},
    }
    await async_release(hass, entry.entry_id)
    await hass.async_block_till_done()
    assert hass_storage[key]["data"]["controlling"] is False
    assert hass_storage[key]["data"]["hand_back_pending"] is False
    assert f"{DOMAIN}.{entry.entry_id}" not in hass_storage
