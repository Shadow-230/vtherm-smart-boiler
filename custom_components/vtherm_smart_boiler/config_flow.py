"""Config flow and options flow.

The level (simple or advanced) changes which fields are shown, never how the plugin behaves:
a field that is not shown keeps its cautious default. Every step reads and writes one part of
the options dictionary that ``config.EntryConfig`` interprets.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .config import ConfigError, EntryConfig
from .const import (
    BOILER,
    BUILDING,
    CIRCUITS,
    CONTROL,
    DOMAIN,
    FRESHNESS,
    LEVEL,
    LEVEL_ADVANCED,
    LEVEL_SIMPLE,
    MONITOR,
    PARAMETERS,
    REFERENCE_ROOM,
    SIGNALS,
    STORAGE_VERSION,
    VT_DOMAIN,
    WEATHER,
    ZONES,
    owes_hand_back,
)
from .control_config import (
    CONTROL_DEFAULTS,
    CURVE_DEFAULTS,
    DEFAULT_REACTIONS,
    INFO_ONLY_ALARMS,
    OTGW_PATHS,
    AlarmReaction,
    HandBack,
    Topology,
    ValueEffect,
    WritePath,
)
from .core.alarms import (
    DEFAULT_FREQUENT_STARTS_PER_HOUR,
    DEFAULT_UNSTABLE_BURNS_PER_DAY,
    FLUE_GAS_CONDENSING_BAND,
    PRESSURE_HIGH_BAND,
    PRESSURE_LOW_BAND,
    AlarmKind,
)
from .core.building import InsulationClass, ThermalMass
from .core.foreign_heat import SourceKind
from .core.guards import WriteType
from .core.installation import BoilerClass, CircuitControl, DhwType, EmitterType
from .core.metrics import ModulationScale
from .core.reference_room import Strategy
from .transport.entities import read_bounds, temperature_unit_of
from .vtherm_link import zone_name

# --- field definitions ----------------------------------------------------------------------

_BINARY = {"domain": "binary_sensor"}
_TEMPERATURE = {"domain": "sensor", "device_class": "temperature"}

# signal -> (entity filter, shown at the simple level)
SIGNAL_FIELDS: dict[str, tuple[dict[str, Any], bool]] = {
    "flame": (_BINARY, True),
    "flow": (_TEMPERATURE, True),
    "return": (_TEMPERATURE, True),
    "modulation": ({"domain": "sensor"}, True),  # in %: no device class, checked on submit
    "dhw_active": (_BINARY, True),
    "pressure": ({"domain": "sensor", "device_class": "pressure"}, True),
    "outdoor": (_TEMPERATURE, True),
    "ch_setpoint": ({"domain": ["sensor", "number"], "device_class": "temperature"}, False),
    "ch_active": (_BINARY, False),
    "pump_running": (_BINARY, False),
    "flue_gas": (_TEMPERATURE, False),
    "gas_meter": ({"domain": "sensor", "device_class": ["gas", "energy"]}, False),
    "room_setpoint": (_TEMPERATURE, False),
    "room_temperature": (_TEMPERATURE, False),
}
REQUIRED_FIELDS = ("flame", "flow")


def _entity(
    filter_: dict[str, Any] | list[dict[str, Any]], multiple: bool = False
) -> selector.EntitySelector:
    filters = filter_ if isinstance(filter_, list) else [filter_]
    return selector.EntitySelector(
        selector.EntitySelectorConfig(filter=filters, multiple=multiple)  # type: ignore[typeddict-item]
    )


def _select(key: str, options: list[str]) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(
            options=options, translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN
        )
    )


def _number(
    low: float, high: float, step: float, unit: str | None = None
) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(
        min=low, max=high, step=step, mode=selector.NumberSelectorMode.BOX
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _optional(key: str, current: dict[str, Any]) -> vol.Optional:
    value = current.get(key)
    return vol.Optional(key, description={"suggested_value": value} if value is not None else None)


def _advanced(options: dict[str, Any]) -> bool:
    return options.get(LEVEL) == LEVEL_ADVANCED


# --- schemas ----------------------------------------------------------------------------------


def user_schema(current: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=current.get("name", "Boiler")): str,
            vol.Required(LEVEL, default=current.get(LEVEL, LEVEL_SIMPLE)): _select(
                "level", [LEVEL_SIMPLE, LEVEL_ADVANCED]
            ),
        }
    )


def level_schema(options: dict[str, Any]) -> vol.Schema:
    """The level of detail; switching to simple may restore the advanced defaults."""
    return vol.Schema(
        {
            vol.Required(LEVEL, default=options.get(LEVEL, LEVEL_SIMPLE)): _select(
                "level", [LEVEL_SIMPLE, LEVEL_ADVANCED]
            ),
            vol.Required("restore_defaults", default=False): selector.BooleanSelector(),
        }
    )


def signals_schema(options: dict[str, Any]) -> vol.Schema:
    current = {**options.get(SIGNALS, {}), WEATHER: options.get(WEATHER)}
    fields: dict[Any, Any] = {}
    for key, (filter_, simple) in SIGNAL_FIELDS.items():
        if not simple and not _advanced(options):
            continue
        marker = (
            vol.Required(key, default=current[key])
            if key in REQUIRED_FIELDS and current.get(key)
            else vol.Required(key)
            if key in REQUIRED_FIELDS
            else _optional(key, current)
        )
        fields[marker] = _entity(filter_)
    fields[_optional(WEATHER, current)] = _entity({"domain": "weather"})
    return vol.Schema(fields)


def freshness_schema(options: dict[str, Any]) -> vol.Schema:
    """An optional age limit, in minutes, for each mapped signal."""
    limits = {k: v / 60.0 for k, v in options.get(FRESHNESS, {}).items() if v is not None}
    return vol.Schema(
        {_optional(key, limits): _number(1, 1440, 1, "min") for key in options.get(SIGNALS, {})}
    )


def apply_freshness(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    options[FRESHNESS] = {
        key: float(value) * 60.0
        for key, value in user_input.items()
        if key in options.get(SIGNALS, {}) and value not in (None, "")
    }


def boiler_schema(options: dict[str, Any]) -> vol.Schema:
    boiler = options.get(BOILER, {})
    params = options.get(PARAMETERS, {})
    current = {**boiler, **params}
    fields: dict[Any, Any] = {
        vol.Required("class", default=boiler.get("class", BoilerClass.READ_ONLY.value)): _select(
            "boiler_class", [c.value for c in BoilerClass]
        ),
        # No default: "none" makes every burn heating, a wrong guess on a combi boiler.
        vol.Required("dhw", default=boiler.get("dhw", vol.UNDEFINED)): _select(
            "dhw_type", [d.value for d in DhwType]
        ),
        vol.Required(
            "condensing", default=boiler.get("condensing", True)
        ): selector.BooleanSelector(),
        _optional("boiler_min_power", current): _number(0.3, 200, 0.1, "kW"),
        _optional("boiler_max_power", current): _number(1, 500, 0.1, "kW"),
    }
    if _advanced(options):
        fields.update(
            {
                _optional("max_ch_setpoint", current): _number(20, 95, 1, "°C"),
                _optional("gas_at_min_power", current): _number(0, 200, 0.01),
                _optional("gas_at_max_power", current): _number(0, 500, 0.01),
                vol.Required(
                    "modulation_scale",
                    default=boiler.get("modulation_scale", ModulationScale.RANGE.value),
                ): _select("modulation_scale", [m.value for m in ModulationScale]),
                vol.Required("bypass", default=boiler.get("bypass", False)): (
                    selector.BooleanSelector()
                ),
            }
        )
    return vol.Schema(fields)


def circuit_schema(
    options: dict[str, Any], current: dict[str, Any], more: bool = False
) -> vol.Schema:
    """``more``: another circuit follows this one — offered next, so none is dropped by default."""
    fields: dict[Any, Any] = {
        vol.Required(
            "control", default=current.get("control", CircuitControl.UNMIXED_SHARED.value)
        ): _select("circuit_control", [c.value for c in CircuitControl]),
        _optional("max_flow", current): _number(20, 90, 1, "°C"),
        _optional("fixed_temperature", current): _number(20, 70, 1, "°C"),
    }
    if _advanced(options):
        fields[_optional("flow_entity", current)] = _entity(_TEMPERATURE)
        fields[vol.Required("add_another", default=more)] = selector.BooleanSelector()
    return vol.Schema(fields)


def zones_schema(options: dict[str, Any]) -> vol.Schema:
    current = [z["entity_id"] for z in options.get(ZONES, [])]
    return vol.Schema(
        {
            vol.Optional("zones", default=current): _entity(
                {"domain": "climate", "integration": VT_DOMAIN}, multiple=True
            )
        }
    )


def zone_schema(options: dict[str, Any], current: dict[str, Any]) -> vol.Schema:
    circuits = [c["id"] for c in options.get(CIRCUITS, [])] or ["main"]
    fields: dict[Any, Any] = {}
    if len(circuits) > 1:
        fields[vol.Required("circuit", default=current.get("circuit", circuits[0]))] = (
            selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=circuits, mode=selector.SelectSelectorMode.DROPDOWN
                )
            )
        )
    # No default: underfloor needs its own maximum flow, and a wrong type would hide that.
    fields[vol.Required("emitter", default=current.get("emitter", vol.UNDEFINED))] = _select(
        "emitter", [e.value for e in EmitterType]
    )
    sources = [s["entity_id"] for s in current.get("foreign_heat", [])]
    # A temperature sensor needs its threshold, entered at the advanced level only.
    offered: list[dict[str, Any]] = [
        {"domain": ["switch", "binary_sensor"]},
        {"domain": "sensor", "device_class": "power"},
    ]
    if _advanced(options):
        offered.append({"domain": "sensor", "device_class": "temperature"})
    fields[vol.Optional("foreign_heat", default=sources)] = _entity(offered, multiple=True)
    if _advanced(options):
        fields[_optional("reference_output_w", current)] = _number(50, 20000, 10, "W")
        fields[_optional("exponent", current)] = _number(1.0, 2.0, 0.01)
        thresholds = {
            s["kind"]: s.get("threshold")
            for s in current.get("foreign_heat", [])
            if s.get("threshold")
        }
        fields[_optional("power_threshold", {"power_threshold": thresholds.get("power")})] = (
            _number(1, 10000, 1, "W")
        )
        fields[
            _optional(
                "temperature_threshold", {"temperature_threshold": thresholds.get("temperature")}
            )
        ] = _number(20, 300, 1, "°C")
    return vol.Schema(fields)


def building_schema(options: dict[str, Any]) -> vol.Schema:
    building = options.get(BUILDING, {})
    params = options.get(PARAMETERS, {})
    fields: dict[Any, Any] = {
        _optional("floor_area", building): _number(10, 5000, 1, "m²"),
        _optional("insulation", building): _select(
            "insulation", [i.value for i in InsulationClass]
        ),
        _optional("thermal_mass", building): _select(
            "thermal_mass", [m.value for m in ThermalMass]
        ),
    }
    if _advanced(options):
        fields.update(
            {
                _optional("design_load_kw", building): _number(0.5, 200, 0.1, "kW"),
                _optional("loss_coefficient", params): _number(0.01, 5, 0.001, "kW/K"),
                _optional("heating_threshold", params): _number(5, 22, 0.5, "°C"),
                _optional("design_outdoor", params): _number(-45, 10, 1, "°C"),
            }
        )
    return vol.Schema(fields)


def reference_schema(options: dict[str, Any]) -> vol.Schema:
    reference = options.get(REFERENCE_ROOM, {})
    zones = [z["entity_id"] for z in options.get(ZONES, [])]
    strategies = [Strategy.LARGEST_DEFICIT.value, Strategy.AVERAGE.value]
    if zones:
        strategies.insert(1, Strategy.CHOSEN_ZONE.value)
    fields: dict[Any, Any] = {
        vol.Required(
            "strategy", default=reference.get("strategy", Strategy.LARGEST_DEFICIT.value)
        ): _select("strategy", strategies),
    }
    if zones:
        fields[_optional("zone", reference)] = _entity(
            {"domain": "climate", "integration": VT_DOMAIN}
        )
    if _advanced(options):
        fields[vol.Required("switch_margin", default=reference.get("switch_margin", 0.3))] = (
            _number(0.1, 3.0, 0.1, "K")
        )
    return vol.Schema(fields)


def monitor_schema(options: dict[str, Any]) -> vol.Schema:
    monitor = options.get(MONITOR, {})
    return vol.Schema(
        {
            vol.Required("condensing_return", default=monitor.get("condensing_return", 55.0)): (
                _number(40, 65, 0.5, "°C")
            ),
            vol.Required("short_burn_min", default=monitor.get("short_burn_min", 10.0)): _number(
                1, 60, 1, "min"
            ),
            vol.Required("monitoring_days", default=monitor.get("monitoring_days", 7.0)): _number(
                7, 60, 1, "d"
            ),
            _optional("verdict_window_days", monitor): _number(7, 365, 1, "d"),
            vol.Required("near_room_k", default=monitor.get("near_room_k", 3.0)): _number(
                1, 10, 0.5, "K"
            ),
            vol.Required(
                "foreign_heat_hold_min", default=monitor.get("foreign_heat_hold_min", 60.0)
            ): _number(0, 720, 5, "min"),
            **_limit(monitor, "pressure_low_warning", PRESSURE_LOW_BAND.warning, 0.3, 2.0, "bar"),
            **_limit(monitor, "pressure_low_alarm", PRESSURE_LOW_BAND.alarm, 0.1, 2.0, "bar"),
            **_limit(monitor, "pressure_high_warning", PRESSURE_HIGH_BAND.warning, 1.5, 4, "bar"),
            **_limit(monitor, "pressure_high_alarm", PRESSURE_HIGH_BAND.alarm, 1.5, 4, "bar"),
            **_limit(monitor, "flue_gas_warning", FLUE_GAS_CONDENSING_BAND.warning, 40, 200, "°C"),
            **_limit(monitor, "flue_gas_alarm", FLUE_GAS_CONDENSING_BAND.alarm, 40, 200, "°C"),
            vol.Required(
                "starts_per_hour_limit",
                default=monitor.get("starts_per_hour_limit", DEFAULT_FREQUENT_STARTS_PER_HOUR),
            ): _number(2, 60, 1),
            vol.Required(
                "unstable_burns_limit",
                default=monitor.get("unstable_burns_limit", DEFAULT_UNSTABLE_BURNS_PER_DAY),
            ): _number(1, 100, 1),
        }
    )


def _limit(
    current: dict[str, Any], key: str, default: float | None, low: float, high: float, unit: str
) -> dict[Any, Any]:
    step = 0.1 if unit == "bar" else 1.0
    return {vol.Required(key, default=current.get(key, default)): _number(low, high, step, unit)}


# --- control ----------------------------------------------------------------------------------

NO_CONTROL = "none"
_SETPOINT_ENTITY = {"domain": ["number", "input_number"]}
_ON_OFF_ENTITY = {"domain": ["switch", "input_boolean"]}
_READ_BACK_ENTITY = {"domain": ["sensor", "number", "input_number"]}
_ECHO_ENTITY = {"domain": ["binary_sensor", "switch", "input_boolean"]}
# Alarms whose reaction the user may choose (an internal error always hands back; frequent starts
# stay information, as nothing counted may hold heating against VT).
REACTION_ALARMS = (
    *(kind.value for kind in AlarmKind if kind.value not in INFO_ONLY_ALARMS),
    "write_failed",
    "write_ignored",
    "outside_change",
)
# Control fields only the advanced level shows; at the simple level they keep their defaults.
CONTROL_ADVANCED_KEYS = (
    "room",
    "exponent",
    "offset",
    "ceiling_band",
    "fallback_setpoint",
    "frost_limit",
    "frost_release",
    "frost_zone",
    "count_threshold",
    "power_threshold_kw",
    "opening_threshold",
    "ramp_k_per_min",
    "decision_interval_min",
    "off_setpoint",
    "learning_pauses",
    "comfort_correction",
    "alarm_reactions",
)
CURVE_KEYS = ("design_outdoor", "design_flow", "room", "exponent", "offset")
# What a hand-back goes through: fixed while one is owed.
HAND_BACK_KEYS = (
    "setpoint_entity", "ch_entity", "hand_back", "hand_back_value", "hand_back_value_effect",
    "hand_back_entity", "gateway_id", "mqtt_top", "mqtt_node",
)  # fmt: skip


def control_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})
    paths = [NO_CONTROL, *(path.value for path in WritePath)]
    return vol.Schema(
        {
            vol.Required("write_path", default=control.get("write_path", NO_CONTROL)): _select(
                "write_path", paths
            ),
            _optional("topology", control): _select("topology", [t.value for t in Topology]),
            _optional("confirmed_entity", control): _entity(_READ_BACK_ENTITY),
            _optional("ch_confirmed_entity", control): _entity(_ECHO_ENTITY),
        }
    )


def control_entity_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})
    return vol.Schema(
        {
            vol.Required(
                "setpoint_entity", default=control.get("setpoint_entity", vol.UNDEFINED)
            ): _entity(_SETPOINT_ENTITY),
            vol.Required(
                "write_type", default=control.get("write_type", WriteType.UNKNOWN.value)
            ): _select("write_type", [t.value for t in WriteType]),
            _optional("ch_entity", control): _entity(_ON_OFF_ENTITY),
            vol.Required(
                "ch_write_type", default=control.get("ch_write_type", WriteType.UNKNOWN.value)
            ): _select("write_type", [t.value for t in WriteType]),
            vol.Required("hand_back", default=control.get("hand_back", vol.UNDEFINED)): _select(
                "hand_back", [h.value for h in HandBack]
            ),
            _optional("hand_back_value", control): _number(0, 90, 0.5, "°C"),
            _optional("hand_back_value_effect", control): _select(
                "hand_back_value_effect", [e.value for e in ValueEffect]
            ),
            _optional("hand_back_entity", control): _entity(_ON_OFF_ENTITY),
        }
    )


def control_gateway_schema(options: dict[str, Any], gateways: list[str]) -> vol.Schema:
    control = options.get(CONTROL, {})
    current = control.get("gateway_id") or (gateways[0] if len(gateways) == 1 else vol.UNDEFINED)
    field: Any = (
        selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=gateways, custom_value=True, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        if gateways
        else str
    )
    return vol.Schema({vol.Required("gateway_id", default=current): field})


def control_mqtt_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})
    return vol.Schema(
        {
            vol.Required("mqtt_top", default=control.get("mqtt_top", "OTGW")): str,
            vol.Required("mqtt_node", default=control.get("mqtt_node", vol.UNDEFINED)): str,
        }
    )


def control_curve_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})
    curve = control.get("curve", {})
    design_outdoor = curve.get(
        "design_outdoor",
        options.get(PARAMETERS, {}).get("design_outdoor", CURVE_DEFAULTS["design_outdoor"]),
    )

    def default(key: str) -> Any:
        return control.get(key, CONTROL_DEFAULTS[key])

    fields: dict[Any, Any] = {
        vol.Required("design_outdoor", default=design_outdoor): _number(-40, 10, 0.5, "°C"),
        # The curve is the user's to enter: no silent default for the design flow.
        vol.Required("design_flow", default=curve.get("design_flow", vol.UNDEFINED)): _number(
            25, 80, 0.5, "°C"
        ),
        vol.Required("hard_min", default=default("hard_min")): _number(10, 50, 0.5, "°C"),
        vol.Required("hard_max", default=default("hard_max")): _number(30, 90, 0.5, "°C"),
    }
    if _advanced(options):
        fields |= {
            vol.Required("room", default=curve.get("room", CURVE_DEFAULTS["room"])): _number(
                15, 25, 0.5, "°C"
            ),
            _optional("exponent", curve): _number(1.0, 2.0, 0.05),
            vol.Required("offset", default=curve.get("offset", CURVE_DEFAULTS["offset"])): (
                _number(-10, 10, 0.5, "K")
            ),
            vol.Required("ceiling_band", default=default("ceiling_band")): _number(0, 20, 0.5, "K"),
            _optional("fallback_setpoint", control): _number(25, 80, 0.5, "°C"),
            vol.Required("frost_limit", default=default("frost_limit")): _number(3, 10, 0.5, "°C"),
            vol.Required("frost_release", default=default("frost_release")): _number(
                4, 12, 0.5, "°C"
            ),
            _optional("frost_zone", control): selector.EntitySelector(
                selector.EntitySelectorConfig(include_entities=_zone_entities(options))
            ),
        }
    return vol.Schema(fields)


def _zone_entities(options: dict[str, Any]) -> list[str]:
    return [zone["entity_id"] for zone in options.get(ZONES, []) if zone.get("entity_id")]


def control_behaviour_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})

    def required(key: str, field: Any) -> dict[Any, Any]:
        return {vol.Required(key, default=control.get(key, CONTROL_DEFAULTS[key])): field}

    return vol.Schema(
        {
            **required("ramp_k_per_min", _number(0.1, 10, 0.1, "K/min")),
            **required("decision_interval_min", _number(1, 30, 1, "min")),
            **required("off_setpoint", _number(0, 30, 0.5, "°C")),
            **required("count_threshold", _number(0, 20, 1)),
            _optional("power_threshold_kw", control): _number(0.1, 100, 0.1, "kW"),
            _optional("opening_threshold", control): _number(1, 100, 1, "%"),
            **required("learning_pauses", selector.BooleanSelector()),
            **required("comfort_correction", selector.BooleanSelector()),
        }
    )


def control_alarms_schema(options: dict[str, Any]) -> vol.Schema:
    reactions = options.get(CONTROL, {}).get("alarm_reactions", {})
    choices = [r.value for r in AlarmReaction]
    return vol.Schema(
        {
            vol.Required(
                alarm,
                default=reactions.get(
                    alarm, DEFAULT_REACTIONS.get(alarm, AlarmReaction.INFO).value
                ),
            ): _select("alarm_reaction", choices)
            for alarm in REACTION_ALARMS
        }
    )


def apply_control(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The first control step: the write path, topology and read-back; "none" removes control."""
    if user_input["write_path"] == NO_CONTROL:
        options.pop(CONTROL, None)
        return
    control = dict(options.get(CONTROL, {}))
    if control.get("write_path") != user_input["write_path"]:
        for key in (
            "setpoint_entity", "write_type", "ch_entity", "ch_write_type", "hand_back",
            "hand_back_value", "hand_back_value_effect", "hand_back_entity", "gateway_id",
            "mqtt_top", "mqtt_node",
        ):  # fmt: skip
            control.pop(key, None)
    _set_or_drop(
        control, user_input, ("write_path", "topology", "confirmed_entity", "ch_confirmed_entity")
    )
    options[CONTROL] = control


def apply_control_details(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    keys = (
        "setpoint_entity", "write_type", "ch_entity", "ch_write_type", "hand_back",
        "hand_back_value", "hand_back_value_effect", "hand_back_entity", "gateway_id",
        "mqtt_top", "mqtt_node",
    )  # fmt: skip
    _set_or_drop(control, user_input, tuple(k for k in keys if k in user_input or k in control))
    options[CONTROL] = control


def apply_control_curve(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    curve = dict(control.get("curve", {}))
    shown = CURVE_KEYS if _advanced(options) else ("design_outdoor", "design_flow")
    for key in shown:
        value = user_input.get(key)
        if value in (None, ""):
            curve.pop(key, None)
        else:
            curve[key] = value
    control["curve"] = curve
    keys = ["hard_min", "hard_max"]
    if _advanced(options):
        keys += ["ceiling_band", "fallback_setpoint", "frost_limit", "frost_release", "frost_zone"]
    _set_or_drop(control, user_input, tuple(keys))
    options[CONTROL] = control


def apply_control_behaviour(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    _set_or_drop(control, user_input, tuple(control_behaviour_schema(options).schema))
    options[CONTROL] = control


def apply_control_alarms(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    control["alarm_reactions"] = {alarm: user_input[alarm] for alarm in REACTION_ALARMS}
    options[CONTROL] = control


def _set_or_drop(target: dict[str, Any], user_input: dict[str, Any], keys: tuple[Any, ...]) -> None:
    for key in (str(k) for k in keys):
        value = user_input.get(key)
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value


# Write paths through a built-in OTGW need a gateway topology; "virtual" is a controller on the
# Home Assistant side, reached through an entity.
_PATH_TOPOLOGIES = {
    WritePath.OPENTHERM_GW: {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT},
    WritePath.OTGW_MQTT: {Topology.GATEWAY_STANDALONE, Topology.GATEWAY_WITH_THERMOSTAT},
    WritePath.ENTITY: {
        Topology.GATEWAY_STANDALONE,
        Topology.GATEWAY_WITH_THERMOSTAT,
        Topology.VIRTUAL,
    },
}


def control_error(user_input: dict[str, Any]) -> dict[str, str]:
    """What the first control step needs: every write is checked against a read-back, and the
    topology decides what a hand-back does — both required, and suited to the write path."""
    path = user_input.get("write_path")
    if path in (None, NO_CONTROL):
        return {}
    if not user_input.get("confirmed_entity"):
        return {"confirmed_entity": "confirmed_entity_missing"}
    topology = user_input.get("topology")
    if not topology:
        return {"topology": "topology_missing"}
    if Topology(topology) is Topology.MONITOR_MODE:
        return {"topology": "topology_no_control"}
    if Topology(topology) not in _PATH_TOPOLOGIES[WritePath(path)]:
        return {"topology": "topology_not_for_path"}
    return {}


def mqtt_topic_valid(value: object) -> bool:
    """A topic level the plugin can publish under: no wildcards, spaces or empty text."""
    if not isinstance(value, str):
        return False
    level = value.strip().strip("/")
    return bool(level) and not any(c in "+#" or c.isspace() for c in level)


def control_details_error(
    user_input: dict[str, Any], bounds: tuple[float | None, float | None] = (None, None)
) -> dict[str, str]:
    """What the write types and the chosen hand-back method need; ``bounds``: what the setpoint
    entity accepts. Nothing goes to the boiler's persistent memory, so the setpoint entity and a
    heating switch must each be declared expiring or held."""
    writable = (WriteType.EXPIRING, WriteType.HELD)
    if "write_type" in user_input and user_input["write_type"] not in writable:
        return {"write_type": "write_type_not_supported"}
    if user_input.get("ch_entity") and user_input.get("ch_write_type") not in writable:
        return {"ch_write_type": "ch_write_type_not_supported"}
    method = user_input.get("hand_back")
    value = user_input.get("hand_back_value")
    if method == HandBack.VALUE:
        if value in (None, ""):
            return {"hand_back_value": "hand_back_value_missing"}
        low, high = bounds
        if (low is not None and value < low) or (high is not None and value > high):
            return {"hand_back_value": "hand_back_value_out_of_range"}
        if not user_input.get("hand_back_value_effect"):
            # 0 means "no heat" on one device and "own control" on another: never assumed.
            return {"hand_back_value_effect": "hand_back_value_effect_missing"}
    if method == HandBack.SWITCH and not user_input.get("hand_back_entity"):
        return {"hand_back_entity": "hand_back_entity_missing"}
    if method == HandBack.TIMEOUT and user_input.get("write_type") != WriteType.EXPIRING:
        # Only a value that lapses goes back on its own; any other would stay for good.
        return {"hand_back": "hand_back_timeout_not_expiring"}
    return {}


def _outside(value: Any, bounds: tuple[float | None, float | None]) -> bool:
    low, high = bounds
    if value in (None, ""):
        return False
    return (low is not None and value < low) or (high is not None and value > high)


# --- applying user input ----------------------------------------------------------------------

BOILER_KEYS = ("class", "dhw", "condensing", "modulation_scale", "bypass")
BOILER_PARAMETER_KEYS = (
    "boiler_min_power",
    "boiler_max_power",
    "max_ch_setpoint",
    "gas_at_min_power",
    "gas_at_max_power",
)
BUILDING_KEYS = ("floor_area", "insulation", "thermal_mass", "design_load_kw")
BUILDING_PARAMETER_KEYS = ("loss_coefficient", "heating_threshold", "design_outdoor")


def apply_signals(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    signals = dict(options.get(SIGNALS, {}))
    for key, (_filter, simple) in SIGNAL_FIELDS.items():
        if simple or _advanced(options):
            if user_input.get(key):
                signals[key] = user_input[key]
            else:
                signals.pop(key, None)
    options[SIGNALS] = signals
    options[WEATHER] = user_input.get(WEATHER) or None


def apply_boiler(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    boiler = dict(options.get(BOILER, {}))
    boiler.update({k: user_input[k] for k in BOILER_KEYS if k in user_input})
    options[BOILER] = boiler
    _apply_parameters(options, user_input, BOILER_PARAMETER_KEYS)


def apply_building(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    building = dict(options.get(BUILDING, {}))
    for key in BUILDING_KEYS:
        if key in user_input and user_input[key] not in (None, ""):
            building[key] = user_input[key]
        elif _advanced(options) or key != "design_load_kw":
            building.pop(key, None)
    options[BUILDING] = building
    _apply_parameters(options, user_input, BUILDING_PARAMETER_KEYS)


def _apply_parameters(
    options: dict[str, Any], user_input: dict[str, Any], keys: tuple[str, ...]
) -> None:
    params = dict(options.get(PARAMETERS, {}))
    shown_advanced = _advanced(options)
    for key in keys:
        if key in user_input and user_input[key] not in (None, ""):
            params[key] = user_input[key]
        elif key in ("boiler_min_power", "boiler_max_power") or shown_advanced:
            params.pop(key, None)
    options[PARAMETERS] = params


def circuit_from_input(user_input: dict[str, Any], circuit_id: str) -> dict[str, Any]:
    circuit: dict[str, Any] = {"id": circuit_id, "control": user_input["control"]}
    for key in ("max_flow", "fixed_temperature", "flow_entity"):
        if user_input.get(key) not in (None, ""):
            circuit[key] = user_input[key]
    return circuit


def source_kind(hass_state_domain: str, device_class: str | None) -> SourceKind | None:
    if hass_state_domain == "switch":
        return SourceKind.SWITCH
    if hass_state_domain == "binary_sensor":
        return SourceKind.BINARY
    if device_class == "power":
        return SourceKind.POWER
    if device_class == "temperature":
        return SourceKind.TEMPERATURE
    return None


def apply_monitor(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    options[MONITOR] = dict(user_input)


def restore_advanced_defaults(options: dict[str, Any]) -> None:
    """Drop every tuning value only the advanced level shows, so its default applies again.
    Facts about the installation — what is mapped, the boiler, circuits, emitter sizes, values
    the user entered — stay (``SCOPE.md`` principle 10)."""
    options.get(REFERENCE_ROOM, {}).pop("switch_margin", None)
    options.pop(MONITOR, None)
    control = options.get(CONTROL, {})
    for key in CONTROL_ADVANCED_KEYS:
        control.pop(key, None)
    for key in ("room", "exponent", "offset"):
        control.get("curve", {}).pop(key, None)


ADVANCED_SIGNALS = tuple(key for key, (_f, simple) in SIGNAL_FIELDS.items() if not simple)
_MISSING = object()


def _schema_defaults(schema: vol.Schema) -> dict[str, Any]:
    """The defaults a form offers, read from its schema so they are written once."""
    return {
        str(key): key.default()
        for key in schema.schema
        if isinstance(key, vol.Required) and callable(key.default)
    }


def _differ(values: dict[str, Any], defaults: dict[str, Any], keys: Any) -> bool:
    return any(key in values and values[key] != defaults.get(key, _MISSING) for key in keys)


def has_hidden_advanced(options: dict[str, Any]) -> bool:
    """At the simple level: whether anything only the advanced level shows is active — a fact
    the user gave, or a setting that differs from its default."""
    if _advanced(options):
        return False
    advanced = {LEVEL: LEVEL_ADVANCED}
    params = options.get(PARAMETERS, {})
    circuits = options.get(CIRCUITS, [])
    zones = options.get(ZONES, [])
    control = options.get(CONTROL, {})
    monitor = options.get(MONITOR, {})
    curve_defaults = _schema_defaults(control_curve_schema(advanced))
    control_defaults = curve_defaults | _schema_defaults(control_behaviour_schema({}))
    reactions = _schema_defaults(control_alarms_schema({}))
    return bool(
        any(key in options.get(SIGNALS, {}) for key in ADVANCED_SIGNALS)
        or _differ(
            options.get(BOILER, {}),
            _schema_defaults(boiler_schema(advanced)),
            ("modulation_scale", "bypass"),
        )
        or any(
            key in params
            for key in (
                "max_ch_setpoint",
                "gas_at_min_power",
                "gas_at_max_power",
                *BUILDING_PARAMETER_KEYS,
            )
        )
        or "design_load_kw" in options.get(BUILDING, {})
        or len(circuits) > 1
        or any("flow_entity" in c for c in circuits)
        or any("reference_output_w" in z or "exponent" in z for z in zones)
        or any("threshold" in s for z in zones for s in z.get("foreign_heat", []))
        or _differ(
            options.get(REFERENCE_ROOM, {}),
            _schema_defaults(reference_schema(advanced)),
            ("switch_margin",),
        )
        or _differ(monitor, _schema_defaults(monitor_schema({})), monitor)
        or _differ(
            control, control_defaults, [k for k in CONTROL_ADVANCED_KEYS if k != "alarm_reactions"]
        )
        or any(
            control.get("alarm_reactions", {}).get(alarm, default) != default
            for alarm, default in reactions.items()
        )
        or _differ(control.get("curve", {}), curve_defaults, ("room", "exponent", "offset"))
    )


def validate(options: dict[str, Any]) -> str | None:
    """A translation key of the first problem, or None."""
    problem = validate_problem(options)
    return None if problem is None else problem[0]


def validate_problem(options: dict[str, Any]) -> tuple[str, str | None] | None:
    """The first problem as a translation key and what it concerns, or None."""
    try:
        EntryConfig.from_options(options)
    except ConfigError as err:
        return err.code, err.subject
    return None


_PROBLEM_STEPS = {
    "missing_signal": "signals",
    "unknown_signal": "signals",
    "no_circuit": "circuit",
    "duplicate_circuit": "circuit",
    "unknown_circuit": "circuit",
    "fixed_temperature_missing": "circuit",
    "duplicate_zone": "zones",
    "zone_without_circuit": "zones",
    "reference_zone_unknown": "reference",
    "alarm_limits_out_of_order": "monitor",
    "invalid_control": "control",
}


def problem_step(code: str, subject: str | None) -> str:
    """The step where the user can fix a problem the last check found."""
    if code in ("unknown_parameter", "implausible_parameter"):
        return "boiler" if subject in BOILER_PARAMETER_KEYS else "building"
    return _PROBLEM_STEPS.get(code, "signals")


# --- flows ------------------------------------------------------------------------------------


class _Steps:
    """Steps shared by the config flow and the options flow."""

    options: dict[str, Any]
    _zone_queue: list[str]
    _zones_done: list[dict[str, Any]]
    _circuits_done: list[dict[str, Any]]
    # A problem the last check found: shown on its step, which the flow goes back to.
    _problem: tuple[str, dict[str, str]] | None = None

    def _form(
        self,
        step_id: str,
        data_schema: vol.Schema,
        errors: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> ConfigFlowResult:
        if not errors and self._problem is not None and self._problem[0] == step_id:
            errors = self._problem[1]
            self._problem = None
        result: ConfigFlowResult = self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id, data_schema=data_schema, errors=errors or {}, **kwargs
        )
        return result

    async def _back_to_problem(self, code: str, subject: str | None) -> ConfigFlowResult:
        """The answers stay: the step that can fix the problem is shown again, with it."""
        step = problem_step(code, subject)
        self._problem = (step, {"base": code})
        return await self._goto(step)

    def _next_after(self, step: str) -> str:
        raise NotImplementedError

    async def _goto(self, step: str) -> ConfigFlowResult:
        result: ConfigFlowResult = await getattr(self, f"async_step_{step}")()
        return result

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            modulation = user_input.get("modulation")
            state = self.hass.states.get(modulation) if modulation else None  # type: ignore[attr-defined]
            if state is not None and state.attributes.get("unit_of_measurement") not in (None, "%"):
                errors["modulation"] = "modulation_not_percent"  # e.g. a power sensor
            else:
                apply_signals(self.options, user_input)
                return await self._goto(self._next_after("signals"))
        return self._form(
            step_id="signals", data_schema=signals_schema(self.options), errors=errors
        )

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            low, high = user_input.get("boiler_min_power"), user_input.get("boiler_max_power")
            if low is not None and high is not None and low >= high:
                errors["base"] = "min_power_not_below_max"
            else:
                apply_boiler(self.options, user_input)
                return await self._goto(self._next_after("boiler"))
        return self._form(step_id="boiler", data_schema=boiler_schema(self.options), errors=errors)

    async def async_step_circuit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        index = len(self._circuits_done)
        existing = self.options.get(CIRCUITS, [])
        current = existing[index] if index < len(existing) else {}
        if user_input is not None:
            circuit = circuit_from_input(user_input, current.get("id", f"circuit_{index + 1}"))
            if index == 0 and not current:
                circuit["id"] = "main"
            if not _advanced(self.options) and current.get("flow_entity"):
                circuit["flow_entity"] = current["flow_entity"]  # not shown: kept
            if (
                circuit["control"] == CircuitControl.PASSIVE_FIXED
                and "fixed_temperature" not in circuit
            ):
                errors["fixed_temperature"] = "fixed_temperature_missing"
            else:
                self._circuits_done.append(circuit)
                if user_input.get("add_another"):
                    return await self.async_step_circuit()
                kept = [] if _advanced(self.options) else existing[len(self._circuits_done) :]
                self.options[CIRCUITS] = [*self._circuits_done, *kept]
                self._circuits_done = []
                return await self._goto(self._next_after("circuit"))
        return self._form(
            step_id="circuit",
            data_schema=circuit_schema(self.options, current, more=index + 1 < len(existing)),
            errors=errors,
            description_placeholders={"number": str(index + 1)},
        )

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_queue = list(user_input.get("zones", []))
            self._zones_done = []
            return await self.async_step_zone()
        return self._form(step_id="zones", data_schema=zones_schema(self.options))

    async def async_step_zone(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if not self._zone_queue:
            self.options[ZONES] = self._zones_done
            return await self._goto(self._next_after("zones"))
        entity_id = self._zone_queue[0]
        previous = {z["entity_id"]: z for z in self.options.get(ZONES, [])}
        current = previous.get(entity_id, {})
        errors: dict[str, str] = {}
        if user_input is not None:
            zone: dict[str, Any] = {"entity_id": entity_id, "emitter": user_input["emitter"]}
            circuits = [c["id"] for c in self.options.get(CIRCUITS, [])] or ["main"]
            zone["circuit"] = user_input.get("circuit", current.get("circuit", circuits[0]))
            for key in ("reference_output_w", "exponent"):
                if user_input.get(key) not in (None, ""):
                    zone[key] = user_input[key]
                elif not _advanced(self.options) and current.get(key) is not None:
                    zone[key] = current[key]  # not shown: kept
            thresholds = {
                s["entity_id"]: s["threshold"]
                for s in current.get("foreign_heat", [])
                if s.get("threshold") is not None
            }
            sources = []
            for source_id in user_input.get("foreign_heat", []):
                state = self.hass.states.get(source_id)  # type: ignore[attr-defined]
                kind = source_kind(
                    source_id.split(".")[0],
                    state.attributes.get("device_class") if state is not None else None,
                )
                if kind is None:
                    errors["foreign_heat"] = "foreign_heat_unsupported"
                    break
                source: dict[str, Any] = {"entity_id": source_id, "kind": kind.value}
                threshold = user_input.get(f"{kind.value}_threshold")
                if threshold in (None, "") and not _advanced(self.options):
                    threshold = thresholds.get(source_id)  # not shown: kept
                if threshold not in (None, ""):
                    source["threshold"] = threshold
                elif kind is SourceKind.TEMPERATURE:
                    errors["foreign_heat"] = "temperature_threshold_missing"
                    break
                sources.append(source)
            if not errors:
                zone["foreign_heat"] = sources
                self._zones_done.append(zone)
                self._zone_queue.pop(0)
                return await self.async_step_zone()
        return self._form(
            step_id="zone",
            data_schema=zone_schema(self.options, current),
            errors=errors,
            description_placeholders={"zone": zone_name(self.hass, entity_id)},  # type: ignore[attr-defined]
        )

    async def async_step_building(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_building(self.options, user_input)
            return await self._goto(self._next_after("building"))
        return self._form(step_id="building", data_schema=building_schema(self.options))

    async def async_step_reference(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            reference = {k: v for k, v in user_input.items() if v not in (None, "")}
            margin = self.options.get(REFERENCE_ROOM, {}).get("switch_margin")
            if not _advanced(self.options) and margin is not None:
                reference["switch_margin"] = margin  # not shown: kept
            zones = [z["entity_id"] for z in self.options.get(ZONES, [])]
            if (
                reference.get("strategy") == Strategy.CHOSEN_ZONE
                and reference.get("zone") not in zones
            ):
                errors["zone"] = "reference_zone_unknown"
            else:
                if reference.get("strategy") != Strategy.CHOSEN_ZONE:
                    reference.pop("zone", None)
                self.options[REFERENCE_ROOM] = reference
                return await self._goto(self._next_after("reference"))
        return self._form(
            step_id="reference", data_schema=reference_schema(self.options), errors=errors
        )

    async def async_step_monitor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_monitor(self.options, user_input)
            return await self._goto(self._next_after("monitor"))
        return self._form(step_id="monitor", data_schema=monitor_schema(self.options))


class SmartBoilerConfigFlow(_Steps, ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2  # 2: the options 0.2.1 removed are gone (see async_migrate_entry)

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self._title = "Boiler"
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartBoilerOptionsFlow()

    ORDER = ("signals", "boiler", "circuit", "zones", "building", "reference", "monitor", "finish")

    def _next_after(self, step: str) -> str:
        following = self.ORDER[self.ORDER.index(step) + 1]
        if following == "monitor" and not _advanced(self.options):
            return "finish"
        return following

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._title = user_input["name"]
            self.options[LEVEL] = user_input[LEVEL]
            return await self.async_step_signals()
        return self.async_show_form(step_id="user", data_schema=user_schema({}))

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate_problem(self.options)
        if problem is not None:
            return await self._back_to_problem(*problem)
        return self.async_create_entry(title=self._title, data={}, options=self.options)


class SmartBoilerOptionsFlow(_Steps, OptionsFlow):
    """A menu of sections; each saves the options when done."""

    def __init__(self) -> None:
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []
        self._options: dict[str, Any] | None = None

    @property
    def options(self) -> dict[str, Any]:  # type: ignore[override]
        if self._options is None:
            self._options = copy.deepcopy(dict(self.config_entry.options))
        return self._options

    def _next_after(self, step: str) -> str:
        return "save"

    async def _async_hand_back_blocker(self) -> str | None:
        """Why what the hand-back goes through must not change now: it has not reached the
        boiler yet, or control holds the boiler — its hand-back must go through the device
        that has it, which the user gets by switching control off first. With the entry not
        running — its setup failed, say — its store tells: the next start makes what the last
        run left owed through what the options say then."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None:
            return "hand_back_pending" if await self._async_owed_in_store() else None
        found = (getattr(coordinator, name, None) for name in ("control", "hand_back_unit"))
        units = [unit for unit in found if unit is not None]
        if any(unit.hand_back_owed for unit in units):
            return "hand_back_pending"
        if any(unit.holding for unit in units):
            return "control_holds_boiler"
        return None

    async def _async_owed_in_store(self) -> bool:
        """What the entry's store says; one that cannot be read tells nothing, as at setup."""
        from homeassistant.helpers.storage import Store

        key = f"{DOMAIN}.{self.config_entry.entry_id}"
        try:
            data = await Store[dict[str, Any]](self.hass, STORAGE_VERSION, key).async_load()
        except Exception:  # unreadable: the setup ignores it too
            return False
        return owes_hand_back(data.get("control") if isinstance(data, dict) else None)

    def _changes_gateway_read_back(self, user_input: dict[str, Any]) -> bool:
        """Whether the answer re-picks a built-in gateway's read-back, which tells whether a
        hand-back through the gateway got there (R6, H2 with C1)."""
        current = self.config_entry.options.get(CONTROL, {})
        path = current.get("write_path")
        if path not in OTGW_PATHS or user_input.get("write_path") != path:
            return False
        return (user_input.get("confirmed_entity") or None) != (
            current.get("confirmed_entity") or None
        )

    def _changes_hand_back(self, user_input: dict[str, Any], schema: vol.Schema) -> bool:
        """Whether the answer changes how the boiler is given back. A field the form shows but
        the answer leaves out was cleared: the frontend leaves an emptied optional field out."""
        current = self.config_entry.options.get(CONTROL, {})
        shown = {str(marker) for marker in schema.schema}

        def value(data: Mapping[str, Any], key: str) -> Any:
            found = data.get(key)
            return None if found in (None, "") else found

        return any(
            value(user_input, key) != value(current, key) for key in HAND_BACK_KEYS if key in shown
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = [
            "signals", "freshness", "boiler", "circuit", "zones", "building", "reference",
            "control",
        ]  # fmt: skip
        if _advanced(self.options):
            menu.append("monitor")
        # At the simple level, say when hidden advanced settings are still active.
        menu.append("level_hidden" if has_hidden_advanced(self.options) else "level")
        return self.async_show_menu(step_id="init", menu_options=menu)

    async def async_step_level_hidden(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self.async_step_level(user_input)

    async def async_step_level(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[LEVEL] == LEVEL_SIMPLE and user_input.get("restore_defaults"):
                restore_advanced_defaults(self.options)
            self.options[LEVEL] = user_input[LEVEL]
            return await self.async_step_save()
        return self.async_show_form(step_id="level", data_schema=level_schema(self.options))

    async def async_step_freshness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_freshness(self.options, user_input)
            return await self.async_step_save()
        return self._form(step_id="freshness", data_schema=freshness_schema(self.options))

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate_problem(self.options)
        if problem is not None:
            return await self._back_to_problem(*problem)
        return self.async_create_entry(data=self.options)

    # --- control: path and topology → path details → curve and limits → (advanced) behaviour
    # → alarm reactions → save

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            path = user_input["write_path"]
            current = self.config_entry.options.get(CONTROL, {}).get("write_path")
            errors = control_error(user_input)
            blocker = await self._async_hand_back_blocker()
            if not errors and path not in (NO_CONTROL, current) and blocker:
                # "No control" stays possible: the hand-back goes through the old path, retried
                # by a unit that only hands back.
                errors = {"write_path": blocker}
            elif not errors and blocker and self._changes_gateway_read_back(user_input):
                errors = {"confirmed_entity": blocker}
            if errors:
                return self._form(
                    step_id="control", data_schema=control_schema(self.options), errors=errors
                )
            apply_control(self.options, user_input)
            if path == NO_CONTROL:
                return await self.async_step_save()
            step = {
                WritePath.ENTITY: "control_entity",
                WritePath.OPENTHERM_GW: "control_gateway",
                WritePath.OTGW_MQTT: "control_mqtt",
            }[WritePath(path)]
            return await self._goto(step)
        return self._form(step_id="control", data_schema=control_schema(self.options))

    async def async_step_control_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if temperature_unit_of(self.hass, user_input["setpoint_entity"]) is False:
                errors = {"setpoint_entity": "setpoint_unit_not_supported"}
            else:
                errors = control_details_error(
                    user_input, read_bounds(self.hass, user_input["setpoint_entity"])
                )
            blocker = await self._async_hand_back_blocker()
            if (
                not errors
                and blocker
                and self._changes_hand_back(user_input, control_entity_schema(self.options))
            ):
                errors = {"base": blocker}
            if not errors:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self._form(
            step_id="control_entity",
            data_schema=control_entity_schema(self.options),
            errors=errors,
        )

    async def async_step_control_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        gateways = sorted(
            str(entry.data["id"])
            for entry in self.hass.config_entries.async_entries("opentherm_gw")
            if entry.data.get("id")
        )
        if user_input is not None:
            if user_input["gateway_id"] not in gateways:
                errors = {"gateway_id": "gateway_unknown"}  # every write would fail
            elif (blocker := await self._async_hand_back_blocker()) and self._changes_hand_back(
                user_input, control_gateway_schema(self.options, gateways)
            ):
                errors = {"base": blocker}
            else:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self._form(
            step_id="control_gateway",
            data_schema=control_gateway_schema(self.options, gateways),
            errors=errors,
        )

    async def async_step_control_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = {
                key: "mqtt_topic_invalid"
                for key in ("mqtt_top", "mqtt_node")
                if not mqtt_topic_valid(user_input.get(key))
            }
            blocker = await self._async_hand_back_blocker()
            # Spaces around a valid topic level are dropped, not published to.
            user_input = {
                key: value.strip()
                if key in ("mqtt_top", "mqtt_node") and isinstance(value, str)
                else value
                for key, value in user_input.items()
            }
            if (
                not errors
                and blocker
                and self._changes_hand_back(user_input, control_mqtt_schema(self.options))
            ):
                errors = {"base": blocker}
            if not errors:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self._form(
            step_id="control_mqtt", data_schema=control_mqtt_schema(self.options), errors=errors
        )

    async def async_step_control_curve(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            bounds = self._setpoint_bounds()
            if user_input["hard_min"] >= user_input["hard_max"]:
                errors["hard_max"] = "hard_limits_out_of_order"
            elif _outside(user_input["hard_min"], bounds):
                errors["hard_min"] = "limits_outside_entity_range"
            elif _outside(user_input["hard_max"], bounds):
                errors["hard_max"] = "limits_outside_entity_range"
            elif user_input.get("frost_limit", CONTROL_DEFAULTS["frost_limit"]) >= user_input.get(
                "frost_release", CONTROL_DEFAULTS["frost_release"]
            ):
                errors["frost_release"] = "frost_release_not_above_limit"
            else:
                apply_control_curve(self.options, user_input)
                if _advanced(self.options):
                    return await self.async_step_control_behaviour()
                return await self.async_step_save()
        return self._form(
            step_id="control_curve", data_schema=control_curve_schema(self.options), errors=errors
        )

    async def async_step_control_behaviour(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            count = int(user_input.get("count_threshold", 1))
            hard_min = float(
                self.options.get(CONTROL, {}).get("hard_min", CONTROL_DEFAULTS["hard_min"])
            )
            if _outside(user_input.get("off_setpoint"), self._setpoint_bounds()):
                errors["off_setpoint"] = "off_setpoint_outside_entity_range"
            elif (
                float(user_input.get("off_setpoint", CONTROL_DEFAULTS["off_setpoint"])) >= hard_min
            ):
                errors["off_setpoint"] = "off_setpoint_not_below_hard_min"
            elif count > len(self.options.get(ZONES, [])):
                errors["count_threshold"] = "count_threshold_above_zones"
            elif count == 0 and not (
                user_input.get("power_threshold_kw") or user_input.get("opening_threshold")
            ):
                errors["count_threshold"] = "no_demand_criterion"
            else:
                apply_control_behaviour(self.options, user_input)
                return await self.async_step_control_alarms()
        return self._form(
            step_id="control_behaviour",
            data_schema=control_behaviour_schema(self.options),
            errors=errors,
        )

    def _setpoint_bounds(self) -> tuple[float | None, float | None]:
        """What the picked setpoint entity accepts; nothing to check on the gateway paths."""
        control = self.options.get(CONTROL, {})
        entity = control.get("setpoint_entity")
        if control.get("write_path") != WritePath.ENTITY or not entity:
            return None, None
        return read_bounds(self.hass, entity)

    async def async_step_control_alarms(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_control_alarms(self.options, user_input)
            return await self.async_step_save()
        return self._form(step_id="control_alarms", data_schema=control_alarms_schema(self.options))
