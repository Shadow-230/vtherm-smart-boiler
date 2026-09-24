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
    SignalKind,
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


def test_binary_specs_have_no_age_limit() -> None:
    binary = [s for s, spec in SIGNAL_SPECS.items() if spec.kind is SignalKind.BINARY]
    assert binary
    assert all(SIGNAL_SPECS[s].max_age_s is None for s in binary)


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
