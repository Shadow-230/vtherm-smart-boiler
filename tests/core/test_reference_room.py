"""Reference room: eligibility, strategies, hysteresis and explicit no-reference states."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.reference_room import (
    ReferenceRoom,
    Strategy,
    select_reference,
)
from custom_components.vtherm_smart_boiler.core.zones import (
    SelectionStatus,
    eligible_zones,
    has_valid_readings,
)

NOW = 1000.0
AGE = 600.0


def zone(zid: str, temp: float | None, target: float | None, **kw) -> ZoneState:
    kw.setdefault("heating_enabled", True)
    kw.setdefault("reported_at", NOW - 10)
    return ZoneState(zid, temperature=temp, target=target, **kw)


def pick(zones, strategy=Strategy.LARGEST_DEFICIT, previous=None, chosen=None) -> ReferenceRoom:
    return select_reference(zones, strategy, NOW, AGE, previous=previous, chosen_zone=chosen)


@pytest.mark.parametrize(
    ("z", "valid"),
    [
        (zone("a", 20.0, 21.0), True),
        (zone("a", None, 21.0), False),
        (zone("a", 20.0, None), False),
        (zone("a", 2.0, 21.0), False),  # implausible room temperature
        (zone("a", 20.0, 50.0), False),  # implausible setpoint
        (zone("a", 20.0, 21.0, reported_at=NOW - 2 * AGE), False),  # stale
        (zone("a", 20.0, 21.0, reported_at=None), False),
    ],
)
def test_valid_readings(z: ZoneState, valid: bool) -> None:
    assert has_valid_readings(z, NOW, AGE) is valid


def test_no_active_zone_and_no_valid_measurement_are_distinct() -> None:
    off = zone("a", 20.0, 21.0, heating_enabled=False)
    assert eligible_zones([], NOW, AGE).status is SelectionStatus.NO_ACTIVE_ZONE
    assert eligible_zones([off], NOW, AGE).status is SelectionStatus.NO_ACTIVE_ZONE
    broken = zone("b", None, 21.0)
    assert eligible_zones([off, broken], NOW, AGE).status is SelectionStatus.NO_VALID_MEASUREMENT
    assert pick([off, broken]) == ReferenceRoom(SelectionStatus.NO_VALID_MEASUREMENT)


def test_largest_deficit_takes_both_values_from_one_zone() -> None:
    result = pick([zone("a", 20.5, 21.0), zone("b", 19.0, 20.5), zone("c", 22.0, 21.0)])
    assert result == ReferenceRoom(SelectionStatus.OK, "b", 19.0, 20.5, ("b",))
    assert result.deficit == pytest.approx(1.5)


def test_overheated_rooms_win_only_when_all_are_overheated() -> None:
    result = pick([zone("a", 22.0, 21.0), zone("b", 21.5, 21.0)])
    assert result.zone_id == "b"  # least negative deficit


def test_hysteresis_keeps_the_previous_zone_on_small_differences() -> None:
    first = pick([zone("a", 20.0, 21.0), zone("b", 20.2, 21.0)])
    assert first.zone_id == "a"
    close = pick([zone("a", 20.0, 21.0), zone("b", 19.8, 21.0)], previous=first)
    assert close.zone_id == "a"  # b is only 0.2 K worse
    clear = pick([zone("a", 20.0, 21.0), zone("b", 19.5, 21.0)], previous=first)
    assert clear.zone_id == "b"


def test_reselects_at_once_when_the_selected_zone_drops_out() -> None:
    first = pick([zone("a", 19.0, 21.0), zone("b", 20.9, 21.0)])
    assert first.zone_id == "a"
    dropped = pick([zone("a", 19.0, 21.0, heating_enabled=False), zone("b", 20.9, 21.0)], first)
    assert dropped.zone_id == "b"


def test_hysteresis_uses_current_values_of_the_kept_zone() -> None:
    first = pick([zone("a", 19.0, 21.0), zone("b", 20.0, 21.0)])
    kept = pick([zone("a", 20.1, 21.0), zone("b", 20.0, 21.0)], previous=first)
    assert kept == ReferenceRoom(SelectionStatus.OK, "a", 20.1, 21.0, ("a",))


def test_chosen_zone() -> None:
    zones = [zone("a", 19.0, 21.0), zone("b", 20.0, 22.0)]
    assert pick(zones, Strategy.CHOSEN_ZONE, chosen="b").zone_id == "b"
    off = [zone("a", 19.0, 21.0), zone("b", 20.0, 22.0, heating_enabled=False)]
    assert pick(off, Strategy.CHOSEN_ZONE, chosen="b").status is SelectionStatus.NO_ACTIVE_ZONE
    broken = [zone("b", None, 22.0)]
    result = pick(broken, Strategy.CHOSEN_ZONE, chosen="b")
    assert result.status is SelectionStatus.NO_VALID_MEASUREMENT
    assert pick(zones, Strategy.CHOSEN_ZONE, chosen="x").status is SelectionStatus.NO_ACTIVE_ZONE


def test_average_of_valid_zones() -> None:
    zones = [zone("b", 20.0, 22.0), zone("a", 19.0, 21.0), zone("c", None, 21.0)]
    result = pick(zones, Strategy.AVERAGE)
    assert result.status is SelectionStatus.OK
    assert result.zone_id is None
    assert result.temperature == pytest.approx(19.5)
    assert result.target == pytest.approx(21.5)
    assert result.zones == ("a", "b")
