"""Forecast recording (FC0): snapshots from ``weather.get_forecasts`` kept in HA storage.

The only service the plugin calls in the monitor is ``weather.get_forecasts``, and only for the
forecast types the weather entity says it offers, while the entity is there and neither
unavailable nor unknown; each call is given ``FORECAST_CALL_TIMEOUT_S`` (P-55). Snapshots are
stored in weekly partitions, one storage file each: a save serialises and writes only its own
week, in the executor, from the snapshots captured when it was planned. At setup the stored
weeks are parsed in the executor, and only the current week stays in memory, the older ones as a
count (P-23). Weeks past the retention are removed, also those a restart no longer loads.
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .core.forecast import (
    DEFAULT_RETENTION_S,
    PARTITION_S,
    ForecastKind,
    ForecastPoint,
    ForecastSnapshot,
    ForecastStore,
    partition_of,
)
from .units import parse_number, temperature_to_celsius

_LOGGER = logging.getLogger(__name__)
STORAGE_VERSION = 1
SAVE_DELAY_S = 60
# How long one ``weather.get_forecasts`` call may take before its snapshot is given up
# (provisional, K4): a weather integration that hangs must not hold the recording.
FORECAST_CALL_TIMEOUT_S = 30.0
_NO_WEATHER = ("unavailable", "unknown")

# The forecast types a weather entity offers (Home Assistant's WeatherEntityFeature).
_FEATURE = {ForecastKind.DAILY: 1, ForecastKind.HOURLY: 2}
_WIND_TO_MS = {"m/s": 1.0, "km/h": 1 / 3.6, "mph": 0.44704, "kn": 0.514444, "ft/s": 0.3048}
_RAIN_TO_MM = {"mm": 1.0, "cm": 10.0, "in": 25.4}


def parse_forecast(items: Sequence[object], units: Mapping[str, Any]) -> tuple[ForecastPoint, ...]:
    """Forecast items of ``weather.get_forecasts`` in core units; unreadable items are skipped."""
    temperature_unit = units.get("temperature_unit")
    wind = _WIND_TO_MS.get(str(units.get("wind_speed_unit")))
    rain = _RAIN_TO_MM.get(str(units.get("precipitation_unit")))

    def temperature(raw: object) -> float | None:
        number = parse_number(raw)
        return None if number is None else temperature_to_celsius(number, temperature_unit)

    points: list[ForecastPoint] = []
    for item in items:
        if not isinstance(item, Mapping):
            continue
        moment = dt_util.parse_datetime(str(item.get("datetime", "")))
        if moment is None:
            continue
        wind_speed = parse_number(item.get("wind_speed"))
        precipitation = parse_number(item.get("precipitation"))
        points.append(
            ForecastPoint(
                moment.timestamp(),
                temperature(item.get("temperature")),
                temperature(item.get("templow")),
                parse_number(item.get("cloud_coverage")),
                None if wind_speed is None or wind is None else wind_speed * wind,
                None if precipitation is None or rain is None else precipitation * rain,
            )
        )
    return tuple(sorted(points, key=lambda p: p.t))


class ForecastRecorder:
    """Takes and stores forecast snapshots of one weather entity."""

    def __init__(self, hass: HomeAssistant, entry_id: str, weather_entity: str) -> None:
        self._hass = hass
        self._entry_id = entry_id
        self._weather = weather_entity
        self.store = ForecastStore()
        self._stores: dict[int, Store[dict[str, Any]]] = {}
        # The weeks changed since they were loaded, each with its snapshots as last captured:
        # what the flush at unload writes — the week may have left memory since (P-23).
        self._dirty: dict[int, tuple[ForecastSnapshot, ...]] = {}
        self.unsupported: set[ForecastKind] = set()

    def _storage(self, partition: int) -> Store[dict[str, Any]]:
        if partition not in self._stores:
            self._stores[partition] = Store(
                self._hass,
                STORAGE_VERSION,
                partition_key(self._entry_id, partition),
                serialize_in_event_loop=False,
            )
        return self._stores[partition]

    async def async_load(self, now: float) -> None:
        """Load the partitions still inside the retention — parsed in the executor, the current
        week in full and the older ones only as a count (P-23) — and remove the files of older
        ones."""
        first = partition_of(now - DEFAULT_RETENTION_S)
        current = partition_of(now)
        loaded: dict[int, Sequence[object]] = {}
        unreadable = 0
        for partition in range(first, current + 1):
            # Each week on its own: one that cannot be read (written by a later version, say)
            # costs that week, not the others or the entry's setup.
            try:
                data = await self._storage(partition).async_load()
            except Exception as err:
                _LOGGER.debug("Could not read stored forecast week %s: %r", partition, err)
                unreadable += 1
                continue
            if isinstance(data, dict) and isinstance(data.get("snapshots"), list):
                loaded[partition] = data["snapshots"]
        if unreadable:
            _LOGGER.warning("Skipped %s stored forecast weeks that could not be read", unreadable)
        # Parsed on a store of its own, which nothing else sees until it is ready; a snapshot
        # taken meanwhile (none at setup) is kept.
        fresh = ForecastStore(self.store.retention_s, self.store.horizon_points)
        skipped = await self._hass.async_add_executor_job(fresh.load, loaded, current)
        for snapshot in self.store.snapshots():
            fresh.add(snapshot)
        self.store = fresh
        if skipped:
            _LOGGER.warning("Skipped %s unreadable stored forecast snapshots", skipped)
        await self._hass.async_add_executor_job(
            remove_partition_files, Path(self._hass.config.path(".storage")), self._entry_id, first
        )

    async def async_take(self, now: float) -> int:
        """Take one snapshot of every supported forecast type; returns how many were stored.
        Nothing is asked while the weather entity is missing, unavailable or unknown (P-55)."""
        state = self._hass.states.get(self._weather)
        if state is None or state.state in _NO_WEATHER:
            _LOGGER.debug("No forecast asked for: %s is not available", self._weather)
            await self._async_prune(now)
            return 0
        units = state.attributes
        features = units.get("supported_features")
        taken = 0
        for kind in (ForecastKind.HOURLY, ForecastKind.DAILY):
            if isinstance(features, int) and not features & _FEATURE[kind]:
                self.unsupported.add(kind)  # the entity does not offer it: never asked for
            else:
                self.unsupported.discard(kind)
            if kind in self.unsupported:
                continue
            try:
                async with asyncio.timeout(FORECAST_CALL_TIMEOUT_S):
                    response = await self._hass.services.async_call(
                        "weather",
                        "get_forecasts",
                        {"entity_id": self._weather, "type": kind.value},
                        blocking=True,
                        return_response=True,
                    )
            except TimeoutError:
                _LOGGER.debug(
                    "No %s forecast from %s within %s s",
                    kind,
                    self._weather,
                    FORECAST_CALL_TIMEOUT_S,
                )
                continue
            except HomeAssistantError as err:
                _LOGGER.debug("No %s forecast from %s: %s", kind, self._weather, err)
                continue
            answer = (response or {}).get(self._weather)
            items = answer.get("forecast") if isinstance(answer, dict) else None
            if not isinstance(items, list) or not items:
                continue
            snapshot = ForecastSnapshot(now, kind, parse_forecast(items, units))
            if self.store.add(snapshot) is None:
                # The clock went back past the week in memory: that week is not rewritten.
                _LOGGER.debug("A forecast snapshot of an earlier week is not stored")
                continue
            taken += 1
        if taken:
            self._schedule_save(partition_of(now))
        await self._async_prune(now)
        return taken

    def _schedule_save(self, partition: int) -> None:
        # Captured now, in the event loop: the save runs in the executor and must not read the
        # store while the loop changes it. A later snapshot plans a save of its own.
        snapshots = tuple(self.store.in_partition(partition))

        def data() -> dict[str, Any]:
            return {"snapshots": [snapshot.to_dict() for snapshot in snapshots]}

        self._dirty[partition] = snapshots
        self._storage(partition).async_delay_save(data, SAVE_DELAY_S)

    async def _async_prune(self, now: float) -> None:
        self.store.prune(now)
        cutoff = partition_of(now - DEFAULT_RETENTION_S - PARTITION_S)
        for partition in [p for p in self._stores if p < cutoff]:
            # P-56: removed for good — the flush at unload must not write it back, empty.
            self._dirty.pop(partition, None)
            await self._stores.pop(partition).async_remove()

    async def async_flush(self) -> None:
        """Write the partitions changed since they were loaded now (on unload), each with its
        snapshots as last captured."""
        for partition, snapshots in sorted(self._dirty.items()):
            await self._storage(partition).async_save(
                {"snapshots": [snapshot.to_dict() for snapshot in snapshots]}
            )
        self._dirty.clear()


def partition_key(entry_id: str, partition: int) -> str:
    return f"{DOMAIN}.{entry_id}.forecast_{partition}"


def remove_partition_files(storage: Path, entry_id: str, before: int | None = None) -> None:
    """Remove an entry's forecast partition files — those older than ``before``, or all.
    Blocking: run it in the executor."""
    pattern = re.compile(re.escape(f"{DOMAIN}.{entry_id}.forecast_") + r"(-?\d+)")
    if not storage.is_dir():
        return
    for path in storage.iterdir():
        match = pattern.fullmatch(path.name)
        if match and (before is None or int(match.group(1)) < before):
            path.unlink(missing_ok=True)
