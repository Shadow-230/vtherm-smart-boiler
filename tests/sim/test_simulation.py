"""The simulated installation without Home Assistant: how writes reach the boiler and what is
counted (P-113), what the gateway shows (Open after R6 #2), the zone valves (S-05, P-114), and
the relay and wall-thermostat models (X8, X6; Z3 rules 7 and 9)."""

from __future__ import annotations

import time

import pytest
from custom_components.boiler_sim.plant import boiler_setpoint
from custom_components.boiler_sim.relay import RESTART_UNAVAILABLE_S, RelayModel, StartUp
from custom_components.boiler_sim.simulation import (
    MAX_CATCH_UP_S,
    RelaySetup,
    SimConfig,
    Simulation,
    Topology,
    Valves,
    WriteType,
    ZoneMode,
)
from custom_components.boiler_sim.thermostat import (
    DAY_SETPOINT,
    IDLE_WATER,
    NIGHT_SETPOINT,
    WallKind,
    WallThermostat,
    program,
)
from custom_components.boiler_sim.tpi import TpiConfig, TpiZone, on_percent

START = 1_768_197_600.0  # 2026-01-12 06:00 UTC: the wall thermostat's day program begins


def sim(**changes) -> Simulation:
    return Simulation(SimConfig(**changes), START)


# --- P-113: what counts as persistent; heating writes counted -----------------------------------


@pytest.mark.parametrize(
    ("write_type", "persistent"),
    [(WriteType.EXPIRING, 0), (WriteType.HELD, 0), (WriteType.PERSISTENT, 3)],
)
def test_only_persistent_writes_count_as_persistent(write_type: WriteType, persistent: int) -> None:
    """P-113: a held setpoint is kept by the device without wearing a memory — only writes of
    type persistent count; the gateway's commands never do."""
    s = sim(write_type=write_type)
    for value in (40.0, 41.0, 42.0):
        s.entity_setpoint(START, value)
    s.gateway_setpoint(START, 45.0)
    assert s.commands.persistent_writes == persistent


@pytest.mark.parametrize(
    ("ch_write_type", "persistent"),
    [(WriteType.HELD, 0), (WriteType.EXPIRING, 0), (WriteType.PERSISTENT, 2)],
)
def test_ch_writes_are_counted(ch_write_type: WriteType, persistent: int) -> None:
    """P-113: heating on/off writes have a counter of their own — the gateway's ``CH=`` and an
    entity's heating switch alike — and a heating switch the device stores counts as
    persistent too."""
    s = sim(ch_write_type=ch_write_type)
    s.gateway_heating(START, False)
    s.entity_heating(START, True)
    s.entity_heating(START, False)
    assert s.commands.ch_writes == 3
    assert s.commands.persistent_writes == persistent
    assert s.commands.dhw_enable_writes == 0


def test_heating_switch_has_its_own_write_type() -> None:
    """Open after R6 #2 (an EMS-ESP-like device): the setpoint expires within a minute unless
    repeated; the heating switch, held, never renews it — the boiler is back on its own
    regulation once the setpoint lapsed, while the switch's "off" stays in force."""
    s = sim(write_type=WriteType.EXPIRING, ch_write_type=WriteType.HELD, outdoor=-5.0)
    s.entity_setpoint(START, 55.0)
    for t in range(30, 151, 30):
        s.entity_heating(START + t, True)
        s.advance(START + t)
    assert not s.plant.override_active(s.t)  # lapsed: the heating writes did not renew it
    assert s.last.setpoint == boiler_setpoint(s.plant.boiler, -5.0)
    s.entity_heating(s.t, False)
    s.advance(s.t + 3600.0)
    assert not s.last.demand  # held "off": still in force an hour later
    expiring = sim(ch_write_type=WriteType.EXPIRING, outdoor=-5.0)
    expiring.entity_heating(START, False)
    expiring.advance(START + 120.0)
    assert expiring.plant.heating_allowed(expiring.t) is None  # lapsed in its turn


# --- Open after R6 #2: the gateway's read-back as opentherm_gw shows it ------------------------


@pytest.mark.parametrize("topology", [Topology.WITH_THERMOSTAT, Topology.STANDALONE])
def test_the_gateway_read_back_acknowledges_at_once_then_shows_what_the_boiler_gets(
    topology: Topology,
) -> None:
    """``opentherm_gw`` writes the gateway's acknowledgement at once; the next exchange shows
    what the boiler gets. A boiler that refuses ID 1 makes the gateway drop the override
    without a message: confirmed, then dropped — to the thermostat's value, or a stand-alone
    gateway's zero — every time it is sent again."""
    s = sim(topology=topology, outdoor=0.0)
    passed = 0.0 if topology is Topology.STANDALONE else boiler_setpoint(s.plant.boiler, 0.0)
    assert s.gateway_read_back() == passed
    s.gateway_setpoint(START, 50.0)
    s.advance(START)  # no time passes: the acknowledgement
    assert s.gateway_read_back() == 50.0
    s.advance(START + 10.0)
    assert s.gateway_read_back() == 50.0  # taken: it stays while repeated
    s.refuses_id1 = True
    for t in (30.0, 60.0):
        s.gateway_setpoint(START + t, 50.0)
        s.advance(START + t)
        assert s.gateway_read_back() == 50.0  # confirmed at once...
        s.advance(START + t + 10.0)
        assert s.gateway_read_back() == passed  # ...then dropped at the next exchange
        assert not s.plant.override_active(s.t)
    s.gateway_setpoint(START + 90.0, 0.0)
    s.advance(START + 90.0)
    assert s.gateway_read_back() == 0.0  # CS=0 acknowledged
    s.advance(START + 100.0)
    assert s.gateway_read_back() == passed


def test_a_gateway_out_of_reach_drops_its_commands_and_shows_nothing() -> None:
    """Missing data: the gateway lost (or restarting) — its services return all the same, the
    command is dropped, and its read-back and CH enable are unknown. A reset loses ``CS``,
    ``CH`` and ``MM``."""
    s = sim(outdoor=0.0)
    s.gateway_setpoint(START, 50.0)
    s.gateway_heating(START, False)
    s.gateway_max_modulation(START, 40)
    s.failed.add("gateway")
    s.gateway_setpoint(START + 10.0, 60.0)
    s.advance(START + 10.0)
    assert s.gateway_read_back() is None
    assert s.gateway_ch_enable() is None
    assert s.plant.override_setpoint == 50.0  # 60 never arrived
    s.failed.discard("gateway")
    s.reset_gateway(START + 20.0)
    s.advance(START + 20.0)
    assert s.gateway_read_back() is None  # restarting
    assert not s.plant.override_active(s.t)
    assert not s.plant.gateway_ch_off
    assert s.plant.max_modulation is None
    s.advance(START + 20.0 + 10.0)
    assert s.gateway_read_back() == boiler_setpoint(s.plant.boiler, 0.0)
    s.gateway_command(START + 40.0, "CS", "48")
    s.gateway_command(START + 40.0, "MM", "x")  # refused by the gateway: nothing changes
    s.gateway_command(START + 40.0, "GW", "R")
    assert ("command", "CS=48") in [(kind, value) for _t, kind, value in s.commands.gateway]
    assert not s.plant.override_active(START + 40.0)  # the reset came after it


# --- S-05, P-114: the zone valves -----------------------------------------------------------


@pytest.mark.parametrize("valves", [Valves.THERMOSTATIC, Valves.SWITCH, Valves.TPI])
def test_off_zones_close_their_valves(valves: Valves) -> None:
    """S-05: a zone VT switched off keeps its valve closed — its room cools and its emitter
    takes no heat, whatever its head or switch would do; VT's "sleep" holds it open; back in
    heat, it opens again."""
    s = sim(valves=valves, outdoor=-5.0)
    for zone in s.zones:
        s.valves[zone.zone_id] = True
    s.plant.room[0] = 10.0  # cold: a head, a switch and TPI would all open
    s.set_zone_mode("zone_living", ZoneMode.OFF)
    s.advance(START + 600.0)
    assert s.opening("zone_living") == 0.0
    assert s.on_percent("zone_living") in (None, 0.0)
    s.set_zone_mode("zone_living", ZoneMode.SLEEP)
    s.advance(START + 610.0)
    assert s.opening("zone_living") == 1.0
    s.set_zone_mode("zone_living", ZoneMode.HEAT)
    s.advance(START + 1200.0)
    assert max(s.opening("zone_living"), s.on_percent("zone_living") or 0.0) > 0.0


def test_tpi_zones_open_for_their_on_percent_of_each_cycle() -> None:
    """P-114: a switch zone under TPI is open for its on-percent of each 5-minute cycle, the
    on-percent taken at the cycle's start from the room, its target and the outdoor
    temperature."""
    config = TpiConfig()
    assert (config.cycle_s, config.coef_int, config.coef_ext) == (300.0, 0.6, 0.01)
    assert on_percent(config, 20.0, 19.0, 0.0) == pytest.approx(0.6 + 0.2)
    assert on_percent(config, 20.0, 22.0, 30.0) == 0.0
    assert on_percent(config, 20.0, 15.0, -10.0) == 1.0
    zone = TpiZone(config)
    openings = [zone.advance(t, 20.0, 19.5, 5.0) for t in range(0, 600, 10)]
    share = 0.6 * 0.5 + 0.01 * 15.0
    assert sum(openings[:30]) == pytest.approx(share * 30, abs=1.0)
    assert openings[:3] == [1.0] * 3
    assert openings[29] == 0.0


# --- X8; rule 7: the relay --------------------------------------------------------------------


def test_the_relay_model_restarts_into_its_state_after_a_power_cut() -> None:
    """A restart Home Assistant sees: out of reach for 10 s, its contact open, then its state
    after a power cut — off, on, or the last; one it does not see: that state at once, still
    available. Each is a change of its own."""
    assert RESTART_UNAVAILABLE_S == 10.0
    for start_up, after in ((StartUp.OFF, False), (StartUp.ON, True), (StartUp.LAST, True)):
        relay = RelayModel(start_up=start_up)
        relay.command(0.0, True)
        relay.restart(100.0)
        assert not relay.available
        assert not relay.contact
        relay.advance(105.0)
        assert not relay.available
        relay.advance(110.0)
        assert relay.available
        assert relay.on is after
        assert relay.own_changes == 1
        quiet = RelayModel(start_up=start_up)
        quiet.command(0.0, True)
        quiet.restart(100.0, reported=False)
        assert quiet.available
        assert quiet.on is after
        assert quiet.own_changes == 1


def test_the_relay_model_keeps_its_state_and_timer_through_a_wifi_loss() -> None:
    relay = RelayModel(off_timer_s=600.0)
    relay.command(0.0, True)
    relay.wifi_loss(60.0, 300.0)
    relay.command(120.0, True)  # cannot reach it: lost
    relay.advance(300.0)
    assert not relay.available
    assert relay.on  # its contact as it was
    relay.advance(360.0)
    assert relay.available
    relay.advance(600.0)
    assert not relay.on  # its timer ran on, from the "on" at 0
    assert relay.commands == [(0.0, True), (120.0, True)]


@pytest.mark.parametrize("restarts", [True, False], ids=["tasmota_like", "not_restarted"])
def test_the_relay_model_timer_restarts_on_a_repeated_on_or_not(restarts: bool) -> None:
    """Tasmota's PulseTime restarts on every "on"; whether a Shelly's auto-off does is not
    documented (Q3.10), so the model has both."""
    relay = RelayModel(off_timer_s=600.0, timer_restarts_on_repeat=restarts)
    relay.command(0.0, True)
    relay.command(300.0, True)
    relay.advance(600.0)
    assert relay.on is restarts
    relay.advance(900.0)
    assert not relay.on
    assert relay.own_changes == 1


def test_another_controller_switching_the_relay_is_a_change_of_its_own() -> None:
    relay = RelayModel()
    relay.command(0.0, False)
    relay.switch(10.0, True)
    assert relay.on
    assert relay.own_changes == 1
    relay.wifi_loss(20.0, 60.0)
    relay.switch(30.0, False)  # out of reach: nothing switches it from Home Assistant's side
    assert relay.own_changes == 1


def test_a_boiler_fault_stops_it_until_it_clears() -> None:
    """The boiler's own fault (boiler protection's input): it does not fire while one holds;
    an unknown fault is refused."""
    s = sim(outdoor=-5.0)
    s.plant.water = 20.0
    s.set_fault("boiler_lockout", True)
    s.advance(START + 300.0)
    assert not s.last.flame
    s.set_fault("boiler_lockout", False)
    s.advance(START + 310.0)
    assert s.last.flame
    with pytest.raises(ValueError, match="unknown fault"):
        s.set_fault("overheating", True)


def test_the_relay_is_the_on_off_boilers_heat_demand() -> None:
    """The relay's contact on the room-thermostat terminals: closed, the boiler heats by its own
    curve; open, no heat — the valves only bound where the heat goes."""
    s = sim(relay=RelaySetup(), outdoor=-5.0)
    s.plant.water = 20.0
    s.advance(START + 60.0)
    assert not s.last.demand
    s.relay_command(START + 60.0, True)
    s.advance(START + 120.0)
    assert s.last.demand
    assert s.last.flame
    assert s.last.setpoint == boiler_setpoint(s.plant.boiler, -5.0)
    with pytest.raises(ValueError, match="no relay"):
        sim().relay_command(START, True)


# --- X6; rule 9: the wall thermostat ---------------------------------------------------------


def test_the_wall_thermostat_keeps_its_program_and_its_own_setting() -> None:
    """21 °C from 06:00 to 22:00, 17 °C otherwise; a setting changed by hand holds until the
    next program switch."""
    assert (DAY_SETPOINT, NIGHT_SETPOINT) == (21.0, 17.0)
    assert program(START) == 21.0
    assert program(START - 60.0) == 17.0
    assert program(START + 16 * 3600.0) == 17.0  # 22:00
    wall = WallThermostat(WallKind.OPENTHERM)
    wall.set_manual(START + 3600.0, 19.0)
    assert wall.setpoint(START + 2 * 3600.0) == 19.0
    assert wall.setpoint(START + 16 * 3600.0) == 17.0  # the program switched: the hand-set goes
    assert wall.setpoint(START + 2 * 3600.0) == 21.0


@pytest.mark.parametrize("kind", [WallKind.OPENTHERM, WallKind.ON_OFF])
def test_the_wall_thermostat_has_no_effect_under_an_override_and_takes_over_after(
    kind: WallKind,
) -> None:
    """While ``CS`` is overridden nothing the thermostat sends reaches the boiler's heating;
    released, it takes over at the next step: an OpenTherm thermostat with its own water
    setpoint and room setpoint, an on/off contact as a demand at the boiler's maximum."""
    s = sim(wall_thermostat=kind, outdoor=0.0)
    s.plant.room[0] = 25.0  # warm: the thermostat does not call
    s.gateway_setpoint(START, 55.0)
    s.advance(START + 10.0)
    assert s.last.demand
    assert s.last.setpoint == 55.0
    s.gateway_setpoint(START + 20.0, 0.0)
    s.advance(START + 30.0)
    assert not s.last.demand  # the thermostat's own: no call
    s.plant.room[0] = 18.0
    s.advance(START + 40.0)
    assert s.last.demand  # it calls: at once
    if kind is WallKind.OPENTHERM:
        assert s.last.setpoint == boiler_setpoint(s.plant.boiler, 0.0)
        assert s.wall_setpoint() == 21.0
        assert s.wall_room() == pytest.approx(18.0, abs=0.1)
        assert s.gateway_read_back() == s.last.setpoint
    else:
        assert s.last.setpoint == s.plant.boiler.max_setpoint
        assert s.wall_setpoint() is None  # a contact sends no room setpoint
        assert s.wall_room() is None
    s.plant.room[0] = 25.0
    s.advance(START + 50.0)
    if kind is WallKind.OPENTHERM:
        assert s.gateway_read_back() == IDLE_WATER


# --- the clock ---------------------------------------------------------------------------------


def test_a_far_jump_of_the_clock_is_not_stepped_through_in_full() -> None:
    """A frozen test clock released at a test's end jumps months: only the last six hours are
    simulated, so the end of a test does not take seconds of stepping."""
    s = sim()
    began = time.monotonic()
    s.advance(START + 263 * 86400.0)
    assert time.monotonic() - began < 5.0
    assert s.t == START + 263 * 86400.0
    assert MAX_CATCH_UP_S == 6 * 3600.0


# --- decision 6's classes, reachable for J4 (P-114) ---------------------------------------------


def test_decision_6s_classes_can_be_produced() -> None:
    """A clipped setpoint (the boiler's own limit), a single fall-back with no trace, and a held
    device that restarts — out of reach, then back with what it was given lost."""
    s = sim(write_type=WriteType.HELD, outdoor=0.0)
    s.clip = 45.0
    s.gateway_setpoint(START, 60.0)
    s.advance(START)
    assert s.gateway_read_back() == 45.0  # the same lower value whatever is sent
    s.entity_setpoint(START, 55.0)
    assert s.plant.override_setpoint == 45.0
    s.clip = None
    s.gateway_setpoint(START + 10.0, 50.0)
    s.drop_override()
    s.advance(START + 20.0)
    assert s.gateway_read_back() == boiler_setpoint(s.plant.boiler, 0.0)  # fell back, untraced
    s.entity_setpoint(START + 30.0, 48.0)
    s.entity_heating(START + 30.0, False)
    s.restart_device(START + 40.0)
    assert not s.device_reachable()
    s.entity_setpoint(START + 45.0, 49.0)  # cannot reach it
    assert not s.plant.override_active(START + 45.0)
    assert s.plant.heating_allowed(START + 45.0) is None  # its "off" lost too
    s.advance(START + 50.0)
    assert s.device_reachable()
    assert s.device_restarts == 1
