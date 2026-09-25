"""Translations: every language has exactly the keys of the English source, with the same
placeholders."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

TRANSLATIONS = (
    Path(__file__).resolve().parents[1] / "custom_components/vtherm_smart_boiler/translations"
)
SOURCE = json.loads((TRANSLATIONS / "en.json").read_text(encoding="utf-8"))
PLACEHOLDER = re.compile(r"\{(\w+)\}")


def flatten(data: object, prefix: str = "") -> dict[str, str]:
    if isinstance(data, dict):
        result: dict[str, str] = {}
        for key, value in data.items():
            result.update(flatten(value, f"{prefix}.{key}" if prefix else key))
        return result
    return {prefix: str(data)}


LANGUAGES = sorted(p.name for p in TRANSLATIONS.glob("*.json") if p.name != "en.json")


def test_there_is_a_polish_translation() -> None:
    assert "pl.json" in LANGUAGES


@pytest.mark.parametrize("language", LANGUAGES)
def test_same_keys_and_placeholders(language: str) -> None:
    source = flatten(SOURCE)
    other = flatten(json.loads((TRANSLATIONS / language).read_text(encoding="utf-8")))
    assert sorted(set(source) - set(other)) == [], "missing"
    assert sorted(set(other) - set(source)) == [], "extra"
    for key, text in source.items():
        assert set(PLACEHOLDER.findall(text)) == set(PLACEHOLDER.findall(other[key])), key
    assert all(text.strip() for text in other.values())


def test_every_entity_key_has_a_name() -> None:
    from custom_components.vtherm_smart_boiler.core.alarms import AlarmKind
    from custom_components.vtherm_smart_boiler.sensor import BOILER_SENSORS

    sensors = SOURCE["entity"]["sensor"]
    binary = SOURCE["entity"]["binary_sensor"]
    for description in BOILER_SENSORS:
        assert "name" in sensors[description.key], description.key
    for key in ("critical_zone", "emitter_power_factor"):
        assert "name" in sensors[key]
    for kind in AlarmKind:
        assert "name" in binary[f"alarm_{kind.value}"], kind
    for key in ("connection", "hot_water", "foreign_heat", "outdoor_sensor_problem"):
        assert "name" in binary[key]


def test_every_form_field_and_select_option_is_translated() -> None:
    from custom_components.vtherm_smart_boiler import config_flow as flow

    options = {
        "level": "advanced",
        "circuits": [{"id": "main"}, {"id": "second"}],
        "zones": [{"entity_id": "climate.a"}],
    }
    schemas = {
        "user": flow.user_schema({}),
        "signals": flow.signals_schema(options),
        "boiler": flow.boiler_schema(options),
        "circuit": flow.circuit_schema(options, {}),
        "zones": flow.zones_schema(options),
        "zone": flow.zone_schema(options, {}),
        "building": flow.building_schema(options),
        "reference": flow.reference_schema(options),
        "monitor": flow.monitor_schema(options),
    }
    options_only = {
        "control": flow.control_schema(options),
        "control_entity": flow.control_entity_schema(options),
        "control_gateway": flow.control_gateway_schema(options, ["gw"]),
        "control_mqtt": flow.control_mqtt_schema(options),
        "control_curve": flow.control_curve_schema(options),
        "control_behaviour": flow.control_behaviour_schema(options),
        "control_alarms": flow.control_alarms_schema(options),
    }
    for section in ("config", "options"):
        steps = schemas | (options_only if section == "options" else {})
        for step, schema in steps.items():
            if section == "options" and step == "user":
                continue
            texts = SOURCE[section]["step"][step]
            for marker, validator in schema.schema.items():
                assert str(marker) in texts["data"], (section, step, marker)
                assert str(marker) in texts["data_description"], (section, step, marker)
                config = getattr(validator, "config", {})
                key = config.get("translation_key")
                if key:
                    for option in config["options"]:
                        assert option in SOURCE["selector"][key]["options"], (key, option)
    menu = SOURCE["options"]["step"]["init"]["menu_options"]
    assert "control" in menu


def test_every_config_error_code_can_be_shown() -> None:
    from custom_components.vtherm_smart_boiler.core.installation import IssueCode

    codes = {
        "missing_signal",
        "unknown_signal",
        "unknown_parameter",
        "implausible_parameter",
        "zone_without_circuit",
        "reference_zone_unknown",
    } | {
        code.value
        for code in IssueCode
        if code.value not in ("empty_circuit", "underfloor_without_max_flow")
    }
    codes |= {"invalid_control", "alarm_limits_out_of_order"}
    for section in ("config", "options"):
        assert codes <= set(SOURCE[section]["abort"]), sorted(codes - set(SOURCE[section]["abort"]))


def test_every_control_entity_blocker_and_issue_is_translated() -> None:
    from custom_components.vtherm_smart_boiler.control import RUNTIME_BLOCKERS, ControlAlarm
    from custom_components.vtherm_smart_boiler.control_config import CONFIG_BLOCKERS
    from custom_components.vtherm_smart_boiler.core.controller import ControlMode

    for blocker in (*CONFIG_BLOCKERS, *RUNTIME_BLOCKERS):
        message = SOURCE["exceptions"][f"blocked_{blocker}"]["message"]
        assert "{others}" in message, blocker
    for kind in ControlAlarm:
        assert "name" in SOURCE["entity"]["binary_sensor"][f"alarm_{kind.value}"], kind
    assert set(SOURCE["entity"]["sensor"]["control_state"]["state"]) == {
        mode.value for mode in ControlMode
    }
    assert "name" in SOURCE["entity"]["sensor"]["control_setpoint"]
    assert "name" in SOURCE["entity"]["switch"]["control"]
    for key in ("auto_tpi_blocked", "learning_not_paused"):
        issue = SOURCE["issues"][key]
        assert "{zones}" in issue["description"]
        assert issue["title"]
