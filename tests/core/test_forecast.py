"""Forecast snapshots: trimming, compact storage, retention, partitions and errors."""

from __future__ import annotations

import json

import pytest

from custom_components.vtherm_smart_boiler.core.forecast import (
    DAY,
    HOUR,
    PARTITION_S,
    ErrorStats,
    ForecastKind,
    ForecastPoint,
    ForecastSnapshot,
    ForecastStore,
    forecast_errors,
    partition_of,
)
from custom_components.vtherm_smart_boiler.core.series import Series

T0 = 1000 * DAY


def hourly(taken_at: float, temps: list[float | None], first: float | None = None):
    first = T0 if first is None else first
    points = tuple(
        ForecastPoint(first + i * HOUR, temperature=t, cloud_coverage=50.0)
        for i, t in enumerate(temps)
    )
    return ForecastSnapshot(taken_at, ForecastKind.HOURLY, points)


def test_trim_drops_past_steps_and_limits_the_horizon() -> None:
    snapshot = hourly(T0 + 90 * 60, [float(i) for i in range(60)])
    trimmed = snapshot.trimmed(48)
    assert trimmed.points[0].t == T0 + HOUR  # the step holding taken_at
    assert len(trimmed.points) == 48


def test_compact_round_trip_through_json() -> None:
    snapshot = ForecastSnapshot(
        T0,
        ForecastKind.DAILY,
        (
            ForecastPoint(T0, 5.04, -1.26, None, 3.33, 0.0),
            ForecastPoint(T0 + DAY, None, None, None, None, None),
        ),
    )
    data = json.loads(json.dumps(snapshot.to_dict()))
    assert "cloud" not in data  # a field never reported is not stored
    restored = ForecastSnapshot.from_dict(data)
    assert restored.kind is ForecastKind.DAILY
    assert restored.points[0] == ForecastPoint(T0, 5.0, -1.3, None, 3.3, 0.0)
    assert restored.points[1] == ForecastPoint(T0 + DAY)


def test_store_trims_sorts_and_prunes() -> None:
    store = ForecastStore()
    store.add(hourly(T0 + 2 * DAY, [1.0] * 60))
    store.add(hourly(T0, [1.0] * 60))
    assert [s.taken_at for s in store.snapshots()] == [T0, T0 + 2 * DAY]
    assert all(len(s.points) <= 48 for s in store.snapshots())
    assert store.snapshots(ForecastKind.DAILY) == []
    assert len(store.snapshots(since=T0 + DAY)) == 1
    assert store.prune(now=T0 + 91 * DAY) == 1
    assert [s.taken_at for s in store.snapshots()] == [T0 + 2 * DAY]


def test_partitions_round_trip_and_skip_broken_entries() -> None:
    store = ForecastStore()
    store.add(hourly(T0, [1.0, 2.0]))
    store.add(hourly(T0 + PARTITION_S, [3.0], first=T0 + PARTITION_S))
    parts = store.partitions()
    assert sorted(parts) == [partition_of(T0), partition_of(T0) + 1]
    restored = ForecastStore()
    skipped = restored.load([*parts.values(), [{"broken": True}]])
    assert skipped == 1
    assert [s.taken_at for s in restored.snapshots()] == [T0, T0 + PARTITION_S]
    assert restored.snapshots()[0].points[1].temperature == 2.0


def test_one_partition_alone() -> None:
    """P31: a save needs one week's snapshots, not every week's serialised to pick one."""
    store = ForecastStore()
    store.add(hourly(T0, [1.0]))
    store.add(hourly(T0 + PARTITION_S, [3.0], first=T0 + PARTITION_S))
    store.add(hourly(T0 + PARTITION_S + HOUR, [4.0], first=T0 + PARTITION_S + HOUR))
    week = store.in_partition(partition_of(T0) + 1)
    assert [s.taken_at for s in week] == [T0 + PARTITION_S, T0 + PARTITION_S + HOUR]
    assert store.in_partition(partition_of(T0) + 5) == []


def test_forecast_errors_by_horizon() -> None:
    observed = Series([(T0, 0.0)])  # it stayed at 0 °C
    snapshots = [
        hourly(T0, [1.0, 1.0, 1.0, 2.0]),  # 0 h, 1 h, 2 h, 3 h ahead
        hourly(T0, [None, -1.0, 0.0, 4.0]),
    ]
    errors = forecast_errors(snapshots, observed, horizons_h=(1, 3))
    assert errors[1] == ErrorStats(2, pytest.approx(0.0), pytest.approx(1.0))
    assert errors[3] == ErrorStats(2, pytest.approx(3.0), pytest.approx(3.0))


def test_forecast_errors_need_observations() -> None:
    assert forecast_errors([hourly(T0, [1.0, 1.0])], Series[float]()) == {}
