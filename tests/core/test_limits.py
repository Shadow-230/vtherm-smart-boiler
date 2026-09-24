"""Flow limits, frost protection and the summer/winter switch."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.limits import (
    FlowLimits,
    FrostConfig,
    LimitCode,
    Limited,
    Season,
    SeasonConfig,
    frost_needed,
    limit_flow,
    update_season,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

LIMITS = FlowLimits(hard_min=25.0, hard_max=70.0, ceiling_band=10.0)


def test_within_limits_is_unchanged() -> None:
    assert limit_flow(45.0, 45.0, LIMITS) == Limited(45.0)


def test_hard_minimum_and_maximum() -> None:
    assert limit_flow(20.0, 20.0, LIMITS) == Limited(25.0, (LimitCode.HARD_MIN,))
    assert limit_flow(90.0, 85.0, LIMITS) == Limited(70.0, (LimitCode.HARD_MAX,))


def test_weather_ceiling_caps_anything_far_above_the_curve() -> None:
    assert limit_flow(60.0, 40.0, LIMITS) == Limited(50.0, (LimitCode.CEILING,))


def test_the_lowest_cap_wins() -> None:
    result = limit_flow(60.0, 60.0, LIMITS, circuit_max=45.0, boiler_max=65.0)
    assert result == Limited(45.0, (LimitCode.CIRCUIT_MAX,))
    boiler = limit_flow(60.0, 60.0, LIMITS, circuit_max=None, boiler_max=55.0)
    assert boiler == Limited(55.0, (LimitCode.BOILER_MAX,))


def test_caps_win_over_the_hard_minimum() -> None:
    limits = FlowLimits(hard_min=30.0, hard_max=70.0)
    result = limit_flow(20.0, 20.0, limits, circuit_max=28.0)
    assert result == Limited(28.0, (LimitCode.HARD_MIN, LimitCode.CIRCUIT_MAX))


@pytest.mark.parametrize(
    "kwargs",
    [{"hard_min": 50.0, "hard_max": 40.0}, {"hard_max": 99.0}, {"ceiling_band": -1.0}],
)
def test_invalid_limits(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        FlowLimits(**kwargs)


def zone(temp: float | None, reported: float | None = 100.0) -> ZoneState:
    return ZoneState("z", temperature=temp, reported_at=reported)


def test_frost_starts_below_the_limit_and_releases_with_hysteresis() -> None:
    config = FrostConfig(room_limit=5.0, release=7.0)
    assert frost_needed([zone(4.9), zone(20.0)], 100.0, 600.0, False, config)
    assert not frost_needed([zone(6.0)], 100.0, 600.0, False, config)
    assert frost_needed([zone(6.0)], 100.0, 600.0, True, config)  # still below the release
    assert not frost_needed([zone(7.0)], 100.0, 600.0, True, config)


def test_frost_ignores_stale_and_unknown_zones() -> None:
    config = FrostConfig()
    assert not frost_needed([zone(2.0, reported=None), zone(None)], 100.0, 600.0, False, config)
    assert not frost_needed([zone(2.0, reported=-10_000.0)], 100.0, 600.0, False, config)


def test_frost_config_is_consistent() -> None:
    with pytest.raises(ValueError, match="release"):
        FrostConfig(room_limit=8.0, release=6.0)


def test_season_switch_with_hysteresis() -> None:
    config = SeasonConfig(threshold=18.0, hysteresis=1.0)
    assert update_season(Season.WINTER, 18.5, config) is Season.WINTER
    assert update_season(Season.WINTER, 19.0, config) is Season.SUMMER
    assert update_season(Season.SUMMER, 17.5, config) is Season.SUMMER
    assert update_season(Season.SUMMER, 17.0, config) is Season.WINTER


def test_unknown_outdoor_means_winter() -> None:
    assert update_season(Season.SUMMER, None, SeasonConfig()) is Season.WINTER
