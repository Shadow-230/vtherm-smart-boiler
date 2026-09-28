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


# Forms whose one description covers every field alike.
ONE_DESCRIPTION = {"freshness"}


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
        "level": flow.level_schema(options),
        "freshness": flow.freshness_schema(
            options
            | {"signals": dict.fromkeys(flow.SIGNAL_FIELDS, "sensor.x"), "weather": "weather.x"}
        ),
        "control": flow.control_schema(options),
        "control_entity": flow.control_entity_schema(
            options | {"control": {"write_path": "entity", "topology": "virtual"}}
        ),  # with the "own room controller" tick (answers F, M)
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
            assert schema.schema, (section, step)
            for marker, validator in schema.schema.items():
                assert str(marker) in texts["data"], (section, step, marker)
                if step not in ONE_DESCRIPTION:
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
        errors = set(SOURCE[section]["error"])  # shown on the step that can fix them
        assert codes <= errors, sorted(codes - errors)


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
    taken = SOURCE["issues"]["hand_back_taken_by_other"]  # V5
    assert "{target}" in taken["description"]
    assert taken["title"]
    failed = SOURCE["issues"]["monitor_failed"]  # V6: the issue, and the note it becomes
    assert failed["title"]
    assert failed["description"]
    note = SOURCE["issues"]["monitor_recovered"]
    assert set(PLACEHOLDER.findall(note["description"])) == {"since", "until"}
    assert note["title"]
    assert SOURCE["exceptions"]["monitor_refresh_failed"]["message"]  # the refresh's failure
    for key in ("control_stopped_heating", "control_latched"):  # V7's two repair issues
        assert SOURCE["issues"][key]["title"], key
        assert SOURCE["issues"][key]["description"], key
    for kind in ("off", "handed_back", "monitor"):  # decision 3's repair issue (X3)
        no_zone = SOURCE["issues"][f"no_zone_known_{kind}"]
        assert no_zone["title"], kind
        assert set(PLACEHOLDER.findall(no_zone["description"])) == {"zones"}, kind


def _values(entity: dict, attribute: str) -> set[str]:
    return set(entity["state_attributes"][attribute]["state"])


def test_coded_states_and_attributes_are_translated() -> None:
    """P50: no raw code reaches the user where Home Assistant can translate it."""
    from custom_components.vtherm_smart_boiler.control import CONFIRMED_BY_GATEWAY
    from custom_components.vtherm_smart_boiler.core.alarms import AlarmKind, Level
    from custom_components.vtherm_smart_boiler.core.emitters import FactorReason, FactorStatus
    from custom_components.vtherm_smart_boiler.core.guards import Confirmation
    from custom_components.vtherm_smart_boiler.core.hand_back import HandBackConfirmation
    from custom_components.vtherm_smart_boiler.core.hot_water import HotWaterReason
    from custom_components.vtherm_smart_boiler.core.signal_check import OutdoorStatus
    from custom_components.vtherm_smart_boiler.core.zones import SelectionStatus

    sensors = SOURCE["entity"]["sensor"]
    binary = SOURCE["entity"]["binary_sensor"]
    confirmations = {c.value for c in Confirmation} | {CONFIRMED_BY_GATEWAY}
    assert _values(binary["hot_water"], "reason") == {r.value for r in HotWaterReason}
    factor = sensors["emitter_power_factor"]
    assert _values(factor, "status") == {s.value for s in FactorStatus}
    assert _values(factor, "reason") == {r.value for r in FactorReason}
    selection = {s.value for s in SelectionStatus}
    assert _values(sensors["critical_zone"], "status") == selection
    assert _values(sensors["reference_room"], "status") == selection
    assert set(sensors["reference_room"]["state"]) == (selection - {"ok"}) | {"average"}
    assert _values(binary["outdoor_sensor_problem"], "status") == {s.value for s in OutdoorStatus}
    for kind in AlarmKind:
        assert _values(binary[f"alarm_{kind.value}"], "level") == {lv.value for lv in Level}
    assert _values(sensors["control_setpoint"], "confirmation") == confirmations
    assert _values(sensors["control_state"], "heating_confirmation") == confirmations
    assert _values(sensors["control_state"], "hand_back_confirmation") == {
        c.value for c in HandBackConfirmation
    }
    assert _values(SOURCE["entity"]["switch"]["control"], "off_by") == {
        "heating_switch",
        "low_setpoint",
    }
    from custom_components.vtherm_smart_boiler.control_config import (
        FrostProtection,
        HandBackEffect,
    )

    assert _values(SOURCE["entity"]["switch"]["control"], "frost_protection_by") == {
        who.value for who in FrostProtection
    }
    assert _values(SOURCE["entity"]["switch"]["control"], "hand_back_effect") == {
        effect.value for effect in HandBackEffect
    }


def test_every_icon_belongs_to_an_entity() -> None:
    """An icon under a key no entity has would silently never show."""
    import json
    from pathlib import Path

    path = Path(__file__).parent.parent / "custom_components/vtherm_smart_boiler/icons.json"
    icons = json.loads(path.read_text())
    for domain, keys in icons["entity"].items():
        assert set(keys) <= set(SOURCE["entity"][domain]), domain
