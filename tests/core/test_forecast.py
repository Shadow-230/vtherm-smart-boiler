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


def test_a_stored_week_later_than_the_current_one_is_left_out() -> None:
    """Negative: a week after the one being written — a clock set back since it was stored —
    is neither loaded nor counted, nor counted as skipped."""
    week = partition_of(T0)
    later = ForecastStore()
    later.add(hourly((week + 1) * PARTITION_S, [3.0], first=(week + 1) * PARTITION_S))
    store = ForecastStore()
    assert store.load({week + 1: later.partitions()[week + 1]}, current=week) == 0
    assert (store.count(), store.snapshots()) == (0, [])


@pytest.mark.parametrize("entry", [None, "text", 3.0, ["at", T0]], ids=str)
def test_an_entry_of_the_current_week_that_is_not_a_mapping_is_skipped(entry: object) -> None:
    """Negative: in the week being written, an entry that is not a mapping is skipped and
    counted as such; the readable ones beside it are kept."""
    week = partition_of(T0)
    current = ForecastStore()
    current.add(hourly(week * PARTITION_S, [3.0], first=week * PARTITION_S))
    store = ForecastStore()
    assert store.load({week: [entry, *current.partitions()[week]]}, current=week) == 1
    assert store.count() == 1


def test_forecast_errors_use_hourly_forecasts_only() -> None:
    """Negative: a daily forecast's steps are a day long; they are not compared hour by hour."""
    observed = Series([(T0, 0.0)])
    daily = ForecastSnapshot(
        T0, ForecastKind.DAILY, tuple(ForecastPoint(T0 + i * HOUR, 5.0) for i in range(4))
    )
    assert forecast_errors([daily], observed, observed_until=T0 + DAY) == {}


def test_a_step_that_began_before_the_snapshot_is_no_forecast_ahead() -> None:
    """Negative: the step holding the moment a snapshot was taken began before it; it is not
    counted at the horizon 0 — only steps from the snapshot's moment on are forecasts."""
    observed = Series([(T0, 0.0)])
    snapshot = hourly(T0 + HOUR / 4, [9.0, 1.0])  # steps at T0 (begun) and T0 + 1 h
    errors = forecast_errors([snapshot], observed, horizons_h=(0, 1), observed_until=T0 + DAY)
    assert set(errors) == {1}
    assert errors[1] == ErrorStats(1, pytest.approx(1.0), pytest.approx(1.0))


# --- Mutation testing (2026-10-12): bounds, storage order, the error's sign ---


def _entry(taken_at: float) -> dict:
    """One stored hourly snapshot taken at ``taken_at``, in the compact form."""
    return hourly(taken_at, [1.0], first=taken_at).to_dict()


def test_a_step_that_ended_as_the_snapshot_was_taken_is_dropped() -> None:
    """Negative: a step ending exactly at the snapshot's moment is past; the step beginning then
    is the first one kept."""
    trimmed = hourly(T0 + HOUR, [1.0, 2.0, 3.0]).trimmed(48)
    assert [p.t for p in trimmed.points] == [T0 + HOUR, T0 + 2 * HOUR]


def test_a_snapshot_exactly_as_old_as_the_retention_is_kept() -> None:
    """Only snapshots older than the retention are dropped; one exactly as old is kept — in the
    week in memory and among an older week's times loaded from storage alike."""
    week = partition_of(T0)
    store = ForecastStore()
    store.load(
        {week: [_entry(week * PARTITION_S)], week + 1: [_entry((week + 1) * PARTITION_S)]},
        current=week + 1,
    )
    assert store.prune(now=week * PARTITION_S + store.retention_s) == 0
    assert store.prune(now=(week + 1) * PARTITION_S + store.retention_s) == 1
    assert [s.taken_at for s in store.snapshots()] == [(week + 1) * PARTITION_S]
    assert store.count() == 1


def test_since_includes_a_snapshot_taken_at_that_moment() -> None:
    """The snapshots since a moment include one taken at it. Negative: a moment later, not."""
    store = ForecastStore()
    taken_at = partition_of(T0) * PARTITION_S + DAY
    store.add(hourly(taken_at, [1.0], first=taken_at))
    assert len(store.snapshots(since=taken_at)) == 1
    assert store.snapshots(since=taken_at + 1.0) == []


def test_the_loaded_week_is_the_week_in_memory() -> None:
    """The week being written, loaded from storage, is held in time order whatever order its
    file lists it in, and stays the week in memory: a snapshot taken later that week joins it,
    and a save of the week holds them all."""
    week = partition_of(T0)
    first = week * PARTITION_S
    entries = [_entry(first + 2 * HOUR), _entry(first + HOUR)]  # stored out of order
    store = ForecastStore()
    assert store.load({week: entries}, current=week) == 0
    assert [s.taken_at for s in store.snapshots()] == [first + HOUR, first + 2 * HOUR]
    assert [s.taken_at for s in store.in_partition(week)] == [first + HOUR, first + 2 * HOUR]
    store.add(hourly(first + 3 * HOUR, [3.0], first=first + 3 * HOUR))
    assert store.count() == 3
    assert len(store.in_partition(week)) == 3


def test_an_entry_filed_under_another_week_is_not_saved_with_the_current_one() -> None:
    """Negative: an entry in the current week's file taken in the week before or after it (a
    file damaged or edited) is not part of that week: a save of the week leaves it out."""
    week = partition_of(T0)
    times = [(week + offset) * PARTITION_S + DAY for offset in (-1, 0, 1)]
    store = ForecastStore()
    store.load({week: [_entry(t) for t in times]}, current=week)
    assert [s.taken_at for s in store.in_partition(week)] == [times[1]]


def test_a_later_week_listed_first_does_not_stop_the_loading() -> None:
    """Negative: a stored week after the current one is left out alone — the current and older
    weeks listed after it are still loaded and counted."""
    week = partition_of(T0)
    stored = {w: [_entry(w * PARTITION_S + DAY)] for w in (week + 1, week, week - 1)}
    store = ForecastStore()
    assert store.load(stored, current=week) == 0
    assert [s.taken_at for s in store.snapshots()] == [week * PARTITION_S + DAY]
    assert store.count() == 2


def test_every_unreadable_entry_is_counted() -> None:
    """Negative: each unreadable entry, of the week being written or of an older one, counts as
    skipped — not only one of them; the readable one beside them is kept."""
    week = partition_of(T0)
    store = ForecastStore()
    stored = {
        week - 1: [None, "text"],
        week: [None, {"at": "not a number"}, _entry(week * PARTITION_S)],
    }
    assert store.load(stored, current=week) == 4
    assert store.count() == 1


def test_the_error_is_the_forecast_minus_the_observation() -> None:
    """A forecast 3 K warmer than the 2 °C observed is an error of +3 K: the bias keeps its sign."""
    observed = Series([(T0, 2.0)])
    snapshot = hourly(T0, [5.0, 5.0])  # 0 h and 1 h ahead
    errors = forecast_errors([snapshot], observed, horizons_h=(1,), observed_until=T0 + DAY)
    assert errors == {1: ErrorStats(1, pytest.approx(3.0), pytest.approx(3.0))}


def test_a_daily_snapshot_before_an_hourly_one_is_skipped_alone() -> None:
    """Negative: a daily snapshot listed first is skipped; the hourly one after it is still
    compared."""
    observed = Series([(T0, 0.0)])
    daily = ForecastSnapshot(T0, ForecastKind.DAILY, (ForecastPoint(T0 + HOUR, 5.0),))
    snapshots = [daily, hourly(T0, [1.0, 1.0])]
    errors = forecast_errors(snapshots, observed, horizons_h=(1,), observed_until=T0 + DAY)
    assert errors == {1: ErrorStats(1, pytest.approx(1.0), pytest.approx(1.0))}


@pytest.mark.parametrize(
    ("taken_at", "horizon"),
    [(T0, 0), (T0 - HOUR / 2, 1)],
    ids=["from_the_moment", "half_an_hour_off"],
)
def test_the_horizons_bounds_are_inclusive(taken_at: float, horizon: int) -> None:
    """A step beginning at the snapshot's moment is a forecast at the horizon 0; a step half an
    hour off a listed horizon still counts at it."""
    observed = Series([(T0, 0.0)])
    snapshot = ForecastSnapshot(taken_at, ForecastKind.HOURLY, (ForecastPoint(T0, 1.0),))
    errors = forecast_errors([snapshot], observed, horizons_h=(horizon,), observed_until=T0 + DAY)
    assert errors == {horizon: ErrorStats(1, pytest.approx(1.0), pytest.approx(1.0))}


@pytest.mark.parametrize(("known_min", "counted"), [(25.0, False), (30.0, True)])
def test_an_hour_needs_half_of_it_observed(known_min: float, counted: bool) -> None:
    """The observation must cover at least half of the forecast hour: 30 minutes are enough.
    Negative: 25 minutes are not."""
    observed = Series([(T0, None), (T0 + HOUR - known_min * 60.0, 0.0)])
    snapshot = hourly(T0 - HOUR, [1.0], first=T0)  # 1 h ahead
    errors = forecast_errors([snapshot], observed, horizons_h=(1,), observed_until=T0 + DAY)
    assert (1 in errors) is counted


def test_an_hour_not_observed_does_not_stop_the_later_ones() -> None:
    """Negative: a forecast hour without observations is skipped alone; the later hours of the
    same snapshot are still compared."""
    observed = Series([(T0 + 2 * HOUR, 0.0)])  # nothing known before
    snapshot = hourly(T0, [1.0, 1.0], first=T0 + HOUR)  # 1 h and 2 h ahead
    errors = forecast_errors([snapshot], observed, horizons_h=(1, 2), observed_until=T0 + DAY)
    assert set(errors) == {2}
