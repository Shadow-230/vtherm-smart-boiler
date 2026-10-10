"""G11 F: a window probably open, seen without a sensor — a room falling fast while it heats."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.window_guard import (
    WINDOW_DROP_K,
    WINDOW_DROP_S,
    WINDOW_HOLD_S,
    WINDOW_WARM_K,
    WindowWatch,
    follow_window,
)

MIN = 60.0


def walk(readings: list[tuple[float, float | None, bool]]) -> WindowWatch:
    watch = WindowWatch()
    for now, temperature, heating in readings:
        watch = follow_window(watch, now, temperature, heating)
    return watch


def test_the_guards_values() -> None:
    """About VT's 3 °C/h: 0.5 K within 10 min; held at least 30 min, until 0.2 K back up."""
    assert (WINDOW_DROP_K, WINDOW_DROP_S, WINDOW_HOLD_S, WINDOW_WARM_K) == (0.5, 600.0, 1800.0, 0.2)


def test_a_room_falling_half_a_kelvin_in_ten_minutes_while_it_heats_has_a_window_open() -> None:
    watch = walk([(0.0, 21.0, True), (5 * MIN, 20.8, True), (9 * MIN, 20.5, True)])
    assert watch.suspected
    assert watch.since == 9 * MIN
    assert watch.lowest == 20.5


@pytest.mark.parametrize(
    "readings",
    [
        [(0.0, 21.0, True), (9 * MIN, 20.6, True)],  # 0.4 K: not enough
        [(0.0, 21.0, True), (11 * MIN, 20.4, True)],  # over more than 10 min: slower
        [(0.0, 21.0, False), (9 * MIN, 20.4, False)],  # not heating: the room may just cool
        [(0.0, 21.0, True), (5 * MIN, None, True), (9 * MIN, 20.8, True)],  # unknown between
    ],
    ids=["small", "slow", "not_heating", "unknown"],
)
def test_a_slow_or_small_fall_or_one_without_heat_is_no_window(
    readings: list[tuple[float, float | None, bool]],
) -> None:
    assert not walk(readings).suspected


def test_it_holds_30_minutes_and_ends_once_the_room_warms_again() -> None:
    """Left out until the room has warmed 0.2 K over its lowest reading since, and for at least
    30 minutes: warm again sooner, it holds; after 30 minutes still cold, it holds too."""
    start = [(0.0, 21.0, True), (9 * MIN, 20.4, True)]
    watch = walk([*start, (20 * MIN, 20.2, True), (25 * MIN, 20.6, True)])
    assert watch.suspected  # warm again, but not 30 minutes yet
    assert watch.lowest == 20.2
    watch = follow_window(watch, 9 * MIN + WINDOW_HOLD_S, 20.3, True)
    assert watch.suspected  # 30 minutes, but only 0.1 K over its lowest
    watch = follow_window(watch, 9 * MIN + WINDOW_HOLD_S + MIN, 20.4, True)
    assert not watch.suspected  # 0.2 K over its lowest after 30 minutes: closed again
    assert watch.since is None


def test_a_clock_set_back_starts_the_watch_again() -> None:
    watch = walk([(600.0, 21.0, True), (300.0, 20.4, True)])
    assert not watch.suspected
    assert watch.readings == ((300.0, 20.4),)
