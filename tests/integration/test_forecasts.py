"""Forecast recording: what is stored, when, and what is cleaned up."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.forecast import (
    DEFAULT_RETENTION_S,
    PARTITION_S,
    ForecastKind,
    ForecastPoint,
    ForecastSnapshot,
    ForecastStore,
    partition_of,
)
from custom_components.vtherm_smart_boiler.forecasts import ForecastRecorder, partition_key

from .harness import WEATHER_ENTITY, FakeForecasts, canned_forecast

NOW = datetime(2026, 1, 20, 12, tzinfo=UTC).timestamp()


def _key(partition: int) -> str:
    return f"{DOMAIN}.entry.forecast_{partition}"


def _write(storage: Path, names: list[str]) -> None:
    storage.mkdir(parents=True, exist_ok=True)
    for name in names:
        (storage / name).write_text(json.dumps({"version": 1, "key": name, "data": {}}))


def _present(storage: Path, names: list[str]) -> list[bool]:
    return [(storage / name).exists() for name in names]


async def test_the_files_a_test_writes_stay_in_its_own_directory(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Z1 (the V1 report): Home Assistant's configuration directory is each test's own, under
    its ``tmp_path`` in ``.tmp/`` — the files these tests write, and those the plugin removes,
    never touch the shared test configuration inside ``.venv``."""
    assert Path(hass.config.config_dir).is_relative_to(tmp_path)
    assert Path(hass.config.path(".storage")).is_relative_to(tmp_path)


async def test_a_save_writes_only_the_current_week(
    hass: HomeAssistant, hass_storage: dict[str, Any], forecasts: FakeForecasts
) -> None:
    """P31: the other weeks are neither serialised nor written again."""
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    await recorder.async_take(NOW - PARTITION_S)
    await recorder.async_take(NOW)
    await recorder.async_flush()
    this_week = hass_storage[_key(partition_of(NOW))]["data"]["snapshots"]
    assert {s["at"] for s in this_week} == {NOW}
    hass_storage.pop(_key(partition_of(NOW) - 1))
    await recorder.async_take(NOW + 3600)
    await recorder.async_flush()
    assert _key(partition_of(NOW) - 1) not in hass_storage  # last week not written again


async def test_weeks_past_the_retention_are_removed_after_a_restart(
    hass: HomeAssistant, forecasts: FakeForecasts
) -> None:
    """P31: a restart loads only the weeks within the retention; older files must not stay
    behind for ever."""
    storage = Path(hass.config.path(".storage"))
    old = partition_of(NOW - DEFAULT_RETENTION_S) - 3
    names = [_key(old), _key(partition_of(NOW)), f"{DOMAIN}.another.forecast_{old}"]
    await hass.async_add_executor_job(_write, storage, names)
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    await recorder.async_load(NOW)
    await hass.async_block_till_done()
    # The old week goes; this week stays, and another entry's files are its own.
    assert await hass.async_add_executor_job(_present, storage, names) == [False, True, True]


async def test_an_unsupported_forecast_is_known_from_the_entity(hass: HomeAssistant) -> None:
    """P96: a forecast type the weather entity does not offer is skipped by its features, not
    by the English text of an exception."""
    calls: list[str] = []

    async def handle(call: ServiceCall) -> dict[str, Any]:
        calls.append(call.data["type"])
        raise HomeAssistantError("Nie obsługuje")  # any language

    hass.services.async_register(
        "weather", "get_forecasts", handle, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(WEATHER_ENTITY, "cloudy", {"supported_features": 1})  # daily only
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    await recorder.async_take(NOW)
    await recorder.async_take(NOW + 1800)
    assert calls == ["daily", "daily"]  # hourly never asked for
    assert recorder.unsupported == {ForecastKind.HOURLY}


async def test_removing_the_entry_removes_its_files(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler import async_remove_entry

    storage = Path(hass.config.path(".storage"))
    names = [f"{DOMAIN}.gone.forecast_{partition_of(NOW)}"]
    await hass.async_add_executor_job(_write, storage, names)
    hass_storage[f"{DOMAIN}.gone"] = {"version": 1, "key": f"{DOMAIN}.gone", "data": {}}
    # P-95: the last-run record goes with the other stores.
    alive = f"{DOMAIN}.gone.alive"
    hass_storage[alive] = {"version": 1, "key": alive, "data": {"alive_at": NOW, "down": []}}
    entry = MockConfigEntry(domain=DOMAIN, entry_id="gone", options={})
    await async_remove_entry(hass, entry)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(_present, storage, names) == [False]
    assert f"{DOMAIN}.gone" not in hass_storage
    assert alive not in hass_storage


async def test_an_odd_forecast_answer_costs_a_snapshot_not_the_job(
    hass: HomeAssistant, hass_storage: dict[str, Any]
) -> None:
    """A weather integration answering in another shape: what cannot be read is skipped, the
    rest is kept, and the recording goes on."""
    answers = iter(
        [
            {WEATHER_ENTITY: ["not", "an", "object"]},
            {
                WEATHER_ENTITY: {
                    "forecast": [
                        "junk",
                        {"datetime": "2026-01-21T12:00:00+00:00", "temperature": 5.0},
                    ]
                }
            },
        ]
    )

    async def handle(call: ServiceCall) -> dict[str, Any]:
        return next(answers)

    hass.services.async_register(
        "weather", "get_forecasts", handle, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(
        WEATHER_ENTITY, "cloudy", {"supported_features": 1, "temperature_unit": "°C"}
    )
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    assert await recorder.async_take(NOW) == 0
    assert await recorder.async_take(NOW + 1800) == 1
    await recorder.async_flush()
    (snapshot,) = hass_storage[_key(partition_of(NOW))]["data"]["snapshots"]
    assert snapshot["dt"] == [24 * 3600 - 1800]  # the one readable point, a day after NOW


async def test_pruned_forecast_partitions_are_not_recreated(
    hass: HomeAssistant, hass_storage: dict[str, Any], forecasts: FakeForecasts
) -> None:
    """P-56: a week pruned past the retention was left marked as changed, so the flush at
    unload wrote it back — an empty file, recreated at every unload. Pruned, it stays gone."""
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    old = NOW - DEFAULT_RETENTION_S - 3 * PARTITION_S
    await recorder.async_take(old)  # a week with a save pending
    await recorder.async_flush()
    assert _key(partition_of(old)) in hass_storage
    await recorder.async_take(old + 3600)  # changed again: its save pending once more
    await recorder.async_take(NOW)  # past the retention now: pruned and removed
    assert _key(partition_of(old)) not in hass_storage
    await recorder.async_flush()
    assert _key(partition_of(old)) not in hass_storage  # not written back
    assert _key(partition_of(NOW)) in hass_storage


async def test_a_flush_without_pruning_writes_the_changed_weeks(
    hass: HomeAssistant, hass_storage: dict[str, Any], forecasts: FakeForecasts
) -> None:
    """P-56's negative: a week within the retention, changed since the last save, is written
    at unload as before."""
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    await recorder.async_take(NOW - PARTITION_S)
    await recorder.async_take(NOW)
    await recorder.async_flush()
    assert _key(partition_of(NOW - PARTITION_S)) in hass_storage
    assert _key(partition_of(NOW)) in hass_storage


def _stored_week(partition: int, count: int) -> list[dict[str, Any]]:
    """A week of hourly snapshots, as a partition file keeps them."""
    start = partition * PARTITION_S
    step = PARTITION_S / count
    return [
        ForecastSnapshot(
            start + index * step,
            ForecastKind.HOURLY,
            tuple(
                ForecastPoint(start + index * step + hour * 3600.0, 5.0, None, 50.0, 3.0, 0.0)
                for hour in range(48)
            ),
        ).to_dict()
        for index in range(count)
    ]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_forecasts_load_off_the_event_loop(
    hass: HomeAssistant,
    hass_storage: dict[str, Any],
    forecasts: FakeForecasts,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """T-36 (P-23): 13 weeks of about 670 snapshots each in storage → setup → the stored weeks
    are parsed in the executor, not in the event loop; in memory stays the current week only,
    the older weeks as a count."""
    import threading

    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.vtherm_smart_boiler.core import forecast as core_forecast

    threads: list[bool] = []
    original = core_forecast.ForecastStore.load

    def load(store: ForecastStore, *args: Any, **kwargs: Any) -> int:
        threads.append(threading.get_ident() == hass.loop_thread_id)
        return original(store, *args, **kwargs)

    monkeypatch.setattr(core_forecast.ForecastStore, "load", load)
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", options={"weather": WEATHER_ENTITY, "signals": {}}
    )
    now = dt_util.utcnow().timestamp()
    current = partition_of(now)
    weeks = list(range(current - 12, current + 1))
    for week in weeks:
        key = partition_key(entry.entry_id, week)
        hass_storage[key] = {
            "version": 1,
            "key": key,
            "data": {"snapshots": _stored_week(week, 670)},
        }
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert threads == [False]  # once, and not in the event loop's thread
    recorder = entry.runtime_data.forecasts
    assert recorder is not None
    kept = {partition_of(s.taken_at) for s in recorder.store.snapshots()}
    assert kept == {current}  # the current week alone in memory
    within = sum(
        1
        for week in weeks
        for snapshot in hass_storage[partition_key(entry.entry_id, week)]["data"]["snapshots"]
        if snapshot["at"] >= now - DEFAULT_RETENTION_S
    )
    assert recorder.store.count() >= within  # the older weeks counted (and a new snapshot)
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_get_forecasts_is_skipped_while_the_weather_is_unavailable(
    hass: HomeAssistant, forecasts: FakeForecasts
) -> None:
    """P-55: no call while the weather entity is missing, unavailable or unknown — its
    snapshot is simply not taken; the call is made again once the entity is back."""
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    for state in ("unavailable", "unknown"):
        hass.states.async_set(WEATHER_ENTITY, state)
        assert await recorder.async_take(NOW) == 0
    hass.states.async_remove(WEATHER_ENTITY)
    assert await recorder.async_take(NOW) == 0
    assert forecasts.calls == []
    hass.states.async_set(WEATHER_ENTITY, "cloudy", {"temperature_unit": "°C"})
    assert await recorder.async_take(NOW) == 2  # back: hourly and daily
    assert len(forecasts.calls) == 2


async def test_get_forecasts_times_out_after_30_s(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """P-55: each call is given 30 s (provisional, K4); a weather integration that does not
    answer costs that snapshot — logged at debug level only — and the next forecast type is
    still asked for."""
    import asyncio
    import logging

    from custom_components.vtherm_smart_boiler import forecasts as module

    assert module.FORECAST_CALL_TIMEOUT_S == 30.0
    monkeypatch.setattr(module, "FORECAST_CALL_TIMEOUT_S", 0.05)
    asked: list[str] = []

    async def handle(call: ServiceCall) -> dict[str, Any]:
        asked.append(call.data["type"])
        if call.data["type"] == "hourly":
            await asyncio.Event().wait()  # never answers
        start = datetime.fromtimestamp(NOW, UTC)
        return {WEATHER_ENTITY: {"forecast": canned_forecast("daily", start, 7, 3.0)}}

    hass.services.async_register(
        "weather", "get_forecasts", handle, supports_response=SupportsResponse.ONLY
    )
    hass.states.async_set(WEATHER_ENTITY, "cloudy", {"temperature_unit": "°C"})
    recorder = ForecastRecorder(hass, "entry", WEATHER_ENTITY)
    with caplog.at_level(logging.DEBUG, logger=module.__name__):
        assert await recorder.async_take(NOW) == 1  # the daily one
    assert asked == ["hourly", "daily"]
    timed_out = [r for r in caplog.records if "hourly" in r.getMessage()]
    assert timed_out
    assert all(r.levelno == logging.DEBUG for r in timed_out)
