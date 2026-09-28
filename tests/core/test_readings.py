"""Current readings: freshness, plausibility, typed access and zone helpers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import (
    UNKNOWN,
    BoilerSnapshot,
    Reading,
    ZoneState,
    plausible_reading,
)
from custom_components.vtherm_smart_boiler.core.signals import (
    REQUIRED_SIGNALS,
    SIGNAL_SPECS,
    Signal,
)


def test_every_signal_has_a_spec_and_flame_and_flow_are_required() -> None:
    assert set(SIGNAL_SPECS) == set(Signal)
    assert REQUIRED_SIGNALS == {Signal.FLAME, Signal.FLOW}


def test_reading_freshness() -> None:
    reading = Reading(45.0, reported_at=100.0)
    assert reading.age(160.0) == 60.0
    assert reading.is_fresh(160.0, max_age=60.0)
    assert not reading.is_fresh(161.0, max_age=60.0)
    assert reading.is_fresh(10_000.0, max_age=None)


def test_unknown_reading_is_never_fresh() -> None:
    assert not UNKNOWN.is_fresh(0.0, None)
    assert not Reading(None, 100.0).is_fresh(100.0, None)
    assert UNKNOWN.age(5.0) is None


@pytest.mark.parametrize(
    ("signal", "raw", "expected"),
    [
        (Signal.FLOW, 45, 45.0),
        (Signal.FLOW, 150.0, None),  # above the plausible range
        (Signal.FLOW, float("nan"), None),
        (Signal.FLOW, True, None),  # a bool is not a temperature
        (Signal.FLAME, True, True),
        (Signal.FLAME, 1.0, None),  # a number is not a flame state
        (Signal.MODULATION, -1.0, None),
        (Signal.PRESSURE, 1.4, 1.4),
        (Signal.OUTDOOR, None, None),
    ],
)
def test_plausible_reading(signal: Signal, raw: float | bool | None, expected: object) -> None:
    reading = plausible_reading(signal, raw, reported_at=5.0)
    assert reading.value == expected
    assert reading.reported_at == 5.0


def test_snapshot_typed_access_and_freshness() -> None:
    snapshot = BoilerSnapshot(
        t=1000.0,
        readings={
            Signal.FLOW: Reading(50.0, 990.0),
            Signal.RETURN: Reading(40.0, 100.0),
            Signal.FLAME: Reading(True, 10.0),
        },
    )
    assert snapshot.number(Signal.FLOW) == 50.0
    assert snapshot.number(Signal.RETURN) == 40.0
    assert snapshot.number(Signal.RETURN, max_age=60.0) is None  # stale
    assert snapshot.flag(Signal.FLAME) is True
    assert snapshot.flag(Signal.FLOW) is None  # wrong type
    assert snapshot.number(Signal.FLAME) is None
    assert snapshot.number(Signal.PRESSURE) is None  # not mapped
    assert snapshot.is_mapped(Signal.FLOW)
    assert not snapshot.is_mapped(Signal.PRESSURE)


def test_zone_deficit_and_demand() -> None:
    zone = ZoneState("z", temperature=19.5, target=21.0, on_percent=0.4, valve_open=0.7)
    assert zone.deficit == pytest.approx(1.5)
    assert zone.demand == 0.7
    assert ZoneState("z", on_percent=0.4).demand == 0.4
    assert ZoneState("z", temperature=20.0).deficit is None


def test_zone_freshness() -> None:
    zone = ZoneState("z", reported_at=100.0)
    assert zone.is_fresh(150.0, 60.0)
    assert not zone.is_fresh(200.0, 60.0)
    assert not ZoneState("z").is_fresh(0.0, None)


# --- X3: which zones are known, which have reported, and their mean power ----------------------

NOW = 1000.0


@pytest.mark.parametrize(
    ("reported", "ready", "started"),
    [
        (True, True, True),
        (False, False, False),
        (False, None, False),  # VT 10.4.0 before its first refresh: neither is_ready nor more
        (None, None, True),  # not said (a caller without VT's attributes): as before
        (None, False, False),
        (None, True, True),
    ],
)
def test_a_zone_is_started_as_vt_shows_it(
    reported: bool | None, ready: bool | None, started: bool
) -> None:
    assert ZoneState("z", reported=reported, ready=ready).started is started


def zone(**kw) -> ZoneState:
    kw.setdefault("reported_at", NOW)
    return ZoneState("z", **kw)


@pytest.mark.parametrize(
    ("state", "known", "known_in_recognition"),
    [
        (zone(), False, False),  # no mode: unavailable, unknown, a mode not listed
        (zone(heating_enabled=True, reported=True), True, True),
        (zone(heating_enabled=False, reported=True), True, True),
        # Heat or auto that VT does not run yet: unknown.
        (zone(heating_enabled=True, reported=False, ready=False), False, False),
        (zone(heating_enabled=True, reported=False), False, False),
        # "Off" that VT has not started: no demand once the recognition period is over (S-34).
        (zone(heating_enabled=False, reported=False, ready=False), True, False),
        (zone(heating_enabled=False, reported=False), True, False),
        (zone(heating_enabled=True), True, True),  # nothing said about the start: as before
        (zone(heating_enabled=True, ready=False), False, False),
        (zone(heating_enabled=True, reported=True, reported_at=None), False, False),  # never
    ],
)
def test_which_zones_are_known(state: ZoneState, known: bool, known_in_recognition: bool) -> None:
    assert state.is_known(NOW, None) is known
    assert state.is_known(NOW, None, recognition=True) is known_in_recognition


def test_a_zone_beyond_its_age_limit_is_unknown() -> None:
    state = zone(heating_enabled=True, reported=True, reported_at=NOW - 700.0)
    assert state.is_known(NOW, None)
    assert not state.is_known(NOW, 600.0)
    assert not state.has_reported(NOW, 600.0)


@pytest.mark.parametrize(
    ("state", "reported"),
    [
        (zone(heating_enabled=True, reported=True), True),
        (zone(heating_enabled=False, reported=True), True),
        (zone(heating_enabled=False, reported=False), False),  # VT's placeholder "off"
        (zone(heating_enabled=True, reported=False, ready=False), False),
        (zone(reported=True), False),  # a mode must be known too
        (zone(heating_enabled=True), True),  # nothing said about the start: as before
    ],
)
def test_a_zone_has_reported_when_vt_shows_it_started_with_its_mode(
    state: ZoneState, reported: bool
) -> None:
    assert state.has_reported(NOW, None) is reported


@pytest.mark.parametrize(
    ("state", "power"),
    [
        (ZoneState("z", mean_power=1.2, power=2.0, on_percent=0.3), 1.2),  # VT's own mean
        (ZoneState("z", mean_power=0.0, power=2.0, on_percent=0.3), 0.0),  # VT says none now
        (ZoneState("z", power=2.0, on_percent=0.6), 1.2),  # an older VT: power times duty
        (ZoneState("z", power=2.0, valve_open=0.5), 1.0),  # or times the valve's opening
        (ZoneState("z", power=2.0, on_percent=0.6, valve_open=0.5), 1.2),  # the duty first
        (ZoneState("z", power=2.0), None),  # no duty cycle: not known here
        (ZoneState("z", on_percent=0.6), None),  # no power: not known
        (ZoneState("z"), None),
    ],
)
def test_a_zones_mean_power_over_its_cycle(state: ZoneState, power: float | None) -> None:
    assert state.cycle_power == (None if power is None else pytest.approx(power))
