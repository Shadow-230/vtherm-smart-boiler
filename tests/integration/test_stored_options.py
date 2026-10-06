"""Step 2.3a of plan 0.2.3: stored options of a wrong shape or value (PB-06, PB-24) and the
failed setup's owed hand-back (TB-03). A section of another shape, or a number the form bounds
stored not finite or outside them, stops the entry with its reason in words; a boiler the last
run held is reported, and decision 12's issue raised where a hand-back stops heating. A control
section of another shape leaves control out, and the owed hand-back still goes out.

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN

from .test_control import (  # the rig fixture comes with them
    LOWEST,
    FakeNumber,
    Rig,
    held_entity,
    issue,
    low_setpoint_off,  # noqa: F401
    options,
    rig,  # noqa: F401
    seed_stores,
    set_up,
    stored_control,
    without_control,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

EN_TEXTS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "custom_components/vtherm_smart_boiler/translations/en.json"
    ).read_text(encoding="utf-8")
)
STANDALONE = "gateway_standalone"  # a gateway without a thermostat: a hand-back stops heating
HELD = {"enabled": True, "controlling": True}  # the last run held the boiler, wish on


def entry_with(
    rig: Rig, hass_storage: dict[str, Any], state: Any, entry_options: dict[str, Any]
) -> MockConfigEntry:
    """An entry whose last run left ``state`` in its control store."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    seed_stores(hass_storage, entry, state, "0.2.2")
    rig.entry = entry
    return entry


@pytest.mark.parametrize(
    ("section", "value", "code"),
    [
        ("monitor", [], "invalid_monitor"),
        ("signals", ["sensor.flow"], "invalid_signals"),
        ("boiler", "flow_setpoint", "invalid_boiler"),
        ("zones", "climate.living", "invalid_zone"),
        ("circuits", {"id": "main"}, "invalid_circuit"),
        ("parameters", [], "invalid_parameters"),
        ("freshness", [60], "invalid_freshness"),
        ("reference_room", "living", "invalid_reference"),
        ("building", [], "invalid_building"),
    ],
)
async def test_a_section_of_another_shape_stops_the_entry_and_reports_a_held_boiler(
    rig: Rig, hass_storage: dict[str, Any], section: str, value: Any, code: str
) -> None:
    """PB-06: ``monitor: []`` (or any section of another shape) with the store saying the boiler
    is held: the entry stops with its reason in words naming the section — not an unexpected
    error — the persistent ``hand_back_owed`` issue tells of the held boiler, and decision 12's
    issue that the house is not heated; nothing is written."""
    entry_options = options(rig.zones, topology=STANDALONE) | {section: value}
    entry = entry_with(rig, hass_storage, HELD, entry_options)
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "invalid_options"
    placeholders = entry.error_reason_translation_placeholders or {}
    assert placeholders["reason"] == EN_TEXTS["options"]["error"][code]
    assert placeholders["subject"] == section
    owed = issue(rig, "hand_back_owed")
    assert owed is not None
    assert owed.is_persistent
    not_heated = issue(rig, "setup_failed_not_heated")
    assert not_heated is not None
    assert not_heated.translation_key == "setup_failed_not_heated"
    assert rig.gateway.calls == []


@pytest.mark.parametrize(
    ("changes", "subject"),
    [
        ({"circuits": [{"id": "main", "max_flow": "nan"}]}, "max_flow"),
        ({"circuits": [{"id": "main", "max_flow": 500}]}, "max_flow"),
        ({"monitor": {"monitoring_days": "inf"}}, "monitoring_days"),
        ({"freshness": {"flow": "nan"}}, "flow"),
        ({"parameters": {"loss_coefficient": [1]}}, "-"),  # unreadable: no section names it
    ],
)
async def test_a_number_outside_the_form_stops_the_entry_and_reports_a_held_boiler(
    rig: Rig, hass_storage: dict[str, Any], changes: dict[str, Any], subject: str
) -> None:
    """PB-24: a circuit maximum of nan or 500 °C, a monitoring period of inf days, a freshness
    limit of nan: the entry stops naming the value — never runs on it — and a held boiler is
    reported."""
    entry = entry_with(rig, hass_storage, HELD, options(rig.zones, topology=STANDALONE) | changes)
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    placeholders = entry.error_reason_translation_placeholders or {}
    assert placeholders["subject"] == subject
    owed = issue(rig, "hand_back_owed")
    assert owed is not None
    assert owed.is_persistent
    assert rig.gateway.calls == []


@pytest.mark.parametrize(
    "control",
    [["opentherm_gw"], "opentherm_gw", {"write_path": "opentherm_gw", "frost_limit": "nan"}],
    ids=["list", "text", "nan"],
)
async def test_a_control_section_that_cannot_be_used_leaves_control_out(
    rig: Rig, hass_storage: dict[str, Any], control: Any
) -> None:
    """PB-06, PB-24: a control section of another shape, or with a frost limit of nan, leaves
    control out — not an unexpected error: the monitor runs, the control-options issue says
    why, and a hand-back owed without the options that took the boiler is asked by hand."""
    entry_options = options(rig.zones) | {"control": control}
    entry = entry_with(rig, hass_storage, {"controlling": True}, entry_options)
    await set_up(rig, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert not entry.runtime_data.config.control.configured
    assert issue(rig, "control_options_invalid") is not None
    assert issue(rig, "hand_back_owed") is not None
    assert rig.gateway.calls == []


async def test_a_failed_late_setup_tells_of_a_hand_back_owed_without_its_options(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """TB-03 (a): the store says the boiler is held, without the options that took it, the
    options hold no control, and the setup fails late (its background start raises): the
    ``hand_back_owed`` issue is persistent — nothing else will tell of the held boiler."""
    from custom_components.vtherm_smart_boiler.coordinator import SmartBoilerCoordinator

    def fail(self: Any) -> None:
        raise RuntimeError("the background start failed")

    monkeypatch.setattr(SmartBoilerCoordinator, "async_start_background", fail)
    entry = entry_with(
        rig, hass_storage, {"controlling": True}, without_control(options(rig.zones))
    )
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    owed = issue(rig, "hand_back_owed")
    assert owed is not None
    assert owed.is_persistent


@pytest.mark.parametrize("section", [True, False], ids=["control", "no_control"])
async def test_unreadable_options_and_a_control_state_that_fails_to_read_report_a_held_boiler(
    rig: Rig, hass_storage: dict[str, Any], monkeypatch: pytest.MonkeyPatch, section: bool
) -> None:
    """TB-03 (b): the options cannot be read and reading the control state fails unexpectedly:
    with a control section it is taken that the boiler was held (the cautious answer) and the
    user is told for good; without one, nothing is owed."""
    from custom_components.vtherm_smart_boiler import coordinator

    async def fail(*args: Any) -> Any:
        raise RuntimeError("the store could not be read")

    monkeypatch.setattr(coordinator, "async_read_control_state", fail)
    entry_options = options(rig.zones) | {"monitor": []}
    if not section:
        entry_options = without_control(entry_options)
    entry = entry_with(rig, hass_storage, {}, entry_options)
    assert not await rig.hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    owed = issue(rig, "hand_back_owed")
    assert (owed is not None) is section
    if owed is not None:
        assert owed.is_persistent


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_hand_back_only_unit_follows_a_renamed_setpoint_entity(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """TB-03 (c): control is out of the options, and the hand-back the last run owed is made by a
    unit built from the options the boiler was taken with; the setpoint entity is renamed while
    it is still owed: what was taken with names the new ID, the entry reloads, and the hand-back
    goes to the new ID."""
    hass = rig.hass
    number = FakeNumber(hass, echo_later=True, value=45.0)  # the hand-back's 50 shows later
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "input_number", "test", "flow", suggested_object_id="fake_boiler_flow"
    )
    number.register()
    taken = held_entity(number) | {"hard_min": LOWEST}
    state = {"controlling": True, "hand_back_pending": True, "taken_with": taken}
    entry = entry_with(rig, hass_storage, state, without_control(options(rig.zones)))
    await set_up(rig, entry)
    unit = entry.runtime_data.hand_back_unit
    assert unit is not None
    assert unit.hand_back_owed
    assert number.writes[-1] == 50.0

    def written_to() -> list[str]:
        return [
            call[2]["entity_id"]
            for call in rig.services
            if call[:2] == ("input_number", "set_value")
        ]

    assert written_to()[-1] == number.entity_id
    old, new = number.entity_id, "input_number.boiler_flow"
    registry.async_update_entity(old, new_entity_id=new)
    hass.states.async_remove(old)  # the device's entity shows under its new ID
    number.entity_id = new
    number.publish(45.0)
    await hass.async_block_till_done(wait_background_tasks=True)
    kept = stored_control(hass_storage, rig)["taken_with"]
    assert kept["setpoint_entity"] == new
    assert kept["confirmed_entity"] == new
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.hand_back_unit is not unit  # reloaded
    assert written_to()[-1] == new
