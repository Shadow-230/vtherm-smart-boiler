"""Setup, unload and reload; missing and stale data; replayed history through the entities."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, radiator_zones
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal
from sim.simulator import DAY, Scenario, daily_cycle, simulate

from .harness import (
    WEATHER_ENTITY,
    FakeBoiler,
    FakeForecasts,
    FakeZones,
    analyse_now,
    analysis_idle,
    apply_event,
    replay_events,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

MAIN = (
    Signal.FLAME,
    Signal.FLOW,
    Signal.RETURN,
    Signal.MODULATION,
    Signal.DHW_ACTIVE,
    Signal.PRESSURE,
)


def entry_for(boiler: FakeBoiler, zones: FakeZones | None = None, **extra) -> MockConfigEntry:
    options = {
        "signals": {s.value: boiler.entity(s) for s in boiler.signals},
        "parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0},
        "zones": [{"entity_id": e} for e in (zones.entities.values() if zones else [])],
    } | extra
    return MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)


async def setup(hass: HomeAssistant, entry: MockConfigEntry, *, background: bool = True) -> None:
    """Set the entry up and, by default, let the recorder read and the first analysis that
    setup starts in the background finish: an analysis the test asks for while that one runs
    would be skipped — only one runs at a time — and the test would depend on the machine's
    speed (Z1). ``background=False``: a test that holds that work on purpose."""
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=background)


def entity_id(
    hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str, zone: str | None = None
) -> str:
    """One of the plugin's entities; a zone's are keyed on the thermostat's registry entry."""
    registry = er.async_get(hass)
    if zone is not None:
        zone_entry = registry.async_get(zone)
        assert zone_entry is not None, zone
        key = f"{key}_{zone_entry.id}"
    found = registry.async_get_entity_id(domain, DOMAIN, f"{entry.entry_id}_{key}")
    assert found is not None, key
    return found


async def test_setup_creates_entities_and_reads_signals(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    boiler = FakeBoiler(hass, MAIN)
    boiler.set_many(
        {
            Signal.FLAME: True,
            Signal.FLOW: 45.0,
            Signal.RETURN: 38.0,
            Signal.MODULATION: 30.0,
            Signal.DHW_ACTIVE: False,
            Signal.PRESSURE: 1.5,
        }
    )
    living = zones.add(
        "living",
        current_temperature=20.0,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=70,
        on_percent=0.7,
    )
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED

    connection = hass.states.get(entity_id(hass, entry, "binary_sensor", "connection"))
    assert connection is not None
    assert connection.state == "on"
    hot = hass.states.get(entity_id(hass, entry, "binary_sensor", "hot_water", living))
    assert hot is not None
    assert hot.state == "on"
    # A power user's diagnostic: registered, hidden until enabled (P104).
    factor_id = entity_id(hass, entry, "sensor", "emitter_power_factor", living)
    registry = er.async_get(hass)
    assert registry.async_get(factor_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
    registry.async_update_entity(factor_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    factor = hass.states.get(factor_id)
    assert factor is not None
    assert float(factor.state) > 0
    reference = hass.states.get(entity_id(hass, entry, "sensor", "reference_room_temperature"))
    assert reference is not None
    assert float(reference.state) == 20.0
    critical = hass.states.get(entity_id(hass, entry, "sensor", "critical_zone_main"))
    assert critical is not None
    assert critical.attributes["zone"] == living
    high = hass.states.get(entity_id(hass, entry, "binary_sensor", "alarm_pressure_high"))
    assert high is not None
    assert high.state == "off"
    # Y1: no "add water" threshold by default — no low-pressure alarm at all.
    unique = {
        e.unique_id for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    }
    assert f"{entry.entry_id}_alarm_pressure_low" not in unique
    # no return mapped would mean no condensing sensor; here it exists
    entity_id(hass, entry, "sensor", "condensing_share")


async def test_feature_entities_follow_the_mapping(hass: HomeAssistant) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    registry = er.async_get(hass)
    unique = {
        e.unique_id for e in registry.entities.values() if e.config_entry_id == entry.entry_id
    }
    assert f"{entry.entry_id}_condensing_share" not in unique
    assert f"{entry.entry_id}_alarm_pressure_low" not in unique
    assert f"{entry.entry_id}_verdict" in unique


async def test_unload_and_reload(hass: HomeAssistant) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data is not coordinator
    assert coordinator._unsubs == []  # the old instance left nothing running
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED
    boiler.set(Signal.FLOW, 40.0)  # no listener left to react
    await hass.async_block_till_done()


async def test_an_unload_leaves_no_listener_on_the_bus(
    hass: HomeAssistant, freezer, zones: FakeZones
) -> None:
    """P-123: after a setup, a reload and an unload, Home Assistant's bus holds exactly the
    listeners it held before the setup — per event type, none left behind by the plugin (its
    state trackers, its start and stop hooks, its entities'). The platforms' own components are
    set up first: Home Assistant keeps their listeners for good, whoever loaded them. A store's
    save still pending at the unload — the plugin's, or Home Assistant's own for its entries
    and entities — holds Home Assistant's final-write hook until it is written: the clock is
    moved past every such delay first."""
    from homeassistant.setup import async_setup_component
    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler import PLATFORMS

    async def saves_written() -> None:
        for _ in range(2):  # the delayed saves, then what their writing leaves
            freezer.tick(timedelta(hours=1))
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()

    for platform in PLATFORMS:
        assert await async_setup_component(hass, platform, {})
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    zones.add("living", hvac_action="heating", valve_open_percent=60)
    await saves_written()
    before = dict(hass.bus.async_listeners())
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    assert dict(hass.bus.async_listeners()) != before  # the plugin listens while it runs
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    await saves_written()
    assert dict(hass.bus.async_listeners()) == before


async def test_a_second_entry_beside_a_running_one_fails_the_test(hass: HomeAssistant) -> None:
    """P-125, T11: the tests' guard (``tests/integration/conftest.py``) stops a test that sets
    up a second entry of this single-entry integration beside one that runs; once the first is
    unloaded, the second sets up."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    first = entry_for(boiler)
    await setup(hass, first)
    second = entry_for(boiler)
    second.add_to_hass(hass)
    with pytest.raises(AssertionError, match="single-entry"):
        await hass.config_entries.async_setup(second.entry_id)
    assert await hass.config_entries.async_unload(first.entry_id)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert second.state is ConfigEntryState.LOADED


async def test_only_an_options_change_reloads_the_entry(hass: HomeAssistant) -> None:
    """P73: a reload hands control back and starts a new session — a new title or preference
    must not cause one."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    hass.config_entries.async_update_entry(entry, title="Boiler in the cellar")
    await hass.async_block_till_done()
    assert entry.runtime_data is coordinator
    # H7: the level of detail changes only what the options show.
    hass.config_entries.async_update_entry(entry, options={**entry.options, "level": "advanced"})
    await hass.async_block_till_done()
    assert entry.runtime_data is coordinator
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "weather": "weather.home"}
    )
    await hass.async_block_till_done()
    assert entry.runtime_data is not coordinator


def test_changing_attributes_stay_out_of_the_recorder() -> None:
    """P33: attributes that change with every update would fill the database."""
    from custom_components.vtherm_smart_boiler.binary_sensor import (
        AlarmSensor,
        HotWaterSensor,
        OutdoorSensorProblem,
    )
    from custom_components.vtherm_smart_boiler.sensor import (
        BoilerSensor,
        ControlSetpointSensor,
        ControlStateSensor,
        CriticalZoneSensor,
        EmitterFactorSensor,
    )

    for cls, changing in (
        (
            ControlStateSensor,
            {
                "reasons",
                "target",
                "heating_on",
                "unknown_zones",
                "comfort_correction",
                "activation_at",
            },
        ),
        (ControlSetpointSensor, {"requested", "read_back", "last_change"}),
        (EmitterFactorSensor, {"computed_at", "output_w"}),
        (CriticalZoneSensor, {"demand", "deficit"}),
        (BoilerSensor, {"reasons", "temperature", "deficit", "contributions"}),
        (OutdoorSensorProblem, {"mean_difference"}),
    ):
        assert changing <= cls._unrecorded_attributes, cls.__name__
    # P-72: the continuous values are no attributes at all any more; the diagnostics keep them.
    for cls in (HotWaterSensor, AlarmSensor):
        assert not cls._unrecorded_attributes & {"excess", "value"}, cls.__name__


async def test_a_new_emitter_factor_is_saved_slowly_a_latch_soon(hass: HomeAssistant) -> None:
    """P33: a factor recomputed at every update while a zone heats must not rewrite the store
    every two minutes; what control needs kept is not held back by it."""
    from custom_components.vtherm_smart_boiler.coordinator import (
        FACTOR_SAVE_DELAY_S,
        SAVE_DELAY_S,
    )

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    delays: list[float] = []
    coordinator._store.async_delay_save = lambda _data, delay: delays.append(delay)
    coordinator._save_due = None
    coordinator.schedule_save(FACTOR_SAVE_DELAY_S)
    coordinator.schedule_save(FACTOR_SAVE_DELAY_S)  # one pending already
    coordinator.schedule_save()  # sooner: brought forward
    coordinator.schedule_save(FACTOR_SAVE_DELAY_S)  # later than the pending one: nothing
    assert delays == [FACTOR_SAVE_DELAY_S, SAVE_DELAY_S]


async def test_the_recorder_backfill_runs_after_setup_and_goes_before_live_samples(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P34, P109: eight days of history are read after setup, in the background, with named
    arguments, and turned into samples off the event loop; they go before the samples recorded
    live meanwhile."""
    import asyncio

    from homeassistant.core import State
    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    now = dt_util.utcnow()
    release = asyncio.Event()
    asked: list[dict] = []

    def significant_states(hass, start_time, *, end_time=None, entity_ids=None, filters=None,
                           include_start_time_state=True, significant_changes_only=True,
                           minimal_response=False, no_attributes=False):  # fmt: skip
        asked.append({"entity_ids": entity_ids, "significant": significant_changes_only})
        flow = boiler.entity(Signal.FLOW)
        unit = {"unit_of_measurement": "°C"}
        return {
            flow: [
                State(flow, "30.0", unit, last_updated=now - timedelta(days=2)),
                State(flow, "40.0", unit, last_updated=now - timedelta(days=1)),
            ]
        }

    class Recorder:
        async def async_add_executor_job(self, target, *args):
            await release.wait()
            return await hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    hass.config.components.add("recorder")
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    entry = entry_for(boiler)
    await setup(hass, entry, background=False)  # does not wait for the recorder
    assert entry.state is ConfigEntryState.LOADED
    history = entry.runtime_data.history.signals[Signal.FLOW]
    assert [s.value for s in history] == [45.0]
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [s.value for s in history] == [30.0, 40.0, 45.0]
    watched = list(entry.runtime_data.config.watched_entities)
    # The rolling history first; then older days, as far as the recorder reaches (no flame
    # there: it stops at once).
    assert asked[0] == {"entity_ids": watched, "significant": False}
    assert len(asked) == 2


async def test_the_backfill_puts_a_zones_recorded_states_before_its_live_ones(
    hass: HomeAssistant, freezer, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-117: a VT zone's recorded states, read back with their attributes, go before the
    zone's states recorded live since setup — series by series, only what is older, as the
    boiler's signals do. Negative: a zone the recorder has nothing for keeps its live states
    alone."""
    import asyncio

    from homeassistant.core import State
    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    now = dt_util.utcnow()
    release = asyncio.Event()
    living = zones.add(
        "living",
        current_temperature=20.5,
        temperature=21.0,
        hvac_action="heating",
        valve_open_percent=70,
    )
    bedroom = zones.add("bedroom", current_temperature=19.0, valve_open_percent=10)

    def recorded(temperature: float, action: str, opening: int, days: int) -> State:
        attributes = {
            "current_temperature": temperature,
            "temperature": 21.0,
            "hvac_action": action,
            "valve_open_percent": opening,
            "is_ready": True,
            "specific_states": {},
        }
        return State(living, "heat", attributes, last_updated=now - timedelta(days=days))

    def significant_states(hass, start_time, **kwargs):
        return {living: [recorded(18.0, "heating", 40, 2), recorded(19.0, "idle", 0, 1)]}

    class Recorder:
        async def async_add_executor_job(self, target, *args):
            await release.wait()
            return await hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    hass.config.components.add("recorder")
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    entry = entry_for(boiler, zones)
    await setup(hass, entry, background=False)  # does not wait for the recorder
    zone = entry.runtime_data.history.zones[living]
    assert [s.value for s in zone.temperature] == [20.5]
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert [s.value for s in zone.temperature] == [18.0, 19.0, 20.5]
    assert [s.value for s in zone.valve_open] == [0.4, 0.0, 0.7]
    assert [s.value for s in zone.calling] == [True, False, True]
    assert [s.value for s in zone.target] == [21.0]  # unchanged throughout: one sample
    assert zone.temperature.first_time == (now - timedelta(days=2)).timestamp()
    other = entry.runtime_data.history.zones[bedroom]
    assert [s.value for s in other.temperature] == [19.0]


async def test_no_day_is_kept_before_the_history_is_back(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """H8: an analysis that runs while a slow recorder is still being read sees only the hours
    since setup; a day it summarised then would be kept, a few hours of it, for a year."""
    import asyncio

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    release = asyncio.Event()

    async def slow_backfill(self: Any, now: float) -> None:
        await release.wait()

    monkeypatch.setattr(coordinator_module.SmartBoilerCoordinator, "_async_backfill", slow_backfill)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry, background=False)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(days=1))  # a whole day since setup: a day to summarise
    boiler.set(Signal.FLAME, True)
    await hass.async_block_till_done()
    await analyse_now(coordinator)
    assert coordinator.analysis is not None
    assert coordinator.daily == {}  # nothing kept while the history is not back
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    await analyse_now(coordinator)
    assert coordinator.daily  # kept once it is


async def test_a_slow_analysis_does_not_set_the_quick_path_back(
    hass: HomeAssistant, freezer, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The analysis runs for a while in the executor; what it publishes is computed when it
    ends, not when it began — else a flow gone stale meanwhile would read as fresh again."""
    import threading

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=50)
    entry = entry_for(boiler, zones, freshness={"flow": 1800.0})
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    hot_id = entity_id(hass, entry, "binary_sensor", "hot_water", living)
    release = threading.Event()
    real = coordinator_module.analyse

    def slow(*args):
        release.wait(10)
        return real(*args)

    monkeypatch.setattr(coordinator_module, "analyse", slow)
    task = hass.async_create_task(coordinator.async_run_analysis())
    await asyncio.sleep(0)
    freezer.tick(timedelta(hours=1))
    zones.set("living", hvac_action="heating", valve_open_percent=50)
    await coordinator.async_refresh()
    assert hass.states.get(hot_id).state == "unknown"  # the flow is stale now
    release.set()
    await task
    await hass.async_block_till_done()
    assert hass.states.get(hot_id).state == "unknown"


async def test_entities_the_options_no_longer_create_are_removed(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P39: a zone taken out of the options takes its entities with it; an entity the user
    disabled stays disabled, not removed."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    bedroom = zones.add("bedroom")
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    registry = er.async_get(hass)
    gone = entity_id(hass, entry, "binary_sensor", "hot_water", bedroom)
    disabled = entity_id(hass, entry, "sensor", "emitter_power_factor", living)
    registry.async_update_entity(disabled, disabled_by=er.RegistryEntryDisabler.USER)
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "zones": [{"entity_id": living}]}
    )
    await hass.async_block_till_done()
    assert registry.async_get(gone) is None
    assert registry.async_get(disabled) is not None


async def test_zone_entities_keep_their_identity_when_the_thermostat_is_renamed(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P39: keyed on the thermostat's registry entry, not its entity ID."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    before = entity_id(hass, entry, "binary_sensor", "hot_water", living)
    registry = er.async_get(hass)
    registry.async_update_entity(living, new_entity_id="climate.lounge")
    hass.states.async_set("climate.lounge", "heat", {"current_temperature": 20.0})
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "zones": [{"entity_id": "climate.lounge"}]}
    )
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "binary_sensor", "hot_water", "climate.lounge") == before


def count_setups(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every setup of the plugin's entry from now on: a reload is one more."""
    import custom_components.vtherm_smart_boiler as plugin

    setups: list[str] = []
    real = plugin.async_setup_entry

    async def counted(hass: HomeAssistant, entry: Any) -> bool:
        setups.append(entry.entry_id)
        return await real(hass, entry)

    monkeypatch.setattr(plugin, "async_setup_entry", counted)
    return setups


async def test_a_renamed_entity_is_followed(
    hass: HomeAssistant, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-19 (follow, provisional, K4): a VT climate and a boiler signal renamed in Home
    Assistant at once — as renaming their device does: the options hold the new entity IDs
    after one reload, as any options save; the zone's entities keep their identity; and the new
    IDs are followed from then on."""
    registry = er.async_get(hass)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    flow = registry.async_get_or_create(
        "sensor", "fake_boiler", "flow", suggested_object_id="fake_boiler_flow"
    )
    assert flow.entity_id == boiler.entity(Signal.FLOW)
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    entry = entry_for(boiler, zones, reference_room={"strategy": "chosen_zone", "zone": living})
    await setup(hass, entry)
    before = entity_id(hass, entry, "binary_sensor", "hot_water", living)
    setups = count_setups(monkeypatch)
    registry.async_update_entity(living, new_entity_id="climate.lounge")
    registry.async_update_entity(flow.entity_id, new_entity_id="sensor.boiler_flow")
    await hass.async_block_till_done()
    assert entry.options["zones"] == [{"entity_id": "climate.lounge"}]
    assert entry.options["signals"]["flow"] == "sensor.boiler_flow"
    assert entry.options["reference_room"]["zone"] == "climate.lounge"
    assert setups == [entry.entry_id]  # one reload
    assert entry.state is ConfigEntryState.LOADED
    assert entity_id(hass, entry, "binary_sensor", "hot_water", "climate.lounge") == before
    registry.async_update_entity("climate.lounge", new_entity_id="climate.salon")
    await hass.async_block_till_done()
    assert entry.options["zones"] == [{"entity_id": "climate.salon"}]
    assert len(setups) == 2


@pytest.mark.parametrize("change", ["rename", "remove"])
async def test_a_registry_change_during_setup_is_followed(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    """PB-55: the registry follower is registered last, so a rename or removal reaching Home
    Assistant while the entry was set up was never followed nor reported — the options kept an
    ID no longer in the registry. Found at the end of setup now: a rename followed (one more
    setup), a removal reported. Negative: a named entity outside the registry (the fire
    signal's plain state) changes nothing."""
    from homeassistant.helpers import issue_registry as ir

    import custom_components.vtherm_smart_boiler as plugin

    registry = er.async_get(hass)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    flow = registry.async_get_or_create(
        "sensor", "fake_boiler", "flow", suggested_object_id="fake_boiler_flow"
    )
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    real = plugin._async_migrate_zone_unique_ids
    done: list[bool] = []

    async def meanwhile(*args: Any) -> None:
        if not done:  # the first setup only
            done.append(True)
            if change == "rename":
                registry.async_update_entity(flow.entity_id, new_entity_id="sensor.boiler_flow")
            else:
                registry.async_remove(flow.entity_id)
        await real(*args)

    monkeypatch.setattr(plugin, "_async_migrate_zone_unique_ids", meanwhile)
    setups = count_setups(monkeypatch)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.state is ConfigEntryState.LOADED
    removed = ir.async_get(hass).async_get_issue(
        DOMAIN, f"entity_removed_{entry.entry_id}_{flow.entity_id}"
    )
    if change == "rename":
        assert entry.options["signals"]["flow"] == "sensor.boiler_flow"
        assert len(setups) == 2  # the reload the options' save starts
        assert removed is None
    else:
        assert entry.options["signals"]["flow"] == flow.entity_id
        assert len(setups) == 1
        assert removed is not None
    assert entry.options["signals"]["flame"] == boiler.entity(Signal.FLAME)
    other = ir.async_get(hass).async_get_issue(
        DOMAIN, f"entity_removed_{entry.entry_id}_{boiler.entity(Signal.FLAME)}"
    )
    assert other is None


async def test_other_registry_changes_are_not_followed(
    hass: HomeAssistant, zones: FakeZones, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negatives: an entity the options do not name renamed or removed, and a named entity
    changed in anything but its ID (its name, disabled or not), change nothing: no reload, no
    issue."""
    from homeassistant.helpers import issue_registry as ir

    registry = er.async_get(hass)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    other = registry.async_get_or_create("sensor", "fake", "other")
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    options = dict(entry.options)
    setups = count_setups(monkeypatch)
    registry.async_update_entity(other.entity_id, new_entity_id="sensor.renamed_other")
    registry.async_update_entity(living, name="Living room")
    registry.async_remove("sensor.renamed_other")
    await hass.async_block_till_done()
    assert dict(entry.options) == options
    assert setups == []
    assert not [i for (d, i) in ir.async_get(hass).issues if d == DOMAIN and "removed" in i]


async def test_a_removed_entity_raises_a_repair_issue(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P-19: an entity the options name removed from Home Assistant — a VT thermostat deleted —
    raises a repair issue naming the fields and the entity: a warning, not fixable, kept across
    restarts; the plugin goes on without it. Back in the registry, the issue goes; so does it
    once the options no longer name the entity."""
    from homeassistant.helpers import issue_registry as ir

    registry = er.async_get(hass)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    bedroom = zones.add("bedroom")
    entry = entry_for(boiler, zones, reference_room={"strategy": "chosen_zone", "zone": living})
    await setup(hass, entry)
    issue_id = f"entity_removed_{entry.entry_id}_{living}"

    def remove(entity: str) -> None:  # as a VT thermostat deleted: its state goes with it
        registry.async_remove(entity)
        hass.states.async_remove(entity)

    remove(living)
    await hass.async_block_till_done()
    issue = ir.async_get(hass).async_get_issue(DOMAIN, issue_id)
    assert issue is not None
    assert issue.translation_key == "entity_removed"
    assert issue.severity is ir.IssueSeverity.WARNING
    assert not issue.is_fixable
    assert issue.is_persistent
    assert issue.translation_placeholders == {
        "field": "zones, reference_room.zone",
        "entity": living,
    }
    assert entry.state is ConfigEntryState.LOADED  # goes on without it
    zones.add("living")  # the same thermostat registered again
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None
    gone = f"entity_removed_{entry.entry_id}_{bedroom}"
    remove(bedroom)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, gone) is not None
    hass.config_entries.async_update_entry(
        entry, options={**entry.options, "zones": [{"entity_id": living}]}
    )
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, gone) is None  # no longer named
    remove(living)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is not None
    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert ir.async_get(hass).async_get_issue(DOMAIN, issue_id) is None  # with the entry


async def test_zone_entities_from_before_move_to_the_stable_key(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """An entity keyed on the thermostat's entity ID (up to 0.2) keeps its entity and history."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    entry = entry_for(boiler, zones)
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    old = registry.async_get_or_create(
        "binary_sensor",
        DOMAIN,
        f"{entry.entry_id}_hot_water_{living}",
        config_entry=entry,
        suggested_object_id="living_hot_water",
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entity_id(hass, entry, "binary_sensor", "hot_water", living) == old.entity_id


async def test_a_store_with_broken_fields_still_loads(
    hass: HomeAssistant, hass_storage: dict[str, Any], zones: FakeZones
) -> None:
    """P66: a broken field is skipped, not the whole store. The monitoring start is the entry's
    creation (V1, R6): a broken stored start no longer starts it again — here the entry was just
    created, so it is about now."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    entry = entry_for(boiler, zones)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": "long ago",
            "factors": {living: {"value": "high"}, "climate.gone": 3},
            "measured": ["not", "a", "mapping"],
            "control": {},
        },
    }
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.runtime_data.monitoring_since == pytest.approx(
        datetime.now(UTC).timestamp(), abs=60
    )


async def test_a_store_that_is_not_a_mapping_is_ignored(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    zones: FakeZones,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stored data of another shape starts from the defaults, with a warning. The monitoring
    start is the entry's creation, not restarted by the loss (V1, R6): about now, as the entry
    was just created."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler, zones)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": ["not", "a", "mapping"],
    }
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert "Ignoring stored data that is not a mapping" in caplog.text
    assert entry.runtime_data.monitoring_since == pytest.approx(
        datetime.now(UTC).timestamp(), abs=60
    )


async def test_a_stopped_installation_writes_nothing_more(
    hass: HomeAssistant, hass_storage: dict[str, Any], zones: FakeZones
) -> None:
    """P66: after a reload the old installation's analysis may still end; it must not write
    over the store of the new one."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    old = entry.runtime_data
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    old.monitoring_since = 0.0  # what the old one would write
    old.schedule_save()
    await analyse_now(old)
    async_fire_time_changed(hass, datetime.now(UTC) + timedelta(minutes=20))  # past any delay
    await hass.async_block_till_done()
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["monitoring_since"] != 0.0


async def test_an_entry_from_before_drops_the_options_that_are_gone(
    hass: HomeAssistant,
) -> None:
    """P71: an entry migration: options removed in 0.2.1 (anti-cycling, the daily cap, the
    summer threshold) leave the stored options."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    old_control = {
        "write_path": "entity",
        "min_burn_min": 5,
        "min_pause_min": 10,
        "daily_cap": 100,
        "cap_reaction": "hand_back",
        "summer_threshold": 16,
        "max_starts_per_hour": 4,
    }
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={**entry.options, "control": old_control},
        version=1,
        minor_version=1,
    )
    await setup(hass, entry)
    assert entry.minor_version == 5
    # Minor version 3 (X6): the lowest water temperature 0.2.1 used, kept.
    assert entry.options["control"] == {"write_path": "entity", "hard_min": 25.0}


@pytest.mark.parametrize(
    ("monitor", "threshold"),
    [
        ({"pressure_low_warning": 1.0, "pressure_low_alarm": 0.7}, None),  # 0.2.1's defaults
        ({"pressure_low_warning": 0.8, "pressure_low_alarm": 0.5}, 0.8),  # the warning, set
        ({"pressure_low_warning": 1.0, "pressure_low_alarm": 0.6}, 0.6),  # the alarm, set
        ({"pressure_low_warning": 0.8, "add_water_below": 1.2}, 1.2),  # already there: kept
        ({"pressure_low_warning": "broken"}, None),  # unreadable: nothing carried over
        ({}, None),
    ],
)
async def test_the_alarm_migration_moves_to_the_add_water_threshold(
    hass: HomeAssistant, monitor: dict[str, Any], threshold: float | None
) -> None:
    """Y1 (minor version 4; feeds P-124): 0.2.1's two low-pressure limits go; one stored other
    than its default — the warning, else the alarm — becomes the "add water" threshold (none at
    the defaults). Stored alarm reactions decision 7 no longer offers go, and one warning issue
    names those that were set to hand back; the ignored write's stays — offered again once the
    gateway's thermostat question allows it, informing until then (PB-72)."""
    from homeassistant.helpers import issue_registry as ir

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    options = dict(entry_for(boiler).options)
    options["monitor"] = {"monitoring_days": 7, **monitor}
    options["control"] = {
        "write_path": "opentherm_gw",
        "gateway_id": "gw",
        "topology": "gateway_standalone",
        "thermostat_kind": "none",
        "hard_min": 25.0,
        "alarm_reactions": {
            "pressure_low": "hand_back",
            "write_ignored": "hand_back",
            "frequent_starts": "info",
            "outside_change": "info",
        },
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options, version=1, minor_version=3
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 5
    stored = entry.options["monitor"]
    assert "pressure_low_warning" not in stored
    assert "pressure_low_alarm" not in stored
    assert stored.get("add_water_below") == threshold
    assert stored["monitoring_days"] == 7
    # PB-72: stand-alone the ignored write's reaction is not offered, but kept: it informs.
    assert entry.options["control"]["alarm_reactions"] == {"write_ignored": "hand_back"}
    assert entry.runtime_data.config.control.reaction("write_ignored").value == "info"
    found = ir.async_get(hass).async_get_issue(DOMAIN, f"reactions_removed_{entry.entry_id}")
    assert found is not None
    assert found.translation_placeholders == {"alarms": "pressure_low"}
    assert found.severity is ir.IssueSeverity.WARNING


async def test_the_alarm_migration_keeps_an_offered_reaction_and_raises_no_issue(
    hass: HomeAssistant,
) -> None:
    """Negative: with a thermostat to take over, the ignored write's reaction is kept; reactions
    that were information only go without an issue."""
    from homeassistant.helpers import issue_registry as ir

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    options = dict(entry_for(boiler).options)
    options["control"] = {
        "write_path": "opentherm_gw",
        "gateway_id": "gw",
        "topology": "gateway_with_thermostat",
        "thermostat_kind": "opentherm",
        "hard_min": 25.0,
        "alarm_reactions": {"write_ignored": "hand_back", "low_flow": "info"},
    }
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options, version=1, minor_version=3
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 5
    assert entry.options["control"]["alarm_reactions"] == {"write_ignored": "hand_back"}
    assert ir.async_get(hass).async_get_issue(DOMAIN, f"reactions_removed_{entry.entry_id}") is None


@pytest.mark.parametrize(
    ("control", "hard_min"),
    [
        ({"write_path": "opentherm_gw"}, 25.0),  # none stored: 0.2.1's floor, kept
        ({"write_path": "opentherm_gw", "hard_min": None}, 25.0),
        ({"write_path": "opentherm_gw", "hard_min": ""}, 25.0),
        ({"write_path": "opentherm_gw", "hard_min": 30}, 30),  # the user's own: unchanged
        ({"write_path": "opentherm_gw", "hard_min": 20.0}, 20.0),
        (None, None),  # no control section: no key
        ({}, None),  # an empty section: control not configured, nothing to keep
    ],
)
async def test_migration_keeps_the_floor_of_a_control_section_without_it(
    hass: HomeAssistant, control: dict[str, Any] | None, hard_min: float | None
) -> None:
    """Decision 2: the lowest water temperature's default becomes 20 °C; an entry of minor
    version 2 whose control section has none gets 25.0 written by the migration, so no
    installation's floor drops silently (provisional, K4). A value the user stored stays; an
    entry without control gets no key."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    options = dict(entry_for(boiler).options)
    if control is not None:
        options["control"] = control
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options, version=1, minor_version=2
    )
    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.minor_version == 5
    stored = entry.options.get("control")
    if hard_min is None:
        assert stored == control
    else:
        assert stored is not None
        assert stored["hard_min"] == hard_min


# P-124: one entry as each minor version stored it — 0.2.0's (1), then what each migration step
# made of it — and the options this version holds for all of them.
_GATEWAY = {
    "write_path": "opentherm_gw",
    "gateway_id": "gw",
    "topology": "gateway_with_thermostat",
    "thermostat_kind": "opentherm",
}
_REACTIONS = {"pressure_low": "hand_back", "write_ignored": "hand_back", "outside_change": "info"}
_OLD_MONITOR = {"monitoring_days": 7, "pressure_low_warning": 0.8, "pressure_low_alarm": 0.5}
STORED_BY_MINOR: dict[int, dict[str, Any]] = {
    1: {
        "boiler": {"class": "flow_setpoint", "dhw": "combi", "shared_return": True},
        "control": _GATEWAY | {"min_burn_min": 5, "daily_cap": 100, "alarm_reactions": _REACTIONS},
        "monitor": _OLD_MONITOR,
    },
    2: {  # 0.2.1's removed options gone (shared_return among them)
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "control": _GATEWAY | {"alarm_reactions": _REACTIONS},
        "monitor": _OLD_MONITOR,
    },
    3: {  # X6: 0.2.1's lowest water temperature kept
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "control": _GATEWAY | {"alarm_reactions": _REACTIONS, "hard_min": 25.0},
        "monitor": _OLD_MONITOR,
    },
}
CURRENT_OPTIONS = {  # Y1: the "add water" threshold; the one reaction still offered
    "boiler": {"class": "flow_setpoint", "dhw": "combi"},
    "control": _GATEWAY | {"alarm_reactions": {"write_ignored": "hand_back"}, "hard_min": 25.0},
    "monitor": {"monitoring_days": 7, "add_water_below": 0.8},
}
STORED_BY_MINOR[4] = STORED_BY_MINOR[5] = CURRENT_OPTIONS  # no pressure: 5 writes nothing


@pytest.mark.parametrize(
    ("minor", "stored", "expected"),
    [
        (4, {}, {"pressure_high_warning": 2.5, "pressure_high_alarm": 2.8}),
        (
            1,
            {"pressure_high_alarm": 3.0},
            {"pressure_high_warning": 2.5, "pressure_high_alarm": 3.0},
        ),
        (5, {}, {}),
    ],
    ids=["ran_with_the_defaults", "one_stored", "this_version"],
)
async def test_an_entry_from_before_keeps_the_high_pressure_limits_it_ran_with(
    hass: HomeAssistant, minor: int, stored: dict[str, float], expected: dict[str, float]
) -> None:
    """Decision 13 of 0.2.3 (SB-18, minor version 5): an entry from before with the water
    pressure mapped keeps the 2.5 / 2.8 bar it ran with — written into its options, shown in
    the form — and so its alarm; a stored limit stays as stored. Negative: an entry of this
    version without limits gets none — no high-pressure alarm, the feature naming what it
    lacks."""
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.PRESSURE))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.PRESSURE: 1.5})
    options = dict(entry_for(boiler).options) | {"monitor": {"monitoring_days": 7, **stored}}
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options, version=1, minor_version=minor
    )
    await setup(hass, entry)
    assert entry.minor_version == 5
    assert entry.options["monitor"] == {"monitoring_days": 7, **expected}
    key = f"{entry.entry_id}_alarm_pressure_high"
    found = er.async_get(hass).async_get_entity_id("binary_sensor", DOMAIN, key)
    assert (found is not None) is bool(expected)
    missing = entry.runtime_data.data.features[Feature.PRESSURE_WARNING].missing
    assert missing == (() if expected else ("pressure_high_threshold",))


@pytest.mark.parametrize("minor", sorted(STORED_BY_MINOR))
async def test_an_entry_of_any_earlier_minor_version_migrates_to_this_ones_options(
    hass: HomeAssistant, minor: int
) -> None:
    """P-124: from minor version 1 through 2, 3 and 4 to this one (5), each step applied once and in
    order from where the entry stands — ``boiler.shared_return`` and 0.2.1's removed control
    options go (2), the lowest water temperature 0.2.1 used is kept (3, X6), the low-pressure
    limits become the "add water" threshold and the reactions decision 7 no longer offers go,
    with their warning (4, Y1). Every starting point ends with the same options; an entry
    already current is left as it is, and warns of nothing."""
    from homeassistant.helpers import issue_registry as ir

    from custom_components.vtherm_smart_boiler.config_flow import SmartBoilerConfigFlow

    assert max(STORED_BY_MINOR) == SmartBoilerConfigFlow.MINOR_VERSION
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    base = dict(entry_for(boiler).options)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=base | STORED_BY_MINOR[minor],
        version=1,
        minor_version=minor,
    )
    await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    assert (entry.version, entry.minor_version) == (1, SmartBoilerConfigFlow.MINOR_VERSION)
    assert dict(entry.options) == base | CURRENT_OPTIONS
    found = ir.async_get(hass).async_get_issue(DOMAIN, f"reactions_removed_{entry.entry_id}")
    if minor < 4:
        assert found is not None
        assert found.translation_placeholders == {"alarms": "pressure_low"}
    else:
        assert found is None


@pytest.mark.parametrize(
    ("version", "minor", "refused"),
    [(2, 1, True), (3, 4, True), (1, 9, False)],
    ids=["version_2", "version_3", "newer_minor_of_version_1"],
)
async def test_a_newer_entry_is_refused(
    hass: HomeAssistant, version: int, minor: int, refused: bool
) -> None:
    """P-124: an entry a newer version stored (version 2 and up) is not set up — nothing here can
    read it: migration error, its options untouched, nothing of the plugin created. Negative: a
    newer minor version of version 1 is, as Home Assistant counts it, one this version can read:
    set up as it is, its minor version kept."""
    from homeassistant.helpers import entity_registry as er

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    options = dict(entry_for(boiler).options) | {"a_later_option": {"x": 1}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options,
        version=version,
        minor_version=minor,
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id) is not refused
    await hass.async_block_till_done(wait_background_tasks=True)
    assert (entry.version, entry.minor_version) == (version, minor)
    assert dict(entry.options) == options
    created = er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    if refused:
        assert entry.state is ConfigEntryState.MIGRATION_ERROR
        assert created == []
    else:
        assert entry.state is ConfigEntryState.LOADED
        assert created


def _stored_days(start: float, count: int, settings: str) -> dict[str, dict[str, Any]]:
    """Days of a boiler cycling twice an hour, as the plugin stores them."""
    from custom_components.vtherm_smart_boiler.core.daily import DaySummary

    days = {}
    for d in range(count):
        begin = start + d * DAY
        day = DaySummary(
            begin, begin + DAY, DAY, 48, 48, 48, 8 * 3600.0, DAY,
            8 * 3600.0, 8 * 3600.0, 7.0, None, settings=settings,
        )  # fmt: skip
        days[str(int(begin))] = day.to_dict()
    return days


def _settings_of(entry: MockConfigEntry) -> str:
    """The key of the settings an entry's days are summarised with."""
    from custom_components.vtherm_smart_boiler.config import EntryConfig
    from custom_components.vtherm_smart_boiler.coordinator import summary_settings
    from custom_components.vtherm_smart_boiler.core.daily import settings_key

    return settings_key(summary_settings(EntryConfig.from_options(entry.options)))


async def test_the_verdict_comes_from_the_days_kept_across_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """W1: day summaries outlive the rolling history; after a restart the verdict does not wait
    for new data."""
    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.RETURN: 28.0})
    entry = entry_for(boiler)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": now - 30 * DAY,
            "daily": _stored_days(now - 20 * DAY, 20, _settings_of(entry)),
        },
    }
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert len(coordinator.daily) == 20
    assert coordinator.analysis is not None
    verdict = coordinator.analysis.verdict
    # All short burns: found from the stored days, and shown as "not changed yet" (answer K).
    assert verdict.verdict.value == "not_worth_it"
    [short] = [r for r in verdict.reasons if r.code.value == "short_burns"]
    assert short.changed_by_control is False
    stored = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert len(stored["daily"]) >= 20


async def test_an_unchanged_building_fit_is_not_saved_again(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A14: the analysis runs every five minutes and fits the building each time; saving the
    whole store after every run, a year of days in it, wore SD cards for nothing. A fit that
    has not moved is not saved again."""
    from custom_components.vtherm_smart_boiler.core.daily import DaySummary

    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler, parameters={"heating_threshold": 16.0})
    key = _settings_of(entry)
    days = {}
    for d in range(12):
        begin = now - (20 - d) * DAY
        outdoor = -4.0 + d
        day = DaySummary(
            begin, begin + DAY, DAY, 10, 10, 0, 6 * 3600.0, DAY, 0.0, 0.0,
            None, None, outdoor_mean=outdoor, heat_kwh=0.2 * 24 * (16.0 - outdoor), settings=key,
        )  # fmt: skip
        days[str(int(begin))] = day.to_dict()
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": now - 30 * DAY, "daily": days},
    }
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert coordinator.analysis is not None
    assert coordinator.analysis.fit is not None
    saves: list[float] = []
    monkeypatch.setattr(coordinator, "schedule_save", lambda delay=0.0: saves.append(delay))
    freezer.tick(300)
    await analyse_now(coordinator)
    assert coordinator.analysis.fit is not None
    assert saves == []  # the same fit: nothing to write


async def test_days_kept_with_other_settings_no_longer_count(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """A4: days summarised before the user corrected a setting keep the old judgement: they are
    kept, should the setting come back, but no longer count."""
    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.RETURN: 28.0})
    entry = entry_for(boiler)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": now - 30 * DAY,
            "daily": _stored_days(now - 20 * DAY, 20, "settings before the correction"),
        },
    }
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert coordinator.analysis is not None
    assert coordinator.analysis.verdict.verdict.value == "not_enough_data"
    assert len(coordinator.daily) == 20  # kept all the same


async def test_days_before_the_history_are_filled_as_far_as_the_recorder_reaches(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """W1: the recorder keeps ten days by default, or whatever it was set to: every day it
    still has is summarised, and the search stops where it has no more."""
    from homeassistant.core import State

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    reach = now - 30 * DAY
    asked: list[float] = []

    def significant_states(hass, start_time, *, end_time=None, entity_ids=None, **_kwargs):
        asked.append(start_time.timestamp())
        end = now if end_time is None else end_time.timestamp()
        begin = max(start_time.timestamp(), reach)
        if begin >= end:
            return {}
        flame = boiler.entity(Signal.FLAME)
        rows = []
        t = begin
        while t < end:  # a ten-minute burn every half hour
            moment = datetime.fromtimestamp(t, UTC)
            rows.append(State(flame, "off", {}, last_updated=moment))
            rows.append(State(flame, "on", {}, last_updated=moment + timedelta(minutes=5)))
            rows.append(State(flame, "off", {}, last_updated=moment + timedelta(minutes=15)))
            t += 1800.0
        return {flame: rows}

    class Recorder:
        async def async_add_executor_job(self, target, *args):
            return await hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    hass.config.components.add("recorder")
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    days = sorted(entry.runtime_data.daily)
    assert days[0] == pytest.approx(reach, abs=DAY)  # as far as the recorder reaches
    assert len(days) >= 29
    assert min(asked) > now - 60 * DAY  # it stopped where the recorder had no more


@pytest.mark.parametrize(("hot_water", "alarm"), [(True, "off"), (False, "on")])
async def test_short_hot_water_draws_are_no_ignition_problem(
    hass: HomeAssistant, freezer, hot_water: bool, alarm: str
) -> None:
    """P47: a combi boiler's short draws are hot water, not flames lost after ignition; the
    same short burns for heating are."""
    freezer.move_to(datetime(2026, 1, 10, 6, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.DHW_ACTIVE))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.DHW_ACTIVE: False})
    entry = entry_for(boiler)
    options = {**entry.options, "boiler": {"class": "read_only", "dhw": "combi"}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    await setup(hass, entry)
    # Y1: a count is judged with the flame known for half its window at least (12 h a day).
    freezer.tick(timedelta(hours=7))
    for _ in range(12):  # twelve 40-second burns
        freezer.tick(timedelta(minutes=30))
        boiler.set_many({Signal.DHW_ACTIVE: hot_water, Signal.FLAME: True})
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=40))
        boiler.set_many({Signal.FLAME: False, Signal.DHW_ACTIVE: False})
        await hass.async_block_till_done()
    # P-80: the count comes from the analysis' burns, as of its last run.
    await analyse_now(entry.runtime_data)
    await hass.async_block_till_done()
    ignition = hass.states.get(entity_id(hass, entry, "binary_sensor", "alarm_unstable_ignition"))
    assert ignition.state == alarm


@pytest.mark.parametrize(("lost", "alarm"), [(False, "off"), (True, "on")])
async def test_a_tpi_zones_short_pulses_are_no_ignition_problem(
    hass: HomeAssistant, freezer, zones: FakeZones, lost: bool, alarm: str
) -> None:
    """R6, A2: a TPI zone at 10 % keeps its duty cycle through the cycle while its relay pulses.
    Burns that follow the relay — lit after it closes, out after it opens — lost no flame; the
    same short burns going out while the relay is still closed are flames lost."""
    freezer.move_to(datetime(2026, 1, 10, 6, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    zones.add("living", on_percent=0.1)
    await setup(hass, entry_for(boiler, zones))
    entry = hass.config_entries.async_entries(DOMAIN)[0]
    # Y1: a count is judged with the flame known for half its window at least (12 h a day).
    freezer.tick(timedelta(hours=12))
    for _ in range(12):  # twelve five-minute cycles, 30 s on each
        zones.set("living", hvac_action="heating", on_percent=0.1)
        freezer.tick(timedelta(seconds=10))
        boiler.set(Signal.FLAME, True)
        await hass.async_block_till_done()
        if lost:
            freezer.tick(timedelta(seconds=15))
            boiler.set(Signal.FLAME, False)  # out while the relay is still closed
            freezer.tick(timedelta(seconds=5))
            zones.set("living", hvac_action="idle", on_percent=0.1)
        else:
            freezer.tick(timedelta(seconds=20))
            zones.set("living", hvac_action="idle", on_percent=0.1)
            freezer.tick(timedelta(seconds=2))
            boiler.set(Signal.FLAME, False)  # out once the relay has opened
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=268))
    # P-80: the count comes from the analysis' burns, as of its last run.
    await analyse_now(entry.runtime_data)
    await hass.async_block_till_done()
    ignition = hass.states.get(entity_id(hass, entry, "binary_sensor", "alarm_unstable_ignition"))
    assert ignition.state == alarm


async def test_an_entered_loss_that_the_measurement_disagrees_with_is_shown(
    hass: HomeAssistant,
) -> None:
    """P77: the mismatch between the value entered and the one measured is shown."""
    from custom_components.vtherm_smart_boiler.core.parameters import (
        Estimate,
        ParameterKey,
        Source,
    )

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    options = {**entry.options, "parameters": {"loss_coefficient": 0.2}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    coordinator.parameters = coordinator.parameters.with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(0.4, Source.MEASURED, 0.8)
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    state = hass.states.get(entity_id(hass, entry, "sensor", "loss_coefficient"))
    assert state.attributes["entered"] == 0.2
    assert state.attributes["measured"] == 0.4
    assert state.attributes["mismatch"] is True


async def test_the_gas_unit_follows_the_meter(hass: HomeAssistant) -> None:
    """P70: a meter whose unit is not known at setup does not leave "gas" in the unit."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.GAS_METER))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    meter = boiler.entity(Signal.GAS_METER)
    hass.states.async_set(meter, "unavailable", {})
    entry = entry_for(boiler)
    await setup(hass, entry)
    hass.states.async_set(meter, "1234.5", {"unit_of_measurement": "m³"})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    sensor = hass.states.get(entity_id(hass, entry, "sensor", "gas_per_degree_day"))
    assert sensor.attributes["unit_of_measurement"] == "m³/K·d"


async def test_invalid_options_fail_setup_with_a_reason(hass: HomeAssistant) -> None:
    # No signal is required any more (X8), and an unknown key is ignored (PB-68): an
    # implausible parameter is refused.
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", options={"parameters": {"boiler_min_power": 0.0}}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.reason is not None


async def test_missing_entities_show_as_signal_problems(hass: HomeAssistant) -> None:
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    boiler.set(Signal.FLAME, False)  # flow and return never appear
    entry = entry_for(boiler)
    await setup(hass, entry)
    connection = hass.states.get(entity_id(hass, entry, "binary_sensor", "connection"))
    assert connection is not None
    assert connection.state == "off"
    assert connection.attributes["problems"] == ["flow"]
    problems = hass.states.get(entity_id(hass, entry, "sensor", "signal_problems"))
    assert problems is not None
    assert problems.state == "2"


@pytest.mark.parametrize(("limit", "stale"), [(None, False), (1800.0, True)])
async def test_a_steady_flow_is_stale_only_past_a_user_limit(
    hass: HomeAssistant, freezer, zones: FakeZones, limit: float | None, stale: bool
) -> None:
    """One freshness rule: many sources report only on change, so a flow steady for an hour is
    still fresh — unless the user set a shorter age limit for it."""
    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=50)
    extra = {} if limit is None else {"freshness": {"flow": limit}}
    entry = entry_for(boiler, zones, **extra)
    await setup(hass, entry)
    hot_id = entity_id(hass, entry, "binary_sensor", "hot_water", living)
    assert hass.states.get(hot_id).state == "on"
    freezer.tick(timedelta(hours=1))
    zones.set("living", hvac_action="heating", valve_open_percent=50)  # the zone stays fresh
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()  # whatever the timers did under load
    await hass.async_block_till_done()
    state = hass.states.get(hot_id)
    assert (state.state == "unknown") is stale  # unknown, not "no" (the user's decision)
    if stale:
        assert state.attributes["reason"] == "flow_stale"


async def test_replayed_history_reaches_the_verdict(
    hass: HomeAssistant, freezer, forecasts: FakeForecasts
) -> None:
    start = datetime(2026, 1, 1, tzinfo=UTC).timestamp()
    scenario = Scenario(
        BOILERS["condensing_large"],
        HOUSES["average"],
        radiator_zones(),
        daily_cycle([9.0] * 8),
        days=8,
        start=start,
        step_s=30.0,  # at most MAX_STEP_S (PB-92)
    )
    history = simulate(scenario).history
    freezer.move_to(datetime.fromtimestamp(start, UTC))
    # the forecast fixture set the weather state before the clock moved back: set it again
    hass.states.async_set(WEATHER_ENTITY, "cloudy", {"temperature": 9.0, "temperature_unit": "°C"})
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN, Signal.MODULATION))
    zones = FakeZones(hass)
    for zone_id in history.zones:
        zones.add(zone_id)
    events = replay_events(history, zones)
    apply_event(boiler, zones, events[0][1])
    entry = entry_for(
        boiler,
        zones,
        weather=WEATHER_ENTITY,
        parameters={
            "boiler_min_power": 4.0,
            "boiler_max_power": 25.0,
            "loss_coefficient": 0.25,
            "heating_threshold": 18.0,
        },
    )
    await setup(hass, entry)
    for t, changes in events[1:]:
        freezer.move_to(datetime.fromtimestamp(t, UTC))
        apply_event(boiler, zones, changes)
    freezer.move_to(datetime.fromtimestamp(start + 8 * DAY, UTC))
    # The first analysis starts in the background at setup; while it runs, another returns at
    # once — so wait for it before running one over the whole history.
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    await analyse_now(coordinator)
    await hass.async_block_till_done()
    verdict = hass.states.get(entity_id(hass, entry, "sensor", "verdict"))
    assert verdict is not None
    # Every criterion judged — the load too, with the model entered (S-17); what is found is
    # not changed by 0.2.2's control for a boiler not declared flow-setpoint (answer K).
    assert verdict.state == "not_worth_it"
    reasons = {r["code"]: r for r in verdict.attributes["reasons"]}
    assert "load_unknown" not in reasons
    assert all(r.get("changed_by_control") is not True for r in reasons.values())
    starts = hass.states.get(entity_id(hass, entry, "sensor", "starts_per_hour"))
    assert starts is not None
    assert float(starts.state) > 1.0
    assert forecasts.calls  # snapshots were taken


async def test_everything_stored_survives_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], zones: FakeZones
) -> None:
    """A restart loads what the last run stored and, stopped again, stores the same: the start
    of monitoring (the entry's creation, V1), the zones' factors, the measured building values
    and the day summaries."""
    from custom_components.vtherm_smart_boiler.core.daily import DaySummary
    from custom_components.vtherm_smart_boiler.core.parameters import ParameterKey, Source

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    living = zones.add("living")
    entry = entry_for(boiler, zones)
    now = datetime.now(UTC).timestamp()
    start = float(int(now - 3 * DAY))
    day = DaySummary(
        start, start + DAY, DAY, 12, 10, 1, 7200.0, 36000.0, 3600.0, 7200.0,
        8.5, None, 4.0, 60.0,
    )  # fmt: skip
    created = float(int(now - 10 * DAY))
    entry.created_at = datetime.fromtimestamp(created, UTC)
    stored = {
        "monitoring_since": created,
        "factors": {living: {"value": 0.8, "at": now - 600, "output_w": None}},
        "measured": {"loss_coefficient": {"value": 0.25, "confidence": 0.6, "at": now - DAY}},
        "daily": {str(int(start)): day.to_dict()},
    }
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = {"version": 1, "key": key, "data": stored}
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert coordinator.monitoring_since == stored["monitoring_since"]
    assert coordinator.daily == {start: day}
    loss = coordinator.parameters.get(ParameterKey.LOSS_COEFFICIENT).estimate(Source.MEASURED)
    assert loss is not None
    assert (loss.value, loss.confidence) == (0.25, 0.6)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    saved = hass_storage[key]["data"]
    for field_name in ("monitoring_since", "measured", "daily"):
        assert saved[field_name] == stored[field_name], field_name
    assert saved["factors"][living]["value"] == 0.8


async def test_a_new_entry_without_control_owes_nothing(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """V1, R3 and R4: a new monitor-only entry has no stores. Nothing is owed and nothing is
    reported; both stores are written, and only after both were read."""
    from unittest.mock import patch

    from homeassistant.helpers import issue_registry as ir
    from homeassistant.helpers.storage import Store

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    keys = {f"{DOMAIN}.{entry.entry_id}", f"{DOMAIN}.{entry.entry_id}.control"}
    order: list[tuple[str, str]] = []
    load, write = Store.async_load, Store._async_write_data

    async def recorded_load(store: Store[Any]) -> Any:
        if store.key in keys:
            order.append(("read", store.key))
        return await load(store)

    async def recorded_write(store: Store[Any], data: dict[str, Any]) -> None:
        if store.key in keys:
            order.append(("write", store.key))
        await write(store, data)

    # Patched for the setup only: the storage mock's own patches must be undone after these.
    with (
        patch.object(Store, "async_load", recorded_load),
        patch.object(Store, "_async_write_data", recorded_write),
    ):
        await setup(hass, entry)
    assert entry.state is ConfigEntryState.LOADED
    reads = [key for action, key in order if action == "read"]
    first_write = next(i for i, (action, _) in enumerate(order) if action == "write")
    assert set(reads[:2]) == keys  # both read ...
    assert all(action == "read" for action, _ in order[:first_write])  # ... before any write
    assert keys <= set(hass_storage)
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}.control"]["data"] == {}
    assert hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]["control_store"] == 1
    assert entry.runtime_data.stored_control == {}
    assert entry.runtime_data.hand_back_unit is None
    issues = ir.async_get(hass)
    for key in ("control_state_unreadable", "hand_back_owed"):
        assert issues.async_get_issue(DOMAIN, f"{key}_{entry.entry_id}") is None
    assert "nothing is owed" in caplog.text  # a warning, not an error


async def test_both_stores_are_written_atomically(hass: HomeAssistant) -> None:
    """V1, R1: a crash while writing leaves the old file whole, for either store and for every
    place that writes them."""
    from custom_components.vtherm_smart_boiler.coordinator import control_store, main_store

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert coordinator._store._atomic_writes
    assert coordinator._control_store._atomic_writes
    assert coordinator._control_store.key == f"{DOMAIN}.{entry.entry_id}.control"
    assert main_store(hass, entry.entry_id)._atomic_writes
    assert control_store(hass, entry.entry_id)._atomic_writes


async def test_a_relay_only_entry_monitors_without_boiler_signals(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """X8 (R4): no boiler signal at all — the entry sets up and monitors; the connection is
    unknown (nothing tells), the features name the flame they miss, and no alarm that needs
    burns exists. With the relay path the connection follows the relay."""
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    zones.add("living")
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={"signals": {}, "zones": [{"entity_id": e} for e in zones.entities.values()]},
    )
    await setup(hass, entry)
    connection = hass.states.get(entity_id(hass, entry, "binary_sensor", "connection"))
    assert connection is not None
    assert connection.state == "unknown"
    assert connection.attributes["problems"] == []
    data = entry.runtime_data.data
    assert data.features[Feature.CYCLES].missing == (Signal.FLAME,)
    registry = er.async_get(hass)
    for kind in ("frequent_starts", "unstable_ignition"):
        unique_id = f"{entry.entry_id}_alarm_{kind}"
        assert registry.async_get_entity_id("binary_sensor", DOMAIN, unique_id) is None


@pytest.mark.parametrize(("shown", "on"), [("off", "on"), ("unavailable", "off")])
async def test_the_connection_follows_the_relay(
    hass: HomeAssistant, zones: FakeZones, shown: str, on: str
) -> None:
    zones.add("living")
    hass.states.async_set("switch.boiler_relay", shown)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options={
            "signals": {},
            "boiler": {"class": "on_off"},
            "zones": [{"entity_id": e} for e in zones.entities.values()],
            "control": {"write_path": "relay", "relay_entity": "switch.boiler_relay"},
        },
    )
    await setup(hass, entry)
    connection = hass.states.get(entity_id(hass, entry, "binary_sensor", "connection"))
    assert connection is not None
    assert connection.state == on
    assert connection.attributes["problems"] == ([] if on == "on" else ["relay"])


# --- Y2: cycles, gas and days ----------------------------------------------------------------


def _fake_recorder(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, rows) -> list[dict]:
    """Home Assistant's recorder answered from ``rows(start, end, entity_ids)``: what each read
    asked is returned."""
    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    asked: list[dict] = []

    def significant_states(hass, start_time, *, end_time=None, entity_ids=None, **_kwargs):
        asked.append({"start": start_time, "end": end_time, "entity_ids": list(entity_ids)})
        return rows(start_time, end_time, entity_ids)

    class Recorder:
        async def async_add_executor_job(self, target, *args):
            return await hass.async_add_executor_job(target, *args)

    monkeypatch.setattr(coordinator_module, "_recorder", lambda hass: Recorder())
    monkeypatch.setattr(coordinator_module, "_significant_states", lambda: significant_states)
    hass.config.components.add("recorder")
    return asked


# The restart the downtime tests share: the plugin last ran at 10:00 (``STOPPED``), Home
# Assistant starts again at 16:00 (``RESTART``); the recorder holds the flame off from 20:00 the
# day before and on from 09:50, and the flow at 40 °C.
RESTART = datetime(2026, 1, 10, 16, tzinfo=UTC)
STOPPED = RESTART.timestamp() - 6 * 3600.0
MIDNIGHT = datetime(2026, 1, 10, tzinfo=UTC).timestamp()


def _alive_key(entry: MockConfigEntry) -> str:
    return f"{DOMAIN}.{entry.entry_id}.alive"


async def _restart(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer,
    monkeypatch: pytest.MonkeyPatch,
    *,
    alive: dict[str, Any] | None = None,
    main: dict[str, Any] | None = None,
    created: datetime | None = None,
) -> MockConfigEntry:
    """Set up an entry at ``RESTART`` over the recorded rows, with the last-run record ``alive``
    (``{"data": ...}``; ``None``: none) and the main store's ``main`` data (``None``: none)."""
    from homeassistant.core import State

    freezer.move_to(RESTART)
    now = RESTART.timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    flame, flow = boiler.entity(Signal.FLAME), boiler.entity(Signal.FLOW)

    def at(t: float) -> datetime:
        return datetime.fromtimestamp(t, UTC)

    def rows(start_time, end_time, entity_ids):
        unit = {"unit_of_measurement": "°C"}
        return {
            flame: [
                State(flame, "off", {}, last_updated=at(now - 20 * 3600.0)),
                State(flame, "on", {}, last_updated=at(STOPPED - 600.0)),
            ],
            flow: [State(flow, "40.0", unit, last_updated=at(now - 20 * 3600.0))],
        }

    _fake_recorder(hass, monkeypatch, rows)
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 40.0})  # burning again at the start
    entry = entry_for(boiler)
    # An entry that has run for a month, unless told otherwise.
    entry.created_at = RESTART - timedelta(days=30) if created is None else created
    key = f"{DOMAIN}.{entry.entry_id}"
    if main is not None:
        hass_storage[key] = {"version": 1, "key": key, "data": main}
    if alive is not None:
        hass_storage[_alive_key(entry)] = {"version": 1, "key": _alive_key(entry)} | alive
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    return entry


async def test_home_assistants_downtime_is_unknown_after_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-95 (A11): the plugin's last-run record — a small store of its own — says when it last
    ran: at a clean stop, the stop. Read back from the recorder, the history is unknown from
    then until the first state after the start: a burn that was on when Home Assistant stopped
    does not burn through the six hours it was down. The record goes on: the stop writes it,
    the entry's main store keeps only a copy of the downtimes, and no ``alive_at``."""
    entry = await _restart(
        hass,
        hass_storage,
        freezer,
        monkeypatch,
        alive={"data": {"alive_at": STOPPED, "down": []}},
        main={"monitoring_since": STOPPED - 30 * DAY},
    )
    now = RESTART.timestamp()
    coordinator = entry.runtime_data
    series = coordinator.history.signals[Signal.FLAME]
    water = coordinator.history.signals[Signal.FLOW]
    assert coordinator.down == [(STOPPED, now)]
    assert series.value_at(STOPPED - 60) is True
    assert water.value_at(STOPPED - 60) == 40.0
    assert series.value_at(STOPPED + 60) is None
    assert series.value_at(now - 60) is None
    assert water.value_at(now - 60) is None
    assert series.value_at(now) is True  # known again from the start
    freezer.tick(60)
    assert await hass.config_entries.async_unload(entry.entry_id)
    from custom_components.vtherm_smart_boiler.coordinator import RUN_KEY

    record = hass_storage[_alive_key(entry)]["data"]
    run = hass.data[RUN_KEY]
    assert record == {"alive_at": pytest.approx(now + 60), "down": [[STOPPED, now]], "run": run}
    main = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    assert "alive_at" not in main
    assert main["down"] == [[STOPPED, now]]
    # PB-65: set up again in the same Home Assistant run (a reload, the entry enabled again):
    # the recorder ran through it — no downtime, the steady flow known throughout.
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.down == [(STOPPED, now)]
    assert entry.runtime_data.history.signals[Signal.FLOW].value_at(now + 90) == 40.0
    # Negative: a record from another run (Home Assistant restarted) is a downtime.
    freezer.tick(60)
    assert await hass.config_entries.async_unload(entry.entry_id)
    hass.data[RUN_KEY] = "another run"
    freezer.tick(60)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.down == [(STOPPED, now), (now + 180, now + 240)]


async def test_home_assistants_stop_writes_the_last_run_record(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """PB-57: Home Assistant's stop unloads no entry, so the record was written only every ten
    minutes — up to ten minutes before each restart counted as downtime. A shutdown job writes
    it at the stop, and stays in Home Assistant's list while the jobs run; an unload without a
    stop removes it (negative: nothing of the entry left behind)."""
    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    name = f"{DOMAIN} last run"

    def ours() -> list[Any]:
        return [j for j in hass._shutdown_jobs if j.job.name == name]

    assert len(ours()) == 1
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert ours() == []
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(ours()) == 1
    freezer.tick(5 * 60)  # before the ten-minute write
    stop = datetime(2026, 2, 1, 0, 5, tzinfo=UTC).timestamp()
    await ours()[0].job.target()
    await hass.async_block_till_done()
    assert hass_storage[_alive_key(entry)]["data"]["alive_at"] == pytest.approx(stop)
    assert len(ours()) == 1  # the job does not remove itself while the jobs run


@pytest.mark.parametrize("platforms_unload", [False, True])
async def test_the_coordinator_stops_whatever_the_platforms_report(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, platforms_unload: bool
) -> None:
    """PB-59: a failed platform unload left the coordinator running — timers, the state
    listener, store writes and notices — in FAILED_UNLOAD until a restart. It stops either
    way; the platforms' answer is still Home Assistant's (negative: a clean unload)."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert coordinator._unsubs

    async def unload_platforms(*_args: Any) -> bool:
        return platforms_unload

    monkeypatch.setattr(hass.config_entries, "async_unload_platforms", unload_platforms)
    assert await hass.config_entries.async_unload(entry.entry_id) is platforms_unload
    expected = ConfigEntryState.NOT_LOADED if platforms_unload else ConfigEntryState.FAILED_UNLOAD
    assert entry.state is expected
    assert coordinator._stopped
    assert coordinator._unsubs == []
    assert not [j for j in hass._shutdown_jobs if j.job.name == f"{DOMAIN} last run"]


async def test_a_control_save_writes_the_entry_store_slowly_unless_the_hold_changed(
    hass: HomeAssistant, freezer
) -> None:
    """PB-60: the entry store — a year of day summaries — was rewritten within 120 s of
    almost every control save. Its copy of the control state now waits the slow delay while
    the boiler's hold and an owed hand-back stay as they are; a change of them is written at
    once (negative)."""
    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler.coordinator import FACTOR_SAVE_DELAY_S

    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    for save in ("scheduled", "now"):
        await coordinator.async_save_now()
        assert coordinator._save_due is None
        if save == "scheduled":
            coordinator.schedule_control_save()
        else:
            assert await coordinator.async_save_control_now()
        assert coordinator._save_due == pytest.approx(now + FACTOR_SAVE_DELAY_S)
    await coordinator.async_save_now()
    coordinator._main_owed = (True, True)  # the copy says held: the hold changed
    coordinator.schedule_control_save()
    assert coordinator._save_due == pytest.approx(now)


@pytest.mark.parametrize("polling", [False, True])
async def test_the_quick_path_follows_its_own_clock(
    hass: HomeAssistant, freezer, polling: bool
) -> None:
    """PB-62: the monitor's 30-s refresh ran only while an entity listened and polling was
    enabled for the entry; with polling disabled the monitor — and V6's failure window — ran
    only on state changes. It runs on the plugin's own clock either way, once per tick (not
    twice with polling on); after the unload it stops (negative)."""
    from homeassistant.util import dt as dt_util

    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    options = entry_for(boiler).options
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options, pref_disable_polling=not polling
    )
    await setup(hass, entry)
    coordinator = entry.runtime_data
    refreshes: list[float] = []
    real = coordinator._async_update_data

    async def counted() -> Any:
        refreshes.append(dt_util.utcnow().timestamp())
        return await real()

    coordinator._async_update_data = counted
    for _ in range(3):
        freezer.tick(30)
        async_fire_time_changed(hass, dt_util.utcnow())
        await hass.async_block_till_done()
    assert len(refreshes) == 3
    assert coordinator.data.now == pytest.approx(dt_util.utcnow().timestamp())
    assert await hass.config_entries.async_unload(entry.entry_id)
    refreshes.clear()
    freezer.tick(60)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()
    assert refreshes == []


async def test_a_dev_builds_alive_at_is_read_once(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-95's migration: a build that kept ``alive_at`` in the entry's main store has no
    last-run record; its ``alive_at`` and downtimes are read from the main store once — the
    record is written from then on, the main store no longer carries it."""
    entry = await _restart(
        hass,
        hass_storage,
        freezer,
        monkeypatch,
        main={
            "monitoring_since": STOPPED - 30 * DAY,
            "alive_at": STOPPED,
            "down": [[STOPPED - 2 * DAY, STOPPED - 2 * DAY + 600]],
        },
    )
    now = RESTART.timestamp()
    coordinator = entry.runtime_data
    assert coordinator.down == [(STOPPED - 2 * DAY, STOPPED - 2 * DAY + 600), (STOPPED, now)]
    assert coordinator.history.signals[Signal.FLAME].value_at(STOPPED + 60) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert hass_storage[_alive_key(entry)]["data"]["alive_at"] == pytest.approx(now)
    assert "alive_at" not in hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]


@pytest.mark.parametrize(
    "alive",
    [None, {"data": None}, {"data": {"alive_at": "yesterday", "down": []}}, {"data": [1, 2]}],
    ids=["missing", "corrupt", "non_numeric", "not_a_mapping"],
)
async def test_an_unreadable_last_run_record_is_never_no_downtime(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer,
    monkeypatch: pytest.MonkeyPatch,
    alive: dict[str, Any] | None,
) -> None:
    """P-95's negative: without a readable last-run record the downtime is not taken as none —
    it is unknown back to the latest moment the main store shows the plugin running, here the
    end of the day it summarised last (midnight). The recorder's rows since are dropped, the
    way a crash's are: unknown rather than wrong."""
    first = {"monitoring_since": STOPPED - 30 * DAY}
    entry = await _restart(hass, hass_storage, freezer, monkeypatch, alive=alive, main=first)
    coordinator = entry.runtime_data
    kept = _stored_days(MIDNIGHT - DAY, 1, _settings_of(entry))
    now = RESTART.timestamp()
    # The main store holds no day here: its only sign of running is the monitoring start, a
    # month back, so the whole rolling history is unknown — never "no downtime".
    assert coordinator.down == [(now - 8 * DAY, now)]
    assert coordinator.history.signals[Signal.FLAME].value_at(STOPPED - 60) is None
    assert await hass.config_entries.async_unload(entry.entry_id)
    # With a day summarised up to midnight in the main store, the downtime starts there.
    hass_storage.pop(_alive_key(entry), None)
    if alive is not None:
        hass_storage[_alive_key(entry)] = {"version": 1, "key": _alive_key(entry)} | alive
    main = hass_storage[f"{DOMAIN}.{entry.entry_id}"]["data"]
    main["daily"] = kept
    main.pop("down", None)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    now = datetime.now(UTC).timestamp()
    assert coordinator.down == [(MIDNIGHT, now)]
    series = coordinator.history.signals[Signal.FLAME]
    assert series.value_at(MIDNIGHT - 60) is False  # before it: known
    assert series.value_at(STOPPED - 60) is None  # the rows after it: dropped


@pytest.mark.parametrize(("created_days_ago", "unknown_s"), [(0.001, 86.4), (30, 8 * DAY)])
async def test_without_any_store_the_downtime_counts_from_the_entrys_creation(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    freezer,
    monkeypatch: pytest.MonkeyPatch,
    created_days_ago: float,
    unknown_s: float,
) -> None:
    """P-95's negative: neither the last-run record nor the main store — a first run, or both
    lost. The downtime counts from the entry's creation, never further back than the rolling
    history: a new entry marks only the moments since it was created, and the recorder's
    history from before stays whole; an old one whose stores are lost has the whole rolling
    history unknown."""
    created = RESTART - timedelta(days=created_days_ago)
    entry = await _restart(hass, hass_storage, freezer, monkeypatch, created=created)
    now = RESTART.timestamp()
    coordinator = entry.runtime_data
    assert coordinator.down == [(pytest.approx(now - unknown_s), now)]
    series = coordinator.history.signals[Signal.FLAME]
    assert series.value_at(STOPPED - 60) is (True if created_days_ago < 1 else None)


async def test_the_last_run_record_has_a_store_of_its_own(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-95: after a crash the downtime starts at the last-run record's last write, so it is
    written every ten minutes (provisional, K4) — to a small store of its own. Sixty minutes of
    running with nothing else changing write it six times, and the entry's main store, a year
    of day summaries in it, not at all: many installations run on SD cards or eMMC."""
    start = datetime(2026, 1, 10, 12, tzinfo=UTC)
    freezer.move_to(start)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert coordinator._alive_store.key == _alive_key(entry)
    assert coordinator._alive_store._atomic_writes
    assert _alive_key(entry) not in hass_storage  # nothing yet: written every ten minutes
    for _ in range(5):  # the start's own save of the main store goes out first, as before
        freezer.tick(60)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    writes = {"main": 0, "alive": 0}

    def spy(store: Any, name: str) -> None:
        write = type(store)._async_write_data

        async def counted(data: Any) -> None:
            writes[name] += 1
            await write(store, data)

        store._async_write_data = counted

    spy(coordinator._store, "main")
    spy(coordinator._alive_store, "alive")
    for _ in range(60):
        freezer.tick(60)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()
    assert writes == {"main": 0, "alive": 6}
    record = hass_storage[_alive_key(entry)]["data"]
    assert record["alive_at"] == pytest.approx(start.timestamp() + 60 * 60)


async def test_analysis_during_backfill_keeps_no_partial_days(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-53: an analysis copies the history while the recorder is still being read; the
    backfill ends while it runs. Its copy holds only the hours since setup: its days are not
    kept, for a year, as whole ones. The next analysis, with the history back, keeps them."""
    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module

    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    release = asyncio.Event()

    async def slow_backfill(self: Any, now: float) -> None:
        await release.wait()

    monkeypatch.setattr(coordinator_module.SmartBoilerCoordinator, "_async_backfill", slow_backfill)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry, background=False)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(days=1))  # a whole day since setup: a day to summarise
    boiler.set(Signal.FLAME, True)
    await hass.async_block_till_done()
    real = coordinator_module.analyse

    def backfill_ends_meanwhile(*args: Any, **kwargs: Any) -> Any:
        coordinator._history_back = True  # the recorder's history arrives while this runs
        return real(*args, **kwargs)

    monkeypatch.setattr(coordinator_module, "analyse", backfill_ends_meanwhile)
    await analyse_now(coordinator)
    assert coordinator.analysis is not None
    assert coordinator.analysis.new_days  # it did summarise the day …
    assert coordinator.daily == {}  # … and kept none of it
    monkeypatch.setattr(coordinator_module, "analyse", real)
    await analyse_now(coordinator)
    assert coordinator.daily  # the history was back when this one copied it
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)


@pytest.mark.parametrize(
    ("change", "kept"),
    [
        ({"parameters": {"boiler_min_power": 4.0, "boiler_max_power": 25.0,
                         "water_volume": 120.0}}, True),
        ({"signals": "add pressure"}, True),
        ({"monitor": {"short_burn_min": 5}}, False),
    ],
)  # fmt: skip
async def test_an_unrelated_option_keeps_the_stored_days(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer, change: dict, kept: bool
) -> None:
    """P-87: any option change made every stored day stop counting — the verdict shrank to what
    the recorder still held. Only what a day's summary depends on does that now: the water
    volume or a pressure signal keep the days; the short-burn limit does not."""
    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.RETURN: 28.0})
    boiler.set(Signal.PRESSURE, 1.5)
    entry = entry_for(boiler)
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {
            "monitoring_since": now - 30 * DAY,
            "daily": _stored_days(now - 20 * DAY, 20, _settings_of(entry)),
        },
    }
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    # The stored days decide (short burns found, "not changed yet" — answer K).
    assert entry.runtime_data.analysis.verdict.verdict.value == "not_worth_it"
    if change.get("signals") == "add pressure":
        signals = dict(entry.options["signals"]) | {"pressure": boiler.entity(Signal.PRESSURE)}
        change = {"signals": signals}
    before = entry.runtime_data
    hass.config_entries.async_update_entry(entry, options={**entry.options, **change})
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data
    assert coordinator is not before  # reloaded
    assert (coordinator.settings_key == before.settings_key) is kept
    assert len(coordinator.daily) == 20  # kept in the store either way
    verdict = coordinator.analysis.verdict.verdict.value
    assert verdict == ("not_worth_it" if kept else "not_enough_data")


async def test_a_renamed_signal_keeps_the_stored_days(
    hass: HomeAssistant, hass_storage: dict[str, Any], freezer
) -> None:
    """PB-17: the day-summary key held the entity IDs, so a rename the plugin follows (P-19)
    dropped every stored day from the verdict. It holds the registry entry now: the flame
    entity renamed, the days still count; a different entity mapped instead does not keep
    them (negative)."""
    from custom_components.vtherm_smart_boiler.config import EntryConfig
    from custom_components.vtherm_smart_boiler.coordinator import summary_settings
    from custom_components.vtherm_smart_boiler.core.daily import settings_key

    freezer.move_to(datetime(2026, 2, 1, tzinfo=UTC))
    now = datetime(2026, 2, 1, tzinfo=UTC).timestamp()
    registry = er.async_get(hass)
    flame = registry.async_get_or_create(
        "binary_sensor", "fake_boiler", "flame", suggested_object_id="fake_boiler_flame"
    )
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.RETURN))
    assert flame.entity_id == boiler.entity(Signal.FLAME)
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0, Signal.RETURN: 28.0})
    entry = entry_for(boiler)

    def source(entity: str) -> str:
        return flame.id if entity == flame.entity_id else entity

    stored = settings_key(summary_settings(EntryConfig.from_options(entry.options), source))
    assert stored != _settings_of(entry)  # keyed on the registry entry, not the entity ID
    key = f"{DOMAIN}.{entry.entry_id}"
    hass_storage[key] = {
        "version": 1,
        "key": key,
        "data": {
            "monitoring_since": now - 30 * DAY,
            "daily": _stored_days(now - 20 * DAY, 20, stored),
        },
    }
    await setup(hass, entry)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.settings_key == stored
    registry.async_update_entity(flame.entity_id, new_entity_id="binary_sensor.burner")
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.options["signals"]["flame"] == "binary_sensor.burner"
    hass.states.async_set("binary_sensor.burner", "off")
    coordinator = entry.runtime_data
    assert coordinator.settings_key == stored
    await analyse_now(coordinator)
    assert coordinator.analysis.verdict.verdict.value == "not_worth_it"
    # Negative: another entity in its place is another source — the days no longer count.
    signals = dict(entry.options["signals"]) | {"flame": "binary_sensor.other_flame"}
    hass.config_entries.async_update_entry(entry, options={**entry.options, "signals": signals})
    await hass.async_block_till_done(wait_background_tasks=True)
    assert entry.runtime_data.settings_key != stored


@pytest.mark.parametrize(("meter", "kept"), [(True, True), (False, False)])
def test_gas_rates_shape_the_days_only_without_a_meter(
    hass: HomeAssistant, meter: bool, kept: bool
) -> None:
    """PB-17: with a gas meter the gas comes from it, so a gas rate entered keeps the stored
    days; without one the rates give the gas, and a changed rate does not (negative)."""
    signals = (Signal.FLAME, Signal.GAS_METER) if meter else (Signal.FLAME, Signal.MODULATION)
    entry = entry_for(FakeBoiler(hass, signals))
    rates = {"gas_at_min_power": 0.4, "gas_at_max_power": 2.5}
    changed = MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={**entry.options, "parameters": {**entry.options["parameters"], **rates}},
    )
    assert (_settings_of(changed) == _settings_of(entry)) is kept


async def test_burns_are_classified_per_analysis(
    hass: HomeAssistant, freezer, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P-80: the quick path classified the last day's burns at every refresh — every few
    seconds, a day of burns each time. The starts and ignition alarms use the analysis' burns
    now (up to five minutes old); before the first analysis they cannot be judged."""
    from dataclasses import replace

    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module
    from custom_components.vtherm_smart_boiler.core import cycles
    from custom_components.vtherm_smart_boiler.core.alarms import HELD, UNKNOWN_INPUT, AlarmKind

    freezer.move_to(datetime(2026, 1, 10, 6, tzinfo=UTC))
    release = asyncio.Event()

    async def slow_backfill(self: Any, now: float) -> None:
        await release.wait()

    monkeypatch.setattr(coordinator_module.SmartBoilerCoordinator, "_async_backfill", slow_backfill)
    calls: list[int] = []
    real = cycles.classify_burn

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(cycles, "classify_burn", counted)
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    # Declared without hot water: every burn heats.
    declared = {**entry_for(boiler).options, "boiler": {"class": "read_only", "dhw": "none"}}
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=declared)
    await setup(hass, entry, background=False)
    coordinator = entry.runtime_data
    for _ in range(20):  # three-minute burns, one every four minutes: fifteen an hour
        freezer.tick(60)
        boiler.set(Signal.FLAME, True)
        await hass.async_block_till_done()
        freezer.tick(180)
        boiler.set(Signal.FLAME, False)
        await hass.async_block_till_done()
    # The clock's analysis may still run in the background (it classifies burns too): done
    # before the test takes its own count (Z1).
    await analysis_idle(coordinator)
    coordinator.analysis = None  # as before the first analysis
    coordinator._alarms = {}
    calls.clear()
    now = dt_util.utcnow().timestamp()
    assert coordinator.heating_starts(now) is None  # the comfort correction's rule 3: unknown
    await coordinator.async_refresh()
    assert calls == []  # the quick path classifies nothing
    starts = coordinator.data.alarms[AlarmKind.FREQUENT_STARTS]
    assert starts.active is None  # no analysis yet: not judged
    assert starts.reason == UNKNOWN_INPUT
    await analyse_now(coordinator)
    assert calls  # the analysis did
    count = len(calls)
    await coordinator.async_refresh()
    assert len(calls) == count
    starts = coordinator.data.alarms[AlarmKind.FREQUENT_STARTS]
    assert starts.active is True
    assert starts.value == 15  # the starts of the last hour, from the analysis' burns
    seen = coordinator.heating_starts(dt_util.utcnow().timestamp())
    assert seen is not None
    assert len(seen) == 20  # rule 3's two hours hold every burn
    # An analysis that has stopped for three runs judges nothing: the alarm holds (S-16).
    now = dt_util.utcnow().timestamp()
    coordinator.analysis = replace(coordinator.analysis, at=now - 3 * 300 - 1)
    assert coordinator.heating_starts(now) is None  # stopped: rule 3 does not judge
    await coordinator.async_refresh()
    starts = coordinator.data.alarms[AlarmKind.FREQUENT_STARTS]
    assert (starts.active, starts.reason) == (True, HELD)
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_trends_and_the_outdoor_check_age_with_the_analysis(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """PB-18: the trend alarms and the outdoor check came from the last successful analysis
    with no age — an analysis failing at every run left them at their last state for good.
    Older than three runs, each trend is not judged: it holds for an hour after that
    analysis, then is unknown; the outdoor check likewise; the failing analysis is shown."""
    from dataclasses import replace

    from homeassistant.util import dt as dt_util

    from custom_components.vtherm_smart_boiler import coordinator as coordinator_module
    from custom_components.vtherm_smart_boiler.core.alarms import (
        HELD,
        UNKNOWN_INPUT,
        Alarm,
        AlarmKind,
    )
    from custom_components.vtherm_smart_boiler.core.signal_check import (
        OutdoorCheck,
        OutdoorStatus,
    )

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    now = dt_util.utcnow().timestamp()
    assert coordinator.analysis is not None
    kind = AlarmKind.PRESSURE_FALLING
    stuck = OutdoorCheck(OutdoorStatus.STUCK)

    def analysed(age: float) -> None:
        at = now - age
        trend = Alarm(kind, True, limit=0.2, known_at=at)
        coordinator.analysis = replace(
            coordinator.analysis, at=at, trends={kind: trend}, outdoor=stuck
        )

    analysed(0)
    assert coordinator.trends(now)[kind].active is True
    assert coordinator.outdoor_check(now) is stuck
    analysed(3 * 300 + 1)  # stopped: not judged, held
    held = coordinator.trends(now)[kind]
    assert (held.active, held.reason) == (True, HELD)
    assert coordinator.outdoor_check(now) is stuck
    analysed(3600 + 1)  # an hour after it: unknown
    gone = coordinator.trends(now)[kind]
    assert (gone.active, gone.reason, gone.limit) == (None, UNKNOWN_INPUT, 0.2)
    assert coordinator.outdoor_check(now) is None
    # Negative: no analysis at all, nothing to show.
    coordinator.analysis = None
    assert coordinator.trends(now) == {}
    assert coordinator.outdoor_check(now) is None
    # The failing analysis is shown, and no longer once it works.
    assert coordinator.analysis_failing is False

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise ValueError("a data-dependent failure")

    real = coordinator_module.analyse
    monkeypatch.setattr(coordinator_module, "analyse", broken)
    await analyse_now(coordinator)
    assert coordinator.analysis_failing is True
    monkeypatch.setattr(coordinator_module, "analyse", real)
    await analyse_now(coordinator)
    assert coordinator.analysis_failing is False


@pytest.mark.parametrize("reported", [True, False])
async def test_gas_used_with_the_burner_off_is_shown_apart(
    hass: HomeAssistant, freezer, reported: bool
) -> None:
    """S-31: the meter counts another consumer too (a cooker). What it counted while the burner
    was known off is left out of heating gas and shown apart, on gas per degree-day; with no
    meter reading there is nothing to show, and the attribute is absent."""
    freezer.move_to(datetime(2026, 1, 10, 12, tzinfo=UTC))
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.GAS_METER))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    meter = boiler.entity(Signal.GAS_METER)
    unit = {"unit_of_measurement": "m³", "device_class": "gas", "state_class": "total_increasing"}
    hass.states.async_set(meter, "100.0" if reported else "unavailable", unit)
    entry = entry_for(boiler)
    await setup(hass, entry)
    freezer.tick(timedelta(hours=1))
    hass.states.async_set(meter, "100.4" if reported else "unavailable", unit)  # the cooker
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=5))
    await analyse_now(entry.runtime_data)
    await hass.async_block_till_done()
    sensor = hass.states.get(entity_id(hass, entry, "sensor", "gas_per_degree_day"))
    assert sensor is not None
    if reported:
        assert sensor.attributes["other_gas"] == pytest.approx(0.4)
        week = entry.runtime_data.analysis.week
        assert week.gas is not None
        assert week.gas.amount == pytest.approx(0.0)  # none of it heating gas
    else:
        assert "other_gas" not in sensor.attributes


# --- Y4 ------------------------------------------------------------------------------------------


EN_TEXTS = json.loads(
    (
        Path(__file__).resolve().parents[2]
        / "custom_components/vtherm_smart_boiler/translations/en.json"
    ).read_text(encoding="utf-8")
)


async def test_invalid_options_name_their_reason_in_words(hass: HomeAssistant) -> None:
    """P-74: options this version cannot use stop the entry with the reason the options form
    shows, in Home Assistant's language — not a raw code; a code without a text stands for
    itself."""
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", options={"boiler": {"class": "no such class"}}
    )
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_ERROR
    assert entry.error_reason_translation_key == "invalid_options"
    placeholders = entry.error_reason_translation_placeholders or {}
    assert placeholders["reason"] == EN_TEXTS["options"]["error"]["invalid_boiler"]
    assert "invalid_boiler" not in (entry.reason or "")


async def test_gas_per_degree_day_has_no_unit_until_the_meter_has_one(
    hass: HomeAssistant,
) -> None:
    """P-75: while the meter's unit is not known, the sensor shows neither a unit nor a value —
    never an English "gas"; once the meter reports its unit, both."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.GAS_METER))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    meter = boiler.entity(Signal.GAS_METER)
    hass.states.async_set(meter, "1234.5", {})  # no unit reported yet
    entry = entry_for(boiler)
    await setup(hass, entry)
    await analyse_now(entry.runtime_data)
    sensor_id = entity_id(hass, entry, "sensor", "gas_per_degree_day")
    sensor = hass.states.get(sensor_id)
    assert sensor is not None
    assert "unit_of_measurement" not in sensor.attributes
    assert sensor.state == "unknown"
    hass.states.async_set(meter, "1234.5", {"unit_of_measurement": "m³"})
    await entry.runtime_data.async_refresh()
    await hass.async_block_till_done()
    sensor = hass.states.get(sensor_id)
    assert sensor is not None
    assert sensor.attributes["unit_of_measurement"] == "m³/K·d"
    assert "gas" not in sensor.attributes["unit_of_measurement"]


async def test_timestamps_are_iso(hass: HomeAssistant, zones: FakeZones) -> None:
    """P-78: every moment an attribute shows is ISO 8601 — the monitoring start, when an
    emitter factor was computed — never seconds since the epoch."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0})
    living = zones.add("living", hvac_action="heating", valve_open_percent=70, on_percent=0.7)
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    registry = er.async_get(hass)
    factor_id = entity_id(hass, entry, "sensor", "emitter_power_factor", living)
    registry.async_update_entity(factor_id, disabled_by=None)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    checked = 0
    for registered in er.async_entries_for_config_entry(registry, entry.entry_id):
        state = hass.states.get(registered.entity_id)
        if state is None:
            continue
        for name, value in state.attributes.items():
            if not (name.endswith("_at") or name.endswith("_since")):
                continue
            checked += 1
            assert value is None or isinstance(value, str), (registered.entity_id, name)
            if value is not None:
                assert datetime.fromisoformat(value).tzinfo is not None, (name, value)
    assert checked >= 2
    verdict = hass.states.get(entity_id(hass, entry, "sensor", "verdict"))
    assert verdict is not None
    assert isinstance(verdict.attributes["monitoring_since"], str)
    factor = hass.states.get(factor_id)
    assert factor is not None
    assert isinstance(factor.attributes["computed_at"], str)


async def test_change_report_and_forecast_snapshots_need_their_data(
    hass: HomeAssistant, forecasts: FakeForecasts
) -> None:
    """P-100: without degree-days — no outdoor sensor, no weather entity — no change report;
    without a weather entity no forecast snapshots. With them, both are created."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    bare = entry_for(boiler)
    await setup(hass, bare)
    registry = er.async_get(hass)
    for key in ("change_report", "forecast_snapshots"):
        assert registry.async_get_entity_id("sensor", DOMAIN, f"{bare.entry_id}_{key}") is None
    assert await hass.config_entries.async_unload(bare.entry_id)
    with_weather = entry_for(boiler, weather=WEATHER_ENTITY)
    await setup(hass, with_weather)
    for key in ("change_report", "forecast_snapshots"):
        found = registry.async_get_entity_id("sensor", DOMAIN, f"{with_weather.entry_id}_{key}")
        assert found is not None, key


def test_percent_sensors_use_unit_of_ratio() -> None:
    """P-102: the percentage unit Home Assistant asks for since 2026.7."""
    from homeassistant.const import UnitOfRatio

    from custom_components.vtherm_smart_boiler import sensor

    percents = [
        d for d in sensor.BOILER_SENSORS if d.native_unit_of_measurement == UnitOfRatio.PERCENTAGE
    ]
    assert {d.key for d in percents} == {"short_burn_share", "condensing_share", "change_report"}
    assert all(type(d.native_unit_of_measurement) is UnitOfRatio for d in percents)
    # Home Assistant keeps an ``_attr_`` class value under ``__attr_``.
    unit = getattr(sensor.EmitterFactorSensor, "__attr_native_unit_of_measurement")
    assert unit is UnitOfRatio.PERCENTAGE
    source = (Path(sensor.__file__)).read_text(encoding="utf-8")
    assert "PERCENTAGE," not in source.replace("UnitOfRatio.PERCENTAGE,", "")


async def test_a_critical_zone_is_named_by_its_circuits_number(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P-73: the critical zone's name gives the circuit as the options show it — its number —
    not its stored ID; its own states are translated."""
    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})
    zones.add("living")
    entry = entry_for(
        boiler, zones, circuits=[{"id": "main"}, {"id": "circuit_2", "control": "separate"}]
    )
    options = dict(entry.options)
    options["zones"] = [{"entity_id": zones.entities["living"], "circuit": "main"}]
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    await setup(hass, entry)
    second = hass.states.get(entity_id(hass, entry, "sensor", "critical_zone_circuit_2"))
    assert second is not None
    assert second.name.endswith("circuit 2")
    assert "circuit_2" not in second.name
    assert second.state == "no_active_zone"  # a state with its text (P-73)


def test_every_platform_takes_the_typed_entry() -> None:
    """P-101: the entry's runtime data is typed — every platform, the diagnostics' data aside,
    takes ``SmartBoilerConfigEntry``; the package's ``__init__`` imports it for typing only."""
    import ast
    import inspect

    from custom_components.vtherm_smart_boiler import (
        binary_sensor,
        button,
        coordinator,
        sensor,
        switch,
    )

    assert coordinator.SmartBoilerConfigEntry.__value__.__args__ == (  # type: ignore[attr-defined]
        coordinator.SmartBoilerCoordinator,
    )
    for module in (sensor, binary_sensor, switch, button):
        hints = inspect.get_annotations(module.async_setup_entry)
        assert hints["entry"] == "SmartBoilerConfigEntry", module.__name__
    package = Path(coordinator.__file__).parent / "__init__.py"
    tree = ast.parse(package.read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, ast.ImportFrom) and n.module == "coordinator"]
    assert top == []  # at module level only under TYPE_CHECKING, inside ``if``


def test_entity_classes_have_their_docstrings() -> None:
    """P-77: a class docstring after the attributes is none; each entity class has its own."""
    from custom_components.vtherm_smart_boiler import binary_sensor

    for cls in (
        binary_sensor.HotWaterSensor,
        binary_sensor.AlarmSensor,
        binary_sensor.OutdoorSensorProblem,
        binary_sensor.ConnectionSensor,
        binary_sensor.ControlAlarmSensor,
    ):
        assert cls.__doc__, cls.__name__


async def test_the_continuous_values_stay_in_the_diagnostics(
    hass: HomeAssistant, zones: FakeZones
) -> None:
    """P-72: an alarm's value and a zone's flow excess leave the attributes — a state row per
    change — and stay in the diagnostics."""
    from custom_components.vtherm_smart_boiler.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW, Signal.PRESSURE))
    boiler.set_many({Signal.FLAME: True, Signal.FLOW: 45.0, Signal.PRESSURE: 1.5})
    living = zones.add("living", hvac_action="heating", valve_open_percent=70, on_percent=0.7)
    entry = entry_for(boiler, zones)
    await setup(hass, entry)
    alarm = hass.states.get(entity_id(hass, entry, "binary_sensor", "alarm_pressure_high"))
    hot = hass.states.get(entity_id(hass, entry, "binary_sensor", "hot_water", living))
    assert alarm is not None
    assert hot is not None
    assert "value" not in alarm.attributes
    assert "excess" not in hot.attributes
    result = await async_get_config_entry_diagnostics(hass, entry)
    assert result["alarms"]["pressure_high"]["value"] == 1.5
    (zone,) = result["zones"].values()
    assert zone["hot_water"]["excess"] is not None


def test_text_attributes_stay_out_of_the_recorder() -> None:
    """P-39: the ``_text`` siblings are the codes again in words — kept out of the recorder, as
    the features' texts are."""
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature
    from custom_components.vtherm_smart_boiler.sensor import (
        BoilerSensor,
        ControlStateSensor,
        FeaturesSensor,
    )
    from custom_components.vtherm_smart_boiler.switch import ControlSwitch

    for cls, texts in (
        (BoilerSensor, {"reasons_text"}),
        (
            ControlStateSensor,
            {"reasons_text", "blockers_text", "blockers_waiting_text", "latched_by_text"},
        ),
        (ControlSwitch, {"blockers_text", "blocked_by_text"}),
        (FeaturesSensor, {f"{feature.value}_missing_text" for feature in Feature}),
    ):
        assert texts <= cls._unrecorded_attributes, cls.__name__


async def test_without_the_texts_the_codes_stand_for_themselves(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative (P-39, P-74): texts that cannot be loaded leave the codes shown as they are —
    never an error, never an empty text for a code."""
    from homeassistant.helpers import translation

    from custom_components.vtherm_smart_boiler import _async_options_error_text
    from custom_components.vtherm_smart_boiler.entity import coded_text

    boiler = FakeBoiler(hass, (Signal.FLAME, Signal.FLOW))
    boiler.set_many({Signal.FLAME: False, Signal.FLOW: 30.0})

    async def broken(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        raise RuntimeError("no translations")

    monkeypatch.setattr(translation, "async_get_translations", broken)
    entry = entry_for(boiler)
    await setup(hass, entry)
    coordinator = entry.runtime_data
    assert coordinator.texts == {}
    shown = coded_text(coordinator, "sensor", "control_state", "reasons", ("control_off", "x"))
    assert shown == "control_off, x"
    assert await _async_options_error_text(hass, "invalid_boiler") == "invalid_boiler"
    monkeypatch.undo()
    assert await _async_options_error_text(hass, "no_such_code") == "no_such_code"
