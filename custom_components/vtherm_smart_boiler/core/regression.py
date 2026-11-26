"""Straight lines through daily figures, with an allowance for correlated days (I13.4).

A house's days are not independent: a cold spell, the building's mass and the sun carry over
from one day to the next, so the residuals of a line through daily figures are correlated, and a
textbook range comes out too narrow (IEA EBC Annex 58, p. 14). The allowance here is the
effective sample size from the lag-1 autocorrelation ``rho`` of the residuals in time order,
``n_eff = n (1 − rho) / (1 + rho)`` (the textbook rule for errors of the first order): a standard
error widens by ``√((1 + rho) / (1 − rho))``, and a 95 % range takes Student's t with the degrees of
freedom ``n_eff`` leaves. A negative ``rho`` gives no allowance, and ``rho`` is held at
``MAX_LAG_ONE``: no data make a range narrower than the textbook one.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

# rho is held here: the widening stays finite (about 4.4 times).
MAX_LAG_ONE = 0.9
# Residuals this small against the values fitted are rounding, not weather: no correlation.
ROUNDING = 1e-9
_Z95 = 1.959963984540054  # the normal distribution's 97.5 % point
# Student's t at 97.5 % for 1 to 4 degrees of freedom; from 5 on, the Cornish–Fisher series
# below is within 0.01 of it.
_T95_SMALL = (12.706, 4.303, 3.182, 2.776)


def t95(dof: float) -> float:
    """Student's t at 97.5 % — half a 95 % range in standard errors — for ``dof`` degrees of
    freedom; a fractional ``dof`` under 5 is rounded down (the wider range). Infinite under 1."""
    if dof < 1:
        return math.inf
    if dof < len(_T95_SMALL) + 1:
        return _T95_SMALL[int(dof) - 1]
    z = _Z95
    return (
        z
        + (z**3 + z) / (4 * dof)
        + (5 * z**5 + 16 * z**3 + 3 * z) / (96 * dof**2)
        + (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / (384 * dof**3)
    )


def lag_one(
    residuals: Sequence[float], adjacent: Sequence[bool] | None = None, scale: float = 0.0
) -> float:
    """The lag-1 autocorrelation of ``residuals`` in time order, over the pairs of neighbours
    only (``adjacent[i]``: residual ``i + 1`` follows ``i`` by one day; ``None``: every pair),
    held within 0 to ``MAX_LAG_ONE``; 0 without a pair, or where the residuals are rounding
    only — none above ``ROUNDING`` times ``scale``, the size of the values fitted."""
    total = sum(r * r for r in residuals)
    pairs = [
        residuals[i] * residuals[i + 1]
        for i in range(len(residuals) - 1)
        if adjacent is None or adjacent[i]
    ]
    if not pairs or total <= 0 or max(abs(r) for r in residuals) <= ROUNDING * scale:
        return 0.0
    # Scaled to the pairs' share of the days, so gaps between them do not shrink it.
    rho = sum(pairs) / total * (len(residuals) - 1) / len(pairs)
    return min(MAX_LAG_ONE, max(0.0, rho))


def widening(rho: float) -> float:
    """How much a standard error widens for days correlated by ``rho``."""
    return math.sqrt((1 + rho) / (1 - rho))


def effective_n(n: int, rho: float) -> float:
    """How many independent days ``n`` correlated ones are worth."""
    return n * (1 - rho) / (1 + rho)


@dataclass(frozen=True, slots=True)
class Line:
    """``y = intercept + slope · x`` fitted by least squares, with what its ranges need."""

    slope: float
    intercept: float
    n: int
    mean_x: float
    sxx: float  # the x values' sum of squared deviations
    deviation: float  # the residuals' standard deviation, n − 2 degrees of freedom
    rho: float  # the residuals' lag-1 autocorrelation (``lag_one``)

    def at(self, x: float) -> float:
        return self.intercept + self.slope * x

    @property
    def t(self) -> float:
        """Half a 95 % range in standard errors, with the days' allowance."""
        return t95(effective_n(self.n, self.rho) - 2)

    @property
    def slope_error(self) -> float:
        """The slope's standard error, widened for correlated days."""
        return self.deviation / math.sqrt(self.sxx) * widening(self.rho)

    def error_at(self, x: float) -> float:
        """The standard error of the line's value at ``x``, widened for correlated days."""
        spread = 1.0 / self.n + (x - self.mean_x) ** 2 / self.sxx
        return self.deviation * math.sqrt(spread) * widening(self.rho)


def fit_line(
    xs: Sequence[float], ys: Sequence[float], adjacent: Sequence[bool] | None = None
) -> Line | None:
    """The least-squares line through the points, in time order (``adjacent`` as for
    ``lag_one``); ``None`` with fewer than three points or no spread of ``xs``."""
    n = len(xs)
    if n < 3:
        return None
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    slope = sxy / sxx
    intercept = mean_y - slope * mean_x
    residuals = [y - (intercept + slope * x) for x, y in zip(xs, ys, strict=True)]
    deviation = math.sqrt(sum(r * r for r in residuals) / (n - 2))
    rho = lag_one(residuals, adjacent, max(abs(y) for y in ys))
    return Line(slope, intercept, n, mean_x, sxx, deviation, rho)
