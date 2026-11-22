"""The plugin's journal (``docs/en/development/plans/plan-0.2-i10.md``, I10.6), in Home
Assistant: control taken and handed back, the heat call and the water, an alarm, the settings
saved from the page and from the settings, the plugin's starts and stops — kept in its own store
across a reload and removed with the entry, read by the page through
``vtherm_smart_boiler/journal``."""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest

from custom_components.vtherm_smart_boiler.const import DOMAIN

from .test_control import (  # the rig fixture comes with them
    EXPECTED,
    HAND_BACK,
    Rig,
    rig,  # noqa: F401
    start,
)
from .test_websocket import Client, connect

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def journal(client: Client, **fields: Any) -> list[dict[str, Any]]:
    reply = await client.ask("journal", **fields)
    assert reply["success"] is True
    assert (reply["result"]["days"], reply["result"]["max"]) == (14, 2000)
    entries: list[dict[str, Any]] = reply["result"]["entries"]
    assert [e["at"] for e in entries] == sorted(e["at"] for e in entries)
    return entries


def kinds(entries: list[dict[str, Any]]) -> list[str]:
    return [entry["kind"] for entry in entries]


async def test_control_taken_heating_and_handed_back(rig: Rig, hass_ws_client: Any) -> None:
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    assert kinds(await journal(client)) == ["started"]

    await rig.switch(True)
    await rig.advance(60)
    entries = await journal(client)
    took = next(e for e in entries if e["kind"] == "took_over")
    call = next(e for e in entries if e["kind"] == "call_on")
    water = next(e for e in entries if e["kind"] == "water")
    assert "demand" in call["reasons"]
    assert water["value"] == EXPECTED
    assert "previous" not in water  # the first water of the session
    assert took["at"] <= call["at"]

    await rig.switch(False)
    entries = await journal(client)
    back = next(e for e in entries if e["kind"] == "handed_back")
    assert back["reasons"] == ["control_off"]
    assert {"kind": "call_off", "at": back["at"], "reasons": ["not_controlling"]} in entries
    # From a moment on, only what came after it.
    assert kinds(await journal(client, since=back["at"])) == ["handed_back", "call_off"]


async def test_a_reload_under_control_journals_the_hand_back_and_the_takeover(
    rig: Rig, hass_ws_client: Any
) -> None:
    """J4 I10.10, F18 (B1, B3, a page's save): the unload hands the boiler back before the
    stop, and the start takes it again — both journaled, around "stopped" and "started"."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    client = await connect(rig.hass, hass_ws_client)
    entries = await journal(client)
    stop = kinds(entries).index("stopped")
    assert kinds(entries)[stop - 1 : stop + 3] == [
        "handed_back", "stopped", "started", "took_over",
    ]  # fmt: skip
    assert "reasons" not in entries[stop - 1]  # the stop's own: the next entry says why
    assert "water" in kinds(entries)[stop + 3 :]


async def test_home_assistant_stopping_under_control_journals_the_hand_back(rig: Rig) -> None:
    """The hand-back runs as a shutdown job, before the stop event that journals the stop."""
    from custom_components.vtherm_smart_boiler.core.journal import Kind

    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.entry is not None
    journal = rig.entry.runtime_data.journal
    await rig.hass.async_stop()
    assert [e.kind for e in journal.entries][-2:] == [Kind.HANDED_BACK, Kind.STOPPED]


async def test_a_hand_back_still_owed_at_the_stop_is_not_journaled(rig: Rig) -> None:
    """The gateway gone at the unload: the hand-back stays owed (a repair issue says so), and
    the journal does not say it was made."""
    from custom_components.vtherm_smart_boiler.core.journal import Kind

    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.entry is not None
    journal = rig.entry.runtime_data.journal
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert [e.kind for e in journal.entries][-1] == Kind.STOPPED
    assert Kind.HANDED_BACK not in [e.kind for e in journal.entries]


async def test_a_journal_that_cannot_be_written_at_the_unload_stops_nothing(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """I10.10's scope check, gap 2 (a): the journal written at the unload fails — a store that
    cannot be saved — and the unload goes on: the hand-back made first, the platforms unloaded,
    nothing left running."""
    from homeassistant.config_entries import ConfigEntryState

    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    entry = rig.entry
    assert entry is not None

    async def fail() -> None:
        raise OSError("the store cannot be written")

    monkeypatch.setattr(entry.runtime_data.journal, "async_stop", fail)
    assert await rig.hass.config_entries.async_unload(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert rig.gateway.calls[-3:] == HAND_BACK
    count = len(rig.gateway.calls)
    await rig.advance(300)
    assert len(rig.gateway.calls) == count  # no control clock left running


async def test_a_journal_failing_at_a_settings_save_does_not_stop_the_save(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Gap 2 (d): the journal's note of a settings save fails; the save reloads the entry all
    the same, with what was saved."""
    from homeassistant.config_entries import ConfigEntryState

    await start(rig)
    entry = rig.entry
    assert entry is not None
    old = entry.runtime_data

    def fail(_changed: Any) -> None:
        raise RuntimeError("the journal failed")

    monkeypatch.setattr(old.journal, "settings_saved", fail)
    control = dict(entry.options["control"])
    control["curve"] = {**control["curve"], "design_flow": 57}
    rig.hass.config_entries.async_update_entry(entry, options={**entry.options, "control": control})
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not old  # reloaded
    assert entry.runtime_data.options["control"]["curve"]["design_flow"] == 57


async def test_an_alarm_raised_is_journaled(rig: Rig, hass_ws_client: Any) -> None:
    await start(rig)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(True)
    client = await connect(rig.hass, hass_ws_client)
    raised = [e for e in await journal(client) if e["kind"] == "alarm_on"]
    assert {"subject": "alarm_write_failed", "level": "alarm"}.items() <= raised[0].items()


async def test_the_settings_saved_from_the_page_then_from_the_settings(
    rig: Rig, hass_ws_client: Any
) -> None:
    await start(rig)
    client = await connect(rig.hass, hass_ws_client)
    entry = rig.entry
    assert entry is not None

    reply = await client.ask("curve/save", design_outdoor=-12, design_flow=58)
    assert reply["result"]["saved"] is True
    await rig.hass.async_block_till_done(wait_background_tasks=True)  # the settings' reload
    entries = await journal(client)
    # Read back from the store by the entry set up again: the save, the stop, the new start.
    assert kinds(entries) == ["started", "settings", "stopped", "started"]
    assert (entries[1]["subject"], entries[1]["reasons"]) == ("page", ["curve"])

    # A save the page refuses leaves nothing behind for the next save.
    reply = await client.ask("curve/save", design_flow=25)
    assert reply["result"]["saved"] is False
    control = dict(entry.options["control"])
    control["curve"] = {**control["curve"], "design_flow": 57}
    rig.hass.config_entries.async_update_entry(entry, options={**entry.options, "control": control})
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    entries = await journal(client)
    saved = [e for e in entries if e["kind"] == "settings"]
    assert (saved[-1]["subject"], saved[-1]["reasons"]) == ("settings", ["control"])

    # The level of detail changes only what the settings show: no reload, nothing journaled.
    level = "simple" if entry.options.get("level") == "advanced" else "advanced"
    rig.hass.config_entries.async_update_entry(entry, options={**entry.options, "level": level})
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    assert len(await journal(client)) == len(entries)


async def test_kept_in_its_own_store_and_removed_with_the_entry(
    rig: Rig, hass_ws_client: Any
) -> None:
    await start(rig)
    entry = rig.entry
    assert entry is not None
    key = f"{DOMAIN}.{entry.entry_id}.journal"
    assert await rig.hass.config_entries.async_unload(entry.entry_id)
    await rig.hass.async_block_till_done()
    stored = rig.storage[key]["data"]["entries"]
    assert [e["kind"] for e in stored] == ["started", "stopped"]

    # A store that cannot be read starts an empty journal; the plugin runs all the same.
    rig.storage[key] = {"version": 1, "key": key, "data": {"entries": ["damaged", {"at": "x"}]}}
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    client = await connect(rig.hass, hass_ws_client)
    assert kinds(await journal(client)) == ["started"]

    assert await rig.hass.config_entries.async_remove(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert key not in rig.storage


async def test_a_store_that_cannot_be_read_starts_an_empty_journal(
    rig: Rig, hass_ws_client: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from homeassistant.helpers.storage import Store

    from custom_components.vtherm_smart_boiler.journal import Journal

    async def broken(_store: Store[Any]) -> None:
        raise ValueError("not JSON")

    monkeypatch.setattr(Store, "async_load", broken)
    kept = Journal(rig.hass, "x")
    await kept.async_load()
    assert kept.entries == ()
    assert "The journal could not be read" in caplog.text


async def test_a_failure_to_follow_is_logged_once_and_changes_nothing(
    rig: Rig, hass_ws_client: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    from custom_components.vtherm_smart_boiler import journal as module

    real = module.follow
    monkeypatch.setattr(module, "follow", lambda *_args: 1 / 0)
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert caplog.text.count("The journal could not follow a change") == 1
    assert rig.state("sensor", "control_state").state == "heating"  # control went on as ever
    monkeypatch.setattr(module, "follow", real)
    await rig.switch(False)
    client = await connect(rig.hass, hass_ws_client)
    # Followed again: the baseline is set by the first look that works.
    assert kinds(await journal(client))[0] == "started"


def test_a_look_without_the_monitors_data_or_control_sees_nothing() -> None:
    from types import SimpleNamespace

    from custom_components.vtherm_smart_boiler.core.journal import Observed
    from custom_components.vtherm_smart_boiler.journal import observed

    look = observed(SimpleNamespace(data=None, control=None))  # type: ignore[arg-type]
    assert look == Observed(False, None, None, None, (), {})
