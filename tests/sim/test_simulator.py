"""The simulator's physics, and simulated history passing through the core."""

from __future__ import annotations

import dataclasses

import pytest
from custom_components.boiler_sim.profiles import BOILERS, HOUSES, radiator_zones

from custom_components.vtherm_smart_boiler.core.building import fit_daily_load
from custom_components.vtherm_smart_boiler.core.cycles import BurnKind
from custom_components.vtherm_smart_boiler.core.monitor import daily_points, summarize, verdict
from custom_components.vtherm_smart_boiler.core.parameters import Estimate, ParameterKey, Source
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.core.verdict import ReasonCode, Verdict
from sim.simulator import (
    DAY,
    DEFAULT_SIGNALS,
    WATER_KWH_PER_L_K,
    DhwSchedule,
    Scenario,
    daily_cycle,
    entered_parameters,
    simulate,
)

HOUR = 3600.0


def scenario(means: list[float], **changes) -> Scenario:
    base = Scenario(
        boiler=BOILERS["condensing_large"],
        house=HOUSES["average"],
        zones=radiator_zones(),
        outdoor=daily_cycle(means),
        days=len(means),
    )
    return dataclasses.replace(base, **changes)


def test_energy_balance() -> None:
    result = simulate(scenario([5.0, 5.0]))
    stored = (result.water_end - result.water_start) * 60.0 * WATER_KWH_PER_L_K
    assert result.burner_kwh == pytest.approx(result.emitted_kwh + stored, rel=0.01)
    assert result.ch_kwh == pytest.approx(result.burner_kwh)
    assert len(result.daily_ch_kwh) == 2


def test_rooms_hold_their_setpoints() -> None:
    result = simulate(scenario([2.0, 2.0]))
    for profile in radiator_zones():
        temperature = result.history.zones[profile.zone_id].temperature
        late = [s.value for s in temperature if s.t > 12 * HOUR and s.value is not None]
        assert min(late) > profile.target - 1.0
        assert max(late) < profile.target + 1.0


def test_mild_weather_cycles_more_than_cold() -> None:
    params = entered_parameters(BOILERS["condensing_large"])
    mild = simulate(scenario([12.0, 12.0]))
    cold = simulate(scenario([-5.0, -5.0]))
    mild_stats = summarize(mild.history, params, DAY, 2 * DAY).heating
    cold_stats = summarize(cold.history, params, DAY, 2 * DAY).heating
    assert mild_stats.starts_per_hour is not None
    assert cold_stats.starts_per_hour is not None
    assert mild_stats.starts_per_hour > 1.0  # the load is below the minimum power
    assert mild_stats.starts_per_hour > cold_stats.starts_per_hour
    # In the cold the burner modulates without stopping.
    assert cold_stats.burn_s > 0.9 * cold_stats.observed_s
    assert mild_stats.burn_s < 0.6 * mild_stats.observed_s


def test_simulated_week_gives_a_verdict_and_counts_dhw() -> None:
    boiler = BOILERS["condensing_large"]
    result = simulate(scenario([10.0] * 8, dhw=DhwSchedule()))
    params = entered_parameters(boiler, heating_threshold=18.0)
    without_building = verdict(summarize(result.history, params, 0, 8 * DAY))
    assert ReasonCode.LOAD_UNKNOWN in {r.code for r in without_building.reasons}
    # The user's loss coefficient lets the verdict compare the load with the minimum power:
    # about 2 kW at 10 °C against 4 kW.
    params = params.with_estimate(
        ParameterKey.LOSS_COEFFICIENT, Estimate(HOUSES["average"].loss_kw_per_k, Source.ENTERED)
    )
    summary = summarize(result.history, params, 0, 8 * DAY)
    assert summary.dhw.starts == 16
    assert summary.observed_s == pytest.approx(8 * DAY)
    assert summary.condensing is not None
    assert summary.condensing.value is not None
    assert summary.condensing.value > 0.5  # low water temperatures in mild weather
    assert summary.load_below_min is not None
    assert summary.load_below_min.value == pytest.approx(1.0)
    result_verdict = verdict(summary)
    assert result_verdict.verdict is Verdict.WORTH_IT
    assert ReasonCode.LOAD_OFTEN_BELOW_MIN_POWER in {r.code for r in result_verdict.reasons}


def test_dhw_is_inferred_without_dhw_or_ch_signal() -> None:
    signals = DEFAULT_SIGNALS - {Signal.DHW_ACTIVE, Signal.CH_ACTIVE}
    result = simulate(scenario([8.0, 8.0], dhw=DhwSchedule(), signals=signals))
    params = entered_parameters(BOILERS["condensing_large"])
    summary = summarize(result.history, params, 0, 2 * DAY)
    schedule = DhwSchedule()
    during_dhw = [b for b in summary.burns if schedule.active(b.burn.start + 60.0)]
    assert during_dhw
    assert all(b.kind is BurnKind.DHW for b in during_dhw)
    heating = [b for b in summary.burns if b not in during_dhw]
    correct = sum(1 for b in heating if b.kind is BurnKind.CH)
    assert correct / len(heating) > 0.9


def test_building_fit_recovers_the_simulated_house() -> None:
    means = [-6.0, -3.0, 0.0, 3.0, 6.0, 9.0, 12.0, -4.0, 1.0, 7.0, 10.0, -1.0]
    house = HOUSES["average"]
    result = simulate(scenario(means))
    params = entered_parameters(BOILERS["condensing_large"])
    days = [(d * DAY, (d + 1) * DAY) for d in range(1, len(means))]  # skip the start-up day
    points = daily_points(result.history, params, days)
    assert len(points) == len(days)
    fit = fit_daily_load(points, threshold=18.0)
    assert fit is not None
    assert fit.loss.value == pytest.approx(house.loss_kw_per_k, rel=0.25)
    assert fit.threshold is not None
    expected_threshold = 20.5 - house.gains_kw / house.loss_kw_per_k
    assert fit.threshold.value == pytest.approx(expected_threshold, abs=2.0)
