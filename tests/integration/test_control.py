"""Control in Home Assistant: switching on and off, keep-alive, every hand-back path, no write
without fresh data, guard alarms, learning pauses and the allowed service calls.

Everything runs in the test's Home Assistant; the gateway, VT and SmartPI are fakes that record
the calls they receive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any

import pytest
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.core import Event, HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache,
)

from custom_components.vtherm_smart_boiler import control as control_module
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.curve import HeatingCurve
from custom_components.vtherm_smart_boiler.core.signals import Signal

from .harness import BOILER_ENTITIES, VT_PLATFORM, FakeBoiler, FakeZones

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SIGNALS = (Signal.FLAME, Signal.FLOW, Signal.OUTDOOR, Signal.DHW_ACTIVE)
CONFIRMED = "sensor.fake_gateway_control_setpoint"
OUTDOOR = 5.0
EXPECTED = round(HeatingCurve().flow(OUTDOOR), 1)  # the curve's setpoint at 5 °C outside
START = datetime(2026, 1, 12, 8, tzinfo=UTC)


@dataclass
class FakeGateway:
    """``opentherm_gw`` services; the control setpoint entity echoes the override like the
    gateway does, or the thermostat's value without one. ``forced`` plays another controller."""

    hass: HomeAssistant
    thermostat: float = 40.0
    echo: bool = True
    forced: float | None = None
    override: float | None = None
    fail_after: bool = False  # the setpoint arrives, but the call reports a failure (a timeout)
    calls: list[tuple[str, Any]] = field(default_factory=list)
    times: list[float] = field(default_factory=list)  # when each setpoint arrived

    def register(self) -> None:
        async def setpoint(call: ServiceCall) -> None:
            value = float(call.data["temperature"])
            self.calls.append(("setpoint", value))
            self.times.append(datetime.now(UTC).timestamp())
            self.override = None if value == 0 else value
            self.publish()
            if self.fail_after:
                raise HomeAssistantError("timed out")

        async def heating(call: ServiceCall) -> None:
            self.calls.append(("ch", call.data["ch_override"]))
            if self.fail_after:
                raise HomeAssistantError("timed out")

        self.hass.services.async_register("opentherm_gw", "set_control_setpoint", setpoint)
        self.hass.services.async_register("opentherm_gw", "set_central_heating_ovrd", heating)
        self.publish()

    def publish(self) -> None:
        if self.forced is not None:
            value = self.forced
        elif self.echo and self.override is not None:
            value = self.override
        else:
            value = self.thermostat
        self.hass.states.async_set(CONFIRMED, str(value), {"unit_of_measurement": "°C"})

    def setpoints(self) -> list[float]:
        return [value for kind, value in self.calls if kind == "setpoint"]


@dataclass
class Rig:
    hass: HomeAssistant
    freezer: Any
    boiler: FakeBoiler
    zones: FakeZones
    gateway: FakeGateway
    entry: MockConfigEntry | None = None
    flow: float | None = 35.0
    dhw: bool = False
    outdoor: float = OUTDOOR
    flow_reported: bool = True  # False: the flow is not reported again (a source that reports
    # only on change, as MQTT entities do)
    services: list[tuple[str, str, dict[str, Any]]] = field(default_factory=list)

    def live(self) -> None:
        """The gateway's periodic reports: fresh boiler signals and setpoint echo."""
        values: dict[Signal, float | bool | None] = {
            Signal.FLAME: False,
            Signal.OUTDOOR: self.outdoor,
            Signal.DHW_ACTIVE: self.dhw,
        }
        if self.flow_reported:
            values[Signal.FLOW] = self.flow
        self.boiler.set_many(values)
        self.gateway.publish()

    async def advance(self, seconds: float, step: float = 10.0) -> None:
        elapsed = 0.0
        while elapsed < seconds:
            self.freezer.tick(step)
            elapsed += step
            self.live()
            async_fire_time_changed(self.hass)
            await self.hass.async_block_till_done()

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

    def plugin_calls(self) -> set[tuple[str, str]]:
        """Service calls made by the plugin (the test's own switch calls left out)."""
        return {(domain, service) for domain, service, _ in self.services if domain != "switch"}


def options(zones: FakeZones, **control: Any) -> dict[str, Any]:
    control_options = {
        "write_path": "opentherm_gw",
        "gateway_id": "gw",
        "confirmed_entity": CONFIRMED,
        "topology": "gateway_with_thermostat",
        "curve": {"design_outdoor": -15, "design_flow": 55},
    } | control
    return {
        "signals": {s.value: BOILER_ENTITIES[s] for s in SIGNALS},
        "boiler": {"class": "flow_setpoint", "dhw": "combi"},
        "zones": [{"entity_id": e} for e in zones.entities.values()],
        "monitor": {"monitoring_days": 0},
        "control": control_options,
    }


@pytest.fixture
async def rig(hass: HomeAssistant, freezer, zones: FakeZones) -> Rig:
    freezer.move_to(START)
    boiler = FakeBoiler(hass, SIGNALS)
    gateway = FakeGateway(hass)
    gateway.register()
    zones.add("living", hvac_action="heating", valve_open_percent=60, on_percent=0.6)
    rig = Rig(hass, freezer, boiler, zones, gateway)
    rig.live()

    def record(event: Event) -> None:
        data = event.data
        rig.services.append((data["domain"], data["service"], dict(data["service_data"])))

    hass.bus.async_listen(EVENT_CALL_SERVICE, record)
    return rig


async def start(rig: Rig, **control: Any) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones, **control)
    )
    entry.add_to_hass(rig.hass)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry


async def test_control_is_off_by_default_and_refused_during_monitoring(rig: Rig) -> None:
    await start(rig)
    assert rig.state("switch", "control").state == "off"
    await rig.advance(60)
    assert rig.gateway.calls == []
    hass = rig.hass
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Second",
        data={},
        options=options(rig.zones) | {"monitor": {"monitoring_days": 7}},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    switch = er.async_get(hass).async_get_entity_id("switch", DOMAIN, f"{entry.entry_id}_control")
    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": switch}, blocking=True
        )
    assert err.value.translation_key == "blocked_monitoring_period"
    assert hass.states.get(switch).state == "off"
    assert rig.gateway.calls == []


async def test_switching_on_writes_keeps_alive_and_switching_off_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    # The setpoint first: the gateway applies heating on/off only while it holds a setpoint.
    assert rig.gateway.calls[:2] == [("setpoint", EXPECTED), ("ch", True)]
    state = rig.state("sensor", "control_state")
    assert state.state == "heating"
    assert rig.state("sensor", "control_setpoint").state == str(EXPECTED)

    await rig.advance(300)
    times = [t for t, (kind, _) in enumerate(rig.gateway.calls) if kind == "setpoint"]
    assert len(times) >= 10  # a keep-alive at least every 30 s over five minutes
    assert set(rig.gateway.setpoints()) == {EXPECTED}
    assert rig.state("sensor", "control_setpoint").attributes["confirmed"] == EXPECTED
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"

    await rig.switch(False)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count  # nothing written once handed back
    assert rig.state("sensor", "control_state").state == "disabled"


async def test_keep_alive_never_lapses_between_ticks(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    moments: list[float] = []

    async def setpoint(call: ServiceCall) -> None:
        moments.append(datetime.now(UTC).timestamp())
        rig.gateway.override = float(call.data["temperature"])
        rig.gateway.publish()

    rig.hass.services.async_register("opentherm_gw", "set_control_setpoint", setpoint)
    await rig.advance(600, step=7.0)  # an uneven clock
    gaps = [b - a for a, b in pairwise(moments)]
    assert gaps
    assert max(gaps) <= 45.0  # well inside the gateway's one-minute limit


async def test_no_write_without_fresh_boiler_data(rig: Rig) -> None:
    rig.flow = None
    rig.live()
    await start(rig)
    await rig.switch(True)
    await rig.advance(60)
    assert rig.gateway.calls == []
    assert rig.state("sensor", "control_state").state == "waiting_data"
    rig.flow = 35.0
    await rig.advance(20)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


async def test_stale_data_stops_writes_and_hands_back_after_five_minutes(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.flow = None
    rig.live()
    count = len(rig.gateway.calls)
    await rig.advance(240)
    assert len(rig.gateway.calls) == count  # no keep-alive: the gateway's override lapses
    assert rig.state("sensor", "control_state").state == "waiting_data"
    await rig.advance(70)
    assert rig.gateway.calls[count:] == [("setpoint", 0.0)]
    assert rig.state("sensor", "control_state").state == "handed_back"
    resumed = len(rig.gateway.calls)
    rig.flow = 35.0
    await rig.advance(20)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[resumed:]  # control resumes with data


async def test_vt_central_mode_stopped_hands_back_and_auto_resumes(rig: Rig) -> None:
    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    hass.states.async_set(select.entity_id, "Stopped")
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert "central_stopped" in rig.state("sensor", "control_state").attributes["reasons"]
    count = len(rig.gateway.calls)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count
    hass.states.async_set(select.entity_id, "Auto")
    await rig.advance(10)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[count:]


async def test_unload_and_reload_hand_back_and_leave_no_loop(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_unload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    count = len(rig.gateway.calls)
    await rig.advance(120)
    assert len(rig.gateway.calls) == count


async def test_reload_resumes_control_as_it_was(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    handed = rig.gateway.calls.index(("setpoint", 0.0))
    await rig.advance(20)
    assert rig.state("switch", "control").state == "on"
    assert ("setpoint", EXPECTED) in rig.gateway.calls[handed:]


async def test_home_assistant_stop_hands_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.hass.async_stop()  # the hand-back runs as a shutdown job, before the stop event
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)


async def test_an_internal_error_hands_back_and_blocks_until_switched_off(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start(rig)
    await rig.switch(True)
    original = control_module.loop_step

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(control_module, "loop_step", broken)
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("binary_sensor", "alarm_control_error").state == "on"
    assert "control_error" in rig.state("switch", "control").attributes["blockers"]
    count = len(rig.gateway.calls)
    monkeypatch.setattr(control_module, "loop_step", original)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # blocked until the user switches it off and on
    await rig.switch(False)
    await rig.switch(True)
    assert ("setpoint", EXPECTED) in rig.gateway.calls[count:]
    assert rig.state("binary_sensor", "alarm_control_error").state == "off"


async def test_an_outside_change_is_rewritten_once_then_handed_back(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)  # confirmed
    rig.gateway.forced = 60.0  # another controller writes and keeps its value
    await rig.advance(10)
    assert rig.gateway.setpoints()[-1] == EXPECTED  # the one rewrite
    await rig.advance(100)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "off"
    await rig.advance(40)  # the rewrite was not confirmed in time; next step hands back
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    assert rig.state("sensor", "control_state").state == "handed_back"
    rig.gateway.forced = None
    count = len(rig.gateway.calls)
    await rig.advance(60)
    assert len(rig.gateway.calls) == count  # latched: no fight


async def test_an_ignored_write_is_reported_and_writing_goes_on(rig: Rig) -> None:
    rig.gateway.echo = False  # the boiler keeps the thermostat's value
    await start(rig)
    await rig.switch(True)
    await rig.advance(90)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "off"
    await rig.advance(60)
    assert rig.state("binary_sensor", "alarm_write_ignored").state == "on"
    assert rig.state("sensor", "control_state").state == "heating"  # information only


async def test_a_failing_write_raises_an_alarm(rig: Rig) -> None:
    await start(rig)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(True)
    assert rig.state("binary_sensor", "alarm_write_failed").state == "on"


async def test_vt_central_boiler_blocks_control(rig: Rig) -> None:
    hass = rig.hass
    await start(rig)
    await rig.switch(True)
    boiler = er.async_get(hass).async_get_or_create(
        "binary_sensor", VT_PLATFORM, "central_boiler_state"
    )
    hass.states.async_set(boiler.entity_id, "off", {"is_central_boiler_configured": True})
    await rig.advance(10)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    blockers = rig.state("switch", "control").attributes["blockers"]
    assert "vt_central_boiler_active" in blockers
    await rig.switch(False)
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_vt_central_boiler_active"


async def test_a_monitor_alarm_set_to_hand_back_hands_back(rig: Rig) -> None:
    rig.boiler = FakeBoiler(rig.hass, (*SIGNALS, Signal.PRESSURE))
    rig.boiler.set(Signal.PRESSURE, 1.5)
    rig.live()
    entry_options = options(rig.zones, alarm_reactions={"pressure_low": "hand_back"})
    entry_options["signals"][Signal.PRESSURE.value] = rig.boiler.entity(Signal.PRESSURE)
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=entry_options)
    entry.add_to_hass(rig.hass)
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.switch(True)
    assert rig.gateway.setpoints()[-1] == EXPECTED
    rig.boiler.set(Signal.PRESSURE, 0.5)
    await rig.advance(40)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert rig.state("sensor", "control_state").state == "handed_back"


async def test_learning_is_paused_during_hot_water_and_released_on_switch_off(
    rig: Rig,
) -> None:
    hass = rig.hass
    learning: list[tuple[str, bool]] = []

    async def set_learning(call: ServiceCall) -> None:
        learning.append((call.data["entity_id"], call.data["learning_enabled"]))

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    zone = rig.zones.entities["living"]
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        on_percent=0.6,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": True},
    )
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(10)
    assert learning == [(zone, False)]
    assert rig.state("sensor", "control_state").attributes["learning_paused"] == [zone]
    await rig.switch(False)
    assert learning[-1] == (zone, True)


async def test_only_allowed_services_are_called(rig: Rig) -> None:
    hass = rig.hass

    async def set_learning(call: ServiceCall) -> None:
        return None

    hass.services.async_register("vtherm_smartpi", "set_smartpi_learning", set_learning)
    rig.zones.set(
        "living",
        hvac_action="heating",
        valve_open_percent=60,
        configuration={"proportional_function": "smartpi"},
        specific_states={"smartpi_learning_enabled": True},
    )
    await start(rig)
    await rig.switch(True)
    rig.dhw = True
    await rig.advance(30)
    await rig.switch(False)
    assert rig.entry is not None
    unit = rig.entry.runtime_data.control
    allowed = unit.allowed_services | {("weather", "get_forecasts")}
    assert allowed >= rig.plugin_calls()
    assert ("vtherm_smartpi", "set_smartpi_learning") in rig.plugin_calls()
    assert unit.allowed_services == {
        ("opentherm_gw", "set_control_setpoint"),
        ("opentherm_gw", "set_central_heating_ovrd"),
        ("vtherm_smartpi", "set_smartpi_learning"),
    }


async def test_the_switch_comes_back_after_a_restart(
    hass: HomeAssistant, rig: Rig
) -> None:
    mock_restore_cache(hass, [State("switch.boiler_boiler_control_experimental", "on")])
    await start(rig)
    assert rig.state("switch", "control").state == "on"
    await rig.advance(10)
    assert ("setpoint", EXPECTED) in rig.gateway.calls


async def test_auto_tpi_zones_that_cannot_learn_raise_a_repair_issue(rig: Rig) -> None:
    rig.zones.set(
        "living",
        configuration={"proportional_function": "tpi", "is_used_by_central_boiler": True},
        specific_states={"auto_tpi_state": "on"},
    )
    await start(rig)
    assert rig.entry is not None
    issue = ir.async_get(rig.hass).async_get_issue(
        DOMAIN, f"auto_tpi_blocked_{rig.entry.entry_id}"
    )
    assert issue is not None
    assert issue.translation_key == "auto_tpi_blocked"


@dataclass
class FakeNumber:
    """A writable setpoint entity (like a boiler's EMS or ESPHome number) that records writes.

    Like Home Assistant, it drops a call while the entity is unavailable; ``lowest`` plays a device
    that ignores values below it and keeps its own.
    """

    hass: HomeAssistant
    entity_id: str = "input_number.fake_boiler_flow"
    writes: list[float] = field(default_factory=list)
    available: bool = True
    lowest: float | None = None
    value: float = 50.0

    def register(self) -> None:
        async def set_value(call: ServiceCall) -> None:
            if not self.available:
                return  # Home Assistant skips an unavailable entity without an error
            value = float(call.data["value"])
            self.writes.append(value)
            if self.lowest is None or value >= self.lowest:
                self.value = value
            self.publish(self.value)

        self.hass.services.async_register("input_number", "set_value", set_value)
        self.publish(self.value)

    def publish(self, value: float) -> None:
        state = str(value) if self.available else "unavailable"
        self.hass.states.async_set(self.entity_id, state, {"unit_of_measurement": "°C"})

    def set_available(self, available: bool) -> None:
        self.available = available
        self.publish(self.value)


def held_entity(number: FakeNumber, **extra: Any) -> dict[str, Any]:
    """Control through a held setpoint entity with a value hand-back."""
    return {
        "write_path": "entity",
        "setpoint_entity": number.entity_id,
        "write_type": "held",
        "hand_back": "value",
        "hand_back_value": 50,
        "hand_back_value_effect": "own_control",
        "confirmed_entity": number.entity_id,
        "topology": "virtual",
    } | extra


async def test_a_held_setpoint_is_written_on_change_only(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, decision_interval_min=1, ramp_k_per_min=10))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    await rig.advance(120)
    assert number.writes == [EXPECTED]  # the device holds it: no keep-alive

    rig.outdoor = -5.0
    await rig.advance(120)
    assert len(number.writes) == 2
    assert number.writes[-1] > EXPECTED
    await rig.switch(False)
    assert number.writes[-1] == 50.0  # the hand-back value
    assert rig.entry is not None
    assert "writes" not in rig.entry.runtime_data.control.stored()  # no daily cap to keep


async def test_mqtt_path_calls_only_its_publish(rig: Rig) -> None:
    published: list[tuple[str, str]] = []

    async def publish(call: ServiceCall) -> None:
        published.append((call.data["topic"], call.data["payload"]))
        if call.data["topic"].endswith("/ctrlsetpt"):
            value = float(call.data["payload"])
            rig.gateway.override = None if value == 0 else value
            rig.gateway.publish()

    rig.hass.services.async_register("mqtt", "publish", publish)
    await start(rig, write_path="otgw_mqtt", mqtt_top="OTGW", mqtt_node="otgw-1")
    await rig.switch(True)
    await rig.advance(60)
    await rig.switch(False)
    assert published[0] == ("OTGW/set/otgw-1/ctrlsetpt", f"{EXPECTED:.1f}")
    assert published[1] == ("OTGW/set/otgw-1/chenable", "1")
    assert published[-1] == ("OTGW/set/otgw-1/ctrlsetpt", "0")
    assert rig.plugin_calls() <= {("mqtt", "publish"), ("weather", "get_forecasts")}


async def test_a_failed_hand_back_is_retried_and_stays_shown(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.hass.services.async_remove("opentherm_gw", "set_control_setpoint")
    await rig.switch(False)  # the hand-back fails
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    await rig.advance(30)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"  # kept
    rig.gateway.register()  # the gateway answers again
    await rig.advance(70)
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)  # retried until it went through
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"


async def test_a_latch_survives_a_reload(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    await rig.advance(30)
    rig.gateway.forced = 60.0  # another controller
    await rig.advance(180)
    assert rig.state("sensor", "control_state").state == "handed_back"
    assert rig.entry is not None
    assert await rig.hass.config_entries.async_reload(rig.entry.entry_id)
    await rig.hass.async_block_till_done()
    count = len(rig.gateway.setpoints())
    await rig.advance(60)
    assert rig.state("switch", "control").state == "on"
    assert len(rig.gateway.setpoints()) == count  # still handed back: no fight after reload
    assert rig.state("binary_sensor", "alarm_outside_change").state == "on"
    rig.gateway.forced = None
    await rig.switch(False)
    await rig.switch(True)  # the user's off and on clears the latch
    assert rig.gateway.setpoints()[-1] == EXPECTED


async def test_a_steady_reading_that_is_reported_only_on_change_is_not_stale(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    rig.flow_reported = False  # the flow stays at its value and is not reported again
    await rig.advance(20 * 60, step=30.0)
    assert rig.state("sensor", "control_state").state == "heating"
    gaps = [b - a for a, b in pairwise(rig.gateway.times[-30:])]
    assert gaps
    assert max(gaps) <= 40.0  # keep-alives went on


async def test_a_failed_write_is_retried_at_the_next_step(rig: Rig) -> None:
    await start(rig)
    await rig.switch(True)
    attempts: list[float] = []
    fail = {"left": 1}

    async def flaky(call: ServiceCall) -> None:
        attempts.append(datetime.now(UTC).timestamp())
        if fail["left"]:
            fail["left"] -= 1
            raise HomeAssistantError("gateway busy")
        rig.gateway.override = float(call.data["temperature"])
        rig.gateway.publish()

    rig.hass.services.async_register("opentherm_gw", "set_control_setpoint", flaky)
    await rig.advance(60)
    assert len(attempts) >= 2
    assert attempts[1] - attempts[0] <= 10.0  # not 30 s later
    assert rig.state("binary_sensor", "alarm_write_failed").state == "off"  # cleared again


async def test_a_timeout_hand_back_needs_expiring_writes(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="held",
        hand_back="timeout",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)
    assert err.value.translation_key == "blocked_timeout_needs_expiring_writes"
    assert number.writes == []


async def test_the_shutdown_hand_back_lets_the_next_shutdown_job_run(rig: Rig) -> None:
    from homeassistant.core import HassJob

    await start(rig)
    await rig.switch(True)
    ran: list[str] = []

    async def other_job() -> None:
        ran.append("other")

    rig.hass.async_add_shutdown_job(HassJob(other_job, "another integration's job"))
    await rig.hass.async_stop()
    assert rig.gateway.calls[-1] == ("setpoint", 0.0)
    assert ran == ["other"]  # removing our job while Home Assistant ran the list skipped this


async def test_a_setpoint_entity_that_rejects_a_limit_blocks_control(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    rig.hass.states.async_set(
        number.entity_id, "50", {"unit_of_measurement": "°C", "min": 20, "max": 50}
    )
    await start(
        rig,
        write_path="entity",
        setpoint_entity=number.entity_id,
        write_type="expiring",
        hand_back="value",
        hand_back_value=30,
        hand_back_value_effect="own_control",
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    with pytest.raises(ServiceValidationError) as err:
        await rig.switch(True)  # the hard maximum of 70 °C and "off" at 10 °C fall outside
    assert err.value.translation_key == "blocked_setpoint_outside_entity_range"
    assert number.writes == []


async def test_nothing_is_handed_back_twice_without_a_write_in_between(rig: Rig) -> None:
    hass = rig.hass
    select = er.async_get(hass).async_get_or_create("select", VT_PLATFORM, "central_mode")
    hass.states.async_set(select.entity_id, "Auto")
    await start(rig)
    await rig.switch(True)
    hass.states.async_set(select.entity_id, "Stopped")
    await rig.advance(10)
    assert rig.gateway.setpoints().count(0.0) == 1
    assert rig.entry is not None
    assert await hass.config_entries.async_unload(rig.entry.entry_id)
    await hass.async_block_till_done()
    assert rig.gateway.setpoints().count(0.0) == 1  # already handed back, nothing written since


async def test_an_entity_hand_back_to_an_unavailable_target_is_retried_until_confirmed(
    rig: Rig,
) -> None:
    """Home Assistant would drop the call without an error: the hand-back is not taken for done,
    is shown, and goes out again once the entity is back — done only when the entity shows it."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    number.set_available(False)
    await rig.switch(False)
    assert number.writes == [EXPECTED]  # nothing reached the device
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    control = rig.entry.runtime_data.control
    assert control.stored()["hand_back_pending"]
    await rig.advance(60)
    assert number.writes == [EXPECTED]  # still away: still owed
    number.set_available(True)
    await rig.advance(60)
    assert number.writes == [EXPECTED, 50.0]
    await rig.advance(10)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert not control.stored()["hand_back_pending"]


async def test_a_value_hand_back_the_device_does_not_take_stays_owed(rig: Rig) -> None:
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number, hand_back_value=10))
    await rig.switch(True)
    number.lowest = 20.0  # the device keeps its value: the hand-back does not reach the boiler
    await rig.switch(False)
    assert number.writes == [EXPECTED, 10.0]
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"  # not yet due
    await rig.advance(60)
    assert number.writes == [EXPECTED, 10.0, 10.0]  # sent again
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    assert rig.entry.runtime_data.control.stored()["hand_back_pending"]
    number.lowest = None
    await rig.advance(70)
    assert number.writes[-1] == 10.0
    assert number.value == 10.0
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "off"
    assert not rig.entry.runtime_data.control.stored()["hand_back_pending"]


def stored_control(hass_storage: dict[str, Any], rig: Rig) -> dict[str, Any]:
    assert rig.entry is not None
    return hass_storage[f"{DOMAIN}.{rig.entry.entry_id}"]["data"]["control"]


async def test_the_controlling_marker_is_stored_at_once(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Were Home Assistant to crash now, the next start must know the boiler was held — not only
    after the store's two-minute delay."""
    await start(rig)
    await rig.switch(True)
    assert rig.gateway.setpoints() == [EXPECTED]
    assert stored_control(hass_storage, rig)["controlling"] is True


async def test_an_unclean_restart_hands_back_when_control_does_not_resume(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """The last run held the boiler and ended without a hand-back (a crash, a power cut): control
    stays off now, so the boiler is handed back in full."""
    hass_storage[f"{DOMAIN}.previous"] = {}  # nothing else in the store matters
    entry = MockConfigEntry(domain=DOMAIN, title="Boiler", data={}, options=options(rig.zones))
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {"monitoring_since": 0.0, "control": {"controlling": True}},
    }
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    await rig.advance(20)
    assert rig.state("switch", "control").state == "off"
    assert rig.gateway.setpoints() == [0.0]  # handed back, though control is off
    await rig.advance(20)
    assert rig.gateway.setpoints() == [0.0]  # once
    assert entry.runtime_data.control.stored()["controlling"] is False


async def test_a_write_reported_failed_is_still_handed_back(rig: Rig) -> None:
    """A write that timed out may still have reached the boiler: the next hand-back is not
    skipped as if nothing had been written."""
    await start(rig)
    await rig.switch(True)
    await rig.switch(False)
    assert rig.gateway.setpoints() == [EXPECTED, 0.0]
    rig.gateway.fail_after = True
    await rig.switch(True)  # setpoint and heating arrive; both calls report a failure
    assert rig.gateway.setpoints() == [EXPECTED, 0.0, EXPECTED]
    rig.gateway.fail_after = False
    await rig.switch(False)
    assert rig.gateway.setpoints()[-1] == 0.0


def issue(rig: Rig, key: str) -> ir.IssueEntry | None:
    assert rig.entry is not None
    return ir.async_get(rig.hass).async_get_issue(DOMAIN, f"{key}_{rig.entry.entry_id}")


async def owe_a_hand_back(rig: Rig) -> FakeNumber:
    """Control through a held entity has the boiler; then the entity goes away."""
    number = FakeNumber(rig.hass)
    number.register()
    await start(rig, **held_entity(number))
    await rig.switch(True)
    assert number.writes == [EXPECTED]
    number.set_available(False)
    return number


async def test_no_control_while_a_hand_back_is_owed_keeps_handing_back(rig: Rig) -> None:
    """Control removed from the options while its hand-back cannot get through: a unit that only
    hands back keeps retrying, with a repair issue, until the boiler has it."""
    number = await owe_a_hand_back(rig)
    assert rig.entry is not None
    options = {k: v for k, v in rig.entry.options.items() if k != "control"}
    rig.hass.config_entries.async_update_entry(rig.entry, options=options)
    await rig.hass.async_block_till_done()
    assert number.writes == [EXPECTED]  # the hand-back on unload did not get through
    assert issue(rig, "hand_back_owed") is not None
    number.set_available(True)
    await rig.advance(70)
    assert number.writes == [EXPECTED, 50.0]
    await rig.advance(10)
    assert issue(rig, "hand_back_owed") is None


async def test_a_broken_control_section_keeps_monitoring_and_handing_back(
    rig: Rig, hass_storage: dict[str, Any]
) -> None:
    """Options that a newer check refuses do not stop the entry: the monitor runs, control is
    left out with a repair issue, and a hand-back still owed goes out."""
    number = FakeNumber(rig.hass)
    number.register()
    taken_with = held_entity(number) | {"curve": {"design_outdoor": -15, "design_flow": 55}}
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Boiler",
        data={},
        options=options(rig.zones, **taken_with) | {"control": {"write_path": "carrier_pigeon"}},
    )
    entry.add_to_hass(rig.hass)
    hass_storage[f"{DOMAIN}.{entry.entry_id}"] = {
        "version": 1,
        "key": f"{DOMAIN}.{entry.entry_id}",
        "data": {
            "monitoring_since": 0.0,
            "control": {"controlling": True, "taken_with": taken_with},
        },
    }
    assert await rig.hass.config_entries.async_setup(entry.entry_id)
    await rig.hass.async_block_till_done()
    rig.entry = entry
    assert issue(rig, "control_options_invalid") is not None
    await rig.advance(20)
    assert number.writes == [50.0]  # handed back through what took the boiler
    assert issue(rig, "hand_back_owed") is None


async def test_changing_the_write_path_is_refused_while_a_hand_back_is_owed(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    await rig.switch(False)
    assert rig.state("binary_sensor", "alarm_hand_back_failed").state == "on"
    assert rig.entry is not None
    flow = await rig.hass.config_entries.options.async_init(rig.entry.entry_id)
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"], {"next_step_id": "control"}
    )
    flow = await rig.hass.config_entries.options.async_configure(
        flow["flow_id"],
        {"write_path": "opentherm_gw", "topology": "virtual", "confirmed_entity": CONFIRMED},
    )
    assert flow["errors"] == {"write_path": "hand_back_pending"}


async def test_removing_the_entry_with_a_hand_back_owed_raises_a_repair_issue(rig: Rig) -> None:
    await owe_a_hand_back(rig)
    assert rig.entry is not None
    entry_id = rig.entry.entry_id
    await rig.hass.config_entries.async_remove(entry_id)
    await rig.hass.async_block_till_done()
    issues = ir.async_get(rig.hass)
    assert issues.async_get_issue(DOMAIN, f"hand_back_owed_after_removal_{entry_id}") is not None
