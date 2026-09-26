"""Setup, unload and reload; missing and stale data; replayed history through the entities."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
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


async def setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


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
    low = hass.states.get(entity_id(hass, entry, "binary_sensor", "alarm_pressure_low"))
    assert low is not None
    assert low.state == "off"
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
        (ControlStateSensor, {"reasons", "target", "heating_on", "unknown_zones"}),
        (ControlSetpointSensor, {"requested", "read_back", "last_change"}),
        (EmitterFactorSensor, {"computed_at", "output_w"}),
        (CriticalZoneSensor, {"demand", "deficit"}),
        (BoilerSensor, {"reasons", "temperature", "deficit", "contributions"}),
        (HotWaterSensor, {"excess"}),
        (AlarmSensor, {"value"}),
        (OutdoorSensorProblem, {"mean_difference"}),
    ):
        assert changing <= cls._unrecorded_attributes, cls.__name__


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
    await setup(hass, entry)  # does not wait for the recorder
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
    await setup(hass, entry)
    coordinator = entry.runtime_data
    freezer.tick(timedelta(days=1))  # a whole day since setup: a day to summarise
    boiler.set(Signal.FLAME, True)
    await hass.async_block_till_done()
    await coordinator.async_run_analysis()
    assert coordinator.analysis is not None
    assert coordinator.daily == {}  # nothing kept while the history is not back
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    await coordinator.async_run_analysis()
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
    """P66: a broken field is skipped, not the whole store; an unreadable start of monitoring
    starts it again, which keeps control off for another monitoring period."""
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
    """Stored data of another shape starts from the defaults, with a warning."""
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
    await old.async_run_analysis()
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
    assert entry.minor_version == 2
    assert entry.options["control"] == {"write_path": "entity"}


def _stored_days(start: float, count: int, settings: str) -> dict[str, dict[str, Any]]:
    """Days of a boiler cycling twice an hour, as the plugin stores them."""
    from custom_components.vtherm_smart_boiler.core.daily import DaySummary

    days = {}
    for d in range(count):
        begin = start + d * DAY
        day = DaySummary(
            begin, begin + DAY, DAY, 48, 48, 48, 8 * 3600.0, DAY,
            8 * 3600.0, 8 * 3600.0, DAY, DAY, True, 7.0, None, settings=settings,
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
    assert coordinator.analysis.verdict.verdict.value == "worth_it"  # all short burns
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
            begin, begin + DAY, DAY, 10, 10, 0, 6 * 3600.0, DAY, 0.0, 0.0, 0.0, 0.0, False,
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
    await coordinator.async_run_analysis()
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
    for _ in range(12):  # twelve 40-second burns
        freezer.tick(timedelta(minutes=30))
        boiler.set_many({Signal.DHW_ACTIVE: hot_water, Signal.FLAME: True})
        await hass.async_block_till_done()
        freezer.tick(timedelta(seconds=40))
        boiler.set_many({Signal.FLAME: False, Signal.DHW_ACTIVE: False})
        await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()
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
    await entry.runtime_data.async_refresh()
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
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", options={"signals": {}})
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
        step_s=60.0,
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
    await coordinator.async_run_analysis()
    await hass.async_block_till_done()
    verdict = hass.states.get(entity_id(hass, entry, "sensor", "verdict"))
    assert verdict is not None
    assert verdict.state == "worth_it"
    starts = hass.states.get(entity_id(hass, entry, "sensor", "starts_per_hour"))
    assert starts is not None
    assert float(starts.state) > 1.0
    assert forecasts.calls  # snapshots were taken


async def test_everything_stored_survives_a_restart(
    hass: HomeAssistant, hass_storage: dict[str, Any], zones: FakeZones
) -> None:
    """A restart loads what the last run stored and, stopped again, stores the same: the start
    of monitoring, the zones' factors, the measured building values and the day summaries."""
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
        0.0, 0.0, False, 8.5, None, 4.0, 60.0,
    )  # fmt: skip
    stored = {
        "monitoring_since": now - 10 * DAY,
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
