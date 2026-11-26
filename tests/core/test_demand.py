"""Boiler demand: VT's decision, and the zones that call (I12)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.demand import (
    Demand,
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
        (zone(valve_open=0.03), True),  # VT's rule: a valve open at all (2026-10-14)
        (zone(valve_open=0.0), False),
        (zone(on_percent=0.5), True),
        (zone(on_percent=0.03), True),  # a duty cycle above 0: it asks within its cycle
        (zone(on_percent=0.0), False),
        (zone(valve_open=0.0, on_percent=0.4), False),  # a valve's opening decides, not the cycle
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
    assert zone_wants_heat(state) is wants


@pytest.mark.parametrize("vt", [True, False, None])
def test_vts_decision_is_the_demand_and_the_zones_are_counted(vt: bool | None) -> None:
    """VT's central boiler decides (I12): its decision is the demand, whatever the zones show —
    a room calling with VT off is "rooms call, VT does not"; the calling rooms are counted for
    the display and the call's reason."""
    zones = [zone("a", valve_open=0.5), zone("b", valve_open=0.0), zone("c", on_percent=0.2)]
    assert boiler_demand(zones, NOW, AGE, vt) == Demand(vt, 2, 3, ())


def test_vt_asking_with_no_zone_calling_is_still_demand() -> None:
    """VT's own thresholds count its devices and powers, which the plugin does not see: VT's
    "on" stands even with no room calling as the plugin reads them."""
    result = boiler_demand([zone("a", valve_open=0.0)], NOW, AGE, True)
    assert (result.wanted, result.zones_wanting) == (True, 0)


def test_stale_zones_do_not_count_and_no_fresh_zone_is_unknown() -> None:
    """With no zone known nothing can ask for heat, whatever VT's helper shows (decision 3)."""
    stale = zone("a", valve_open=0.9, reported_at=NOW - 2 * AGE)
    assert boiler_demand([stale], NOW, AGE, True) == Demand(None, unknown=("a",))
    assert boiler_demand([], NOW, AGE, True) == Demand(None)
    mixed = boiler_demand([stale, zone("b", valve_open=0.0)], NOW, AGE, False)
    assert mixed == Demand(False, 0, 1, ("a",))


@pytest.mark.parametrize(
    "unknown",
    [
        zone("a", heating_enabled=None, valve_open=0.9),  # `unavailable`, or a mode not known
        zone("a", ready=False, valve_open=0.9),  # heating, but VT has not finished starting it
        zone("a", reported=False, valve_open=0.9),  # heating, VT's first refresh still to come
        zone("a", valve_open=0.9, temperature_at=NOW - 2 * AGE),  # its room sensor went quiet
    ],
)
def test_a_zone_that_is_not_known_is_never_counted(unknown: ZoneState) -> None:
    """Alone it makes demand unknown (decision 3 then decides); with others, the known ones are
    counted and VT decides."""
    assert boiler_demand([unknown], NOW, AGE, True) == Demand(None, unknown=("a",))
    other = boiler_demand([unknown, zone("b", valve_open=0.0)], NOW, AGE, True)
    assert other == Demand(True, 0, 1, ("a",))


def test_the_temperature_age_decides_freshness() -> None:
    """VT rewrites its climate often: its report time says little about the room sensor."""
    fresh = zone(valve_open=0.5, reported_at=NOW - 3 * AGE, temperature_at=NOW - 10.0)
    assert fresh.is_fresh(NOW, AGE)
    assert not zone(reported_at=NOW, temperature_at=NOW - 2 * AGE).is_fresh(NOW, AGE)


@pytest.mark.parametrize(
    ("ready", "reported", "known"),
    [
        (None, False, False),  # VT's placeholder: neither ``is_ready`` nor ``specific_states``
        (False, False, False),  # ``is_ready`` false: VT cannot start it
        (None, True, True),  # an older VT: ``specific_states`` without ``is_ready``
        (True, True, True),  # started
    ],
)
def test_an_off_zone_not_started_after_the_recognition(
    ready: bool | None, reported: bool, known: bool
) -> None:
    """T-17 (S-34) and SB-02: "off" is the user's "off" only on a zone VT has started. VT's
    placeholder and ``is_ready`` false stay unknown after the recognition period too (check C's
    F1)."""
    off = zone("a", heating_enabled=False, ready=ready, reported=reported, temperature=19.0)
    result = boiler_demand([off], NOW, AGE, False)
    assert result.wanted is (False if known else None)
    assert result.unknown == (() if known else ("a",))


@pytest.mark.parametrize("ready", [False, None])
def test_a_heating_zone_not_ready_is_unknown(ready: bool | None) -> None:
    heating = zone("a", ready=ready, reported=False, valve_open=0.6)
    assert boiler_demand([heating], NOW, AGE, True) == Demand(None, unknown=("a",))


def test_a_shed_zone_does_not_call() -> None:
    """T-45's core: VT's power shedding holds the zone off — whatever its duty cycle or its
    device showed last."""
    shed = zone("a", valve_open=0.6, device_active=True, power=2.0, on_percent=0.6, shedding=True)
    assert zone_wants_heat(shed) is False
    assert boiler_demand([shed], NOW, AGE, False) == Demand(False, 0, 1, ())


def test_a_remembered_zone_keeps_its_last_answer() -> None:
    """The grace (decision 3): a zone that stopped answering keeps its last known state, as a
    known zone — counted, and keeping VT's decision in force."""
    last = zone("a", valve_open=0.6, device_active=True)
    gone = ZoneState("a")  # unavailable now
    other = zone("b", valve_open=0.0)
    result = boiler_demand([gone, other], NOW, AGE, True, memory={"a": last})
    assert result == Demand(True, 1, 2, ())
    assert boiler_demand([gone], NOW, AGE, True, memory={"a": last}).wanted is True
    assert boiler_demand([gone], NOW, AGE, True) == Demand(None, unknown=("a",))  # no memory


def test_a_zone_in_vts_safety_mode_stays_known_and_is_counted_as_vt_runs_it() -> None:
    """VT's safety mode (the room sensor gone quiet): VT keeps running the zone on its safety
    duty, its device pulsing. The zone stays known — never unknown — and calls as VT's pulses
    show; the lost sensor only raises the zone's alarm (S-35)."""
    normal = zone("a", on_percent=0.6, device_active=True, temperature=19.0)
    pulse_on = replace(
        normal, on_percent=0.1, device_active=True, safety_on=True, room_sensor_lost=True
    )
    pulse_off = replace(pulse_on, device_active=False)
    results = [boiler_demand([z], NOW, AGE, True) for z in (normal, pulse_on, pulse_off)]
    assert [(r.zones_wanting, r.fresh_zones, r.unknown) for r in results] == [
        (1, 1, ()),
        (1, 1, ()),
        (0, 1, ()),
    ]


def test_an_open_window_switching_a_zone_off_leaves_it_known() -> None:
    """VT's window detection with its "turn off" action: the zone goes to "off" while VT keeps
    it started — known, not calling, so no "no zone known" end state follows."""
    heating = zone("a", valve_open=0.7, calling=True, ready=True, reported=True)
    window_off = replace(heating, heating_enabled=False, valve_open=0.0, calling=False)
    assert boiler_demand([window_off], NOW, AGE, False) == Demand(False, 0, 1, ())
    assert boiler_demand([heating], NOW, AGE, True) == Demand(True, 1, 1, ())


def test_a_vt_restart_off_and_not_ready_then_started() -> None:
    """VT reloads: before its first refresh each thermostat shows a placeholder "off", without
    ``is_ready``. Such a zone is unknown, as is a heating mode VT has not started; once VT has
    started the zone, it counts as it shows."""
    placeholder = zone("a", heating_enabled=False, ready=None, reported=False, temperature=None)
    heat_unstarted = zone("a", valve_open=0.6, ready=False, reported=False)
    started = zone("a", valve_open=0.6, ready=True, reported=True)
    results = [boiler_demand([z], NOW, AGE, True) for z in (placeholder, heat_unstarted, started)]
    assert [(r.wanted, r.fresh_zones, r.unknown) for r in results] == [
        (None, 0, ("a",)),
        (None, 0, ("a",)),
        (True, 1, ()),
    ]


@pytest.mark.parametrize(
    "state",
    [
        zone(valve_open=0.0),  # a closed valve
        zone(on_percent=0.0),  # a duty cycle of 0
        zone(auto_mode=True, valve_open=0.0),
        zone(auto_mode=True),  # no action and no opening: nothing says it heats
    ],
)
def test_a_zone_neither_open_nor_cycling_does_not_want_heat(state: ZoneState) -> None:
    """Negative: without VT's own word, a zone wants heat only with its valve open at all, or
    without a valve its duty cycle above 0 — VT's rule (2026-10-14); closed, at 0, or with
    nothing to judge by, it does not, in "auto" alike."""
    assert zone_wants_heat(state) is False
