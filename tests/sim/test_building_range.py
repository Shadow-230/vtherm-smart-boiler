"""I13.4: the building fit's range on houses with a known heat loss and correlated days.

Two hundred seeded months of a house (``sim.house_days``) — its heat loss 0.25 kW/K, a daily
error of 10 % that carries half over to the next day, the sun left out of the fit. The range is
meant to hold the true loss 95 % of the time: it must in at least 90 % of the runs, and stay
narrow enough to say something.
"""

from __future__ import annotations

import statistics

import pytest

from custom_components.vtherm_smart_boiler.core.building import (
    MIN_RANGE_SHARE,
    fit_daily_load,
    measured_range,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    DEFAULT_CONFIDENCE,
    Estimate,
    Source,
)
from sim.house_days import HouseDays

RUNS = 200
DEFAULT_15 = Estimate(15.0, Source.DEFAULT, DEFAULT_CONFIDENCE)


def _runs(house: HouseDays, days: int) -> tuple[int, int, list[float], list[float]]:
    """How many runs gave a loss, how many of their ranges held the true one, the ranges'
    shares and the thresholds fitted."""
    fitted = covered = 0
    shares: list[float] = []
    thresholds: list[float] = []
    for seed in range(RUNS):
        fit = fit_daily_load(house.days(days, seed), DEFAULT_15)
        if fit is None or fit.loss is None:
            continue
        fitted += 1
        found = measured_range(fit.loss)
        assert found is not None
        covered += found[0] <= house.loss_kw_per_k <= found[1]
        assert fit.loss.range_share is not None
        shares.append(fit.loss.range_share)
        if fit.threshold is not None:
            thresholds.append(fit.threshold.value)
    return fitted, covered, shares, thresholds


def test_a_winter_months_range_holds_the_true_loss() -> None:
    """A winter month (30 days around 4 °C): the range holds the true loss in at least 90 % of
    the fits (186 of 194 when written), about ±18 % in the middle run, and under ±40 % in nine
    runs of ten."""
    fitted, covered, shares, _ = _runs(HouseDays(), 30)
    assert fitted >= 0.9 * RUNS
    assert covered >= 0.9 * fitted
    assert MIN_RANGE_SHARE <= statistics.median(shares) <= 0.25
    assert sorted(shares)[int(0.9 * len(shares))] <= 0.4


def test_without_the_allowance_for_correlated_days_the_range_would_be_too_narrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The allowance matters: with the days taken as independent, the same month's ranges hold
    the true loss less often (174 of 194 when written) than with it."""
    from custom_components.vtherm_smart_boiler.core import regression

    _, with_allowance, _, _ = _runs(HouseDays(), 30)
    monkeypatch.setattr(regression, "lag_one", lambda *_args: 0.0)
    _, without, _, _ = _runs(HouseDays(), 30)
    assert without < with_allowance


def test_a_noisier_house_gets_a_wider_range_that_still_holds() -> None:
    """A daily error of 20 %: wider ranges (about ±35 % in the middle run), still holding the
    true loss in at least 90 % of the fits."""
    fitted, covered, shares, _ = _runs(HouseDays(error_share=0.2), 30)
    assert covered >= 0.9 * fitted
    assert statistics.median(shares) > 0.25


def test_with_days_on_both_sides_the_threshold_comes_from_the_days() -> None:
    """Autumn — 45 days around 12 °C, many above the 15 °C default: the change point finds the
    house's own threshold (16 °C here) in the middle run within half a kelvin, and the range
    still holds the true loss in at least 90 % of the fits."""
    house = HouseDays(mean_outdoor=12.0, outdoor_sd=5.0)
    fitted, covered, _, thresholds = _runs(house, 45)
    assert fitted >= 0.9 * RUNS
    assert covered >= 0.9 * fitted
    assert statistics.median(thresholds) == pytest.approx(house.threshold, abs=0.5)
