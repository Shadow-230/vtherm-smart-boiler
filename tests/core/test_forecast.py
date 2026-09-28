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
    week = partition_of(T0) * PARTITION_S
    store.add(hourly(week + 2 * DAY, [1.0] * 60))
    store.add(hourly(week, [1.0] * 60))
    assert [s.taken_at for s in store.snapshots()] == [week, week + 2 * DAY]
    assert all(len(s.points) <= 48 for s in store.snapshots())
    assert store.snapshots(ForecastKind.DAILY) == []
    assert len(store.snapshots(since=week + DAY)) == 1
    assert store.prune(now=week + 91 * DAY) == 1
    assert [s.taken_at for s in store.snapshots()] == [week + 2 * DAY]
    assert store.count() == 1


def test_only_the_current_week_is_kept_in_memory() -> None:
    """P-23: the snapshots of the week being written stay in memory; the older weeks only as a
    count — which is all this release uses — pruned with the retention as before."""
    store = ForecastStore()
    week = partition_of(T0) * PARTITION_S
    store.add(hourly(week, [1.0]))
    store.add(hourly(week + HOUR, [2.0], first=week + HOUR))
    store.add(hourly(week + PARTITION_S, [3.0], first=week + PARTITION_S))
    assert [s.taken_at for s in store.snapshots()] == [week + PARTITION_S]
    assert store.in_partition(partition_of(week)) == []  # the older week: counted only
    assert [s.taken_at for s in store.in_partition(partition_of(week) + 1)] == [week + PARTITION_S]
    assert store.count() == 3
    assert store.prune(now=week + HOUR + 90 * DAY + 1) == 2
    assert store.count() == 1


def test_a_snapshot_of_an_older_week_is_not_stored() -> None:
    """Negative: with the clock set back past the start of the week in memory, a snapshot of
    the older week is refused — that week is no longer in memory, and its file must not be
    rewritten with this one snapshot alone."""
    store = ForecastStore()
    week = partition_of(T0) * PARTITION_S
    store.add(hourly(week + PARTITION_S, [3.0], first=week + PARTITION_S))
    assert store.add(hourly(week + DAY, [1.0], first=week + DAY)) is None
    assert store.count() == 1
    assert [s.taken_at for s in store.snapshots()] == [week + PARTITION_S]


def test_partitions_load_the_current_week_and_count_the_others() -> None:
    """P-23: stored weeks are parsed apart — the current one in full, the older ones only far
    enough to count what they hold; an unreadable entry is skipped and counted as such."""
    week = partition_of(T0) * PARTITION_S
    older = ForecastStore()
    older.add(hourly(week, [1.0, 2.0]))
    older.add(hourly(week + HOUR, [1.5], first=week + HOUR))
    current = ForecastStore()
    current.add(hourly(week + PARTITION_S, [3.0], first=week + PARTITION_S))
    restored = ForecastStore()
    skipped = restored.load(
        {
            partition_of(week): [*older.partitions()[partition_of(week)], {"broken": True}],
            partition_of(week) + 1: [
                *current.partitions()[partition_of(week) + 1],
                {"at": "not a number"},
            ],
        },
        current=partition_of(week) + 1,
    )
    assert skipped == 2
    assert [s.taken_at for s in restored.snapshots()] == [week + PARTITION_S]
    assert restored.snapshots()[0].points[0].temperature == 3.0
    assert restored.count() == 3


@pytest.mark.parametrize(
    "entry",
    [
        None,
        "text",
        {},
        {"at": None, "kind": "hourly", "dt": []},
        {"at": float("nan"), "kind": "hourly", "dt": []},
        {"at": True, "kind": "hourly", "dt": []},
        {"at": T0, "kind": "weekly", "dt": []},
        {"at": T0, "kind": "hourly", "dt": "not a list"},
    ],
    ids=["none", "text", "empty", "no_time", "nan", "bool", "unknown_kind", "no_offsets"],
)
def test_an_unreadable_older_entry_is_not_counted(entry: object) -> None:
    """Negative: an older week's entry is counted only when it could be read."""
    store = ForecastStore()
    week = partition_of(T0)
    assert store.load({week: [entry]}, current=week + 1) == 1
    assert store.count() == 0


def test_loading_nothing_leaves_an_empty_store() -> None:
    store = ForecastStore()
    assert store.load({}, current=partition_of(T0)) == 0
    assert (store.count(), store.snapshots()) == (0, [])


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
    errors = forecast_errors(snapshots, observed, horizons_h=(1, 3), observed_until=T0 + 4 * HOUR)
    assert errors[1] == ErrorStats(2, pytest.approx(0.0), pytest.approx(1.0))
    assert errors[3] == ErrorStats(2, pytest.approx(3.0), pytest.approx(3.0))


def test_forecast_errors_need_observations() -> None:
    observed = Series[float]()
    assert forecast_errors([hourly(T0, [1.0, 1.0])], observed, observed_until=T0 + DAY) == {}


def test_forecast_errors_skip_hours_not_yet_observed() -> None:
    """T-40 (P-88): a series with one observation at T0 holds that value for ever, so every
    hour of a 48-hour forecast taken at T0 looked observed. Knowing the observation ends at T0,
    no horizon has statistics; an hour counts once it has ended by ``observed_until``."""
    observed = Series([(T0, 0.0)])
    snapshot = hourly(T0, [1.0] * 48)
    assert forecast_errors([snapshot], observed, observed_until=T0) == {}
    errors = forecast_errors([snapshot], observed, observed_until=T0 + 7 * HOUR)
    assert set(errors) == {1, 3, 6}  # the hours ending by T0 + 7 h
    assert errors[6] == ErrorStats(1, pytest.approx(1.0), pytest.approx(1.0))
