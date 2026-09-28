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
        zone("a", ready=False, valve_open=0.9),  # heating, but VT has not finished starting it
        zone("a", reported=False, valve_open=0.9),  # heating, VT's first refresh still to come
        zone("a", valve_open=0.9, temperature_at=NOW - 2 * AGE),  # its room sensor went quiet
    ],
)
def test_a_zone_that_is_not_known_never_means_no_demand(unknown: ZoneState) -> None:
    """Alone it makes demand unknown (decision 3 then decides); with others, the known ones
    decide."""
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
    "kwargs",
    [
        {"count_threshold": -1},
        {"zone_opening": 1.0},
        {"count_threshold": 0},
        {"opening_threshold": 0.0},  # would mean demand for ever
        {"power_threshold_kw": 0.0},
    ],
)
def test_invalid_config(kwargs: dict) -> None:
    with pytest.raises(ValueError, match="must"):
        DemandConfig(**kwargs)


# --- X3: calling zones only, the power over the cycle, criteria without data, S-34, shedding ----


def test_the_opening_threshold_follows_calling_zones_only() -> None:
    """T-46 (P-13): an over_switch zone keeps its duty cycle through its off phase; VT's device
    is off, so the zone does not call, and its duty cycle is no opening of a calling zone."""
    switch = zone("a", on_percent=0.6, device_active=False)
    config = DemandConfig(count_threshold=0, opening_threshold=0.5)
    result = boiler_demand([switch], NOW, AGE, config)
    assert result.wanted is False
    assert result.widest_opening is None
    assert result.criteria_without_data == ()  # the zone publishes an opening: data, no call


def test_the_power_criterion_counts_a_switch_zone_through_its_off_phase() -> None:
    """VT counts a zone's mean power over its cycle — 0.6 of 2 kW for a switch zone in its off
    phase — while heat can flow: another zone's valve is open."""
    switch = zone("a", on_percent=0.6, power=2.0, device_active=False)
    valve = zone("b", valve_open=0.5)
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand([switch, valve], NOW, AGE, config)
    assert result.power_kw == pytest.approx(1.2)
    assert result.wanted is True
    published = zone("a", on_percent=0.6, power=2.0, mean_power=1.2, device_active=False)
    assert boiler_demand([published, valve], NOW, AGE, config).power_kw == pytest.approx(1.2)


def test_the_power_criterion_needs_an_open_valve_or_an_active_device() -> None:
    """Mean power of 3 kW, but no zone has its valve open or its device on: no heat can flow,
    so the power criterion asks for nothing — and it still has data."""
    zones = [
        zone("a", on_percent=0.6, power=2.5, device_active=False),
        zone("b", on_percent=0.6, mean_power=1.5, power=2.5, device_active=False),
    ]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is False
    assert result.criteria_without_data == ()
    active = [*zones[:1], zone("b", on_percent=0.6, power=2.5, device_active=True)]
    assert boiler_demand(active, NOW, AGE, config).wanted is True


def test_a_criterion_without_data_is_not_no_demand() -> None:
    """T-27 (P-14): a count of 0 and only a power threshold, while no zone has a device power
    (VT publishes 0 when none is set): whether to heat is not known — never a silent "no"."""
    zones = [zone("a", valve_open=0.6, device_active=True), zone("b", valve_open=0.3)]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ("power",)
    assert result.power_kw is None


def test_an_opening_criterion_without_data_is_not_no_demand() -> None:
    """No zone publishes an opening or a duty cycle (VT's over_climate): the opening
    criterion cannot be judged."""
    zones = [zone("a", calling=True), zone("b", calling=False)]
    config = DemandConfig(count_threshold=0, opening_threshold=0.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ("opening",)


@pytest.mark.parametrize(("calling", "wanted"), [(True, True), (False, False)])
def test_only_the_criterion_without_data_is_left_out(calling: bool, wanted: bool) -> None:
    """A count of 1 and a power threshold without data: the count decides."""
    zones = [zone("a", valve_open=0.6 if calling else 0.0)]
    config = DemandConfig(count_threshold=1, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is wanted
    assert result.criteria_without_data == ("power",)


def test_a_device_power_of_zero_is_no_data_but_a_mean_power_of_zero_is_none_now() -> None:
    """A zone with its device power known and nothing flowing now feeds the criterion with 0."""
    zones = [zone("a", valve_open=0.6, power=2.0, mean_power=0.0)]
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.criteria_without_data == ()
    assert result.power_kw == 0.0
    assert result.wanted is False


def test_an_off_zone_not_ready_is_known_without_demand() -> None:
    """T-17 (S-34): "off" has no demand whatever VT's start shows, once the recognition period
    is over; during it, the zone is not known yet."""
    off = zone("a", heating_enabled=False, ready=False, reported=False, temperature=19.0)
    result = boiler_demand([off], NOW, AGE, DemandConfig())
    assert result.wanted is False
    assert result.unknown == ()
    during = boiler_demand([off], NOW, AGE, DemandConfig(), recognition=True)
    assert during.wanted is None
    assert during.unknown == ("a",)


@pytest.mark.parametrize("ready", [False, None])
def test_a_heating_zone_not_ready_is_unknown(ready: bool | None) -> None:
    heating = zone("a", ready=ready, reported=False, valve_open=0.6)
    result = boiler_demand([heating], NOW, AGE, DemandConfig())
    assert result.wanted is None
    assert result.unknown == ("a",)


def test_a_shed_zone_has_no_demand_and_no_power() -> None:
    """T-45's core: VT's power shedding holds the zone off — whatever its duty cycle or its
    device showed last."""
    shed = zone("a", valve_open=0.6, device_active=True, power=2.0, on_percent=0.6, shedding=True)
    assert zone_wants_heat(shed, 0.05) is False
    config = DemandConfig(count_threshold=1, power_threshold_kw=0.5, opening_threshold=0.3)
    result = boiler_demand([shed], NOW, AGE, config)
    assert result.wanted is False
    assert result.zones_wanting == 0
    assert result.power_kw == 0.0
    assert result.widest_opening is None


def test_a_remembered_zone_keeps_its_last_answer() -> None:
    """The grace (decision 3): a zone that stopped answering keeps its last known state in
    demand, as a known zone — the count's cap included."""
    last = zone("a", valve_open=0.6, device_active=True, power=2.0, on_percent=0.6)
    gone = ZoneState("a")  # unavailable now
    other = zone("b", valve_open=0.0)
    result = boiler_demand([gone, other], NOW, AGE, DemandConfig(), memory={"a": last})
    assert result.wanted is True
    assert result.fresh_zones == 2
    assert result.unknown == ()
    two = DemandConfig(count_threshold=2)
    assert boiler_demand([gone], NOW, AGE, two, memory={"a": last}).wanted is True  # capped
    assert boiler_demand([gone, other], NOW, AGE, DemandConfig()).wanted is False  # no memory


@pytest.mark.parametrize(
    "zones",
    [
        [],
        [ZoneState("a")],
        [zone("a", heating_enabled=None, power=None, mean_power=None, valve_open=None)],
    ],
)
def test_no_zone_known_names_no_criterion(zones: list[ZoneState]) -> None:
    """Every zone unknown is decision 3's own case, not a criterion without data."""
    config = DemandConfig(count_threshold=0, power_threshold_kw=1.0, opening_threshold=0.5)
    result = boiler_demand(zones, NOW, AGE, config)
    assert result.wanted is None
    assert result.criteria_without_data == ()
