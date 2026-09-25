"""Critical zone per circuit."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.critical_zone import CriticalZone, critical_zone
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.zones import SelectionStatus

NOW = 1000.0
AGE = 600.0


def zone(zid: str, temp: float, target: float, demand: float | None, **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    return ZoneState(zid, temperature=temp, target=target, valve_open=demand, reported_at=NOW, **kw)


def pick(zones, previous=None) -> CriticalZone:
    return critical_zone("c", zones, NOW, AGE, previous=previous)


def test_highest_demand_wins() -> None:
    result = pick([zone("a", 20.0, 21.0, 0.4), zone("b", 20.8, 21.0, 0.9)])
    assert result == CriticalZone("c", SelectionStatus.OK, "b", 0.9, pytest.approx(0.2), False)


def test_deficit_breaks_ties_between_full_valves_and_marks_saturation() -> None:
    result = pick([zone("a", 20.0, 21.0, 1.0), zone("b", 19.0, 21.0, 1.0)])
    assert result.zone_id == "b"
    assert result.saturated


def test_fully_open_but_warm_enough_is_not_saturated() -> None:
    assert not pick([zone("a", 21.2, 21.0, 1.0)]).saturated


def test_zones_without_demand_fall_back_to_deficit() -> None:
    result = pick([zone("a", 20.0, 21.0, None), zone("b", 19.0, 21.0, None)])
    assert result.zone_id == "b"
    assert result.demand is None
    assert not result.saturated


def test_hysteresis_on_demand_and_deficit() -> None:
    first = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.7)])
    assert first.zone_id == "a"
    close = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.85)], previous=first)
    assert close.zone_id == "a"
    clear = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 20.0, 21.0, 0.95)], previous=first)
    assert clear.zone_id == "b"
    deeper = pick([zone("a", 20.0, 21.0, 0.8), zone("b", 19.5, 21.0, 0.85)], previous=first)
    assert deeper.zone_id == "b"  # same demand band, clearly colder


def test_known_demand_beats_unknown_and_keeps_its_place() -> None:
    unknown_first = pick([zone("a", 19.0, 21.0, None)])
    result = pick([zone("a", 19.0, 21.0, None), zone("b", 20.9, 21.0, 0.3)], previous=unknown_first)
    assert result.zone_id == "b"
    back = pick([zone("a", 19.0, 21.0, None), zone("b", 20.9, 21.0, 0.3)], previous=result)
    assert back.zone_id == "b"


def test_no_zone_states() -> None:
    assert pick([]).status is SelectionStatus.NO_ACTIVE_ZONE
    off = zone("a", 20.0, 21.0, 0.5, heating_enabled=False)
    assert pick([off]).status is SelectionStatus.NO_ACTIVE_ZONE
    stale = ZoneState("a", 20.0, 21.0, heating_enabled=True, reported_at=NOW - 2 * AGE)
    assert pick([stale]) == CriticalZone("c", SelectionStatus.NO_VALID_MEASUREMENT)


def test_within_the_demand_margin_the_colder_zone_wins() -> None:
    """P61: as the docstring says — among zones with about the same demand, the one furthest
    below its setpoint."""
    result = pick([zone("a", 20.8, 21.0, 0.85), zone("b", 19.5, 21.0, 0.8)])
    assert result.zone_id == "b"


def test_a_zone_at_vts_cap_is_as_open_as_it_gets() -> None:
    """P61: one meaning of "fully open" — VT's cap on the duty cycle counts, as in control."""
    capped = ZoneState("a", 19.0, 21.0, True, on_percent=0.8, max_on_percent=0.8, reported_at=NOW)
    assert pick([capped]).saturated
