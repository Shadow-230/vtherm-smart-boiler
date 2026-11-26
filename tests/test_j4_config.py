"""J4's test configurations (devenv/config/*.yaml): each names its role for the runner and
base.py (input_text.j4_role, the test session's review of 2026-11-22), each holds the helper VT's
central boiler switches (I12.8), and the gateway's carries the automation through which J4's I2
switches control."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

DEVENV = Path(__file__).resolve().parents[1] / "devenv"
CONFIG = DEVENV / "config"
ROLES = {
    "configuration": "gateway",
    "relay": "relay",
    "entity": "entity",
    "standalone": "standalone",
    "starts": "starts",
}


def _load(name: str) -> dict:
    return yaml.safe_load((CONFIG / f"{name}.yaml").read_text(encoding="utf-8"))


def test_every_configuration_is_listed() -> None:
    assert {path.stem for path in CONFIG.glob("*.yaml")} == set(ROLES)


@pytest.mark.parametrize(("name", "role"), sorted(ROLES.items()))
def test_each_configuration_names_its_role(name: str, role: str) -> None:
    assert _load(name)["input_text"]["j4_role"]["initial"] == role


@pytest.mark.parametrize("name", sorted(ROLES))
def test_each_configuration_holds_vt_s_boiler_helper(name: str) -> None:
    """I12.8: without the helper VT's central boiler switches, control stays blocked in every
    role, not only the gateway's (the test session's review of 2026-11-26)."""
    # The runner's options, by their file: a pure module, as tests/integration/test_j4_walk.py
    # loads it.
    spec = importlib.util.spec_from_file_location("j4_options", DEVENV / "j4" / "options.py")
    assert spec is not None
    assert spec.loader is not None
    options = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(options)
    domain, object_id = options.VT_HELPER.split(".")
    assert object_id in _load(name)[domain]


def test_the_gateway_configuration_switches_control_by_an_automation() -> None:
    config = _load("configuration")
    assert "j4_set_control" in config["input_boolean"]
    (automation,) = [a for a in config["automation"] if a["id"] == "j4_set_control"]
    (trigger,) = automation["triggers"]
    assert trigger["entity_id"] == "input_boolean.j4_set_control"
    (action,) = automation["actions"]
    assert action["action"] == "vtherm_smart_boiler.set_control"
    assert "enabled" in action["data"]


def test_the_gateway_bedroom_is_light_and_the_starts_house_is_the_comparisons() -> None:
    """L15: the gateway's configuration, where Q1 and Q5 run with SmartPI in the bedroom, has the
    light bedroom; the starts criterion's keeps the radiator zones of the in-process comparison
    (tests/sim/test_control_loop.py), and every role the recalibrated house (L16)."""
    assert _load("configuration")["boiler_sim"]["zones"] == "radiators_light_bedroom"
    assert _load("starts")["boiler_sim"]["zones"] == "radiators"
    for name in ROLES:
        assert _load(name)["boiler_sim"]["house"] == "average", name
