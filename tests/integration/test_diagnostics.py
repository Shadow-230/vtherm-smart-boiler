"""Diagnostics download: complete enough to help, and without entity IDs."""

from __future__ import annotations

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.diagnostics import async_get_config_entry_diagnostics

from .harness import WEATHER_ENTITY, FakeBoiler, FakeForecasts, FakeZones, analyse_now

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")


async def test_diagnostics_are_redacted(
    hass: HomeAssistant, zones: FakeZones, forecasts: FakeForecasts
) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.PRESSURE))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0, Signal.PRESSURE: 1.5})
    living = zones.add("living", hvac_action="heating", valve_open_percent=40)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping(),
            "weather": WEATHER_ENTITY,
            "zones": [{"entity_id": living}],
            "parameters": {"boiler_min_power": 4.0},
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)  # the first analysis
    await analyse_now(entry.runtime_data)
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    for entity in (*boiler.mapping().values(), living, WEATHER_ENTITY):
        assert entity not in text
    assert result["options"]["signals"]["flame"].startswith("entity_")
    assert result["signals"]["flow"]["status"] == "ok"
    assert result["parameters"]["boiler_min_power"]["effective"] == 4.0
    assert result["capabilities"]["vtherm_api_version"] == "0.5.0"
    assert result["analysis"]["verdict"] == "not_enough_data"
    assert len(result["zones"]) == 1
    assert result["forecasts"]["snapshots"] >= 1


async def test_diagnostics_before_the_first_analysis_leave_its_summary_out(
    hass: HomeAssistant, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While the first analysis has not run — the recorder still being read — the diagnostics
    give no analysis summary rather than an empty or invented one; once it has run, its summary
    is there. (Before Z1 this was reached only when a test's timing happened to allow it.)"""
    import asyncio

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    release = asyncio.Event()

    async def slow_backfill(self: Any, now: float) -> None:
        await release.wait()

    monkeypatch.setattr(coordinator_module.SmartBoilerCoordinator, "_async_backfill", slow_backfill)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=40)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={"signals": boiler.mapping(), "zones": [{"entity_id": living}]},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.runtime_data.analysis is None
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["analysis"] is None
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["analysis"]["verdict"] == "not_enough_data"


async def test_the_control_section_keeps_what_is_not_personal(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P69: service names and versions are not personal and stay readable; entity IDs and the
    gateway's identifiers do not."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=40)
    hass.states.async_set("sensor.gw_control_setpoint", "40", {"unit_of_measurement": "°C"})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping(),
            "boiler": {"class": "flow_setpoint", "dhw": "combi"},
            "zones": [{"entity_id": living}],
            "monitor": {"monitoring_days": 0},
            "control": {
                "write_path": "opentherm_gw",
                "gateway_id": "gw-in-the-cellar",
                "confirmed_entity": "sensor.gw_control_setpoint",
                "topology": "gateway_with_thermostat",
                "curve": {"design_outdoor": -15, "design_flow": 55},
            },
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    control = result["control"]
    assert control["enabled"] is False
    assert "opentherm_gw.set_control_setpoint" in control["allowed_services"]
    assert control["status"]["configured"] is True
    assert "controlling" in control["stored"]
    assert "gw-in-the-cellar" not in text
    assert "sensor.gw_control_setpoint" not in text
    assert living not in text


async def test_diagnostics_redact_an_entity_that_is_away(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """T-50 (P-30): the options name ``sensor.gone`` — in no state and not in the registry. The
    entry's options are a read-only mapping, not a dict: the entity named there is redacted
    all the same, wherever it appears."""
    from types import MappingProxyType

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 40.0})
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": boiler.mapping() | {"pressure": "sensor.gone"},
            "zones": [{"entity_id": zones.add("living")}],
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert isinstance(entry.options, MappingProxyType)
    assert hass.states.get("sensor.gone") is None
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    assert "sensor.gone" not in text
    assert result["options"]["signals"]["pressure"].startswith("entity_")


async def test_diagnostics_work_for_an_entry_in_setup_error(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """Review question 20: an entry whose setup failed has no runtime data — its diagnostics
    give the redacted options, the entry's state, and the control state read from its store,
    redacted too (an owed hand-back is what the user most needs to see)."""
    from homeassistant.config_entries import ConfigEntryState

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        options={
            "signals": {"flame": "binary_sensor.boiler_flame"},
            "boiler": {"class": "no such class"},  # cannot be read: the setup fails
        },
    )
    entry.add_to_hass(hass)
    key = f"{DOMAIN}.{entry.entry_id}.control"
    stored = {
        "controlling": True,
        "hand_back_pending": True,
        "taken_with": {"setpoint_entity": "number.boiler_setpoint_gone"},
        "resuming": {"climate.room_gone": 1000.0},  # a zone keyed by its ID
    }
    hass_storage[key] = {"version": 1, "key": key, "data": stored}
    assert not await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert not hasattr(entry, "runtime_data")
    result = await async_get_config_entry_diagnostics(hass, entry)
    text = json.dumps(result)
    assert result["state"] == "setup_error"
    assert result["options"]["boiler"] == {"class": "no such class"}
    assert result["options"]["signals"]["flame"].startswith("entity_")
    assert result["control_state"]["controlling"] is True
    assert result["control_state"]["hand_back_pending"] is True
    assert "binary_sensor.boiler_flame" not in text
    assert "number.boiler_setpoint_gone" not in text
    assert "climate.room_gone" not in text


async def test_diagnostics_of_an_entry_never_set_up_read_nothing_owed(
    hass: HomeAssistant,
) -> None:
    """Negative: without runtime data and without any store, the diagnostics still answer —
    nothing stored, nothing owed."""
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", options={"signals": {}})
    entry.add_to_hass(hass)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["state"] == "not_loaded"
    assert result["control_state"] == {}
    assert result["control_readable"] is False


async def test_diagnostics_answer_when_the_stored_control_state_cannot_be_read(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Question 20, negative: reading the store fails — the diagnostics still answer, with the
    redacted options and the entry's state, and say the control state could not be read."""
    from custom_components.vtherm_smart_boiler import diagnostics

    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", options={"signals": {"flame": "binary_sensor.flame"}}
    )
    entry.add_to_hass(hass)

    async def broken(*_args: object, **_kwargs: object) -> None:
        raise OSError("the disk failed")

    monkeypatch.setattr(diagnostics, "async_read_control_state", broken)
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["control_state"] == {}
    assert result["control_readable"] is False
    assert result["state"] == "not_loaded"
    assert "binary_sensor.flame" not in json.dumps(result)


async def test_diagnostics_say_when_no_feature_manager_was_registered(hass: HomeAssistant) -> None:
    from custom_components.vtherm_smart_boiler.diagnostics import _feature_manager

    assert _feature_manager(hass) == {"state": None}
