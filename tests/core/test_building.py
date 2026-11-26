"""Building load: first estimates, the load model and the fit to recorded heating days."""

from __future__ import annotations

import math
import random

import pytest

from custom_components.vtherm_smart_boiler.core import building
from custom_components.vtherm_smart_boiler.core.building import (
    ANNUAL_ENERGY_CONFIDENCE,
    CLAMPED_CONFIDENCE,
    MAX_RANGE_SHARE,
    MAX_THRESHOLD_ERROR_K,
    MAX_USED_RANGE_SHARE,
    MIN_FIT_DAYS,
    MIN_KNOWN_DAYS,
    MIN_QUALITY,
    MIN_RANGE_SHARE,
    SINGLE_PARAMETER_PENALTY,
    DayPoint,
    LoadModel,
    change_point,
    fit_daily_load,
    loss_from_annual_energy,
    loss_from_design_load,
    measured_range,
    threshold_error,
    trusted,
    trusted_load_model,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    DEFAULT_CONFIDENCE,
    MIN_CONFIDENCE,
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)
from custom_components.vtherm_smart_boiler.core.regression import fit_line

# The threshold a fit is given: the user's entry, or the class default nothing supports (P-32).
ENTERED_15 = Estimate(15.0, Source.ENTERED)
DEFAULT_15 = Estimate(15.0, Source.DEFAULT, DEFAULT_CONFIDENCE)


def test_design_load_is_the_users_entry() -> None:
    estimate = loss_from_design_load(8.0, design_outdoor=-20.0, indoor=20.0)
    assert estimate.value == pytest.approx(0.2)
    assert estimate.source is Source.ENTERED


def test_no_rule_of_thumb_from_floor_area_insulation_or_mass() -> None:
    """I8 (decision B5): the floor area, the insulation class and the thermal mass are gone —
    no function needed their rough estimates; the time constant they gave was read by none."""
    from custom_components.vtherm_smart_boiler.core import building

    for name in (
        "InsulationClass",
        "ThermalMass",
        "loss_from_coarse_answers",
        "time_constant_from_mass",
        "COARSE_CONFIDENCE",
    ):
        assert not hasattr(building, name), name
    assert "THERMAL_TIME_CONSTANT" not in ParameterKey.__members__


def test_annual_energy_estimate() -> None:
    estimate = loss_from_annual_energy(heating_energy_kwh=14_400.0, degree_days=3000.0)
    assert estimate.value == pytest.approx(0.2)
    assert estimate.source is Source.DEFAULT


@pytest.mark.parametrize(
    "call",
    [
        lambda: loss_from_design_load(0.0, -20.0, 20.0),
        lambda: loss_from_design_load(8.0, 20.0, 20.0),
        lambda: loss_from_annual_energy(1000.0, 0.0),
    ],
)
def test_invalid_inputs_are_rejected(call) -> None:
    with pytest.raises(ValueError, match="positive"):
        call()


def test_load_model() -> None:
    model = LoadModel(loss_coefficient=0.2, heating_threshold=15.0)
    assert model.load_kw(15.0) == 0.0
    assert model.load_kw(20.0) == 0.0
    assert model.load_kw(-5.0) == pytest.approx(4.0)
    assert model.outdoor_at_load(3.0) == pytest.approx(0.0)


def test_load_model_from_parameters_needs_a_loss_coefficient() -> None:
    assert LoadModel.from_parameters(ParameterSet()) is None
    params = ParameterSet().with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(0.25, Source.ENTERED)
    )
    assert LoadModel.from_parameters(params) == LoadModel(0.25, 15.0)


def _days(loss: float, threshold: float, outdoors: list[float], noise: list[float] | None = None):
    noise = noise or [0.0] * len(outdoors)
    return [
        DayPoint(t, 24 * loss * (threshold - t) * (1 + n))
        for t, n in zip(outdoors, noise, strict=True)
    ]


def test_fit_recovers_loss_and_threshold() -> None:
    days = _days(0.2, 16.0, [-5, -2, 0, 2, 4, 6, 8, 10, 12, 1, 3, 5])
    fit = fit_daily_load(days, threshold=DEFAULT_15, at=100.0)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.2)
    assert fit.threshold is not None
    assert fit.threshold.value == pytest.approx(16.0)
    assert fit.loss.source is Source.MEASURED
    assert fit.loss.at == 100.0
    assert fit.days == 12
    assert fit.quality == pytest.approx(1.0)
    assert 0 < fit.loss.confidence <= 0.95


def test_fit_with_noise_stays_close() -> None:
    outdoors = [-8, -6, -4, -2, 0, 2, 4, 6, 8, 10, -3, 1, 5, 9]
    noise = [
        0.05,
        -0.04,
        0.03,
        -0.05,
        0.02,
        -0.03,
        0.04,
        -0.02,
        0.05,
        -0.04,
        0.01,
        0.0,
        -0.01,
        0.03,
    ]
    fit = fit_daily_load(_days(0.3, 15.0, outdoors, noise), threshold=DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.3, rel=0.1)


def test_narrow_outdoor_band_fits_loss_only() -> None:
    """Through the threshold the user entered (P-32): the loss alone, the threshold not fitted."""
    days = _days(0.2, 15.0, [4, 5, 6, 5, 4, 6, 5, 5])
    fit = fit_daily_load(days, threshold=ENTERED_15)
    assert fit is not None
    assert fit.threshold is None
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.2)


def test_fit_needs_enough_heating_days() -> None:
    assert fit_daily_load(_days(0.2, 15.0, [0, 2, 4, 6, 8, 10]), threshold=ENTERED_15) is None
    warm = _days(0.2, 25.0, [16, 17, 18, 19, 20, 21, 22, 23])
    assert fit_daily_load(warm, threshold=ENTERED_15) is None  # all days above the threshold


def test_fit_rejects_energy_rising_with_outdoor_temperature() -> None:
    days = [DayPoint(t, 10 + t) for t in [0, 2, 4, 6, 8, 10, 12, 1]]
    assert fit_daily_load(days, threshold=DEFAULT_15) is None


def test_fit_rejects_scattered_data() -> None:
    energies = [50, 5, 60, 3, 70, 2, 55, 4]
    days = [DayPoint(t, e) for t, e in zip([0, 1, 2, 3, 4, 5, 6, 7], energies, strict=True)]
    assert fit_daily_load(days, threshold=ENTERED_15) is None


def test_a_fit_beyond_any_house_is_clamped_and_not_trusted() -> None:
    """P44: a fit outside the plausible range no longer raises at every analysis; it is kept at
    the bound with a confidence too low to be used."""
    fit = fit_daily_load(_days(8.0, 16.0, list(range(-10, 12, 2))), threshold=DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.value == 5.0
    assert fit.loss.confidence < 0.5


def test_a_month_of_good_days_gives_a_usable_confidence() -> None:
    """P44: confidence reachable — with thirty days of a clean fit it passes 0.5."""
    outdoors = [(-5 + (i % 15)) * 1.0 for i in range(30)]
    fit = fit_daily_load(_days(0.2, 16.0, outdoors), threshold=DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.confidence >= 0.5


def _noisy(
    loss: float, threshold: float, outdoors: list[float], noise: float, seed: int
) -> list[DayPoint]:
    """Days of a house with ``loss`` and ``threshold``, each day's energy off by a random share
    (``noise``, one standard deviation) — the same days for the same seed."""
    rng = random.Random(seed)
    return [
        DayPoint(t, 24 * loss * (threshold - t) * (1 + rng.gauss(0.0, noise))) for t in outdoors
    ]


def _band(low: float, high: float, count: int = 30) -> list[float]:
    return [low + (high - low) * i / (count - 1) for i in range(count)]


def test_a_threshold_from_a_narrow_cold_band_is_not_trusted() -> None:
    """T-41 (P-31): 30 days at −4.5…0 °C, 8 % noise, a true threshold of 16 °C. The threshold
    is extrapolated 16 K beyond the days; it is not fitted at all under an 8 K spread — with the
    class default given, nothing is; with the user's threshold, the loss alone."""
    days = _noisy(0.2, 16.0, _band(-4.5, 0.0), 0.08, seed=41)
    assert fit_daily_load(days, DEFAULT_15) is None  # PB-95: exactly nothing
    fit = fit_daily_load(days, ENTERED_15)
    assert fit is not None
    assert fit.threshold is None  # not fitted, not merely distrusted
    assert fit.loss is not None


def test_a_threshold_far_beyond_a_wide_cold_band_is_capped() -> None:
    """P-31: a 12 K spread, but far below the threshold, with 8 % noise: its standard error
    (delta method) is over 2 K, so it is shown at ``CLAMPED_CONFIDENCE`` and never used."""
    days = _noisy(0.2, 16.0, _band(-20.0, -8.0), 0.08, seed=31)
    fit = fit_daily_load(days, DEFAULT_15)
    assert fit is not None  # the fit ran, its quality enough …
    assert fit.threshold is not None
    assert fit.threshold.confidence <= CLAMPED_CONFIDENCE  # … the cap decided
    assert fit.loss is not None
    assert fit.loss.confidence >= MIN_CONFIDENCE  # the slope itself is well determined


def test_a_wide_spread_fits_a_trusted_threshold() -> None:
    """The positive control: 30 days at −5…+10 °C with the same 8 % noise give the threshold
    within 2 K, trusted."""
    days = _noisy(0.2, 16.0, _band(-5.0, 10.0), 0.08, seed=41)
    fit = fit_daily_load(days, DEFAULT_15, at=100.0)
    assert fit is not None
    assert fit.threshold is not None
    assert fit.threshold.value == pytest.approx(16.0, abs=2.0)
    assert fit.threshold.confidence >= MIN_CONFIDENCE
    assert fit.threshold.source is Source.MEASURED
    assert fit.threshold.at == 100.0
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.2, rel=0.15)


def test_the_threshold_has_its_own_confidence() -> None:
    """P-31: the threshold's confidence also weighs the spread (full from 12 K on), the loss's
    does not: 9 K of clean days give the loss 0.95 and the threshold 0.75."""
    days = _noisy(0.2, 16.0, _band(-4.0, 5.0), 0.0, seed=1)
    fit = fit_daily_load(days, DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.threshold is not None
    assert fit.loss.confidence == pytest.approx(0.95)
    assert fit.threshold.confidence == pytest.approx(0.75)
    assert fit.threshold.value == pytest.approx(16.0)


def test_loss_alone_through_a_default_threshold_is_not_trusted() -> None:
    """T-42 (P-32): 30 days at 8–11.5 °C of a house whose threshold is 18 °C, the class default
    15 °C (confidence 0.2) given: the loss fitted through it would be biased (+57 %) — it is not
    fitted, and a measured loss never becomes effective."""
    days = _noisy(0.2, 18.0, _band(8.0, 11.5), 0.05, seed=42)
    default = ParameterSet().get(ParameterKey.HEATING_THRESHOLD).effective()
    assert default is not None
    assert default.source is Source.DEFAULT
    assert fit_daily_load(days, default) is None  # PB-95: not fitted at all
    # Nor through a measured threshold without the confidence the plugin counts, or unknown.
    for weak in (Estimate(15.0, Source.MEASURED, 0.3), Estimate(15.0, Source.LEARNED, 0.0)):
        assert fit_daily_load(days, weak) is None, weak


def test_loss_alone_with_an_entered_threshold_is_fitted() -> None:
    """P-32: the same days through the threshold the user entered, or one measured with the
    confidence the plugin counts, give the loss alone — trusted, the threshold not fitted."""
    days = _noisy(0.2, 18.0, _band(8.0, 11.5), 0.05, seed=42)
    for given in (Estimate(18.0, Source.ENTERED), Estimate(18.0, Source.MEASURED, 0.6)):
        fit = fit_daily_load(days, given)
        assert fit is not None, given
        assert fit.threshold is None
        assert fit.loss is not None
        assert fit.loss.value == pytest.approx(0.2, rel=0.1)
        assert fit.loss.confidence >= MIN_CONFIDENCE


def _parameters(**estimates: Estimate) -> ParameterSet:
    parameters = ParameterSet()
    for key, estimate in estimates.items():
        parameters = parameters.with_estimate(ParameterKey(key), estimate)
    return parameters


def test_the_load_model_decides_only_when_entered_or_confidently_measured() -> None:
    """S-17: both the loss and the threshold entered, or measured or learned with at least
    ``MIN_CONFIDENCE``; a rule of thumb (the class default threshold, a default loss) makes no
    trusted model, whatever the loss."""
    entered = Estimate(0.2, Source.ENTERED)
    threshold = Estimate(16.0, Source.ENTERED)
    assert trusted_load_model(_parameters(loss_coefficient=entered, heating_threshold=threshold))
    measured = Estimate(0.2, Source.MEASURED, 0.6)
    learned = Estimate(16.0, Source.LEARNED, 0.5)
    assert trusted_load_model(_parameters(loss_coefficient=measured, heating_threshold=learned))
    coarse = Estimate(0.34, Source.DEFAULT, 0.3)
    for loss, given in (
        (entered, None),  # the class default threshold
        (coarse, threshold),
        (Estimate(0.2, Source.MEASURED, 0.4), threshold),
        (entered, Estimate(16.0, Source.MEASURED, 0.3)),
    ):
        estimates = {"loss_coefficient": loss}
        if given is not None:
            estimates["heating_threshold"] = given
        assert trusted_load_model(_parameters(**estimates)) is None, (loss, given)
    assert trusted_load_model(ParameterSet()) is None  # nothing at all


def test_nothing_to_trust_decides_nothing() -> None:
    """Without an estimate there is nothing that may decide (Y3)."""
    assert not trusted(None)


def test_a_poor_fit_over_a_wide_spread_gives_none() -> None:
    """P-31: energies that do not follow the outdoor temperature over a wide spread give no fit,
    rather than a line through noise (R² below ``MIN_QUALITY``)."""
    outdoor = [-5.0, -3.0, -1.0, 1.0, 3.0, 5.0, 7.0, 9.0]
    energy = [100.0, 20.0, 95.0, 15.0, 90.0, 10.0, 85.0, 5.0]
    days = [DayPoint(x, y) for x, y in zip(outdoor, energy, strict=True)]
    assert fit_daily_load(days, ENTERED_15) is None


def test_a_loss_held_at_its_bound_is_shown_never_trusted() -> None:
    """A loss fitted alone beyond the parameter's bound is held at the bound, its confidence
    capped at ``CLAMPED_CONFIDENCE`` — shown, never used — however many days support it."""
    outdoor = [11.0 + 0.1 * i for i in range(31)]  # a month on a 3 K band: full coverage
    days = [DayPoint(x, 24.0 * 6.0 * (15.0 - x)) for x in outdoor]
    fit = fit_daily_load(days, ENTERED_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.value == 5.0
    assert fit.loss.confidence == CLAMPED_CONFIDENCE


def test_the_threshold_error_is_infinite_without_enough_to_judge() -> None:
    """P-31: two days, a flat line, or one outdoor temperature cannot place the threshold."""
    assert threshold_error([1.0, 2.0], [10.0, 5.0], [10.0, 5.0], -5.0, 3.0) == math.inf
    flat = [9.0, 6.0, 3.0]
    assert threshold_error([1.0, 2.0, 3.0], flat, flat, 0.0, 3.0) == math.inf
    assert threshold_error([2.0, 2.0, 2.0], flat, [6.0, 6.0, 6.0], -3.0, 4.0) == math.inf


# --- Mutation testing (2026-10-12): edges of refusals, the days counted, confidences and caps ---


@pytest.mark.parametrize(
    ("design_load_kw", "design_outdoor", "indoor", "expected"),
    [
        (1.0, -20.0, 20.0, 0.025),  # a design load of 1 kW
        (2.0, 10.0, 11.0, 2.0),  # 1 K between the design outdoor and indoor temperatures
    ],
)
def test_a_small_but_positive_design_load_or_span_is_accepted(
    design_load_kw: float, design_outdoor: float, indoor: float, expected: float
) -> None:
    """Only a design load or a span of zero or less is refused; small positive ones count."""
    estimate = loss_from_design_load(design_load_kw, design_outdoor, indoor)
    assert estimate.value == pytest.approx(expected)


@pytest.mark.parametrize(
    ("energy_kwh", "degree_days", "expected"),
    [
        (1.0, 2.0, 1.0 / 48.0),  # 1 kWh in a year
        (48.0, 1.0, 2.0),  # 1 K·day in a year
    ],
)
def test_a_small_but_positive_annual_energy_or_degree_days_is_accepted(
    energy_kwh: float, degree_days: float, expected: float
) -> None:
    """Only energy or degree-days of zero or less are refused; the estimate is a rule of thumb
    with its own low confidence."""
    estimate = loss_from_annual_energy(energy_kwh, degree_days)
    assert estimate.value == pytest.approx(expected)
    assert estimate.confidence == ANNUAL_ENERGY_CONFIDENCE


def test_no_annual_energy_gives_no_estimate() -> None:
    """Negative: a year without heating energy gives no loss coefficient."""
    with pytest.raises(ValueError, match="positive"):
        loss_from_annual_energy(0.0, 3000.0)


@pytest.mark.parametrize(
    ("extra", "counted"),
    [
        (DayPoint(20.0, 10.0), 8),  # warmer than the threshold: not a heating day
        (DayPoint(15.0, 10.0), 8),  # exactly at the threshold: not colder than it
        (DayPoint(5.0, 0.0), 8),  # no energy
        (_days(0.2, 15.0, [14.9])[0], 9),  # 0.48 kWh, just below the threshold: counted
    ],
)
def test_only_days_colder_than_the_threshold_with_energy_count(
    extra: DayPoint, counted: int
) -> None:
    """Negative: a day at or above the threshold, or without energy, is not a heating day;
    a day just below it with a little energy is."""
    days = [*_days(0.2, 15.0, [-4, -2, 0, 2, 4, 6, 8, 10]), extra]
    fit = fit_daily_load(days, ENTERED_15)
    assert fit is not None
    assert fit.days == counted


def test_exactly_the_minimum_number_of_days_gives_a_fit() -> None:
    """``MIN_FIT_DAYS`` heating days are enough (one fewer is not: above)."""
    fit = fit_daily_load(_days(0.2, 15.0, [4, 5, 6, 5, 4, 6, 5]), ENTERED_15)
    assert fit is not None
    assert fit.days == MIN_FIT_DAYS


@pytest.mark.parametrize("count", [21, 60])
def test_the_loss_fitted_alone_weighs_coverage_quality_and_the_penalty(count: int) -> None:
    """Fitted alone, the loss's confidence is coverage (full from 30 days on, never more) times
    quality times the single-parameter penalty; the fit keeps its days, quality and time."""
    days = _noisy(0.2, 15.0, _band(8.0, 11.5, count), 0.05, seed=7)
    fit = fit_daily_load(days, ENTERED_15, at=100.0)
    assert fit is not None
    assert fit.threshold is None
    assert fit.days == count
    assert MIN_QUALITY <= fit.quality < 1.0
    assert fit.loss is not None
    assert fit.loss.source is Source.MEASURED
    assert fit.loss.at == 100.0
    coverage = min(1.0, count / 30)
    assert fit.loss.confidence == pytest.approx(coverage * fit.quality * SINGLE_PARAMETER_PENALTY)


def test_a_small_house_is_fitted_alone_too() -> None:
    """A loss of 0.02 kW/K (under 1 kWh per day and kelvin) is fitted like any other."""
    fit = fit_daily_load(_days(0.02, 15.0, [4, 5, 6, 5, 4, 6, 5, 5]), ENTERED_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.02)


def test_a_spread_of_exactly_the_minimum_fits_the_threshold() -> None:
    """P-31: an outdoor spread of exactly ``MIN_OUTDOOR_SPREAD_K`` (8 K) fits the threshold too —
    with the class default given, which alone would fit nothing."""
    fit = fit_daily_load(_days(0.2, 16.0, [-4, -3, -2, -1, 0, 1, 2, 3, 4]), DEFAULT_15)
    assert fit is not None
    assert fit.threshold is not None
    assert fit.threshold.value == pytest.approx(16.0)


@pytest.mark.parametrize("rise", [0.0, 0.5])
def test_energy_flat_or_gently_rising_with_outdoor_temperature_gives_no_fit(rise: float) -> None:
    """Negative: energy that does not fall as it gets warmer — the same every day, or rising
    a little — is no heating load, whatever the spread."""
    days = [DayPoint(t, 10.0 + rise * t) for t in [-4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0, 10.0]]
    assert fit_daily_load(days, DEFAULT_15) is None


def test_a_fit_of_exactly_the_minimum_quality_is_kept() -> None:
    """R² of exactly ``MIN_QUALITY`` is enough. The days (two clusters 8 K apart, energies in
    quarter kWh) make R² exactly 0.5 and the energies' total square deviation exactly 1."""
    cold = [DayPoint(0.0, e) for e in (10.0, 9.5, 10.0, 9.5)]
    mild = [DayPoint(8.0, e) for e in (9.5, 9.0, 9.5, 9.0)]
    fit = fit_daily_load([*cold, *mild], DEFAULT_15)
    assert fit is not None
    assert fit.quality == MIN_QUALITY


def test_a_loss_fitted_alone_of_exactly_the_minimum_quality_is_kept() -> None:
    """1 − relative RMS error of exactly ``MIN_QUALITY`` is enough: energies of 15 and 5 kWh at
    one outdoor temperature are off their mean by exactly half of it."""
    fit = fit_daily_load([DayPoint(7.0, e) for e in (15.0, 5.0) * 4], ENTERED_15)
    assert fit is not None
    assert fit.quality == MIN_QUALITY


def test_both_confidences_weigh_coverage_and_r_squared_the_threshold_its_spread_to_full() -> None:
    """P-31: with 24 noisy days over an 18 K spread, both the loss and the threshold weigh
    coverage (24 of 30 days) times R² — the spread beyond ``FULL_SPREAD_K`` adds nothing."""
    days = _noisy(0.2, 16.0, _band(-5.0, 13.0, 24), 0.05, seed=3)
    fit = fit_daily_load(days, DEFAULT_15)
    assert fit is not None
    assert fit.quality < 1.0
    assert fit.loss is not None
    assert fit.threshold is not None
    assert fit.loss.confidence == pytest.approx(0.8 * fit.quality)
    assert fit.threshold.confidence == pytest.approx(0.8 * fit.quality)


@pytest.mark.parametrize(("count", "used"), [(20, False), (21, True)])
def test_a_fit_from_under_three_weeks_of_heating_is_shown_never_used(
    count: int, used: bool
) -> None:
    """K4 (the user's decision of 2026-11-17): published methods need about 3 weeks of
    heating-season data — a fit from fewer than ``MIN_KNOWN_DAYS`` heating days is shown at
    ``CLAMPED_CONFIDENCE``, never used, both values and either kind of fit; from 21 its
    confidence is weighed as before (the loss alone, with its penalty, a little later)."""
    assert MIN_KNOWN_DAYS == 21
    wide = fit_daily_load(_days(0.2, 16.0, _band(-5.0, 13.0, count)), DEFAULT_15)
    alone = fit_daily_load(_days(0.2, 15.0, _band(8.0, 11.5, count)), ENTERED_15)
    assert wide is not None
    assert wide.loss is not None
    assert wide.threshold is not None
    assert trusted(wide.loss) is used
    assert trusted(wide.threshold) is used
    assert alone is not None
    assert alone.loss is not None
    clamped = alone.loss.confidence == CLAMPED_CONFIDENCE
    assert clamped is not used
    assert alone.loss.confidence == pytest.approx(
        CLAMPED_CONFIDENCE if not used else count / 30 * alone.quality * SINGLE_PARAMETER_PENALTY
    )


@pytest.mark.parametrize(
    ("loss", "threshold"),
    [
        (8.0, 16.0),  # the loss beyond its bound, the threshold not
        (0.2, 25.0),  # the threshold beyond its bound, the loss not
    ],
)
def test_either_value_held_at_its_bound_caps_both_confidences(
    loss: float, threshold: float
) -> None:
    """Negative: a month of clean days, but one fitted value outside its plausible range — both
    the loss and the threshold are shown at ``CLAMPED_CONFIDENCE``, never used."""
    fit = fit_daily_load(_days(loss, threshold, _band(-5.0, 10.0)), DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.threshold is not None
    assert fit.loss.confidence == CLAMPED_CONFIDENCE
    assert fit.threshold.confidence == CLAMPED_CONFIDENCE


def test_a_threshold_error_of_exactly_the_limit_does_not_cap() -> None:
    """P-31: only a standard error above ``MAX_THRESHOLD_ERROR_K`` caps the threshold. Thirty
    days in two clusters 12 K apart (slope −3 kWh/K, threshold 16 °C, residual square sum 6048)
    give a standard error of exactly 2 K: the threshold keeps its own confidence."""
    cold = [DayPoint(-2.0, e) for e in [72.0] * 7 + [36.0] * 7 + [54.0]]
    mild = [DayPoint(10.0, e) for e in [30.0] * 5 + [6.0] * 5 + [24.0, 12.0, 18.0, 18.0, 18.0]]
    days = [*cold, *mild]
    xs = [d.outdoor_mean for d in days]
    ys = [d.energy_kwh for d in days]
    predicted = [54.0] * 15 + [18.0] * 15
    assert threshold_error(xs, ys, predicted, -3.0, 16.0) == MAX_THRESHOLD_ERROR_K
    fit = fit_daily_load(days, DEFAULT_15)
    assert fit is not None
    assert fit.threshold is not None
    assert fit.threshold.value == pytest.approx(16.0)
    assert fit.threshold.confidence == pytest.approx(fit.quality)
    assert fit.threshold.confidence > CLAMPED_CONFIDENCE


def test_the_threshold_error_by_the_delta_method() -> None:
    """P-31: ``s / |slope| · √(1/n + (threshold − mean outdoor)² / Sxx)``, from three days on and
    over any spread: s = 2, |slope| = 4, n = 3, Sxx = 0.5, the threshold 2 K from the mean."""
    error = threshold_error([0.0, 0.5, 1.0], [12.0, 7.0, 4.0], [10.0, 7.0, 4.0], -4.0, 2.5)
    assert error == pytest.approx(2.5 / math.sqrt(3.0))


# --- I13.4: the range from the fit, the change point ------------------------------------------


def _dated(points: list[DayPoint], apart: float = 86400.0) -> list[DayPoint]:
    """The points with their days' starts, ``apart`` seconds after each other."""
    return [DayPoint(p.outdoor_mean, p.energy_kwh, i * apart) for i, p in enumerate(points)]


def _line_share(days: list[DayPoint]) -> float:
    """The range the fit should give: t times the slope's widened error over the slope."""
    line = fit_line([d.outdoor_mean for d in days], [d.energy_kwh for d in days])
    assert line is not None
    return line.t * line.slope_error / -line.slope


def test_a_clean_fit_has_the_floor_range() -> None:
    """Days on a perfect line: no error, the range is the ±15 % floor (I13.4)."""
    fit = fit_daily_load(_dated(_days(0.2, 16.0, _band(-5.0, 13.0))), DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.range_share == MIN_RANGE_SHARE
    assert measured_range(fit.loss) == pytest.approx((0.17, 0.23))
    assert fit.threshold is not None
    assert fit.threshold.range_share is None  # the threshold keeps its own error rule


def test_a_noisy_fit_takes_its_range_from_the_fit() -> None:
    """Thirty days, 15 % noise: the range is t times the slope's error over the slope, wider
    than the floor; its days in time order."""
    days = _dated(_noisy(0.2, 16.0, _band(-5.0, 13.0), 0.15, seed=5))
    fit = fit_daily_load(days, DEFAULT_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.range_share is not None
    assert fit.loss.range_share == pytest.approx(_line_share(days))
    assert fit.loss.range_share > MIN_RANGE_SHARE


def _wave(order: list[int], error: float = 12.0) -> list[DayPoint]:
    """Thirty days of a 0.2 kW/K house over −5…13 °C, each off by ``error`` kWh either way in
    the pattern ``order`` gives (+1 or −1 per day)."""
    return _dated(
        [
            DayPoint(t, 24 * 0.2 * (16.0 - t) + error * sign)
            for t, sign in zip(_band(-5.0, 13.0), order, strict=True)
        ]
    )


def test_correlated_days_widen_the_range() -> None:
    """The same errors, once day after day alike (a cold spell, the building's mass) and once
    alternating: the correlated days give the wider range."""
    alike = _wave(([1] * 3 + [-1] * 3) * 5)
    alternating = _wave([1, -1] * 15)
    wide = fit_daily_load(alike, DEFAULT_15)
    narrow = fit_daily_load(alternating, DEFAULT_15)
    assert wide is not None
    assert narrow is not None
    assert wide.loss is not None
    assert narrow.loss is not None
    assert wide.loss.range_share is not None
    assert narrow.loss.range_share is not None
    assert wide.loss.range_share > narrow.loss.range_share


def test_days_are_taken_in_time_order_and_a_gap_breaks_their_pair() -> None:
    """Days handed over in any order are put in time order; days a week apart do not follow
    each other, so they get no allowance for correlation."""
    alike = _wave(([1] * 3 + [-1] * 3) * 5)
    shuffled = alike[::2] + alike[1::2]
    apart = _dated(alike, 7 * 86400.0)
    in_order = fit_daily_load(alike, DEFAULT_15)
    any_order = fit_daily_load(shuffled, DEFAULT_15)
    weekly = fit_daily_load(apart, DEFAULT_15)
    assert in_order is not None
    assert any_order is not None
    assert weekly is not None
    assert in_order.loss is not None
    assert any_order.loss is not None
    assert weekly.loss is not None
    assert any_order.loss.range_share == pytest.approx(in_order.loss.range_share)
    assert weekly.loss.range_share is not None
    assert in_order.loss.range_share is not None
    assert weekly.loss.range_share < in_order.loss.range_share


def test_a_range_too_wide_is_shown_never_used() -> None:
    """A month whose days are off by 3 kWh in three runs of ten (a long spell): the line fits
    well, but such correlated days leave hardly a degree of freedom — the range is held at
    ±100 %, wider than ±50 %: the loss is shown, never used."""
    fit = fit_daily_load(_wave([1] * 10 + [-1] * 10 + [1] * 10, error=3.0), DEFAULT_15)
    assert fit is not None
    assert fit.quality > 0.95
    assert fit.loss is not None
    assert fit.loss.range_share == MAX_RANGE_SHARE
    assert fit.loss.range_share > MAX_USED_RANGE_SHARE
    assert fit.loss.confidence == CLAMPED_CONFIDENCE
    assert not trusted(fit.loss)


def test_the_loss_alone_carries_its_range_too() -> None:
    """Fitted alone through the user's threshold, the loss has its range — the floor for clean
    days, wider for days off by ±20 % in runs of five."""
    clean = fit_daily_load(_dated(_days(0.2, 15.0, _band(8.0, 11.5))), ENTERED_15)
    noisy = fit_daily_load(_runs_off(0.2, ([1] * 5 + [-1] * 5) * 3), ENTERED_15)
    assert clean is not None
    assert noisy is not None
    assert clean.loss is not None
    assert noisy.loss is not None
    assert clean.loss.range_share == MIN_RANGE_SHARE
    assert noisy.loss.range_share is not None
    assert noisy.loss.range_share > MIN_RANGE_SHARE


def test_a_loss_alone_too_uncertain_is_shown_never_used() -> None:
    """Fitted alone over a month of days off by ±30 % in three runs of ten: its range is wider
    than ±50 % — shown, never used."""
    fit = fit_daily_load(_runs_off(0.3, [1] * 10 + [-1] * 10 + [1] * 10), ENTERED_15)
    assert fit is not None
    assert fit.loss is not None
    assert fit.loss.range_share is not None
    assert fit.loss.range_share > MAX_USED_RANGE_SHARE
    assert fit.loss.confidence == CLAMPED_CONFIDENCE


def _runs_off(share: float, order: list[int]) -> list[DayPoint]:
    """Thirty days at 8…11.5 °C of a 0.2 kW/K house with a 15 °C threshold, each off by
    ``share`` of its energy either way in the pattern ``order`` gives."""
    return _dated(
        [
            DayPoint(t, 24 * 0.2 * (15.0 - t) * (1 + share * sign))
            for t, sign in zip(_band(8.0, 11.5), order, strict=True)
        ]
    )


def test_a_value_kept_before_ranges_has_none() -> None:
    """A measured loss stored before I13.4 has no range until the next analysis fits one."""
    assert measured_range(Estimate(0.2, Source.MEASURED, 0.8)) is None
    assert measured_range(Estimate(0.2, Source.MEASURED, 0.8, None, 1.5)) == pytest.approx(
        (0.0, 0.5)
    )  # never below zero


def _both_sides(warm: int) -> list[DayPoint]:
    """A 0.2 kW/K house that needs heat below 17 °C: 30 days from −5 to 16.5 °C, and ``warm``
    days from 18 °C up without heat."""
    cold = _days(0.2, 17.0, _band(-5.0, 16.5))
    return _dated([*cold, *(DayPoint(18.0 + i, 0.0) for i in range(warm))])


def test_with_a_week_on_each_side_the_threshold_comes_from_the_days() -> None:
    """I13.4: with at least a week of days on each side of the threshold in use (15 °C), the
    change point is the house's own: 17 °C."""
    assert change_point(_both_sides(10), 15.0) == pytest.approx(17.0)


@pytest.mark.parametrize("warm", [0, 6])
def test_without_a_week_on_each_side_no_change_point(warm: int) -> None:
    """Six warm days are not a week: the threshold in use stays (``None``)."""
    days = [d for d in _both_sides(warm) if d.outdoor_mean < 15.0 or d.energy_kwh == 0.0]
    assert change_point(days, 15.0) is None


def test_no_change_point_without_more_heat_on_colder_days() -> None:
    """Days whose energy rises with the outdoor temperature show no heating threshold."""
    days = [DayPoint(t, t) for t in _band(0.0, 25.0)]
    assert change_point(days, 15.0) is None


def test_the_change_point_keeps_cool_nights_out_of_the_heating_days() -> None:
    """Days just above the house's threshold with a little heat (cool nights) flatten the line
    when the threshold in use takes them in (20 °C, the user's): the change point leaves them
    out, and the loss comes out right."""
    cold = _days(0.2, 15.0, _band(-5.0, 14.5, 20))
    nights = [DayPoint(15.5 + i * 0.5, 1.0) for i in range(8)]
    summer = [DayPoint(20.5 + i, 0.0) for i in range(8)]
    entered_20 = Estimate(20.0, Source.ENTERED)
    found = fit_daily_load(_dated([*cold, *nights, *summer]), entered_20)
    taken_in = fit_daily_load(_dated([*cold, *nights]), entered_20)  # no warm week: no point
    assert found is not None
    assert taken_in is not None
    assert found.loss is not None
    assert taken_in.loss is not None
    assert found.loss.value == pytest.approx(0.2, rel=0.03)
    assert taken_in.loss.value < 0.19


def test_a_change_point_with_too_little_spread_below_fits_the_loss_alone() -> None:
    """Days below the change point spread under 8 K: the loss alone, through the threshold
    given (the user's), over the days below it."""
    cold = _days(0.2, 15.0, _band(8.0, 14.0, 20))
    summer = [DayPoint(16.0 + i, 0.0) for i in range(8)]
    fit = fit_daily_load(_dated([*cold, *summer]), ENTERED_15)
    assert fit is not None
    assert fit.threshold is None
    assert fit.loss is not None
    assert fit.loss.value == pytest.approx(0.2)


@pytest.mark.parametrize(
    ("fitted", "share"),
    [(0.05, MIN_RANGE_SHARE), (0.3, 0.3), (7.0, MAX_RANGE_SHARE), (math.inf, MAX_RANGE_SHARE)],
)
def test_a_range_is_held_between_its_floor_and_its_cap(fitted: float, share: float) -> None:
    """±15 % at least, ±100 % at most — an error with no degrees of freedom left (infinite, or
    zero times infinite) is the widest."""
    assert building._share(fitted) == share
    assert building._share(math.nan) == MAX_RANGE_SHARE
