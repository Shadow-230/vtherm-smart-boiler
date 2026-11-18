"""The curve as the Boiler page draws it (``docs/en/development/plans/plan-0.2-i10.md``, I10.2).

Each point is the water control asks for at that outdoor temperature: the curve at the room
temperature in use, then the limits — the lowest water, the highest, a circuit's and the boiler's
caps — as ``core.controller`` decides it, before the comfort correction, a circuit's need and the
ramp. The page draws these points; it never computes a curve of its own.
"""

from __future__ import annotations

from .curve import HeatingCurve
from .limits import FlowLimits, limit_flow

MAX_POINTS = 1000  # a page needs a few hundred at most


def curve_points(
    curve: HeatingCurve,
    limits: FlowLimits,
    circuit_max: float | None,
    boiler_max: float | None,
    outdoor_from: float,
    outdoor_to: float,
    *,
    step: float = 0.5,
) -> tuple[tuple[float, float], ...]:
    """(outdoor, water) from ``outdoor_from`` to ``outdoor_to``, both included, every ``step``
    degrees; a range that is empty, backwards or too fine is refused with ``ValueError``."""
    if step <= 0 or outdoor_to < outdoor_from:
        raise ValueError("the outdoor range must run forwards in positive steps")
    count = round((outdoor_to - outdoor_from) / step)
    if count + 1 > MAX_POINTS:
        raise ValueError(f"the outdoor range gives more than {MAX_POINTS} points")
    outdoors = [round(outdoor_from + i * step, 6) for i in range(count + 1)]
    return tuple(
        (o, limit_flow(curve.flow(o), limits, circuit_max, boiler_max).value) for o in outdoors
    )
