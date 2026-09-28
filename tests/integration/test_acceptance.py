"""Acceptance scenarios (docs/plan-0.2.md, J4), in-process against the simulator component.

The plugin controls the simulated boiler through the same paths as in the test Home Assistant:
the gateway-like services or the writable setpoint entity, read back from the boiler's control
setpoint. VT's zones are stood in for by climate states mirrored from the simulated rooms and
their thermostatic valves; the test HA runs real VT instead. Nothing connects anywhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest
from custom_components.boiler_sim import SimHub
from custom_components.boiler_sim.plant import PlantOutput
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.vtherm_smart_boiler.const import DOMAIN

from .harness import VT_PLATFORM, FakeZones

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
CONFIRMED = "sensor.boiler_sim_ch_setpoint"
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
    fahrenheit: bool = False  # Home Assistant in US customary units: VT reports in °F
    calls: list[tuple[float, str, str, dict[str, Any]]] = field(default_factory=list)

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
        "off" shows its valve closed and its device off, as VT 10.4.0 does (decision 4); in
        "sleep" it shows "off" with its valve held at 100 %. (The simulated plant still opens
        its valve: Z3 closes it.)"""
        for zone in self.sim.zones:
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
                self.hass.states.async_set(
                    entity_id,
                    mode,
                    {
                        "current_temperature": self.degrees(self.sim.room(zone.zone_id)),
                        "temperature": self.degrees(self.sim.plant.targets[index]),
                        "hvac_action": action,
                        "is_ready": True,
                        "specific_states": {"is_device_active": active},
                    },
                )
                continue
            self.zones.set(
                zone.zone_id,
                mode,
                current_temperature=self.degrees(self.sim.room(zone.zone_id)),
                temperature=self.degrees(self.sim.plant.targets[index]),
                hvac_action=action,
                valve_open_percent=round(opening * 100),
                on_percent=0.0 if mode == "off" else round(opening, 2),
                # What real VT publishes for every thermostat, and what demand follows first
                # (T4): whether its device heats now, and that it has started.
                specific_states={"is_device_active": active},
                is_ready=True,
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
        await self.hass.services.async_call(
            "switch",
            "turn_on" if on else "turn_off",
            {"entity_id": self.entity("switch", "control")},
            blocking=True,
        )
        await self.hass.async_block_till_done()

    def gateway(self, kind: str | None = None) -> list[tuple[float, str, object]]:
        return [c for c in self.sim.commands.gateway if kind is None or c[1] == kind]

    def setpoints(self) -> list[float]:
        return [float(value) for _t, _kind, value in self.gateway("setpoint")]  # type: ignore[arg-type]

    def plugin_services(self) -> set[tuple[str, str]]:
        return {(d, s) for _t, d, s, _data in self.calls if d not in ("switch", SIM)}


async def start(
    rig: Rig,
    sim: dict[str, Any] | None = None,
    stored: dict[str, Any] | None = None,
    monitor: dict[str, Any] | None = None,
    **control: Any,
) -> None:
    """The simulator, VT's zones and the plugin; ``stored``: what an earlier run left in the
    entry store (0.2.1's layout). Without it, the entry ran before and its control store owes
    nothing: an entry with control and no stores at all would hand back first (V1)."""
    hass = rig.hass
    assert await async_setup_component(hass, SIM, {SIM: {"outdoor": -2.0} | (sim or {})})
    await hass.async_block_till_done()
    rig.hub = hass.data[SIM]
    for zone in rig.sim.zones:
        rig.zones.add(zone.zone_id)
    rig.mirror_zones()
    options = {
        "signals": SIGNALS,
        "weather": "weather.boiler_sim_weather",
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "parameters": {"boiler_min_power": 2.5, "boiler_max_power": 15.0},
        "zones": [{"entity_id": e} for e in rig.zones.entities.values()],
        "monitor": {"monitoring_days": 0} | (monitor or {}),
        "control": GATEWAY_CONTROL | control,
    }
    # The simulated gateway's entry in the OpenTherm Gateway integration: control writes through
    # a gateway set up in Home Assistant (X5.5).
    MockConfigEntry(domain="opentherm_gw", data={"id": "sim"}).add_to_hass(hass)
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


@pytest.fixture
async def rig(hass: HomeAssistant, freezer, zones: FakeZones, hass_storage: dict[str, Any]) -> Rig:
    freezer.move_to(START)
    rig = Rig(hass, freezer, zones, hass_storage)

    def record(event: Event) -> None:
        data = event.data
        rig.calls.append((rig.now(), data["domain"], data["service"], dict(data["service_data"])))

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    return rig


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
    assert all(25.0 <= v <= 70.0 for v in values)
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


async def test_the_monitor_works_on_the_simulated_boiler(rig: Rig) -> None:
    await start(rig)
    await rig.advance(3 * 3600, step=30.0)
    assert rig.state("binary_sensor", "connection").state == "on"
    # T10: numbers the monitor worked out from the simulated burns, not merely "available".
    assert float(rig.state("sensor", "starts_per_hour").state) >= 0.0
    assert float(rig.state("sensor", "burner_hours").state) > 0.0
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
    await rig.hass.services.async_call(SIM, "set_outdoor", {"temperature": -25}, blocking=True)
    await rig.switch(True)
    await rig.advance(1800, step=30.0)
    assert max(rig.setpoints()) <= 48.0
    assert "limit_hard_max" in rig.state("sensor", "control_state").attributes["reasons"]


async def test_stale_data_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    await rig.hass.services.async_call(SIM, "fail_signal", {"signal": "flow"}, blocking=True)
    count = len(rig.gateway())
    await rig.advance(240)
    assert len(rig.gateway()) == count  # nothing written without fresh data
    await rig.advance(90)
    assert rig.setpoints()[-1] == 0.0
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_a_failed_outdoor_sensor_falls_back_to_the_weather(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.hass.services.async_call(SIM, "fail_signal", {"signal": "outdoor"}, blocking=True)
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
    await rig.hass.services.async_call(SIM, "ignore_writes", {"enabled": True}, blocking=True)
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
    await rig.hass.services.async_call(SIM, "set_outdoor", {"temperature": 24}, blocking=True)
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
    await rig.hass.services.async_call(SIM, "force_setpoint", {"value": 62}, blocking=True)
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert [(kind, value) for _t, kind, value in rig.gateway()[-3:]] == [
        ("setpoint", 25.0),
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
# The safe hand-back on a gateway: the lowest water temperature (the hard minimum's default),
# CH=1, then CS=0 (V5).
SAFE_HAND_BACK = [("setpoint", 25.0), ("ch", True), ("setpoint", 0.0)]


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
    3 K at most, and the user is told once it has sat at that edge."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(900, step=30.0)
    attributes = rig.state("sensor", "control_state").attributes
    assert "comfort_correction" not in attributes["reasons"]
    base = attributes["target"]
    rig.sim.plant.targets[0] = 30.0  # out of reach: its valve stays fully open
    targets = []
    for _ in range(60):  # five hours
        await rig.advance(300, step=30.0)
        targets.append(rig.state("sensor", "control_state").attributes["target"])
    assert max(targets) > base + 1.0  # the correction worked
    assert max(targets) <= base + 3.0 + 0.1  # and stayed within its band
    assert max(rig.setpoints()) <= base + 3.0 + 0.1
    assert rig.state("binary_sensor", "alarm_correction_at_limit").state == "on"


async def test_an_alarm_that_hands_back_does(rig: Rig, monkeypatch: pytest.MonkeyPatch) -> None:
    """An alarm whose reaction is a hand-back — here the water pressure falling past its alarm
    limit, as with a leak — gives the boiler back, and control does not take it again."""
    await start(rig, alarm_reactions={"pressure_low": "hand_back"})
    await rig.switch(True)
    await rig.advance(60)
    assert rig.sim.plant.override_active(rig.now())
    monkeypatch.setattr(PlantOutput, "pressure", property(lambda _output: 0.4))
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_pressure_low").state == "on"
    control_state = rig.state("sensor", "control_state")
    assert control_state.state == "handed_back"
    assert "alarm_hand_back" in control_state.attributes["reasons"]
    assert rig.setpoints()[-1] == 0.0
    assert not rig.sim.plant.override_active(rig.now())
    count = len(rig.gateway())
    await rig.advance(180)
    assert len(rig.gateway()) == count


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
        await rig.hass.services.async_call(SIM, "fail_signal", {"signal": signal}, blocking=True)
    await rig.advance(900, step=30.0)
    assert "outdoor_held" in rig.state("sensor", "control_state").attributes["reasons"]
    await rig.advance(3 * 3600, step=60.0)
    assert "outdoor_unknown" in rig.state("sensor", "control_state").attributes["reasons"]
    assert rig.setpoints()[-1] >= 25.0
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
    assert all(25.0 <= v <= 70.0 for v in values), values  # °C at the boiler
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
    assert entity_setpoints(rig)[-2:] == [25.0, 0.0]  # the lowest, then the hand-back value
    assert not rig.sim.plant.override_active(rig.now())  # the boiler is on its own curve
    count = len(entity_setpoints(rig))
    await rig.advance(130)
    assert len(entity_setpoints(rig)) == count  # judged, not sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    confirmation = rig.state("sensor", "control_state").attributes["hand_back_confirmation"]
    assert confirmation == "taken_by_other"
    assert not rig.storage[key]["data"]["control"]["hand_back_pending"]


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
    assert entity_setpoints(rig)[count:] == [25.0]
    assert not rig.sim.plant.override_active(rig.now())
