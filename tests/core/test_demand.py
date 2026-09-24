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


def test_power_threshold_can_add_demand() -> None:
    zones = [zone("a", on_percent=0.5, power=3.0), zone("b", on_percent=0.4, power=1.0)]
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
    assert boiler_demand([stale], NOW, AGE, DemandConfig()) == Demand(None)
    assert boiler_demand([], NOW, AGE, DemandConfig()) == Demand(None)
    mixed = boiler_demand([stale, zone("b", valve_open=0.0)], NOW, AGE, DemandConfig())
    assert mixed.wanted is False
    assert mixed.fresh_zones == 1


@pytest.mark.parametrize("kwargs", [{"count_threshold": 0}, {"zone_opening": 1.0}])
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        DemandConfig(**kwargs)
