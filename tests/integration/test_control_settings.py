"""I11.1 (``docs/en/development/plans/plan-0.2-i11.md``): control switched in the plugin's
settings — the tick "Control on" in "Control mode", applied at "Save and finish" as the switch
applied it: off at once with the safe hand-back, on refused while a blocker that needs the user
remains, on saved with other changes taken by the reload's run."""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.setup import async_setup_component

from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler
from .test_control import (  # the rig fixture comes with them
    EXPECTED,
    HAND_BACK,
    Rig,
    rig,  # noqa: F401
    start,
)
from .test_setup import entry_for, setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


def shown(form: dict[str, Any]) -> dict[str, Any]:
    """The values a form shows: each field's default."""
    values: dict[str, Any] = {}
    for marker in form["data_schema"].schema:
        default = getattr(marker, "default", None)
        if callable(default):
            value = default()
            if value is not None and repr(value) != "...":
                values[str(marker)] = value
    return values


async def mode_form(hass: HomeAssistant, entry_id: str) -> dict[str, Any]:
    options = hass.config_entries.options
    flow = await options.async_init(entry_id)
    form = await options.async_configure(flow["flow_id"], {"next_step_id": "mode"})
    assert form["step_id"] == "mode"
    return form


async def save_with(rig: Rig, **answers: Any) -> dict[str, Any]:
    """ "Control mode" answered with what it shows and ``answers``, then "Save and finish"."""
    assert rig.entry is not None
    options = rig.hass.config_entries.options
    form = await mode_form(rig.hass, rig.entry.entry_id)
    menu = await options.async_configure(form["flow_id"], {**shown(form), **answers})
    assert menu["type"] is FlowResultType.MENU
    done = await options.async_configure(form["flow_id"], {"next_step_id": "save"})
    await rig.hass.async_block_till_done(wait_background_tasks=True)
    return done


def control_on(rig: Rig) -> bool:
    return rig.state("binary_sensor", "control").state == "on"


async def started(rig: Rig, **control: Any) -> None:
    """The rig started, then "Control mode" saved once as it shows: the rig's entry lacks what
    the form writes, so its first save reloads; after it, a save without changes does not."""
    await start(rig, **control)
    done = await save_with(rig)
    assert done["type"] is FlowResultType.CREATE_ENTRY


async def test_the_tick_switches_control_on_and_off_without_a_reload(rig: Rig) -> None:
    await started(rig)
    assert rig.entry is not None
    running = rig.entry.runtime_data
    form = await mode_form(rig.hass, rig.entry.entry_id)
    assert shown(form)["control_on"] is False  # the wish as it stands
    rig.hass.config_entries.options.async_abort(form["flow_id"])

    done = await save_with(rig, control_on=True)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert rig.entry.runtime_data is running  # applied, not reloaded
    assert control_on(rig)
    await rig.advance(60)
    assert ("setpoint", EXPECTED) in rig.gateway.calls

    form = await mode_form(rig.hass, rig.entry.entry_id)
    assert shown(form)["control_on"] is True
    rig.hass.config_entries.options.async_abort(form["flow_id"])
    done = await save_with(rig, control_on=False)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert rig.gateway.calls[-3:] == HAND_BACK  # the safe hand-back at once
    assert not control_on(rig)


async def test_a_blocker_that_needs_the_user_refuses_the_tick(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """On refused, as the switch refused it: the first blocker's own text and the count of the
    others; nothing changes, and the menu shows again."""
    await started(rig)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    monkeypatch.setattr(
        unit, "blockers", lambda _now: ("thermostat_kind_unknown", "vt_central_boiler_active")
    )
    refused = await save_with(rig, control_on=True)
    assert refused["step_id"] == "control_blocked"
    placeholders = refused["description_placeholders"]
    assert "Boiler interface" in placeholders["first"]  # the blocker's own text
    assert placeholders["more"] == "1"
    menu = await rig.hass.config_entries.options.async_configure(refused["flow_id"], {})
    assert menu["type"] is FlowResultType.MENU
    rig.hass.config_entries.options.async_abort(menu["flow_id"])
    assert not control_on(rig)
    assert rig.gateway.calls == []


async def test_blockers_that_pass_on_their_own_are_waited_for(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Home Assistant starting and the like refuse nothing: control is on and waits."""
    await started(rig)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    monkeypatch.setattr(unit, "blockers", lambda _now: ("ha_starting",))
    done = await save_with(rig, control_on=True)
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert control_on(rig)


async def test_the_tick_saved_with_other_changes_is_taken_by_the_next_run(rig: Rig) -> None:
    """Saved with another change, which reloads the entry: the wish is kept for the reload's
    run, which takes the boiler with the new options — this run, its options being replaced,
    never takes it."""
    await started(rig)
    assert rig.entry is not None
    running = rig.entry.runtime_data
    form = await mode_form(rig.hass, rig.entry.entry_id)
    other = next(key for key in ("condensing", "dhw_priority") if key in shown(form))
    rig.hass.config_entries.options.async_abort(form["flow_id"])
    before = len(rig.gateway.calls)

    done = await save_with(rig, control_on=True, **{other: not shown(form)[other]})
    assert done["type"] is FlowResultType.CREATE_ENTRY
    assert rig.entry.runtime_data is not running  # reloaded
    assert control_on(rig)
    assert ("setpoint", 0.0) not in rig.gateway.calls[before:]  # nothing held, nothing given back
    await rig.advance(60)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[before:]


async def test_the_tick_is_not_shown_without_control(hass: HomeAssistant) -> None:
    """An entry that only monitors: "Control mode" shows no tick."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    form = await mode_form(hass, entry.entry_id)
    assert "control_on" not in shown(form)
    hass.config_entries.options.async_abort(form["flow_id"])
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_only_an_administrator_reaches_the_tick(
    rig: Rig, hass_client_no_auth: Any, hass_read_only_access_token: str
) -> None:
    """Home Assistant opens the settings to an administrator only: a user without the rights
    cannot start them."""
    await started(rig)
    assert rig.entry is not None
    assert await async_setup_component(rig.hass, "config", {})
    client = await hass_client_no_auth()
    reply = await client.post(
        "/api/config/config_entries/options/flow",
        json={"handler": rig.entry.entry_id},
        headers={"Authorization": f"Bearer {hass_read_only_access_token}"},
    )
    assert reply.status == 401


# --- I11.2: the action for automations -----------------------------------------------------


async def set_control(rig: Rig, enabled: bool, user_id: str | None = None) -> None:
    """The action as an automation calls it (no user), or as a person does (``user_id``)."""
    from homeassistant.core import Context

    await rig.hass.services.async_call(
        "vtherm_smart_boiler",
        "set_control",
        {"enabled": enabled},
        blocking=True,
        context=Context(user_id=user_id),
    )


async def test_an_automation_switches_control_on_and_off(rig: Rig) -> None:
    await started(rig)
    await set_control(rig, True)
    assert control_on(rig)
    await rig.advance(60)
    assert ("setpoint", EXPECTED) in rig.gateway.calls
    await set_control(rig, False)
    assert rig.gateway.calls[-3:] == HAND_BACK
    assert not control_on(rig)


async def test_a_person_calling_the_action_is_sent_to_the_settings(
    rig: Rig, hass_admin_user: Any
) -> None:
    """The user's decision of 2026-11-22: control is switched in the settings — an
    administrator too is refused here, from a dashboard, a script or the developer tools."""
    from homeassistant.exceptions import ServiceValidationError

    await started(rig)
    with pytest.raises(ServiceValidationError) as raised:
        await set_control(rig, True, user_id=hass_admin_user.id)
    assert raised.value.translation_key == "control_in_settings"
    assert not control_on(rig)


async def test_the_action_refuses_on_as_the_settings_do(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from homeassistant.exceptions import ServiceValidationError

    await started(rig)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    monkeypatch.setattr(unit, "blockers", lambda _now: ("thermostat_kind_unknown",))
    with pytest.raises(ServiceValidationError) as raised:
        await set_control(rig, True)
    assert raised.value.translation_key == "blocked_thermostat_kind_unknown"
    assert raised.value.translation_placeholders == {"count": "0"}
    assert not control_on(rig)


async def test_the_action_says_when_the_boiler_did_not_take_the_hand_back(rig: Rig) -> None:
    from homeassistant.exceptions import HomeAssistantError

    await started(rig)
    await set_control(rig, True)
    await rig.advance(20)
    rig.gateway.connected = False
    rig.live()
    with pytest.raises(HomeAssistantError) as raised:
        await set_control(rig, False)
    assert raised.value.translation_key == "hand_back_failed"
    assert not control_on(rig)


async def test_the_action_goes_with_the_entry(hass: HomeAssistant) -> None:
    """Registered while the entry runs; without control it says so."""
    from homeassistant.core import Context
    from homeassistant.exceptions import ServiceValidationError

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(
            "vtherm_smart_boiler", "set_control", {"enabled": True}, blocking=True,
            context=Context(),
        )  # fmt: skip
    assert raised.value.translation_key == "control_not_running"
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service("vtherm_smart_boiler", "set_control")


def _gateway_configuration() -> dict[str, Any]:
    """J4's gateway configuration (devenv/config/configuration.yaml)."""
    from pathlib import Path

    import yaml

    path = Path(__file__).resolve().parents[2] / "devenv/config/configuration.yaml"
    return dict(yaml.safe_load(path.read_text(encoding="utf-8")))


async def test_the_j4_automation_switches_control(rig: Rig) -> None:
    """J4's I2 (the test session's review of 2026-11-22, point 7): the test configuration's
    automation "J4 set control" (devenv/config/configuration.yaml) switches control through the
    action — an automation's call, with no user — on and off with the safe hand-back."""
    config = _gateway_configuration()
    await started(rig)
    boolean = {"j4_set_control": config["input_boolean"]["j4_set_control"]}
    assert await async_setup_component(rig.hass, "input_boolean", {"input_boolean": boolean})
    assert await async_setup_component(rig.hass, "automation", {"automation": config["automation"]})
    await rig.hass.async_block_till_done()

    async def flip(service: str) -> None:
        await rig.hass.services.async_call(
            "input_boolean", service, {"entity_id": "input_boolean.j4_set_control"}, blocking=True
        )
        await rig.hass.async_block_till_done(wait_background_tasks=True)

    await flip("turn_on")
    assert control_on(rig)
    await rig.advance(60)
    assert ("setpoint", EXPECTED) in rig.gateway.calls
    await flip("turn_off")
    assert not control_on(rig)
    assert rig.gateway.calls[-3:] == HAND_BACK
