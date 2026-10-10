"""Step 1.3 of plan 0.2.3: the control unit's wish and hand-back debt hold under errors and
restarts — the review of 2026-10-04, PB-02, PB-04, PB-05, PB-12, PB-13, PB-14 and PB-16, with the
missing tests TB-02, TB-05 and TB-06.

- PB-02: the wish the switch restores is in the control store before anything else.
- PB-04, PB-05, TB-02: after an error in the control step, the hand-back the step decided is made
  even before its debt was marked, and an owed one keeps its minute and its confirmation.
- PB-12: a hand-back whose writes go through but never show the release raises the fixable owed
  issue once it shows as failed.
- PB-13: a new session folds an owed hand-back in at its first write attempt: its own writes are
  never judged another controller's, and its hand-back stays whole.
- PB-14: the lost link's issue is kept across a restart, and follows ``blocked_by``.
- PB-16: a control-store write that fails keeps control from taking the boiler, with a repair
  issue, until the store has written for a while without a failure (M1 of the part-1 check);
  the store's watch passes on whatever Home Assistant's store gives it (L2).
- TB-05, TB-06: a stop that cannot get the unit's lock in time keeps the debt; a switch change or
  a restore queued behind a stop does nothing.

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import asyncio
import copy
import dataclasses
import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import CoreState, HomeAssistant, State
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import storage as ha_storage
from homeassistant.util import dt as dt_util
from homeassistant.util.file import WriteError
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.vtherm_smart_boiler import control as control_module
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

from .test_control import (  # the rig fixture comes with them
    EXPECTED,
    HAND_BACK,
    LOWEST,
    RESTORED,
    SWITCH,
    FakeNumber,
    FakeSwitch,
    Rig,
    _logged,
    alarm,
    blockers,
    control_key,
    held_entity,
    issue,
    link_alarm,
    low_setpoint_off,  # noqa: F401
    main_key,
    not_started,
    owed_entry,
    restorable,
    rig,  # noqa: F401
    seed_stores,
    set_up,
    settle,
    start,
    start_with_stored,
    stored_control,
    unit_of,
    vt_central_unknown,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

LINK_ISSUE = "hand_back_boiler_link_lost"
STORE_ISSUE = "control_state_not_saved"
OWED = "hand_back_owed"
NO_DEMAND = {"hvac_action": "idle", "valve_open_percent": 0, "on_percent": 0.0}


def broken(self: Any, *args: Any) -> None:
    raise RuntimeError("a bug in the control step")


async def broken_step(self: Any, now: float) -> None:
    raise RuntimeError("a bug in the control step")


def active(rig: Rig, key: str) -> bool:
    found = issue(rig, key)
    return found is not None and found.active


async def crash_and_start(rig: Rig, hass_storage: dict[str, Any], left: dict[str, Any]) -> None:
    """Home Assistant crashes, leaving ``left`` in the control store, and starts again: the
    entry unloads here (its stop writes what it writes), then the stores are put back as the
    crash left them, and the entry is set up anew."""
    entry = rig.entry
    assert entry is not None
    assert await rig.hass.config_entries.async_unload(entry.entry_id)
    await rig.hass.async_block_till_done()
    seed_stores(hass_storage, entry, left, "0.2.2")
    rig.gateway.calls.clear()
    await set_up(rig, entry)


def made_inactive(rig: Rig, key: str) -> None:
    """The issue as Home Assistant loads a non-persistent one after a restart: kept, inactive
    (``issue_registry._async_load``, Home Assistant 2026.9.3)."""
    assert rig.entry is not None
    registry = ir.async_get(rig.hass)
    issue_id = f"{key}_{rig.entry.entry_id}"
    found = registry.async_get_issue(DOMAIN, issue_id)
    assert found is not None
    registry.issues[(DOMAIN, issue_id)] = dataclasses.replace(found, active=False)


async def restart(rig: Rig, inactive: tuple[str, ...] = ()) -> None:
    """Home Assistant restarting: the entry unloads, the issues ``inactive`` names come back
    inactive, and the entry is set up again."""
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    assert await rig.hass.config_entries.async_unload(entry_id)
    await rig.hass.async_block_till_done()
    for key in inactive:
        made_inactive(rig, key)
    assert await rig.hass.config_entries.async_setup(entry_id)
    await rig.hass.async_block_till_done()


@contextmanager
def writes_failing(key: str, after: int = 0) -> Iterator[list[str]]:
    """Every write of the store ``key`` — after its first ``after`` ones — fails as Home
    Assistant's own writer fails on a full disk or a storage turned read-only: ``WriteError``,
    which its store logs and swallows. The other stores are written as before. Yields the failed
    writes, by key. Undone inside the test: the storage mock this wraps is the test's own (see
    ``REAL_STORE_LOAD`` in the control tests)."""
    write = ha_storage.Store._async_write_data  # the test's storage mock
    failed: list[str] = []
    passed = 0

    async def failing(store: ha_storage.Store[Any], data: dict[str, Any]) -> None:
        nonlocal passed
        if store.key == key:
            if passed >= after:
                failed.append(store.key)
                raise WriteError(OSError(30, "Read-only file system"))
            passed += 1
        await write(store, data)

    with patch.object(ha_storage.Store, "_async_write_data", failing):
        yield failed


@contextmanager
def control_writes(rig: Rig, fails: Callable[[int], bool]) -> Iterator[list[tuple[float, bool]]]:
    """Each write of this entry's control store, numbered from 1, fails where ``fails`` says so
    (``WriteError``, as in ``writes_failing``) — a store that fails now and then, a dying SD card
    say. Yields every write's time and whether it went through."""
    assert rig.entry is not None
    key = control_key(rig.entry)
    write = ha_storage.Store._async_write_data  # the test's storage mock
    log: list[tuple[float, bool]] = []

    async def flaky(store: ha_storage.Store[Any], data: dict[str, Any]) -> None:
        if store.key == key:
            ok = not fails(len(log) + 1)
            log.append((dt_util.utcnow().timestamp(), ok))
            if not ok:
                raise WriteError(OSError(5, "Input/output error"))
        await write(store, data)

    with patch.object(ha_storage.Store, "_async_write_data", flaky):
        yield log


def first_working_after(log: list[tuple[float, bool]], at: float) -> float | None:
    """The first write in ``log`` after ``at`` that went through."""
    return next((t for t, ok in log if ok and t > at), None)


@contextmanager
def control_writes_failing(rig: Rig, after: int = 0) -> Iterator[list[str]]:
    """Every write of this entry's control store fails, after its first ``after`` ones
    (``writes_failing``)."""
    assert rig.entry is not None
    with writes_failing(control_key(rig.entry), after) as failed:
        yield failed


# --- PB-02: the restored wish, stored before anything else -------------------------------------


@pytest.mark.parametrize("held_by", ["blocker", "restore_waiting"])
async def test_the_restored_wish_is_stored_before_any_write(
    rig: Rig, hass_storage: dict[str, Any], held_by: str
) -> None:
    """PB-02: the switch gives the stored wish "on" back at a start while control writes nothing
    yet — a blocker holds it (VT's central boiler cannot be ruled out), or decision 3's restore
    waits for the boiler link (after a power cut). The control store says "on" at once and still,
    nothing written, a minute and ten minutes on (within the recognition period, for the
    restore): a crash in that window brings control back on, and decision 3's restore runs, with
    no hand-back first. Before the fix the restore stored the old "off" until control's first
    write."""
    if held_by == "blocker":
        vt_central_unknown(rig)
        stored: dict[str, Any] = {"enabled": True}
        marks = (0, 10, 60, 600)
    else:
        not_started(rig)
        rig.flow = None  # the boiler link has not reported since the start
        rig.live()
        stored = restorable(rig)
        marks = (0, 10, 60, 170)
    await start_with_stored(rig, hass_storage, stored, "0.2.2")
    assert unit_of(rig).enabled
    elapsed = 0
    for mark in marks:
        await rig.advance(mark - elapsed)
        elapsed = mark
        assert stored_control(hass_storage, rig)["enabled"] is True, mark
    assert rig.gateway.calls == []  # nothing written: the store is all a crash would leave
    left = copy.deepcopy(stored_control(hass_storage, rig))
    rig.flow = 35.0
    rig.live()
    await crash_and_start(rig, hass_storage, left)
    assert rig.state("switch", "control").state == "on"
    if held_by == "blocker":
        return
    await rig.advance(10)
    assert rig.gateway.calls[:2] == [("setpoint", RESTORED), ("ch", True)]  # decision 3
    assert ("setpoint", 0.0) not in rig.gateway.calls  # no hand-back first


@pytest.mark.parametrize("restored", ["on", "off", None], ids=["on", "off", "nothing_restored"])
async def test_without_a_stored_wish_the_restored_switch_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any], restored: str | None
) -> None:
    """PB-02's negative, missing data: no wish stored (the first start of 0.2.2) — the switch's
    own restored state decides once and is in the control store at once, though a blocker keeps
    control from writing; with no restored state either, control is off, and so is the store."""
    if restored is not None:
        mock_restore_cache(rig.hass, [State(SWITCH, restored)])
    vt_central_unknown(rig)
    await start_with_stored(rig, hass_storage, {}, "0.2.2")
    on = restored == "on"
    assert rig.state("switch", "control").state == ("on" if on else "off")
    assert stored_control(hass_storage, rig)["enabled"] is on
    await rig.advance(60)
    assert stored_control(hass_storage, rig)["enabled"] is on
    assert rig.gateway.calls == []


# --- PB-04: an error between the step's hand-back decision and its mark -----------------------


@pytest.mark.parametrize("where", ["_note_blocker_release", "_latched_now"])
async def test_an_error_after_the_step_decided_a_hand_back_still_hands_back(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, where: str
) -> None:
    """PB-04: control holds the boiler; another controller makes the plugin step aside, and the
    latching step raises after the core decided the hand-back but before its debt was marked —
    in ``_note_blocker_release``, or in ``_latched_now`` (the review's probe B). The error's own
    hand-back is the whole safe hand-back, at once, the debt stored before its first write, as
    the internal error's issue says. Before the fix nothing was written, then or later, and the
    store said "held" with nothing owed."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    unit = unit_of(rig)
    monkeypatch.setattr(type(unit), where, broken)
    seen: list[bool] = []

    def watch(kind: str, value: Any) -> None:
        if (kind, value) == ("setpoint", LOWEST):
            seen.append(stored_control(hass_storage, rig)["hand_back_pending"])

    rig.gateway.watch = watch
    rig.gateway.forced = 60.0  # another controller writes and keeps its value
    for _ in range(20):  # the one rewrite, not confirmed in time: the step that latches
        await rig.advance(10)
        if rig.state("binary_sensor", "alarm_control_error").state == "on":
            break
    assert rig.state("binary_sensor", "alarm_control_error").state == "on"
    assert rig.gateway.calls[-3:] == HAND_BACK  # the whole safe hand-back, over its 60 °C
    assert seen == [True]  # owed and stored before its first write
    assert issue(rig, "hand_back_control_error") is not None
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # the release shows: done, nothing sent again
    assert not unit.hand_back_owed
    assert not unit.holding


async def test_an_error_at_switch_off_hands_back_and_owes_it_until_it_shows(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-04 at a switch-off, with no target of a debt known yet: the step that hands back
    raises before the debt is marked, and the gateway does not show the release at first. The
    hand-back goes out at once all the same, owed and stored, is sent again a minute later, and
    is done once the read-back shows the release."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    monkeypatch.setattr(type(unit), "_note_blocker_release", broken)
    rig.gateway.ignore_release = True
    await rig.switch(False)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert unit.hand_back_owed
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is True
    assert stored["controlling"] is True
    await rig.advance(50)
    assert rig.gateway.setpoints().count(0.0) == 1  # a minute between attempts
    rig.gateway.ignore_release = False
    await rig.advance(20)
    assert rig.gateway.setpoints().count(0.0) == 2
    assert not unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is False


# --- PB-05: the error path keeps the minute and the confirmation ------------------------------


async def test_a_lasting_step_error_sends_the_owed_hand_back_once_a_minute(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-05: an owed hand-back the gateway does not show released (it keeps its override after
    CS=0), and a control step that raises at every step (P-24 expects lasting errors). The
    hand-back goes out once a minute — three CS=0 in two minutes, not twelve — shows as failed
    once its minute is over, with the fixable owed issue, while the internal error's issue says
    the boiler was handed back."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.gateway.ignore_release = True
    monkeypatch.setattr(type(unit), "_async_step", broken_step)
    sent = rig.gateway.setpoints().count(0.0)
    await rig.advance(10)  # the first failing step: the whole safe hand-back
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert rig.gateway.setpoints().count(0.0) == sent + 1
    assert unit.hand_back_owed
    assert alarm(rig) == "off"
    await rig.advance(40)
    assert rig.gateway.setpoints().count(0.0) == sent + 1  # nothing more within the minute
    assert issue(rig, OWED) is None
    await rig.advance(20)
    assert rig.gateway.setpoints().count(0.0) == sent + 2
    assert alarm(rig) == "on"
    found = issue(rig, OWED)
    assert found is not None
    assert found.is_fixable
    await rig.advance(60)
    assert rig.gateway.setpoints().count(0.0) == sent + 3
    assert issue(rig, "hand_back_control_error") is not None
    assert unit.hand_back_owed


# --- TB-02: an owed hand-back whose own attempt raises --------------------------------------------


@pytest.mark.parametrize("raising", ["hand_back", "store"])
async def test_an_owed_hand_back_that_raises_at_setup_stays_owed_and_is_retried(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    raising: str,
) -> None:
    """TB-02 (control.py's ``async_hand_back_owed``): the last run left a hand-back owed, and the
    attempt at setup raises once — the attempt itself (a bug), or the store before it (the
    gateway then keeps its override at first). Setup completes; the debt stays owed and stored,
    ``hand_back_failed`` shows once the start's grace is over, and the hand-back is retried at
    the minute and goes through."""
    original_try = control_module.ControlUnit._async_try_hand_back
    original_save = SmartBoilerCoordinator.async_save_control_now
    calls = 0

    async def try_once(self: Any, *args: Any, **kwargs: Any) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("a bug in the hand-back")
        await original_try(self, *args, **kwargs)

    async def save_once(self: Any) -> bool:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("no space left on the device")
        return await original_save(self)

    if raising == "hand_back":
        monkeypatch.setattr(control_module.ControlUnit, "_async_try_hand_back", try_once)
    else:
        monkeypatch.setattr(SmartBoilerCoordinator, "async_save_control_now", save_once)
        rig.gateway.ignore_release = True
    entry = owed_entry(rig, hass_storage)
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    unit = unit_of(rig)
    assert unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True
    if raising == "hand_back":
        assert rig.gateway.calls == []
        assert (
            _logged(caplog, logging.ERROR, "Handing back what the last run left owed failed") == 1
        )
    else:
        assert rig.gateway.calls == HAND_BACK  # made all the same, not shown
        assert _logged(caplog, logging.ERROR, "Could not store the owed hand-back") == 1
    sent = len(rig.gateway.calls)
    await rig.advance(50)
    assert len(rig.gateway.calls) == sent  # retried at the minute, not before
    assert unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is True
    if raising == "hand_back":
        assert alarm(rig) == "on"  # a failed attempt shows at once
        await rig.advance(20)
        assert rig.gateway.calls == HAND_BACK  # the retry, through
        assert not unit.hand_back_owed
        assert alarm(rig) == "off"
        return
    assert alarm(rig) == "off"  # within the start's grace, a target not shown raises nothing
    await rig.advance(20)
    assert rig.gateway.setpoints().count(0.0) == 2  # the retry at the minute
    assert alarm(rig) == "on"  # the grace is over
    assert unit.hand_back_owed
    rig.gateway.ignore_release = False
    await rig.advance(60)
    assert not unit.hand_back_owed
    assert stored_control(hass_storage, rig)["hand_back_pending"] is False


async def test_a_failing_step_whose_hand_back_and_issues_fail_keeps_the_debt(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TB-02 (the error path's own failures): the control step raises at every step, the
    hand-back raises too (a bug in the writer) and the issue registry fails. The debt stays
    stored, each error is logged once — later ones at DEBUG — and the hand-back is tried once a
    minute, never at every step."""
    from custom_components.vtherm_smart_boiler.transport.writers import OpenthermGwWriter

    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    attempts: list[float] = []

    async def hand_back(self: Any, **kwargs: Any) -> Any:
        attempts.append(rig.hass.loop.time())
        raise RuntimeError("a bug in the writer")

    create = ir.async_create_issue

    def create_issue(hass: HomeAssistant, domain: str, *args: Any, **kwargs: Any) -> None:
        if domain == DOMAIN:
            raise RuntimeError("the issue registry fails")
        create(hass, domain, *args, **kwargs)

    monkeypatch.setattr(OpenthermGwWriter, "hand_back", hand_back)
    monkeypatch.setattr(type(unit), "_async_step", broken_step)
    monkeypatch.setattr(ir, "async_create_issue", create_issue)
    caplog.clear()
    await rig.advance(10)
    assert len(attempts) == 1
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is True
    assert stored["controlling"] is True
    await rig.advance(50)
    assert len(attempts) == 1  # not at every step
    await rig.advance(20)
    assert len(attempts) == 2  # once a minute
    await rig.advance(60)
    assert len(attempts) == 3
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is True
    assert stored["controlling"] is True
    assert unit.hand_back_owed
    assert _logged(caplog, logging.ERROR, "The control step failed") == 1
    assert _logged(caplog, logging.ERROR, "Handing control back failed") == 1
    assert _logged(caplog, logging.ERROR, "Handing control back after an error failed") == 1
    # The entry unloads with all of it still failing: the stop never raises, so the unload goes
    # through, and the debt stays stored for the next start.
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert rig.entry.state is ConfigEntryState.NOT_LOADED
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is True
    assert stored["controlling"] is True


@pytest.mark.parametrize("also", ["learning_release", "issue_registry"])
async def test_a_lasting_step_error_with_another_failure_keeps_the_minutes_retry(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, also: str
) -> None:
    """TB-02 with a second lasting failure (L1 of the part-1 check): the control step raises at
    every step, the gateway does not show the owed hand-back released, and — at every step as
    well — the release of learning raises, or the issue registry fails for this integration.
    The hand-back still goes out once a minute: a step that made no attempt does not put the
    retry off, and an owed issue that cannot be raised does not stop the attempt. Before: CS=0
    once in six minutes."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    unit = unit_of(rig)
    rig.gateway.ignore_release = True
    monkeypatch.setattr(type(unit), "_async_step", broken_step)
    if also == "learning_release":

        async def broken_release(self: Any, now: float) -> None:
            raise RuntimeError("a bug in the learning release")

        monkeypatch.setattr(type(unit), "_async_release_learning", broken_release)
    else:
        create = ir.async_create_issue

        def create_issue(hass: HomeAssistant, domain: str, *args: Any, **kwargs: Any) -> None:
            if domain == DOMAIN:
                raise RuntimeError("the issue registry fails")
            create(hass, domain, *args, **kwargs)

        monkeypatch.setattr(ir, "async_create_issue", create_issue)
    sent = rig.gateway.setpoints().count(0.0)
    await rig.advance(10)  # the first failing step: the whole safe hand-back
    assert rig.gateway.setpoints().count(0.0) == sent + 1
    await rig.advance(40)
    assert rig.gateway.setpoints().count(0.0) == sent + 1  # nothing more within the minute
    for minute in range(1, 6):
        await rig.advance(60 if minute > 1 else 20)
        assert rig.gateway.setpoints().count(0.0) == sent + 1 + minute
    assert unit.hand_back_owed


async def test_an_error_whose_hand_back_raises_with_nothing_held_owes_nothing(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-02's negative: control off, nothing held or owed; the step raises, and so does what
    the error path does instead of a hand-back (learning's release). No debt is made up: nothing
    is owed or stored as owed, and nothing is written."""
    await start(rig)
    unit = unit_of(rig)

    async def release(self: Any, now: float) -> None:
        raise RuntimeError("a bug in the learning release")

    monkeypatch.setattr(type(unit), "_async_step", broken_step)
    monkeypatch.setattr(type(unit), "_async_release_learning", release)
    await rig.advance(70)
    assert not unit.hand_back_owed
    assert not unit.holding
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is False
    assert stored["controlling"] is False
    assert rig.gateway.calls == []


# --- PB-12: the fixable owed issue once a hand-back stays unconfirmed --------------------------


@pytest.mark.parametrize("target", ["gateway", "held_entity"])
@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_hand_back_whose_release_never_shows_raises_the_fixable_owed_issue(
    rig: Rig, target: str
) -> None:
    """PB-12 (the review's probe C): the hand-back's writes go through, but the release never
    shows — a gateway that takes CS=<lowest> and drops CS=0, or a held setpoint entity that keeps
    the lowest water temperature. Once ``hand_back_failed`` shows — a minute on for the gateway,
    a step on for the held entity — the fixable ``hand_back_owed`` issue is raised, and it stays
    through the retries that stay unconfirmed; its fix flow, the only way to settle the debt by
    hand while the entry runs (S-45), stops them. Negative: before the alarm, no issue."""
    from homeassistant.components.repairs import DOMAIN as REPAIRS
    from homeassistant.setup import async_setup_component

    number = FakeNumber(rig.hass)
    if target == "gateway":
        await start(rig)
        await rig.switch(True)
        await rig.advance(20)
        rig.gateway.ignore_release = True
        alarm_after = 60

        def sent() -> int:
            return len(rig.gateway.calls)

    else:
        number.register()
        await start(rig, **held_entity(number, hand_back_value=15))
        await rig.switch(True)
        number.lowest = 20.0  # it keeps the lowest the hand-back writes first
        alarm_after = 10

        def sent() -> int:
            return len(number.writes)

    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    assert alarm(rig) == "off"
    assert issue(rig, OWED) is None
    await rig.advance(alarm_after - 10)
    assert alarm(rig) == "off"
    assert issue(rig, OWED) is None
    await rig.advance(10)
    assert alarm(rig) == "on"
    found = issue(rig, OWED)
    assert found is not None
    assert found.active
    assert found.is_fixable
    assert not found.is_persistent
    assert found.severity is ir.IssueSeverity.ERROR
    before = sent()
    await rig.advance(60)
    assert sent() > before  # sent again at the minute, still not shown...
    assert issue(rig, OWED) is not None  # ...so the issue stays
    assert await async_setup_component(rig.hass, REPAIRS, {})
    manager = rig.hass.data[REPAIRS]["flow_manager"]
    flow = await manager.async_init(DOMAIN, data={"issue_id": found.issue_id})
    flow = await manager.async_configure(flow["flow_id"], {})
    assert flow["type"] == "create_entry"
    count = sent()
    await rig.advance(130)
    assert sent() == count  # no more retries
    assert issue(rig, OWED) is None
    assert alarm(rig) == "off"
    assert not unit_of(rig).hand_back_owed


# --- PB-13: the old debt folded at the session's first write attempt --------------------------


async def owe_with_a_switch_shown_on(rig: Rig) -> tuple[FakeNumber, FakeSwitch]:
    """A hand-back owed through a held setpoint entity and a held heating switch: the switch is
    back on and read back so, while the setpoint entity has gone away — its part does not get
    through. Then more than the five minutes after the unit's start in which a change of the
    switch would be taken for a trace of an outage. A session's setpoint write fails while the
    entity is away, so its first write that goes through is the switch's."""
    number = FakeNumber(rig.hass)
    number.register()
    switch = FakeSwitch(rig.hass)
    switch.register()
    await start(rig, **held_entity(number, ch_entity=switch.entity_id, ch_write_type="held"))
    await rig.switch(True)
    await rig.advance(20)
    assert switch.on
    number.set_available(False)
    await rig.switch(False)
    assert unit_of(rig).hand_back_owed
    assert switch.on
    await rig.advance(310)
    assert unit_of(rig).hand_back_owed
    rig.zones.set("living", **NO_DEMAND)  # the next session switches heating off
    return number, switch


async def test_a_new_sessions_own_write_is_not_taken_for_another_controller(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-13 (the review's probe B2): with that hand-back owed, a new session takes the boiler
    and switches heating off — the plugin's own write. It is not judged "taken by another
    controller" — no warning, no issue — and the old debt is folded into the session. Before the
    fix the old debt's watch, still on, took it for another controller's."""
    _number, switch = await owe_with_a_switch_shown_on(rig)
    caplog.clear()
    await rig.switch(True)
    assert switch.on is False
    assert _logged(caplog, logging.WARNING, "another controller holds") == 0
    assert issue(rig, "hand_back_taken_by_other") is None
    assert not unit_of(rig).hand_back_owed  # folded into the session, whose hand-back is whole
    await rig.advance(30)
    assert _logged(caplog, logging.WARNING, "another controller holds") == 0
    assert issue(rig, "hand_back_taken_by_other") is None


async def test_a_sessions_write_that_lands_but_reports_a_failure_is_still_handed_back(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-13 (the review's probes B and B3): with that hand-back owed, the new session's "heating
    off" lands, but its service call reports a failure (a slow integration past the cap). The
    debt is folded in at that attempt, so the switch is not taken for another controller's; the
    session's own hand-back — the user switches control off once the entity is back — turns the
    switch back on, as "own control resumes" needs, and nothing is left owed. Before the fix
    that hand-back skipped the switch, leaving it off with nothing owed."""
    number, switch = await owe_with_a_switch_shown_on(rig)
    switch.fail_off = True
    caplog.clear()
    await rig.switch(True)
    assert switch.on is False
    assert issue(rig, "hand_back_taken_by_other") is None
    unit = unit_of(rig)
    assert unit.holding
    switch.fail_off = False
    number.set_available(True)
    await rig.switch(False)
    await rig.advance(10)
    assert switch.on is True
    assert not unit.hand_back_owed
    assert not unit.holding
    assert alarm(rig) == "off"
    assert issue(rig, "hand_back_taken_by_other") is None
    assert _logged(caplog, logging.WARNING, "another controller holds") == 0


# --- PB-14: the lost link's issue across restarts ---------------------------------------------


async def lose_the_link_while_holding(rig: Rig) -> None:
    """Stand-alone, control holds the boiler; then the flow is gone for five minutes: handed
    back, with the error-level issue of the lost link."""
    await start(rig, topology="gateway_standalone")
    await rig.switch(True)
    await rig.advance(30)
    rig.flow = None
    await rig.advance(310)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert active(rig, LINK_ISSUE)


@pytest.mark.parametrize("link", ["still_lost", "back"])
async def test_the_lost_link_issue_is_kept_across_a_restart(rig: Rig, link: str) -> None:
    """PB-14 (the review's probe A): the lost link handed back with its issue, then Home
    Assistant restarts — bringing every non-persistent issue back inactive — with the link still
    lost. The issue is raised again at once, an error, and stays while the link stays lost: ten
    minutes on the alarm is on and ``blocked_by`` names it; it goes once control resumes by
    itself. Negative: the link back at the restart — control takes the boiler at its first step,
    and no issue is left behind."""
    await lose_the_link_while_holding(rig)
    if link == "back":
        rig.flow = 35.0
        rig.live()
    await restart(rig, (LINK_ISSUE,))
    if link == "back":
        assert rig.gateway.setpoints()[-1] == EXPECTED  # control holds the boiler again
        assert issue(rig, LINK_ISSUE) is None
        await rig.advance(80)
        assert issue(rig, LINK_ISSUE) is None
        return
    found = issue(rig, LINK_ISSUE)
    assert found is not None
    assert found.active
    assert found.severity is ir.IssueSeverity.ERROR
    await rig.advance(600)
    assert link_alarm(rig) == "on"
    assert rig.state("switch", "control").attributes["blocked_by"] == ["boiler_link_lost"]
    assert active(rig, LINK_ISSUE)
    rig.flow = 35.0
    await rig.advance(80)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # control resumed by itself
    assert issue(rig, LINK_ISSUE) is None


async def test_the_lost_link_issue_is_kept_across_a_reload(rig: Rig) -> None:
    """PB-14 at a reload, which keeps a non-persistent issue up: the new run takes it on, keeps
    it while the link stays lost, and deletes it once control resumes by itself."""
    await lose_the_link_while_holding(rig)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert active(rig, LINK_ISSUE)
    await rig.advance(60)
    assert active(rig, LINK_ISSUE)
    rig.flow = 35.0
    await rig.advance(400)  # the link fresh again, past the five minutes it needs after a start
    assert rig.gateway.setpoints()[-1] == EXPECTED
    assert issue(rig, LINK_ISSUE) is None


async def test_a_lost_link_issue_left_with_control_off_goes_at_the_start(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """PB-14's negative: the lost link's issue an earlier run left up, with the stored wish off —
    control is off, nothing resumes: it goes at the start."""
    from custom_components.vtherm_smart_boiler.control import HAND_BACK_ISSUE, HAND_BACK_LINK

    entry = owed_entry(rig, hass_storage)
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"{HAND_BACK_ISSUE}_{HAND_BACK_LINK}_{entry.entry_id}",
        is_fixable=False,
        severity=ir.IssueSeverity.ERROR,
        translation_key=f"{HAND_BACK_ISSUE}_{HAND_BACK_LINK}",
    )
    assert active(rig, LINK_ISSUE)
    await set_up(rig, entry)
    assert issue(rig, LINK_ISSUE) is None


async def test_the_lost_link_issue_goes_with_control_switched_off_and_stays_gone(
    rig: Rig,
) -> None:
    """PB-14's negative: the user switches control off while the link is lost — the issue goes,
    and a restart with the link still lost does not raise it again."""
    await lose_the_link_while_holding(rig)
    await rig.switch(False)
    assert issue(rig, LINK_ISSUE) is None
    await restart(rig)
    await rig.advance(600)
    assert issue(rig, LINK_ISSUE) is None


async def test_the_lost_link_issue_follows_blocked_by(rig: Rig) -> None:
    """PB-14, the issue's own rule: whenever control is switched on, does not hold the boiler and
    the boiler link is lost — ``blocked_by`` names it, here switched on while the link was
    already lost — the issue is up, an error stand-alone; switched off, it goes."""
    await start(rig, topology="gateway_standalone")
    rig.flow = None
    await rig.advance(320)
    await rig.switch(True)
    await rig.advance(10)
    assert rig.state("switch", "control").attributes["blocked_by"] == ["boiler_link_lost"]
    assert rig.gateway.calls == []
    found = issue(rig, LINK_ISSUE)
    assert found is not None
    assert found.severity is ir.IssueSeverity.ERROR
    await rig.switch(False)
    assert issue(rig, LINK_ISSUE) is None


@pytest.mark.parametrize(
    ("stored", "raised"),
    [(True, True), ("unreadable", True), (False, False), (None, False), ("wish_off", False)],
    ids=["set", "unreadable", "clear", "missing", "wish_off"],
)
async def test_a_stored_lost_link_issue_is_read_cautiously(
    rig: Rig, hass_storage: dict[str, Any], stored: Any, raised: bool
) -> None:
    """PB-14, missing data: the flag the last run stored that the lost link's issue was up is
    read cautiously — one that cannot be read counts as set, and the issue is raised at once
    while the stored wish is on; none stored, or the wish off, none raised (the link still lost,
    within the five minutes its alarm needs after a start)."""
    control: dict[str, Any] = {"enabled": stored != "wish_off"}
    if stored == "wish_off":
        control["link_lost_issue"] = True
    elif stored is not None:
        control["link_lost_issue"] = stored
    rig.flow = None
    rig.live()
    await start_with_stored(rig, hass_storage, control, "0.2.2", topology="gateway_standalone")
    await rig.advance(60)
    assert active(rig, LINK_ISSUE) is raised
    assert rig.gateway.calls == []


# --- PB-16: a control-store write that fails ---------------------------------------------------


async def test_control_does_not_take_the_boiler_while_its_memory_cannot_be_written(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """PB-16: every write of the control store fails (a full disk, a storage turned read-only:
    Home Assistant's store logs it and goes on). Switched on, control does not take the boiler —
    a crash would forget it holds it: the blocker ``control_state_not_saved`` and an error-level
    repair issue say why, the switch stays on, and the store is tried again every minute;
    nothing is written to the boiler. Once the store has written for ``STORE_HOLD_S`` without a
    failure, both go, control takes the boiler, and the store says so."""
    await start(rig)
    with control_writes_failing(rig) as failed:
        await rig.switch(True)
        assert rig.state("switch", "control").state == "on"  # not refused: it passes by itself
        assert "control_state_not_saved" in blockers(rig)
        found = issue(rig, STORE_ISSUE)
        assert found is not None
        assert found.severity is ir.IssueSeverity.ERROR
        assert not found.is_fixable
        assert rig.gateway.calls == []
        tries = len(failed)
        assert tries >= 1
        await rig.advance(50)
        assert len(failed) == tries  # not at every step
        await rig.advance(20)
        assert len(failed) == tries + 1  # once a minute
        assert rig.gateway.calls == []
    await rig.advance(60)  # the minute's retry works: control is held off a while longer
    assert "control_state_not_saved" in blockers(rig)
    assert rig.gateway.calls == []
    await rig.advance(control_module.STORE_HOLD_S)
    assert "control_state_not_saved" not in blockers(rig)
    assert issue(rig, STORE_ISSUE) is None
    assert rig.gateway.setpoints() == [EXPECTED]
    stored = stored_control(hass_storage, rig)
    assert stored["enabled"] is True
    assert stored["controlling"] is True


async def test_a_session_whose_hold_cannot_be_stored_does_not_take_the_boiler(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """PB-16 at the session's first write: the wish is stored, then the store fails at the write
    that marks the boiler held — made before the write, as a crash must know of it. Nothing is
    written: the boiler is not taken; the next step shows the blocker and the issue, with
    nothing to hand back. Control takes the boiler once the store has written for
    ``STORE_HOLD_S`` without a failure."""
    await start(rig)
    unit = unit_of(rig)
    with control_writes_failing(rig, after=1) as failed:  # the wish goes through, then none
        await rig.switch(True)
        assert failed
        assert rig.gateway.calls == []  # not taken
        assert not unit.holding
        assert stored_control(hass_storage, rig)["controlling"] is False
        await rig.advance(10)
        assert "control_state_not_saved" in blockers(rig)
        assert issue(rig, STORE_ISSUE) is not None
        assert rig.gateway.calls == []  # nothing held: nothing to hand back
    await rig.advance(60)
    assert issue(rig, STORE_ISSUE) is not None  # held off a while longer
    await rig.advance(control_module.STORE_HOLD_S)
    assert issue(rig, STORE_ISSUE) is None
    assert rig.gateway.setpoints() == [EXPECTED]
    assert stored_control(hass_storage, rig)["controlling"] is True


async def test_a_control_store_failing_while_control_holds_the_boiler_hands_back(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-16 while control holds the boiler: a write of the control store fails — here the one
    that stores heating switched off at once. The next step hands the boiler back, though its
    debt cannot be stored first (a hand-back is never held back), with the blocker and the
    issue; once the store has written for ``STORE_HOLD_S`` without a failure, control takes the
    boiler afresh."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    with control_writes_failing(rig) as failed:
        rig.zones.set("living", **NO_DEMAND)
        await rig.advance(10)  # heating off, stored at once: the write fails
        tries = len(failed)
        assert tries >= 1
        await rig.advance(10)  # the blocker: the safe hand-back
        assert rig.gateway.calls[-3:] == HAND_BACK
        assert len(failed) > tries  # the debt's own save, made first, failed too: made anyway
        assert "control_state_not_saved" in blockers(rig)
        assert issue(rig, STORE_ISSUE) is not None
        assert _logged(caplog, logging.ERROR, "The control state could not be written") == 1
    rig.zones.set("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    await rig.advance(70)
    assert issue(rig, STORE_ISSUE) is not None  # held off a while longer
    assert rig.gateway.calls[-3:] == HAND_BACK
    await rig.advance(control_module.STORE_HOLD_S)
    assert issue(rig, STORE_ISSUE) is None
    assert rig.gateway.setpoints()[-1] == EXPECTED


async def held_off_until(rig: Rig, at: float) -> ir.IssueEntry:
    """Steps until shortly before ``at``, control held off at each: the blocker up and the
    store's error issue the same one throughout — neither deleted nor raised again."""
    found = issue(rig, STORE_ISSUE)
    assert found is not None
    while dt_util.utcnow().timestamp() < at - 10:
        await rig.advance(10)
        assert "control_state_not_saved" in blockers(rig)
        assert issue(rig, STORE_ISSUE) == found
    return found


async def test_one_failed_control_store_write_hands_back_once_and_holds_control_off(
    rig: Rig,
) -> None:
    """PB-16's hold-off (M1 of the part-1 check): one write of the control store fails while
    control holds the boiler. The next step hands back — once: the writes that work after it,
    the debt's own first, do not let control take the boiler again; the blocker and the error
    issue hold until the store has written for ``STORE_HOLD_S`` without a failure, the store
    written again every minute meanwhile. Then control takes the boiler again. Before: control
    took the boiler again a step after the hand-back — a burner cycle ten seconds apart."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    rig.gateway.calls.clear()
    with control_writes(rig, lambda n: n == 1) as log:
        await coordinator.async_save_control_now()  # the one write that fails
        await rig.advance(10)  # the blocker: the safe hand-back
        assert rig.gateway.calls == HAND_BACK
        working = first_working_after(log, 0.0)  # the debt's own write
        assert working is not None
        await held_off_until(rig, working + control_module.STORE_HOLD_S)
        assert rig.gateway.calls == HAND_BACK  # not taken in between
        # The minute's retry kept writing the store meanwhile.
        retries = [t for t, ok in log if t > working + 1]
        assert len(retries) >= control_module.STORE_HOLD_S / control_module.STORE_RETRY_S - 1
        assert all(ok for _, ok in log[1:])
        await rig.advance(30)
    assert "control_state_not_saved" not in blockers(rig)
    assert issue(rig, STORE_ISSUE) is None
    assert rig.gateway.setpoints()[-1] == EXPECTED


async def test_a_control_store_failing_every_other_write_hands_back_once(rig: Rig) -> None:
    """PB-16's hold-off with a store that fails at every second write (a dying SD card) for a
    quarter of an hour: one hand-back, control held off and the error issue up throughout —
    each failure, the minute's retry meeting them, starts the hold again. Once the writes work,
    control takes the boiler ``STORE_HOLD_S`` after the first that worked. Before: thirteen
    hand-backs in five minutes, the issue created and deleted with each."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    rig.gateway.calls.clear()
    failing = True
    with control_writes(rig, lambda n: failing and n % 2 == 1) as log:
        await coordinator.async_save_control_now()  # the first write fails
        await rig.advance(10)
        assert rig.gateway.calls == HAND_BACK
        await held_off_until(rig, dt_util.utcnow().timestamp() + 15 * 60)
        assert rig.gateway.calls == HAND_BACK  # one hand-back; the boiler never taken again
        assert sum(not ok for _, ok in log) >= 7  # the minute's retry met the failures
        failing = False
        last_failure = max(t for t, ok in log if not ok)
        while (working := first_working_after(log, last_failure)) is None:
            await rig.advance(10)
            assert "control_state_not_saved" in blockers(rig)
        await held_off_until(rig, working + control_module.STORE_HOLD_S)
        assert rig.gateway.calls == HAND_BACK
        await rig.advance(30)
    assert "control_state_not_saved" not in blockers(rig)
    assert issue(rig, STORE_ISSUE) is None
    assert rig.gateway.setpoints()[-1] == EXPECTED


async def test_a_delayed_control_save_that_fails_is_noticed(rig: Rig) -> None:
    """PB-16: a control save made without waiting (``schedule_control_save``) that fails is
    noticed too, at the next step."""
    await start(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    with control_writes_failing(rig) as failed:
        coordinator.schedule_control_save()
        await rig.advance(10)  # written at the next turn of the loop: it fails
        assert failed
        assert coordinator.control_store_failing
        await rig.advance(10)
        assert "control_state_not_saved" in blockers(rig)
        assert issue(rig, STORE_ISSUE) is not None


async def test_the_entry_stores_own_failure_does_not_keep_control_from_the_boiler(
    rig: Rig,
) -> None:
    """PB-16's negative: only the control store counts — the entry's own store failing (the
    monitor's days, a copy of the control state) neither blocks control nor raises the issue."""
    await start(rig)
    assert rig.entry is not None
    with writes_failing(main_key(rig.entry)) as failed:
        await rig.switch(True)
        await rig.advance(20)
        assert failed
        assert rig.gateway.setpoints()[-1] == EXPECTED
        assert "control_state_not_saved" not in blockers(rig)
        assert issue(rig, STORE_ISSUE) is None


async def test_an_error_the_store_lets_through_counts_as_a_failed_write(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """PB-16: an error Home Assistant's store does not catch itself — an ``OSError`` its own
    writer does not wrap — counts as a failed write as well: logged, noted, and never raised to
    the caller; the next write that works ends it."""
    await start(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    key = control_key(rig.entry)
    write = ha_storage.Store._async_write_data  # the test's storage mock

    async def failing(store: ha_storage.Store[Any], data: dict[str, Any]) -> None:
        if store.key == key:
            raise PermissionError(13, "Permission denied")
        await write(store, data)

    with patch.object(ha_storage.Store, "_async_write_data", failing):
        assert await coordinator.async_save_control_now() is False
    assert coordinator.control_store_failing
    assert _logged(caplog, logging.ERROR, "Could not write the control state") == 1
    assert await coordinator.async_save_control_now() is True
    assert not coordinator.control_store_failing


async def test_a_control_store_write_with_no_outcome_is_not_a_failure(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """PB-16, unknown outcome: Home Assistant stopping defers a store's write to its final write
    (``Store.async_save``), so nothing is known of it yet — no outcome is told, not a failure;
    and a store with no one to tell (the repair release's, the removal's) takes a failure
    quietly."""
    from custom_components.vtherm_smart_boiler.coordinator import control_store

    told: list[bool] = []
    store = control_store(hass, "x", told.append)
    hass.set_state(CoreState.stopping)
    try:
        await store.async_save({"controlling": True})
    finally:
        hass.set_state(CoreState.running)
    assert told == []
    with writes_failing(store.key):
        await store.async_save({"controlling": True})
    assert told == [False]
    await store.async_save({"controlling": False})
    assert told == [False, True]
    quiet = control_store(hass, "y")
    with writes_failing(quiet.key) as failed:
        await quiet.async_save({"controlling": True})  # nothing raised
    assert failed == [quiet.key]


async def test_the_control_stores_watch_passes_on_an_argument_more(hass: HomeAssistant) -> None:
    """PB-16 (L2 of the part-1 check): the watch on the control store's writes overrides a
    private method of Home Assistant's store, so it passes on whatever it is given — an argument
    a later Home Assistant adds included — and still tells each outcome, rather than making
    every control-store write fail and blocking control for good."""
    from custom_components.vtherm_smart_boiler.coordinator import control_store

    told: list[bool] = []
    store = control_store(hass, "x", told.append)
    given: list[tuple[Any, ...]] = []

    async def write_data(self: Any, data: dict[str, Any], *args: Any, **kwargs: Any) -> None:
        given.append((data, args, kwargs))
        if kwargs.get("fail"):
            raise WriteError(OSError(30, "Read-only file system"))

    with patch.object(ha_storage.Store, "_async_write_data", write_data):
        await store._async_write_data({"controlling": True}, "more", flag=True)
        with pytest.raises(WriteError):
            await store._async_write_data({"controlling": False}, fail=True)
    assert given == [
        ({"controlling": True}, ("more",), {"flag": True}),
        ({"controlling": False}, (), {"fail": True}),
    ]
    assert told == [True, False]


# --- TB-05: the stop cannot get the unit's lock in time ----------------------------------------


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_stop_that_cannot_get_the_lock_in_time_keeps_the_debt(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """TB-05 (H9): control holds the boiler through a held entity, and a switch change holds the
    unit's lock beyond the stop's budget in a slow store write — not a step, so the stop cannot
    cancel it. The entry unloads: the stop returns within its budget, the debt stays stored and
    the persistent ``hand_back_owed`` issue is raised; once the slow write ends, nothing more is
    written — the late switch change runs no step after the stop."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    unit = unit_of(rig)
    assert rig.entry is not None
    coordinator = rig.entry.runtime_data
    monkeypatch.setattr(control_module, "STOP_BUDGET_S", 2.0)
    original = coordinator.async_save_control_now
    slow = asyncio.Event()

    async def slow_save() -> bool:
        await slow.wait()
        return await original()

    monkeypatch.setattr(coordinator, "async_save_control_now", slow_save)
    switching = asyncio.ensure_future(unit.async_set_enabled(False))
    await settle(rounds=20)
    assert not switching.done()  # it holds the lock, waiting in the store
    unload = asyncio.ensure_future(rig.hass.config_entries.async_unload(rig.entry.entry_id))
    await settle(rounds=50)
    assert not unload.done()
    rig.freezer.tick(2.5)  # past the budget
    assert await settle(unload, rounds=200), "the stop outlasted its budget"
    assert await unload
    assert number.writes == [EXPECTED]  # the lock was never free: nothing handed back
    found = issue(rig, OWED)
    assert found is not None
    assert found.is_persistent
    stored = stored_control(hass_storage, rig)
    assert stored["hand_back_pending"] is True
    assert stored["controlling"] is True
    assert _logged(caplog, logging.ERROR, "ran out of time") == 1
    slow.set()
    await switching
    await rig.hass.async_block_till_done()
    assert number.writes == [EXPECTED]  # nothing after the stop
    assert unit.stopping


# --- TB-06: a switch change or a restore queued behind a stop ------------------------------------


@pytest.mark.parametrize("call", ["set_enabled", "restore_enabled"])
async def test_a_switch_change_queued_behind_a_stop_does_nothing(
    rig: Rig, hass_storage: dict[str, Any], call: str
) -> None:
    """TB-06: the boiler holds a value of the plugin's — a hand-back owed — and the stop holds
    the unit's lock for its hand-back (the gateway slow to take it). Switching control on, or
    the switch restoring "on" before it ever restored (here it is disabled in Home Assistant),
    queued behind it: once the stop is through, nothing is written after its hand-back, control
    stays off and the unit stays stopped."""
    if call == "set_enabled":
        await start(rig)
        await rig.switch(True)
        await rig.advance(20)
        rig.gateway.ignore_release = True
        await rig.switch(False)  # handed back, not shown: still held, and owed
    else:
        entry = owed_entry(rig, hass_storage)
        er.async_get(rig.hass).async_get_or_create(
            "switch",
            DOMAIN,
            f"{entry.entry_id}_control",
            config_entry=entry,
            disabled_by=er.RegistryEntryDisabler.USER,
        )
        rig.gateway.ignore_release = True
        await set_up(rig, entry)
    unit = unit_of(rig)
    assert unit.holding
    assert unit.hand_back_owed
    assert not unit.enabled
    rig.gateway.ignore_release = False
    hanging = asyncio.Event()
    rig.gateway.block_hand_back = hanging
    stop = asyncio.ensure_future(unit.async_stop())
    await settle(rounds=50)
    assert rig.gateway.calls[-1] == ("ch", True)  # the stop's hand-back hangs in its first call
    if call == "set_enabled":
        queued = asyncio.ensure_future(unit.async_set_enabled(True))
    else:
        queued = asyncio.ensure_future(unit.async_restore_enabled(True))
    assert not await settle(queued, rounds=50), "it did not wait for the stop"
    hanging.set()
    await stop
    count = len(rig.gateway.calls)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # the stop's hand-back, through
    await queued
    await rig.hass.async_block_till_done()
    await rig.advance(30)
    assert len(rig.gateway.calls) == count  # nothing after the stop's hand-back
    assert not unit.enabled
    assert unit.stopping
