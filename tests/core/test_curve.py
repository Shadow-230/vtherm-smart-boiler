"""Heating curve and effective outdoor temperature."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from custom_components.vtherm_smart_boiler.core.curve import (
    AUTO_ROOM_MAX,
    HOUR,
    HeatingCurve,
    OutdoorSource,
    OutdoorState,
    auto_room,
    update_outdoor,
)


def test_curve_passes_through_room_and_design_point() -> None:
    curve = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)
    assert curve.flow(20.0) == pytest.approx(20.0)
    assert curve.flow(25.0) == pytest.approx(20.0)  # no heat needed above the room
    assert curve.flow(-15.0) == pytest.approx(55.0)


def test_curve_is_bent_by_the_exponent() -> None:
    bent = HeatingCurve(exponent=1.3)
    straight = HeatingCurve(exponent=1.0)
    middle = 2.5  # halfway between room and design outdoor
    assert straight.flow(middle) == pytest.approx(37.5)
    assert bent.flow(middle) > straight.flow(middle)  # emitters need relatively warmer water
    assert bent.flow(middle) == pytest.approx(20.0 + 35.0 * 0.5 ** (1 / 1.3))


def test_curve_rises_monotonically_as_it_gets_colder() -> None:
    curve = HeatingCurve()
    flows = [curve.flow(t) for t in range(20, -21, -1)]
    assert all(b >= a for a, b in pairwise(flows))


def test_offset_shifts_the_whole_curve() -> None:
    assert HeatingCurve(offset=3.0).flow(0.0) == pytest.approx(HeatingCurve().flow(0.0) + 3.0)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"design_outdoor": 25.0},
        {"design_flow": 18.0},
        {"exponent": 0.0},
    ],
)
def test_invalid_curves_are_rejected(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must be"):
        HeatingCurve(**kwargs)


def test_sensor_wins_and_average_starts_at_the_first_value() -> None:
    state = update_outdoor(OutdoorState(), sensor=5.0, weather=8.0, now=0.0)
    assert state == OutdoorState(5.0, 5.0, OutdoorSource.SENSOR, 0.0)


def test_weather_is_the_fallback_source() -> None:
    state = update_outdoor(OutdoorState(), sensor=None, weather=8.0, now=0.0)
    assert state.source is OutdoorSource.WEATHER
    assert state.effective == 8.0


def test_cold_snap_is_followed_at_once_warming_slowly() -> None:
    state = update_outdoor(OutdoorState(), 5.0, None, 0.0)
    colder = update_outdoor(state, -5.0, None, 600.0)
    assert colder.effective == -5.0  # the current value is lower than the average
    assert colder.average is not None
    assert -5.0 < colder.average < 5.0
    warmer = update_outdoor(colder, 10.0, None, 1200.0)
    assert warmer.effective == warmer.average  # the average lags behind the warm-up
    assert warmer.effective < 10.0


def test_average_follows_the_time_constant() -> None:
    state = update_outdoor(OutdoorState(), 0.0, None, 0.0)
    later = update_outdoor(state, 10.0, None, 3 * HOUR, time_constant_s=3 * HOUR)
    assert later.average == pytest.approx(10.0 * (1 - math.exp(-1)), rel=1e-6)


def test_a_clock_set_back_holds_the_outdoor_value_its_own_time_only() -> None:
    """PB-28: the wall clock set back a day — a reading "later than now" counts from now, so the
    hold lasts its three hours, not 27."""
    state = update_outdoor(OutdoorState(), 2.0, None, 86_400.0)
    held = update_outdoor(state, None, None, 0.0, hold_s=3 * HOUR)
    assert held.source is OutdoorSource.HELD
    assert held.updated_at == 0.0
    later = update_outdoor(held, None, None, 3 * HOUR - 1.0, hold_s=3 * HOUR)
    assert later.source is OutdoorSource.HELD
    gone = update_outdoor(later, None, None, 3 * HOUR + 1.0, hold_s=3 * HOUR)
    assert gone.source is OutdoorSource.NONE


def test_missing_readings_hold_the_last_value_then_give_up() -> None:
    state = update_outdoor(OutdoorState(), 2.0, None, 0.0)
    held = update_outdoor(state, None, None, 1800.0, hold_s=HOUR)
    assert held.source is OutdoorSource.HELD
    assert held.effective == 2.0
    gone = update_outdoor(held, None, None, HOUR + 1.0, hold_s=HOUR)
    assert gone.source is OutdoorSource.NONE
    assert gone.effective is None
    assert update_outdoor(OutdoorState(), None, None, 0.0).source is OutdoorSource.NONE


AUTO_CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=20.0, exponent=1.3)


@pytest.mark.parametrize(
    ("targets", "previous", "expected"),
    [
        ((21.5, 19.0), None, 21.5),  # the warmest room's setpoint
        ((25.0, 19.0), None, AUTO_ROOM_MAX),  # at most 23 °C
        ((), 21.0, 21.0),  # no zone that heats: the last Auto value holds
        ((), None, 20.0),  # none yet: the curve's own, the manual value
        ((12.0,), None, 15.0),  # never below the room temperature's bounds
    ],
)
def test_the_auto_room_is_the_warmest_setpoint_within_bounds(
    targets: tuple[float, ...], previous: float | None, expected: float
) -> None:
    """G11 D: Auto takes the highest setpoint among the zones that heat, at most 23 °C, within
    the room temperature's bounds; with none, the last Auto value, else the manual one."""
    assert AUTO_ROOM_MAX == 23.0
    assert auto_room(targets, AUTO_CURVE, previous) == pytest.approx(expected)


@pytest.mark.parametrize(
    ("curve", "expected"),
    [
        (HeatingCurve(design_outdoor=-15.0, design_flow=26.0, room=20.0), 21.0),  # flow − 5 K
        (HeatingCurve(design_outdoor=9.0, design_flow=55.0, room=20.0), 19.0),  # outdoor + 10 K
    ],
)
def test_the_auto_room_keeps_the_curves_own_checks(curve: HeatingCurve, expected: float) -> None:
    """G11 D: Auto stays where the curve step's checks hold — at most the design flow − 5 K,
    at least the design outdoor temperature + 10 K — so the curve it builds is always valid."""
    room = auto_room((22.0,) if expected > 20 else (17.0,), curve, None)
    assert room == pytest.approx(expected)
    assert curve.design_outdoor < room < curve.design_flow
