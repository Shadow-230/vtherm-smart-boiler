"""Whole-house heat load in kW — the boiler's load, not a model of any room.

The load at an outdoor temperature is ``H · max(0, threshold − outdoor)``: ``H`` is the loss
coefficient (kW/K) and ``threshold`` the outdoor temperature above which the house needs no
heating (internal and solar gains are folded into it). Recorded days of heating give the
values; a year of energy use may give a first one. A value the user entered — the design load,
the threshold — always wins: data never replace it; they show a mismatch (P-92, review question
12). Floor area, insulation and thermal mass gave only rules of thumb no function needed, and
went in I8 (decision B5).

The building model feeds the monitor only — the verdict's load criterion, degree-days, the
lowest water temperature's "about" estimate; control never reads it (review question 11). The
measured values are shown with their source and confidence, and each can be reset: it is then
fitted again from later days only (P-90).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from .parameters import (
    MIN_CONFIDENCE,
    PARAMETER_DEFS,
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)

HOURS_PER_DAY = 24.0


ANNUAL_ENERGY_CONFIDENCE = 0.4


def loss_from_design_load(design_load_kw: float, design_outdoor: float, indoor: float) -> Estimate:
    """The user's own heat-load calculation: ``H = P / (indoor − design outdoor)``."""
    span = indoor - design_outdoor
    if design_load_kw <= 0 or span <= 0:
        raise ValueError("design load and indoor-minus-design-outdoor must be positive")
    return Estimate(design_load_kw / span, Source.ENTERED)


def loss_from_annual_energy(heating_energy_kwh: float, degree_days: float) -> Estimate:
    """A first value from a year of heating energy (e.g. gas bills times efficiency).

    ``degree_days`` (K·day) must use the same base as the heating threshold.
    """
    if heating_energy_kwh <= 0 or degree_days <= 0:
        raise ValueError("energy and degree-days must be positive")
    return Estimate(
        heating_energy_kwh / (degree_days * HOURS_PER_DAY), Source.DEFAULT, ANNUAL_ENERGY_CONFIDENCE
    )


@dataclass(frozen=True, slots=True)
class LoadModel:
    loss_coefficient: float  # kW/K
    heating_threshold: float  # °C

    @classmethod
    def from_parameters(cls, parameters: ParameterSet) -> LoadModel | None:
        """The model from the effective values, whatever their source — rule-of-thumb defaults
        included: for showing only. What decides uses ``trusted_load_model``."""
        loss = parameters.value(ParameterKey.LOSS_COEFFICIENT)
        threshold = parameters.value(ParameterKey.HEATING_THRESHOLD)
        if loss is None or threshold is None:
            return None
        return cls(loss, threshold)

    def load_kw(self, outdoor: float) -> float:
        return self.loss_coefficient * max(0.0, self.heating_threshold - outdoor)

    def outdoor_at_load(self, power_kw: float) -> float:
        """Outdoor temperature at which the load equals ``power_kw``.

        Above it the load is smaller — for the boiler's minimum power, that is where cycling
        becomes unavoidable.
        """
        return self.heating_threshold - power_kw / self.loss_coefficient


_MEASURED_SOURCES = frozenset({Source.MEASURED, Source.LEARNED})


def trusted(estimate: Estimate | None) -> bool:
    """An estimate that may decide something: the user's entry, or one measured or learned with
    the confidence the plugin counts (``MIN_CONFIDENCE``) — never a rule of thumb."""
    if estimate is None:
        return False
    if estimate.source is Source.ENTERED:
        return True
    return estimate.source in _MEASURED_SOURCES and estimate.confidence >= MIN_CONFIDENCE


def trusted_load_model(parameters: ParameterSet) -> LoadModel | None:
    """S-17: the load model when both its values are trusted — the loss and the threshold each
    entered, or measured or learned with ``MIN_CONFIDENCE``; ``None`` otherwise, a model from
    rule-of-thumb defaults included: it is shown, and decides nothing."""
    loss = parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    threshold = parameters.get(ParameterKey.HEATING_THRESHOLD).effective()
    if loss is None or threshold is None or not (trusted(loss) and trusted(threshold)):
        return None
    return LoadModel(loss.value, threshold.value)


@dataclass(frozen=True, slots=True)
class DayPoint:
    """One day of heating: mean outdoor temperature and the heat delivered for space heating."""

    outdoor_mean: float
    energy_kwh: float


@dataclass(frozen=True, slots=True)
class LoadFit:
    # ``None`` only where the analysis fitted the two apart (a reset of one, P-90) and the days
    # since the loss's reset gave none.
    loss: Estimate | None
    threshold: Estimate | None  # None when the days did not spread enough to fit it
    days: int
    quality: float  # 0 to 1


MIN_FIT_DAYS = 7
# P-31: the heating threshold is fitted only over at least this spread of daily outdoor
# temperatures, and weighs fully from ``FULL_SPREAD_K`` on; a standard error above
# ``MAX_THRESHOLD_ERROR_K`` caps its confidence (provisional, K4).
MIN_OUTDOOR_SPREAD_K = 8.0
FULL_SPREAD_K = 12.0
MAX_THRESHOLD_ERROR_K = 2.0
MIN_QUALITY = 0.5  # R² for the two-parameter fit, 1 − relative RMS error otherwise
MAX_FIT_CONFIDENCE = 0.95
SINGLE_PARAMETER_PENALTY = 0.7
FULL_COVERAGE_DAYS = 30  # this many heating days give the fit its full weight
CLAMPED_CONFIDENCE = 0.3  # a fit held at a bound, or too uncertain: shown, never used


def fit_daily_load(
    days: Sequence[DayPoint], threshold: Estimate, at: float | None = None
) -> LoadFit | None:
    """Fit ``energy = 24 · H · (threshold − outdoor)`` to recorded heating days.

    Only days colder than ``threshold`` — the one in use, with its source — with positive energy
    count. Over an outdoor spread of ``MIN_OUTDOOR_SPREAD_K`` or more, ``H`` and the threshold
    are fitted together; the threshold gets its own confidence, weighed by the spread and capped
    at ``CLAMPED_CONFIDENCE`` when its standard error exceeds ``MAX_THRESHOLD_ERROR_K`` (P-31).
    Over a narrower spread only ``H`` is fitted, through ``threshold`` — and only when that is
    the user's entry or trusted (P-32): through a rule of thumb, ``H`` would take its error.
    ``None`` when the data cannot support a fit.
    """
    usable = [d for d in days if d.outdoor_mean < threshold.value and d.energy_kwh > 0]
    if len(usable) < MIN_FIT_DAYS:
        return None
    xs = [d.outdoor_mean for d in usable]
    ys = [d.energy_kwh for d in usable]
    n = len(usable)
    coverage = min(1.0, n / FULL_COVERAGE_DAYS)
    spread = max(xs) - min(xs)
    if spread >= MIN_OUTDOOR_SPREAD_K:
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        sxx = sum((x - mean_x) ** 2 for x in xs)
        sxy = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
        slope = sxy / sxx
        if slope >= 0:  # more energy on warmer days: not a heating load
            return None
        intercept = mean_y - slope * mean_x
        predicted = [intercept + slope * x for x in xs]
        r_squared = _r_squared(ys, predicted)
        if r_squared < MIN_QUALITY:
            return None
        crossing = intercept / -slope
        loss, loss_clamped = _clamped(ParameterKey.LOSS_COEFFICIENT, -slope / HOURS_PER_DAY)
        fitted, threshold_clamped = _clamped(ParameterKey.HEATING_THRESHOLD, crossing)
        confidence = min(MAX_FIT_CONFIDENCE, coverage * r_squared)
        own = min(MAX_FIT_CONFIDENCE, coverage * r_squared * min(1.0, spread / FULL_SPREAD_K))
        if loss_clamped or threshold_clamped:
            confidence = min(confidence, CLAMPED_CONFIDENCE)
            own = min(own, CLAMPED_CONFIDENCE)
        if threshold_error(xs, ys, predicted, slope, crossing) > MAX_THRESHOLD_ERROR_K:
            own = min(own, CLAMPED_CONFIDENCE)
        return LoadFit(
            Estimate(loss, Source.MEASURED, confidence, at),
            Estimate(fitted, Source.MEASURED, own, at),
            n,
            r_squared,
        )
    if not trusted(threshold):
        return None  # P-32: the loss alone only through a threshold that can be trusted
    # Too little spread to fit the threshold: fit H alone through the given threshold. R² means
    # little on such a narrow band, so quality is 1 − relative RMS error instead.
    spans = [threshold.value - x for x in xs]
    loss_per_day = sum(y * s for y, s in zip(ys, spans, strict=True)) / sum(s * s for s in spans)
    quality = _relative_quality(ys, [loss_per_day * s for s in spans])
    if loss_per_day <= 0 or quality < MIN_QUALITY:
        return None
    confidence = min(MAX_FIT_CONFIDENCE, coverage * quality * SINGLE_PARAMETER_PENALTY)
    loss, clamped = _clamped(ParameterKey.LOSS_COEFFICIENT, loss_per_day / HOURS_PER_DAY)
    if clamped:
        confidence = min(confidence, CLAMPED_CONFIDENCE)
    return LoadFit(Estimate(loss, Source.MEASURED, confidence, at), None, n, quality)


def threshold_error(
    xs: Sequence[float],
    ys: Sequence[float],
    predicted: Sequence[float],
    slope: float,
    crossing: float,
) -> float:
    """The standard error of the fitted threshold — where the line crosses zero energy — by the
    delta method: ``s / |slope| · √(1/n + (threshold − mean outdoor)² / Sxx)``, ``s`` the
    residuals' standard deviation. The further the threshold lies beyond the days, the larger
    it is. Infinite with too few days to judge (P-31)."""
    n = len(xs)
    if n <= 2 or slope == 0:
        return math.inf
    mean_x = sum(xs) / n
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx <= 0:
        return math.inf
    residual = sum((y - p) ** 2 for y, p in zip(ys, predicted, strict=True))
    deviation = math.sqrt(residual / (n - 2))
    return deviation / abs(slope) * math.sqrt(1.0 / n + (crossing - mean_x) ** 2 / sxx)


def _clamped(key: ParameterKey, value: float) -> tuple[float, bool]:
    """A fitted value within the parameter's plausible range, and whether it had to be held."""
    definition = PARAMETER_DEFS[key]
    held = min(definition.high, max(definition.low, value))
    return held, held != value


def _r_squared(observed: Sequence[float], predicted: Sequence[float]) -> float:
    mean = sum(observed) / len(observed)
    total = sum((y - mean) ** 2 for y in observed)
    residual = sum((y - p) ** 2 for y, p in zip(observed, predicted, strict=True))
    if total == 0:
        return 1.0 if residual == 0 else 0.0
    return max(0.0, 1.0 - residual / total)


def _relative_quality(observed: Sequence[float], predicted: Sequence[float]) -> float:
    mean = sum(observed) / len(observed)
    residual = sum((y - p) ** 2 for y, p in zip(observed, predicted, strict=True))
    rms = math.sqrt(residual / len(observed))
    return max(0.0, 1.0 - rms / mean)
