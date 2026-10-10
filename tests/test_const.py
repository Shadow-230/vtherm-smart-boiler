"""The pure answer to "is a hand-back owed" (V1, R5): one rule for every place that asks."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.const import (
    assumed_owed_state,
    control_state_owed,
    has_control_section,
    owes_hand_back,
)


@pytest.mark.parametrize(
    ("state", "owed"),
    [
        ({"controlling": True}, True),
        ({"hand_back_pending": True}, True),
        ({"controlling": False, "hand_back_pending": False}, False),
        ({}, False),
        ({"controlling": "maybe"}, True),  # unreadable counts as set
        ({"controlling": ""}, True),
        ({"controlling": None, "hand_back_pending": 0}, False),
        (None, False),
        ("not a mapping", False),
    ],
)
def test_owes_hand_back_reads_flags_cautiously(state: object, owed: bool) -> None:
    assert owes_hand_back(state) is owed


@pytest.mark.parametrize(
    ("options", "found"),
    [
        ({"control": {"write_path": "opentherm_gw"}}, True),
        ({"control": {"write_path": "no such path"}}, True),  # unparseable still counts
        ({"control": {"write_path": None}}, False),
        ({"control": {}}, False),
        ({"control": "garbage"}, False),
        ({}, False),
        (None, False),
    ],
)
def test_a_control_section_names_a_write_path(options: object, found: bool) -> None:
    assert has_control_section(options) is found


def test_a_readable_state_owes_what_its_flags_say() -> None:
    assert control_state_owed({"controlling": True}, readable=True, has_control_section=False)
    assert not control_state_owed({}, readable=True, has_control_section=True)


def test_an_unreadable_state_is_owed_with_control_configured() -> None:
    assert control_state_owed(None, readable=False, has_control_section=True)
    assert control_state_owed({}, readable=False, has_control_section=True)


def test_an_unreadable_state_without_control_owes_only_what_its_copy_says() -> None:
    """A monitor-only entry whose store is lost owes nothing; one whose surviving copy still owes
    a hand-back (control removed while it was owed) does."""
    assert not control_state_owed(None, readable=False, has_control_section=False)
    assert not control_state_owed({}, readable=False, has_control_section=False)
    assert control_state_owed(
        {"hand_back_pending": True}, readable=False, has_control_section=False
    )


def test_the_assumed_state_keeps_the_copy_and_holds_the_boiler() -> None:
    copy = {"taken_with": {"write_path": "entity"}, "latched": True, "controlling": False}
    assert assumed_owed_state(copy) == {
        "taken_with": {"write_path": "entity"},
        "latched": True,
        "controlling": True,
        "hand_back_pending": True,
    }
    assert assumed_owed_state(None) == {"controlling": True, "hand_back_pending": True}
    assert assumed_owed_state(["junk"]) == {"controlling": True, "hand_back_pending": True}
