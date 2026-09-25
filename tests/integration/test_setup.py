"""Setup, unload and reload; missing and stale data; replayed history through the entities."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.signals import Signal
from sim.profiles import BOILERS, HOUSES, radiator_zones
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


def entity_id(hass: HomeAssistant, entry: MockConfigEntry, domain: str, key: str) -> str:
    registry = er.async_get(hass)
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
    hot = hass.states.get(entity_id(hass, entry, "binary_sensor", f"hot_water_{living}"))
    assert hot is not None
    assert hot.state == "on"
    factor = hass.states.get(entity_id(hass, entry, "sensor", f"emitter_power_factor_{living}"))
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
    hot_id = entity_id(hass, entry, "binary_sensor", f"hot_water_{living}")
    assert hass.states.get(hot_id).state == "on"
    freezer.tick(timedelta(hours=1))
    zones.set("living", hvac_action="heating", valve_open_percent=50)  # the zone stays fresh
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await entry.runtime_data.async_refresh()  # whatever the timers did under load
    await hass.async_block_till_done()
    state = hass.states.get(hot_id)
    assert (state.state == "off") is stale
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
