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
    for key in ("critical_zone", "emitter_power_factor", "features"):
        assert "name" in sensors[key]
    for kind in AlarmKind:
        assert "name" in binary[f"alarm_{kind.value}"], kind
    for key in ("connection", "hot_water", "foreign_heat", "outdoor_sensor_problem"):
        assert "name" in binary[key]


# Forms whose one description covers every field alike (P-103: the freshness step has its
# fields' own now).
ONE_DESCRIPTION: set[str] = set()


def test_every_form_field_and_select_option_is_translated() -> None:
    from custom_components.vtherm_smart_boiler import config_flow as flow

    options = {
        "level": "advanced",
        "circuits": [{"id": "main"}, {"id": "second"}],
        "zones": [{"entity_id": "climate.a"}],
        # I6.1: a boiler that burns fuel and heats hot water shows every field of the panels.
        "boiler": {"connection": "opentherm_gw", "heat_source": "gas", "type": "combi"},
    }
    schemas = {
        "connection": flow.connection_schema(options),
        "mode": flow.mode_schema(options),
        "name": flow.user_schema({}),
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
            if section == "options" and step == "name":
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
    assert next(iter(menu)) == "connection"  # I6.1: the options open with the first panels


def test_every_config_error_code_can_be_shown() -> None:
    from custom_components.vtherm_smart_boiler.core.installation import IssueCode

    codes = {
        "missing_signal",
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
    unfed = SOURCE["options"]["error"]["zone_feeds_no_criterion"]  # PB-23 names the zone
    assert set(PLACEHOLDER.findall(unfed)) == {"zone"}


def test_every_control_entity_blocker_and_issue_is_translated() -> None:
    from custom_components.vtherm_smart_boiler.control import RUNTIME_BLOCKERS, ControlAlarm
    from custom_components.vtherm_smart_boiler.control_config import CONFIG_BLOCKERS
    from custom_components.vtherm_smart_boiler.core.controller import ControlMode

    for blocker in (*CONFIG_BLOCKERS, *RUNTIME_BLOCKERS):
        message = SOURCE["exceptions"][f"blocked_{blocker}"]["message"]
        assert "{count}" in message, blocker  # P-74: the others counted, not listed by key
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
        # PB-03: the zones known, no criterion judged — the issue names the criteria.
        no_criterion = SOURCE["issues"][f"no_criterion_judged_{kind}"]
        assert no_criterion["title"], kind
        assert set(PLACEHOLDER.findall(no_criterion["description"])) == {"criteria"}, kind
    # Decision 4 (X4); SB-27: the advice by VT's reason for closing the room.
    for advice in ("", "_window", "_central_mode", "_vt_function", "_mixed"):
        frost = SOURCE["issues"][f"frost_zone_closed{advice}"]
        assert frost["title"], advice
        assert set(PLACEHOLDER.findall(frost["description"])) == {"zones"}, advice
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
    # SB-16: a stand-alone gateway's setpoint lapses within about a minute of an outage.
    assert _values(SOURCE["entity"]["switch"]["control"], "outage_effect") == {"heating_stops"}


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
    # F5 of the test report: VT's central configuration made after Home Assistant started, with
    # no central boiler, waits for one restart too — the text says so, not only "configured".
    assert "created or changed after Home Assistant started" in active
    assert "even without a central boiler" in active
    state = SOURCE["entity"]["sensor"]["control_state"]["state_attributes"]["blockers"]["state"]
    assert "one restart of Home Assistant" in state["vt_central_boiler_active"]
    assert SOURCE["entity"]["binary_sensor"]["hot_water"]["name"] == "{zone} heat available"
    flat = flatten(SOURCE)
    assert not [key for key, text in flat.items() if "hot-water and emitter" in text]


def test_x8_texts_are_translated() -> None:
    """X8: the relay path's options, blockers, alarms, attributes and issues — every coded value
    with its text, every issue with the placeholders the code fills in; the relay's own settings
    say a Shelly's timer on a repeated "on" is not documented (Q3.10)."""
    from custom_components.vtherm_smart_boiler.control import (
        RELAY_IGNORED_ISSUE,
        RELAY_NOT_TAKING_ISSUE,
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
    # Decision 6 of 0.2.3 (SB-06): the relay that stopped taking commands in the session.
    for key in (RELAY_NOT_TAKING_ISSUE, f"{RELAY_NOT_TAKING_ISSUE}_off"):
        assert set(PLACEHOLDER.findall(SOURCE["issues"][key]["description"])) == {"relay"}
    assert "the house is not heated" in SOURCE["issues"][RELAY_NOT_TAKING_ISSUE]["description"]
    stuck = SOURCE["issues"][f"{RELAY_NOT_TAKING_ISSUE}_off"]["description"]
    assert "the relay does not switch off" in stuck
    rests = SOURCE["issues"][RELAY_RESTS_OFF_ISSUE]
    assert set(PLACEHOLDER.findall(rests["description"])) == {"zones"}
    for key in (
        "control_latched_relay_off",
        "control_latched_relay_on",
        "control_latched_relay_heating_off_ignored",
        "control_latched_relay_heating_on_ignored",
        "control_latched_relay_off_not_taken",
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
        ("control_latched_heating_on_ignored", set()),
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
        in SOURCE["config"]["step"]["boiler"]["data_description"]["pressure_high_alarm"]
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
        boiler = steps["boiler"]  # I6: the boiler step asks it
        assert "Empty by default" in boiler["data_description"]["add_water_below"]
        assert "add_water_below" not in steps["monitor"]["data"]
        assert "pressure_low_warning" not in steps["monitor"]["data"]


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


def test_y3_texts_are_translated() -> None:
    """Y3: the heating threshold's sensor with its attributes and the source of each value
    (P-90); the verdict's new reasons, "changed by control" with its "not changed yet" text and
    the "estimate only" detail (S-22, S-32, S-17, S-43); the switch's verdict (S-43); the two
    reset buttons; the installation's issues with the circuits they name (P-94); the building
    texts saying an entered value always wins (P-92) — in every language."""
    from custom_components.vtherm_smart_boiler.core.parameters import Source
    from custom_components.vtherm_smart_boiler.core.verdict import (
        ESTIMATE_ONLY,
        WATER_NOT_CONTROLLED,
        ReasonCode,
        Verdict,
    )

    for language in ("en.json", *LANGUAGES):
        texts = json.loads((TRANSLATIONS / language).read_text(encoding="utf-8"))
        sensors = texts["entity"]["sensor"]
        threshold = sensors["heating_threshold"]
        assert threshold["name"], language
        for attribute in ("source", "confidence", "entered", "measured", "mismatch"):
            assert threshold["state_attributes"][attribute]["name"], (language, attribute)
        sources = {s.value for s in Source}
        assert _values(threshold, "source") == sources, language
        assert _values(sensors["loss_coefficient"], "source") == sources, language
        verdict = sensors["verdict"]
        codes = {ReasonCode.CRITERIA_JUDGED.value, ReasonCode.NO_BURNER_SIGNAL.value}
        assert codes <= _values(verdict, "reasons"), language
        assert _values(verdict, "changed_by_control") == {"true", "false"}, language
        assert _values(verdict, "detail") == {ESTIMATE_ONLY, WATER_NOT_CONTROLLED}, language
        switch = texts["entity"]["switch"]["control"]
        assert _values(switch, "verdict") == {v.value for v in Verdict}, language
        for key in ("reset_heating_threshold", "reset_loss_coefficient"):
            assert texts["entity"]["button"][key]["name"], (language, key)
        for key in ("installation_empty_circuit", "installation_underfloor_without_max_flow"):
            issue = texts["issues"][key]
            assert issue["title"], (language, key)
            assert set(PLACEHOLDER.findall(issue["description"])) == {"circuits"}, key
    verdict = SOURCE["entity"]["sensor"]["verdict"]["state_attributes"]
    not_changed = verdict["changed_by_control"]["state"]["false"]
    assert not_changed.startswith("Not changed yet")
    assert "anti-cycling is planned" in not_changed
    # PB-75: no version or file the user does not have, no nested parentheses (the text is
    # shown inside parentheses after the reason).
    for language in ALL_LANGUAGES:
        texts = _texts(language)["entity"]["sensor"]["verdict"]["state_attributes"]
        for text in texts["changed_by_control"]["state"].values():
            assert not re.search(r"\d+\.\d+|PLAN|\(|\)", text), (language, text)
    buttons = SOURCE["entity"]["button"]
    assert buttons["reset_heating_threshold"]["name"] == "Reset measured heating threshold"
    assert buttons["reset_loss_coefficient"]["name"] == "Reset measured heat loss"
    for flow in ("config", "options"):
        building = SOURCE[flow]["step"]["building"]
        assert "data never replace it; they show a mismatch" in building["description"]
        assert "never replace it" in building["data_description"]["design_load_kw"]
        monitoring = SOURCE[flow]["step"]["monitor"]["data_description"]["monitoring_days"]
        assert "even without a verdict" in monitoring
    switch = SOURCE["entity"]["switch"]["control"]["state_attributes"]["verdict"]["state"]
    assert "without a verdict" in switch["not_enough_data"]


# --- P-76: the reverse key parity ---------------------------------------------------------------

PACKAGE = TRANSLATIONS.parent


def _module_constants() -> dict[str, str]:
    """Every module-level string constant of the package, by name (a name bound to two values
    is left out)."""
    import ast

    found: dict[str, str] = {}
    clashes: set[str] = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            targets = [node.target] if isinstance(node, ast.AnnAssign) else []
            if isinstance(node, ast.Assign):
                targets = node.targets
            value = getattr(node, "value", None)
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
                continue
            for target in targets:
                if isinstance(target, ast.Name):
                    if found.get(target.id, value.value) != value.value:
                        clashes.add(target.id)
                    found[target.id] = value.value
    return {name: value for name, value in found.items() if name not in clashes}


def _code_mentions() -> tuple[set[str], list[re.Pattern[str]]]:
    """What the package's code can name a translation key with: every string constant, every
    value of its enums, and every f-string as a pattern — its names resolved to the package's
    constants, anything else any text (an f-string of fewer than three letters of its own is
    left out: it could match anything)."""
    import ast
    import enum
    import importlib
    import inspect

    constants = _module_constants()
    literals: set[str] = {"true", "false"}  # a bool shown as its state's key
    patterns: list[re.Pattern[str]] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                literals.add(node.value)
            elif isinstance(node, ast.JoinedStr):
                parts: list[str] = []
                own = 0
                for value in node.values:
                    if isinstance(value, ast.Constant):
                        parts.append(re.escape(str(value.value)))
                        own += len(str(value.value))
                    elif (
                        isinstance(value, ast.FormattedValue)
                        and isinstance(value.value, ast.Name)
                        and value.value.id in constants
                    ):
                        parts.append(re.escape(constants[value.value.id]))
                        own += len(constants[value.value.id])
                    else:
                        parts.append(".+")
                if own >= 3:
                    patterns.append(re.compile("^" + "".join(parts) + "$"))
        module = ".".join(path.relative_to(PACKAGE.parents[1]).with_suffix("").parts)
        loaded = importlib.import_module(module.removesuffix(".__init__"))
        for _name, member in inspect.getmembers(loaded, inspect.isclass):
            if issubclass(member, enum.StrEnum) and member.__module__ == loaded.__name__:
                literals.update(item.value for item in member)
    return literals, patterns


def _mentioned(code: str, literals: set[str], patterns: list[re.Pattern[str]]) -> bool:
    return code in literals or any(pattern.match(code) for pattern in patterns)


def _flow_fields() -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """The fields of every step's form, built at both levels of detail and for each write path,
    and the options each translated selector offers."""
    from custom_components.vtherm_smart_boiler import config_flow as flow

    zones = {"zones": [{"entity_id": "climate.a"}, {"entity_id": "climate.b"}]}
    circuits = {"circuits": [{"id": "main", "max_flow": 45}, {"id": "second"}]}
    signals = {"signals": dict.fromkeys(flow.SIGNAL_FIELDS, "sensor.x"), "weather": "weather.x"}
    controls = [
        {
            "write_path": "opentherm_gw",
            "topology": "gateway_with_thermostat",
            "thermostat_kind": "opentherm",
        },
        {"write_path": "otgw_mqtt", "topology": "gateway_standalone"},
        {"write_path": "entity", "topology": "virtual", "hand_back": "value"},
        {"write_path": "entity", "topology": "virtual", "hand_back": "switch"},
        {"write_path": "relay"},
    ]
    fields: dict[str, set[str]] = {}
    selectors: dict[str, set[str]] = {}
    for level in ("simple", "advanced"):
        for control in controls:
            relay = control["write_path"] == "relay"
            boiler = {
                "class": "on_off" if relay else "flow_setpoint",
                # I6.1: the panels — every mode a connection offers, and every field shown;
                # I6.2: the connection whose path the control section takes.
                "connection": {"entity": "other_entity"}.get(
                    control["write_path"], control["write_path"]
                ),
                "heat_source": "gas",
                "type": "combi",
            }
            options = {"level": level, **zones, **circuits, **signals, "boiler": boiler}
            options["control"] = control
            schemas = {
                "connection": flow.connection_schema(options),
                "mode": flow.mode_schema(options),
                "name": flow.user_schema({}),
                "level": flow.level_schema(options),
                "signals": flow.signals_schema(options),
                "freshness": flow.freshness_schema(options),
                "boiler": flow.boiler_schema(options),
                "circuit": flow.circuit_schema(options, {}, more=True),
                "zones": flow.zones_schema(options),
                "zone": flow.zone_schema(options, {}),
                "building": flow.building_schema(options),
                "reference": flow.reference_schema(options),
                "monitor": flow.monitor_schema(options),
                "control": flow.control_schema(options),
                "control_entity": flow.control_entity_schema(options),
                "control_gateway": flow.control_gateway_schema(options, ["gw"]),
                "control_mqtt": flow.control_mqtt_schema(options),
                "control_curve": flow.control_curve_schema(options, 120.0),
                "control_behaviour": flow.control_behaviour_schema(options),
                "control_alarms": flow.control_alarms_schema(options),
                "control_return_confirm": flow.control_return_confirm_schema(),
                "confirm_blocking": flow.confirm_blocking_schema(),
                "control_relay": flow.control_relay_schema(options),
                "control_relay_from_vt": flow.control_relay_schema(options),
                "control_relay_behaviour": flow.control_relay_behaviour_schema(options),
            }
            for step, schema in schemas.items():
                for marker, validator in schema.schema.items():
                    fields.setdefault(step, set()).add(str(marker))
                    config = getattr(validator, "config", {})
                    key = config.get("translation_key")
                    if key:
                        offered = config["options"]
                        values = {o["value"] if isinstance(o, dict) else o for o in offered}
                        selectors.setdefault(key, set()).update(values)
    # I6.5: the MQTT topics step, for the OTGW firmware and for EMS-ESP.
    for connection in ("otgw_mqtt", "ems_esp"):
        schema = flow.mqtt_topics_schema({"boiler": {"connection": connection}})
        fields.setdefault("mqtt_topics", set()).update(str(m) for m in schema.schema)
    # I6.2: ESPHome's safe-start tick, asked on the writable-entity step for ESPHome only.
    esphome = {"boiler": {"connection": "esphome"}, "control": {"write_path": "entity"}}
    fields["control_entity"] |= {str(m) for m in flow.control_entity_schema(esphome).schema}
    # I6.2: the signals step reads its hint for the connection into its description.
    from custom_components.vtherm_smart_boiler.control_config import Connection

    selectors.setdefault(flow.SIGNAL_HINT, set()).update(c.value for c in Connection)
    # I6.3: and the heat source's, where it changes what to pick.
    selectors.setdefault(flow.SOURCE_HINT, set()).update(("electric", "oil"))
    # I7: the menus read what is left, what to fix and what changed into their descriptions.
    selectors.setdefault(flow.MENU_STATE, set()).update(
        ("left", "fix", "ready", "changed", "unchanged")
    )
    return fields, selectors


def _unused_keys(texts: dict) -> list[str]:
    from custom_components.vtherm_smart_boiler.config_flow import (
        SmartBoilerConfigFlow,
        SmartBoilerOptionsFlow,
    )

    literals, patterns = _code_mentions()
    fields, selectors = _flow_fields()
    flows = {"config": SmartBoilerConfigFlow, "options": SmartBoilerOptionsFlow}
    unused: list[str] = []
    for key in flatten(texts):
        parts = key.split(".")
        section = parts[0]
        if section in flows and parts[1] == "step":
            step, part = parts[2], parts[3]
            no_step = not hasattr(flows[section], f"async_step_{step}")
            no_field = part in ("data", "data_description") and parts[4] not in fields.get(step, ())
            no_menu = part == "menu_options" and not _mentioned(parts[4], literals, patterns)
            if no_step or no_field or no_menu:
                unused.append(key)
        elif section in flows:
            if not _mentioned(parts[2], literals, patterns):
                unused.append(key)  # an error or abort reason the code never gives
        elif section == "selector":
            if parts[3] not in selectors.get(parts[1], set()):
                unused.append(key)  # a choice no form offers
        elif section == "entity":
            codes = [parts[2]] + [
                p for p in parts[3:] if p not in ("name", "state", "state_attributes")
            ]
            if not all(_mentioned(code, literals, patterns) for code in codes):
                unused.append(key)
        elif section in ("exceptions", "issues", "device"):
            if not _mentioned(parts[1], literals, patterns):
                unused.append(key)
        else:
            unused.append(key)
    return unused


def test_every_key_is_used() -> None:
    """P-76: the reverse key parity — every text in the English source is one the code can
    show: a step and field of a form built at both levels, a selector's choice a form offers, an
    entity, attribute or state the code names, an error, exception or issue the code raises. A
    text left behind by removed code (the ``frequent_starts`` reaction's, say) fails here."""
    assert _unused_keys(SOURCE) == []


def test_an_unused_key_is_found() -> None:
    """P-76's negative: a text the code cannot show — a field no form has, a selector's choice
    no form offers, an issue, an attribute's state or an error nobody raises — is reported."""
    import copy

    texts = copy.deepcopy(SOURCE)
    texts["options"]["step"]["control_alarms"]["data"]["frequent_starts"] = "Frequent starts"
    texts["options"]["step"]["no_such_step"] = {"title": "Nowhere"}
    texts["selector"]["level"]["options"]["expert"] = "Expert"
    texts["issues"]["never_raised_issue"] = {"title": "Never"}
    texts["entity"]["sensor"]["verdict"]["state_attributes"]["reasons"]["state"]["xyzzy"] = "X"
    texts["options"]["error"]["never_given_error"] = "Never"
    assert sorted(_unused_keys(texts)) == [
        "entity.sensor.verdict.state_attributes.reasons.state.xyzzy",
        "issues.never_raised_issue.title",
        "options.error.never_given_error",
        "options.step.control_alarms.data.frequent_starts",
        "options.step.no_such_step.title",
        "selector.level.options.expert",
    ]


ALL_LANGUAGES = ("en.json", *LANGUAGES)


def _texts(language: str) -> dict:
    return json.loads((TRANSLATIONS / language).read_text(encoding="utf-8"))


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_coded_lists_have_translated_text(language: str) -> None:
    """P-39: every code the coded lists carry — control's reasons, blockers and latch, the
    verdict's reasons — has a text under its entity's ``state_attributes.<name>.state``, each
    list with its ``_text`` attribute named, in every language."""
    from custom_components.vtherm_smart_boiler.control import RUNTIME_BLOCKERS, ControlAlarm
    from custom_components.vtherm_smart_boiler.control_config import CONFIG_BLOCKERS
    from custom_components.vtherm_smart_boiler.core.controller import Reason
    from custom_components.vtherm_smart_boiler.core.loop import (
        HEATING_OFF_IGNORED,
        HEATING_ON_IGNORED,
        RELAY_OFF_NOT_TAKEN,
    )
    from custom_components.vtherm_smart_boiler.core.verdict import ReasonCode

    entity = _texts(language)["entity"]
    state = entity["sensor"]["control_state"]
    switch = entity["switch"]["control"]
    verdict = entity["sensor"]["verdict"]
    blockers = {*CONFIG_BLOCKERS, *RUNTIME_BLOCKERS}
    latches = {ControlAlarm.OUTSIDE_CHANGE.value, ControlAlarm.WRITE_IGNORED.value}
    latches |= {HEATING_OFF_IGNORED, HEATING_ON_IGNORED, RELAY_OFF_NOT_TAKEN}
    assert _values(state, "reasons") == {reason.value for reason in Reason}
    assert _values(state, "blockers") == blockers
    assert _values(switch, "blockers") == blockers
    assert _values(state, "latched_by") == latches
    assert _values(verdict, "reasons") == {code.value for code in ReasonCode}
    for owner, attributes in (
        (state, ("reasons", "blockers", "blockers_waiting", "latched_by")),
        (switch, ("blockers", "blocked_by")),
        (verdict, ("reasons",)),
    ):
        for attribute in attributes:
            assert owner["state_attributes"][f"{attribute}_text"]["name"], attribute
    for texts in (state, switch, verdict):
        for attribute in texts["state_attributes"].values():
            assert all(text.strip() for text in attribute.get("state", {}).values())


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_every_feature_and_missing_input_has_a_text(language: str) -> None:
    """The missing-data rule (Y4): the "Features" sensor names every feature, its statuses and
    both its attributes, and every input a feature can lack has a text — a signal by its field's
    label, a dropped signal with the one that kept its entity."""
    from custom_components.vtherm_smart_boiler.core import signal_check
    from custom_components.vtherm_smart_boiler.core.signal_check import Feature, FeatureStatus
    from custom_components.vtherm_smart_boiler.core.signals import Signal

    texts = _texts(language)
    sensor = texts["entity"]["sensor"]["features"]
    assert sensor["name"]
    attributes = sensor["state_attributes"]
    for feature in Feature:
        assert set(attributes[feature.value]["state"]) == {s.value for s in FeatureStatus}
        assert attributes[f"{feature.value}_missing"]["name"]
        assert attributes[f"{feature.value}_missing_text"]["name"]
    inputs = {
        value
        for name, value in vars(signal_check).items()
        if name.isupper() and isinstance(value, str)
    }
    missing = attributes["missing"]["state"]
    # Every signal a feature can lack: all but the modulation and the wired thermostat's room
    # temperature, which no feature needs alone.
    unneeded = {Signal.MODULATION, Signal.ROOM_TEMPERATURE}
    assert inputs | {s.value for s in Signal if s not in unneeded} <= set(missing)
    # Composed by the plugin with the signals' names: no placeholders (hassfest forbids them in
    # an attribute's states).
    assert missing[signal_check.ENTITY_FOR_TWO_SIGNALS]
    assert missing["unavailable_now"]
    fields = texts["options"]["step"]["freshness"]["data"]
    assert missing["flame"] == fields["flame"]  # a signal is named as its field is


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_critical_zone_states_are_translated(language: str) -> None:
    """P-73: the critical zone's own states have their text, and its name the circuit's
    number, as the options show the circuit."""
    from custom_components.vtherm_smart_boiler.core.zones import SelectionStatus

    critical = _texts(language)["entity"]["sensor"]["critical_zone"]
    assert set(critical["state"]) == {s.value for s in SelectionStatus} - {"ok"}
    assert set(PLACEHOLDER.findall(critical["name"])) == {"circuit"}


def test_blocked_switch_messages_count_the_others() -> None:
    """P-74: no raw code in a message — the switch's refusal counts the other blockers, and
    the options' error gives its reason in words."""
    for language in ALL_LANGUAGES:
        exceptions = _texts(language)["exceptions"]
        for key, text in exceptions.items():
            if key.startswith("blocked_"):
                assert set(PLACEHOLDER.findall(text["message"])) == {"count"}, (language, key)
        assert set(PLACEHOLDER.findall(exceptions["invalid_options"]["message"])) == {
            "reason",
            "subject",
        }


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_entity_names_do_not_repeat_the_device(language: str) -> None:
    """P-104: the device is named after the entry ("Boiler" by default); no entity's name
    starts with it again."""
    names = [
        texts["name"]
        for platform in _texts(language)["entity"].values()
        for texts in platform.values()
    ]
    assert not [name for name in names if name.split()[0].lower() in ("boiler", "kocioł")]
    entity = _texts(language)["entity"]
    assert entity["binary_sensor"]["connection"]["name"] in ("Signals", "Sygnały")
    assert entity["switch"]["control"]["name"] in (
        "Control (experimental)",
        "Sterowanie (eksperymentalne)",
    )


def test_y4_texts_are_translated() -> None:
    """Y4: the room for correction says the correction's real bound (P-66); every freshness
    field has its own description (P-103); the resumes given up have their issue, naming the
    zones, and the control state its attribute; the verdict's low condensing through a relay
    says why it is not changed — in every language."""
    from custom_components.vtherm_smart_boiler.control import LEARNING_NOT_RESUMED_ISSUE
    from custom_components.vtherm_smart_boiler.core.controller import CORRECTION_MAX_K

    band = SOURCE["options"]["step"]["control_curve"]["data_description"]["ceiling_band"]
    assert f"stops at {CORRECTION_MAX_K:g} K" in band
    assert "10 K" in band
    for language in ALL_LANGUAGES:
        texts = _texts(language)
        freshness = texts["options"]["step"]["freshness"]
        assert set(freshness["data_description"]) == set(freshness["data"]), language
        issue = texts["issues"][LEARNING_NOT_RESUMED_ISSUE]
        assert issue["title"], language
        assert set(PLACEHOLDER.findall(issue["description"])) == {"zones"}, language
        state = texts["entity"]["sensor"]["control_state"]["state_attributes"]
        assert state["learning_not_resumed"]["name"], language
    detail = SOURCE["entity"]["sensor"]["verdict"]["state_attributes"]["detail"]["state"]
    assert "does not set the water temperature" in detail["water_not_controlled"]
    assert "anti-cycling" not in detail["water_not_controlled"]


def test_the_unknown_relay_timer_says_what_it_costs() -> None:
    """Z4-02: the relay timer's "I don't know" says that a switch-off after the repeat interval
    counts like an unreported restart, the fourth in a day stepping aside, and to declare the
    timer's length."""
    timer = SOURCE["options"]["step"]["control_relay"]["data_description"]["relay_off_timer"]
    assert "the fourth within a day makes the plugin step aside" in timer
    assert "declare its length" in timer


def test_the_read_back_waiting_issue_is_translated() -> None:
    """Z4-10: the repair issue of control waiting for the gateway's read-back, with a title and
    a text and no placeholder, in every language."""
    from custom_components.vtherm_smart_boiler.control import READ_BACK_WAIT_ISSUE

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][READ_BACK_WAIT_ISSUE]
        assert issue["title"], language
        assert issue["description"], language
        assert PLACEHOLDER.findall(issue["description"]) == [], language


def test_the_control_store_issue_is_translated() -> None:
    """PB-16: the repair issue of a control store that cannot be written, with a title and a
    text in every language, its one placeholder the minutes of the hold (M1 of the part-1
    check); it says that control does not take the boiler meanwhile, that the plugin saves
    again every minute and that control resumes by itself once saving has worked that long."""
    from custom_components.vtherm_smart_boiler.control import STORE_NOT_SAVED

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][STORE_NOT_SAVED]
        assert issue["title"], language
        assert issue["description"], language
        assert PLACEHOLDER.findall(issue["description"]) == ["minutes"], language
    text = SOURCE["issues"][STORE_NOT_SAVED]["description"]
    assert "control does not take the boiler" in text
    assert "every minute" in text
    assert "resumes on its own once saving has worked for {minutes} minutes" in text


def test_the_ignored_command_without_heat_issue_is_translated() -> None:
    """Z4-11: the repair issue of a command ignored from the start with nothing else heating the
    house, with a title and a text and no placeholder, in every language. It says the command is
    tried again at the next session, not at the next take (Z4R-06): "ignored from the start"
    lasts through hand-backs inside the session."""
    from custom_components.vtherm_smart_boiler.control import WRITE_IGNORED_ISSUE

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][WRITE_IGNORED_ISSUE]
        assert issue["title"], language
        assert issue["description"], language
        assert PLACEHOLDER.findall(issue["description"]) == [], language
    text = SOURCE["issues"][WRITE_IGNORED_ISSUE]["description"]
    assert "at the next session" in text
    assert "next takes the boiler" not in text


def test_the_relay_timer_seen_issue_is_translated() -> None:
    """Z4R-02: the warning issue asking to declare the relay's own timer, naming the relay and
    the minutes, in every language — read in the relay's own settings, as the time seen may be a
    whole multiple of it; the timer option's "I don't know" says that switch-offs recurring the
    same time after "on" are taken for the relay's own timer."""
    from custom_components.vtherm_smart_boiler.control import RELAY_TIMER_ISSUE

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][RELAY_TIMER_ISSUE]
        assert issue["title"], language
        assert set(PLACEHOLDER.findall(issue["description"])) == {"relay", "minutes"}, language
    issue = SOURCE["issues"][RELAY_TIMER_ISSUE]["description"]
    assert "read its length in the relay's own settings" in issue  # not the number seen
    assert 'a "maximum run time"' in issue  # an automation looks the same (Z4R2-05)
    assert "at least every half of that time" in issue  # the renewal, as for a declared timer
    timer = SOURCE["options"]["step"]["control_relay"]["data_description"]["relay_off_timer"]
    assert "the same time after" in timer


def test_the_short_relay_timer_texts_are_translated() -> None:
    """K4.2 (decided by the user 2026-10-03): the latch issue of a relay that switched itself off
    every few minutes — one per rest state, naming the relay and the minutes — says how often,
    and to set its timer to at least 30 min or switch the timer off; the form's error for a
    declared timer under 10 min; the timer fields say the shortest is 10 min, in every
    language."""
    for language in ALL_LANGUAGES:
        texts = _texts(language)
        for rest in ("off", "on"):
            issue = texts["issues"][f"control_latched_relay_short_timer_{rest}"]
            assert issue["title"], language
            found = set(PLACEHOLDER.findall(issue["description"]))
            assert found == {"relay", "minutes"}, (language, rest)
            assert "30 min" in issue["description"], (language, rest)
        assert "10" in texts["options"]["error"]["relay_off_timer_min_short"], language
        for step in ("control_relay", "control_relay_from_vt"):
            length = texts["options"]["step"][step]["data_description"]["relay_off_timer_min"]
            assert "10–120" in length, (language, step)
    for rest in ("off", "on"):
        text = SOURCE["issues"][f"control_latched_relay_short_timer_{rest}"]["description"]
        assert "switched itself off about every {minutes} min" in text
        assert "at least 30 min, or switch the timer off" in text
    on = SOURCE["issues"]["control_latched_relay_short_timer_on"]["description"]
    assert "switches it off again" in on  # the rest state "on" does not hold
    timer = SOURCE["options"]["step"]["control_relay"]["data_description"]["relay_off_timer"]
    assert "9 min or more (a 10-min timer measured up to a minute short)" in timer  # KD-02


def test_the_relay_not_taking_texts_count_through_command_changes() -> None:
    """L2 of the part-1 check: the run of checks without the plugin's command goes on through
    new commands, so the current one may be younger than the quarter hour: the texts say the
    relay has shown none of the commands for about 15 minutes, and not the current one now."""
    for key, command in (("relay_not_taking", "on"), ("relay_not_taking_off", "off")):
        text = SOURCE["issues"][key]["description"]
        assert "for about 15 minutes — three checks — it has shown none of them" in text
        assert f'it does not show "{command}" now' in text
        assert f'has not shown "{command}" for about' not in text


def test_the_heating_read_back_says_how_soon_it_must_report() -> None:
    """K4.3 (decided by the user 2026-10-03; Z4R3-03): the heating read-back field says to pick an
    entity that reports a change within about a minute — a slower one delays noticing a change,
    one slower than 5 min can make the plugin wrongly step aside — in every language."""
    for language in ALL_LANGUAGES:
        step = _texts(language)["options"]["step"]["control"]
        text = step["data_description"]["ch_confirmed_entity"]
        assert "5 min" in text, language
    text = SOURCE["options"]["step"]["control"]["data_description"]["ch_confirmed_entity"]
    assert "reports a change within about a minute" in text
    assert "a slower one delays noticing a change" in text
    assert "one slower than 5 min can make the plugin wrongly step aside" in text


def test_the_setpoint_not_shown_issue_is_translated() -> None:
    """Z4R2-03: the repair issue of a setpoint the boiler does not show, with a title and a text
    and no placeholder, in every language; it says control goes on without a hand-back."""
    from custom_components.vtherm_smart_boiler.control import NOT_SHOWN_ISSUE

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][NOT_SHOWN_ISSUE]
        assert issue["title"], language
        assert issue["description"], language
        assert PLACEHOLDER.findall(issue["description"]) == [], language
    assert "does not hand the boiler back" in SOURCE["issues"][NOT_SHOWN_ISSUE]["description"]


def test_the_no_sign_the_boiler_heats_issue_is_translated() -> None:
    """Decision 2 of 0.2.3 (SB-01): the warning of a boiler that shows no sign of heating on the
    water paths, in every language, with its minutes; it says what it may mean — a lockout,
    summer mode or heating off on the panel, no gas — what to check, and that control goes on
    without a hand-back. The alarm's name says the same on every path."""
    from custom_components.vtherm_smart_boiler.control import NO_HEAT_SIGN_ISSUE

    for language in ALL_LANGUAGES:
        issue = _texts(language)["issues"][NO_HEAT_SIGN_ISSUE]
        assert issue["title"], language
        assert PLACEHOLDER.findall(issue["description"]) == ["minutes"], language
    text = SOURCE["issues"][NO_HEAT_SIGN_ISSUE]["description"]
    for said in ("locked out", "summer mode", "gas", "does not hand the boiler back"):
        assert said in text, said
    alarm = SOURCE["entity"]["binary_sensor"]["alarm_boiler_not_responding"]["name"]
    assert alarm == "Control: no sign the boiler heats"


def test_the_comfort_correction_says_it_is_on_and_what_it_costs() -> None:
    """G11 B: the comfort correction's description says it is on by default with full control,
    what it costs — more gas, possibly more starts — and the risk with VT's TPI zones: the
    water at its limit while a zone at full duty stays short by TPI's own offset, the burner
    stopped by every zone's cycle, 1.75 to 5 times the starts in the simulation — in the
    behaviour step and in the simple level's curve step, in every language; its limit and the
    "curve too low" issue have their texts."""
    for step in ("control_behaviour", "control_curve"):
        text = SOURCE["options"]["step"][step]["data_description"]["comfort_correction"]
        assert "On (default with full control)" in text, step
        assert "more gas" in text, step
        assert "TPI" in text, step
        assert "1.75" in text, step
        assert "5 times the starts" in text, step
        assert "0.5 K" in text, step  # SmartPI's learning band (G11 C)
        for language in LANGUAGES:
            translated = _texts(language)["options"]["step"][step]["data_description"]
            assert "1,75" in translated["comfort_correction"], (language, step)
    behaviour = SOURCE["options"]["step"]["control_behaviour"]["data_description"]
    assert "3 K a day" in behaviour["comfort_correction_max_k"]
    for key in ("curve_too_low", "room_short_at_limit"):  # additions 2 and 3: the causes
        issue = SOURCE["issues"][key]
        assert set(PLACEHOLDER.findall(issue["title"] + issue["description"])) == {
            "zones",
            "limit",
        }, key
        assert "radiator" in issue["description"], key
        assert "heat" in issue["description"], key
        assert "does not climb further" in issue["description"], key


def test_sb10_texts_are_translated() -> None:
    """SB-10 (decision 12): a failed setup's issue, the house known or only possibly unheated —
    every report the rule gives has its text, without placeholders, and says what to do."""
    from custom_components.vtherm_smart_boiler.control_config import FailedSetupReport

    for report in FailedSetupReport:
        issue = SOURCE["issues"][report.value]
        assert issue["title"], report
        assert issue["description"], report
        assert "{" not in issue["title"] + issue["description"], report
        assert "reload the entry" in issue["description"], report


# Step 3.1's specification points that are texts: each option description named here says it,
# wherever the option is asked (``data_description``), and the issue is worded as settled.
SAID: list[tuple[str, str, str]] = [
    ("SB-12", "design_flow", "SmartPI (0.4.0) learns its own outdoor term"),
    ("SB-35", "max_flow", "own maximum is the only one"),
    ("SB-35", "topology", "own maximum, not the plugin's"),
    ("SB-35", "hand_back", "own maximum is the only one"),
    ("SB-35", "hard_max", "own maximum holds"),
    ("SB-37", "setpoint_entity", "the water would not follow the curve"),
    ("SB-37", "hand_back_value_effect", "leaves the house unheated"),
    ("SB-37", "gateway_id", "another one would get the plugin's commands"),
    ("SB-37", "hard_max", "too low: rooms stay cold"),
    ("SB-37", "boiler_heats_above_w", "Too low:"),
    ("SB-38", "relay_is_separate_contact", "for a boiler thermostat entity"),
]


@pytest.mark.parametrize(("point", "key", "phrase"), SAID, ids=[f"{p}-{k}" for p, k, _ in SAID])
def test_the_settled_texts_say_it(point: str, key: str, phrase: str) -> None:
    found = {
        path: text
        for path, text in flatten(SOURCE).items()
        if ".data_description." in f".{path}" and path.endswith(f".{key}")
    }
    assert found, (point, key)
    assert all(phrase in text for text in found.values()), (point, key)


def test_the_unreadable_notice_does_not_claim_the_hand_back() -> None:
    """SB-39: the notice goes once its hand-back is confirmed, so it never says it was made."""
    text = SOURCE["issues"]["control_state_unreadable"]["description"]
    assert "handed it back" not in text
    assert "goes once the boiler shows that hand-back" in text


def test_the_auto_tpi_advice_names_what_clearing_the_flag_costs() -> None:
    """PB-74: clearing VT's "used by the central boiler" also removes VT's own guard — Auto-TPI
    then learns while zones call and the boiler does not heat; the issue says so."""
    text = SOURCE["issues"]["auto_tpi_blocked"]["description"]
    assert "the boiler does not heat" in text
    assert "activation delay" in text
    assert "monitoring period" in text


# PB-82: attributes the plugin keeps in °C whatever unit Home Assistant shows (its states are
# converted, its attributes are not) — each names the unit.
CELSIUS_ATTRIBUTES = (
    ("sensor", "control_setpoint", "requested"),
    ("sensor", "control_setpoint", "read_back"),
    ("sensor", "control_state", "target"),
    ("sensor", "reference_room", "temperature"),
    ("sensor", "reference_room", "setpoint"),
    ("sensor", "lowest_water_suggestion", "reference"),
    ("sensor", "lowest_water_suggestion", "estimate_from_power"),
    ("binary_sensor", "alarm_flue_gas_high", "limit"),
    ("binary_sensor", "alarm_circuit_too_hot", "limit"),
    ("switch", "control", "wall_thermostat_setpoint"),
)


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_temperature_attributes_name_their_unit(language: str) -> None:
    entities = _texts(language)["entity"]
    for platform, key, attribute in CELSIUS_ATTRIBUTES:
        name = entities[platform][key]["state_attributes"][attribute]["name"]
        assert "°C" in name, (language, key, attribute)


# PB-78: the coded lists joined with ", " into one text (``coded_text``, the verdict's reasons
# with their details): a text with a comma of its own would read as two items.
JOINED_LISTS = (
    ("sensor", "features", "missing"),
    ("sensor", "control_state", "reasons"),
    ("sensor", "control_state", "blockers"),
    ("sensor", "control_state", "latched_by"),
    ("sensor", "verdict", "reasons"),
    ("sensor", "verdict", "detail"),
    ("sensor", "verdict", "changed_by_control"),
    ("sensor", "lowest_water_suggestion", "missing"),
    ("switch", "control", "blockers"),
    ("switch", "control", "blocked_by"),
    ("binary_sensor", "connection", "problems"),
    ("binary_sensor", "alarm_demand_criterion_no_data", "criteria"),
)


@pytest.mark.parametrize("language", ALL_LANGUAGES)
def test_joined_list_texts_have_no_comma(language: str) -> None:
    entities = _texts(language)["entity"]
    found = [
        (key, attribute, code)
        for platform, key, attribute in JOINED_LISTS
        for code, text in entities[platform][key]["state_attributes"][attribute]["state"].items()
        if "," in text
    ]
    assert found == [], language
