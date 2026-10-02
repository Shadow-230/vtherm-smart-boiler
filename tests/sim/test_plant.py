"""The plant stepped from outside: overrides that lapse or hold, valves driven from outside, the
boiler's own regulation, its restart lockout and pump overrun, emitter inertia, and the
gateway's ``CH=0`` flag against each kind of wall thermostat."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest
from custom_components.boiler_sim.plant import (
    EMITTER_TAU_S,
    Plant,
    PlantOutput,
    Request,
    WithoutOverride,
)
from custom_components.boiler_sim.profiles import (
    BOILERS,
    HOUSES,
    LONG_RESTART_LOCKOUT_S,
    ZoneProfile,
    radiator_zones,
)

from custom_components.vtherm_smart_boiler.core.installation import EmitterType


def plant(**kwargs) -> Plant:
    return Plant(BOILERS["condensing_small"], HOUSES["average"], radiator_zones(), 40.0, **kwargs)


def run(p: Plant, start: float, seconds: float, outdoor: float, **step) -> list[PlantOutput]:
    return [
        p.step(start + i * 10.0, 10.0, outdoor, False, **step) for i in range(int(seconds // 10))
    ]


def test_an_override_lapses_unless_repeated() -> None:
    p = plant(override_expires_s=60.0)
    p.set_setpoint(0.0, 45.0)
    assert p.override_active(60.0)
    assert not p.override_active(61.0)


def test_a_holding_override_never_lapses() -> None:
    p = plant(override_expires_s=60.0)
    p.set_setpoint(0.0, 45.0, holds=True)
    assert p.override_active(86400.0)
    p.clear_override()
    assert not p.override_active(1.0)


def test_valves_from_outside_drive_the_emitters() -> None:
    p = plant(without_override=WithoutOverride.OWN_CURVE)
    closed = p.step(0.0, 10.0, 0.0, False, [0.0] * len(p.zones))
    assert closed.emitted_kw == 0.0
    assert not closed.demand
    opened = p.step(10.0, 10.0, 0.0, False, [1.0] * len(p.zones))
    assert opened.demand
    assert opened.emitted_kw > 0.0


def test_standalone_without_override_does_not_heat() -> None:
    p = plant(without_override=WithoutOverride.OFF)
    out = p.step(0.0, 10.0, -5.0, False, [1.0] * len(p.zones))
    assert not out.demand
    assert not out.flame


# --- P-112: the boiler holds its flow at the setpoint; emitters have inertia --------------------


def test_the_boiler_regulates_its_own_flow_with_emitter_inertia() -> None:
    """P-112. Given a load above the minimum power, the boiler modulates and its reported flow
    settles at the setpoint — no auxiliary flow above it. Given a load below it, the flow rises
    above the setpoint only at the minimum power, the burner stops once the flow is 5 K above
    it and lights again only once the water is 5 K below it. An emitter passes the heat it
    takes from the water on to its room with first-order inertia: about 63 % after its time
    constant — 20 minutes for a radiator, 2 hours for underfloor heating — and the room still
    gets heat after the valve closed, while the water gives none."""
    boiler = BOILERS["condensing_small"]
    cold = plant()
    cold.set_setpoint(0.0, 50.0, holds=True)
    outs = run(cold, 0.0, 3 * 3600.0, -5.0, openings=[1.0] * 3)
    late = [o for o in outs[-360:] if o.flame and o.power_kw > boiler.min_power_kw + 0.1]
    assert late, "the burner must modulate above its minimum for this case to mean anything"
    assert all(abs(o.flow - 50.0) <= 0.5 for o in late), max(o.flow for o in late)
    assert all(o.flow <= 50.0 + 0.5 for o in outs if o.power_kw > boiler.min_power_kw + 0.1)

    mild = plant()
    mild.set_setpoint(0.0, 40.0, holds=True)
    outs = run(mild, 0.0, 6 * 3600.0, 16.0, openings=[0.2] * 3)  # valves nearly closed
    starts = [i for i in range(1, len(outs)) if outs[i].flame and not outs[i - 1].flame]
    stops = [i for i in range(1, len(outs)) if outs[i - 1].flame and not outs[i].flame]
    assert len(starts) >= 3, "the load below the minimum power makes it cycle"
    for i in stops:
        assert outs[i - 1].flow > 40.0 + 5.0 - 0.5  # stopped at the setpoint + 5 K
    for i in starts:
        assert outs[i - 1].water < 40.0 - 5.0 + 0.1  # lit again 5 K below it
    above = [o for o in outs if o.flow > 40.0 + 0.5]
    assert above
    assert all(o.power_kw in (0.0, boiler.min_power_kw) for o in above)

    for emitter, tau in ((EmitterType.RADIATOR, 20 * 60.0), (EmitterType.UNDERFLOOR, 2 * 3600.0)):
        assert EMITTER_TAU_S[emitter] == tau
        zone = ZoneProfile("zone", 1.0, emitter)
        p = Plant(boiler, HOUSES["average"], (zone,), 45.0)
        p.set_setpoint(0.0, 45.0, holds=True)
        outs = []
        for i in range(int(tau // 10)):
            p.water = 45.0  # the water held steady: the emitter's own response alone
            outs.append(p.step(i * 10.0, 10.0, 0.0, False, [1.0]))
        taken = outs[-1].emitted_kw
        assert outs[0].room_kw < 0.05 * taken  # nothing reaches the room at once
        assert outs[-1].room_kw == pytest.approx(taken * (1 - math.exp(-1)), rel=0.1)
        p.water = 45.0
        after = p.step(tau, 10.0, 0.0, False, [0.0])
        assert after.emitted_kw == 0.0  # the valve closed: the water gives nothing
        assert after.room_kw > 0.5 * outs[-1].room_kw  # the emitter still warms the room


def test_a_settled_start_neither_warms_nor_cools_the_rooms() -> None:
    """A run begins with each emitter passing on its room's loss: no room drifts merely because
    the run began, whatever the emitter's inertia."""
    p = plant()
    p.settle(0.0)
    rooms = list(p.room)
    out = p.step(0.0, 10.0, 0.0, False, [0.0] * 3)
    assert out.room_kw > 0.0
    for before, after in zip(rooms, p.room, strict=True):
        assert after == pytest.approx(before, abs=1e-4)


# --- Z3 rule 8: the restart lockout and the pump overrun ------------------------------------


def test_restart_lockout_and_pump_overrun() -> None:
    """Rule 8. A boiler with a 20-minute restart lockout (test-only): once the heating demand
    ends the burner stops and the pump runs on for 5 minutes, the emitters still taking heat
    from the water; the demand back a minute later, with the water cold, the burner waits out
    the lockout — shown, and no fault — and lights at its end. A fault the boiler reports keeps
    it off after the lockout; its fault signal missing changes nothing here."""
    boiler = replace(BOILERS["condensing_small"], anti_cycle_s=LONG_RESTART_LOCKOUT_S)
    assert LONG_RESTART_LOCKOUT_S == 20 * 60.0
    assert boiler.pump_overrun_s == 5 * 60.0
    p = Plant(boiler, HOUSES["average"], radiator_zones(), 30.0)
    call, stop = Request(True), Request(False)
    outs = run(p, 0.0, 600.0, 0.0, openings=[1.0] * 3, request=call)
    assert outs[-1].flame
    stopped = 600.0
    outs = run(p, stopped, 60.0, 0.0, openings=[1.0] * 3, request=stop)
    assert not outs[0].flame
    assert all(o.pump for o in outs)
    assert all(o.emitted_kw > 0.0 for o in outs)  # the overrun carries the heat out
    p.water = 20.0  # cold: the boiler would light at once but for its lockout
    outs = run(p, stopped + 60.0, 20 * 60.0, 0.0, openings=[1.0] * 3, request=call)
    waiting = [o for o in outs if stopped + 60.0 + outs.index(o) * 10.0 < stopped + 20 * 60.0]
    assert not any(o.flame for o in waiting)
    assert all(o.lockout for o in waiting)
    assert outs[-1].flame  # the lockout over: it lights
    assert not p.fault

    q = Plant(boiler, HOUSES["average"], radiator_zones(), 30.0)
    run(q, 0.0, 600.0, 0.0, openings=[1.0] * 3, request=call)
    outs = run(q, 600.0, 400.0, 0.0, openings=[1.0] * 3, request=stop)
    assert [o.pump for o in outs].index(False) * 10.0 == pytest.approx(300.0, abs=10.0)
    q.water = 20.0
    q.fault = True  # the boiler's own lockout fault, reported or not
    outs = run(q, 1000.0, 3600.0, 0.0, openings=[1.0] * 3, request=call)
    assert not any(o.flame for o in outs)
    q.fault = False
    assert q.step(4600.0, 10.0, 0.0, False, [1.0] * 3, call).flame


# --- the gateway's CH=0 flag (PIC 6.6) and the wall thermostat's kind -------------------------


@pytest.mark.parametrize(
    ("masked", "heats"), [(True, False), (False, True)], ids=["on_off_contact", "opentherm"]
)
def test_the_gateway_ch_off_masks_an_on_off_contact_not_an_opentherm_thermostat(
    masked: bool, heats: bool
) -> None:
    """T-07's plant part: after ``CH=0`` the flag outlives ``CS=0`` and the override's lapse; an
    on/off contact's demand is masked, an OpenTherm thermostat's own CH bit passes; under any
    override the flag masks CH enable for both; ``CH=1`` clears it."""
    p = plant(override_expires_s=60.0)
    p.set_setpoint(0.0, 50.0)
    p.gateway_ch_off = True
    request = Request(True, 60.0, masked=masked)
    assert not p.step(10.0, 10.0, 0.0, False, [1.0] * 3, request).demand  # under the override
    p.clear_override()  # CS=0
    assert p.step(20.0, 10.0, 0.0, False, [1.0] * 3, request).demand is heats
    p.set_setpoint(30.0, 50.0)
    out = run(p, 100.0, 60.0, 0.0, openings=[1.0] * 3, request=request)[-1]  # lapsed by now
    assert not out.override
    assert out.demand is heats
    p.gateway_ch_off = False  # CH=1
    assert p.step(200.0, 10.0, 0.0, False, [1.0] * 3, request).demand


def test_a_heating_switch_never_renews_the_setpoint_override() -> None:
    """Open after R6 #2: a heating switch has a write type of its own; repeating it does not
    keep an expiring setpoint alive, and a held "off" outlasts the setpoint's lapse."""
    p = plant(override_expires_s=60.0)
    p.set_setpoint(0.0, 50.0)
    for t in (30.0, 60.0, 90.0):
        p.set_heating(t, True, holds=False)
    assert not p.override_active(90.0)  # lapsed at 60 s whatever the switch did
    assert p.heating_allowed(90.0) is True
    p.set_heating(100.0, False, holds=True)
    assert p.heating_allowed(10_000.0) is False
    assert not p.step(10_000.0, 10.0, 0.0, False, [1.0] * 3).demand
    p.set_heating(10_010.0, True, holds=False)
    assert p.heating_allowed(10_071.0) is None  # an expiring switch lapses: nothing in force
