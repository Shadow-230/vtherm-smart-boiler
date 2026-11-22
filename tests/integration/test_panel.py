"""The Boiler page in the sidebar (``docs/en/development/plans/plan-0.2-i10.md``, I10.1): put
there for every user with its title in Home Assistant's language, taken away and put back by its
switch, gone with the entry, hidden after a restart where it was left hidden, and nothing at all
without Home Assistant's frontend. Its cards (I10.8): the module loaded on every page while the
entry runs, whatever the switch, and no longer once it unloads. The tests have no frontend
package, so its functions and the HTTP server are stand-ins here."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.panel import (
    FRONTEND_DIR,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_MODULE,
    PANEL_URL_PATH,
    STATIC_URL,
)

from .harness import FakeBoiler
from .test_setup import entity_id, entry_for, setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


@dataclass
class Frontend:
    register: AsyncMock
    remove: MagicMock
    serve: AsyncMock
    add_script: MagicMock
    remove_script: MagicMock


@pytest.fixture
def frontend(hass: HomeAssistant) -> Iterator[Frontend]:
    """Home Assistant's frontend as running: the HTTP server and the panel functions."""
    hass.config.components.add("frontend")
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()
    with (
        patch("homeassistant.components.panel_custom.async_register_panel") as register,
        patch("homeassistant.components.frontend.async_remove_panel") as remove,
        patch("homeassistant.components.frontend.add_extra_js_url") as add_script,
        patch("homeassistant.components.frontend.remove_extra_js_url") as remove_script,
    ):
        yield Frontend(
            register, remove, hass.http.async_register_static_paths, add_script, remove_script
        )


async def started(hass: HomeAssistant):
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    return entry


async def test_the_page_is_in_the_sidebar_for_everyone(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    hass.config.language = "pl"
    entry = await started(hass)

    frontend.serve.assert_awaited_once()
    (served,) = frontend.serve.await_args.args[0]
    assert (served.url_path, served.path) == (STATIC_URL, str(FRONTEND_DIR))
    frontend.register.assert_awaited_once()
    kwargs = frontend.register.await_args.kwargs
    assert kwargs["frontend_url_path"] == PANEL_URL_PATH
    assert kwargs["webcomponent_name"] == PANEL_ELEMENT
    assert kwargs["sidebar_title"] == "Kocioł"  # Home Assistant's language
    assert kwargs["sidebar_icon"] == PANEL_ICON
    assert kwargs["require_admin"] is False
    assert kwargs["config"] == {"entry_id": entry.entry_id}
    # The address changes with the page's content: no browser keeps an old copy.
    assert kwargs["module_url"].startswith(f"{STATIC_URL}/{PANEL_MODULE}?v=")
    assert not kwargs["module_url"].endswith("?v=missing")

    page = hass.states.get(entity_id(hass, entry, "switch", "sidebar_page"))
    assert page is not None
    assert page.state == "on"
    registered = er.async_get(hass).async_get(page.entity_id)
    assert registered is not None
    assert registered.entity_category is not None
    assert registered.entity_category.value == "config"


async def test_an_unknown_language_gets_the_english_title(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    hass.config.language = "de"
    await started(hass)
    assert frontend.register.await_args.kwargs["sidebar_title"] == "Boiler"


async def test_the_switch_takes_the_page_away_and_back(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    entry = await started(hass)
    page = entity_id(hass, entry, "switch", "sidebar_page")
    frontend.remove.reset_mock()

    await hass.services.async_call("switch", "turn_off", {"entity_id": page}, blocking=True)
    frontend.remove.assert_called_once_with(hass, PANEL_URL_PATH, warn_if_unknown=False)
    assert hass.states.get(page).state == "off"
    assert frontend.register.await_count == 1

    await hass.services.async_call("switch", "turn_on", {"entity_id": page}, blocking=True)
    assert frontend.register.await_count == 2
    assert hass.states.get(page).state == "on"
    frontend.serve.assert_awaited_once()  # the files are served once per run


async def test_the_page_stays_through_a_reload(hass: HomeAssistant, frontend: Frontend) -> None:
    """J4 I10.10, F17: a reload — a settings save, the page's own curve save — must not take the
    page out of the sidebar while the user is on it (Home Assistant's frontend then throws them
    off it with an error). Nothing takes it away at the unload; the start registers it again in
    one step, its old registration replaced."""
    entry = await started(hass)
    frontend.remove.reset_mock()
    order = MagicMock()
    order.attach_mock(frontend.remove, "remove")
    order.attach_mock(frontend.register, "register")

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [call[0] for call in order.mock_calls] == ["remove", "register"]
    frontend.serve.assert_awaited_once()
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("how", ["disabled", "removed"])
async def test_the_page_goes_with_the_entry(
    hass: HomeAssistant, frontend: Frontend, how: str
) -> None:
    """The entry disabled or removed: the page leaves the sidebar."""
    from homeassistant.config_entries import ConfigEntryDisabler

    entry = await started(hass)
    frontend.remove.reset_mock()
    if how == "disabled":
        assert await hass.config_entries.async_set_disabled_by(
            entry.entry_id, ConfigEntryDisabler.USER
        )
    else:
        assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    frontend.remove.assert_called_with(hass, PANEL_URL_PATH, warn_if_unknown=False)


async def test_the_page_goes_with_its_switch_disabled(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    """The sidebar switch's entity disabled by the user: the page goes with it."""
    entry = await started(hass)
    page = entity_id(hass, entry, "switch", "sidebar_page")
    frontend.remove.reset_mock()
    er.async_get(hass).async_update_entity(page, disabled_by=er.RegistryEntryDisabler.USER)
    await hass.async_block_till_done()
    frontend.remove.assert_called_with(hass, PANEL_URL_PATH, warn_if_unknown=False)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_a_page_left_hidden_stays_hidden_after_a_restart(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    er.async_get(hass).async_get_or_create(
        "switch", DOMAIN, f"{entry.entry_id}_sidebar_page", suggested_object_id="boiler_page"
    )
    mock_restore_cache(hass, [State("switch.boiler_page", "off")])
    await setup(hass, entry)

    assert hass.states.get("switch.boiler_page").state == "off"
    frontend.register.assert_not_awaited()
    frontend.serve.assert_awaited_once()  # for the cards, which do not follow the switch
    frontend.add_script.assert_called_once()


async def test_without_the_frontend_nothing_is_registered(hass: HomeAssistant) -> None:
    """A minimal setup without Home Assistant's frontend: the switch works, no page."""
    with (
        patch("homeassistant.components.panel_custom.async_register_panel") as register,
        patch("homeassistant.components.frontend.async_remove_panel") as remove,
        patch("homeassistant.components.frontend.add_extra_js_url") as add_script,
        patch("homeassistant.components.frontend.remove_extra_js_url") as remove_script,
    ):
        entry = await started(hass)
        page = entity_id(hass, entry, "switch", "sidebar_page")
        assert hass.states.get(page).state == "on"
        await hass.services.async_call("switch", "turn_off", {"entity_id": page}, blocking=True)
        await hass.services.async_call("switch", "turn_on", {"entity_id": page}, blocking=True)
        assert await hass.config_entries.async_unload(entry.entry_id)
    register.assert_not_called()
    remove.assert_not_called()
    add_script.assert_not_called()
    remove_script.assert_not_called()


async def test_the_cards_are_loaded_while_the_entry_runs(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    """I10.8: the page's module on every page of Home Assistant, at its versioned address, so
    its cards are in the card picker; once per address across a reload; gone at unload."""
    entry = await started(hass)
    frontend.add_script.assert_called_once()
    (_hass, url) = frontend.add_script.call_args.args
    assert url == frontend.register.await_args.kwargs["module_url"]  # the page's own module
    assert url.startswith(f"{STATIC_URL}/{PANEL_MODULE}?v=")

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    frontend.remove_script.assert_called_once_with(hass, url)
    assert frontend.add_script.call_count == 2

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert frontend.remove_script.call_count == 2
    assert frontend.remove_script.call_args.args == (hass, url)


async def test_a_new_module_takes_the_place_of_the_old(
    hass: HomeAssistant, frontend: Frontend
) -> None:
    """After an update the module's address changes: the old one is taken away first."""
    from custom_components.vtherm_smart_boiler.panel import async_add_cards

    await started(hass)
    (_hass, old) = frontend.add_script.call_args.args
    with patch("custom_components.vtherm_smart_boiler.panel.module_version", return_value="new"):
        assert await async_add_cards(hass)
        assert await async_add_cards(hass)  # the same address again: nothing to do
    frontend.remove_script.assert_called_once_with(hass, old)
    assert frontend.add_script.call_args.args == (hass, f"{STATIC_URL}/{PANEL_MODULE}?v=new")
    assert frontend.add_script.call_count == 2


@pytest.mark.parametrize("home_assistant_has_it", [True, False])
async def test_a_renamed_switch_keeps_the_page(
    hass: HomeAssistant,
    frontend: Frontend,
    monkeypatch: pytest.MonkeyPatch,
    home_assistant_has_it: bool,
) -> None:
    """The switch's ``async_entity_id_changed`` passes the rename on to Home Assistant's own
    where it has one (2026.11 onward) and takes the page nowhere."""
    from homeassistant.helpers.entity import Entity

    entry = await started(hass)
    calls: list[tuple[str, str]] = []
    if home_assistant_has_it:

        def own(self: Entity, old_entity_id: str) -> None:
            calls.append((self.entity_id, old_entity_id))

        monkeypatch.setattr(Entity, "async_entity_id_changed", own, raising=False)
    else:
        monkeypatch.delattr(Entity, "async_entity_id_changed", raising=False)
    page = entity_id(hass, entry, "switch", "sidebar_page")
    switch = hass.data["switch"].get_entity(page)
    assert switch is not None
    frontend.remove.reset_mock()
    switch.async_entity_id_changed("switch.before")
    assert calls == ([(page, "switch.before")] if home_assistant_has_it else [])
    frontend.remove.assert_not_called()
