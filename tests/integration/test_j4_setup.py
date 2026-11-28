"""J4's setup script (I12.28, ``devenv/j4/setup_instance.py``) walked through the real flows:
VT 10.6.5's central configuration and zones, the simulated gateway and the plugin's entry for each
role, over Home Assistant's REST API, as on a test instance — nothing connects anywhere. A second
run makes nothing. The gateway role differs from the starts role only by SmartPI's entry and the
bedroom's algorithm: the vendored SmartPI 0.4.0 does not register with VT 10.6.5 (the bench runs a
later one), and a failed thermostat leaves VT's shared state behind for the next test, so it is
not walked here."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

DEVENV = Path(__file__).resolve().parents[2] / "devenv"
CONFIG = {
    "gateway": "configuration",
    "starts": "starts",
    "relay": "relay",
    "entity": "entity",
    "standalone": "standalone",
}


@pytest.fixture
def setup_script(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    """The script, loaded from ``devenv/j4`` with its pure siblings; sys.modules as it was after."""
    monkeypatch.syspath_prepend(str(DEVENV / "j4"))
    before = set(sys.modules)
    yield importlib.import_module("setup_instance")
    for name in set(sys.modules) - before:
        del sys.modules[name]


async def _rest(hass: HomeAssistant, hass_client: Any) -> Any:
    assert await async_setup_component(hass, "config", {})
    client = await hass_client()

    async def rest(method: str, path: str, body: dict[str, Any] | None) -> tuple[int, Any]:
        response = await client.request(method, path, json=body)
        try:
            return response.status, await response.json()
        except ValueError:
            return response.status, await response.text()

    return rest


@pytest.mark.parametrize("role", ["starts", "relay", "entity", "standalone"])
async def test_the_setup_script_sets_up_a_role_through_the_real_flows(
    hass: HomeAssistant, hass_client: Any, setup_script: Any, role: str
) -> None:
    from custom_components.versatile_thermostat.vtherm_central_api import VersatileThermostatAPI

    # VT's API is a class-wide one, kept from an earlier test's Home Assistant with that test's
    # central configuration: pointed at this one, as VT's own setup does.
    VersatileThermostatAPI.get_vtherm_api(hass)
    config = yaml.safe_load((DEVENV / "config" / f"{CONFIG[role]}.yaml").read_text())
    assert await async_setup_component(
        hass, "input_boolean", {"input_boolean": config["input_boolean"]}
    )
    assert await async_setup_component(hass, "boiler_sim", {"boiler_sim": config["boiler_sim"]})
    await hass.async_block_till_done()
    rest = await _rest(hass, hass_client)

    async def state(entity_id: str) -> dict[str, Any] | None:
        found = hass.states.get(entity_id)
        return None if found is None else {"state": found.state}

    made = await setup_script.set_up(rest, state, role)
    zones = [f"VT: {zone} (tpi)" for zone in setup_script.ZONES]
    gateway = [] if role == "relay" else ["the simulated gateway"]
    assert made == ["VT: Central configuration", *zones, *gateway, f"Smart Boiler: {role}"]
    await hass.async_block_till_done()

    vt = {entry.title: entry for entry in hass.config_entries.async_entries("versatile_thermostat")}
    central = vt["Central configuration"]
    helper = setup_script.VT_HELPER
    assert central.data["central_boiler_activation_service"] == f"{helper}/input_boolean.turn_on"
    assert central.data["central_boiler_deactivation_service"] == f"{helper}/input_boolean.turn_off"
    for zone in setup_script.ZONES:
        assert vt[zone].data["used_by_controls_central_boiler"] is True, zone
    assert vt["zone_bath"].data["window_sensor_entity_id"] == setup_script.BATH_WINDOW
    (plugin,) = hass.config_entries.async_entries("vtherm_smart_boiler")
    assert helper in json.dumps({**plugin.data, **plugin.options})
    assert await setup_script.set_up(rest, state, role) == []  # everything there: nothing made


async def test_an_unknown_role_is_refused(setup_script: Any) -> None:
    async def never(*_args: Any) -> Any:
        raise AssertionError("nothing is asked")

    with pytest.raises(ValueError, match="no role"):
        await setup_script.set_up(never, never, "boiler")
