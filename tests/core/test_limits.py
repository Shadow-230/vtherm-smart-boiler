"""Flow limits and frost protection."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.limits import (
    FlowLimits,
    FrostConfig,
    Grid,
    LimitCode,
    Limited,
    can_take_heat,
    frost_closed,
    frost_needed,
    handed_back_in_frost,
    install_cap,
    is_on_grid,
    limit_flow,
    on_grid,
    write_bounds,
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


def test_a_value_goes_on_the_entitys_grid_inside_the_limits() -> None:
    """P-98: rounding to the entity's step stays inside the limits — the grid value just inside
    where the nearest falls outside; none without one."""
    assert on_grid(70.0, 0.5, 0.25, 25.0, 70.0) == 69.75  # a tie, the nearest above is outside
    assert on_grid(45.3, 0.5, 0.0, 25.0, 70.0) == 45.5
    assert on_grid(24.9, 1.0, 0.0, 25.0, 70.0) == 25.0  # the nearest (25) is inside
    assert on_grid(25.2, 5.0, 0.0, 25.2, 70.0) == 30.0  # just inside from below
    assert on_grid(40.0, 5.0, 0.0, 41.0, 44.0) is None  # no grid value inside
    assert on_grid(45.37, 0.0, 0.0, 25.0, 70.0) == 45.37  # no step: no grid
    assert on_grid(80.0, 0.0, 0.0, None, 70.0) is None
    assert is_on_grid(69.75, 0.5, 0.25)
    assert not is_on_grid(70.0, 0.5, 0.25)
    assert is_on_grid(45.123, 0.0, 0.0)


def test_a_grid_in_another_unit_is_applied_in_that_unit() -> None:
    """P-15: a °F entity's grid is applied in °F and the value returned in °C; its step as a
    temperature difference decides whether it is too coarse (above 1 K)."""
    fahrenheit = Grid(step=1.0, minimum=50.0, maximum=190.0, scale=1.8, offset=32.0)
    value = fahrenheit.put(45.3, 25.0, 70.0)
    assert value is not None
    assert fahrenheit.to_unit(value) == pytest.approx(114.0)
    assert not fahrenheit.too_coarse  # 0.56 K
    assert Grid(step=2.0, scale=1.8, offset=32.0).too_coarse  # 1.1 K
    assert Grid(step=1.0).step_k == 1.0
    assert not Grid(step=1.0).too_coarse
    assert Grid(step=5.0).too_coarse
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(20.0, 25.0, 70.0) == 30.0
    assert Grid(step=0.5, minimum=30.0, maximum=60.0).put(20.0, None, 25.0) is None


def test_the_bounds_a_written_value_keeps() -> None:
    limits = FlowLimits(hard_min=25.0, hard_max=70.0)
    assert write_bounds(limits) == (25.0, 70.0)
    assert write_bounds(limits, circuit_max=45.0, boiler_max=80.0) == (25.0, 45.0)
    assert write_bounds(limits, floor=40.0) == (40.0, 70.0)
    assert write_bounds(limits, circuit_max=35.0, floor=40.0) == (35.0, 35.0)


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


# --- V7, S-57: handed back while a room is near freezing ----------------------------------------


def in_frost(
    zones: list[ZoneState],
    active: bool = False,
    heating_stops: bool = True,
    controlling: bool = False,
    config: FrostConfig | None = None,
) -> bool | None:
    return handed_back_in_frost(
        zones,
        100.0,
        600.0,
        config or FrostConfig(room_limit=5.0, release=7.0),
        heating_stops=heating_stops,
        controlling=controlling,
        active=active,
    )


def test_handed_back_in_frost_rises_below_the_limit_and_clears_at_the_release() -> None:
    """S-57: where a hand-back stops heating and control does not hold the boiler, a watched
    zone below the frost limit raises the alarm; it holds until every watched zone with a known
    temperature is at or above the release."""
    assert in_frost([zone(4.0), zone(20.0)])
    assert not in_frost([zone(6.0)])  # between the limit and the release: not raised
    assert in_frost([zone(6.0)], active=True)  # once raised, it holds below the release
    assert in_frost([zone(7.5), zone(6.9)], active=True)
    assert not in_frost([zone(7.5)], active=True)
    assert not in_frost([zone(7.0)], active=True)  # at the release: off


def test_handed_back_in_frost_never_while_controlling_or_where_something_else_heats() -> None:
    """Negatives: while control holds the boiler its own frost protection heats; with a
    thermostat or a device's own control after the hand-back, frost protection rests on it."""
    assert not in_frost([zone(3.0)], controlling=True)
    assert not in_frost([zone(3.0)], active=True, controlling=True)
    assert not in_frost([zone(3.0)], heating_stops=False)
    assert not in_frost([zone(3.0)], active=True, heating_stops=False)


def test_handed_back_in_frost_ignores_unknown_stale_and_implausible_rooms() -> None:
    """Missing data: a zone with no temperature, a stale one or a broken sensor is not counted;
    with no watched zone known the alarm cannot be judged (``None``) — the control unit holds
    its last state for an hour, then shows it unknown (S-16, Y1). One known zone judges."""
    assert in_frost([zone(None)]) is None
    assert in_frost([zone(None)], active=True) is None
    assert in_frost([zone(2.0, reported=None)]) is None
    assert in_frost([zone(2.0, reported=-10_000.0)]) is None
    assert in_frost([zone(-127.0)]) is None
    assert in_frost([]) is None
    assert in_frost([], active=True) is None
    assert in_frost([zone(None), zone(20.0)]) is False
    assert in_frost([zone(None)], controlling=True) is False  # does not apply: known off


def test_handed_back_in_frost_watches_the_zones_frost_protection_watches() -> None:
    """Every zone by default, or only the zone the user picked for frost protection."""
    zones = [zone(3.0, zid="garage"), zone(20.0, zid="living")]
    assert in_frost(zones)
    assert not in_frost(zones, config=FrostConfig(zone="living"))
    assert in_frost(zones, config=FrostConfig(zone="garage"))


# --- X4, decision 4: frost heat only where the emitter can take it -------------------------------


def room(
    zid: str,
    temp: float | None,
    *,
    mode: bool | None = True,
    valve: float | None = None,
    duty: float | None = None,
    device: bool | None = None,
    **kw: object,
) -> ZoneState:
    """A zone as VT publishes it: its mode, its opening (valve, else duty cycle) and device."""
    return ZoneState(
        zid,
        temperature=temp,
        heating_enabled=mode,
        valve_open=valve,
        on_percent=duty,
        device_active=device,
        reported_at=100.0,
        **kw,  # type: ignore[arg-type]
    )


def test_a_zone_can_take_heat_by_its_opening_or_its_device_never_by_its_mode() -> None:
    """An opening above 0 (the valve, else the duty cycle) or VT's device active; heat mode
    with a closed valve cannot, and an off zone asleep at 100 % can."""
    config = FrostConfig()
    assert can_take_heat(room("a", 4.0, valve=0.3), config)
    assert can_take_heat(room("a", 4.0, duty=0.2), config)
    assert can_take_heat(room("a", 4.0, valve=0.0, device=True), config)
    assert can_take_heat(room("a", 4.0, mode=False, valve=1.0, duty=0.0, device=False), config)
    assert not can_take_heat(room("a", 4.0, valve=0.0, device=False), config)  # heat, closed
    assert not can_take_heat(room("a", 4.0, mode=False, duty=0.0, device=False), config)
    assert not can_take_heat(room("a", 4.0, valve=0.0), config)  # device unknown


def test_a_zone_whose_valve_state_cannot_be_read_can_take_heat() -> None:
    """Negative: no opening published — an older VT, an over_climate zone off with its device
    off — is heated as today; so is a zone VT has not started (its opening is a placeholder)."""
    config = FrostConfig()
    assert can_take_heat(room("a", 4.0), config)
    assert can_take_heat(room("a", 4.0, mode=False, device=False), config)
    assert can_take_heat(room("a", 4.0, mode=None), config)
    assert can_take_heat(room("a", 4.0, mode=False, duty=0.0, reported=False), config)


def test_closes_when_off_counts_an_off_zone_without_an_opening_as_closed() -> None:
    """The per-zone option (off by default): while VT has the zone off and publishes no
    opening, it cannot take heat. In heat mode, or with an opening or device shown, the
    published state decides."""
    config = FrostConfig(closes_when_off=frozenset({"a"}))
    assert not can_take_heat(room("a", 4.0, mode=False), config)
    assert not can_take_heat(room("a", 4.0, mode=False, device=False), config)
    assert can_take_heat(room("a", 4.0, mode=True), config)
    assert can_take_heat(room("a", 4.0, mode=None), config)  # mode unknown: not "off"
    assert can_take_heat(room("a", 4.0, mode=False, valve=1.0), config)  # asleep at 100 %
    assert can_take_heat(room("a", 4.0, mode=False, device=True), config)
    assert can_take_heat(room("b", 4.0, mode=False), config)  # another zone: as today


def test_frost_heats_only_for_cold_zones_that_can_take_heat() -> None:
    """Closed zones neither start frost heating nor hold it; the open ones do, with the
    hysteresis."""
    config = FrostConfig(room_limit=5.0, release=7.0)
    closed = room("off", 3.0, mode=False, valve=0.0, device=False)
    assert not frost_needed([closed], 100.0, None, False, config)
    assert not frost_needed([closed], 100.0, None, True, config)
    assert frost_needed([closed, room("open", 4.5, valve=0.4)], 100.0, None, False, config)
    assert frost_needed([closed, room("open", 6.0, valve=0.4)], 100.0, None, True, config)
    assert not frost_needed([closed, room("open", 7.0, valve=0.4)], 100.0, None, True, config)
    assert frost_needed([closed], 100.0, None, False, config, closed_too=True)  # S-57's watch


def test_the_closed_cold_zones_are_flagged_with_their_own_hysteresis() -> None:
    """A watched zone below the frost limit that cannot take heat is flagged; it stays flagged
    until it is at or above the release, or can take heat. Unknown, stale, implausible or
    unwatched zones, and zones VT has not started, are not flagged."""
    config = FrostConfig(room_limit=5.0, release=7.0)

    def closed(temp: float | None, zid: str = "a", **kw: object) -> ZoneState:
        return room(zid, temp, mode=False, valve=0.0, device=False, **kw)

    assert frost_closed([closed(4.0)], 100.0, None, config) == ("a",)
    assert frost_closed([closed(6.0)], 100.0, None, config) == ()  # not below the limit
    assert frost_closed([closed(6.0)], 100.0, None, config, ("a",)) == ("a",)  # held
    assert frost_closed([closed(7.0)], 100.0, None, config, ("a",)) == ()  # released
    opened = room("a", 4.0, mode=False, valve=1.0)
    assert frost_closed([opened], 100.0, None, config, ("a",)) == ()  # can take heat now
    assert frost_closed([closed(None)], 100.0, None, config, ("a",)) == ()
    assert frost_closed([closed(-127.0)], 100.0, None, config) == ()
    stale = replace(closed(4.0), reported_at=-10_000.0)
    assert frost_closed([stale], 100.0, 600.0, config) == ()
    assert frost_closed([closed(4.0, reported=False)], 100.0, None, config) == ()
    picked = FrostConfig(zone="b")
    assert frost_closed([closed(4.0), closed(4.0, "b")], 100.0, None, picked) == ("b",)


def test_handed_back_in_frost_still_watches_closed_zones() -> None:
    """S-57 tells of a room near freezing while nothing heats, whether or not VT keeps it
    closed: the hand-back leaves it cold either way."""
    closed = room("a", 4.0, mode=False, valve=0.0, device=False)
    assert in_frost([closed])


def test_the_installation_cap_is_the_lowest_of_the_hard_circuit_and_boiler_maximum() -> None:
    """S-23: the ramp is skipped only above this cap — never for the weather ceiling."""
    assert install_cap(LIMITS) == 70.0
    assert install_cap(LIMITS, circuit_max=45.0) == 45.0
    assert install_cap(LIMITS, circuit_max=45.0, boiler_max=40.0) == 40.0
    assert install_cap(LIMITS, boiler_max=80.0) == 70.0
