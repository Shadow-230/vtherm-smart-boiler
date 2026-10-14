"""J4's runner saves the plugin's options through Home Assistant's REST API (``devenv/j4/walk.py``,
with instance 1's base in ``devenv/j4/options.py``): walked here through the real options flow,
over the same REST API, on the simulator the test instances run — so a change to the forms that
would make the runner's saves fail fails here first, with no test Home Assistant (I8)."""

# The acceptance tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component

from .test_acceptance import (  # the rig fixture comes with them
    CH_ENABLED,
    CONFIRMED,
    ENTITY_CONTROL,
    RELAY,
    Rig,
    rig,  # noqa: F401
    start,
    start_relay,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

J4 = Path(__file__).resolve().parents[2] / "devenv" / "j4"


def _module(name: str) -> ModuleType:
    """A module of the runner, by its file: the runner's own ``lib`` reads the test instances'
    access data, so only these two pure modules are loaded."""
    spec = importlib.util.spec_from_file_location(f"j4_{name}", J4 / f"{name}.py")
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


walk = _module("walk")
j4_options = _module("options")


async def _rest(rig: Rig, hass_client: Any) -> Any:
    """The runner's ``rest``, on Home Assistant's own HTTP API."""
    assert await async_setup_component(rig.hass, "config", {})
    client = await hass_client()

    async def rest(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = await client.request(method, path, json=body)
        try:
            return response.status, await response.json()
        except ValueError:
            return response.status, await response.text()

    return rest


def _entry_id(rig: Rig) -> str:
    assert rig.entry is not None
    return rig.entry.entry_id


def _control(rig: Rig) -> dict[str, Any]:
    assert rig.entry is not None
    return dict(rig.entry.options["control"])


ONE_CIRCUIT = {"level": "advanced", "circuits": [{"id": "main", "control": "unmixed_shared"}]}


@pytest.mark.parametrize("connected", [False, True], ids=["before_connection", "connected"])
async def test_instance_1_base_is_asked_and_saved(
    rig: Rig, hass_client: Any, connected: bool
) -> None:
    """Every key of instance 1's base is asked by a form — those asked only in some
    installations aside — and saved where the plugin keeps it: the read-backs among the
    signals, the curve's values in its section, the circuit without a maximum of its own. An
    entry made before the connection question picks its path in the control device; one with
    its connection does not."""
    boiler = {"class": "flow_setpoint", "dhw": "combi"}
    if connected:
        boiler |= {"connection": "opentherm_gw", "control_mode": "full", "heat_source": "gas"}
    await start(rig, entry_options=ONE_CIRCUIT | {"boiler": boiler})
    rest = await _rest(rig, hass_client)
    base = j4_options.BASE_GATEWAY
    required = set(base) - j4_options.ASKED_SOMETIMES
    result = await walk.save_options(
        rest, _entry_id(rig), base, j4_options.GATEWAY_ITEMS, required=required
    )
    await rig.hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert rig.entry is not None
    options = rig.entry.options
    assert options["signals"]["ch_setpoint"] == CONFIRMED
    assert options["signals"]["ch_enabled"] == CH_ENABLED
    control = _control(rig)
    assert control["topology"] == "gateway_with_thermostat"
    assert control["thermostat_kind"] == "opentherm"
    assert control["curve"]["design_flow"] == 55.0
    assert control["curve"]["room_mode"] == "manual"
    assert "exponent" not in control["curve"]  # emptied: the emitters' default
    assert control["hard_min"] == 20.0
    assert control["comfort_correction"] is False
    assert control["activation_delay_s"] == 0
    assert (control["frost_limit"], control["frost_release"]) == (5.0, 7.0)
    assert options["circuits"][0].get("max_flow") is None
    # Asked where it applies: the path, by an entry made before the connection question.
    asked = set(result["seen"])
    assert ("control" in asked) is not connected


async def test_a_circuit_maximum_is_set_then_the_base_puts_it_back(
    rig: Rig, hass_client: Any
) -> None:
    """E1: the curve's former hard maximum is the circuit's now — 48 °C set with a design flow
    of 48 °C, and the base takes the maximum away again, with its too-hot alarm."""
    await start(rig, entry_options=ONE_CIRCUIT)
    rest = await _rest(rig, hass_client)
    base = j4_options.BASE_GATEWAY
    change = {"max_flow": 48.0, "design_flow": 48.0}
    await walk.save_options(
        rest, _entry_id(rig), base | change, j4_options.GATEWAY_ITEMS, required=change
    )
    await rig.hass.async_block_till_done()
    assert rig.entry is not None
    assert rig.entry.options["circuits"][0]["max_flow"] == 48.0
    assert _control(rig)["curve"]["design_flow"] == 48.0
    await walk.save_options(rest, _entry_id(rig), base, j4_options.GATEWAY_ITEMS)
    await rig.hass.async_block_till_done()
    circuit = rig.entry.options["circuits"][0]
    assert circuit.get("max_flow") is None
    assert circuit.get("max_flow_alarm") is None


async def test_a_field_no_form_asks_saves_nothing(rig: Rig, hass_client: Any) -> None:
    """Negative: a key no form asks any more — the curve's ceiling band, gone in I8 — stops the
    save, strictly with an error; otherwise its errors come back. Nothing is saved either way,
    and the flow is closed."""
    await start(rig, entry_options=ONE_CIRCUIT)
    rest = await _rest(rig, hass_client)
    before = _control(rig)
    change = j4_options.BASE_GATEWAY | {"ceiling_band": 10.0, "design_flow": 50.0}
    with pytest.raises(walk.OptionsNotSaved, match="ceiling_band"):
        await walk.save_options(
            rest, _entry_id(rig), change, j4_options.GATEWAY_ITEMS, required=["ceiling_band"]
        )
    result = await walk.save_options(
        rest,
        _entry_id(rig),
        change,
        j4_options.GATEWAY_ITEMS,
        required=["ceiling_band"],
        strict=False,
    )
    assert result["errors"]
    assert _control(rig) == before
    assert not rig.hass.config_entries.options.async_progress()


async def test_a_refused_answer_comes_back_with_its_errors(rig: Rig, hass_client: Any) -> None:
    """A form that refuses its answer — frost protection released below its limit — comes back
    with its errors, and a strict save raises. G3: an on/off contact on the gateway's thermostat
    terminals is taken by the form (the switch refuses it) or refused there; the runner sees
    which."""
    await start(rig, entry_options=ONE_CIRCUIT)
    rest = await _rest(rig, hass_client)
    change = j4_options.BASE_GATEWAY | {"frost_release": 4.0}  # below the frost limit of 5 °C
    result = await walk.save_options(
        rest, _entry_id(rig), change, j4_options.GATEWAY_ITEMS, strict=False
    )
    assert result["errors"]
    with pytest.raises(walk.OptionsNotSaved):
        await walk.save_options(rest, _entry_id(rig), change, j4_options.GATEWAY_ITEMS)
    result = await walk.save_options(
        rest,
        _entry_id(rig),
        j4_options.BASE_GATEWAY | {"thermostat_kind": "on_off"},
        j4_options.GATEWAY_ITEMS,
        required=["thermostat_kind"],
        strict=False,
    )
    await rig.hass.async_block_till_done()
    assert result.get("errors") or _control(rig)["thermostat_kind"] == "on_off"


async def test_monitoring_only_refuses_the_control_switch(rig: Rig, hass_client: Any) -> None:
    """G2: "monitor mode" is no longer a topology but the control mode "monitoring only" (I8,
    decision B7), in its own item: saved, switching control on is refused and the switch stays
    off; full control again keeps the control section as it was."""
    boiler = {"class": "flow_setpoint", "dhw": "combi", "connection": "opentherm_gw"}
    boiler |= {"control_mode": "full", "heat_source": "gas"}
    await start(rig, entry_options=ONE_CIRCUIT | {"boiler": boiler})
    rest = await _rest(rig, hass_client)
    await walk.save_options(
        rest, _entry_id(rig), {"control_mode": "monitor"}, ("mode",), required=["control_mode"]
    )
    await rig.hass.async_block_till_done()
    assert rig.entry is not None
    assert rig.entry.options["boiler"]["control_mode"] == "monitor"
    with pytest.raises(HomeAssistantError):
        await rig.switch(True)
    assert rig.state("switch", "control").state == "off"
    await walk.save_options(
        rest, _entry_id(rig), {"control_mode": "full"}, ("mode",), required=["control_mode"]
    )
    await rig.hass.async_block_till_done()
    assert rig.entry.options["boiler"]["control_mode"] == "full"
    assert _control(rig)["topology"] == "gateway_with_thermostat"


async def test_the_relay_path_walks_its_device_and_behaviour(rig: Rig, hass_client: Any) -> None:
    """R6, R8 and the relay's settings (instance 6): the relay's own settings in the control
    device, VT's activation delay in the behaviour (no longer a relay form of its own, I8)."""
    await start_relay(rig)
    rest = await _rest(rig, hass_client)
    change = {
        "relay_power_on_state": "last",
        "relay_off_timer": "none",
        "relay_repeat_s": None,
        "activation_delay_s": 120,
    }
    items = ("control", "control_behaviour")
    required = [k for k, v in change.items() if v is not None]
    await walk.save_options(rest, _entry_id(rig), change, items, required=required)
    await rig.hass.async_block_till_done()
    control = _control(rig)
    assert control["relay_entity"] == RELAY
    assert control["relay_power_on_state"] == "last"
    assert control["activation_delay_s"] == 120
    result = await walk.save_options(
        rest,
        _entry_id(rig),
        {"relay_is_separate_contact": False},
        ("control",),
        required=["relay_is_separate_contact"],
        strict=False,
    )
    await rig.hass.async_block_till_done()  # the reload a save starts, done before teardown
    assert result.get("errors") or _control(rig)["relay_is_separate_contact"] is False


async def test_the_entity_path_answers_a_form_shown_again(rig: Rig, hass_client: Any) -> None:
    """N7 (instance 7): the hand-back method changed to a switch shows the entity's form again
    with the switch's fields (I8, decision A2), answered as a user fills them in; the value
    hand-back is put back the same way."""
    await start(rig, sim={"write_type": "held"}, **ENTITY_CONTROL)
    rest = await _rest(rig, hass_client)
    external = "switch.boiler_sim_external_control"
    change = {
        "hand_back": "switch",
        "hand_back_entity": external,
        "hand_back_entity_write_type": "held",
    }
    result = await walk.save_options(rest, _entry_id(rig), change, ("control",), required=change)
    await rig.hass.async_block_till_done()
    control = _control(rig)
    assert (control["hand_back"], control["hand_back_entity"]) == ("switch", external)
    assert "control_entity" in result["seen"]
    back = {"hand_back": "value", "hand_back_value": 0}
    await walk.save_options(rest, _entry_id(rig), back, ("control",), required=back)
    await rig.hass.async_block_till_done()
    control = _control(rig)
    assert (control["hand_back"], control["hand_back_value"]) == ("value", 0)


async def test_e7_adds_a_circuit_run_by_other_automation_and_removes_it(
    rig: Rig, hass_client: Any
) -> None:
    """E7: "Add circuit" with a circuit run by other automation — its form shown again once the
    type reveals the request's fields (I8, decision A2), answered as a user fills them in — then
    the same circuit's tick removes it, back to instance 1's one circuit."""
    rig.hass.states.async_set(j4_options.CIRCUIT_ASKS_ENTITY, "off")
    await start(rig, entry_options=ONE_CIRCUIT)
    rest = await _rest(rig, hass_client)
    change = j4_options.CIRCUIT_ASKS
    result = await walk.save_options(
        rest, _entry_id(rig), change, ("add_circuit",), required=list(change)
    )
    await rig.hass.async_block_till_done()
    assert result["type"] == "create_entry"
    assert rig.entry is not None
    circuits = rig.entry.options["circuits"]
    assert len(circuits) == 2
    added = circuits[1]
    assert added["control"] == "separate"
    assert added["request_entity"] == j4_options.CIRCUIT_ASKS_ENTITY
    assert added["needed_temperature"] == 50.0
    remove = j4_options.REMOVE_CIRCUIT
    await walk.save_options(rest, _entry_id(rig), remove, ("circuit_2",), required=list(remove))
    await rig.hass.async_block_till_done()
    assert [c["id"] for c in rig.entry.options["circuits"]] == ["main"]
