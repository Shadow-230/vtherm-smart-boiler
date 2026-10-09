"""The test-only simulator component and the test-only ``opentherm_gw`` stub on it: entities, the
gateway-like and entity write paths, the relay, and the scenario services the acceptance
scenarios use (in-process here; the same in the test Home Assistant at J4)."""

from __future__ import annotations

import ast
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
import voluptuous as vol
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.core import Context, HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import ServiceValidationError
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import async_fire_time_changed

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")
START = datetime(2026, 1, 12, 8, tzinfo=UTC)
COMPONENTS = Path(__file__).resolve().parents[2] / "sim/custom_components"
READ_BACK = "sensor.otgw_sim_boiler_control_setpoint"
CH_ENABLE = "binary_sensor.otgw_sim_boiler_master_ch_enabled"
ROOM_SETPOINT = "sensor.otgw_sim_thermostat_room_setpoint"
ROOM_TEMPERATURE = "sensor.otgw_sim_thermostat_room_temperature"
RELAY = "switch.boiler_sim_relay"


@pytest.mark.parametrize("component", ["boiler_sim", "opentherm_gw", "j4_faults"])
def test_the_component_imports_only_what_home_assistant_can(component: str) -> None:
    """P55: Home Assistant keeps ``/config`` on the import path only while it imports
    ``custom_components``, so the simulator carries its physics: it imports itself, the
    plugin's core, Home Assistant, voluptuous and the standard library — nothing from ``sim/``.
    The stub imports nothing of the simulator either: it reaches its hub through Home
    Assistant's data. The test-only fault injector reaches the plugin by its name, at run time."""
    allowed = {"homeassistant", "voluptuous", *sys.stdlib_module_names}
    imported: list[tuple[str, str]] = []
    for path in (COMPONENTS / component).rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                imported.append((path.name, node.module))
            elif isinstance(node, ast.Import):
                imported.extend((path.name, alias.name) for alias in node.names)
    assert imported, "the walk found no imports"
    core = "custom_components.vtherm_smart_boiler.core"
    outside = [
        (name, module)
        for name, module in imported
        if module.split(".")[0] not in allowed
        and not (component == "boiler_sim" and module.startswith(core))
    ]
    assert outside == []


async def setup_sim(hass: HomeAssistant, freezer, gateway: bool = True, **conf) -> None:
    freezer.move_to(START)
    assert await async_setup_component(hass, "boiler_sim", {"boiler_sim": conf})
    await hass.async_block_till_done()
    if gateway:
        await setup_gateway(hass)


async def setup_gateway(hass: HomeAssistant) -> str:
    """The simulated gateway, set up as a user does: through the stub's config flow."""
    result = await hass.config_entries.flow.async_init(
        "opentherm_gw", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    return result["result"].entry_id


async def advance(hass: HomeAssistant, freezer, seconds: float) -> None:
    for _ in range(int(seconds // 10)):
        freezer.tick(10)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


def value(hass: HomeAssistant, entity_id: str) -> str:
    state = hass.states.get(entity_id)
    assert state is not None, entity_id
    return state.state


async def gateway(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call(
        "opentherm_gw", service, {"gateway_id": "sim"} | data, blocking=True
    )


async def scenario(hass: HomeAssistant, service: str, **data) -> None:
    await hass.services.async_call("boiler_sim", service, data, blocking=True)


async def test_entities_follow_the_plant(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer, outdoor=0.0)
    for entity_id in (
        "binary_sensor.boiler_sim_flame",
        "sensor.boiler_sim_flow",
        "sensor.boiler_sim_ch_setpoint",
        "sensor.boiler_sim_zone_living_temperature",
        "switch.boiler_sim_zone_living_valve",
        "weather.boiler_sim_weather",
        "binary_sensor.boiler_sim_low_pressure_fault",
        "binary_sensor.boiler_sim_boiler_lockout",
        "binary_sensor.boiler_sim_fault_indication",
        READ_BACK,
        CH_ENABLE,
    ):
        assert value(hass, entity_id) not in ("unavailable", "unknown"), entity_id
    assert value(hass, "number.boiler_sim_flow_setpoint") == "unknown"  # nothing written yet
    assert value(hass, ROOM_SETPOINT) == "unknown"  # no wall thermostat modelled
    assert hass.states.get(RELAY) is None  # no relay in this installation
    assert float(value(hass, "sensor.boiler_sim_outdoor")) == 0.0
    await advance(hass, freezer, 1800)
    assert float(value(hass, "sensor.boiler_sim_zone_living_temperature")) > 15.0


async def test_the_stub_gateway_is_set_up_like_the_real_one(hass: HomeAssistant, freezer) -> None:
    """P-37: the stub's config flow makes the entry the plugin's gateway step looks for —
    ``{"id": "sim"}``, running — registers the gateway services, and creates the entities the
    plugin reads with unique IDs of the real form; a second entry is refused. Unloaded, its
    gateway is refused by the services, which stay, as the real integration's do."""
    await setup_sim(hass, freezer, gateway=False)
    entry_id = await setup_gateway(hass)
    entry = hass.config_entries.async_get_entry(entry_id)
    assert entry is not None
    assert entry.data == {"id": "sim"}
    assert entry.state is ConfigEntryState.LOADED
    services = hass.services.async_services()["opentherm_gw"]
    assert {
        "set_control_setpoint",
        "set_central_heating_ovrd",
        "set_max_modulation",
        "send_transparent_command",
    } <= set(services)
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    found = registry.async_get(READ_BACK)
    assert found is not None
    assert (found.platform, found.unique_id) == ("opentherm_gw", "sim-boiler-control_setpoint")
    found = registry.async_get(CH_ENABLE)
    assert found is not None
    assert found.unique_id == "sim-boiler-master_ch_enabled"
    again = await hass.config_entries.flow.async_init(
        "opentherm_gw", context={"source": SOURCE_USER}
    )
    assert again["type"] is FlowResultType.ABORT
    assert again["reason"] == "already_configured"
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(
            "opentherm_gw",
            "set_control_setpoint",
            {"gateway_id": "other", "temperature": 40},
            blocking=True,
        )
    assert await hass.config_entries.async_unload(entry_id)
    with pytest.raises(ServiceValidationError):  # as the real one: the gateway is not set up
        await gateway(hass, "set_control_setpoint", temperature=40)


async def test_the_stub_needs_the_simulator(hass: HomeAssistant) -> None:
    """Without the simulator there is no gateway to set up (the test Home Assistant sets the
    simulator up from its YAML first), and the stub sets up nothing — no service of its own
    where another integration's, or a test's fake, may stand."""
    result = await hass.config_entries.flow.async_init(
        "opentherm_gw", context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_simulator"
    assert not await async_setup_component(hass, "opentherm_gw", {})
    assert "opentherm_gw" not in hass.services.async_services()


async def test_the_gateway_path_lapses_unless_repeated(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer, outdoor=5.0)
    own = float(value(hass, "sensor.boiler_sim_ch_setpoint"))
    await gateway(hass, "set_control_setpoint", temperature=52.0)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 52.0
    assert float(value(hass, READ_BACK)) == 52.0
    await advance(hass, freezer, 80)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == own  # lapsed
    assert float(value(hass, READ_BACK)) == own  # the thermostat's value passes again
    await gateway(hass, "set_control_setpoint", temperature=5.0)
    await advance(hass, freezer, 600)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 5.0  # below 8 °C: holds


async def test_the_stub_shows_the_acknowledgement_then_what_the_boiler_gets(
    hass: HomeAssistant, freezer
) -> None:
    """Open after R6 #2, as ``opentherm_gw`` shows it: the control setpoint written is shown at
    once; a boiler that refuses ID 1 has it dropped at the next exchange. ``CH=0`` shows as the
    boiler's "Central heating 1" off. The gateway out of reach: unavailable, commands dropped."""
    await setup_sim(hass, freezer, outdoor=5.0)
    own = float(value(hass, READ_BACK))
    await scenario(hass, "refuse_id1", enabled=True)
    await gateway(hass, "set_control_setpoint", temperature=52.0)
    assert float(value(hass, READ_BACK)) == 52.0  # confirmed...
    await advance(hass, freezer, 10)
    assert float(value(hass, READ_BACK)) == own  # ...then dropped
    await scenario(hass, "refuse_id1", enabled=False)
    await gateway(hass, "set_control_setpoint", temperature=52.0)
    await gateway(hass, "set_central_heating_ovrd", ch_override=False)
    await advance(hass, freezer, 10)
    assert float(value(hass, READ_BACK)) == 52.0
    assert value(hass, CH_ENABLE) == "off"
    await scenario(hass, "fail_signal", signal="gateway")
    for entity_id in (READ_BACK, CH_ENABLE, ROOM_SETPOINT):
        assert value(hass, entity_id) == "unavailable", entity_id
    await gateway(hass, "set_central_heating_ovrd", ch_override=True)  # returns: dropped
    await scenario(hass, "fail_signal", signal="gateway", failed=False)
    assert value(hass, CH_ENABLE) == "off"  # CH=1 never arrived
    await gateway(hass, "reset_gateway")
    assert value(hass, READ_BACK) == "unavailable"  # restarting
    await advance(hass, freezer, 20)
    assert value(hass, CH_ENABLE) == "on"  # the reset cleared CH=0
    await gateway(hass, "set_max_modulation", level=30)
    await gateway(hass, "send_transparent_command", transp_cmd="cs", transp_arg="47")
    assert float(value(hass, READ_BACK)) == 47.0
    commands = hass.data["boiler_sim"].sim.commands
    assert ("max_modulation", 30) in [(kind, v) for _t, kind, v in commands.gateway]
    assert commands.ch_writes == 2


async def test_a_persistent_setpoint_holds_and_counts_writes(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer, write_type="persistent")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.boiler_sim_flow_setpoint", "value": 48},
        blocking=True,
    )
    await advance(hass, freezer, 600)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 48.0
    assert value(hass, "sensor.boiler_sim_persistent_writes") == "1"
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.boiler_sim_external_control"}, blocking=True
    )
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) != 48.0  # handed back


async def test_heating_writes_are_counted_apart(hass: HomeAssistant, freezer) -> None:
    """P-113 through the entities: a held setpoint wears nothing — persistent writes stay 0 —
    and the heating switch's writes have their own counter."""
    await setup_sim(hass, freezer, write_type="held")
    await hass.services.async_call(
        "number",
        "set_value",
        {"entity_id": "number.boiler_sim_flow_setpoint", "value": 48},
        blocking=True,
    )
    for service in ("turn_on", "turn_off"):
        await hass.services.async_call(
            "switch", service, {"entity_id": "switch.boiler_sim_ch_enable"}, blocking=True
        )
    counters = hass.states.get("sensor.boiler_sim_persistent_writes")
    assert counters is not None
    assert counters.state == "0"
    assert counters.attributes["ch_writes"] == 2
    assert counters.attributes["relay_commands"] == 0


async def test_scenario_services(hass: HomeAssistant, freezer) -> None:
    await setup_sim(hass, freezer)
    await scenario(hass, "fail_signal", signal="flow")
    assert value(hass, "sensor.boiler_sim_flow") == "unavailable"
    await scenario(hass, "fail_signal", signal="flow", failed=False)
    assert value(hass, "sensor.boiler_sim_flow") != "unavailable"
    await scenario(hass, "force_setpoint", value=61)
    await gateway(hass, "set_control_setpoint", temperature=40.0)
    await advance(hass, freezer, 20)
    assert float(value(hass, "sensor.boiler_sim_ch_setpoint")) == 61.0  # the other controller
    await scenario(hass, "set_outdoor", temperature=-8)
    assert float(value(hass, "sensor.boiler_sim_outdoor")) == -8.0
    await gateway(hass, "set_hot_water_ovrd", dhw_override=0)
    assert value(hass, "binary_sensor.boiler_sim_dhw_enable") == "off"
    counters = hass.states.get("sensor.boiler_sim_persistent_writes").attributes
    assert counters["dhw_enable_writes"] == 1
    await scenario(hass, "set_zone_mode", zone="zone_living", mode="off")
    await advance(hass, freezer, 10)
    assert value(hass, "sensor.boiler_sim_zone_living_opening") == "0"  # S-05
    await scenario(hass, "set_room_temperature", zone="zone_bedroom", temperature=4)
    assert float(value(hass, "sensor.boiler_sim_zone_bedroom_temperature")) == 4.0
    with pytest.raises(vol.Invalid):
        await scenario(hass, "set_room_temperature", zone="zone_garage", temperature=4)
    await scenario(hass, "set_fault", fault="low_pressure_fault")
    assert value(hass, "binary_sensor.boiler_sim_low_pressure_fault") == "on"
    assert value(hass, "binary_sensor.boiler_sim_fault_indication") == "on"
    await scenario(hass, "fail_signal", signal="low_pressure_fault")
    assert value(hass, "binary_sensor.boiler_sim_low_pressure_fault") == "unavailable"
    for service, data in (
        ("relay_restart", {}),
        ("relay_wifi_loss", {"minutes": 1}),
        ("relay_switch", {"on": True}),
        ("set_wall_setpoint", {"temperature": 19}),
    ):
        with pytest.raises(ServiceValidationError):
            await scenario(hass, service, **data)


async def test_decision_6s_classes_are_reachable_through_services(
    hass: HomeAssistant, freezer
) -> None:
    """P-114: J4 reaches decision 6's classes in the test Home Assistant through services —
    the boiler clipping the setpoint, dropping the override once, its setpoint's device
    restarting (out of reach, then back with what it was given lost)."""
    await setup_sim(hass, freezer, write_type="held", outdoor=0.0)
    await scenario(hass, "clip_setpoint", value=45)
    await gateway(hass, "set_control_setpoint", temperature=60.0)
    assert float(value(hass, READ_BACK)) == 45.0
    await scenario(hass, "clip_setpoint")
    await gateway(hass, "set_control_setpoint", temperature=50.0)
    await scenario(hass, "drop_override")
    assert float(value(hass, READ_BACK)) != 50.0
    setpoint, heating = "number.boiler_sim_flow_setpoint", "switch.boiler_sim_ch_enable"
    await hass.services.async_call(
        "number", "set_value", {"entity_id": setpoint, "value": 48}, blocking=True
    )
    await hass.services.async_call("switch", "turn_off", {"entity_id": heating}, blocking=True)
    await scenario(hass, "restart_device", seconds=20)
    assert value(hass, setpoint) == "unavailable"
    assert value(hass, heating) == "unavailable"
    await advance(hass, freezer, 20)
    assert value(hass, setpoint) == "unknown"  # back, its value lost
    assert value(hass, heating) == "unknown"


async def test_the_relay_entity_follows_the_relay(hass: HomeAssistant, freezer) -> None:
    """X8's relay (rule 7): Home Assistant's calls switch it, with the caller's context; a
    restart takes it out of reach for 10 s and back in its state after a power cut, a change
    of its own with a context of its own; a restart nobody sees, the switch of another
    controller and its own timer the same, without the unavailable phase; a Wi-Fi loss keeps
    its state; its state may be unknown. Its contact is the on/off boiler's demand."""
    await setup_sim(hass, freezer, gateway=False, relay={"start_up": "off", "off_timer_min": 10})
    assert value(hass, RELAY) == "off"
    caller = Context()
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": RELAY}, blocking=True, context=caller
    )
    state = hass.states.get(RELAY)
    assert state is not None
    assert (state.state, state.context.id) == ("on", caller.id)
    assert hass.data["boiler_sim"].sim.last.demand
    await scenario(hass, "relay_restart")
    assert value(hass, RELAY) == "unavailable"
    await advance(hass, freezer, 10)
    state = hass.states.get(RELAY)
    assert state is not None
    assert state.state == "off"  # its state after a power cut
    assert state.context.id != caller.id
    await hass.services.async_call("switch", "turn_on", {"entity_id": RELAY}, blocking=True)
    await scenario(hass, "relay_restart", reported=False)
    assert value(hass, RELAY) == "off"  # at once, never unavailable
    await scenario(hass, "relay_switch", on=True)  # an automation, or its own button
    assert value(hass, RELAY) == "on"
    await scenario(hass, "relay_wifi_loss", minutes=2)
    assert value(hass, RELAY) == "unavailable"
    await advance(hass, freezer, 120)
    assert value(hass, RELAY) == "on"  # kept through the loss
    await advance(hass, freezer, 480)
    assert value(hass, RELAY) == "off"  # its own 10-minute timer, started by the switch
    await scenario(hass, "fail_signal", signal="relay")
    assert value(hass, RELAY) == "unknown"
    counters = hass.states.get("sensor.boiler_sim_persistent_writes")
    assert counters is not None
    assert counters.attributes["relay_commands"] == 2


async def test_the_wall_thermostat_is_shown_on_the_gateways_thermostat_device(
    hass: HomeAssistant, freezer
) -> None:
    """X6's wall thermostat (rule 9): its room setpoint and room temperature as an OpenTherm
    thermostat sends them; a setting changed by hand; its setpoint failed for the missing-data
    runs."""
    await setup_sim(hass, freezer, wall_thermostat="opentherm")
    assert float(value(hass, ROOM_SETPOINT)) == 21.0  # 08:00: the day program
    assert value(hass, ROOM_TEMPERATURE) not in ("unknown", "unavailable")
    await scenario(hass, "set_wall_setpoint", temperature=19)
    assert float(value(hass, ROOM_SETPOINT)) == 19.0
    await scenario(hass, "fail_signal", signal="thermostat_setpoint")
    assert value(hass, ROOM_SETPOINT) == "unavailable"
    assert value(hass, READ_BACK) != "unavailable"


def test_the_test_ha_configuration_is_valid() -> None:
    import yaml
    from custom_components.boiler_sim import CONFIG_SCHEMA, SIGNALS, sim_config

    root = Path(__file__).resolve().parents[2]
    text = (root / "devenv/config/configuration.yaml").read_text(encoding="utf-8")
    configuration = yaml.safe_load(text)
    assert "default_config" not in configuration  # nothing scans the local network
    conf = CONFIG_SCHEMA({"boiler_sim": configuration["boiler_sim"]})["boiler_sim"]
    assert sim_config(conf).relay is None
    assert "flow" in SIGNALS
    # J4's relay phase, as the comment gives it: uncommented, it is valid too.
    lines = text.splitlines()
    first = next(i for i, line in enumerate(lines) if line.startswith("  # relay:"))
    relay = yaml.safe_load("\n".join(line.replace("  # ", "", 1) for line in lines[first:]))
    phase = {k: v for k, v in configuration["boiler_sim"].items() if k != "wall_thermostat"}
    conf = CONFIG_SCHEMA({"boiler_sim": phase | relay})["boiler_sim"]
    assert sim_config(conf).relay is not None
    assert conf["restart_lockout_s"] == 1200


async def test_a_boiler_side_limit_or_refusal_is_not_shown_by_the_gateway(
    hass: HomeAssistant, freezer
) -> None:
    """PB-91: with ``at: boiler`` the gateway acknowledges and shows what it sends; the boiler
    limits or ignores it behind the gateway."""
    await setup_sim(hass, freezer, outdoor=0.0)
    hub = hass.data["boiler_sim"]
    await scenario(hass, "clip_setpoint", value=45, at="boiler")
    await gateway(hass, "set_control_setpoint", temperature=60.0)
    assert float(value(hass, READ_BACK)) == 60.0
    assert hub.sim.plant.boiler_clip == 45.0
    await scenario(hass, "clip_setpoint", at="boiler")
    await scenario(hass, "ignore_writes", enabled=True, at="boiler")
    assert hub.sim.plant.boiler_ignores_override
    assert not hub.sim.ignore_writes
    await gateway(hass, "set_control_setpoint", temperature=50.0)
    assert float(value(hass, READ_BACK)) == 50.0


def _fields(path: Path, service: str) -> dict[str, tuple[bool, object, object]]:
    """A service's fields in a ``services.yaml``: each one's required flag and number range."""
    import yaml

    found = yaml.safe_load(path.read_text(encoding="utf-8"))[service]["fields"]
    result: dict[str, tuple[bool, object, object]] = {}
    for name, field in found.items():
        number = (field.get("selector") or {}).get("number") or {}
        result[name] = (bool(field.get("required")), number.get("min"), number.get("max"))
    return result


def test_the_stub_services_match_home_assistants_for_every_call_the_plugin_makes() -> None:
    """TB-38: for every gateway service the plugin calls, the stub's ``services.yaml`` has Home
    Assistant's fields (2026.9.3, in ``.venv``), with the same required flags and ranges — a
    plugin that passes against the stub calls the real one with what it takes."""
    from homeassistant import components

    from custom_components.vtherm_smart_boiler.transport.writers import OTGW_SERVICES

    real = Path(components.__file__).parent / "opentherm_gw/services.yaml"
    stub = COMPONENTS / "opentherm_gw/services.yaml"
    for _domain, service in sorted(OTGW_SERVICES):
        assert _fields(stub, service) == _fields(real, service), service


async def test_every_simulator_service_is_described(hass: HomeAssistant, freezer) -> None:
    """F1 of the test report: the simulator's ``services.yaml`` describes exactly the services it
    registers — each with a name and a description, every field of its schema with the same
    required flag, and each choice field with the same choices — so Home Assistant loads the
    actions' descriptions without the error it logged at start. Negative: no described service
    or field is one the simulator does not take."""
    import yaml
    from homeassistant.helpers.service import async_get_all_descriptions

    await setup_sim(hass, freezer, gateway=False)
    path = COMPONENTS / "boiler_sim/services.yaml"
    described = yaml.safe_load(path.read_text(encoding="utf-8"))
    registered = hass.services.async_services_for_domain("boiler_sim")
    assert set(described) == set(registered)
    for name, service in registered.items():
        entry = described[name]
        assert entry["name"], name
        assert entry["description"], name
        schema = service.schema
        assert isinstance(schema, vol.Schema), name
        fields = entry.get("fields") or {}
        assert set(fields) == {str(marker) for marker in schema.schema}, name
        for marker, validator in schema.schema.items():
            field = fields[str(marker)]
            assert field["name"], (name, marker)
            assert field["description"], (name, marker)
            assert bool(field.get("required")) == isinstance(marker, vol.Required), (name, marker)
            if str(marker) == "zone":
                assert "text" in field["selector"], name  # the IDs follow the configured layout
            elif isinstance(validator, vol.In):
                offered = field["selector"]["select"]["options"]
                assert offered == list(validator.container), (name, marker)
    descriptions = await async_get_all_descriptions(hass)
    for name in registered:
        assert descriptions["boiler_sim"][name]["description"], name


async def test_the_gateway_rules_run_against_the_stub(hass: HomeAssistant, freezer) -> None:
    """TB-38: the stub's entities are the gateway's to the plugin — registered by
    ``opentherm_gw``, its 0 bar after a gateway reset unknown until read again — and its fault
    flags are gated, the boiler's "Fault indication" being the gate itself; a fault set in the
    simulator counts through that gate, and no longer once it clears, though the stub keeps its
    flag on as the real gateway does (Q3.9)."""
    from custom_components.vtherm_smart_boiler.core.alarms import fault_counts
    from custom_components.vtherm_smart_boiler.core.signals import Signal
    from custom_components.vtherm_smart_boiler.transport.entities import (
        EntityTransport,
        gateway_signals,
    )

    await setup_sim(hass, freezer)
    mapping = {
        Signal.PRESSURE: "sensor.otgw_sim_boiler_ch_water_pressure",
        Signal.FAULT_INDICATION: "binary_sensor.otgw_sim_boiler_slave_fault_indication",
        Signal.LOW_PRESSURE_FAULT: "binary_sensor.otgw_sim_boiler_slave_low_water_pressure",
    }
    carried = gateway_signals(hass, mapping)
    assert carried == {Signal.PRESSURE, Signal.LOW_PRESSURE_FAULT}
    transport = EntityTransport(hass, mapping, carried)

    def counts() -> bool:
        flag = transport.reading(Signal.LOW_PRESSURE_FAULT).value
        gate = transport.reading(Signal.FAULT_INDICATION).value
        return fault_counts(
            flag if isinstance(flag, bool) else None,
            gated=Signal.LOW_PRESSURE_FAULT in carried,
            gate=gate if isinstance(gate, bool) else None,
        )

    pressure = transport.reading(Signal.PRESSURE).value
    assert isinstance(pressure, float)
    assert pressure > 0.5
    assert not counts()
    await gateway(hass, "reset_gateway")
    await advance(hass, freezer, 30)
    assert float(value(hass, mapping[Signal.PRESSURE])) == 0.0  # the stub shows the reset's 0
    assert transport.reading(Signal.PRESSURE).value is None  # the plugin reads it as unknown
    await advance(hass, freezer, 60)
    assert transport.reading(Signal.PRESSURE).value == pytest.approx(pressure, abs=0.2)
    await scenario(hass, "set_fault", fault="low_pressure_fault")
    assert value(hass, mapping[Signal.FAULT_INDICATION]) == "on"
    assert counts()
    await scenario(hass, "set_fault", fault="low_pressure_fault", on=False)
    assert value(hass, mapping[Signal.LOW_PRESSURE_FAULT]) == "on"  # the stale flag
    assert value(hass, mapping[Signal.FAULT_INDICATION]) == "off"
    assert not counts()
