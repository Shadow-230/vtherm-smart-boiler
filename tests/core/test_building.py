"""Building load: first estimates, the load model and the fit to recorded heating days."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.building import (
    COARSE_CONFIDENCE,
    DayPoint,
    InsulationClass,
    LoadModel,
    ThermalMass,
    fit_daily_load,
    loss_from_annual_energy,
    loss_from_coarse_answers,
    loss_from_design_load,
    time_constant_from_mass,
)
from custom_components.vtherm_smart_boiler.core.parameters import (
    Estimate,
    ParameterKey,
    ParameterSet,
    Source,
)


def test_design_load_is_the_users_entry() -> None:
    estimate = loss_from_design_load(8.0, design_outdoor=-20.0, indoor=20.0)
    assert estimate.value == pytest.approx(0.2)
    assert estimate.source is Source.ENTERED


def test_coarse_answers_are_a_low_confidence_default() -> None:
    estimate = loss_from_coarse_answers(150.0, InsulationClass.AVERAGE, -15.0, 20.0)
    assert estimate.value == pytest.approx(150 * 80 / 1000 / 35)
    assert estimate.source is Source.DEFAULT
    assert estimate.confidence == COARSE_CONFIDENCE


def test_annual_energy_estimate() -> None:
    estimate = loss_from_annual_energy(heating_energy_kwh=14_400.0, degree_days=3000.0)
    assert estimate.value == pytest.approx(0.2)
    assert estimate.source is Source.DEFAULT


@pytest.mark.parametrize(
    "call",
    [
        lambda: loss_from_design_load(0.0, -20.0, 20.0),
        lambda: loss_from_design_load(8.0, 20.0, 20.0),
        lambda: loss_from_coarse_answers(-1.0, InsulationClass.GOOD, -15.0, 20.0),
        lambda: loss_from_annual_energy(1000.0, 0.0),
    ],
)
def test_invalid_inputs_are_rejected(call) -> None:
    with pytest.raises(ValueError, match="positive"):
        call()


def test_thermal_mass_gives_a_time_constant() -> None:
    assert (
        time_constant_from_mass(ThermalMass.HEAVY).value
        > time_constant_from_mass(ThermalMass.LIGHT).value
    )


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
    fit = fit_daily_load(days, threshold=15.0, at=100.0)
    assert fit is not None
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
    fit = fit_daily_load(_days(0.3, 15.0, outdoors, noise), threshold=15.0)
    assert fit is not None
    assert fit.loss.value == pytest.approx(0.3, rel=0.1)


def test_narrow_outdoor_band_fits_loss_only() -> None:
    days = _days(0.2, 15.0, [4, 5, 6, 5, 4, 6, 5, 5])
    fit = fit_daily_load(days, threshold=15.0)
    assert fit is not None
    assert fit.threshold is None
    assert fit.loss.value == pytest.approx(0.2)


def test_fit_needs_enough_heating_days() -> None:
    assert fit_daily_load(_days(0.2, 15.0, [0, 2, 4, 6, 8, 10]), threshold=15.0) is None
    warm = _days(0.2, 25.0, [16, 17, 18, 19, 20, 21, 22, 23])
    assert fit_daily_load(warm, threshold=15.0) is None  # all days above the threshold


def test_fit_rejects_energy_rising_with_outdoor_temperature() -> None:
    days = [DayPoint(t, 10 + t) for t in [0, 2, 4, 6, 8, 10, 12, 1]]
    assert fit_daily_load(days, threshold=15.0) is None


def test_fit_rejects_scattered_data() -> None:
    energies = [50, 5, 60, 3, 70, 2, 55, 4]
    days = [DayPoint(t, e) for t, e in zip([0, 1, 2, 3, 4, 5, 6, 7], energies, strict=True)]
    assert fit_daily_load(days, threshold=15.0) is None


def test_a_fit_beyond_any_house_is_clamped_and_not_trusted() -> None:
    """P44: a fit outside the plausible range no longer raises at every analysis; it is kept at
    the bound with a confidence too low to be used."""
    fit = fit_daily_load(_days(8.0, 16.0, list(range(-10, 12, 2))), threshold=15.0)
    assert fit is not None
    assert fit.loss.value == 5.0
    assert fit.loss.confidence < 0.5


def test_a_month_of_good_days_gives_a_usable_confidence() -> None:
    """P44: confidence reachable — with thirty days of a clean fit it passes 0.5."""
    outdoors = [(-5 + (i % 15)) * 1.0 for i in range(30)]
    fit = fit_daily_load(_days(0.2, 16.0, outdoors), threshold=15.0)
    assert fit is not None
    assert fit.loss.confidence >= 0.5
