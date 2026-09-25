"""Flow limits and frost protection."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.limits import (
    FlowLimits,
    FrostConfig,
    LimitCode,
    Limited,
    frost_needed,
    limit_flow,
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


def test_caps_that_protect_the_installation_win_over_the_hard_minimum() -> None:
    limits = FlowLimits(hard_min=30.0, hard_max=70.0)
    result = limit_flow(20.0, 20.0, limits, circuit_max=28.0)
    assert result == Limited(28.0, (LimitCode.HARD_MIN, LimitCode.CIRCUIT_MAX))


def test_the_weather_ceiling_never_falls_below_the_hard_minimum() -> None:
    """The ceiling protects nothing but gas: it gives way to the hard minimum."""
    limits = FlowLimits(hard_min=30.0, hard_max=70.0, ceiling_band=5.0)
    assert limit_flow(40.0, 20.0, limits) == Limited(30.0, (LimitCode.CEILING,))
    assert limit_flow(20.0, 20.0, limits) == Limited(30.0, (LimitCode.HARD_MIN,))


def test_a_fixed_temperature_circuit_keeps_the_boiler_flow_above_it() -> None:
    """A thermostatic mixing valve set to 40 °C needs at least that from the boiler."""
    assert limit_flow(32.0, 32.0, LIMITS, floor=40.0) == Limited(40.0, (LimitCode.FIXED_CIRCUIT,))
    assert limit_flow(32.0, 32.0, LIMITS, floor=40.0, circuit_max=38.0) == Limited(
        38.0, (LimitCode.FIXED_CIRCUIT, LimitCode.CIRCUIT_MAX)
    )


@pytest.mark.parametrize(
    "kwargs",
    [{"hard_min": 50.0, "hard_max": 40.0}, {"hard_max": 99.0}, {"ceiling_band": -1.0}],
)
def test_invalid_limits(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        FlowLimits(**kwargs)


def zone(temp: float | None, reported: float | None = 100.0, zid: str = "z") -> ZoneState:
    return ZoneState(zid, temperature=temp, reported_at=reported)


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


def test_frost_watches_every_zone_or_the_one_picked() -> None:
    """Every zone by default, VT's switched-off ones included; or only the zone the user picks
    (e.g. to leave an unheated room out)."""
    zones = [zone(3.0, zid="garage"), zone(20.0, zid="living")]
    assert frost_needed(zones, 100.0, 600.0, False, FrostConfig())
    assert not frost_needed(zones, 100.0, 600.0, False, FrostConfig(zone="living"))
    assert frost_needed(zones, 100.0, 600.0, False, FrostConfig(zone="garage"))


def test_implausible_room_temperatures_are_rejected() -> None:
    """A sensor reading -127 °C is broken, not a frozen room."""
    assert not frost_needed([zone(-127.0), zone(20.0)], 100.0, 600.0, False, FrostConfig())
    assert frost_needed([zone(-5.0)], 100.0, 600.0, False, FrostConfig())
