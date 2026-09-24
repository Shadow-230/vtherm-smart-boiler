"""Heating curve and effective outdoor temperature."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from custom_components.vtherm_smart_boiler.core.curve import (
    HOUR,
    HeatingCurve,
    OutdoorSource,
    OutdoorState,
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


def test_missing_readings_hold_the_last_value_then_give_up() -> None:
    state = update_outdoor(OutdoorState(), 2.0, None, 0.0)
    held = update_outdoor(state, None, None, 1800.0, hold_s=HOUR)
    assert held.source is OutdoorSource.HELD
    assert held.effective == 2.0
    gone = update_outdoor(held, None, None, HOUR + 1.0, hold_s=HOUR)
    assert gone.source is OutdoorSource.NONE
    assert gone.effective is None
    assert update_outdoor(OutdoorState(), None, None, 0.0).source is OutdoorSource.NONE
