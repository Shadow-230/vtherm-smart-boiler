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
from homeassistant.const import EVENT_CALL_SERVICE, EVENT_HOMEASSISTANT_STOP
from homeassistant.core import Event, HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
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
    hub: SimHub | None = None
    entry: MockConfigEntry | None = None
    calls: list[tuple[float, str, str, dict[str, Any]]] = field(default_factory=list)

    @property
    def sim(self):
        assert self.hub is not None
        return self.hub.sim

    def now(self) -> float:
        return datetime.now(UTC).timestamp()

    def mirror_zones(self) -> None:
        """VT's thermostats as the plugin reads them, from the simulated rooms."""
        for zone in self.sim.zones:
            opening = self.sim.opening(zone.zone_id)
            index = [z.zone_id for z in self.sim.zones].index(zone.zone_id)
            self.zones.set(
                zone.zone_id,
                current_temperature=round(self.sim.room(zone.zone_id), 1),
                temperature=self.sim.plant.targets[index],
                hvac_action="heating" if opening > 0.05 else "idle",
                valve_open_percent=round(opening * 100),
                on_percent=round(opening, 2),
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


async def start(rig: Rig, sim: dict[str, Any] | None = None, **control: Any) -> None:
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
        "monitor": {"monitoring_days": 0},
        "control": GATEWAY_CONTROL | control,
    }
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    rig.entry = entry


@pytest.fixture
async def rig(hass: HomeAssistant, freezer, zones: FakeZones) -> Rig:
    freezer.move_to(START)
    rig = Rig(hass, freezer, zones)

    def record(event: Event) -> None:
        data = event.data
        rig.calls.append(
            (rig.now(), data["domain"], data["service"], dict(data["service_data"]))
        )

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    return rig


# --- closed loop --------------------------------------------------------------------------


async def test_a_cold_day_under_control(rig: Rig) -> None:
    """Six hours at −2 °C: rooms held, limits kept, keep-alive never lapses, heating switched
    within its minimum times and budget, the DHW-enable bit never touched, only allowed
    services called."""
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
    switches = [(t, v) for t, _k, v in rig.gateway("ch")]
    changes = [(t, v) for (t, v), (_t0, v0) in zip(switches[1:], switches, strict=False) if v != v0]
    for (a, _), (b, _) in pairwise(changes):
        assert b - a >= 300.0  # minimum on and off times
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
    assert rig.state("sensor", "starts_per_hour").state not in ("unavailable",)
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
        hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
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


async def test_keep_alive_loss_lets_the_gateway_fall_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.advance(90)
    assert not rig.sim.plant.override_active(rig.now())  # lapsed: the thermostat has it back
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"


async def test_hard_limits_hold_in_hard_frost(rig: Rig) -> None:
    await start(rig, hard_max=48)
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


async def test_an_ignored_command_is_detected(rig: Rig) -> None:
    await start(rig)
    await rig.hass.services.async_call(SIM, "ignore_writes", {"enabled": True}, blocking=True)
    await rig.switch(True)
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"


async def test_central_mode_stopped_hands_back(rig: Rig) -> None:
    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    hass.states.async_set(select.entity_id, "Stopped")
    await rig.advance(10)
    assert rig.setpoints()[-1] == 0.0
    assert not rig.sim.plant.override_active(rig.now())


async def test_frost_protection_heats_in_summer(rig: Rig) -> None:
    await start(rig)
    await rig.hass.services.async_call(SIM, "set_outdoor", {"temperature": 24}, blocking=True)
    await rig.switch(True)
    await rig.advance(600)
    assert rig.state("sensor", "control_state").state == "summer"
    rig.sim.plant.room[0] = 4.0  # a room left to freeze
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
        sim={"write_type": "persistent"},
        write_path="entity",
        setpoint_entity="number.boiler_sim_flow_setpoint",
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
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    await rig.hass.services.async_call(SIM, "force_setpoint", {"value": 62}, blocking=True)
    await rig.advance(180)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    count = len(rig.setpoints())
    await rig.advance(120)
    assert len(rig.setpoints()) == count  # no fight


async def test_persistent_writes_the_daily_cap_and_a_hand_back_past_it(rig: Rig) -> None:
    await start(
        rig,
        sim={"write_type": "persistent"},
        write_path="entity",
        setpoint_entity="number.boiler_sim_flow_setpoint",
        write_type="persistent",
        hand_back="value",
        hand_back_value=0,
        topology="virtual",
        daily_cap=3,
        decision_interval_min=1,
        ramp_k_per_min=10,
    )
    await rig.switch(True)
    for outdoor in (-4, -7, -10, -13, -16):
        await rig.hass.services.async_call(
            SIM, "set_outdoor", {"temperature": outdoor}, blocking=True
        )
        await rig.advance(120)
    writes = entity_setpoints(rig)
    assert len(writes) == 3  # stopped at the cap
    assert all(abs(b - a) >= 1.0 for a, b in pairwise(writes))
    assert rig.state("binary_sensor", "alarm_daily_cap").state == "on"
    assert rig.sim.plant.override_active(rig.now())  # the last value is held
    await rig.switch(False)
    assert entity_setpoints(rig)[-1] == 0.0
    assert not rig.sim.plant.override_active(rig.now())


def entity_setpoints(rig: Rig) -> list[float]:
    return [float(v) for _t, kind, v in rig.sim.commands.entity if kind == "setpoint"]  # type: ignore[arg-type]
