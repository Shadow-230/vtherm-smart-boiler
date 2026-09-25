"""Step-wise series: ordering, change-only storage, segments, windows and helpers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.series import (
    Segment,
    Series,
    duration_where,
    known_duration,
    time_weighted_mean,
)


def test_keeps_only_changes() -> None:
    series = Series([(0, 1.0), (10, 1.0), (20, 2.0), (30, 2.0)])
    assert [(s.t, s.value) for s in series] == [(0, 1.0), (20, 2.0)]


def test_same_time_replaces_last_value() -> None:
    series = Series([(0, 1.0), (10, 2.0)])
    series.append(10, 3.0)
    assert [(s.t, s.value) for s in series] == [(0, 1.0), (10, 3.0)]


def test_same_time_back_to_previous_value_drops_the_sample() -> None:
    series = Series([(0, 1.0), (10, 2.0)])
    series.append(10, 1.0)
    assert [(s.t, s.value) for s in series] == [(0, 1.0)]


def test_rejects_samples_going_back_in_time() -> None:
    series = Series([(10, 1.0)])
    with pytest.raises(ValueError, match="older"):
        series.append(5, 2.0)


def test_value_at_holds_until_next_sample() -> None:
    series = Series([(10, 1.0), (20, None), (30, 3.0)])
    assert series.value_at(5) is None
    assert series.value_at(10) == 1.0
    assert series.value_at(19.9) == 1.0
    assert series.value_at(25) is None
    assert series.value_at(1000) == 3.0


def test_segments_cover_the_window_with_unknown_before_first_sample() -> None:
    series = Series([(10, True), (20, False)])
    assert list(series.segments(0, 30)) == [
        Segment(0, 10, None),
        Segment(10, 20, True),
        Segment(20, 30, False),
    ]


def test_segments_clip_to_the_window() -> None:
    series = Series([(0, 1.0), (10, 2.0), (20, 3.0)])
    assert list(series.segments(5, 15)) == [Segment(5, 10, 1.0), Segment(10, 15, 2.0)]
    assert list(series.segments(15, 15)) == []


def test_empty_series_is_unknown() -> None:
    assert list(Series[float]().segments(0, 10)) == [Segment(0, 10, None)]
    assert Series[float]().last is None


def test_window_starts_with_the_value_holding_at_start() -> None:
    series = Series([(0, 1.0), (10, 2.0), (20, 3.0)])
    window = series.window(5, 15)
    assert [(s.t, s.value) for s in window] == [(5, 1.0), (10, 2.0)]


def test_drop_before_keeps_the_value_holding_at_the_cut() -> None:
    series = Series([(0, 1.0), (10, 2.0), (20, 3.0)])
    series.drop_before(15)
    assert [(s.t, s.value) for s in series] == [(10, 2.0), (20, 3.0)]
    assert series.value_at(15) == 2.0


def test_durations_ignore_unknown_stretches() -> None:
    flame = Series([(0, True), (10, None), (20, False), (30, True)])
    assert duration_where(flame, 0, 40, bool) == 20
    assert known_duration(flame, 0, 40) == 30


def test_time_weighted_mean_uses_known_data_only() -> None:
    flow = Series([(0, 40.0), (10, None), (20, 60.0)])
    mean = time_weighted_mean(flow, 0, 30)
    assert mean.value == pytest.approx(50.0)
    assert mean.known_s == 20
    assert time_weighted_mean(Series[float](), 0, 10).value is None


def test_older_samples_go_before_the_first_one() -> None:
    """A backfill from the recorder arrives after live samples: it goes before them, and only
    what is older than the first live sample."""
    live = Series([(100.0, 2.0), (200.0, 3.0)])
    live.prepend(Series([(0.0, 1.0), (50.0, 2.0), (150.0, 9.0)]))
    assert [(s.t, s.value) for s in live] == [(0.0, 1.0), (50.0, 2.0), (200.0, 3.0)]
    empty: Series[float] = Series()
    empty.prepend(Series([(0.0, 1.0)]))
    assert [(s.t, s.value) for s in empty] == [(0.0, 1.0)]
