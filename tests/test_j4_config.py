"""J4's test configurations (devenv/config/*.yaml): each names its role for the runner and
base.py (input_text.j4_role, the test session's review of 2026-11-22), and the gateway's carries
the automation through which J4's I2 switches control."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

CONFIG = Path(__file__).resolve().parents[1] / "devenv" / "config"
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


def test_the_gateway_configuration_switches_control_by_an_automation() -> None:
    config = _load("configuration")
    assert "j4_set_control" in config["input_boolean"]
    (automation,) = [a for a in config["automation"] if a["id"] == "j4_set_control"]
    (trigger,) = automation["triggers"]
    assert trigger["entity_id"] == "input_boolean.j4_set_control"
    (action,) = automation["actions"]
    assert action["action"] == "vtherm_smart_boiler.set_control"
    assert "enabled" in action["data"]
