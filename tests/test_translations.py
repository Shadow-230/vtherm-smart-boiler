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
        "control_return_confirm": flow.control_return_confirm_schema(),
        "confirm_blocking": flow.confirm_blocking_schema(),  # X5.12
        # X8: the relay path's steps.
        "control_relay": flow.control_relay_schema(options),
        "control_relay_from_vt": flow.control_relay_schema(options),
        "control_relay_behaviour": flow.control_relay_behaviour_schema(options),
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
    # X5: a stored value this version does not know, shown on its section's step (P-70); what
    # every form checks on submit (P-79, P-16, X5.19, P-64).
    codes |= {
        "invalid_boiler",
        "invalid_circuit",
        "invalid_zone",
        "invalid_reference",
        "invalid_monitor",
        "invalid_building",
        "invalid_freshness",
        "unreadable_options",
        "entity_not_suitable",
        "zone_not_vt",
        "entity_for_two_signals",
        "zone_on_boiler_thermostat",
        "circuit_has_zones",
    }
    for section in ("config", "options"):
        errors = set(SOURCE[section]["error"])  # shown on the step that can fix them
        assert codes <= errors, sorted(codes - errors)
    from custom_components.vtherm_smart_boiler.config_flow import _PROBLEM_STEPS

    assert set(_PROBLEM_STEPS) <= set(SOURCE["options"]["error"])
    options_only = {
        "hand_back_switch_is_heating_switch",
        "gateway_not_set_up",
        "mqtt_not_set_up",
        "design_flow_too_low",
        "design_flow_above_hard_max",
        "design_outdoor_too_warm",
        "hard_min_not_below_design_flow",
        "off_setpoint_not_below_hard_min",
    }
    assert options_only <= set(SOURCE["options"]["error"])
    zone = SOURCE["config"]["error"]["zone_on_boiler_thermostat"]
    assert set(PLACEHOLDER.findall(zone)) == {"zone"}  # the zones step names the zone


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
    frost = SOURCE["issues"]["frost_zone_closed"]  # decision 4 (X4)
    assert frost["title"]
    assert set(PLACEHOLDER.findall(frost["description"])) == {"zones"}
    assert SOURCE["entity"]["button"]["reset_comfort_correction"]["name"]  # answer J (X4)
    too_hot = SOURCE["entity"]["binary_sensor"]["alarm_circuit_too_hot"]["state_attributes"]
    # Y1 (S-16): held through a gap in the flow, then unknown with its reason.
    assert set(too_hot["reason"]["state"]) == {"no_flow_reading", "circuit_not_measured", "held"}


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
        "relay",
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


def test_x6_texts_are_translated() -> None:
    """X6: the thermostat-terminals question's errors and notice, the wall thermostat's
    attributes and issues, and the lowest water temperature's sensor and issues — every coded
    value with its text, every issue with the placeholders the code fills in."""
    from custom_components.vtherm_smart_boiler.control_config import ThermostatKind
    from custom_components.vtherm_smart_boiler.core.lowest_water import (
        EstimateGap,
        SetpointSource,
        SuggestionState,
        WallWarning,
    )

    assert set(SOURCE["selector"]["thermostat_kind"]["options"]) == {
        k.value for k in ThermostatKind
    }
    for key in ("thermostat_kind_missing", "thermostat_kind_contradicts_topology"):
        assert SOURCE["options"]["error"][key], key
    kind = SOURCE["issues"]["thermostat_kind_missing"]
    assert kind["title"]
    assert not PLACEHOLDER.findall(kind["description"])
    switch = SOURCE["entity"]["switch"]["control"]
    assert switch["state_attributes"]["wall_thermostat_setpoint"]["name"]
    assert _values(switch, "wall_thermostat_warning") == {w.value for w in WallWarning}
    wall = SOURCE["issues"]["wall_thermostat_fallback"]
    assert set(PLACEHOLDER.findall(wall["description"])) == {"value"}
    unknown = SOURCE["issues"]["wall_thermostat_fallback_unknown"]
    assert not PLACEHOLDER.findall(unknown["description"])
    sensor = SOURCE["entity"]["sensor"]["lowest_water_suggestion"]
    assert sensor["name"]
    assert _values(sensor, "state") == {s.value for s in SuggestionState}
    assert _values(sensor, "source") == {s.value for s in SetpointSource}
    assert _values(sensor, "estimate_gap") == {g.value for g in EstimateGap}
    placeholders = {"days", "short", "burns", "reference", "limit", "value"}
    for key in ("lowest_water_suggestion", "lowest_water_suggestion_boiler"):
        issue = SOURCE["issues"][key]
        assert issue["title"], key
        assert set(PLACEHOLDER.findall(issue["description"])) == placeholders, key
    held = "the plugin sends it again with the control setpoint, every 30 s"  # the follow-up
    assert held in SOURCE["options"]["step"]["control_gateway"]["data_description"]["gateway_id"]
    assert held in SOURCE["options"]["step"]["control_mqtt"]["description"]
    labels = SOURCE["options"]["step"]["control_curve"]["data"]
    assert labels["hard_min"] == "Lowest water temperature"  # the carry-over from X5
    assert labels["hard_max"] == "Highest water temperature"
    flat = flatten(SOURCE)
    assert not [key for key, text in flat.items() if "flow setpoint" in text and "hard_" in key]


def test_x7_texts_are_translated() -> None:
    """X7: VT's central entry not running (P-20), an entity removed (P-19), VT without feature
    managers naming the first version that loads them and the one tested (P-60), the restart
    the "VT central boiler active" blocker waits for, and the zone value's public name (P-61) —
    each issue with the placeholders the code fills in."""
    from custom_components.vtherm_smart_boiler import REMOVED_ISSUE
    from custom_components.vtherm_smart_boiler.control import VT_CENTRAL_ISSUE
    from custom_components.vtherm_smart_boiler.feature_manager import UNSUPPORTED_ISSUE
    from custom_components.vtherm_smart_boiler.vtherm_link import VT_TESTED

    central = SOURCE["issues"][VT_CENTRAL_ISSUE]
    assert central["title"]
    assert not PLACEHOLDER.findall(central["description"])
    removed = SOURCE["issues"][REMOVED_ISSUE]
    assert removed["title"]
    assert set(PLACEHOLDER.findall(removed["description"])) == {"field", "entity"}
    unsupported = SOURCE["issues"][UNSUPPORTED_ISSUE]["description"]
    assert set(PLACEHOLDER.findall(unsupported)) == {"version"}
    assert f"VT {VT_TESTED}" in unsupported
    active = SOURCE["exceptions"]["blocked_vt_central_boiler_active"]["message"]
    assert "until Home Assistant has restarted, even once you have unticked it" in active
    assert SOURCE["entity"]["binary_sensor"]["hot_water"]["name"] == "{zone} heat available"
    flat = flatten(SOURCE)
    assert not [key for key, text in flat.items() if "hot-water and emitter" in text]


def test_x8_texts_are_translated() -> None:
    """X8: the relay path's options, blockers, alarms, attributes and issues — every coded value
    with its text, every issue with the placeholders the code fills in; the relay's own settings
    say a Shelly's timer on a repeated "on" is not documented (Q3.10)."""
    from custom_components.vtherm_smart_boiler.control import (
        RELAY_IGNORED_ISSUE,
        RELAY_RESTS_OFF_ISSUE,
        RELAY_UNREACHABLE_ISSUE,
    )
    from custom_components.vtherm_smart_boiler.control_config import WritePath
    from custom_components.vtherm_smart_boiler.core.relay import (
        HeatEvidence,
        RelayCheck,
        RelayPowerOn,
        RelayReports,
        RelayRest,
        RelayTimer,
    )

    selectors = SOURCE["selector"]
    assert set(selectors["write_path"]["options"]) == {"none"} | {p.value for p in WritePath}
    for key, kind in (
        ("relay_reports_state", RelayReports),
        ("relay_power_on_state", RelayPowerOn),
        ("relay_off_timer", RelayTimer),
        ("relay_rest_state", RelayRest),
    ):
        assert set(selectors[key]["options"]) == {k.value for k in kind}, key
    state = SOURCE["entity"]["sensor"]["control_state"]
    assert _values(state, "relay_state") == {"on", "off", "other", "unreachable"}
    assert _values(state, "relay_check") == {c.value for c in RelayCheck}
    assert _values(state, "boiler_heats") == {h.value for h in HeatEvidence}
    switch = SOURCE["entity"]["switch"]["control"]
    assert _values(switch, "confirmation") == {
        "controlled_without_confirmation",
        "without_heat_confirmation",
    }
    for value in RelayPowerOn:
        issue = SOURCE["issues"][f"{RELAY_UNREACHABLE_ISSUE}_{value.value}"]
        assert issue["title"]
        assert set(PLACEHOLDER.findall(issue["description"])) == {"relay"}
    for key in (RELAY_IGNORED_ISSUE, f"{RELAY_IGNORED_ISSUE}_off"):
        assert set(PLACEHOLDER.findall(SOURCE["issues"][key]["description"])) == {"relay"}
    off = SOURCE["issues"][f"{RELAY_IGNORED_ISSUE}_off"]["description"]
    assert "the relay does not switch off" in off
    rests = SOURCE["issues"][RELAY_RESTS_OFF_ISSUE]
    assert set(PLACEHOLDER.findall(rests["description"])) == {"zones"}
    for key in (
        "control_latched_relay_off",
        "control_latched_relay_on",
        "control_latched_relay_heating_off_ignored",
    ):
        issue = SOURCE["issues"][key]
        assert issue["title"], key
        assert set(PLACEHOLDER.findall(issue["description"])) == {"relay"}, key
    step = SOURCE["options"]["step"]
    timer = step["control_relay"]["data_description"]["relay_off_timer"]
    assert 'whether a Shelly restarts it on a repeated "on" is not documented' in timer
    assert 'untick "Use a central boiler"' in step["control_relay_from_vt"]["description"]
    for key in ("relay_off_timer_min_missing", "vt_commands_not_supported"):
        assert SOURCE["options"]["error"][key], key
    assert "blocked_boiler_not_flow_setpoint" not in SOURCE["exceptions"]
    for signals in (SOURCE["config"]["step"]["signals"], step["signals"]):
        assert "None is required" in signals["description"]
        assert signals["data"]["boiler_power"]


def test_y1_texts_are_translated() -> None:
    """Y1: the notifications, the hand-back issues and every latch cause's issue, each with the
    placeholders the code fills in; the reasons an alarm cannot be judged; the fault signals and
    the "add water" threshold with their risks; the words the plan asks for — "there is a risk
    of a leak", never "likely"; the safety valve's rating read on the valve."""
    from custom_components.vtherm_smart_boiler.core.alarms import HOT_WATER_UNKNOWN, NO_ZONE_DATA
    from custom_components.vtherm_smart_boiler.core.controller import ControlMode

    issues = SOURCE["issues"]
    for key, placeholders in (
        ("add_water", {"value", "threshold"}),
        ("pressure_high", {"value", "limit"}),
        ("flue_gas_high", {"value", "limit"}),
        ("pressure_falling", {"change"}),
        ("boiler_fault", {"entity"}),
        ("control_latched", {"target", "value"}),
        ("control_latched_write_ignored", set()),
        ("control_latched_heating_off_ignored", set()),
        ("control_latched_other", {"alarm"}),
        ("hand_back_boiler_link_lost", set()),
        ("hand_back_control_error", set()),
        ("reactions_removed", {"alarms"}),
    ):
        issue = issues[key]
        assert issue["title"], key
        assert set(PLACEHOLDER.findall(issue["description"])) == placeholders, key
    falling = issues["pressure_falling"]["description"]
    assert "there is a risk of a leak" in falling
    assert "likely" not in falling
    assert (
        "read on the valve"
        in SOURCE["config"]["step"]["monitor"]["data_description"]["pressure_high_alarm"]
    )
    binary = SOURCE["entity"]["binary_sensor"]
    for kind in ("pressure_low", "pressure_high", "flue_gas_high", "frequent_starts"):
        assert {"held", "unknown_input"} <= _values(binary[f"alarm_{kind}"], "reason"), kind
    assert HOT_WATER_UNKNOWN in _values(binary["alarm_low_flow"], "reason")
    assert NO_ZONE_DATA in _values(binary["alarm_hysteresis_drift"], "reason")
    assert SOURCE["entity"]["sensor"]["control_state"]["state"][ControlMode.BOILER_FAULT.value]
    switch = SOURCE["entity"]["switch"]["control"]
    assert _values(switch, "blocked_by") == {"boiler_link_lost"}
    for flow in ("config", "options"):
        steps = SOURCE[flow]["step"]
        for key in ("low_pressure_fault", "boiler_lockout", "fault_indication"):
            assert steps["signals"]["data"][key], key
            assert "Optional" in steps["signals"]["data_description"][key], key
        monitor = steps["monitor"]
        assert "Empty by default" in monitor["data_description"]["add_water_below"]
        assert "pressure_low_warning" not in monitor["data"]


def test_y2_texts_are_translated() -> None:
    """Y2: the gas meter's text says that gas used with the burner off is shown apart and that
    gas used while it runs counts as heating (S-31); the attributes that show it and the days
    the verdict leaves out under control (P-96) have their names, in every language."""
    for flow in ("config", "options"):
        text = SOURCE[flow]["step"]["signals"]["data_description"]["gas_meter"]
        assert "while the burner is off" in text
        assert "is shown apart" in text
        assert "counts as heating" in text
    sensors = SOURCE["entity"]["sensor"]
    assert sensors["gas_per_degree_day"]["state_attributes"]["other_gas"]["name"]
    assert sensors["verdict"]["state_attributes"]["days_left_out"]["name"]
    for language in LANGUAGES:
        other = json.loads((TRANSLATIONS / language).read_text(encoding="utf-8"))
        names = other["entity"]["sensor"]
        assert names["gas_per_degree_day"]["state_attributes"]["other_gas"]["name"], language
        assert names["verdict"]["state_attributes"]["days_left_out"]["name"], language
