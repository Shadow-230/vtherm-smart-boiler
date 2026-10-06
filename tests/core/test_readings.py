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
    ("state", "known", "reported"),
    [
        (zone(), False, False),  # no mode: unavailable, unknown, a mode not listed
        (zone(heating_enabled=True, reported=True), True, True),
        (zone(heating_enabled=False, reported=True), True, True),
        # Heat or auto that VT does not run yet: unknown.
        (zone(heating_enabled=True, reported=False, ready=False), False, False),
        (zone(heating_enabled=True, reported=False), False, False),
        # "Off" that VT has not started, neither ``is_ready`` nor ``specific_states`` shown: VT's
        # placeholder, kept for good while none of its devices has reported (VT 10.4.0) — not
        # the user's "off": unknown after the recognition period too (SB-02, check C's F1).
        (zone(heating_enabled=False, reported=False), False, False),
        # VT says it has not started it (``is_ready`` false): it cannot — a device unavailable —
        # so its "off" is not the user's: unknown after the recognition period too (SB-02).
        (zone(heating_enabled=False, reported=False, ready=False), False, False),
        (zone(heating_enabled=False, ready=False), False, False),
        # Started and "off": the user's "off", known without demand (S-34).
        (zone(heating_enabled=False, reported=True, ready=True), True, True),
        (zone(heating_enabled=True), True, True),  # nothing said about the start: as before
        (zone(heating_enabled=True, ready=False), False, False),
        (zone(heating_enabled=True, reported=True, reported_at=None), False, False),  # never
    ],
)
def test_which_zones_are_known(state: ZoneState, known: bool, reported: bool) -> None:
    assert state.is_known(NOW, None) is known
    assert state.has_reported(NOW, None) is reported  # what the recognition period waits for


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
