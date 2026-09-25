"""Forecast recording: what is stored, when, and what is cleaned up."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.forecast import (
    DEFAULT_RETENTION_S,
    PARTITION_S,
    ForecastKind,
    partition_of,
)
from custom_components.vtherm_smart_boiler.forecasts import ForecastRecorder

from .harness import WEATHER_ENTITY, FakeForecasts

NOW = datetime(2026, 1, 20, 12, tzinfo=UTC).timestamp()


def _key(partition: int) -> str:
    return f"{DOMAIN}.entry.forecast_{partition}"


def _write(storage: Path, names: list[str]) -> None:
    storage.mkdir(parents=True, exist_ok=True)
    for name in names:
        (storage / name).write_text(json.dumps({"version": 1, "key": name, "data": {}}))


def _present(storage: Path, names: list[str]) -> list[bool]:
    return [(storage / name).exists() for name in names]


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
    entry = MockConfigEntry(domain=DOMAIN, entry_id="gone", options={})
    await async_remove_entry(hass, entry)
    await hass.async_block_till_done()
    assert await hass.async_add_executor_job(_present, storage, names) == [False]
    assert f"{DOMAIN}.gone" not in hass_storage


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
