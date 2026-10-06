"""Step 1.4d of plan 0.2.3: SB-10 (decision 12). A setup that fails where a hand-back stops
heating — judged by the options that can be read, else by the options the control was taken with
— and the stored wish is not a clear "off" raises at once a persistent error-level repair issue:
the plugin did not start and the house is not heated (or may not be, where no options tell). A
later setup that works removes it, and so does the entry's removal; an owed hand-back still goes
first.

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN

from .test_control import (  # the rig fixture comes with them
    HAND_BACK,
    Rig,
    issue,
    options,
    rig,  # noqa: F401
    seed_stores,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

ISSUE = "setup_failed_not_heated"
MAY_NOT_BE_HEATED = "setup_failed_may_not_be_heated"
STANDALONE = "gateway_standalone"  # a gateway without a thermostat: a hand-back stops heating
WITH_THERMOSTAT = "gateway_with_thermostat"
# Options this version cannot read: a boiler class and a write path it does not know.
UNREADABLE = {"boiler": {"class": "no such class"}, "control": {"write_path": "carrier_pigeon"}}


def fail_platforms(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """The next setup fails late, in its platforms — after the hand-back it owed was made."""
    original = rig.hass.config_entries.async_forward_entry_setups
    failures = [RuntimeError("the platforms could not be set up")]

    async def forward(*args: Any, **kwargs: Any) -> None:
        if failures:
            raise failures.pop()
        await original(*args, **kwargs)

    monkeypatch.setattr(rig.hass.config_entries, "async_forward_entry_setups", forward)


def entry_with(
    rig: Rig, hass_storage: dict[str, Any], state: Any, entry_options: dict[str, Any]
) -> MockConfigEntry:
    """An entry whose last run left ``state`` in its control store."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, state, "0.2.2")
    rig.entry = entry
    return entry


async def failed_setup(rig: Rig, entry: MockConfigEntry, state: ConfigEntryState) -> None:
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is state


def assert_raised(rig: Rig, key: str) -> None:
    found = issue(rig, ISSUE)
    assert found is not None
    assert found.translation_key == key
    assert found.is_persistent
    assert not found.is_fixable
    assert found.severity is ir.IssueSeverity.ERROR


@pytest.mark.parametrize(
    ("wish", "topology", "raised"),
    [(True, STANDALONE, True), (False, STANDALONE, False), (True, WITH_THERMOSTAT, False)],
    ids=["standalone_on", "standalone_off", "thermostat_on"],
)
async def test_a_failed_setup_where_a_hand_back_stops_heating_raises_an_issue(
    rig: Rig,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    wish: bool,
    topology: str,
    raised: bool,
) -> None:
    """SB-10: at once, with the wish "on" where a hand-back stops heating; none with the wish
    "off" (no heat from control either way) or with a thermostat that takes over."""
    fail_platforms(rig, monkeypatch)
    entry = entry_with(rig, hass_storage, {"enabled": wish}, options(rig.zones, topology=topology))
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    if raised:
        assert_raised(rig, ISSUE)
    else:
        assert issue(rig, ISSUE) is None


async def test_the_owed_hand_back_goes_before_the_issue(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An owed hand-back is made first, as before; the issue follows, and nothing is written
    after it."""
    calls_at_issue: list[int] = []
    create = ir.async_create_issue

    def spy(hass: Any, domain: str, issue_id: str, **kwargs: Any) -> None:
        if issue_id.startswith(ISSUE):
            calls_at_issue.append(len(rig.gateway.calls))
        create(hass, domain, issue_id, **kwargs)

    monkeypatch.setattr(ir, "async_create_issue", spy)
    fail_platforms(rig, monkeypatch)
    state = {"enabled": True, "controlling": True, "hand_back_pending": True}
    entry = entry_with(rig, hass_storage, state, options(rig.zones, topology=STANDALONE))
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert calls_at_issue == [len(rig.gateway.calls)]
    assert_raised(rig, ISSUE)


@pytest.mark.parametrize(
    ("taken_with", "key"),
    [(STANDALONE, ISSUE), (WITH_THERMOSTAT, None), (None, MAY_NOT_BE_HEATED)],
    ids=["taken_standalone", "taken_with_thermostat", "nothing_taken"],
)
async def test_unreadable_options_are_judged_by_the_options_the_boiler_was_taken_with(
    rig: Rig, hass_storage: dict[str, Any], taken_with: str | None, key: str | None
) -> None:
    """The options cannot be read, their control section neither: the options the control was
    taken with decide. Without them nothing tells what a hand-back does, so the house may not be
    heated: the cautious wording, rather than silence (the plugin did not start either way)."""
    taken = None if taken_with is None else options(rig.zones, topology=taken_with)["control"]
    entry = entry_with(
        rig,
        hass_storage,
        {"enabled": True, "taken_with": taken},
        options(rig.zones) | UNREADABLE,
    )
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    if key is None:
        assert issue(rig, ISSUE) is None
    else:
        assert_raised(rig, key)
    assert rig.gateway.calls == []  # nothing owed: nothing written


async def test_an_unreadable_control_store_counts_as_control_on(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The control store is damaged: the hand-back is made as if the boiler was held, and the
    wish, unknown, counts as "on" — the plugin did not start and the house is not heated."""
    fail_platforms(rig, monkeypatch)
    entry = entry_with(
        rig, hass_storage, ["not", "a", "mapping"], options(rig.zones, topology=STANDALONE)
    )
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert issue(rig, "control_state_unreadable") is None  # SB-39: the hand-back confirmed
    assert_raised(rig, ISSUE)


async def test_a_store_read_that_fails_is_judged_by_the_options_alone(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The options cannot be read but their control section can, and reading the control state
    fails outright: no crash; the owed hand-back is reported, cautiously, and the options'
    section — a stand-alone gateway — says the house is not heated."""
    from custom_components.vtherm_smart_boiler import coordinator

    async def broken(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("the stores cannot be read")

    monkeypatch.setattr(coordinator, "async_read_control_state", broken)
    entry_options = options(rig.zones, topology=STANDALONE) | {"boiler": UNREADABLE["boiler"]}
    entry = entry_with(rig, hass_storage, {"enabled": False}, entry_options)
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    assert issue(rig, "hand_back_owed") is not None
    assert_raised(rig, ISSUE)


@pytest.mark.parametrize("then", ["setup_works", "entry_removed"])
async def test_the_issue_goes_once_a_setup_works_or_the_entry_is_removed(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, then: str
) -> None:
    fail_platforms(rig, monkeypatch)  # the first setup only
    entry = entry_with(
        rig, hass_storage, {"enabled": True}, options(rig.zones, topology=STANDALONE)
    )
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    assert_raised(rig, ISSUE)
    if then == "setup_works":
        assert await rig.hass.config_entries.async_reload(entry.entry_id)
        await rig.hass.async_block_till_done()
        assert entry.state is ConfigEntryState.LOADED
    else:
        await rig.hass.config_entries.async_remove(entry.entry_id)
        await rig.hass.async_block_till_done()
    assert issue(rig, ISSUE) is None


async def test_a_failed_setup_that_no_longer_leaves_the_house_unheated_clears_the_issue(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An earlier failure raised the issue; the next setup fails again, now with control
    switched off: the issue no longer holds, so it goes."""
    entry = entry_with(
        rig, hass_storage, {"enabled": False}, options(rig.zones, topology=STANDALONE)
    )
    ir.async_create_issue(
        rig.hass,
        DOMAIN,
        f"{ISSUE}_{entry.entry_id}",
        is_fixable=False,
        is_persistent=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE,
    )
    fail_platforms(rig, monkeypatch)
    await failed_setup(rig, entry, ConfigEntryState.SETUP_ERROR)
    assert issue(rig, ISSUE) is None
