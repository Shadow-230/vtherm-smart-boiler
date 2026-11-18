"""The curve as the Boiler page draws it (``docs/en/development/plans/plan-0.2-i10.md``, I10.2):
the water control asks for at each outdoor temperature — the curve at the room temperature in
use, then the limits — before the comfort correction, a circuit's need and the ramp."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.curve_view import curve_points
from custom_components.vtherm_smart_boiler.core.limits import FlowLimits, limit_flow

CURVE = HeatingCurve(design_outdoor=-15.0, design_flow=55.0, room=21.0)
LIMITS = FlowLimits(hard_min=25.0, hard_max=70.0)


def test_each_point_is_the_water_control_asks_for() -> None:
    points = curve_points(CURVE, LIMITS, None, None, -20.0, 20.0)
    assert points[0][0] == -20.0
    assert points[-1][0] == 20.0
    assert len(points) == 81  # every half degree, both ends included
    for outdoor, water in points:
        assert water == limit_flow(CURVE.flow(outdoor), LIMITS).value


def test_the_limits_cut_the_curve() -> None:
    """The lowest water in mild weather, the lowest cap — a circuit's, the boiler's — in frost."""
    points = dict(curve_points(CURVE, LIMITS, 50.0, 60.0, -25.0, 20.0, step=5.0))
    assert points[20.0] == 25.0  # the curve there is at the room temperature: the lowest water
    assert points[-25.0] == 50.0  # the circuit's maximum, below the boiler's and the hard one
    assert points[0.0] == pytest.approx(CURVE.flow(0.0))  # within the limits: the curve itself


def test_a_room_temperature_moves_the_curve() -> None:
    warmer = curve_points(HeatingCurve(-15.0, 55.0, room=23.0), LIMITS, None, None, 0.0, 0.0)
    cooler = curve_points(HeatingCurve(-15.0, 55.0, room=19.0), LIMITS, None, None, 0.0, 0.0)
    assert warmer[0][1] > cooler[0][1]


def test_steps_land_on_round_values() -> None:
    points = curve_points(CURVE, LIMITS, None, None, -1.0, 1.0, step=0.1)
    assert [o for o, _ in points][:3] == [-1.0, -0.9, -0.8]
    assert points[-1][0] == 1.0


@pytest.mark.parametrize(
    ("start", "end", "step"),
    [(0.0, -1.0, 0.5), (0.0, 10.0, 0.0), (0.0, 10.0, -1.0), (-100.0, 100.0, 0.01)],
)
def test_a_range_that_makes_no_sense_is_refused(start: float, end: float, step: float) -> None:
    with pytest.raises(ValueError, match="range"):
        curve_points(CURVE, LIMITS, None, None, start, end, step=step)
