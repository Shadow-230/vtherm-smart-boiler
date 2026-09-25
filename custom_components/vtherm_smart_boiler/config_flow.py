"""Config flow and options flow.

The level (simple or advanced) changes which fields are shown, never how the plugin behaves:
a field that is not shown keeps its cautious default. Every step reads and writes one part of
the options dictionary that ``config.EntryConfig`` interprets.
"""

from __future__ import annotations

import copy
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
    LEVEL,
    LEVEL_ADVANCED,
    LEVEL_SIMPLE,
    MONITOR,
    PARAMETERS,
    REFERENCE_ROOM,
    SIGNALS,
    VT_DOMAIN,
    WEATHER,
    ZONES,
)
from .control_config import (
    DEFAULT_REACTIONS,
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
from .transport.entities import read_bounds

# --- field definitions ----------------------------------------------------------------------

_BINARY = {"domain": "binary_sensor"}
_TEMPERATURE = {"domain": "sensor", "device_class": "temperature"}

# signal -> (entity filter, shown at the simple level)
SIGNAL_FIELDS: dict[str, tuple[dict[str, Any], bool]] = {
    "flame": (_BINARY, True),
    "flow": (_TEMPERATURE, True),
    "return": (_TEMPERATURE, True),
    "modulation": ({"domain": "sensor"}, True),
    "dhw_active": (_BINARY, True),
    "pressure": ({"domain": "sensor", "device_class": "pressure"}, True),
    "outdoor": (_TEMPERATURE, True),
    "ch_setpoint": ({"domain": ["sensor", "number"]}, False),
    "ch_active": (_BINARY, False),
    "pump_running": (_BINARY, False),
    "flue_gas": (_TEMPERATURE, False),
    "gas_meter": ({"domain": "sensor", "device_class": ["gas", "energy"]}, False),
    "room_setpoint": (_TEMPERATURE, False),
    "room_temperature": (_TEMPERATURE, False),
}
REQUIRED_FIELDS = ("flame", "flow")


def _entity(filter_: dict[str, Any], multiple: bool = False) -> selector.EntitySelector:
    return selector.EntitySelector(
        selector.EntitySelectorConfig(filter=[filter_], multiple=multiple)  # type: ignore[typeddict-item]
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


def boiler_schema(options: dict[str, Any]) -> vol.Schema:
    boiler = options.get(BOILER, {})
    params = options.get(PARAMETERS, {})
    current = {**boiler, **params}
    fields: dict[Any, Any] = {
        vol.Required("class", default=boiler.get("class", BoilerClass.READ_ONLY.value)): _select(
            "boiler_class", [c.value for c in BoilerClass]
        ),
        vol.Required("dhw", default=boiler.get("dhw", DhwType.NONE.value)): _select(
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
                vol.Required(
                    "shared_return", default=boiler.get("shared_return", False)
                ): selector.BooleanSelector(),
            }
        )
    return vol.Schema(fields)


def circuit_schema(options: dict[str, Any], current: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(
            "control", default=current.get("control", CircuitControl.UNMIXED_SHARED.value)
        ): _select("circuit_control", [c.value for c in CircuitControl]),
        _optional("max_flow", current): _number(20, 90, 1, "°C"),
        _optional("fixed_temperature", current): _number(20, 70, 1, "°C"),
    }
    if _advanced(options):
        fields[_optional("flow_entity", current)] = _entity(_TEMPERATURE)
        fields[vol.Required("add_another", default=False)] = selector.BooleanSelector()
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
    fields[vol.Required("emitter", default=current.get("emitter", EmitterType.RADIATOR.value))] = (
        _select("emitter", [e.value for e in EmitterType])
    )
    sources = [s["entity_id"] for s in current.get("foreign_heat", [])]
    fields[vol.Optional("foreign_heat", default=sources)] = _entity(
        {"domain": ["switch", "binary_sensor", "sensor"]}, multiple=True
    )
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
# Alarms whose reaction the user may choose (a reached daily cap has its own field; an internal
# error always hands back).
REACTION_ALARMS = (
    *(kind.value for kind in AlarmKind),
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
    "count_threshold",
    "power_threshold_kw",
    "opening_threshold",
    "min_burn_min",
    "min_pause_min",
    "max_starts_per_hour",
    "min_on_min",
    "min_off_min",
    "max_switches_per_hour",
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
        "design_outdoor", options.get(PARAMETERS, {}).get("design_outdoor", -15.0)
    )
    fields: dict[Any, Any] = {
        vol.Required("design_outdoor", default=design_outdoor): _number(-40, 10, 0.5, "°C"),
        # The curve is the user's to enter: no silent default for the design flow.
        vol.Required(
            "design_flow", default=curve.get("design_flow", vol.UNDEFINED)
        ): _number(25, 80, 0.5, "°C"),
        vol.Required("hard_min", default=control.get("hard_min", 25.0)): _number(
            10, 50, 0.5, "°C"
        ),
        vol.Required("hard_max", default=control.get("hard_max", 70.0)): _number(
            30, 90, 0.5, "°C"
        ),
        vol.Required(
            "summer_threshold", default=control.get("summer_threshold", 20.0)
        ): _number(10, 25, 0.5, "°C"),
    }
    if _advanced(options):
        fields |= {
            vol.Required("room", default=curve.get("room", 20.0)): _number(15, 25, 0.5, "°C"),
            _optional("exponent", curve): _number(1.0, 2.0, 0.05),
            vol.Required("offset", default=curve.get("offset", 0.0)): _number(-10, 10, 0.5, "K"),
            vol.Required("ceiling_band", default=control.get("ceiling_band", 10.0)): _number(
                0, 20, 0.5, "K"
            ),
            _optional("fallback_setpoint", control): _number(25, 80, 0.5, "°C"),
            vol.Required("frost_limit", default=control.get("frost_limit", 5.0)): _number(
                3, 10, 0.5, "°C"
            ),
            vol.Required("frost_release", default=control.get("frost_release", 7.0)): _number(
                4, 12, 0.5, "°C"
            ),
        }
    return vol.Schema(fields)


def control_behaviour_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})

    def required(key: str, default: Any, field: Any) -> dict[Any, Any]:
        return {vol.Required(key, default=control.get(key, default)): field}

    return vol.Schema(
        {
            **required("min_burn_min", 5.0, _number(0, 30, 1, "min")),
            **required("min_pause_min", 5.0, _number(0, 60, 1, "min")),
            **required("max_starts_per_hour", 6, _number(1, 20, 1)),
            **required("min_on_min", 5.0, _number(0, 30, 1, "min")),
            **required("min_off_min", 5.0, _number(0, 60, 1, "min")),
            **required("max_switches_per_hour", 6, _number(1, 20, 1)),
            **required("ramp_k_per_min", 1.0, _number(0.1, 10, 0.1, "K/min")),
            **required("decision_interval_min", 5.0, _number(1, 30, 1, "min")),
            **required("off_setpoint", 10.0, _number(0, 30, 0.5, "°C")),
            **required("count_threshold", 1, _number(1, 20, 1)),
            _optional("power_threshold_kw", control): _number(0, 100, 0.1, "kW"),
            _optional("opening_threshold", control): _number(0, 100, 1, "%"),
            **required("learning_pauses", True, selector.BooleanSelector()),
            **required("comfort_correction", True, selector.BooleanSelector()),
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
    _set_or_drop(control, user_input, ("write_path", "topology", "confirmed_entity"))
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
    keys = ["hard_min", "hard_max", "summer_threshold"]
    if _advanced(options):
        keys += ["ceiling_band", "fallback_setpoint", "frost_limit", "frost_release"]
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

BOILER_KEYS = ("class", "dhw", "condensing", "modulation_scale", "shared_return")
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
    """Drop every value only the advanced level shows, so its default applies again."""
    signals = options.get(SIGNALS, {})
    for key, (_filter, simple) in SIGNAL_FIELDS.items():
        if not simple:
            signals.pop(key, None)
    boiler = options.get(BOILER, {})
    for key in ("modulation_scale", "shared_return"):
        boiler.pop(key, None)
    params = options.get(PARAMETERS, {})
    for key in (
        "max_ch_setpoint",
        "gas_at_min_power",
        "gas_at_max_power",
        *BUILDING_PARAMETER_KEYS,
    ):
        params.pop(key, None)
    options.get(BUILDING, {}).pop("design_load_kw", None)
    circuits = options.get(CIRCUITS, [])
    if circuits:
        first = {k: v for k, v in circuits[0].items() if k != "flow_entity"}
        options[CIRCUITS] = [first]
        first_id = first["id"]
        for zone in options.get(ZONES, []):
            zone["circuit"] = first_id
    for zone in options.get(ZONES, []):
        zone.pop("reference_output_w", None)
        zone.pop("exponent", None)
        for source in zone.get("foreign_heat", []):
            source.pop("threshold", None)
    options.get(REFERENCE_ROOM, {}).pop("switch_margin", None)
    options.pop(MONITOR, None)
    control = options.get(CONTROL, {})
    for key in CONTROL_ADVANCED_KEYS:
        control.pop(key, None)
    for key in ("room", "exponent", "offset"):
        control.get("curve", {}).pop(key, None)


ADVANCED_SIGNALS = tuple(key for key, (_f, simple) in SIGNAL_FIELDS.items() if not simple)


def has_hidden_advanced(options: dict[str, Any]) -> bool:
    """At the simple level: whether any setting only the advanced level shows is set."""
    if _advanced(options):
        return False
    params = options.get(PARAMETERS, {})
    circuits = options.get(CIRCUITS, [])
    zones = options.get(ZONES, [])
    return bool(
        any(key in options.get(SIGNALS, {}) for key in ADVANCED_SIGNALS)
        or any(key in options.get(BOILER, {}) for key in ("modulation_scale", "shared_return"))
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
        or "switch_margin" in options.get(REFERENCE_ROOM, {})
        or MONITOR in options
        or any(key in options.get(CONTROL, {}) for key in CONTROL_ADVANCED_KEYS)
        or any(
            key in options.get(CONTROL, {}).get("curve", {})
            for key in ("room", "exponent", "offset")
        )
    )


def validate(options: dict[str, Any]) -> str | None:
    """A translation key of the first problem, or None."""
    try:
        EntryConfig.from_options(options)
    except ConfigError as err:
        return err.code
    return None


# --- flows ------------------------------------------------------------------------------------


class _Steps:
    """Steps shared by the config flow and the options flow."""

    options: dict[str, Any]
    _zone_queue: list[str]
    _zones_done: list[dict[str, Any]]
    _circuits_done: list[dict[str, Any]]

    def _next_after(self, step: str) -> str:
        raise NotImplementedError

    async def _goto(self, step: str) -> ConfigFlowResult:
        return await getattr(self, f"async_step_{step}")()

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            apply_signals(self.options, user_input)
            return await self._goto(self._next_after("signals"))
        return self.async_show_form(  # type: ignore[attr-defined]
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
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="boiler", data_schema=boiler_schema(self.options), errors=errors
        )

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
            if (
                circuit["control"] == CircuitControl.PASSIVE_FIXED
                and "fixed_temperature" not in circuit
            ):
                errors["fixed_temperature"] = "fixed_temperature_missing"
            else:
                self._circuits_done.append(circuit)
                if user_input.get("add_another"):
                    return await self.async_step_circuit()
                self.options[CIRCUITS] = self._circuits_done
                self._circuits_done = []
                return await self._goto(self._next_after("circuit"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="circuit",
            data_schema=circuit_schema(self.options, current),
            errors=errors,
            description_placeholders={"number": str(index + 1)},
        )

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._zone_queue = list(user_input.get("zones", []))
            self._zones_done = []
            return await self.async_step_zone()
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="zones", data_schema=zones_schema(self.options)
        )

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
            zone["circuit"] = user_input.get("circuit", circuits[0])
            for key in ("reference_output_w", "exponent"):
                if user_input.get(key) not in (None, ""):
                    zone[key] = user_input[key]
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
        name_state = self.hass.states.get(entity_id)  # type: ignore[attr-defined]
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="zone",
            data_schema=zone_schema(self.options, current),
            errors=errors,
            description_placeholders={"zone": name_state.name if name_state else entity_id},
        )

    async def async_step_building(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_building(self.options, user_input)
            return await self._goto(self._next_after("building"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="building", data_schema=building_schema(self.options)
        )

    async def async_step_reference(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            reference = {k: v for k, v in user_input.items() if v not in (None, "")}
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
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="reference", data_schema=reference_schema(self.options), errors=errors
        )

    async def async_step_monitor(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_monitor(self.options, user_input)
            return await self._goto(self._next_after("monitor"))
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id="monitor", data_schema=monitor_schema(self.options)
        )


class SmartBoilerConfigFlow(_Steps, ConfigFlow, domain=DOMAIN):
    VERSION = 1

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
        problem = validate(self.options)
        if problem is not None:
            return self.async_abort(reason=problem)
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

    def _hand_back_owed(self) -> bool:
        """A hand-back has not reached the boiler yet: what it goes through must not change."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        units = [getattr(coordinator, name, None) for name in ("control", "hand_back_unit")]
        return any(unit is not None and unit.hand_back_owed for unit in units)

    def _changes_hand_back(self, user_input: dict[str, Any]) -> bool:
        current = self.config_entry.options.get(CONTROL, {})
        return any(
            key in user_input and user_input.get(key) != current.get(key)
            for key in HAND_BACK_KEYS
        )

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = ["signals", "boiler", "circuit", "zones", "building", "reference", "control"]
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
        schema = vol.Schema(
            {
                vol.Required(LEVEL, default=self.options.get(LEVEL, LEVEL_SIMPLE)): _select(
                    "level", [LEVEL_SIMPLE, LEVEL_ADVANCED]
                ),
                vol.Required("restore_defaults", default=False): selector.BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="level", data_schema=schema)

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate(self.options)
        if problem is not None:
            return self.async_abort(reason=problem)
        return self.async_create_entry(data=self.options)

    # --- control: path and topology → path details → curve and limits → (advanced) behaviour
    # → alarm reactions → save

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            path = user_input["write_path"]
            current = self.config_entry.options.get(CONTROL, {}).get("write_path")
            if path not in (NO_CONTROL, current) and self._hand_back_owed():
                # "No control" stays possible: a unit that only hands back keeps retrying.
                return self.async_show_form(
                    step_id="control",
                    data_schema=control_schema(self.options),
                    errors={"write_path": "hand_back_pending"},
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
        return self.async_show_form(step_id="control", data_schema=control_schema(self.options))

    async def async_step_control_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = control_details_error(
                user_input, read_bounds(self.hass, user_input["setpoint_entity"])
            )
            if not errors and self._hand_back_owed() and self._changes_hand_back(user_input):
                errors = {"base": "hand_back_pending"}
            if not errors:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self.async_show_form(
            step_id="control_entity",
            data_schema=control_entity_schema(self.options),
            errors=errors,
        )

    async def async_step_control_gateway(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._hand_back_owed() and self._changes_hand_back(user_input):
                errors = {"base": "hand_back_pending"}
            else:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        gateways = sorted(
            str(entry.data["id"])
            for entry in self.hass.config_entries.async_entries("opentherm_gw")
            if entry.data.get("id")
        )
        return self.async_show_form(
            step_id="control_gateway",
            data_schema=control_gateway_schema(self.options, gateways),
            errors=errors,
        )

    async def async_step_control_mqtt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if self._hand_back_owed() and self._changes_hand_back(user_input):
                errors = {"base": "hand_back_pending"}
            else:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self.async_show_form(
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
            elif user_input.get("frost_limit", 5.0) >= user_input.get("frost_release", 7.0):
                errors["frost_release"] = "frost_release_not_above_limit"
            else:
                apply_control_curve(self.options, user_input)
                if _advanced(self.options):
                    return await self.async_step_control_behaviour()
                return await self.async_step_save()
        return self.async_show_form(
            step_id="control_curve", data_schema=control_curve_schema(self.options), errors=errors
        )

    async def async_step_control_behaviour(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if _outside(user_input.get("off_setpoint"), self._setpoint_bounds()):
                errors["off_setpoint"] = "off_setpoint_outside_entity_range"
            else:
                apply_control_behaviour(self.options, user_input)
                return await self.async_step_control_alarms()
        return self.async_show_form(
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
        return self.async_show_form(
            step_id="control_alarms", data_schema=control_alarms_schema(self.options)
        )
