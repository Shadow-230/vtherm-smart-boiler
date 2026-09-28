"""Every default of ``SCOPE.md`` §7's table "Defaults of the safety options and why" (P-127), as Q1
left it, pinned where the plugin holds it: ``CONTROL_DEFAULTS`` and ``CURVE_DEFAULTS`` (which the
parser and the options forms both read), the alarm bands, the forms' own defaults — the monitor
schema among them — and what the parser applies to a control section that stores nothing.

Each row names its SCOPE row. A default changed in the code without the table, or in the table
without the code, fails here; the user reviews the provisional ones at K4.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import voluptuous as vol

from custom_components.vtherm_smart_boiler import config_flow
from custom_components.vtherm_smart_boiler.config import EntryConfig
from custom_components.vtherm_smart_boiler.control_config import (
    ALWAYS_HAND_BACK_ALARMS,
    CONTROL_DEFAULTS,
    CURVE_DEFAULTS,
    OPTIONAL_HAND_BACK_ALARMS,
    RELAY_DEFAULTS,
    ControlOptions,
    HandBack,
    RelayOptions,
    WritePath,
    config_blockers,
    parse_control,
)
from custom_components.vtherm_smart_boiler.core.alarms import (
    CIRCUIT_ALARM_MIN,
    CIRCUIT_ALARM_RISE_K,
)
from custom_components.vtherm_smart_boiler.core.controller import (
    CORRECTION_MAX_K,
    fallback_setpoint,
)
from custom_components.vtherm_smart_boiler.core.curve import DEFAULT_HOLD_S
from custom_components.vtherm_smart_boiler.core.guards import WriteType
from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    CircuitControl,
    DhwType,
    Installation,
    Zone,
)
from custom_components.vtherm_smart_boiler.core.relay import (
    REPEAT_DEFAULT_S,
    REPEAT_MAX_S,
    REPEAT_MIN_S,
    RelayConfig,
    RelayPowerOn,
    RelayReports,
    RelayRest,
    RelayTimer,
)
from custom_components.vtherm_smart_boiler.core.signals import Signal
from custom_components.vtherm_smart_boiler.transport.writers import OTGW_MIN_SETPOINT

HOUR = 3600.0
INSTALLATION = Installation(
    boiler=Boiler(BoilerClass.FLOW_SETPOINT, DhwType.COMBI),
    circuits=(Circuit("main", CircuitControl.UNMIXED_SHARED),),
    zones=(Zone("climate.a", "main"),),
)
ON_OFF = Installation(
    boiler=Boiler(BoilerClass.ON_OFF, DhwType.COMBI),
    circuits=INSTALLATION.circuits,
    zones=INSTALLATION.zones,
)
# A control section that stores nothing but its path: what the parser applies by itself.
BARE = parse_control({"write_path": WritePath.OPENTHERM_GW.value}, INSTALLATION, None)
BARE_ENTITY = parse_control({"write_path": WritePath.ENTITY.value}, INSTALLATION, None)
BARE_RELAY = parse_control({"write_path": WritePath.RELAY.value}, ON_OFF, None)
MINIMAL_OPTIONS: dict[str, Any] = {
    "signals": {Signal.FLAME.value: "binary_sensor.flame", Signal.FLOW.value: "sensor.flow"},
    "zones": [{"entity_id": "climate.a"}],
}


def form_defaults(schema: vol.Schema) -> dict[str, Any]:
    """What a form offers before the user types anything (``vol.UNDEFINED``: no default)."""
    found: dict[str, Any] = {}
    for key in schema.schema:
        if isinstance(key, vol.Required | vol.Optional):
            found[str(key)] = key.default() if callable(key.default) else vol.UNDEFINED
    return found


ADVANCED = {"level": "advanced"}
CURVE_FORM = form_defaults(config_flow.control_curve_schema(ADVANCED))
MONITOR_FORM = form_defaults(config_flow.monitor_schema({}))
ENTITY_FORM = form_defaults(config_flow.control_entity_schema({}))
# The tick is offered on the entity path with the virtual topology (answers F, M).
OWN_CONTROL_FORM = form_defaults(
    config_flow.control_entity_schema({"control": {"write_path": "entity", "topology": "virtual"}})
)
RELAY_FORM = form_defaults(config_flow.control_relay_schema({}))
ZONE_FORM = form_defaults(config_flow.zone_schema({}, {}))
BEHAVIOUR_FORM = form_defaults(config_flow.control_behaviour_schema(ADVANCED))
CONFIG = EntryConfig.from_options(MINIMAL_OPTIONS)

# (the SCOPE §7 row, what the plugin holds, the table's value)
ROWS: list[tuple[str, Callable[[], Any], Any]] = [
    # Control | off; available after 7 days of monitoring. The control switch's own start, off,
    # is Home Assistant's to show: tests/integration/test_control.py pins it
    # (test_control_is_off_by_default, test_control_is_refused_during_monitoring).
    ("control: not configured, nothing to switch on", lambda: ControlOptions().configured, False),
    ("control: 7 days of monitoring (form)", lambda: MONITOR_FORM["monitoring_days"], 7.0),
    ("control: 7 days of monitoring (parser)", lambda: CONFIG.monitor.monitoring_days, 7.0),
    # Heating curve | none — the design flow is entered
    ("heating curve: no design flow offered", lambda: CURVE_FORM["design_flow"], vol.UNDEFINED),
    ("heating curve: none stored, none entered", lambda: BARE.curve_entered, False),
    ("heating curve: none stored blocks control", lambda: "curve_not_entered" in _bare(), True),
    ("heating curve: the form's design outdoor", lambda: CURVE_DEFAULTS["design_outdoor"], -15.0),
    ("heating curve: the form's room", lambda: CURVE_DEFAULTS["room"], 20.0),
    ("heating curve: the form's offset", lambda: CURVE_DEFAULTS["offset"], 0.0),
    # Emitter type | none — the user chooses
    ("emitter type: none offered", lambda: ZONE_FORM["emitter"], vol.UNDEFINED),
    # Lowest / highest water temperature | 20 °C (provisional, K4) / 70 °C
    ("lowest water temperature", lambda: CONTROL_DEFAULTS["hard_min"], 20.0),
    ("lowest water temperature (form)", lambda: CURVE_FORM["hard_min"], 20.0),
    ("lowest water temperature (parser)", lambda: BARE.loop.control.limits.hard_min, 20.0),
    ("highest water temperature", lambda: CONTROL_DEFAULTS["hard_max"], 70.0),
    ("highest water temperature (form)", lambda: CURVE_FORM["hard_max"], 70.0),
    ("highest water temperature (parser)", lambda: BARE.loop.control.limits.hard_max, 70.0),
    # Weather ceiling | the curve + 10 K
    ("weather ceiling", lambda: CONTROL_DEFAULTS["ceiling_band"], 10.0),
    ("weather ceiling (form)", lambda: CURVE_FORM["ceiling_band"], 10.0),
    ("weather ceiling (parser)", lambda: BARE.loop.control.limits.ceiling_band, 10.0),
    # Ramp | 1 K per minute
    ("ramp", lambda: CONTROL_DEFAULTS["ramp_k_per_min"], 1.0),
    ("ramp (form)", lambda: BEHAVIOUR_FORM["ramp_k_per_min"], 1.0),
    ("ramp (parser)", lambda: BARE.loop.control.ramp_k_per_min, 1.0),
    # Decision interval | 5 min
    ("decision interval", lambda: CONTROL_DEFAULTS["decision_interval_min"], 5.0),
    ("decision interval (form)", lambda: BEHAVIOUR_FORM["decision_interval_min"], 5.0),
    ("decision interval (parser)", lambda: BARE.loop.control.decision_interval_s, 300.0),
    # Activation delay | 0 s
    ("activation delay", lambda: CONTROL_DEFAULTS["activation_delay_s"], 0),
    ("activation delay (form)", lambda: CURVE_FORM["activation_delay_s"], 0),
    ("activation delay (parser)", lambda: BARE.loop.control.activation_delay_s, 0.0),
    # Write type of a picked target | unknown — control stays off until declared
    ("write type (form)", lambda: ENTITY_FORM["write_type"], WriteType.UNKNOWN.value),
    ("write type (parser)", lambda: BARE_ENTITY.write_type, WriteType.UNKNOWN),
    (
        "write type: unknown blocks control",
        lambda: "write_type_not_supported" in _bare(WritePath.ENTITY),
        True,
    ),
    # "Off" setpoint | 10 °C — only where "off" sends one with the heating switch (OTGW CS,
    # never below 8 °C)
    ('"off" setpoint', lambda: CONTROL_DEFAULTS["off_setpoint"], 10.0),
    ('"off" setpoint (parser)', lambda: BARE.loop.off_setpoint, 10.0),
    ('"off" setpoint: never below 8 °C on the gateway', lambda: OTGW_MIN_SETPOINT, 8.0),
    # Hand-back value (entity) | none — entered with its effect
    ("hand-back value (form)", lambda: ENTITY_FORM["hand_back_value"], vol.UNDEFINED),
    (
        "hand-back value's effect (form)",
        lambda: ENTITY_FORM["hand_back_value_effect"],
        vol.UNDEFINED,
    ),
    ("hand-back method (form)", lambda: ENTITY_FORM["hand_back"], vol.UNDEFINED),
    (
        "hand-back (parser)",
        lambda: (BARE_ENTITY.hand_back, BARE_ENTITY.hand_back_value),
        (None, None),
    ),
    ("hand-back: none blocks control", lambda: "no_hand_back" in _bare(WritePath.ENTITY), True),
    # Fallback setpoint | the last effective outdoor temperature for 3 h, then the design flow,
    # or the user's fixed value (decision 9)
    ("fallback: the last outdoor temperature's hold", lambda: DEFAULT_HOLD_S, 3 * HOUR),
    ("fallback: the hold (parser)", lambda: BARE.loop.control.outdoor_hold_s, 3 * HOUR),
    ("fallback: no fixed value (parser)", lambda: BARE.loop.control.fallback_setpoint, None),
    ("fallback: no fixed value (form)", lambda: CURVE_FORM["fallback_setpoint"], vol.UNDEFINED),
    (
        "fallback: then the design flow",
        lambda: fallback_setpoint(BARE.loop.control),
        BARE.loop.control.curve.flow(BARE.loop.control.curve.design_outdoor),
    ),
    # Frost limit / release | 5 / 7 °C
    ("frost limit", lambda: CONTROL_DEFAULTS["frost_limit"], 5.0),
    ("frost limit (form)", lambda: CURVE_FORM["frost_limit"], 5.0),
    ("frost limit (parser)", lambda: BARE.loop.control.frost.room_limit, 5.0),
    ("frost release", lambda: CONTROL_DEFAULTS["frost_release"], 7.0),
    ("frost release (form)", lambda: CURVE_FORM["frost_release"], 7.0),
    ("frost release (parser)", lambda: BARE.loop.control.frost.release, 7.0),
    # Frost protection | every zone, heated only where its emitter can take heat
    ("frost protection: every zone (parser)", lambda: BARE.loop.control.frost.zone, None),
    ("frost protection: every zone (form)", lambda: CURVE_FORM["frost_zone"], vol.UNDEFINED),
    (
        'frost protection: no zone "closes when off"',
        lambda: BARE.loop.control.frost.closes_when_off,
        frozenset(),
    ),
    (
        'frost protection: "closes when off" unticked (form)',
        lambda: ZONE_FORM["closes_when_off"],
        False,
    ),
    # Demand threshold | one zone calling
    ("demand threshold", lambda: CONTROL_DEFAULTS["count_threshold"], 1),
    ("demand threshold (form)", lambda: BEHAVIOUR_FORM["count_threshold"], 1),
    (
        "demand threshold (parser)",
        lambda: _demand(BARE),
        (1, None, None),
    ),
    # Comfort correction | on, up to +3 K
    ("comfort correction", lambda: CONTROL_DEFAULTS["comfort_correction"], True),
    ("comfort correction (form)", lambda: BEHAVIOUR_FORM["comfort_correction"], True),
    ("comfort correction (parser)", lambda: BARE.loop.control.comfort_correction, True),
    ("comfort correction: its bound", lambda: CORRECTION_MAX_K, 3.0),
    # Learning pauses | on
    ("learning pauses", lambda: CONTROL_DEFAULTS["learning_pauses"], True),
    ("learning pauses (form)", lambda: BEHAVIOUR_FORM["learning_pauses"], True),
    ("learning pauses (parser)", lambda: BARE.learning_pauses, True),
    # Alarm reaction | information; the hand-backs of decision 7 always
    ("alarm reaction: information (parser)", lambda: dict(BARE.alarm_reactions), {}),
    (
        "alarm reaction: decision 7's hand-backs, always",
        lambda: ALWAYS_HAND_BACK_ALARMS,
        frozenset(
            {
                "control_error",
                "boiler_link_lost",
                "outside_change",
                "monitor_failed",
                "heating_off_ignored",
            }
        ),
    ),
    (
        "alarm reaction: the one optional",
        lambda: OPTIONAL_HAND_BACK_ALARMS,
        frozenset({"write_ignored"}),
    ),
    # Circuit-maximum alarm | the circuit's maximum + 5 K, for 10 min (information)
    ("circuit-maximum alarm: + 5 K", lambda: CIRCUIT_ALARM_RISE_K, 5.0),
    ("circuit-maximum alarm: 10 min", lambda: CIRCUIT_ALARM_MIN, 10.0),
    # "Add water" threshold | none
    ('"add water" threshold (form)', lambda: MONITOR_FORM["add_water_below"], vol.UNDEFINED),
    ('"add water" threshold (parser)', lambda: CONFIG.monitor.alarms.add_water_below, None),
    # Boiler-fault signals | none
    (
        "boiler-fault signals",
        lambda: {Signal.LOW_PRESSURE_FAULT, Signal.FAULT_INDICATION} & set(CONFIG.signals),
        set(),
    ),
    # Thermostat terminals (gateway) | none — required; "I don't know" blocks control
    ("thermostat terminals (parser)", lambda: BARE.thermostat_kind, None),
    (
        "thermostat terminals: none blocks control",
        lambda: "thermostat_kind_unknown" in _gateway_blockers(),
        True,
    ),
    (
        'thermostat terminals: "I don\'t know" blocks control',
        lambda: "thermostat_kind_unknown" in _gateway_blockers(thermostat_kind="unknown"),
        True,
    ),
    # "The boiler has its own room controller" | not ticked
    ("own room controller", lambda: CONTROL_DEFAULTS["own_room_controller"], False),
    ("own room controller (form)", lambda: OWN_CONTROL_FORM["own_room_controller"], False),
    ("own room controller (parser)", lambda: BARE_ENTITY.own_room_controller, False),
    # Relay rest state | off
    ("relay rest state", lambda: RELAY_DEFAULTS["relay_rest_state"], RelayRest.OFF.value),
    ("relay rest state (form)", lambda: RELAY_FORM["relay_rest_state"], RelayRest.OFF.value),
    ("relay rest state (parser)", lambda: BARE_RELAY.relay.rest, RelayRest.OFF),
    # Relay settings | "I don't know" — its state report treated as "no"
    ("relay reports its state (form)", lambda: RELAY_FORM["relay_reports_state"], "unknown"),
    ("relay state after a power cut (form)", lambda: RELAY_FORM["relay_power_on_state"], "unknown"),
    ("relay switch-off timer (form)", lambda: RELAY_FORM["relay_off_timer"], "unknown"),
    (
        "relay settings (parser)",
        lambda: (BARE_RELAY.relay.reports, BARE_RELAY.relay.power_on, BARE_RELAY.relay.timer),
        (RelayReports.UNKNOWN, RelayPowerOn.UNKNOWN, RelayTimer.UNKNOWN),
    ),
    ('relay: "I don\'t know" reports as "no"', lambda: RelayConfig().reports_state, False),
    (
        'relay: "I don\'t know" is "maybe on" after a power cut',
        lambda: RelayConfig().power_cut_state,
        None,
    ),
    ('relay: "I don\'t know" may have a timer', lambda: RelayConfig().renew_s, REPEAT_DEFAULT_S),
    # Relay repeat interval | 300 s (10–300 s)
    ("relay repeat interval", lambda: REPEAT_DEFAULT_S, 300.0),
    ("relay repeat interval's range", lambda: (REPEAT_MIN_S, REPEAT_MAX_S), (10.0, 300.0)),
    ("relay repeat interval (parser)", lambda: BARE_RELAY.relay.repeat_s, 300.0),
    ("relay repeat interval (options)", lambda: RelayOptions().repeat_s, 300.0),
    # Relay "separate contact" tick | not ticked — control does not start without it
    ('relay "separate contact"', lambda: RELAY_DEFAULTS["relay_is_separate_contact"], False),
    ('relay "separate contact" (form)', lambda: RELAY_FORM["relay_is_separate_contact"], False),
    ('relay "separate contact" (parser)', lambda: BARE_RELAY.relay.separate_contact, False),
    (
        'relay "separate contact": unticked blocks control',
        lambda: "relay_contact_not_confirmed" in _bare(WritePath.RELAY),
        True,
    ),
    # Return by itself after another controller | off
    ("return by itself (parser)", lambda: BARE.return_after_outside_change, False),
    # Freshness age limit | none — availability only
    (
        "freshness age limit",
        lambda: {signal: CONFIG.freshness.get(signal) for signal in CONFIG.signals},
        {Signal.FLAME: None, Signal.FLOW: None},
    ),
    ("freshness age limit: the weather", lambda: CONFIG.weather_max_age_s, None),
]


def _bare(path: WritePath = WritePath.OPENTHERM_GW) -> list[str]:
    """The blockers of a control section that stores nothing but its path."""
    control = {
        WritePath.OPENTHERM_GW: BARE,
        WritePath.ENTITY: BARE_ENTITY,
        WritePath.RELAY: BARE_RELAY,
    }
    installation = ON_OFF if path is WritePath.RELAY else INSTALLATION
    return config_blockers(control[path], installation, signals=(Signal.FLAME, Signal.FLOW))


def _gateway_blockers(**stored: Any) -> list[str]:
    """The blockers of a gateway section with its topology and nothing more (decision 1)."""
    section = {"write_path": WritePath.OPENTHERM_GW.value, "topology": "gateway_with_thermostat"}
    control = parse_control(section | stored, INSTALLATION, None)
    return config_blockers(control, INSTALLATION, signals=(Signal.FLAME, Signal.FLOW))


def _demand(control: ControlOptions) -> tuple[int, float | None, float | None]:
    demand = control.loop.control.demand
    return demand.count_threshold, demand.power_threshold_kw, demand.opening_threshold


@pytest.mark.parametrize(("row", "read", "expected"), ROWS, ids=[row for row, _, _ in ROWS])
def test_every_default_of_the_scope_table(row: str, read: Callable[[], Any], expected: Any) -> None:
    assert read() == expected, row


def test_the_bare_sections_parse_to_their_paths() -> None:
    """The table reads what a section storing nothing but its path gives: the parser takes
    those paths, and hands back nothing else by itself."""
    assert (BARE.write_path, BARE_ENTITY.write_path, BARE_RELAY.write_path) == (
        WritePath.OPENTHERM_GW,
        WritePath.ENTITY,
        WritePath.RELAY,
    )
    assert BARE_ENTITY.hand_back is not HandBack.TIMEOUT
