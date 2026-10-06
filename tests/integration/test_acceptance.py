"""Acceptance scenarios (docs/plan-0.2.md, J4), in-process against the simulator component.

The plugin controls the simulated boiler through the same paths as in the test Home Assistant:
the OpenTherm Gateway — the test-only stub ``opentherm_gw`` on the simulator, set up through its
config flow and read back from its boiler device's "Control setpoint 1" (P-37) — the writable
setpoint entity, or a relay on an on/off boiler. VT's zones are stood in for by climate states
mirrored from the simulated rooms and their thermostatic valves, and a zone VT has off closes its
valve in the simulator too (S-05); the test HA runs real VT instead. Nothing connects anywhere.
"""

from __future__ import annotations

import math
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest
from custom_components.boiler_sim import SimHub
from custom_components.boiler_sim.plant import PlantOutput
from custom_components.boiler_sim.simulation import ZoneMode
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import CoreState, Event, HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.control_config import MIGRATED_HARD_MIN

from .harness import VT_PLATFORM, FakeZones, ServiceSpy, analyse_now

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

START = datetime(2026, 1, 12, 6, tzinfo=UTC)
SIM = "boiler_sim"
SIGNALS = {
    "flame": "binary_sensor.boiler_sim_flame",
    "flow": "sensor.boiler_sim_flow",
    "return": "sensor.boiler_sim_return",
    "modulation": "sensor.boiler_sim_modulation",
    "ch_setpoint": "sensor.boiler_sim_ch_setpoint",
    "dhw_active": "binary_sensor.boiler_sim_dhw_active",
    "pressure": "sensor.boiler_sim_pressure",
    "outdoor": "sensor.boiler_sim_outdoor",
    "ch_active": "binary_sensor.boiler_sim_ch_active",
    "pump_running": "binary_sensor.boiler_sim_pump_running",
}
# The gateway's read-back as opentherm_gw shows it: the stub's boiler device (P-37).
CONFIRMED = "sensor.otgw_sim_boiler_control_setpoint"
CH_ENABLED = "binary_sensor.otgw_sim_boiler_master_ch_enabled"
FITTING_KIND = {"gateway_with_thermostat": "opentherm", "gateway_standalone": "none"}
# The lowest water temperature: a test's entry is stored as minor version 1, so the entry
# migration keeps 0.2.1's 25 °C in its control section (X6).
LOWEST = MIGRATED_HARD_MIN
GATEWAY_CONTROL = {
    "write_path": "opentherm_gw",
    "gateway_id": "sim",
    "confirmed_entity": CONFIRMED,
    "topology": "gateway_with_thermostat",
    "curve": {"design_outdoor": -15, "design_flow": 55},
}


@dataclass
class Rig:
    hass: HomeAssistant
    freezer: Any
    zones: FakeZones
    storage: dict[str, Any] = field(default_factory=dict)
    hub: SimHub | None = None
    entry: MockConfigEntry | None = None
    vt_mode: str = "heat"  # the HVAC mode VT gives its thermostats (VT's own modes act on it)
    over_climate: set[str] = field(default_factory=set)  # zones of VT's over_climate type
    modes: dict[str, str] = field(default_factory=dict)  # a zone's own mode, over ``vt_mode``
    # VT's ``is_ready`` on every thermostat; false: VT cannot start them; ``None``: its
    # placeholder, neither ``is_ready`` nor ``specific_states`` (no device has reported).
    vt_ready: bool | None = True
    fahrenheit: bool = False  # Home Assistant in US customary units: VT reports in °F
    spy: ServiceSpy | None = None  # every service call (P-118)
    smartpi: dict[str, bool] = field(default_factory=dict)  # SmartPI zones: learning on or off

    @property
    def sim(self):
        assert self.hub is not None
        return self.hub.sim

    def now(self) -> float:
        return datetime.now(UTC).timestamp()

    def degrees(self, celsius: float) -> float:
        """A temperature as VT reports it, in Home Assistant's unit."""
        return round(celsius * 9.0 / 5.0 + 32.0, 1) if self.fahrenheit else round(celsius, 1)

    def mirror_zones(self) -> None:
        """VT's thermostats as the plugin reads them, from the simulated rooms. A zone VT has
        "off" shows its valve closed and its device off, as VT 10.4.0 does (decision 4) — and its
        valve is closed in the simulated plant too (S-05); in "sleep" it shows "off" with its
        valve held at 100 %, open in the plant."""
        for zone in self.sim.zones:
            mode = self.modes.get(zone.zone_id, self.vt_mode)
            plant_mode = {"off": ZoneMode.OFF, "sleep": ZoneMode.SLEEP}.get(mode, ZoneMode.HEAT)
            self.sim.set_zone_mode(zone.zone_id, plant_mode)
            opening = self.sim.opening(zone.zone_id)
            index = [z.zone_id for z in self.sim.zones].index(zone.zone_id)
            entity_id = self.zones.entities[zone.zone_id]
            mode = self.modes.get(zone.zone_id, self.vt_mode)
            if mode == "unavailable":
                self.hass.states.async_set(entity_id, "unavailable", {})
                continue
            active = opening > 0.05
            action = "heating" if active else "idle"
            if mode in ("off", "sleep"):
                opening = 1.0 if mode == "sleep" else 0.0
                mode, active, action = "off", False, "off"
            if zone.zone_id in self.over_climate:
                # It drives a device with its own regulation: no opening, only whether it heats
                # — and, as VT 10.4.0 shows every started thermostat, that it has started.
                shown: dict[str, Any] = {
                    "current_temperature": self.degrees(self.sim.room(zone.zone_id)),
                    "temperature": self.degrees(self.sim.plant.targets[index]),
                    "hvac_action": action,
                }
                if self.vt_ready is not None:
                    shown |= {
                        "is_ready": self.vt_ready,
                        "specific_states": {"is_device_active": active},
                    }
                self.hass.states.async_set(entity_id, mode, shown)
                continue
            # What real VT publishes for every thermostat, and what demand follows first (T4):
            # whether its device heats now, and that it has started; a SmartPI zone, its flag.
            specific: dict[str, Any] = {"is_device_active": active}
            extra: dict[str, Any] = {}
            if zone.zone_id in self.smartpi:
                specific["smartpi_learning_enabled"] = self.smartpi[zone.zone_id]
                extra["configuration"] = {"proportional_function": "smartpi"}
            self.zones.set(
                zone.zone_id,
                mode,
                current_temperature=self.degrees(self.sim.room(zone.zone_id)),
                temperature=self.degrees(self.sim.plant.targets[index]),
                hvac_action=action,
                valve_open_percent=round(opening * 100),
                on_percent=0.0 if mode == "off" else round(opening, 2),
                specific_states=specific if self.vt_ready is not None else None,
                is_ready=self.vt_ready,
                **extra,
            )

    async def advance(self, seconds: float, step: float = 10.0) -> None:
        elapsed = 0.0
        while elapsed < seconds:
            self.freezer.tick(step)
            elapsed += step
            async_fire_time_changed(self.hass)
            await self.hass.async_block_till_done()
            self.mirror_zones()

    def entity(self, domain: str, key: str) -> str:
        assert self.entry is not None
        found = er.async_get(self.hass).async_get_entity_id(
            domain, DOMAIN, f"{self.entry.entry_id}_{key}"
        )
        assert found is not None, key
        return found

    def state(self, domain: str, key: str) -> State:
        state = self.hass.states.get(self.entity(domain, key))
        assert state is not None
        return state

    async def switch(self, on: bool) -> None:
        """The user's switch, as the test's own call: tagged, not taken for the plugin's."""
        assert self.spy is not None
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": self.entity("switch", "control")},
            blocking=True,
            context=self.spy.own,
        )
        await self.hass.async_block_till_done()

    async def scenario(self, service: str, **data: Any) -> None:
        """One of the simulator's scenario services, as the test's own call."""
        assert self.spy is not None
        await self.hass.services.async_call(SIM, service, data, blocking=True, context=self.spy.own)

    def gateway(self, kind: str | None = None) -> list[tuple[float, str, object]]:
        return [c for c in self.sim.commands.gateway if kind is None or c[1] == kind]

    def setpoints(self) -> list[float]:
        return [float(value) for _t, _kind, value in self.gateway("setpoint")]  # type: ignore[arg-type]

    def plugin_services(self) -> set[tuple[str, str]]:
        """The services the plugin called — a switch's or the simulator's included (P-118); the
        test's own calls are left out by their tag, not by their domain."""
        assert self.spy is not None
        return self.spy.plugin_services()


async def start(
    rig: Rig,
    sim: dict[str, Any] | None = None,
    stored: dict[str, Any] | None = None,
    monitor: dict[str, Any] | None = None,
    entry_options: dict[str, Any] | None = None,
    emitter: str | None = None,
    with_control: bool = True,
    **control: Any,
) -> None:
    """The simulator, VT's zones and the plugin; ``stored``: what an earlier run left in the
    entry store (0.2.1's layout). Without it, the entry ran before and its control store owes
    nothing: an entry with control and no stores at all would hand back first (V1).
    ``entry_options``: sections of the entry's options to replace (circuits, signals, the
    boiler); ``emitter``: every zone's; ``with_control``: no control section at all."""
    hass = rig.hass
    assert await async_setup_component(hass, SIM, {SIM: {"outdoor": -2.0} | (sim or {})})
    await hass.async_block_till_done()
    rig.hub = hass.data[SIM]
    for zone in rig.sim.zones:
        rig.zones.add(zone.zone_id)
    rig.mirror_zones()
    control_options = GATEWAY_CONTROL | control
    # What is wired to the gateway's thermostat terminals (decision 1): the answer that fits the
    # topology, unless the test gives its own.
    kind = FITTING_KIND.get(control_options.get("topology", ""))
    if kind is not None and "thermostat_kind" not in control_options:
        control_options["thermostat_kind"] = kind
    zone = {} if emitter is None else {"emitter": emitter}
    options = {
        "signals": SIGNALS,
        "weather": "weather.boiler_sim_weather",
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "parameters": {"boiler_min_power": 2.5, "boiler_max_power": 15.0},
        "zones": [{"entity_id": e} | zone for e in rig.zones.entities.values()],
        "monitor": {"monitoring_days": 0} | (monitor or {}),
        "control": control_options,
    } | (entry_options or {})
    if not with_control:
        del options["control"]
    # The simulated gateway, set up as a user sets up a gateway: through the config flow of the
    # OpenTherm Gateway integration — here the test-only stub on the simulator (P-37, X5.5).
    await setup_gateway(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    if stored is not None:
        key = f"{DOMAIN}.{entry.entry_id}"
        version = stored.pop("__version__", 1)  # another version: a store this one cannot read
        rig.storage[key] = {"version": version, "key": key, "data": stored}
    else:
        key = f"{DOMAIN}.{entry.entry_id}.control"
        rig.storage[key] = {"version": 1, "key": key, "data": {}}
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    rig.entry = entry


async def setup_gateway(hass: HomeAssistant) -> str:
    """The stub gateway's config flow, as in the test Home Assistant's user interface."""
    result = await hass.config_entries.flow.async_init(
        "opentherm_gw", context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    await hass.async_block_till_done()
    return str(result["result"].entry_id)


@pytest.fixture
async def rig(
    hass: HomeAssistant,
    freezer,
    zones: FakeZones,
    hass_storage: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[Rig]:
    freezer.move_to(START)
    rig = Rig(hass, freezer, zones, hass_storage, spy=ServiceSpy(hass))
    assert rig.spy is not None
    rig.spy.install(monkeypatch)
    yield rig
    # Control handed back first, while the simulated gateway is set up: the test harness unloads
    # every entry at once at its end, and a hand-back racing the gateway's own unload would find
    # no gateway. Switching off waits for no read-back, which the frozen clock would never bring.
    if rig.entry is None or rig.entry.state is not ConfigEntryState.LOADED:
        return
    if hass.state is not CoreState.running:
        return
    unique_id = f"{rig.entry.entry_id}_control"
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, unique_id)
    state = hass.states.get(switch) if switch is not None else None
    if state is not None and state.state == "on":
        await rig.switch(False)


# --- closed loop --------------------------------------------------------------------------


async def test_a_cold_day_under_control(rig: Rig) -> None:
    """Six hours at −2 °C: rooms held, limits kept, keep-alive never lapses, the DHW-enable bit
    never touched, only allowed services called."""
    await start(rig)
    await rig.advance(1800, step=30.0)  # the boiler on its own curve first
    await rig.switch(True)
    await rig.advance(6 * 3600, step=30.0)

    setpoints = rig.gateway("setpoint")
    assert setpoints
    values = [float(v) for _t, _k, v in setpoints]  # type: ignore[arg-type]
    assert all(LOWEST <= v <= 70.0 for v in values)
    gaps = [b[0] - a[0] for a, b in pairwise(setpoints)]
    assert max(gaps) <= 45.0  # the gateway's one-minute limit is never reached
    for zone in rig.sim.zones:
        index = [z.zone_id for z in rig.sim.zones].index(zone.zone_id)
        assert abs(rig.sim.room(zone.zone_id) - rig.sim.plant.targets[index]) < 1.5, zone
    assert rig.sim.commands.dhw_enable_writes == 0
    unit = rig.entry.runtime_data.control
    assert rig.plugin_services() <= unit.allowed_services | {("weather", "get_forecasts")}
    assert rig.state("sensor", "control_state").state in ("heating", "idle")

    await rig.switch(False)
    assert rig.setpoints()[-1] == 0.0
    assert not rig.sim.plant.override_active(rig.now())  # handed back at once


def burns_seen(changes: list[tuple[float, bool]], until: float) -> list[tuple[float, float, bool]]:
    """The flame's burns as its entity reported them — ``(start, end, start seen)``, the last
    one cut at ``until`` — worked out apart from the plugin (P-121)."""
    burns: list[tuple[float, float, bool]] = []
    started: float | None = None
    seen = False
    for index, (t, on) in enumerate(changes):
        if t >= until:
            break
        if on and started is None:
            started, seen = t, index > 0  # a flame on at the first report: its start not seen
        elif not on and started is not None:
            burns.append((started, t, seen))
            started = None
    if started is not None:
        burns.append((started, until, seen))
    return burns


@pytest.mark.parametrize(
    ("outdoor", "cycles"), [(-2.0, False), (12.0, True)], ids=["cold_day", "mild_day"]
)
async def test_the_monitor_works_on_the_simulated_boiler(
    rig: Rig, outdoor: float, cycles: bool
) -> None:
    """T10, P-121: the monitor's numbers are the simulated boiler's own. Three hours of the
    boiler on its own curve — on a cold day one burn from the start, whose start nobody saw; on
    a mild day it cycles. The burns, taken apart from the plugin from every report of the
    flame's entity, give the starts, the starts per hour of heating (per clock hour that holds a
    burn) and the burner hours the monitor shows — exactly, not merely "a number"."""
    from homeassistant.const import EVENT_STATE_CHANGED

    changes: list[tuple[float, bool]] = []

    def flame(event: Event) -> None:
        state = event.data["new_state"]
        if event.data["entity_id"] != SIGNALS["flame"] or state is None:
            return
        if state.state in ("on", "off") and (
            not changes or changes[-1][1] != (state.state == "on")
        ):
            changes.append((state.last_updated.timestamp(), state.state == "on"))

    rig.hass.bus.async_listen(EVENT_STATE_CHANGED, flame)
    await start(rig, sim={"outdoor": outdoor})
    await rig.advance(3 * 3600, step=30.0)
    assert rig.state("binary_sensor", "connection").state == "on"
    assert rig.entry is not None
    # The clock's own analysis runs in the background: one to its end, published, so the
    # analysis read here and the sensors come from the same run.
    await analyse_now(rig.entry.runtime_data)
    analysis = rig.entry.runtime_data.analysis
    assert analysis is not None
    burns = burns_seen(changes, analysis.at)
    starts = sum(1 for _start, _end, seen in burns if seen)
    assert (starts >= 3) is cycles  # cold: the one burn from the start, its start not seen
    assert burns  # it burned
    hours = {
        h
        for start_t, end_t, _ in burns
        for h in range(int(start_t // 3600), math.ceil(end_t / 3600))
    }
    active = sum(min((h + 1) * 3600.0, analysis.at) - h * 3600.0 for h in hours)
    shown = rig.state("sensor", "starts_per_hour")
    assert shown.attributes["starts"] == starts
    assert float(shown.state) == round(starts / (active / 3600.0), 2)
    burned = sum(end_t - start_t for start_t, end_t, _ in burns)
    assert float(rig.state("sensor", "burner_hours").state) == round(burned / 3600.0, 2)
    assert rig.gateway() == []  # control is off: nothing written


# --- hand-back on every exit ----------------------------------------------------------------


@pytest.mark.parametrize("exit_path", ["switch_off", "unload", "reload", "stop"])
async def test_hand_back_on_every_exit(rig: Rig, exit_path: str) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.sim.plant.override_active(rig.now())
    hass = rig.hass
    assert rig.entry is not None
    if exit_path == "switch_off":
        await rig.switch(False)
    elif exit_path == "unload":
        assert await hass.config_entries.async_unload(rig.entry.entry_id)
    elif exit_path == "reload":
        assert await hass.config_entries.async_reload(rig.entry.entry_id)
    else:
        await hass.async_stop()  # the hand-back runs as a shutdown job, before the stop event
        assert ("setpoint", 0.0) in [(k, v) for _t, k, v in rig.gateway()][-3:]
        assert not rig.sim.plant.override_active(rig.now())
        return
    await hass.async_block_till_done()
    assert ("setpoint", 0.0) in [(k, v) for _t, k, v in rig.gateway()][-3:]
    if exit_path == "reload":
        await rig.advance(20)
        assert rig.sim.plant.override_active(rig.now())  # control resumed as it was
    else:
        assert not rig.sim.plant.override_active(rig.now())
        count = len(rig.gateway())
        await rig.advance(120)
        assert len(rig.gateway()) == count  # no loop left running


async def test_a_thermostat_heats_again_after_a_hand_back_that_followed_off(rig: Rig) -> None:
    """The gateway keeps a CH=0 through CS=0 (PIC 6.6): a hand-back that sent only CS=0 after
    control had switched heating off would leave the thermostat calling and the boiler cold."""
    await start(rig)
    await rig.switch(True)
    plant = rig.sim.plant
    plant.room = [target + 2.0 for target in plant.targets]  # every room warm: no demand
    rig.mirror_zones()
    await rig.advance(360)
    assert rig.gateway("ch")[-1][2] is False  # control switched heating off
    await rig.switch(False)
    plant.room = [target - 3.0 for target in plant.targets]  # the rooms cool: the thermostat calls
    rig.mirror_zones()
    await rig.advance(30)
    assert not plant.override_active(rig.now())
    assert rig.sim.last.demand  # the thermostat's call reaches the boiler


async def test_heating_follows_the_zones_at_once_both_ways(rig: Rig) -> None:
    """VT decides whether to heat: heating goes off within a step of the rooms being satisfied
    and on within a step of a call, with no hold of any kind."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    plant = rig.sim.plant

    def rooms(offset: float) -> None:
        plant.room = [target + offset for target in plant.targets]
        rig.sim.advance(rig.now())  # the valves follow the rooms at once
        rig.mirror_zones()

    rooms(2.0)
    await rig.advance(10)
    assert rig.gateway("ch")[-1][2] is False
    rooms(-2.0)
    await rig.advance(10)
    assert rig.gateway("ch")[-1][2] is True


async def test_keep_alive_loss_lets_the_gateway_fall_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.advance(90)
    assert not rig.sim.plant.override_active(rig.now())  # lapsed: the thermostat has it back
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"


async def test_hard_limits_hold_in_hard_frost(rig: Rig) -> None:
    # Below the design outdoor temperature the curve asks for more than its design flow, which
    # the hard maximum cuts (a design flow above the maximum itself is refused, P-68).
    await start(rig, hard_max=48, curve={"design_outdoor": -15, "design_flow": 48})
    await rig.scenario("set_outdoor", temperature=-25)
    await rig.switch(True)
    await rig.advance(1800, step=30.0)
    assert max(rig.setpoints()) <= 48.0
    assert "limit_hard_max" in rig.state("sensor", "control_state").attributes["reasons"]


async def test_stale_data_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    await rig.scenario("fail_signal", signal="flow")
    count = len(rig.gateway())
    await rig.advance(240)
    assert len(rig.gateway()) == count  # nothing written without fresh data
    await rig.advance(90)
    assert rig.setpoints()[-1] == 0.0
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_a_failed_outdoor_sensor_falls_back_to_the_weather(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.scenario("fail_signal", signal="outdoor")
    await rig.advance(400)
    reasons = rig.state("sensor", "control_state").attributes["reasons"]
    assert "outdoor_weather" in reasons
    assert rig.sim.plant.override_active(rig.now())  # heating goes on


async def test_a_command_never_taken_is_detected_and_not_fought(rig: Rig) -> None:
    """S-48, decision 6 (replaces "another controller" here): the boiler keeps its own steady
    value from the start and never takes ours — ignored from the start once three counted sends
    (the first five minutes after the unit's start carry its trace and do not count) went
    unanswered: reported, not sent again this session, never another controller; control stays
    on and nothing is handed back."""
    await start(rig)
    await rig.scenario("ignore_writes", enabled=True)
    await rig.switch(True)
    await rig.advance(700)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    assert rig.state("sensor", "control_state").state != "handed_back"
    assert 0.0 not in rig.setpoints()  # nothing handed back
    count = len(rig.setpoints())
    await rig.advance(300)
    assert len(rig.setpoints()) == count  # not sent again this session


async def test_vt_stopped_means_no_demand_not_a_hand_back(rig: Rig) -> None:
    """VT's central mode "Stopped" turns its zones off: the plugin sees no demand — heating off,
    no hand-back, control goes on — and frost protection still watches: a room left to freeze
    behind a valve VT keeps closed gets no frost heat, which could not reach it, but a repair
    issue naming it (decision 4)."""
    from homeassistant.helpers import issue_registry as ir

    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    hass.states.async_set(select.entity_id, "Stopped")
    rig.vt_mode = "off"  # VT applies it to the thermostats that follow the central mode
    rig.mirror_zones()
    await rig.advance(10)
    assert rig.gateway("ch")[-1][2] is False
    assert 0.0 not in rig.setpoints()  # not handed back
    assert rig.sim.plant.override_active(rig.now())
    rig.sim.plant.room[0] = 4.0  # a room left to freeze
    rig.sim.advance(rig.now())
    rig.mirror_zones()
    await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "idle"
    assert rig.gateway("ch")[-1][2] is False  # the boiler is not run against closed valves
    # S-05: the valve VT keeps closed is closed in the simulated plant too — its cold room
    # would open a thermostatic head — so no heat could have reached it.
    assert rig.sim.opening(rig.sim.zones[0].zone_id) == 0.0
    assert 0.0 not in rig.setpoints()
    assert rig.entry is not None
    found = ir.async_get(hass).async_get_issue(DOMAIN, f"frost_zone_closed_{rig.entry.entry_id}")
    assert found is not None
    assert (
        rig.zones.entities[rig.sim.zones[0].zone_id].split(".")[1].replace("_", " ")
        in (found.translation_placeholders["zones"])
    )


async def test_vt_stopped_leaves_a_zone_outside_the_central_mode_heating(rig: Rig) -> None:
    """VT applies "Stopped" only to the thermostats that follow the central mode: one that does
    not keeps asking for heat, and the plugin heats for it."""
    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    hass.states.async_set(select.entity_id, "Stopped")
    rig.vt_mode = "off"
    rig.modes[rig.sim.zones[0].zone_id] = "heat"  # not controlled by the central mode
    plant = rig.sim.plant
    plant.room[0] = plant.targets[0] - 2.0
    rig.sim.advance(rig.now())
    rig.mirror_zones()
    await rig.advance(20)
    assert rig.gateway("ch")[-1][2] is True
    assert "demand" in rig.state("sensor", "control_state").attributes["reasons"]
    assert 0.0 not in rig.setpoints()


async def test_frost_protection_heats_while_vt_is_off(rig: Rig) -> None:
    """Summer and winter come from VT: with its zones off nothing heats, but a room close to
    freezing whose valve VT holds open — VT's SLEEP shows "off" with the valve at 100 % — still
    gets heat (decision 4)."""
    await start(rig)
    await rig.scenario("set_outdoor", temperature=24)
    rig.vt_mode = "sleep"
    await rig.switch(True)
    await rig.advance(600)
    assert rig.state("sensor", "control_state").state == "idle"
    assert rig.gateway("ch")[-1][2] is False
    rig.sim.plant.room[0] = 4.0
    rig.sim.advance(rig.now())
    rig.mirror_zones()
    await rig.advance(20)
    assert rig.state("sensor", "control_state").state == "frost"
    assert rig.gateway("ch")[-1][2] is True


@pytest.mark.parametrize(
    ("changes", "blocker"),
    [
        ({"confirmed_entity": ""}, "blocked_no_confirmed_setpoint"),
        ({"topology": "monitor_mode"}, "blocked_topology_no_control"),
    ],
)
async def test_control_is_refused_where_it_may_not_run(
    rig: Rig, changes: dict, blocker: str
) -> None:
    await start(rig, **changes)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == blocker
    await rig.advance(60)
    assert rig.gateway() == []


async def test_control_is_refused_without_a_hand_back(rig: Rig) -> None:
    await start(
        rig,
        sim={"write_type": "held"},
        write_path="entity",
        setpoint_entity="number.boiler_sim_flow_setpoint",
        write_type="held",
        ch_entity="switch.boiler_sim_ch_enable",
        ch_write_type="held",
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_no_hand_back"


async def test_standalone_hand_back_stops_heating(rig: Rig) -> None:
    await start(rig, sim={"topology": "standalone"}, topology="gateway_standalone")
    assert rig.state("switch", "control").attributes["hand_back_effect"] == "heating_stops"
    await rig.switch(True)
    await rig.advance(120)
    assert rig.sim.last.demand
    await rig.switch(False)
    await rig.advance(10)
    assert not rig.sim.last.demand  # as the switch said: no heat until control resumes


async def test_an_outside_change_is_rewritten_once_then_alarmed(rig: Rig) -> None:
    """Another controller holds its value after the one rewrite: the plugin steps aside with the
    whole safe hand-back — the lowest water temperature, CH=1, CS=0 — and never fights it."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    await rig.scenario("force_setpoint", value=62)
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert [(kind, value) for _t, kind, value in rig.gateway()[-3:]] == [
        ("setpoint", LOWEST),
        ("ch", True),
        ("setpoint", 0.0),
    ]
    count = len(rig.setpoints())
    await rig.advance(120)
    assert len(rig.setpoints()) == count  # no fight


@pytest.mark.parametrize("write_type", ["persistent", "unknown"])
async def test_nothing_is_written_to_the_boilers_persistent_memory(
    rig: Rig, write_type: str
) -> None:
    """A setpoint the boiler stores, or might, keeps control off: never a single write."""
    await start(
        rig,
        sim={"write_type": "persistent"},
        write_path="entity",
        setpoint_entity="number.boiler_sim_flow_setpoint",
        write_type=write_type,
        hand_back="value",
        hand_back_value=0,
        hand_back_value_effect="own_control",
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_write_type_not_supported"
    await rig.advance(600)
    assert entity_setpoints(rig) == []


def entity_setpoints(rig: Rig) -> list[float]:
    return [float(v) for _t, kind, v in rig.sim.commands.entity if kind == "setpoint"]  # type: ignore[arg-type]


# --- hand-back kept and retried; a restart without a clean stop -----------------------------


async def test_a_hand_back_is_kept_and_retried_until_the_gateway_takes_it(rig: Rig) -> None:
    """A hand-back whose target is away is shown as failed, kept and sent again every minute;
    once it goes through, the alarm clears and nothing more is sent."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    hass = rig.hass
    away = hass.services.async_services()["opentherm_gw"]
    for name in away:
        hass.services.async_remove("opentherm_gw", name)
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    for name, service in away.items():
        hass.services.async_register("opentherm_gw", name, service.job.target, service.schema)
    await rig.advance(70)
    assert [(k, v) for _t, k, v in rig.gateway()][-2:] == [("ch", True), ("setpoint", 0.0)]
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    count = len(rig.gateway())
    await rig.advance(180)
    assert len(rig.gateway()) == count  # given back: nothing more is sent


# What a run of 0.2.2 stores at once when it first commands the boiler (V3): a gateway's release
# is judged against it after a crash (V4, R7). 55 °C is well away from the simulated boiler's own
# curve at −2 °C (47 °C), which the simulator's read-back shows once the override is gone.
LAST_COMMAND = {"heating": True, "setpoint": 55.0, "at": START.timestamp() - 600.0}
# The safe hand-back on a gateway: the lowest water temperature, CH=1, then CS=0 (V5).
SAFE_HAND_BACK = [("setpoint", LOWEST), ("ch", True), ("setpoint", 0.0)]


async def test_a_restart_without_a_clean_stop_hands_back_first(rig: Rig) -> None:
    """The last run held the boiler and never gave it back (a crash, a power cut): the first
    step gives it back in full, and control stays off until the user switches it on."""
    await start(rig, stored={"control": {"controlling": True, "last_command": LAST_COMMAND}})
    await rig.advance(30)
    assert [(k, v) for _t, k, v in rig.gateway()][:3] == SAFE_HAND_BACK
    assert rig.state("switch", "control").state == "off"
    count = len(rig.gateway())
    await rig.advance(180)
    assert len(rig.gateway()) == count


async def test_a_store_that_cannot_be_read_hands_back_first(
    rig: Rig, caplog: pytest.LogCaptureFixture
) -> None:
    """Stored data this version cannot read (from a newer one, say) may hide a boiler still
    held: it is given back in full first, as after a crash."""
    await start(rig, stored={"__version__": 99, "control": {"controlling": False}})
    await rig.advance(30)
    assert "Could not read the stored data" in caplog.text
    assert [(k, v) for _t, k, v in rig.gateway()][:3] == SAFE_HAND_BACK
    assert rig.state("switch", "control").state == "off"


async def test_a_stored_latch_and_an_owed_hand_back_both_hold(rig: Rig) -> None:
    """The last run was latched by an alarm and still owed the hand-back: it is made in full
    first, and the latch keeps control off until the user switches it off and on."""
    await start(
        rig,
        stored={
            "control": {
                "controlling": True,
                "latched": True,
                "latched_by": ["outside_change"],
                "hand_back_pending": True,
                "last_command": LAST_COMMAND,
            }
        },
    )
    await rig.advance(30)
    assert [(k, v) for _t, k, v in rig.gateway()][:3] == SAFE_HAND_BACK
    count = len(rig.gateway())
    await rig.switch(True)
    await rig.advance(120)
    assert len(rig.gateway()) == count  # latched: nothing written
    control_state = rig.state("sensor", "control_state")
    assert control_state.state == "handed_back"
    assert control_state.attributes["latched_by"] == ["outside_change"]
    await rig.switch(False)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.sim.plant.override_active(rig.now())  # the user's off and on cleared it


async def test_reloads_leave_exactly_one_control_loop(rig: Rig) -> None:
    """A reload that left an old loop running would drive the boiler from two loops at once (a
    VT user's report): after three reloads the gateway gets what one loop sends."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(600)
    before = len(rig.gateway())
    await rig.advance(300)
    one_loop = len(rig.gateway()) - before
    assert rig.entry is not None
    for _ in range(3):
        assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
        await rig.hass.async_block_till_done()
        await rig.advance(20)
    await rig.advance(300)  # the ramp after a reload settles
    after = len(rig.gateway())
    await rig.advance(300)
    assert one_loop > 0
    assert len(rig.gateway()) - after <= one_loop + 2
    assert rig.sim.plant.override_active(rig.now())  # control resumed


# --- VT's zones as VT has them ------------------------------------------------------------


@pytest.mark.parametrize(
    ("topology", "handed_back"),
    [("gateway_with_thermostat", True), ("gateway_standalone", False)],
)
async def test_zones_that_cannot_be_read_end_in_decision_3s_end_state(
    rig: Rig, topology: str, handed_back: bool
) -> None:
    """Every VT zone unavailable at once (VT reloading, then gone): the recognition period keeps
    the command held for ten minutes; then nothing can ask for heat — with the thermostat on the
    gateway, the boiler is handed back to it; stand-alone, the usual "off" — never heating on
    the curve with no zone known. The alarm and the repair issue come at once; control resumes
    by itself when the zones answer again."""
    from homeassistant.helpers import issue_registry as ir

    await start(rig, topology=topology)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.gateway("ch")[-1][2] is True
    rig.vt_mode = "unavailable"
    rig.mirror_zones()
    await rig.advance(540, step=30.0)
    attributes = rig.state("sensor", "control_state").attributes
    assert attributes["reasons"] == ["zones_recognition"]  # the command held meanwhile
    assert len(attributes["unknown_zones"]) == len(rig.sim.zones)
    assert rig.gateway("ch")[-1][2] is True
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    await rig.advance(90, step=30.0)
    state = rig.state("sensor", "control_state")
    assert "zones_unknown" in state.attributes["reasons"]
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "on"
    assert rig.entry is not None
    issue = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"no_zone_known_{rig.entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == (
        "no_zone_known_handed_back" if handed_back else "no_zone_known_off"
    )
    if handed_back:
        assert state.state == "handed_back"
        assert rig.setpoints()[-1] == 0.0  # the thermostat has the boiler
    else:
        assert state.state == "idle"
        assert rig.gateway("ch")[-1][2] is False  # heating off, no hand-back
        assert rig.setpoints()[-1] > 0.0
    rig.vt_mode = "heat"
    rig.mirror_zones()
    await rig.advance(30, step=10.0)
    assert rig.state("sensor", "control_state").state in ("heating", "idle")
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"
    assert (
        ir.async_get(rig.hass).async_get_issue(DOMAIN, f"no_zone_known_{rig.entry.entry_id}")
        is None
    )


@pytest.mark.parametrize("shown", [False, None], ids=["not_ready", "placeholder"])
@pytest.mark.parametrize("when", ["restart", "reload"])
@pytest.mark.parametrize(
    ("topology", "handed_back"),
    [("gateway_with_thermostat", True), ("gateway_standalone", False)],
)
async def test_zones_vt_cannot_start_end_in_decision_3s_end_state(
    rig: Rig, topology: str, handed_back: bool, when: str, shown: bool | None
) -> None:
    """SB-02 (decision 1 of 2026-10-05): VT cannot start any thermostat — the Zigbee or Z-Wave
    integration down after a restart, or after VT's reload — and shows each "off" with
    ``is_ready`` false for as long as it cannot, or, no device ever reporting, its placeholder
    with neither ``is_ready`` nor ``specific_states`` (check C's F1). That is not the user's
    "off": once the
    recognition period is over every zone is unknown — with the thermostat on the gateway the
    boiler is handed back to it; stand-alone, heating off — with the alarm and the repair issue,
    never "no demand"; control resumes once VT starts them."""
    from homeassistant.helpers import issue_registry as ir

    if when == "restart":
        rig.vt_mode, rig.vt_ready = "off", shown
    await start(rig, topology=topology)
    await rig.switch(True)
    if when == "reload":
        await rig.advance(60)
        assert rig.gateway("ch")[-1][2] is True
        rig.vt_mode, rig.vt_ready = "off", shown
        rig.mirror_zones()
    reasons: set[str] = set()
    for _ in range(22):  # 11 minutes: the recognition period and a little more
        await rig.advance(30, step=30.0)
        reasons |= set(rig.state("sensor", "control_state").attributes["reasons"])
    state = rig.state("sensor", "control_state")
    assert "no_demand" not in reasons
    assert "zones_unknown" in state.attributes["reasons"]
    assert len(state.attributes["unknown_zones"]) == len(rig.sim.zones)
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "on"
    assert rig.entry is not None
    issue = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"no_zone_known_{rig.entry.entry_id}")
    assert issue is not None
    assert issue.translation_key == (
        "no_zone_known_handed_back" if handed_back else "no_zone_known_off"
    )
    if handed_back:
        assert state.state == "handed_back"
        assert not rig.gateway("ch") or rig.gateway("ch")[-1][2] is not False  # no CH=0
    else:
        assert state.state == "idle"
        assert rig.gateway("ch")[-1][2] is False  # heating off, no hand-back
    rig.vt_mode, rig.vt_ready = "heat", True
    rig.mirror_zones()
    await rig.advance(30, step=10.0)
    assert rig.state("sensor", "control_state").state in ("heating", "idle")
    assert rig.state("binary_sensor", "alarm_no_zone_known").state == "off"


@pytest.mark.parametrize("kind", ["auto", "over_climate"])
async def test_zones_in_auto_or_of_the_over_climate_type_decide_as_well(
    rig: Rig, kind: str
) -> None:
    """A thermostat in "auto", or one that drives a device with its own regulation (no opening
    published), still asks for heat, and stops asking."""
    await start(rig)
    if kind == "auto":
        rig.vt_mode = "auto"
    else:
        rig.over_climate = {zone.zone_id for zone in rig.sim.zones}
    plant = rig.sim.plant

    def rooms(offset: float) -> None:
        plant.room = [target + offset for target in plant.targets]
        rig.sim.advance(rig.now())
        rig.mirror_zones()

    rooms(-2.0)
    await rig.switch(True)
    await rig.advance(20)
    assert rig.gateway("ch")[-1][2] is True
    assert "demand" in rig.state("sensor", "control_state").attributes["reasons"]
    rooms(2.0)
    await rig.advance(20)
    assert rig.gateway("ch")[-1][2] is False


# --- bounded learning, alarms, a short-cycling boiler, no outdoor reading ------------------


async def test_the_comfort_correction_stays_within_3_k(rig: Rig) -> None:
    """A room that cannot reach its setpoint with its valve fully open raises the water, by
    3 K at most, and the user is told once it has sat at that edge — switched on: off by
    default since the user's decision of 2026-10-03 (K4.1)."""
    await start(rig, comfort_correction=True)
    await rig.switch(True)
    await rig.advance(900, step=30.0)
    attributes = rig.state("sensor", "control_state").attributes
    assert "comfort_correction" not in attributes["reasons"]
    base = attributes["target"]
    rig.sim.plant.targets[0] = 30.0  # out of reach: its valve stays fully open
    targets = []
    # Six hours: the first reads the weather (rule 5 judges its rate by an hour of readings).
    for _ in range(72):
        await rig.advance(300, step=30.0)
        targets.append(rig.state("sensor", "control_state").attributes["target"])
    assert max(targets) > base + 1.0  # the correction worked
    assert max(targets) <= base + 3.0 + 0.1  # and stayed within its band
    assert max(rig.setpoints()) <= base + 3.0 + 0.1
    assert rig.state("binary_sensor", "alarm_correction_at_limit").state == "on"


async def test_low_pressure_informs_and_never_hands_back(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Y1 (decision 7): the water pressure falling below the "add water" threshold — as with a
    leak — raises its alarm and the notification after five minutes, and control keeps the
    boiler: a reaction stored earlier for it is neutralised, and heating stops only while the
    boiler itself reports a fault that stops it (boiler protection)."""
    from homeassistant.helpers import issue_registry as ir

    await start(
        rig, monitor={"add_water_below": 0.8}, alarm_reactions={"pressure_low": "hand_back"}
    )
    await rig.switch(True)
    await rig.advance(60)
    assert rig.sim.plant.override_active(rig.now())
    monkeypatch.setattr(PlantOutput, "pressure", property(lambda _output: 0.4))
    await rig.advance(360)
    assert rig.state("binary_sensor", "alarm_pressure_low").state == "on"
    control_state = rig.state("sensor", "control_state")
    assert control_state.state != "handed_back"
    assert "alarm_hand_back" not in control_state.attributes["reasons"]
    assert rig.sim.plant.override_active(rig.now())
    entry = rig.hass.config_entries.async_entries(DOMAIN)[0]
    issue = ir.async_get(rig.hass).async_get_issue(DOMAIN, f"add_water_{entry.entry_id}")
    assert issue is not None
    assert issue.translation_placeholders == {"value": "0.40", "threshold": "0.8"}


async def test_a_short_cycling_boiler_is_never_held_off(rig: Rig) -> None:
    """An oversized boiler in mild weather starts often on its own; heating still follows VT's
    zones and is never switched off while a zone calls."""
    await start(rig, sim={"boiler": "short_cycling", "outdoor": 10.0})
    await rig.switch(True)
    seen: list[tuple[float, bool]] = []  # when the zones were mirrored, and whether one called
    starts, flame = 0, rig.sim.last.flame
    for _ in range(360):  # an hour
        await rig.advance(10)
        seen.append((rig.now(), any(rig.sim.opening(z.zone_id) > 0.05 for z in rig.sim.zones)))
        starts += rig.sim.last.flame and not flame
        flame = rig.sim.last.flame
    assert starts >= 6, "the boiler must cycle for this scenario to mean anything"
    assert any(calling for _at, calling in seen)
    assert rig.gateway("ch")
    for written_at, _kind, on in rig.gateway("ch"):
        before = [calling for at, calling in seen if at < written_at]
        if on is False and before:
            assert not before[-1], written_at  # off only when no zone called


async def test_without_any_outdoor_reading_the_fallback_setpoint_heats(rig: Rig) -> None:
    """The boiler's outdoor sensor and the weather entity both gone: the last value stands in
    for three hours, then the fallback setpoint — never zero heat."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    for signal in ("outdoor", "weather"):
        await rig.scenario("fail_signal", signal=signal)
    await rig.advance(900, step=30.0)
    assert "outdoor_held" in rig.state("sensor", "control_state").attributes["reasons"]
    await rig.advance(3 * 3600, step=60.0)
    assert "outdoor_unknown" in rig.state("sensor", "control_state").attributes["reasons"]
    assert rig.setpoints()[-1] >= LOWEST
    assert rig.gateway("ch")[-1][2] is True
    assert rig.sim.plant.override_active(rig.now())


# --- Home Assistant in US customary units -------------------------------------------------

ENTITY_CONTROL = {
    "write_path": "entity",
    "setpoint_entity": "number.boiler_sim_flow_setpoint",
    "write_type": "held",
    # Decision 11: control needs a heating switch the boiler does not store (the simulated
    # device keeps its state).
    "ch_entity": "switch.boiler_sim_ch_enable",
    "ch_write_type": "held",
    "hand_back": "value",
    "hand_back_value": 0,
    "hand_back_value_effect": "own_control",
    "topology": "virtual",
}


@pytest.mark.parametrize("write_path", ["opentherm_gw", "entity"])
async def test_a_home_assistant_in_fahrenheit(rig: Rig, write_path: str) -> None:
    """Home Assistant in US customary units: the sensors, VT's zones, the weather and the
    setpoint entity are all in °F; the boiler still gets what the plugin means in °C, the
    rooms are not taken for freezing, the read-back confirms, and the hand-back arrives."""
    rig.hass.config.units = US_CUSTOMARY_SYSTEM
    rig.fahrenheit = True
    entity = write_path == "entity"
    await start(
        rig, sim={"write_type": "held"} if entity else None, **(ENTITY_CONTROL if entity else {})
    )
    assert rig.hass.states.get(SIGNALS["flow"]).attributes["unit_of_measurement"] == "°F"
    await rig.switch(True)
    await rig.advance(1800, step=30.0)
    values = entity_setpoints(rig) if entity else rig.setpoints()
    assert values
    assert all(LOWEST <= v <= 70.0 for v in values), values  # °C at the boiler
    assert rig.state("sensor", "control_state").state in ("heating", "idle")
    for alarm in ("alarm_write_ignored", "alarm_outside_change", "alarm_write_failed"):
        assert rig.state("binary_sensor", alarm).state == "off", alarm
    assert rig.sim.plant.override_active(rig.now())
    await rig.switch(False)
    assert not rig.sim.plant.override_active(rig.now())


async def test_an_entity_hand_back_waits_for_its_target_and_is_stored(rig: Rig) -> None:
    """The setpoint entity goes unavailable while control holds the boiler: the hand-back is
    shown as failed, stored for a restart and sent again; once the entity is back, it arrives.

    The simulated device is declared held, and its hand-back value hands the boiler to its own
    curve, which the read-back — the boiler's control setpoint — then shows. A held target is
    released only at its hand-back value (V5), so that steady other value counts as another
    controller's at the second retry check: done, with no retry, and a repair issue (a question
    for K4: an own-control value on a held device read back from the boiler)."""
    await start(rig, sim={"write_type": "held"}, **ENTITY_CONTROL)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.sim.plant.override_active(rig.now())
    rig.sim.failed.add("flow_setpoint")
    rig.hub.refresh()
    await rig.hass.async_block_till_done()
    assert rig.hass.states.get(ENTITY_CONTROL["setpoint_entity"]).state == "unavailable"
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    await rig.advance(600)  # past the delayed save
    key = f"{DOMAIN}.{rig.entry.entry_id}"
    assert rig.storage[key]["data"]["control"]["hand_back_pending"] is True
    assert 0.0 not in entity_setpoints(rig)
    rig.sim.failed.discard("flow_setpoint")
    rig.hub.refresh()
    await rig.advance(70)
    assert entity_setpoints(rig)[-2:] == [LOWEST, 0.0]  # the lowest, then the hand-back value
    assert not rig.sim.plant.override_active(rig.now())  # the boiler is on its own curve
    count = len(entity_setpoints(rig))
    await rig.advance(130)
    assert len(entity_setpoints(rig)) == count  # judged, not sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    confirmation = rig.state("sensor", "control_state").attributes["hand_back_confirmation"]
    assert confirmation == "taken_by_other"
    assert not rig.storage[key]["data"]["control"]["hand_back_pending"]


async def test_a_held_device_that_restarts_gets_its_values_again(rig: Rig) -> None:
    """S-13 (T-47), reachable at J4 (P-114): control through a held device — an ESPHome-like
    master — which restarts: out of reach for 20 s, back with what it was given lost. Its
    setpoint and heating switch are sent again once it is back — a lost command, with the trace
    of its outage — with no outside change and no hand-back."""
    await start(rig, sim={"write_type": "held"}, **ENTITY_CONTROL)
    await rig.switch(True)
    await rig.advance(120)
    assert rig.sim.plant.override_active(rig.now())
    setpoints = len(entity_setpoints(rig))
    switches = len([1 for _t, kind, _v in rig.sim.commands.entity if kind == "ch"])
    await rig.scenario("restart_device", seconds=20)
    assert not rig.sim.plant.override_active(rig.now())
    await rig.advance(60)
    assert len(entity_setpoints(rig)) > setpoints  # sent again
    assert len([1 for _t, kind, _v in rig.sim.commands.entity if kind == "ch"]) > switches
    assert rig.sim.plant.override_active(rig.now())
    for alarm_kind in ("alarm_outside_change", "alarm_write_ignored"):
        assert rig.state("binary_sensor", alarm_kind).state == "off", alarm_kind
    assert rig.state("sensor", "control_state").state != "handed_back"


async def test_a_switch_hand_back_gives_the_boiler_its_own_control(rig: Rig) -> None:
    """The entity path with a switch that enables external control: taking control turns it
    on, the hand-back turns it off — confirmed by its state — and the boiler is on its own."""
    external = "switch.boiler_sim_external_control"
    control = {k: v for k, v in ENTITY_CONTROL.items() if not k.startswith("hand_back")}
    await start(
        rig,
        sim={"write_type": "held"},
        **control,
        hand_back="switch",
        hand_back_entity=external,
        hand_back_entity_write_type="held",  # the simulated device keeps it (P-40)
    )
    await rig.switch(True)
    await rig.advance(60)
    assert rig.hass.states.get(external).state == "on"
    assert rig.sim.plant.override_active(rig.now())
    await rig.switch(False)
    await rig.advance(20)
    assert rig.hass.states.get(external).state == "off"
    assert not rig.sim.plant.override_active(rig.now())
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    await rig.switch(True)
    await rig.advance(30)
    assert rig.hass.states.get(external).state == "on"
    assert rig.sim.plant.override_active(rig.now())


async def test_a_timeout_hand_back_lets_the_override_lapse(rig: Rig) -> None:
    """An expiring setpoint entity handed back by its own timeout: control simply stops
    writing, and within the device's timeout the boiler is on its own."""
    control = {k: v for k, v in ENTITY_CONTROL.items() if not k.startswith("hand_back")}
    await start(rig, **control | {"write_type": "expiring"}, hand_back="timeout")
    await rig.switch(True)
    await rig.advance(120)
    assert rig.sim.plant.override_active(rig.now())
    count = len(entity_setpoints(rig))
    assert count >= 3  # kept alive
    await rig.switch(False)
    await rig.advance(90)  # past the simulated device's one-minute timeout
    # The lowest water temperature, then nothing: the device's own timeout releases it.
    assert entity_setpoints(rig)[count:] == [LOWEST]
    assert not rig.sim.plant.override_active(rig.now())


# --- Z3: the J4 route, hot water, the thermostat kind, the circuit maximum, the read-back -------

ROOM_SETPOINT = "sensor.otgw_sim_thermostat_room_setpoint"


async def options_step(rig: Rig, result: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return await rig.hass.config_entries.options.async_configure(result["flow_id"], data)


async def test_options_flow_configures_control_on_the_simulator(rig: Rig) -> None:
    """T-23 (P-37): the plugin past its monitoring and no control yet; the simulated gateway set
    up through the stub's config flow, as at J4 — options → Control → OpenTherm Gateway →
    gateway ID ``sim``: the flow completes; the plugin then controls the simulated boiler
    through it, its setpoint confirmed by the gateway's read-back and its heating switch by the
    boiler's "Central heating 1"."""
    await start(rig, with_control=False)
    assert rig.entry is not None
    hass = rig.hass
    menu = await hass.config_entries.options.async_init(rig.entry.entry_id)
    assert "control" in menu["menu_options"]
    result = await options_step(rig, menu, {"next_step_id": "control"})
    result = await options_step(
        rig,
        result,
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
            "confirmed_entity": CONFIRMED,
            "ch_confirmed_entity": CH_ENABLED,
        },
    )
    assert result["step_id"] == "control_gateway"
    offered = next(v for m, v in result["data_schema"].schema.items() if str(m) == "gateway_id")
    assert offered.config["options"] == ["sim"]
    result = await options_step(rig, result, {"gateway_id": "sim"})
    assert result["step_id"] == "control_curve"
    curve = {"design_outdoor": -15, "design_flow": 55, "hard_min": 25, "hard_max": 70}
    result = await options_step(rig, result, curve)
    if result.get("step_id") == "control_alarms":
        result = await options_step(rig, result, {})
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    control = rig.entry.options["control"]
    assert (control["write_path"], control["gateway_id"]) == ("opentherm_gw", "sim")
    await rig.switch(True)
    await rig.advance(600, step=30.0)
    assert rig.setpoints()
    assert rig.sim.plant.override_active(rig.now())
    for alarm in ("alarm_write_ignored", "alarm_outside_change", "alarm_write_failed"):
        assert rig.state("binary_sensor", alarm).state == "off", alarm
    control_state = rig.state("sensor", "control_state")
    assert control_state.state in ("heating", "idle")
    assert control_state.attributes["latched_by"] == []


async def test_a_dhw_draw_under_control_raises_no_outside_change(rig: Rig) -> None:
    """T-21 (P-36, P-22): control through the simulated gateway, its heating switch read back
    from the boiler's "Central heating 1" (CH enable, not "running"), a SmartPI zone learning. A
    ten-minute hot-water draw: the boiler leaves heating for the tank — no outside change, no
    ignored write, no latch, the DHW-enable bit never written; SmartPI's learning paused for the
    draw and resumed after it; heating back once the draw ends."""
    hass = rig.hass
    calls: list[tuple[str, bool]] = []

    async def set_learning(call: Any) -> None:
        calls.append((call.data["entity_id"], call.data["learning_enabled"]))
        zone = next(z for z, e in rig.zones.entities.items() if e == call.data["entity_id"])
        rig.smartpi[zone] = call.data["learning_enabled"]

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    learner = "zone_bath"
    rig.smartpi[learner] = True
    await start(rig, ch_confirmed_entity=CH_ENABLED)
    rig.sim.plant.targets[2] = 24.0  # the bath calls, its valve open
    await rig.switch(True)
    await rig.advance(900, step=30.0)
    entity = rig.zones.entities[learner]
    assert calls == []
    await rig.scenario("start_dhw", minutes=10)
    await rig.advance(60)
    assert rig.sim.last.dhw
    assert calls == [(entity, False)]
    assert entity in rig.state("sensor", "control_state").attributes["learning_paused"]
    await rig.advance(540)
    assert not rig.sim.last.dhw  # the draw is over
    await rig.advance(1800, step=30.0)
    assert calls[-1] == (entity, True)  # resumed
    assert rig.smartpi[learner] is True
    assert rig.sim.last.flame  # heating back
    for alarm in ("alarm_outside_change", "alarm_write_ignored"):
        assert rig.state("binary_sensor", alarm).state == "off", alarm
    control_state = rig.state("sensor", "control_state")
    assert control_state.attributes["latched_by"] == []
    assert control_state.state == "heating"
    assert rig.sim.commands.dhw_enable_writes == 0
    assert rig.plugin_services() <= rig.entry.runtime_data.control.allowed_services | {
        ("weather", "get_forecasts")
    }


@pytest.mark.parametrize("kind", ["on_off", "unknown"])
async def test_otgw_on_off_thermostat_heats_after_an_unclean_exit_while_off(
    rig: Rig, kind: str
) -> None:
    """T-07 (S-01, decision 1): an on/off contact on the gateway's thermostat terminals, or
    "I don't know". Control is refused (the blocker), nothing is written, and the contact heats
    the house — the gateway turns it into a demand at the boiler's maximum. Why: with the
    session the blocker prevents, left "off" (``CH=0``) when Home Assistant vanished without a
    hand-back, the override lapses and the thermostat closes its contact — and the boiler gets
    no CH enable: the PIC keeps ``CH=0`` and masks the contact, until ``CH=1`` or a gateway
    reset."""
    await start(rig, sim={"wall_thermostat": "on_off"}, thermostat_kind=kind)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    blocker = {"on_off": "thermostat_on_off", "unknown": "thermostat_kind_dont_know"}[kind]
    assert err.value.translation_key == f"blocked_{blocker}"
    plant = rig.sim.plant
    plant.room[0] = 18.0  # the contact's room is cold: it closes
    await rig.advance(60)
    assert rig.gateway() == []
    assert rig.sim.wall is not None
    assert rig.sim.wall.calling
    assert rig.sim.last.demand
    assert rig.sim.last.setpoint == plant.boiler.max_setpoint
    # What the blocker prevents: a session's last commands, "off", then nothing more.
    hass = rig.hass
    for service, data in (
        ("set_control_setpoint", {"temperature": 55.0}),
        ("set_central_heating_ovrd", {"ch_override": False}),
    ):
        await hass.services.async_call(
            "opentherm_gw", service, {"gateway_id": "sim"} | data, blocking=True
        )
    await rig.advance(120)
    assert not plant.override_active(rig.now())  # CS lapsed
    assert rig.sim.wall.calling  # the contact asks for heat...
    assert not rig.sim.last.demand  # ...and is masked: the house cools
    await rig.advance(1800, step=60.0)
    assert not rig.sim.last.demand
    await hass.services.async_call(
        "opentherm_gw",
        "set_central_heating_ovrd",
        {"gateway_id": "sim", "ch_override": True},
        blocking=True,
    )
    assert rig.sim.last.demand  # CH=1: the contact heats again


@pytest.mark.parametrize("outdoor", [5.0, -5.0])
@pytest.mark.parametrize("layout", ["underfloor", "shared_loop"])
async def test_underfloor_flow_stays_within_the_circuit_maximum(
    rig: Rig, layout: str, outdoor: float
) -> None:
    """T-20 (S-14, decision 10): underfloor heating on an unmixed loop — alone, or sharing it
    with radiators — the circuit's maximum 40 °C below what the curve asks in frost, six hours
    of control at +5 °C and at −5 °C: the maximum limits every setpoint, and says so where it
    holds one back; the boiler's own regulation lets the measured flow overshoot only by its stop
    hysteresis — 5 K, the documented margin — so the circuit's too-hot alarm, pre-filled at
    45 °C for 10 minutes, stays off, and judged."""
    circuit = {"id": "main", "control": "unmixed_shared", "max_flow": 40}
    emitters = dict.fromkeys(("zone_ground", "zone_upstairs", "zone_living"), "underfloor")
    await start(
        rig,
        sim={"zones": layout, "outdoor": outdoor},
        entry_options={"circuits": [circuit]},
    )
    assert rig.entry is not None
    zones = [
        {"entity_id": rig.zones.entities[z.zone_id], "emitter": emitters.get(z.zone_id, "radiator")}
        for z in rig.sim.zones
    ]
    options = dict(rig.entry.options) | {"zones": zones}
    rig.hass.config_entries.async_update_entry(rig.entry, options=options)
    await rig.hass.async_block_till_done()
    await rig.switch(True)
    flows: list[float] = []
    capped = False
    for _ in range(72):  # six hours
        await rig.advance(300, step=30.0)
        flows.append(float(rig.hass.states.get(SIGNALS["flow"]).state))
        reasons = rig.state("sensor", "control_state").attributes["reasons"]
        capped = capped or "limit_circuit_max" in reasons
    assert rig.setpoints()
    assert max(rig.setpoints()) <= 40.0
    # At −5 °C the curve asks for about 46 °C: the maximum holds it back, and says so.
    assert capped is (outdoor < 0)
    assert max(flows) <= 40.0 + 5.0
    alarm = rig.state("binary_sensor", "alarm_circuit_too_hot")
    assert alarm.state == "off"
    assert alarm.attributes["limit"] == 45.0
    assert alarm.attributes.get("reason") is None  # judged on the measured flow


async def test_gateway_read_back_confirms_then_drops_on_a_refused_id1(rig: Rig) -> None:
    """Open after R6 #2 (decision 6, answer E): a boiler that refuses ID 1 — the gateway drops
    the control setpoint at the next exchange without a message, so ``opentherm_gw`` shows it
    confirmed, then dropped, after every send from the session's start. The plugin takes it as
    ignored from the start: reported, not sent again this session, never another controller —
    no latch, no hand-back."""
    await start(rig)
    await rig.scenario("refuse_id1", enabled=True)
    await rig.switch(True)
    seen: list[float] = []
    for _ in range(90):  # fifteen minutes
        await rig.advance(10)
        state = rig.hass.states.get(CONFIRMED)
        assert state is not None
        seen.append(float(state.state))
    sent = set(rig.setpoints())
    assert sent & set(seen)  # each send shown confirmed...
    assert not rig.sim.plant.override_active(rig.now())  # ...and dropped
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    control_state = rig.state("sensor", "control_state")
    assert control_state.state != "handed_back"
    assert control_state.attributes["latched_by"] == []
    assert 0.0 not in rig.setpoints()
    count = len(rig.setpoints())
    await rig.advance(600, step=30.0)
    assert len(rig.setpoints()) == count  # not sent again this session


async def test_wall_thermostat_takes_over_after_hand_back_with_its_own_program(rig: Rig) -> None:
    """X6, rule 9: an OpenTherm wall thermostat on the gateway, its program 21 °C from 06:00
    to 22:00 and 17 °C otherwise. While the plugin controls it has no effect on heating, and the
    control switch shows what it would keep after a hand-back — its room setpoint from the
    gateway's thermostat device. Handed back, it takes over within a minute: the boiler follows
    its own call and water setpoint; at 22:00 its program lowers the room. With its setpoint
    unknown, the switch says so."""
    signals = SIGNALS | {"room_setpoint": ROOM_SETPOINT}
    await start(rig, sim={"wall_thermostat": "opentherm"}, entry_options={"signals": signals})
    plant = rig.sim.plant
    await rig.switch(True)
    await rig.advance(600, step=30.0)
    switch = rig.state("switch", "control")
    assert switch.attributes["wall_thermostat_setpoint"] == 21.0
    assert switch.attributes["wall_thermostat_warning"] is None
    plant.room[0] = 25.0  # its room warm: it does not call, yet control heats the others
    rig.mirror_zones()
    await rig.advance(30)
    assert rig.sim.wall is not None
    assert not rig.sim.wall.calling
    assert plant.override_active(rig.now())
    await rig.switch(False)
    await rig.advance(60)
    assert not plant.override_active(rig.now())
    assert not rig.sim.last.demand  # the thermostat has the boiler: it does not call
    plant.room[0] = 19.0
    await rig.advance(60)
    assert rig.sim.wall.calling
    assert rig.sim.last.demand  # within a minute of its call
    assert float(rig.hass.states.get(CONFIRMED).state) == rig.sim.last.setpoint
    # Past 22:00 (the run began at 06:00 UTC): 17 °C from then on.
    await rig.advance(START.timestamp() + 16 * 3600 + 300 - rig.now(), step=120.0)
    plant.room[0] = 19.0
    await rig.advance(60, step=30.0)
    assert float(rig.hass.states.get(ROOM_SETPOINT).state) == 17.0
    assert not rig.sim.wall.calling  # 19 °C is warm enough at night
    await rig.scenario("fail_signal", signal="thermostat_setpoint")
    await rig.advance(30)
    switch = rig.state("switch", "control")
    assert switch.attributes["wall_thermostat_setpoint"] is None
    assert switch.attributes["wall_thermostat_warning"] == "unknown"


# --- Z3, X8: an on/off boiler switched by the simulator's relay (answers C, D, G, L, N) ---------

RELAY = "switch.boiler_sim_relay"
RELAY_SIGNALS = {key: SIGNALS[key] for key in ("flame", "flow", "return", "pressure", "outdoor")}
# The relay path's answers: a relay that reports its state, starts off after a power cut and has
# no timer — the separate-contact tick given (answer G).
RELAY_CONTROL = {
    "write_path": "relay",
    "relay_entity": RELAY,
    "relay_is_separate_contact": True,
    "relay_reports_state": "yes",
    "relay_power_on_state": "off",
    "relay_off_timer": "none",
}
START_TRACE_S = 310.0  # past the five minutes a unit's start counts as a trace of an outage


async def start_relay(
    rig: Rig,
    relay: dict[str, Any] | None = None,
    signals: dict[str, str] = RELAY_SIGNALS,
    lockout_s: float | None = None,
    **control: Any,
) -> None:
    """The simulator with an on/off boiler whose room-thermostat terminals a relay closes (the
    relay's own settings: ``relay``), and the plugin controlling it through that relay."""
    sim: dict[str, Any] = {"relay": {"start_up": "off"} | (relay or {})}
    if lockout_s is not None:
        sim["restart_lockout_s"] = lockout_s
    await start(
        rig,
        sim=sim,
        entry_options={
            "signals": signals,
            "boiler": {"class": "on_off", "dhw": "combi"},
            "control": RELAY_CONTROL | control,
        },
    )


def relay_model(rig: Rig) -> Any:
    relay = rig.sim.relay
    assert relay is not None
    return relay


def relay_commands(rig: Rig) -> list[bool]:
    """What the relay was told through Home Assistant — by the plugin: the test switches it only
    through the simulator's scenario services."""
    return [on for _t, on in relay_model(rig).commands]


def rooms_call(rig: Rig, call: bool) -> None:
    """Every room below its target (its valve open: the zones call) or above it."""
    plant = rig.sim.plant
    plant.room = [target + (-2.0 if call else 2.0) for target in plant.targets]
    rig.sim.advance(rig.now())
    rig.mirror_zones()


def alarm(rig: Rig, kind: str) -> str:
    return rig.state("binary_sensor", f"alarm_{kind}").state


def repair(rig: Rig, key: str) -> Any:
    from homeassistant.helpers import issue_registry as ir

    assert rig.entry is not None
    return ir.async_get(rig.hass).async_get_issue(DOMAIN, f"{key}_{rig.entry.entry_id}")


async def relay_on_under_control(rig: Rig) -> None:
    rooms_call(rig, True)
    await rig.switch(True)
    await rig.advance(30)
    assert relay_model(rig).on
    await rig.advance(START_TRACE_S)


async def test_relay_restart_is_resent(rig: Rig) -> None:
    """Answer C: the relay restarts — seen unavailable for 10 s, back in its state after a power
    cut, off — and gets the command again at once, counted; the third within a day raises
    "commands lost", information only, never another controller. Missing data: its state
    unknown for 5 minutes raises "relay out of reach", with no hand-back."""
    await start_relay(rig)
    await relay_on_under_control(rig)
    for n in (1, 2, 3):
        await rig.advance(130)  # past the last send's confirmation window
        await rig.scenario("relay_restart")
        assert rig.hass.states.get(RELAY).state == "unavailable"
        await rig.advance(30)
        assert relay_commands(rig)[-1] is True, n
        assert relay_model(rig).on, n
        assert alarm(rig, "commands_lost") == ("on" if n == 3 else "off"), n
    assert alarm(rig, "outside_change") == "off"
    assert rig.state("sensor", "control_state").state == "heating"
    count = len(relay_commands(rig))
    await rig.scenario("fail_signal", signal="relay")
    assert rig.hass.states.get(RELAY).state == "unknown"
    await rig.advance(280)
    assert alarm(rig, "relay_unreachable") == "off"
    await rig.advance(30)
    assert alarm(rig, "relay_unreachable") == "on"
    assert relay_commands(rig)[count:] == []  # no rest state: nothing handed back
    assert rig.state("sensor", "control_state").state == "heating"


async def test_relay_restart_without_unavailability_is_resent(rig: Rig) -> None:
    """Answer D: a relay that reports no availability restarts unseen — found in the state the
    user declared for after a power cut, off, while commanded on, never unavailable: the command
    goes again, counted; the third within a day raises the information warning."""
    await start_relay(rig)
    await relay_on_under_control(rig)
    for n in (1, 2, 3):
        await rig.advance(130)
        await rig.scenario("relay_restart", reported=False)
        assert rig.hass.states.get(RELAY).state == "off"  # at once, never unavailable
        await rig.advance(10)
        assert relay_commands(rig)[-1] is True, n
        assert relay_model(rig).on, n
        assert alarm(rig, "commands_lost") == ("on" if n == 3 else "off"), n
    assert alarm(rig, "outside_change") == "off"
    assert rig.state("sensor", "control_state").state == "heating"


@pytest.mark.parametrize(
    ("start_up", "declared"), [("off", "off"), ("last", "unknown")], ids=["declared_off", "last"]
)
async def test_relay_fourth_unreported_restart_in_a_day_steps_aside(
    rig: Rig, start_up: str, declared: str
) -> None:
    """Answer N: found in its declared state after a power cut with no trace — or, the state
    declared "I don't know" (its model: the last one), switched by its own button while
    available — answered three times within a day; the fourth counts as another controller: the
    plugin steps aside at once, with no rewrite first, the rest state set once (the relay reads
    off already: nothing written), the latch kept with its repair issue, the relay left alone."""
    await start_relay(rig, relay={"start_up": start_up}, relay_power_on_state=declared)
    await relay_on_under_control(rig)

    async def event() -> None:
        if declared == "off":
            await rig.scenario("relay_restart", reported=False)
        else:
            await rig.scenario("relay_switch", on=False)

    for n in (1, 2, 3):
        await event()
        await rig.advance(10)
        assert relay_commands(rig)[-1] is True, n
        assert relay_model(rig).on, n
        await rig.advance(600)
    count = len(relay_commands(rig))
    await event()
    await rig.advance(20)
    assert relay_commands(rig)[count:] == []  # no rewrite; the rest state read already
    control_state = rig.state("sensor", "control_state")
    assert control_state.state == "handed_back"
    assert repair(rig, "control_latched") is not None
    await rig.scenario("relay_switch", on=True)
    await rig.advance(600)
    assert relay_commands(rig)[count:] == []  # left alone


async def test_relay_switched_while_available_is_rewritten_once_then_stepped_aside(
    rig: Rig,
) -> None:
    """Answers C, H and L: commanded off, the relay is switched on by an automation while it
    stays available — written back once; the second time within a day the plugin steps aside:
    the rest state, off, written once over the automation's value, then nothing more, even when
    the automation switches the relay again; latched, with its repair issue."""
    await start_relay(rig)
    rooms_call(rig, False)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    assert relay_commands(rig) == []  # it reads "off" already: nothing to write
    await rig.scenario("relay_switch", on=True)
    await rig.advance(10)
    assert relay_commands(rig) == [False]  # rewritten once
    assert not relay_model(rig).on
    await rig.advance(130)
    await rig.scenario("relay_switch", on=True)
    await rig.advance(20)
    assert relay_commands(rig) == [False, False]  # the rest state, once
    assert not relay_model(rig).on
    await rig.scenario("relay_switch", on=True)  # the automation again
    await rig.advance(600)
    assert relay_commands(rig) == [False, False]  # left alone
    assert relay_model(rig).on
    assert rig.state("sensor", "control_state").state == "handed_back"
    found = repair(rig, "control_latched")
    assert found is not None
    assert found.translation_key == "control_latched_relay_off"


async def test_relay_wifi_loss_raises_alarm_after_5_min_and_resends(rig: Rig) -> None:
    """R6: the relay loses its Wi-Fi for eight minutes, its contact as it was; meanwhile the
    rooms stop calling. Nothing is written while it is out of reach, nor handed back; after five
    minutes the alarm and its repair issue; back, it still reads on — the command, off, goes at
    once, and the alarm clears."""
    await start_relay(rig)
    await relay_on_under_control(rig)
    count = len(relay_commands(rig))
    await rig.scenario("relay_wifi_loss", minutes=8)
    rooms_call(rig, False)
    await rig.advance(280)
    assert alarm(rig, "relay_unreachable") == "off"
    await rig.advance(30)
    assert alarm(rig, "relay_unreachable") == "on"
    assert repair(rig, "relay_unreachable") is not None
    assert relay_commands(rig)[count:] == []  # nothing could reach it, no hand-back tried
    assert relay_model(rig).on  # its contact as it was: the boiler may heat meanwhile
    await rig.advance(160)
    assert rig.hass.states.get(RELAY).state == "unavailable"  # 7 min 50 s
    await rig.advance(20)
    assert relay_commands(rig)[count:] == [False]  # back, still on: the command at once
    assert not relay_model(rig).on
    assert alarm(rig, "relay_unreachable") == "off"
    assert repair(rig, "relay_unreachable") is None


@pytest.mark.parametrize("restarts", [True, False], ids=["tasmota_like", "not_restarted"])
async def test_relay_off_timer_lapses_without_repeats(rig: Rig, restarts: bool) -> None:
    """R3, R7 row 5: the relay's own 10-minute switch-off timer, declared, renewed by "on" at
    half its length. Where an "on" restarts it (Tasmota's PulseTime) it never lapses under
    control; where it does not (a Shelly's auto-off: not documented, Q3.10) it lapses 10 minutes
    after the on-period began, renewals or not — the plugin takes that as the relay's own lapse:
    "on" again at once, never counted as a lost command, never another controller."""
    await start_relay(
        rig,
        relay={"off_timer_min": 10, "timer_restarts_on_repeat": restarts},
        relay_off_timer="minutes",
        relay_off_timer_min=10,
    )
    await relay_on_under_control(rig)
    lapsed = relay_model(rig).own_changes  # the relay's own switch-offs: its timer here
    await rig.advance(3600)
    lapses = relay_model(rig).own_changes - lapsed
    assert relay_commands(rig).count(False) == 0
    assert relay_commands(rig).count(True) >= 10  # renewed every five minutes
    if restarts:
        assert lapses == 0
    else:
        assert lapses >= 5
        assert relay_model(rig).on  # each lapse answered at once
    assert alarm(rig, "commands_lost") == "off"
    assert alarm(rig, "outside_change") == "off"
    assert rig.state("sensor", "control_state").state == "heating"
    assert repair(rig, "relay_timer_seen") is None  # declared: nothing to ask (Z4R-02)


async def test_an_undeclared_relay_timer_is_recognised_and_heating_goes_on(rig: Rig) -> None:
    """Z4R-02: the timer left at "I don't know"; the relay's own 30-minute timer, which a
    repeated "on" does not restart (a Shelly's auto-off, say), switches it off 30 min into every
    on-period while the rooms call for hours. The first switch-off counts as a possible restart;
    the second, at the same time into its on-period, shows the relay's own timer: answered at
    once and no longer counted, and a warning repair issue asks to declare it, naming about 30
    minutes. After two and a half hours control still heats — before, the fourth switch-off
    stepped aside to the rest state "off" after two hours."""
    from homeassistant.helpers import issue_registry as ir

    await start_relay(
        rig,
        relay={"off_timer_min": 30, "timer_restarts_on_repeat": False},
        relay_off_timer="unknown",
    )
    await relay_on_under_control(rig)
    lapsed = relay_model(rig).own_changes
    for _ in range(9):
        await rig.advance(1000)
        assert rig.state("sensor", "control_state").state == "heating"
    assert relay_model(rig).own_changes - lapsed >= 4  # its timer, again and again
    assert relay_model(rig).on  # each answered at once
    assert alarm(rig, "outside_change") == "off"
    found = repair(rig, "relay_timer_seen")
    assert found is not None
    assert found.severity is ir.IssueSeverity.WARNING
    assert found.translation_placeholders["minutes"] == "30"


@pytest.mark.parametrize("event", ["link_drop", "restart", "options_save"])
async def test_an_undeclared_relay_timer_outlives_link_drops_restarts_and_options_saves(
    rig: Rig, event: str
) -> None:
    """Z4R2-01, Z4R2-02: the timer left at "I don't know"; the relay's own 27-minute timer, which
    a repeated "on" does not restart (27, so the 5-min renewals do not happen to hide its
    lapses). Three times in a day, mid on-period: the relay's link drops for 20 s (back "on", its
    timer running: the on-period still counts from its own "on"), or the entry restarts, or an
    options save reloads it (the timer seen, and the switch-offs compared, are stored and read
    back). A switch-off at the timer's age is never counted toward answer N, after such an event
    too: heating goes on, never a step aside, and the issue asks to declare the timer."""
    await start_relay(
        rig,
        relay={"off_timer_min": 27, "timer_restarts_on_repeat": False},
        relay_off_timer="unknown",
    )
    await relay_on_under_control(rig)
    assert rig.entry is not None
    started = rig.now() - START_TRACE_S - 30.0  # the relay went on with control
    repeat = 300
    for minutes in (40, 85, 130):
        await rig.advance(started + minutes * 60 - rig.now())
        if event == "link_drop":
            await rig.scenario("relay_wifi_loss", minutes=20 / 60)
        elif event == "restart":
            assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
            await rig.hass.async_block_till_done()
        else:
            repeat -= 7  # never a divisor of 27 min: a renewal would race every lapse
            control = dict(rig.entry.options["control"]) | {"relay_repeat_s": repeat}
            options = dict(rig.entry.options) | {"control": control}
            rig.hass.config_entries.async_update_entry(rig.entry, options=options)
            await rig.hass.async_block_till_done()
        assert rig.state("sensor", "control_state").state != "handed_back"
    while rig.now() < started + 300 * 60:  # five hours from the start
        await rig.advance(900)
        assert rig.state("sensor", "control_state").state == "heating"
        assert alarm(rig, "outside_change") == "off"
    assert relay_model(rig).own_changes >= 8  # its timer, again and again
    unit = rig.entry.runtime_data.control
    assert len(unit._session.loop.relay.restarts) <= 1  # the first lapse only
    seen = unit._session.loop.relay.timer_seen_s
    assert seen is not None
    assert abs(seen - 27 * 60) <= 20.0
    found = repair(rig, "relay_timer_seen")
    assert found is not None
    assert found.translation_placeholders["minutes"] == "27"


@pytest.mark.parametrize(
    ("repeat_s", "rest"),
    # 50 s, not 60: a renewal every 60 s would land at the very moment of each 2-min lapse, and
    # the simulator's order within that moment would decide whether a lapse is ever shown.
    [(50, "off"), (300, "on")],
    ids=["repeat_50s_rest_off", "repeat_300s_rest_on"],
)
async def test_a_short_relay_timer_makes_the_plugin_step_aside_and_says_so(
    rig: Rig, repeat_s: int, rest: str
) -> None:
    """K4.2 (decided by the user 2026-10-03; Z4R3-02): the timer left at "I don't know"; the
    relay switches itself off 2 min after every "on" — an "inching" timer that a repeated "on"
    does not restart. Too short to be taken for the relay's own timer: each switch-off is
    answered and counted (in the unit's first five minutes as an outage's lost command), and the
    fourth counted within a day makes the plugin step aside — about 13 min after control
    started, after 6 boiler starts, where before it went on with some 30 starts an hour for good.
    The rest state is set once and the relay left alone; the latch issue, an error, says the
    relay switched itself off about every 2 min and to set its timer to at least 30 min or
    switch it off — again after a restart."""
    from homeassistant.helpers import issue_registry as ir

    await start_relay(
        rig,
        relay={"off_timer_min": 2, "timer_restarts_on_repeat": False},
        relay_off_timer="unknown",
        relay_repeat_s=repeat_s,
        relay_rest_state=rest,
    )
    await relay_on_under_control(rig)
    for _ in range(90):  # up to a quarter of an hour more
        if rig.state("sensor", "control_state").state == "handed_back":
            break
        await rig.advance(10)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert relay_model(rig).own_changes <= 7  # its switch-offs up to the step aside
    await rig.advance(30)
    found = repair(rig, "control_latched")
    assert found is not None
    assert found.translation_key == f"control_latched_relay_short_timer_{rest}"
    assert found.translation_placeholders == {"relay": "Boiler sim relay", "minutes": "2"}
    assert found.severity is ir.IssueSeverity.ERROR  # its timer stops heating either way
    count, lapses = len(relay_commands(rig)), relay_model(rig).own_changes
    await rig.advance(1800, step=30.0)
    assert relay_commands(rig)[count:] == []  # left alone
    assert relay_model(rig).own_changes - lapses <= 1  # at most the rest state "on" lapsing
    assert not relay_model(rig).on
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    await rig.advance(30)
    again = repair(rig, "control_latched")
    assert again is not None
    assert again.translation_key == found.translation_key
    assert again.translation_placeholders == found.translation_placeholders


async def test_relay_with_an_unknown_timer_is_kept_on_by_repeats(rig: Rig) -> None:
    """R3, R8: the timer declared "I don't know": "on" is repeated every repeat interval
    (300 s) while the command is on, and the relay's own 10-minute timer, restarted by each
    "on", never lapses; "off" is not repeated — the relay reports its state."""
    await start_relay(rig, relay={"off_timer_min": 10}, relay_off_timer="unknown")
    await relay_on_under_control(rig)
    for _ in range(360):  # an hour
        await rig.advance(10)
        assert relay_model(rig).on
    times = [t for t, on in relay_model(rig).commands if on]
    gaps = [b - a for a, b in pairwise(times)]
    assert gaps
    assert max(gaps) <= 310.0
    rooms_call(rig, False)
    await rig.advance(1200, step=30.0)
    assert relay_commands(rig)[-1] is False
    assert relay_commands(rig).count(False) == 1


@pytest.mark.parametrize(
    ("start_up", "commanded", "sent"),
    [("off", True, True), ("on", False, False), ("last", True, None), ("last", False, None)],
)
async def test_relay_start_up_state_after_power_cut(
    rig: Rig, start_up: str, commanded: bool, sent: bool | None
) -> None:
    """Rule 7: a power cut of the relay, seen as 10 s unavailable; back in its own state after a
    power cut. Found other than commanded — off while heat is wanted, or on while it is not,
    the boiler heating without control — the command goes at once (answer C); found as
    commanded ("last"), nothing. Missing data: no flame or flow mapped — a home with a relay
    alone — control runs all the same, shown without confirmation that the boiler heats."""
    await start_relay(rig, relay={"start_up": start_up}, signals={})
    rooms_call(rig, commanded)
    await rig.switch(True)
    await rig.advance(START_TRACE_S)
    count = len(relay_commands(rig))
    restarts = relay_model(rig).own_changes
    await rig.scenario("relay_restart")
    await rig.advance(40)
    assert relay_model(rig).available
    assert relay_model(rig).own_changes == restarts + 1  # back in its own state, then...
    assert relay_commands(rig)[count:] == ([] if sent is None else [sent])
    assert relay_model(rig).on is commanded
    switch = rig.state("switch", "control")
    assert switch.attributes["confirmation"] == "without_heat_confirmation"
    assert rig.state("sensor", "control_state").state == ("heating" if commanded else "idle")


async def test_an_optimistic_relay_is_controlled_without_confirmation(rig: Rig) -> None:
    """Rule 7's ``assumed_state``: an optimistic relay entity — its state Home Assistant's own
    guess, declared to report its state all the same — confirms nothing: control runs "without
    confirmation", the command, on or off, repeated blindly every repeat interval, and a
    restart nobody saw is undone within that interval."""
    await start_relay(rig, relay={"assumed_state": True})
    await relay_on_under_control(rig)
    assert rig.hass.states.get(RELAY).attributes.get("assumed_state") is True
    switch = rig.state("switch", "control")
    assert switch.attributes["confirmation"] == "controlled_without_confirmation"
    assert rig.state("sensor", "control_state").attributes["relay_check"] == "unverified"
    count = len(relay_commands(rig))
    await rig.scenario("relay_restart", reported=False)
    assert not relay_model(rig).on
    await rig.advance(310)
    assert relay_commands(rig)[count:] == [True]  # the blind repeat put it back
    assert relay_model(rig).on
    rooms_call(rig, False)
    await rig.advance(620)
    assert relay_commands(rig)[-3:] == [False, False, False]  # "off" repeated too
    assert alarm(rig, "outside_change") == "off"


async def test_relay_path_without_the_separate_contact_tick_is_blocked(rig: Rig) -> None:
    """Answer G: without the tick "this is a separate relay contact, not a setting stored in the
    boiler's memory" control does not start — it says why — and nothing reaches the relay; the
    monitor runs."""
    await start_relay(rig, relay_is_separate_contact=False)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_relay_contact_not_confirmed"
    rooms_call(rig, True)
    await rig.advance(600, step=30.0)
    assert relay_commands(rig) == []
    assert rig.state("binary_sensor", "connection").state == "on"  # the monitor runs


# --- Z3, rule 8: the boiler's restart lockout against the relay's proof of heat --------------


async def test_relay_proof_of_heat_outlasts_the_restart_lockout(rig: Rig) -> None:
    """R12 against rule 8: a boiler with a 20-minute restart lockout (test-only). The relay off
    and on again a minute later: the burner waits out its lockout before it fires — within X8's
    30-minute proof window, so no "boiler not responding". A boiler whose own lockout fault keeps
    it off raises that information alarm after 30 minutes — control goes on. Missing data: the
    boiler's lockout signal mapped but unavailable counts as no fault."""
    signals = RELAY_SIGNALS | {"boiler_lockout": "binary_sensor.boiler_sim_boiler_lockout"}
    await start_relay(rig, signals=signals, lockout_s=1200.0)
    await rig.scenario("fail_signal", signal="boiler_lockout")
    await relay_on_under_control(rig)
    assert rig.sim.last.flame
    rooms_call(rig, False)
    await rig.advance(30)
    assert not relay_model(rig).on
    assert not rig.sim.last.flame
    rig.sim.plant.water = 20.0  # cooled: it would fire at once but for its lockout
    await rig.advance(30)
    rooms_call(rig, True)
    fired_after: float | None = None
    for i in range(180):  # thirty minutes
        await rig.advance(10)
        if fired_after is None and rig.sim.last.flame:
            fired_after = (i + 1) * 10.0
        assert alarm(rig, "boiler_not_responding") == "off", i
    assert fired_after is not None
    assert 15 * 60.0 <= fired_after <= 20 * 60.0  # the lockout's end, not before
    assert rig.state("sensor", "control_state").attributes["boiler_heats"] == "heats"
    await rig.scenario("set_fault", fault="boiler_lockout")  # its signal unavailable all along
    rooms_call(rig, False)
    await rig.advance(60)
    rooms_call(rig, True)
    await rig.advance(1800, step=30.0)
    assert relay_model(rig).on  # no protection stop on an unknown fault signal
    await rig.advance(60, step=30.0)
    assert alarm(rig, "boiler_not_responding") == "on"
    assert rig.state("sensor", "control_state").state == "heating"  # information only
