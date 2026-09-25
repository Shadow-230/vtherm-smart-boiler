"""Boiler demand from the zones."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.demand import (
    Demand,
    DemandConfig,
    boiler_demand,
    zone_wants_heat,
)
from custom_components.vtherm_smart_boiler.core.readings import ZoneState

NOW = 1000.0
AGE = 600.0


def zone(zid: str = "z", **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    kw.setdefault("reported_at", NOW)
    return ZoneState(zid, **kw)


@pytest.mark.parametrize(
    ("state", "wants"),
    [
        (zone(valve_open=0.3), True),
        (zone(valve_open=0.03), False),
        (zone(on_percent=0.5), True),
        (zone(calling=True), True),  # no opening: VT's own flag decides
        (zone(calling=False), False),
        (zone(valve_open=0.0, calling=True), False),  # the opening decides
        (zone(valve_open=0.8, heating_enabled=False), False),  # sleeping or off
        # VT's own view of its devices wins: a switch on, a valve open (its minimal activation
        # time respected), a climate heating.
        (zone(valve_open=0.03, device_active=True), True),
        (zone(on_percent=0.5, device_active=False), False),
        # "auto" or heat_cool: heats only while its action says so.
        (zone(auto_mode=True, calling=True), True),
        (zone(auto_mode=True, calling=False, on_percent=0.8, device_active=True), False),
        (zone(auto_mode=True, on_percent=0.8), True),
    ],
)
def test_zone_wants_heat(state: ZoneState, wants: bool) -> None:
    assert zone_wants_heat(state, 0.05) is wants


def test_count_threshold() -> None:
    zones = [zone("a", valve_open=0.5), zone("b", valve_open=0.0)]
    assert boiler_demand(zones, NOW, AGE, DemandConfig()).wanted is True
    two = DemandConfig(count_threshold=2)
    result = boiler_demand(zones, NOW, AGE, two)
    assert result == Demand(False, 1, None, 0.5, 2)
    assert result.unknown == ()


def test_power_threshold_can_add_demand() -> None:
    zones = [
        zone("a", on_percent=0.5, power=3.0),
        zone("b", on_percent=0.4, power=1.0),
        zone("c", on_percent=0.0, power=2.0),
    ]
    config = DemandConfig(count_threshold=3, power_threshold_kw=1.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.power_kw == pytest.approx(1.9)
    assert result.wanted is True
    stricter = DemandConfig(count_threshold=3, power_threshold_kw=2.0)
    assert boiler_demand(zones, NOW, AGE, stricter).wanted is False


def test_opening_threshold_can_add_demand() -> None:
    zones = [zone("a", valve_open=0.6), zone("b", valve_open=0.2)]
    config = DemandConfig(count_threshold=3, opening_threshold=0.5)
    assert boiler_demand(zones, NOW, AGE, config).wanted is True


def test_stale_zones_do_not_count_and_no_fresh_zone_is_unknown() -> None:
    stale = zone("a", valve_open=0.9, reported_at=NOW - 2 * AGE)
    assert boiler_demand([stale], NOW, AGE, DemandConfig()).wanted is None
    assert boiler_demand([], NOW, AGE, DemandConfig()) == Demand(None)
    mixed = boiler_demand([stale, zone("b", valve_open=0.0)], NOW, AGE, DemandConfig())
    assert mixed.wanted is False
    assert mixed.fresh_zones == 1
    assert mixed.unknown == ("a",)


@pytest.mark.parametrize(
    "unknown",
    [
        zone("a", heating_enabled=None, valve_open=0.9),  # `unavailable`, or a mode not known
        zone("a", ready=False, valve_open=0.9),  # VT has not finished starting it
        zone("a", valve_open=0.9, temperature_at=NOW - 2 * AGE),  # its room sensor went quiet
    ],
)
def test_a_zone_that_is_not_known_never_means_no_demand(unknown: ZoneState) -> None:
    """Alone it makes demand unknown (the curve heats); with others, the known ones decide."""
    assert boiler_demand([unknown], NOW, AGE, DemandConfig()) == Demand(None, unknown=("a",))
    other = boiler_demand([unknown, zone("b", valve_open=0.0)], NOW, AGE, DemandConfig())
    assert other.wanted is False
    assert other.unknown == ("a",)


def test_the_temperature_age_decides_freshness() -> None:
    """VT rewrites its climate often: its report time says little about the room sensor."""
    fresh = zone(valve_open=0.5, reported_at=NOW - 3 * AGE, temperature_at=NOW - 10.0)
    assert fresh.is_fresh(NOW, AGE)
    assert not zone(reported_at=NOW, temperature_at=NOW - 2 * AGE).is_fresh(NOW, AGE)


def test_each_criterion_can_stand_alone() -> None:
    """As in VT, a count threshold of 0 turns the count off."""
    zones = [zone("a", valve_open=0.3, power=1.0), zone("b", valve_open=0.2, power=1.0)]
    by_opening = DemandConfig(count_threshold=0, opening_threshold=0.5)
    assert boiler_demand(zones, NOW, AGE, by_opening).wanted is False
    by_power = DemandConfig(count_threshold=0, power_threshold_kw=0.4)
    assert boiler_demand(zones, NOW, AGE, by_power).wanted is True


def test_the_count_never_asks_for_more_zones_than_are_known() -> None:
    zones = [zone("a", valve_open=0.6), zone("b", heating_enabled=None)]
    assert boiler_demand(zones, NOW, AGE, DemandConfig(count_threshold=2)).wanted is True


@pytest.mark.parametrize(
    "kwargs", [{"count_threshold": -1}, {"zone_opening": 1.0}, {"count_threshold": 0}]
)
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        DemandConfig(**kwargs)
