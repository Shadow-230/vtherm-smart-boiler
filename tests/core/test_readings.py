"""Current readings: freshness, plausibility, typed access and zone helpers."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.curve import (
    OutdoorSource,
    OutdoorState,
    update_outdoor,
)
from custom_components.vtherm_smart_boiler.core.readings import (
    UNKNOWN,
    BoilerSnapshot,
    Reading,
    ZoneState,
)
from custom_components.vtherm_smart_boiler.core.signals import (
    GATEWAY_OUTDOOR_ZERO_NEAR_K,
    LINK_SIGNALS,
    SIGNAL_SPECS,
    GatewayOutdoor,
    Signal,
)


def test_every_signal_has_a_spec_and_flame_and_flow_form_the_boiler_link() -> None:
    """SB-21: flame and flow are optional for the entry (X8); they are the boiler link's
    signals, which water-temperature control needs mapped."""
    assert set(SIGNAL_SPECS) == set(Signal)
    assert LINK_SIGNALS == {Signal.FLAME, Signal.FLOW}


def test_a_gateway_zero_is_unknown_for_pressure_and_every_measured_temperature() -> None:
    """PB-21: an OpenTherm Gateway shows 0 after a PIC reset (and for good where the boiler
    never answers an ID) — for pressure and every measured temperature it is unknown; a
    setpoint's 0 is a value (a hand-back, no request); binary and counter signals are apart."""
    measured = {
        Signal.PRESSURE,
        Signal.FLOW,
        Signal.RETURN,
        Signal.FLUE_GAS,
        Signal.OUTDOOR,
        Signal.ROOM_TEMPERATURE,
    }
    assert {s for s, spec in SIGNAL_SPECS.items() if spec.gateway_zero_unknown} == measured
    assert not SIGNAL_SPECS[Signal.CH_SETPOINT].gateway_zero_unknown
    assert not SIGNAL_SPECS[Signal.ROOM_SETPOINT].gateway_zero_unknown


def test_water_below_freezing_is_implausible() -> None:
    """PB-21: a flow or return below 0 °C is a broken sensor, not water in a heating circuit."""
    for signal in (Signal.FLOW, Signal.RETURN):
        assert not SIGNAL_SPECS[signal].plausible(-0.5)
        assert SIGNAL_SPECS[signal].plausible(0.0)
        assert SIGNAL_SPECS[signal].plausible(20.0)


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


# --- X3: which zones are known and which have reported ------------------------------------------

NOW = 1000.0


def zone(**kw) -> ZoneState:
    kw.setdefault("reported_at", NOW)
    return ZoneState("z", **kw)


@pytest.mark.parametrize(
    ("state", "known"),
    [
        (zone(), False),  # no mode: not handed over, or a mode not listed
        (zone(heating_enabled=True), True),
        (zone(heating_enabled=False), True),  # started and "off": the user's "off" (S-34)
        # Heat, or "off", that VT has not started — no ``refresh_state`` on the manager yet
        # (I12.7): not the user's "off", unknown after the recognition period too (SB-02, check
        # C's F1).
        (zone(heating_enabled=True, started=False), False),
        (zone(heating_enabled=False, started=False), False),
        (zone(started=True), False),  # a mode must be known too
        (zone(heating_enabled=True, reported_at=None), False),  # never read
    ],
)
def test_which_zones_are_known(state: ZoneState, known: bool) -> None:
    assert state.is_known(NOW, None) is known
    assert state.has_reported(NOW, None) is known  # what the recognition period waits for


def test_a_zone_beyond_its_age_limit_is_unknown() -> None:
    state = zone(heating_enabled=True, reported_at=NOW - 700.0)
    assert state.is_known(NOW, None)
    assert not state.is_known(NOW, 600.0)
    assert not state.has_reported(NOW, 600.0)


def test_a_zone_is_fresh_when_read_whatever_its_measurement() -> None:
    """I12.7: VT keeps the thermostat's values live; how old the room's measurement is, VT's
    safety mode and the rooms' trust tell, not freshness."""
    assert zone(temperature_at=NOW - 7200.0).is_fresh(NOW, 600.0)
    assert not zone(reported_at=None, temperature_at=NOW).is_fresh(NOW, None)


@pytest.mark.parametrize(
    ("state", "full"),
    [
        (ZoneState("z", valve_open=0.95), True),
        (ZoneState("z", valve_open=0.9, on_percent=1.0), False),  # the valve decides
        (ZoneState("z", on_percent=1.0), True),
        (ZoneState("z", on_percent=0.8), False),  # VT's cap is not seen (I12.7)
        (ZoneState("z"), False),  # nothing applied yet
    ],
)
def test_a_zone_is_fully_open_at_95_percent(state: ZoneState, full: bool) -> None:
    assert state.fully_open is full


def _outdoor_run(values: list[float | None], step_s: float = 30 * 60) -> list[OutdoorState]:
    """Gateway outdoor readings, one every ``step_s``, through the zero rule and the curve's
    effective outdoor temperature (no weather entity)."""
    memory = GatewayOutdoor()
    state = OutdoorState()
    states = []
    for index, value in enumerate(values):
        state = update_outdoor(state, memory.read(value), None, index * step_s)
        states.append(state)
    return states


def test_a_gateway_outdoor_zero_near_the_last_reading_is_a_reading_for_hours() -> None:
    """PB-21, M1: a boiler reporting whole or half degrees reads exactly 0 for hours at
    freezing — after a reading near 0 it is 0 °C, not unknown; no fallback after the hold."""
    states = _outdoor_run([1.0] + [0.0] * 9)  # 0 °C for 4.5 h
    assert all(state.source is OutdoorSource.SENSOR for state in states)
    assert states[-1].effective == pytest.approx(0.0, abs=0.3)
    states = _outdoor_run([0.5] + [0.0] * 9)
    assert all(state.source is OutdoorSource.SENSOR for state in states)
    assert GatewayOutdoor(-2.0).read(0.0) == 0.0  # the margin itself counts as near


def test_a_gateway_outdoor_zero_far_from_the_last_reading_or_first_is_unknown() -> None:
    """PB-21, M1: the gateway's reset shows 0 — after a reading more than 2 K away, or with no
    reading yet in this run, a 0 is unknown, and so are the zeros after it."""
    assert GATEWAY_OUTDOOR_ZERO_NEAR_K == 2.0
    for first in (8.0, -2.5, 2.1):
        memory = GatewayOutdoor()
        assert memory.read(first) == first
        assert memory.read(0.0) is None
        assert memory.read(0.0) is None
        assert memory.read(1.5) == 1.5  # a real reading again
        assert memory.read(0.0) == 0.0
    memory = GatewayOutdoor()
    assert memory.read(0.0) is None
    assert memory.read(0.0) is None
    states = _outdoor_run([8.0] + [0.0] * 8)
    assert states[1].source is OutdoorSource.HELD
    assert states[-1].source is OutdoorSource.NONE  # unknown, as before: the hold then ends


def test_a_gateway_outdoor_zero_after_an_unknown_state_is_unknown() -> None:
    """PB-21, M1: a state that is unknown (``None``: unavailable, missing, implausible) is a
    trace of the gateway's outage or reset — the next 0 is unknown until a real reading."""
    memory = GatewayOutdoor()
    assert memory.read(0.5) == 0.5
    assert memory.read(None) is None
    assert memory.read(0.0) is None
    assert memory.last is None
    assert memory.read(-0.5) == -0.5
    assert memory.read(0.0) == 0.0


def test_a_plausible_range_includes_its_bounds_and_may_be_open() -> None:
    """TB-28, the pure cases of ``SignalSpec.plausible``: a value on either bound is plausible,
    one past it is not; a bound not set limits nothing."""
    from custom_components.vtherm_smart_boiler.core.signals import SignalKind, SignalSpec

    both = SignalSpec(SignalKind.TEMPERATURE, low=0.0, high=110.0)
    assert [both.plausible(v) for v in (-0.1, 0.0, 110.0, 110.1)] == [False, True, True, False]
    assert SignalSpec(SignalKind.PRESSURE, low=0.0).plausible(1e6)
    assert SignalSpec(SignalKind.PRESSURE, high=4.0).plausible(-1e6)
    assert not SignalSpec(SignalKind.PRESSURE, high=4.0).plausible(4.01)


# --- Mutation testing (2026-10-12): ages and freshness at their exact bounds ------------------


def test_a_reading_reported_this_moment_is_zero_seconds_old() -> None:
    """A report at this very moment, or under a second ago, has that age — never rounded up;
    one "later than now" (a clock set back) is 0 seconds old."""
    reading = Reading(45.0, reported_at=100.0)
    assert reading.age(100.0) == 0.0
    assert reading.age(100.5) == 0.5
    assert reading.age(90.0) == 0.0


def test_a_fresh_reading_within_its_age_limit_is_used() -> None:
    """With ``max_age`` set, a reading reported within it gives its value — a number or a
    flag alike."""
    snapshot = BoilerSnapshot(
        t=1000.0,
        readings={Signal.FLOW: Reading(50.0, 990.0), Signal.FLAME: Reading(True, 990.0)},
    )
    assert snapshot.number(Signal.FLOW, max_age=60.0) == 50.0
    assert snapshot.flag(Signal.FLAME, max_age=60.0) is True


def test_a_stale_flag_is_unknown() -> None:
    """Negative: a binary signal reported longer ago than ``max_age`` is unknown, as a stale
    number is — not its last value."""
    snapshot = BoilerSnapshot(t=1000.0, readings={Signal.FLAME: Reading(True, 10.0)})
    assert snapshot.flag(Signal.FLAME, max_age=60.0) is None
    assert snapshot.flag(Signal.FLAME) is True


def test_a_zone_reported_exactly_its_age_limit_ago_is_fresh() -> None:
    """The age limit includes its bound: reported exactly ``max_age`` ago is still fresh, a
    second more is not."""
    state = ZoneState("z", reported_at=100.0)
    assert state.is_fresh(160.0, 60.0)
    assert not state.is_fresh(161.0, 60.0)
