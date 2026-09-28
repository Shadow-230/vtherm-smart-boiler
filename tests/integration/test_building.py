"""Y3 through Home Assistant: the building model's measured values shown and resettable (P-90),
an entered design load always winning (P-92), the installation's warnings as repair issues
(P-94), and the control switch saying that control starts without a verdict (S-43).

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.daily import DaySummary
from custom_components.vtherm_smart_boiler.core.parameters import ParameterKey, Source
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import FakeBoiler, FakeZones
from .test_control import (  # the rig fixture comes with them
    SIGNALS,
    START,
    Rig,
    options,
    ran_before,
    rig,  # noqa: F401
)
from .test_setup import entity_id, entry_for, setup

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

DAY = 86400.0
HOUR = 3600.0
NOW = datetime(2026, 2, 1, tzinfo=UTC)
TRANSLATIONS = (
    Path(__file__).resolve().parents[2] / "custom_components/vtherm_smart_boiler/translations"
)
SOURCE_EN = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
SOURCE_PL = json.loads((TRANSLATIONS / "pl.json").read_text(encoding="utf-8"))


def house_days(
    first: float, loss: float, threshold: float, settings: str, count: int = 20
) -> dict[float, DaySummary]:
    """``count`` whole days of a house with ``loss`` (kW/K) and ``threshold`` (°C), at outdoor
    temperatures spread evenly over −5…+10 °C, from ``first`` on — as the plugin keeps them."""
    days: dict[float, DaySummary] = {}
    for index in range(count):
        outdoor = -5.0 + 15.0 * index / (count - 1)
        start = first + index * DAY
        days[start] = DaySummary(
            start, start + DAY, DAY, 10, 10, 0, HOUR, 10 * HOUR, 0.0, 0.0, None, None,
            outdoor_mean=outdoor, heat_kwh=24 * loss * (threshold - outdoor), settings=settings,
            outdoor_s=((round(outdoor), DAY),),
        )  # fmt: skip
    return days


def stored(entry: MockConfigEntry, **data: Any) -> dict[str, Any]:
    key = f"{DOMAIN}.{entry.entry_id}"
    return {"version": 1, "key": key, "data": {"monitoring_since": 0.0, **data}}


def measured(value: float, confidence: float, at: float) -> dict[str, float]:
    return {"value": value, "confidence": confidence, "at": at}


async def test_the_measured_threshold_is_shown(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """P-90: the heating threshold — the degree-days' base — has a sensor, hidden by default like
    the loss coefficient: the value in use with its source and confidence, and the measured one
    beside the entered one, with whether they disagree. A measured value without the confidence
    the plugin counts is shown, never used."""
    freezer.move_to(NOW)
    now = NOW.timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
        entry, measured={"heating_threshold": measured(17.5, 0.6, now - DAY)}
    )
    await setup(hass, entry)
    sensor = entity_id(hass, entry, "sensor", "heating_threshold")
    registered = er.async_get(hass).async_get(sensor)
    assert registered is not None
    assert registered.hidden_by is er.RegistryEntryHider.INTEGRATION
    state = hass.states.get(sensor)
    assert state is not None
    assert float(state.state) == 17.5
    assert state.attributes["source"] == "measured"
    assert state.attributes["confidence"] == 0.6
    assert (state.attributes["entered"], state.attributes["measured"]) == (None, 17.5)
    assert state.attributes["mismatch"] is False
    # The user enters 15 °C: it wins; the measured value is shown beside it, 2.5 K apart.
    parameters = {**entry.options["parameters"], "heating_threshold": 15.0}
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "parameters": parameters}
    )
    await hass.async_block_till_done()
    state = hass.states.get(sensor)
    assert state is not None
    assert float(state.state) == 15.0
    assert state.attributes["source"] == "entered"
    assert (state.attributes["entered"], state.attributes["measured"]) == (15.0, 17.5)
    assert state.attributes["mismatch"] is True


async def test_a_measured_threshold_without_confidence_is_shown_never_used(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """P-31: a threshold held at 0.3 (a standard error over 2 K) is shown beside the class
    default, which stays in use."""
    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
        entry, measured={"heating_threshold": measured(19.0, 0.3, NOW.timestamp() - DAY)}
    )
    await setup(hass, entry)
    state = hass.states.get(entity_id(hass, entry, "sensor", "heating_threshold"))
    assert state is not None
    assert float(state.state) == 15.0
    assert state.attributes["source"] == "default"
    assert (state.attributes["measured"], state.attributes["measured_confidence"]) == (19.0, 0.3)


async def press(hass: HomeAssistant, entry: MockConfigEntry, key: str) -> None:
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id(hass, entry, "button", key)}, blocking=True
    )
    await hass.async_block_till_done()


def measured_value(entry: MockConfigEntry, key: ParameterKey) -> float | None:
    estimate = entry.runtime_data.parameters.get(key).estimate(Source.MEASURED)
    return None if estimate is None else estimate.value


async def test_reset_buttons_forget_measured_values_and_refit_from_new_days_only(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """P-90, question 11: each button forgets only its own measured value — shown at once,
    stored at once — and it is fitted again from the days that start after the press only:
    the old days of the house as it was never bring it back. No option is saved, nothing is
    reloaded, and control, which never reads the building model, goes on without a hand-back."""
    hass = rig.hass
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(hass)
    ran_before(rig, entry)
    await setup(hass, entry)
    rig.entry = entry
    coordinator = entry.runtime_data
    now = START.timestamp()
    # Twenty days of the house before: 0.25 kW/K, heating up to 18 °C outside.
    coordinator.daily = house_days(now - 25 * DAY, 0.25, 18.0, coordinator.settings_key)
    await coordinator.async_run_analysis()
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.25)
    assert measured_value(entry, ParameterKey.HEATING_THRESHOLD) == pytest.approx(18.0)
    await rig.switch(True)
    await rig.advance(30)
    assert rig.state("sensor", "control_state").state == "heating"
    count = len(rig.gateway.calls)
    options_before = dict(entry.options)

    await press(hass, entry, "reset_heating_threshold")
    assert measured_value(entry, ParameterKey.HEATING_THRESHOLD) is None
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.25)
    reset_at = datetime.now(UTC).timestamp()
    assert coordinator.fit_since == {ParameterKey.HEATING_THRESHOLD: reset_at}
    saved = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert saved["fit_since"] == {"heating_threshold": reset_at}  # at once
    assert set(saved["measured"]) == {"loss_coefficient"}
    shown = rig.state("sensor", "heating_threshold")
    assert (float(shown.state), shown.attributes["measured"]) == (15.0, None)  # at once
    await hass.async_block_till_done(wait_background_tasks=True)  # the analysis it starts
    await coordinator.async_run_analysis()
    # The old days fit the loss as before, but never the threshold again.
    assert measured_value(entry, ParameterKey.HEATING_THRESHOLD) is None
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.25)

    await press(hass, entry, "reset_loss_coefficient")
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) is None
    assert set(coordinator.fit_since) == {
        ParameterKey.HEATING_THRESHOLD,
        ParameterKey.LOSS_COEFFICIENT,
    }
    assert rig.state("sensor", "loss_coefficient").attributes.get("measured") is None
    # Neither reset touched the options or control: no reload, no hand-back.
    assert entry.runtime_data is coordinator
    assert dict(entry.options) == options_before
    await rig.advance(30)
    assert 0.0 not in rig.gateway.setpoints()[count:]
    assert rig.state("sensor", "control_state").state == "heating"
    assert rig.state("switch", "control").state == "on"

    # Twenty days after the resets, of the house insulated since: 0.2 kW/K up to 16 °C.
    await rig.switch(False)
    rig.freezer.move_to(START + timedelta(days=22))
    coordinator.daily |= house_days(reset_at + HOUR, 0.2, 16.0, coordinator.settings_key)
    await coordinator.async_run_analysis()
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.2)
    assert measured_value(entry, ParameterKey.HEATING_THRESHOLD) == pytest.approx(16.0)


async def test_a_reset_while_an_analysis_runs_is_not_undone(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-90: an analysis that started before the press finishes after it: its fit, from the old
    days, is not written over the reset."""
    import asyncio

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    coordinator.daily = house_days(NOW.timestamp() - 25 * DAY, 0.25, 18.0, coordinator.settings_key)
    started, release = asyncio.Event(), asyncio.Event()
    analyse = coordinator_module.analyse

    def slow(*args: Any) -> Any:
        result = analyse(*args)
        hass.loop.call_soon_threadsafe(started.set)
        asyncio.run_coroutine_threadsafe(release.wait(), hass.loop).result()
        return result

    monkeypatch.setattr(coordinator_module, "analyse", slow)
    running = hass.async_create_task(coordinator.async_run_analysis())
    await started.wait()
    await coordinator.async_reset_measured(ParameterKey.HEATING_THRESHOLD)
    release.set()
    await running
    assert measured_value(entry, ParameterKey.HEATING_THRESHOLD) is None
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.25)


async def test_the_reset_buttons_exist_without_control(hass: HomeAssistant, freezer) -> None:
    """The building model feeds the monitor: its reset buttons exist for a monitor-only entry,
    in the configuration category; the comfort correction's does not."""
    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    registry = er.async_get(hass)
    for key in ("reset_heating_threshold", "reset_loss_coefficient"):
        found = registry.async_get(entity_id(hass, entry, "button", key))
        assert found is not None
        assert found.entity_category is not None
        assert found.entity_category.value == "config"
    missing = registry.async_get_entity_id(
        "button", DOMAIN, f"{entry.entry_id}_reset_comfort_correction"
    )
    assert missing is None
    # A press with nothing measured changes nothing but the moment fitting starts from.
    await press(hass, entry, "reset_loss_coefficient")
    assert set(entry.runtime_data.fit_since) == {ParameterKey.LOSS_COEFFICIENT}


async def test_an_unreadable_stored_reset_counts_from_the_start(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """The negative: a stored reset whose moment cannot be read — not a number, none, one in
    the future — counts from this start, so the days the user set aside are never fitted
    again; one of a value that cannot be reset is ignored."""
    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    entry.add_to_hass(hass)
    now = NOW.timestamp()
    for broken in ("yesterday", None, now + DAY):
        hass_storage[f"{DOMAIN}.{entry.entry_id}"] = stored(
            entry,
            fit_since={
                "heating_threshold": broken,
                "loss_coefficient": now - DAY,
                "boiler_min_power": now - DAY,
                "unknown": now - DAY,
            },
        )
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert entry.runtime_data.fit_since == {
            ParameterKey.HEATING_THRESHOLD: now,
            ParameterKey.LOSS_COEFFICIENT: now - DAY,
        }, broken
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()


async def test_an_entered_design_load_always_wins(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """P-92 (question 12): the user's design load gives the heat loss, and recorded days that
    measure another one never replace it — they show a mismatch; the texts say so."""
    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    # 7 kW at −15 °C with 20 °C inside: 0.2 kW/K entered.
    entry = entry_for(boiler, building={"design_load_kw": 7.0})
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    coordinator.daily = house_days(NOW.timestamp() - 25 * DAY, 0.35, 16.0, coordinator.settings_key)
    await coordinator.async_run_analysis()
    assert measured_value(entry, ParameterKey.LOSS_COEFFICIENT) == pytest.approx(0.35)
    state = hass.states.get(entity_id(hass, entry, "sensor", "loss_coefficient"))
    assert state is not None
    assert float(state.state) == 0.2  # the entry, not the measurement
    assert state.attributes["source"] == "entered"
    assert (state.attributes["entered"], state.attributes["measured"]) == (0.2, 0.35)
    assert state.attributes["mismatch"] is True
    for source in (SOURCE_EN, SOURCE_PL):
        for flow in ("config", "options"):
            texts = source[flow]["step"]["building"]
            assert texts["description"]
            assert texts["data_description"]["design_load_kw"]
    building = SOURCE_EN["config"]["step"]["building"]
    assert "data never replace it" in building["description"]
    assert "never replace it" in building["data_description"]["design_load_kw"]


async def test_installation_warnings_raise_an_issue(
    hass: HomeAssistant, zones: FakeZones, freezer
) -> None:
    """P-94: a circuit without zones and underfloor heating on an unmixed circuit without a
    maximum each raise a warning repair issue naming the circuits; fixed in the options, they
    go; the entry's removal takes them."""
    freezer.move_to(NOW)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    floor = zones.add("floor")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": {s.value: boiler.entity(s) for s in boiler.signals},
            "circuits": [{"id": "ground"}, {"id": "upstairs"}],
            "zones": [{"entity_id": floor, "circuit": "ground", "emitter": "underfloor"}],
        },
    )
    await setup(hass, entry)
    registry = ir.async_get(hass)
    empty = registry.async_get_issue(DOMAIN, f"installation_empty_circuit_{entry.entry_id}")
    assert empty is not None
    assert empty.severity is ir.IssueSeverity.WARNING
    assert empty.translation_key == "installation_empty_circuit"
    assert empty.translation_placeholders == {"circuits": "upstairs"}
    underfloor = registry.async_get_issue(
        DOMAIN, f"installation_underfloor_without_max_flow_{entry.entry_id}"
    )
    assert underfloor is not None
    assert underfloor.severity is ir.IssueSeverity.WARNING
    assert underfloor.translation_placeholders == {"circuits": "ground"}
    # Fixed: the floor's maximum entered, the empty circuit gone — both issues go.
    fixed = {
        **entry.options,
        "circuits": [{"id": "ground", "max_flow": 40.0}],
    }
    hass.config_entries.async_update_entry(entry, options=fixed)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"installation_empty_circuit_{entry.entry_id}") is None
    assert (
        registry.async_get_issue(
            DOMAIN, f"installation_underfloor_without_max_flow_{entry.entry_id}"
        )
        is None
    )
    # A circuit added without zones, then the entry removed: its issue goes with it.
    two = {**fixed, "circuits": [{"id": "ground", "max_flow": 40.0}, {"id": "attic"}]}
    hass.config_entries.async_update_entry(entry, options=two)
    await hass.async_block_till_done()
    again = registry.async_get_issue(DOMAIN, f"installation_empty_circuit_{entry.entry_id}")
    assert again is not None
    assert again.translation_placeholders == {"circuits": "attic"}
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get_issue(DOMAIN, f"installation_empty_circuit_{entry.entry_id}") is None


async def test_the_switch_says_control_starts_without_a_verdict(rig: Rig) -> None:
    """S-43 (answer K): the monitoring period counts calendar days from the entry's creation.
    Once they have passed, control may start without a verdict — off-season there may be too
    little data for one — and the switch shows the verdict, "not enough data", whose text says
    so. Before they have passed, switching on is refused."""
    from homeassistant.exceptions import ServiceValidationError

    hass = rig.hass
    monitored = options(rig.zones) | {"monitor": {"monitoring_days": 7}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=monitored)
    entry.created_at = START - timedelta(days=8)  # the period has passed
    entry.add_to_hass(hass)
    ran_before(rig, entry)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    rig.entry = entry
    switch = rig.state("switch", "control")
    assert switch.attributes["verdict"] == "not_enough_data"
    assert "monitoring_period" not in switch.attributes["blockers"]
    await rig.switch(True)
    await rig.advance(30)
    assert rig.state("switch", "control").state == "on"
    assert rig.state("sensor", "control_state").state == "heating"  # without a verdict
    for source in (SOURCE_EN, SOURCE_PL):
        states = source["entity"]["switch"]["control"]["state_attributes"]["verdict"]["state"]
        assert set(states) == {"worth_it", "not_worth_it", "not_enough_data"}
    assert (
        "without a verdict"
        in (
            SOURCE_EN["entity"]["switch"]["control"]["state_attributes"]["verdict"]["state"][
                "not_enough_data"
            ]
        )
    )
    control_step = SOURCE_EN["options"]["step"]["control"]["description"]
    assert "counted in days from when this integration was added" in control_step
    assert "even without a verdict" in control_step
    # A second entry created three days ago: still in its monitoring period.
    young = MockConfigEntry(domain=DOMAIN, title="Young", data={}, options=monitored)
    young.created_at = START - timedelta(days=3)
    young.add_to_hass(hass)
    ran_before(rig, young)
    await setup(hass, young)
    switch_id = er.async_get(hass).async_get_entity_id(
        "switch", DOMAIN, f"{young.entry_id}_control"
    )
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call("switch", "turn_on", {"entity_id": switch_id}, blocking=True)
    assert err.value.translation_key == "blocked_monitoring_period"


async def test_without_a_flame_signal_the_verdict_names_it(rig: Rig) -> None:
    """S-43: an entry without a flame signal gets no verdict — "not enough data" with the
    reason ``no_burner_signal``, on the verdict sensor and on the switch."""
    hass = rig.hass
    no_flame = options(rig.zones)
    no_flame["signals"] = {s.value: rig.boiler.entity(s) for s in SIGNALS if s is not Signal.FLAME}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=no_flame)
    entry.add_to_hass(hass)
    ran_before(rig, entry)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    rig.entry = entry
    verdict = rig.state("sensor", "verdict")
    assert verdict.state == "not_enough_data"
    assert [r["code"] for r in verdict.attributes["reasons"]] == ["no_burner_signal"]
    assert rig.state("switch", "control").attributes["verdict"] == "not_enough_data"
