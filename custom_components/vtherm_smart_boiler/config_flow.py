"""Config flow and options flow.

The level (simple or advanced) changes which fields are shown, never how the plugin behaves:
a field that is not shown keeps its cautious default. Every step reads and writes one part of
the options dictionary that ``config.EntryConfig`` interprets.

What the forms offer is checked again on submit (P-79): each entity field's domain, integration
and — for an entity that has reported — device class, zones being Versatile Thermostat climates
only; one entity for one signal and one role; the gateway or MQTT integration set up; the
curve's values fitting together. A value stored that this version does not know shows on its
section's step, never as an exception (P-70). An options edit that would add a blocker to
control asks for confirmation first (Open after R6 #3); every save but the level's reloads the
integration, which hands the boiler back while control holds it (P-67, provisional, K4).

The setup opens with how the boiler is connected (I6): the connection, the heat source and the
boiler type, then the control mode — chosen on purpose, no default — with condensing and the
hot-water priority where they apply, then the name and the level. The boiler class follows from
the connection; an entry made before the panels keeps its stored class and is offered the panels
in the options, pre-filled where its stored write path names the connection.

The write path suits the boiler class: a flow-setpoint boiler gets the setpoint paths, an on/off
boiler the relay (X8), the other classes only "no control"; monitoring only, or room values until
0.3, offers "no control" alone. The relay path asks for the relay and
its own settings — pre-filled from Versatile Thermostat's central boiler where it can be moved
over, shown for confirmation and never saved without the user — then its behaviour step, which
shows VT's activation delay at every level; no signal is required for the entry.
"""

from __future__ import annotations

import copy
from collections.abc import Collection, Iterable, Mapping, Sequence
from enum import StrEnum
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.translation import async_get_translations
from homeassistant.util import dt as dt_util

from .config import (
    CIRCUIT_BOUNDS,
    FOREIGN_HEAT_THRESHOLDS,
    FRESHNESS_BOUNDS_MIN,
    MONITOR_BOUNDS,
    MONITORING_DAYS_BOUNDS,
    SECTION_CODES,
    SWITCH_MARGIN_BOUNDS,
    ZONE_BOUNDS,
    ConfigError,
    EntryConfig,
    section_fits,
)
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
    MQTT_DOMAIN,
    OPENTHERM_GW_DOMAIN,
    PARAMETERS,
    REFERENCE_ROOM,
    SIGNALS,
    VT_DOMAIN,
    WEATHER,
    ZONES,
)
from .control_config import (
    CONNECTION_MODES,
    CONNECTION_PATH,
    CONTROL_BOUNDS,
    CONTROL_DEFAULTS,
    CURVE_BOUNDS,
    CURVE_DEFAULTS,
    ESPHOME_SAFE_START,
    GATEWAY_TOPOLOGIES,
    HAND_BACK_TIMEOUT_DEFAULT_MIN,
    HAND_BACK_TIMEOUT_MIN,
    PATH_TOPOLOGIES,
    RELAY_DEFAULTS,
    RELAY_DOMAINS,
    RELAY_KEYS,
    TARGET_KEYS,
    VIRTUAL_CONNECTIONS,
    AlarmReaction,
    Connection,
    ControlMode,
    ControlOptions,
    HandBack,
    ThermostatKind,
    Topology,
    ValueEffect,
    WritePath,
    boiler_class_for,
    config_blockers,
    connection_suggested_by,
    curve_problems,
    fixed_keys,
    hand_back_value_problems,
    heating_writes,
    kind_contradicts_topology,
    lowest_above_max,
    mqtt_topic_valid,
    off_too_close_to_lowest,
    own_room_controller_offered,
    parse_thermostat_kind,
    write_ignored_offered,
)
from .core.alarms import (
    ADD_WATER_RANGE_BAR,
    CIRCUIT_ALARM_MIN,
    CIRCUIT_ALARM_RISE_K,
    DEFAULT_FREQUENT_STARTS_PER_HOUR,
    DEFAULT_UNSTABLE_BURNS_PER_DAY,
    FLUE_GAS_CONDENSING_BAND,
)
from .core.building import InsulationClass, ThermalMass
from .core.demand import feeds_opening, feeds_power
from .core.foreign_heat import SourceKind
from .core.guards import WriteType
from .core.installation import BoilerClass, BoilerType, CircuitControl, EmitterType, HeatSource
from .core.metrics import ModulationScale
from .core.reference_room import Strategy
from .core.relay import TIMER_MIN_S, RelayPowerOn, RelayReports, RelayRest, RelayTimer
from .transport.entities import read_bounds, read_grid, relay_hvac_modes, temperature_unit_of
from .vtherm_link import (
    VtCentralBoiler,
    VtCommands,
    VThermLink,
    is_vt_climate,
    relay_of_boiler_interface,
    relay_used_by_zone,
    vt_central_boiler_settings,
    zone_name,
    zones_on_boiler_thermostat,
)

# --- field definitions ----------------------------------------------------------------------

_BINARY = {"domain": "binary_sensor"}
_TEMPERATURE = {"domain": "sensor", "device_class": "temperature"}

# signal -> (entity filter, shown at the simple level), in the signals' precedence
# (``core.signals.SIGNAL_PRECEDENCE``): where one entity is picked for two, the later is refused.
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
    # X8: the boiler's electric power, only a relay's proof that the boiler heats.
    "boiler_power": ({"domain": "sensor", "device_class": "power"}, False),
    "room_setpoint": (_TEMPERATURE, False),
    "room_temperature": (_TEMPERATURE, False),
    # Y1, boiler protection: the boiler's own low-water-pressure fault (simple level) and
    # another fault it reports as stopping it (advanced), each a binary sensor; the boiler's
    # general fault indication, which the gateway's fault flags need (Q3.9).
    "low_pressure_fault": (_BINARY, True),
    "boiler_lockout": (_BINARY, False),
    "fault_indication": (_BINARY, True),
}


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


def _choice(stored: Any, kind: type[StrEnum], default: Any) -> Any:
    """A stored choice as its field's default; one this version does not know is offered to be
    chosen again (no default), never passed off as a known one (P-70)."""
    if stored is None:
        return default
    return stored if stored in {member.value for member in kind} else vol.UNDEFINED


# --- what the forms offer, checked again on submit (P-79) ---------------------------------------

type EntityFilter = Mapping[str, Any] | Sequence[Mapping[str, Any]]


def _listed(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list | tuple | set | frozenset) else [value]


def entity_suitable(hass: HomeAssistant, entity_id: object, filters: EntityFilter) -> bool:
    """Whether an entity passes a field's selector filter as the form offers it: its domain, from
    the entity ID, always; its integration from the entity registry; its device class only once
    it has reported — an entity with no state yet, or unavailable or unknown without a device
    class, passes on its domain."""
    if not isinstance(entity_id, str) or "." not in entity_id:
        return False
    domain = entity_id.split(".", 1)[0]
    registered = er.async_get(hass).async_get(entity_id)
    state = hass.states.get(entity_id)
    device_class = None if state is None else state.attributes.get("device_class")
    reported = device_class is not None or (
        state is not None and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
    )
    for filter_ in [filters] if isinstance(filters, Mapping) else filters:
        if "domain" in filter_ and domain not in _listed(filter_["domain"]):
            continue
        if "integration" in filter_ and (
            registered is None or registered.platform != filter_["integration"]
        ):
            continue
        if (
            "device_class" in filter_
            and reported
            and device_class not in _listed(filter_["device_class"])
        ):
            continue
        return True
    return False


def entity_errors(
    hass: HomeAssistant, user_input: Mapping[str, Any], fields: Mapping[str, EntityFilter]
) -> dict[str, str]:
    """``entity_not_suitable`` on each field whose entity — or one of whose entities — the form
    would not have offered; a field left empty is no answer, never an error."""
    errors: dict[str, str] = {}
    for key, filters in fields.items():
        picked = _listed(user_input.get(key))
        if any(entity not in (None, "") for entity in picked) and not all(
            entity_suitable(hass, entity, filters) for entity in picked
        ):
            errors[key] = "entity_not_suitable"
    return errors


def zones_not_vt(hass: HomeAssistant, entities: Iterable[object]) -> bool:
    """Whether any of the picked zones is not a Versatile Thermostat climate (question 19,
    provisional, K4: zones are VT climates only)."""
    return any(not isinstance(e, str) or not is_vt_climate(hass, e) for e in entities)


# --- schemas ----------------------------------------------------------------------------------


DEFAULT_NAME = "Boiler"  # the English text; the form offers the translated one (PB-83)
DEFAULT_NAME_KEY = "boiler"  # its translation key, under "device"


def user_schema(current: dict[str, Any], name: str = DEFAULT_NAME) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required("name", default=current.get("name", name)): str,
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


# --- the first panels: how the boiler is connected, and the control mode (I6) ----------------

CONNECTION = "connection"
CONTROL_MODE = "control_mode"
HEAT_SOURCE = "heat_source"
BOILER_TYPE = "type"
DHW_PRIORITY = "dhw_priority"
CONNECTION_STEP_KEYS = (CONNECTION, HEAT_SOURCE, BOILER_TYPE)
# The boiler's keys the panels write: a stored value of them this version cannot read is fixed
# there (P-70).
PANEL_BOILER_KEYS = ("class", "dhw", "condensing")


def _stored_boiler(options: Mapping[str, Any]) -> Mapping[str, Any]:
    boiler = options.get(BOILER)
    return boiler if isinstance(boiler, Mapping) else {}


def _known[E: StrEnum](kind: type[E], raw: object) -> E | None:
    try:
        return kind(str(raw)) if raw is not None else None
    except ValueError:
        return None


def _suggested_connection(options: Mapping[str, Any]) -> Any:
    """The stored connection; for an entry made before the question, the one its stored write
    path names (decision 12); else none — chosen on purpose."""
    boiler = _stored_boiler(options)
    if CONNECTION in boiler:
        return _choice(boiler[CONNECTION], Connection, vol.UNDEFINED)
    control = options.get(CONTROL)
    suggested = connection_suggested_by(
        control.get("write_path") if isinstance(control, Mapping) else None
    )
    return vol.UNDEFINED if suggested is None else suggested.value


def connection_schema(options: dict[str, Any]) -> vol.Schema:
    """The setup's first panel (decisions 1, 7, 8): how the boiler is connected, what it burns
    or uses, and its type by the standard names — each chosen on purpose, with no default; an
    entry made before the panel is offered its type from its stored hot-water kind."""
    boiler = _stored_boiler(options)
    if BOILER_TYPE in boiler:
        kind = _choice(boiler[BOILER_TYPE], BoilerType, vol.UNDEFINED)
    else:
        suggested = BoilerType.suggested_for(boiler.get("dhw"))
        kind = vol.UNDEFINED if suggested is None else suggested.value
    return vol.Schema(
        {
            vol.Required(CONNECTION, default=_suggested_connection(options)): _select(
                CONNECTION, [c.value for c in Connection]
            ),
            vol.Required(
                HEAT_SOURCE, default=_choice(boiler.get(HEAT_SOURCE), HeatSource, vol.UNDEFINED)
            ): _select(HEAT_SOURCE, [s.value for s in HeatSource]),
            vol.Required(BOILER_TYPE, default=kind): _select(
                "boiler_type", [k.value for k in BoilerType]
            ),
        }
    )


def modes_offered(options: Mapping[str, Any]) -> list[str]:
    """The control modes the stored connection can do (decision 6)."""
    connection = _known(Connection, _stored_boiler(options).get(CONNECTION))
    modes = CONNECTION_MODES[connection] if connection is not None else tuple(ControlMode)
    return [mode.value for mode in modes]


def _suggested_mode(options: Mapping[str, Any], modes: list[str]) -> Any:
    """The stored mode where the connection can do it; for an entry made before the question,
    the one its stored control section shows — a relay switches on and off, any other path
    sets the water; else none — chosen on purpose (decision 6)."""
    boiler = _stored_boiler(options)
    if CONTROL_MODE in boiler:
        stored = boiler[CONTROL_MODE]
        return stored if stored in modes else vol.UNDEFINED
    control = options.get(CONTROL)
    path = control.get("write_path") if isinstance(control, Mapping) else None
    if not path:
        return vol.UNDEFINED
    suggested = ControlMode.ON_OFF if path == WritePath.RELAY else ControlMode.FULL
    return suggested.value if suggested.value in modes else vol.UNDEFINED


def mode_schema(options: dict[str, Any]) -> vol.Schema:
    """The second panel (decisions 6, 7, 8): the control mode the connection can do, with no
    default; condensing for a boiler that burns fuel; the hot-water priority for one that heats
    hot water — on by default, as the plugin took it before."""
    boiler = _stored_boiler(options)
    modes = modes_offered(options)
    fields: dict[Any, Any] = {
        vol.Required(CONTROL_MODE, default=_suggested_mode(options, modes)): _select(
            CONTROL_MODE, modes
        )
    }
    source = _known(HeatSource, boiler.get(HEAT_SOURCE))
    if source is None or source.burns_fuel:
        fields[vol.Required("condensing", default=boiler.get("condensing", True))] = (
            selector.BooleanSelector()
        )
    kind = _known(BoilerType, boiler.get(BOILER_TYPE))
    if kind is None or kind.heats_hot_water:
        fields[vol.Required(DHW_PRIORITY, default=boiler.get(DHW_PRIORITY, True))] = (
            selector.BooleanSelector()
        )
    return vol.Schema(fields)


def apply_connection(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The first panel's answers; the hot-water kind follows the boiler type, so a version
    without the type reads the entry the same. Topics of a connection no longer chosen go."""
    boiler = dict(_stored_boiler(options))
    for key in CONNECTION_STEP_KEYS:
        boiler[key] = user_input[key]
    boiler["dhw"] = BoilerType(user_input[BOILER_TYPE]).dhw.value
    kept = TOPIC_KEYS.get(Connection(user_input[CONNECTION]), ())
    for keys in TOPIC_KEYS.values():
        for key in keys:
            if key not in kept:
                boiler.pop(key, None)
    options[BOILER] = boiler


# The MQTT topics each MQTT connection publishes under (I6, decision 9): asked with the
# connection, so the plugin can hear its repeats whether or not control is set up.
EMS_ESP_BASE = "ems_esp_base"
TOPIC_KEYS: Mapping[Connection, tuple[str, ...]] = {
    Connection.OTGW_MQTT: ("mqtt_top", "mqtt_node"),
    Connection.EMS_ESP: (EMS_ESP_BASE,),
}


def mqtt_topics_schema(options: dict[str, Any]) -> vol.Schema:
    """The OTGW firmware's top level and node — taken from the control options where they are
    there — or EMS-ESP's base topic, ``ems-esp`` unless stored."""
    boiler = _stored_boiler(options)
    control = options.get(CONTROL)
    control = control if isinstance(control, Mapping) else {}
    if stored_connection(options) is Connection.EMS_ESP:
        return vol.Schema(
            {vol.Required(EMS_ESP_BASE, default=boiler.get(EMS_ESP_BASE, "ems-esp")): str}
        )
    top = boiler.get("mqtt_top") or control.get("mqtt_top") or "OTGW"
    node = boiler.get("mqtt_node") or control.get("mqtt_node") or vol.UNDEFINED
    return vol.Schema(
        {
            vol.Required("mqtt_top", default=top): str,
            vol.Required("mqtt_node", default=node): str,
        }
    )


def apply_mode(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The second panel's answers; the class follows the connection and the mode (decision 2).
    An electric boiler does not condense; one without hot water keeps no priority."""
    boiler = dict(_stored_boiler(options))
    boiler[CONTROL_MODE] = user_input[CONTROL_MODE]
    boiler["condensing"] = user_input.get("condensing", False)  # not shown: it burns nothing
    if DHW_PRIORITY in user_input:
        boiler[DHW_PRIORITY] = user_input[DHW_PRIORITY]
    else:
        boiler.pop(DHW_PRIORITY, None)  # not shown: no hot water
    boiler["class"] = boiler_class_for(
        Connection(boiler[CONNECTION]), ControlMode(user_input[CONTROL_MODE])
    ).value
    options[BOILER] = boiler


# The OpenTherm Gateway integration's own entities, by its unique IDs ``<gateway>-boiler-<key>``
# (Home Assistant 2026.9.3, ``opentherm_gw/entity.py``; the keys are pyotgw's): its boiler device's,
# never its thermostat device's, which show what the thermostat sees (I6, decision 2).
GATEWAY_SIGNALS: Mapping[str, tuple[str, str]] = {
    "flame": ("binary_sensor", "slave_flame_on"),
    "flow": ("sensor", "ch_water_temp"),
    "return": ("sensor", "return_water_temp"),
    "modulation": ("sensor", "relative_mod_level"),
    "dhw_active": ("binary_sensor", "slave_dhw_active"),
    "pressure": ("sensor", "ch_water_pressure"),
    "low_pressure_fault": ("binary_sensor", "slave_low_water_pressure"),
    "fault_indication": ("binary_sensor", "slave_fault_indication"),
    "ch_active": ("binary_sensor", "slave_ch_active"),
}
GATEWAY_READ_BACKS: Mapping[str, tuple[str, str]] = {
    "confirmed_entity": ("sensor", "control_setpoint"),
    "ch_confirmed_entity": ("binary_sensor", "master_ch_enabled"),
}
# The texts the signals step reads into its description, one per connection (I6, decision 2).
SIGNAL_HINT = "signal_hint"
SOURCE_HINT = "source_hint"  # and one per heat source that changes what to pick (I6)


def gateway_entities(hass: HomeAssistant, wanted: Mapping[str, tuple[str, str]]) -> dict[str, str]:
    """The entities of the one OpenTherm Gateway set up and running, for each field; none where
    there is no gateway or more than one, and none disabled."""
    gateways = [
        entry
        for entry in hass.config_entries.async_entries(
            OPENTHERM_GW_DOMAIN, include_ignore=False, include_disabled=False
        )
        if entry.state is ConfigEntryState.LOADED and entry.data.get("id")
    ]
    if len(gateways) != 1:
        return {}
    gateway = str(gateways[0].data["id"])
    registry = er.async_get(hass)
    found: dict[str, str] = {}
    for field_name, (domain, key) in wanted.items():
        entity_id = registry.async_get_entity_id(
            domain, OPENTHERM_GW_DOMAIN, f"{gateway}-boiler-{key}"
        )
        registered = registry.async_get(entity_id) if entity_id else None
        if registered is not None and registered.disabled_by is None:
            found[field_name] = registered.entity_id
    return found


def _stored_signals(options: Mapping[str, Any]) -> dict[str, Any]:
    """The stored signals; a section of another shape entirely reads as none, so the signals
    step can show and replace it (P-70)."""
    signals = options.get(SIGNALS)
    return dict(signals) if isinstance(signals, Mapping) else {}


def signals_schema(
    options: dict[str, Any], suggested: Mapping[str, str] | None = None
) -> vol.Schema:
    """Every signal optional (X8): a home with only a relay is monitored too; water-temperature
    control gets a blocker without flame and flow. ``suggested``: entities the connection names
    for signals not mapped yet (I6, decision 2), shown for the user to check."""
    current = {**(suggested or {}), **_stored_signals(options), WEATHER: options.get(WEATHER)}
    fields: dict[Any, Any] = {}
    for key, (filter_, simple) in SIGNAL_FIELDS.items():
        if not signal_shown(options, key, simple):
            continue
        fields[_optional(key, current)] = _entity(filter_)
    fields[_optional(WEATHER, current)] = _entity({"domain": "weather"})
    return vol.Schema(fields)


def _freshness_keys(options: dict[str, Any]) -> list[str]:
    """What may have an age limit: each mapped signal, and the weather entity when one is set —
    its own limit, never the outdoor sensor's (X2)."""
    keys = list(options.get(SIGNALS, {}))
    if options.get(WEATHER):
        keys.append(WEATHER)
    return keys


def freshness_schema(options: dict[str, Any]) -> vol.Schema:
    """An optional age limit, in minutes, for each mapped signal and the weather entity: empty,
    the automatic one its source earns (I6, decision 9); 0, none."""
    limits = {k: v / 60.0 for k, v in options.get(FRESHNESS, {}).items() if v is not None}
    return vol.Schema(
        {
            _optional(key, limits): _number(0, FRESHNESS_BOUNDS_MIN[1], 1, "min")
            for key in _freshness_keys(options)
        }
    )


def apply_freshness(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    keys = _freshness_keys(options)
    options[FRESHNESS] = {
        key: float(value) * 60.0
        for key, value in user_input.items()
        if key in keys and value not in (None, "")
    }


def boiler_schema(options: dict[str, Any]) -> vol.Schema:
    boiler = options.get(BOILER, {})
    params = options.get(PARAMETERS, {})
    current = {**boiler, **params}
    # The class, the hot water and condensing are the first panels' (I6).
    fields: dict[Any, Any] = {
        _optional("boiler_min_power", current): _number(0.3, 200, 0.1, "kW"),
        _optional("boiler_max_power", current): _number(1, 500, 0.1, "kW"),
    }
    if _advanced(options):
        fields[_optional("max_ch_setpoint", current)] = _number(20, 95, 1, "°C")
        if gas_rates_shown(options):  # I6, decision 7: a gas boiler's, or one not said
            fields[_optional("gas_at_min_power", current)] = _number(0, 200, 0.01)
            fields[_optional("gas_at_max_power", current)] = _number(0, 500, 0.01)
    fields |= pressure_fields(options)
    if _advanced(options):
        fields.update(
            {
                vol.Required(
                    "modulation_scale",
                    default=_choice(
                        boiler.get("modulation_scale"),
                        ModulationScale,
                        ModulationScale.RANGE.value,
                    ),
                ): _select("modulation_scale", [m.value for m in ModulationScale]),
                vol.Required("bypass", default=boiler.get("bypass", False)): (
                    selector.BooleanSelector()
                ),
            }
        )
    return vol.Schema(fields)


# The water pressure's limits, from the boiler's manual and the safety valve's rating: facts about
# the boiler, asked in its step at both levels and kept by "restore defaults" (I6); stored in the
# monitor section, whose alarms they set.
PRESSURE_KEYS = ("add_water_below", "pressure_high_warning", "pressure_high_alarm")


def pressure_fields(options: dict[str, Any]) -> dict[Any, Any]:
    monitor = options.get(MONITOR, {})
    return {
        # Y1: one optional "add water" threshold from the boiler's manual — none by default.
        _optional("add_water_below", monitor): _number(*ADD_WATER_RANGE_BAR, 0.1, "bar"),
        # Decision 13 (SB-18): the high-pressure limits, from the safety valve's rating — none by
        # default, each optional.
        _optional("pressure_high_warning", monitor): _number(
            *MONITOR_BOUNDS["pressure_high_warning"], 0.1, "bar"
        ),
        _optional("pressure_high_alarm", monitor): _number(
            *MONITOR_BOUNDS["pressure_high_alarm"], 0.1, "bar"
        ),
    }


def pressure_error(user_input: dict[str, Any]) -> dict[str, str]:
    """The high-pressure alarm above its warning, where both are set."""
    warning, alarm = user_input.get("pressure_high_warning"), user_input.get("pressure_high_alarm")
    if warning is None or alarm is None or alarm > warning:
        return {}
    return {"pressure_high_alarm": "alarm_limits_out_of_order"}


def circuit_schema(
    options: dict[str, Any], current: dict[str, Any], more: bool = False
) -> vol.Schema:
    """``more``: another circuit follows this one — offered next, so none is dropped by default.
    At the advanced level the maximum's too-hot alarm (decision 10): its temperature and time,
    offered as stored — pre-filled once the maximum is entered."""
    fields: dict[Any, Any] = {
        vol.Required(
            "control",
            default=_choice(
                current.get("control"), CircuitControl, CircuitControl.UNMIXED_SHARED.value
            ),
        ): _select("circuit_control", [c.value for c in CircuitControl]),
        _optional("max_flow", current): _number(*CIRCUIT_BOUNDS["max_flow"], 1, "°C"),
        _optional("fixed_temperature", current): _number(
            *CIRCUIT_BOUNDS["fixed_temperature"], 1, "°C"
        ),
    }
    if _advanced(options):
        fields[_optional(MAX_FLOW_ALARM, current)] = _number(
            *CIRCUIT_BOUNDS[MAX_FLOW_ALARM], 1, "°C"
        )
        fields[_optional(MAX_FLOW_ALARM_MIN, current)] = _number(
            *CIRCUIT_BOUNDS[MAX_FLOW_ALARM_MIN], 1, "min"
        )
        fields[_optional("flow_entity", current)] = _entity(_TEMPERATURE)
        fields[vol.Required("add_another", default=more)] = selector.BooleanSelector()
    return vol.Schema(fields)


MAX_FLOW_ALARM = "max_flow_alarm"
MAX_FLOW_ALARM_MIN = "max_flow_alarm_min"


def circuit_alarm_error(circuit: Mapping[str, Any], advanced: bool) -> dict[str, str]:
    """The too-hot alarm must lie above the circuit's maximum (decision 10). At the simple level
    its field is hidden: the maximum's field says it."""
    maximum, alarm = circuit.get("max_flow"), circuit.get(MAX_FLOW_ALARM)
    if maximum is None or alarm is None or alarm > maximum:
        return {}
    return {MAX_FLOW_ALARM if advanced else "max_flow": "max_flow_alarm_not_above_max"}


_ZONE_FILTER = {"domain": "climate", "integration": VT_DOMAIN}
CLOSES_WHEN_OFF = "closes_when_off"


def zones_schema(options: dict[str, Any]) -> vol.Schema:
    current = [z["entity_id"] for z in options.get(ZONES, [])]
    return vol.Schema(
        {vol.Optional("zones", default=current): _entity(_ZONE_FILTER, multiple=True)}
    )


def foreign_heat_filters(options: dict[str, Any]) -> list[dict[str, Any]]:
    """What a zone's other heat sources may be; a temperature sensor needs its threshold,
    entered at the advanced level only."""
    offered: list[dict[str, Any]] = [
        {"domain": ["switch", "binary_sensor"]},
        {"domain": "sensor", "device_class": "power"},
    ]
    if _advanced(options):
        offered.append({"domain": "sensor", "device_class": "temperature"})
    return offered


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
    fields[
        vol.Required("emitter", default=_choice(current.get("emitter"), EmitterType, vol.UNDEFINED))
    ] = _select("emitter", [e.value for e in EmitterType])
    # Decision 4 (provisional, K4): at both levels, off unless the user ticked it.
    fields[vol.Required(CLOSES_WHEN_OFF, default=current.get(CLOSES_WHEN_OFF) is True)] = (
        selector.BooleanSelector()
    )
    sources = [s["entity_id"] for s in current.get("foreign_heat", [])]
    fields[vol.Optional("foreign_heat", default=sources)] = _entity(
        foreign_heat_filters(options), multiple=True
    )
    if _advanced(options):
        fields[_optional("reference_output_w", current)] = _number(
            *ZONE_BOUNDS["reference_output_w"], 10, "W"
        )
        fields[_optional("exponent", current)] = _number(*ZONE_BOUNDS["exponent"], 0.01)
        thresholds = {
            s["kind"]: s.get("threshold")
            for s in current.get("foreign_heat", [])
            if s.get("threshold")
        }
        fields[_optional("power_threshold", {"power_threshold": thresholds.get("power")})] = (
            _number(*FOREIGN_HEAT_THRESHOLDS[SourceKind.POWER], 1, "W")
        )
        fields[
            _optional(
                "temperature_threshold", {"temperature_threshold": thresholds.get("temperature")}
            )
        ] = _number(*FOREIGN_HEAT_THRESHOLDS[SourceKind.TEMPERATURE], 1, "°C")
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
        # I6: one value with the heating curve's, at both levels; never empty, so the curve
        # never falls back to a default unseen.
        vol.Required("design_outdoor", default=design_outdoor_of(options)): _number(
            *CURVE_BOUNDS["design_outdoor"], 0.5, "°C"
        ),
    }
    if _advanced(options):
        fields.update(
            {
                _optional("design_load_kw", building): _number(0.5, 200, 0.1, "kW"),
                _optional("loss_coefficient", params): _number(0.01, 5, 0.001, "kW/K"),
                _optional("heating_threshold", params): _number(5, 22, 0.5, "°C"),
            }
        )
    return vol.Schema(fields)


def design_outdoor_too_warm(options: Mapping[str, Any], design_outdoor: float) -> bool:
    """The building's design outdoor temperature too warm for the curve entered (X5.8, P-68): the
    curve step's check, made where the same value is entered too (I6)."""
    control = options.get(CONTROL)
    curve = control.get("curve") if isinstance(control, Mapping) else None
    if not isinstance(curve, Mapping) or curve.get("design_flow") in (None, ""):
        return False
    room = float(curve.get("room", CURVE_DEFAULTS["room"]))
    problems = curve_problems(float(curve["design_flow"]), design_outdoor, room, 0.0, 100.0)
    return ("design_outdoor", "design_outdoor_too_warm") in problems


def design_outdoor_of(options: Mapping[str, Any]) -> float:
    """The design outdoor temperature, one value for the building and the curve (I6), as control
    reads it: the curve's own where its section still holds one (a hand edit), else the
    building's, else the default."""
    control = options.get(CONTROL)
    curve = control.get("curve") if isinstance(control, Mapping) else None
    params = options.get(PARAMETERS)
    for source in (curve, params):
        if isinstance(source, Mapping) and source.get("design_outdoor") not in (None, ""):
            return float(source["design_outdoor"])
    return CURVE_DEFAULTS["design_outdoor"]


def reference_schema(options: dict[str, Any]) -> vol.Schema:
    reference = options.get(REFERENCE_ROOM, {})
    zones = [z["entity_id"] for z in options.get(ZONES, [])]
    strategies = [Strategy.LARGEST_DEFICIT.value, Strategy.AVERAGE.value]
    if zones:
        strategies.insert(1, Strategy.CHOSEN_ZONE.value)
    fields: dict[Any, Any] = {
        vol.Required(
            "strategy",
            default=_choice(reference.get("strategy"), Strategy, Strategy.LARGEST_DEFICIT.value),
        ): _select("strategy", strategies),
    }
    if zones:
        fields[_optional("zone", reference)] = _entity(_ZONE_FILTER)
    if _advanced(options):
        fields[vol.Required("switch_margin", default=reference.get("switch_margin", 0.3))] = (
            _number(*SWITCH_MARGIN_BOUNDS, 0.1, "K")
        )
    return vol.Schema(fields)


def monitor_schema(options: dict[str, Any]) -> vol.Schema:
    monitor = options.get(MONITOR, {})
    return vol.Schema(
        {
            vol.Required("condensing_return", default=monitor.get("condensing_return", 55.0)): (
                _number(*MONITOR_BOUNDS["condensing_return"], 0.5, "°C")
            ),
            vol.Required("short_burn_min", default=monitor.get("short_burn_min", 10.0)): _number(
                *MONITOR_BOUNDS["short_burn_min"], 1, "min"
            ),
            vol.Required("monitoring_days", default=monitor.get("monitoring_days", 7.0)): _number(
                *MONITORING_DAYS_BOUNDS, 1, "d"
            ),
            _optional("verdict_window_days", monitor): _number(
                *MONITOR_BOUNDS["verdict_window_days"], 1, "d"
            ),
            vol.Required("near_room_k", default=monitor.get("near_room_k", 3.0)): _number(
                *MONITOR_BOUNDS["near_room_k"], 0.5, "K"
            ),
            vol.Required(
                "foreign_heat_hold_min", default=monitor.get("foreign_heat_hold_min", 60.0)
            ): _number(*MONITOR_BOUNDS["foreign_heat_hold_min"], 5, "min"),
            # I6 (decision 7): a condensing boiler's only — the alarm is off for any other.
            **(
                _limit(
                    monitor,
                    "flue_gas_warning",
                    FLUE_GAS_CONDENSING_BAND.warning,
                    *MONITOR_BOUNDS["flue_gas_warning"],
                    "°C",
                )
                | _limit(
                    monitor,
                    "flue_gas_alarm",
                    FLUE_GAS_CONDENSING_BAND.alarm,
                    *MONITOR_BOUNDS["flue_gas_alarm"],
                    "°C",
                )
                if flue_gas_limits_shown(options)
                else {}
            ),
            vol.Required(
                "starts_per_hour_limit",
                default=monitor.get("starts_per_hour_limit", DEFAULT_FREQUENT_STARTS_PER_HOUR),
            ): _number(*MONITOR_BOUNDS["starts_per_hour_limit"], 1),
            vol.Required(
                "unstable_burns_limit",
                default=monitor.get("unstable_burns_limit", DEFAULT_UNSTABLE_BURNS_PER_DAY),
            ): _number(*MONITOR_BOUNDS["unstable_burns_limit"], 1),
        }
    )


def _limit(
    current: dict[str, Any], key: str, default: float | None, low: float, high: float, unit: str
) -> dict[Any, Any]:
    """A flue-gas limit, in whole degrees, offered at its default."""
    return {vol.Required(key, default=current.get(key, default)): _number(low, high, 1.0, unit)}


# --- control ----------------------------------------------------------------------------------

NO_CONTROL = "none"
_RELAY_ENTITY = {"domain": list(RELAY_DOMAINS)}  # a switch, or a boiler thermostat entity
_SETPOINT_ENTITY = {"domain": ["number", "input_number"]}
_ON_OFF_ENTITY = {"domain": ["switch", "input_boolean"]}
_READ_BACK_ENTITY = {"domain": ["sensor", "number", "input_number"]}
_ECHO_ENTITY = {"domain": ["binary_sensor", "switch", "input_boolean"]}
_THERMOSTAT_SETPOINT_ENTITY = {"domain": ["sensor", "number"], "device_class": "temperature"}
_RESTART_ENTITY = {"domain": "sensor"}
# The one alarm whose reaction the user may choose (decision 7, Y1): a write the boiler ignores,
# offered only where a thermostat or the boiler's own control takes over, at both levels. The
# others are the allow-list's to decide: an internal error, the lost link, another controller,
# the monitor failing and heating off ignored from the start always hand back; every other alarm
# informs.
REACTION_ALARMS = ("write_ignored",)
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
    "return_after_outside_change",
    "return_after_switch_hand_back",
)
CURVE_KEYS = ("design_flow", "room", "exponent", "offset")  # the design outdoor: the building's
OWN_ROOM_CONTROLLER = "own_room_controller"
HAND_BACK_TIMEOUT = "hand_back_timeout_min"
# What an absent hand-back answer means: the form fills in this default (an entry saved before
# the answer existed has none). What a hand-back goes through and what judges it
# (``fixed_keys``) and the writable-entity step's answers (``TARGET_KEYS``) are listed once, in
# the control options.
_HAND_BACK_DEFAULTS = {
    "hand_back_entity_write_type": WriteType.UNKNOWN.value,
    "relay_rest_state": RELAY_DEFAULTS["relay_rest_state"],
    "write_type": WriteType.UNKNOWN.value,
    "ch_write_type": WriteType.UNKNOWN.value,
    "hard_min": CONTROL_DEFAULTS["hard_min"],
    HAND_BACK_TIMEOUT: HAND_BACK_TIMEOUT_DEFAULT_MIN,
}
HAND_BACK_PENDING = "hand_back_pending"
# A demand threshold no zone can feed (P-14): the field, and what the form says.
_UNFED = {
    "power_threshold_kw": "power_criterion_no_zone",
    "opening_threshold": "opening_criterion_no_zone",
    "count_threshold": "zone_feeds_no_criterion",  # PB-23: a zone a count of 0 never hears
}


THERMOSTAT_KIND = "thermostat_kind"


def _thermostat_kind_field(control: Mapping[str, Any]) -> vol.Optional:
    """Decision 1: what is wired to the gateway's thermostat terminals — no default: a gateway
    topology needs an answer; one this version cannot read is offered to be answered again."""
    kind = parse_thermostat_kind(control.get(THERMOSTAT_KIND))
    return vol.Optional(
        THERMOSTAT_KIND,
        description={"suggested_value": kind.value} if kind is not None else None,
    )


# The write paths each boiler class may take (R1): the setpoint paths for a flow-setpoint
# boiler, the relay for an on/off boiler; the other classes are monitored only.
_PATHS_BY_CLASS: Mapping[str, tuple[str, ...]] = {
    BoilerClass.FLOW_SETPOINT.value: (
        WritePath.ENTITY.value,
        WritePath.OPENTHERM_GW.value,
        WritePath.OTGW_MQTT.value,
    ),
    BoilerClass.ON_OFF.value: (WritePath.RELAY.value,),
}


def wants_control(options: Mapping[str, Any]) -> bool:
    """Full control or on/off chosen on the second panel: the setup goes through the control
    steps (I6, decision 11). The control switch starts off all the same."""
    mode = _known(ControlMode, _stored_boiler(options).get(CONTROL_MODE))
    return mode in (ControlMode.FULL, ControlMode.ON_OFF)


def control_mode_off(options: Mapping[str, Any]) -> bool:
    """Monitoring only, or room values until 0.3, chosen on the second panel (decision 6)."""
    mode = _known(ControlMode, _stored_boiler(options).get(CONTROL_MODE))
    return mode in (ControlMode.MONITOR, ControlMode.ROOM_VALUES)


def paths_for_class(options: Mapping[str, Any]) -> list[str]:
    """The write paths the form offers for the boiler class: "no control" and those that suit
    it; "no control" alone where the control mode keeps control off."""
    if control_mode_off(options):
        return [NO_CONTROL]
    connection = stored_connection(options)
    if connection is not None:
        path = CONNECTION_PATH[connection]  # I6, decision 2
        return [NO_CONTROL] if path is None else [NO_CONTROL, path.value]
    boiler_class = _stored_boiler(options).get("class")
    return [NO_CONTROL, *_PATHS_BY_CLASS.get(str(boiler_class), ())]


def stored_heat_source(options: Mapping[str, Any]) -> HeatSource | None:
    """The heat source the first panel stored; ``None`` for an entry made before it — every field
    shown, as before (I6, decision 7)."""
    return _known(HeatSource, _stored_boiler(options).get(HEAT_SOURCE))


# What one heat source lacks (I6, decision 7): an electric boiler has no flue gas; an oil boiler
# no gas meter.
_SIGNALS_NOT_FOR = {HeatSource.ELECTRIC: ("flue_gas",), HeatSource.OIL: ("gas_meter",)}
# Gas per hour at minimum and maximum power: a gas boiler's, or one whose fuel is not said.
_GAS_RATES = ("gas_at_min_power", "gas_at_max_power")
# The flue-gas limits: they judge a condensing boiler only (the alarm is off for any other).
FLUE_GAS_LIMITS = ("flue_gas_warning", "flue_gas_alarm")


def signal_shown(options: Mapping[str, Any], key: str, simple: bool) -> bool:
    """Whether the signals step shows a signal: by the level, and by the heat source."""
    source = stored_heat_source(options)
    if source is not None and key in _SIGNALS_NOT_FOR.get(source, ()):
        return False
    return simple or options.get(LEVEL) == LEVEL_ADVANCED


def gas_rates_shown(options: Mapping[str, Any]) -> bool:
    return stored_heat_source(options) not in (HeatSource.ELECTRIC, HeatSource.OIL)


def flue_gas_limits_shown(options: Mapping[str, Any]) -> bool:
    """A condensing boiler's, or one never declared otherwise (as before)."""
    return _stored_boiler(options).get("condensing") is not False


def stored_connection(options: Mapping[str, Any]) -> Connection | None:
    """How the boiler is connected, as the first panel stored it; ``None`` for an entry made
    before the question, or an answer this version cannot read (the save names it)."""
    return _known(Connection, _stored_boiler(options).get(CONNECTION))


def control_schema(
    options: dict[str, Any], suggested: Mapping[str, Any] | None = None
) -> vol.Schema:
    """The first control step. ``suggested``: what the connection suggests where nothing is
    stored (I6, decision 2) — the virtual topology for a controller on Home Assistant's side, the
    gateway's own read-backs."""
    control = options.get(CONTROL, {})
    shown = {**(suggested or {}), **{k: v for k, v in control.items() if v not in (None, "")}}
    paths = paths_for_class(options)
    stored = control.get("write_path", NO_CONTROL)
    # A stored path the class no longer suits is not offered: the user chooses again.
    default = stored if stored in paths else vol.UNDEFINED
    return vol.Schema(
        {
            vol.Required("write_path", default=default): _select("write_path", paths),
            _optional("topology", shown): _select("topology", [t.value for t in Topology]),
            # Asked with a gateway topology only; the form cannot hide it for the others, chosen
            # on this same page (its text says so), and the save drops it for them.
            _thermostat_kind_field(control): _select(
                THERMOSTAT_KIND, [kind.value for kind in ThermostatKind]
            ),
            _optional("confirmed_entity", shown): _entity(_READ_BACK_ENTITY),
            _optional("ch_confirmed_entity", shown): _entity(_ECHO_ENTITY),
            # With an OpenTherm thermostat on a gateway (its text says so): its own request,
            # which a fall-back after an outage shows. The form cannot show it only for that
            # topology, chosen on this same page; the plugin reads it only with it.
            _optional("thermostat_setpoint_entity", control): _entity(_THERMOSTAT_SETPOINT_ENTITY),
            _optional("restart_entity", control): _entity(_RESTART_ENTITY),
        }
    )


# What a connection with writable entities offers where nothing is stored (I6, decision 2): the
# setpoint's write type, the heating switch's, and the hand-back — ESPHome holds both and has no
# own control to return to; EMS-ESP's setpoint lapses within about a minute.
_ENTITY_DEFAULTS: Mapping[Connection, tuple[str, str, Any]] = {
    Connection.ESPHOME: (WriteType.HELD.value, WriteType.HELD.value, HandBack.VALUE.value),
    Connection.EMS_ESP: (WriteType.EXPIRING.value, WriteType.UNKNOWN.value, HandBack.TIMEOUT.value),
}
_NO_ENTITY_DEFAULTS = (WriteType.UNKNOWN.value, WriteType.UNKNOWN.value, vol.UNDEFINED)


def control_entity_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})
    connection = stored_connection(options)
    defaults = _ENTITY_DEFAULTS.get(connection) if connection is not None else None
    write_type, ch_write_type, hand_back = defaults or _NO_ENTITY_DEFAULTS
    fields: dict[Any, Any] = {
        vol.Required(
            "setpoint_entity", default=control.get("setpoint_entity", vol.UNDEFINED)
        ): _entity(_SETPOINT_ENTITY),
        vol.Required("write_type", default=control.get("write_type", write_type)): _select(
            "write_type", [t.value for t in WriteType]
        ),
        _optional("ch_entity", control): _entity(_ON_OFF_ENTITY),
        vol.Required("ch_write_type", default=control.get("ch_write_type", ch_write_type)): (
            _select("write_type", [t.value for t in WriteType])
        ),
        vol.Required("hand_back", default=control.get("hand_back", hand_back)): _select(
            "hand_back", [h.value for h in HandBack]
        ),
        _optional("hand_back_value", control): _number(
            *CONTROL_BOUNDS["hand_back_value"], 0.5, "°C"
        ),
        _optional("hand_back_value_effect", control): _select(
            "hand_back_value_effect", [e.value for e in ValueEffect]
        ),
        _optional("hand_back_entity", control): _entity(_ON_OFF_ENTITY),
        vol.Required(
            "hand_back_entity_write_type",
            default=control.get("hand_back_entity_write_type", WriteType.UNKNOWN.value),
        ): _select("write_type", [t.value for t in WriteType]),
        # The timeout method's device timeout (decision 5 of 0.2.3), shown with its cautious
        # default; the form cannot hide it for the other methods, and the save drops it there.
        vol.Optional(
            HAND_BACK_TIMEOUT,
            description={
                "suggested_value": control.get(HAND_BACK_TIMEOUT, HAND_BACK_TIMEOUT_DEFAULT_MIN)
            },
        ): _number(*HAND_BACK_TIMEOUT_MIN, 1, "min"),
    }
    if _offers_own_room_controller(control):
        # Next to the hand-back fields, at the simple level; off by default (answers F, M).
        fields[
            vol.Required(OWN_ROOM_CONTROLLER, default=control.get(OWN_ROOM_CONTROLLER) is True)
        ] = selector.BooleanSelector()
    if connection is Connection.ESPHOME:
        # Decision 3: never pre-filled, as the relay's separate-contact tick (answer G).
        fields[
            vol.Required(ESPHOME_SAFE_START, default=control.get(ESPHOME_SAFE_START) is True)
        ] = selector.BooleanSelector()
    return vol.Schema(fields)


def _offers_own_room_controller(control: Mapping[str, Any]) -> bool:
    """The tick "the boiler has its own room controller" is offered on the entity path with
    the virtual topology — not with a gateway (answer M) — and on the relay step."""
    try:
        path = WritePath(str(control.get("write_path")))
    except ValueError:
        return False
    if path is WritePath.RELAY:
        return True
    try:
        topology = Topology(str(control.get("topology")))
    except ValueError:
        return False
    return own_room_controller_offered(path, topology)


def control_gateway_schema(options: dict[str, Any], gateways: list[str]) -> vol.Schema:
    control = options.get(CONTROL, {})
    current = control.get("gateway_id") or (gateways[0] if len(gateways) == 1 else vol.UNDEFINED)
    field: Any = (
        selector.SelectSelector(
            # Only a gateway set up and enabled in Home Assistant can take a write (P-106).
            selector.SelectSelectorConfig(
                options=gateways, custom_value=False, mode=selector.SelectSelectorMode.DROPDOWN
            )
        )
        if gateways
        else str
    )
    return vol.Schema({vol.Required("gateway_id", default=current): field})


def control_mqtt_schema(options: dict[str, Any]) -> vol.Schema:
    """The firmware's topics; where the control options have none, the first panel's (I6)."""
    control = options.get(CONTROL, {})
    boiler = _stored_boiler(options)
    top = control.get("mqtt_top", boiler.get("mqtt_top", "OTGW"))
    node = control.get("mqtt_node", boiler.get("mqtt_node", vol.UNDEFINED))
    return vol.Schema(
        {
            vol.Required("mqtt_top", default=top): str,
            vol.Required("mqtt_node", default=node): str,
        }
    )


ACTIVATION_DELAY = "activation_delay_s"


def activation_delay_field(
    control: Mapping[str, Any], vt_delay: float | None = None
) -> dict[Any, Any]:
    """VT's activation delay (decision 5), 0–600 s in steps of 10, at every level: the stored
    value, else VT's own where VT kept one (``vt_delay``, read from VT's central entry), else 0 —
    offered for the user to confirm by saving, never taken silently. The relay path's behaviour
    step shows the same field (X8)."""
    stored = control.get(ACTIVATION_DELAY)
    if stored is None:
        stored = CONTROL_DEFAULTS[ACTIVATION_DELAY] if vt_delay is None else vt_delay
    return {
        vol.Required(ACTIVATION_DELAY, default=stored): _number(
            *CONTROL_BOUNDS[ACTIVATION_DELAY], 10, "s"
        )
    }


def control_curve_schema(options: dict[str, Any], vt_delay: float | None = None) -> vol.Schema:
    control = options.get(CONTROL, {})
    curve = control.get("curve", {})

    def default(key: str) -> Any:
        return control.get(key, CONTROL_DEFAULTS[key])

    fields: dict[Any, Any] = {
        vol.Required("design_outdoor", default=design_outdoor_of(options)): _number(
            *CURVE_BOUNDS["design_outdoor"], 0.5, "°C"
        ),
        # The curve is the user's to enter: no silent default for the design flow.
        vol.Required("design_flow", default=curve.get("design_flow", vol.UNDEFINED)): _number(
            *CURVE_BOUNDS["design_flow"], 0.5, "°C"
        ),
        vol.Required("hard_min", default=default("hard_min")): _number(
            *CONTROL_BOUNDS["hard_min"], 0.5, "°C"
        ),
        vol.Required("hard_max", default=default("hard_max")): _number(
            *CONTROL_BOUNDS["hard_max"], 0.5, "°C"
        ),
        **activation_delay_field(control, vt_delay),
    }
    if _advanced(options):
        fields |= {
            vol.Required("room", default=curve.get("room", CURVE_DEFAULTS["room"])): _number(
                *CURVE_BOUNDS["room"], 0.5, "°C"
            ),
            _optional("exponent", curve): _number(*CURVE_BOUNDS["exponent"], 0.05),
            vol.Required("offset", default=curve.get("offset", CURVE_DEFAULTS["offset"])): (
                _number(*CURVE_BOUNDS["offset"], 0.5, "K")
            ),
            vol.Required("ceiling_band", default=default("ceiling_band")): _number(
                *CONTROL_BOUNDS["ceiling_band"], 0.5, "K"
            ),
            _optional("fallback_setpoint", control): _number(
                *CONTROL_BOUNDS["fallback_setpoint"], 0.5, "°C"
            ),
            vol.Required("frost_limit", default=default("frost_limit")): _number(
                *CONTROL_BOUNDS["frost_limit"], 0.5, "°C"
            ),
            vol.Required("frost_release", default=default("frost_release")): _number(
                *CONTROL_BOUNDS["frost_release"], 0.5, "°C"
            ),
            _optional("frost_zone", control): selector.EntitySelector(
                selector.EntitySelectorConfig(include_entities=_zone_entities(options))
            ),
        }
    return vol.Schema(fields)


def _zone_entities(options: dict[str, Any]) -> list[str]:
    return [zone["entity_id"] for zone in options.get(ZONES, []) if zone.get("entity_id")]


# --- the relay path (X8) ------------------------------------------------------------------------

RELAY_ENTITY = "relay_entity"
RELAY_TIMER_MIN = "relay_off_timer_min"
HEATS_ABOVE = "boiler_heats_above_w"
RELAY_STEP_KEYS = (*RELAY_KEYS, OWN_ROOM_CONTROLLER)


def control_relay_schema(
    options: dict[str, Any], prefill: VtCentralBoiler | None = None
) -> vol.Schema:
    """The relay and its own settings (R3) — the user's declaration, each with its cautious
    default — and the tick "the boiler has its own room controller" (answer M). ``prefill``:
    VT's central boiler, whose relay and repeat interval are offered for confirmation where
    nothing is stored yet (R14). The separate-contact tick is never pre-filled (answer G)."""
    control = options.get(CONTROL, {})

    def choice(key: str, kind: type[StrEnum]) -> Any:
        return _choice(control.get(key), kind, RELAY_DEFAULTS[key])

    relay = control.get(RELAY_ENTITY) or (prefill.relay if prefill is not None else None)
    repeat = control.get("relay_repeat_s")
    if repeat in (None, "") and prefill is not None:
        repeat = prefill.repeat_s
    fields: dict[Any, Any] = {
        vol.Required(RELAY_ENTITY, default=relay or vol.UNDEFINED): _entity(_RELAY_ENTITY),
        vol.Required(
            "relay_is_separate_contact", default=control.get("relay_is_separate_contact") is True
        ): selector.BooleanSelector(),
        vol.Required(
            "relay_reports_state", default=choice("relay_reports_state", RelayReports)
        ): _select("relay_reports_state", [r.value for r in RelayReports]),
        vol.Required(
            "relay_power_on_state", default=choice("relay_power_on_state", RelayPowerOn)
        ): _select("relay_power_on_state", [p.value for p in RelayPowerOn]),
        vol.Required("relay_off_timer", default=choice("relay_off_timer", RelayTimer)): _select(
            "relay_off_timer", [t.value for t in RelayTimer]
        ),
        # 10 to 120 min (K4.2); the box takes less, so the step answers it with its own
        # translated error rather than Home Assistant's untranslated range check.
        _optional(RELAY_TIMER_MIN, control): _number(1, 120, 1, "min"),
        _optional("relay_repeat_s", {"relay_repeat_s": repeat}): _number(10, 300, 10, "s"),
        vol.Required("relay_rest_state", default=choice("relay_rest_state", RelayRest)): _select(
            "relay_rest_state", [r.value for r in RelayRest]
        ),
        vol.Required(
            OWN_ROOM_CONTROLLER, default=control.get(OWN_ROOM_CONTROLLER) is True
        ): selector.BooleanSelector(),
    }
    if _advanced(options):
        fields[_optional(HEATS_ABOVE, control)] = _number(10, 10000, 10, "W")
    return vol.Schema(fields)


def relay_entity_error(
    hass: HomeAssistant, options: Mapping[str, Any], entity: object
) -> str | None:
    """R2, in the form: the relay is a switch, or a boiler thermostat entity that can be set to
    both heat and off — never a helper; one no VT thermostat drives for a room; no entity of the
    boiler's gateway integration or of VT; none the options already use in another role. The
    error key, or ``None``."""
    if not isinstance(entity, str) or "." not in entity:
        return "entity_not_suitable"
    if entity.split(".", 1)[0] not in RELAY_DOMAINS:
        return "relay_domain_not_supported"
    modes = relay_hvac_modes(hass.states.get(entity))
    if entity.startswith("climate.") and modes is not None and not {"heat", "off"} <= modes:
        return "relay_climate_modes"
    if relay_used_by_zone(hass, entity):
        return "relay_used_by_zone"
    if relay_of_boiler_interface(hass, entity):
        return "relay_of_boiler_interface"
    from .config import named_entities

    fields = named_entities(options).get(entity, ())
    if any(field != f"{CONTROL}.{RELAY_ENTITY}" for field in fields):
        return "relay_in_another_role"
    return None


def apply_control_relay(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The relay step's answers; the power threshold kept where its field is not shown, and a
    timer's length only with a declared length."""
    control = dict(options.get(CONTROL, {}))
    shown = [key for key in RELAY_STEP_KEYS if key != HEATS_ABOVE or _advanced(options)]
    _set_or_drop(control, user_input, tuple(shown))
    if control.get("relay_off_timer") != RelayTimer.MINUTES:
        control.pop(RELAY_TIMER_MIN, None)
    options[CONTROL] = control


# The relay path's behaviour step: its demand thresholds, learning pauses and frost fields at the
# advanced level (``CONTROL_ADVANCED_KEYS``), VT's activation delay at every level (decision 5).
RELAY_BEHAVIOUR_KEYS = (
    "count_threshold",
    "power_threshold_kw",
    "opening_threshold",
    "learning_pauses",
    "frost_limit",
    "frost_release",
    "frost_zone",
)


def control_relay_behaviour_schema(
    options: dict[str, Any], prefill: VtCentralBoiler | None = None
) -> vol.Schema:
    """The relay path's behaviour (R5, R14): VT's activation delay, shown at every level and
    pre-filled from VT's own; at the advanced level the demand thresholds — pre-filled with VT's
    as it used them — learning pauses and frost protection, moved here from the curve step,
    which the relay path does not have."""
    control = options.get(CONTROL, {})
    vt_delay = None if prefill is None else prefill.activation_delay_s
    fields: dict[Any, Any] = {**activation_delay_field(control, vt_delay)}
    if not _advanced(options):
        return vol.Schema(fields)

    def default(key: str) -> Any:
        return control.get(key, CONTROL_DEFAULTS[key])

    count = control.get("count_threshold")
    if count is None and prefill is not None and prefill.count_threshold is not None:
        count = prefill.count_threshold
    power = control.get("power_threshold_kw")
    if power in (None, "") and prefill is not None:
        power = prefill.power_threshold_kw
    fields |= {
        vol.Required(
            "count_threshold",
            default=CONTROL_DEFAULTS["count_threshold"] if count is None else count,
        ): _number(*CONTROL_BOUNDS["count_threshold"], 1),
        _optional("power_threshold_kw", {"power_threshold_kw": power}): _number(
            *CONTROL_BOUNDS["power_threshold_kw"], 0.1, "kW"
        ),
        _optional("opening_threshold", control): _number(
            *CONTROL_BOUNDS["opening_threshold"], 1, "%"
        ),
        vol.Required("learning_pauses", default=default("learning_pauses")): (
            selector.BooleanSelector()
        ),
        vol.Required("frost_limit", default=default("frost_limit")): _number(
            *CONTROL_BOUNDS["frost_limit"], 0.5, "°C"
        ),
        vol.Required("frost_release", default=default("frost_release")): _number(
            *CONTROL_BOUNDS["frost_release"], 0.5, "°C"
        ),
        _optional("frost_zone", control): selector.EntitySelector(
            selector.EntitySelectorConfig(include_entities=_zone_entities(options))
        ),
    }
    return vol.Schema(fields)


def apply_control_relay_behaviour(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    keys: tuple[str, ...] = (ACTIVATION_DELAY,)
    if _advanced(options):
        keys += RELAY_BEHAVIOUR_KEYS
    _set_or_drop(control, user_input, keys)
    options[CONTROL] = control


def control_behaviour_schema(options: dict[str, Any]) -> vol.Schema:
    control = options.get(CONTROL, {})

    def required(key: str, field: Any) -> dict[Any, Any]:
        return {vol.Required(key, default=control.get(key, CONTROL_DEFAULTS[key])): field}

    return vol.Schema(
        {
            **required("ramp_k_per_min", _number(*CONTROL_BOUNDS["ramp_k_per_min"], 0.1, "K/min")),
            **required(
                "decision_interval_min", _number(*CONTROL_BOUNDS["decision_interval_min"], 1, "min")
            ),
            # EMS-ESP's "off" is its own 0 (I6, decision 4): nothing to choose there.
            **(
                {}
                if fixed_off(options)
                else required("off_setpoint", _number(*CONTROL_BOUNDS["off_setpoint"], 0.5, "°C"))
            ),
            **required("count_threshold", _number(*CONTROL_BOUNDS["count_threshold"], 1)),
            _optional("power_threshold_kw", control): _number(
                *CONTROL_BOUNDS["power_threshold_kw"], 0.1, "kW"
            ),
            _optional("opening_threshold", control): _number(
                *CONTROL_BOUNDS["opening_threshold"], 1, "%"
            ),
            **required("learning_pauses", selector.BooleanSelector()),
            **required("comfort_correction", selector.BooleanSelector()),
        }
    )


RETURN_KEY = "return_after_outside_change"
# SB-36 (decision 10 of 0.2.3): after the external-control switch's hand-back, its own opt-in.
RETURN_SWITCH_KEY = "return_after_switch_hand_back"


def _relay_path(options: Mapping[str, Any]) -> bool:
    control = options.get(CONTROL)
    return isinstance(control, Mapping) and control.get("write_path") == WritePath.RELAY


def reaction_alarms(options: Mapping[str, Any]) -> tuple[str, ...]:
    """The alarms whose reaction the form offers (decision 7): an ignored write, only where a
    hand-back returns the boiler to a thermostat or its own control — never stand-alone, with an
    undeclared effect, or on the relay path."""
    control = options.get(CONTROL)
    return REACTION_ALARMS if write_ignored_offered(control) else ()


def control_alarms_schema(options: dict[str, Any]) -> vol.Schema:
    """The alarm step: the reaction to an ignored write where it is offered, at both levels —
    a reaction stored earlier is never hidden (Y1); and, at the advanced level, the return by
    itself after another controller (not for relays), and where the hand-back turns off the
    external-control switch, its own opt-in for that method (SB-36), off by default."""
    control = options.get(CONTROL, {})
    reactions = control.get("alarm_reactions", {})
    choices = [r.value for r in AlarmReaction]
    fields: dict[Any, Any] = {
        vol.Required(alarm, default=reactions.get(alarm, AlarmReaction.INFO.value)): _select(
            "alarm_reaction", choices
        )
        for alarm in reaction_alarms(options)
    }
    if _advanced(options) and not _relay_path(options):
        # Off by default, confirmed twice (decision 6); not offered for relays.
        fields[vol.Required(RETURN_KEY, default=control.get(RETURN_KEY) is True)] = (
            selector.BooleanSelector()
        )
        if control.get("hand_back") == HandBack.SWITCH:
            fields[
                vol.Required(RETURN_SWITCH_KEY, default=control.get(RETURN_SWITCH_KEY) is True)
            ] = selector.BooleanSelector()
    return vol.Schema(fields)


def alarm_step_offered(options: Mapping[str, Any]) -> bool:
    """Whether the alarm step has anything to ask at the options' level."""
    return bool(control_alarms_schema(dict(options)).schema)


def control_return_confirm_schema() -> vol.Schema:
    return vol.Schema({vol.Required("understood", default=False): selector.BooleanSelector()})


def confirm_blocking_schema() -> vol.Schema:
    """Saving an edit that keeps control from running: off by default, nothing saved."""
    return vol.Schema({vol.Required("save_anyway", default=False): selector.BooleanSelector()})


CONTROL_STEP_KEYS = (
    "write_path",
    "topology",
    THERMOSTAT_KIND,
    "confirmed_entity",
    "ch_confirmed_entity",
    "thermostat_setpoint_entity",
    "restart_entity",
)


# What the relay path does not read (X8): it has no topology, no thermostat terminals and no
# setpoint read-back; a restart indicator of the relay's device stays a trace of an outage.
_NOT_FOR_RELAY = (
    "topology",
    THERMOSTAT_KIND,
    "confirmed_entity",
    "ch_confirmed_entity",
    "thermostat_setpoint_entity",
)


def apply_control(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The first control step: the write path, topology, what is wired to the gateway's
    thermostat terminals and read-backs; "none" removes control. A topology without thermostat
    terminals keeps no answer about them; the relay path keeps none of them but the restart
    indicator."""
    if user_input["write_path"] == NO_CONTROL:
        options.pop(CONTROL, None)
        return
    control = dict(options.get(CONTROL, {}))
    if control.get("write_path") != user_input["write_path"]:
        for key in TARGET_KEYS:
            control.pop(key, None)
    _set_or_drop(control, user_input, CONTROL_STEP_KEYS)
    if not _gateway_topology(control.get("topology")):
        control.pop(THERMOSTAT_KIND, None)
    if user_input["write_path"] == WritePath.RELAY:
        for key in _NOT_FOR_RELAY:
            control.pop(key, None)
    options[CONTROL] = control


def _gateway_topology(raw: object) -> bool:
    try:
        return Topology(str(raw)) in GATEWAY_TOPOLOGIES
    except ValueError:
        return False


def apply_control_details(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The writable-entity step's answers; the device's timeout only with the timeout method."""
    control = dict(options.get(CONTROL, {}))
    keys = TARGET_KEYS
    _set_or_drop(control, user_input, tuple(k for k in keys if k in user_input or k in control))
    if control.get("hand_back") != HandBack.TIMEOUT:
        control.pop(HAND_BACK_TIMEOUT, None)
    options[CONTROL] = control


def water_limits(options: Mapping[str, Any]) -> dict[str, str]:
    """The curve step's (decision 10 of I6): the boiler's and the first circuit's maxima, which
    cap the water with the step's own highest temperature — the lowest of them applies; "—"
    where one is not entered."""
    params = options.get(PARAMETERS)
    circuits = options.get(CIRCUITS)
    boiler = params.get("max_ch_setpoint") if isinstance(params, Mapping) else None
    first = circuits[0] if isinstance(circuits, list) and circuits else None
    circuit = first.get("max_flow") if isinstance(first, Mapping) else None
    return {"boiler_max": _degrees(boiler), "circuit_max": _degrees(circuit)}


def _degrees(value: object) -> str:
    """A stored temperature as the form shows it; anything but a number (none stored, a hand
    edit) as "—"."""
    if isinstance(value, bool) or not isinstance(value, int | float):
        return "—"
    return f"{value:g} °C"


def apply_control_curve(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    curve = dict(control.get("curve", {}))
    # I6: the design outdoor temperature is the building's, one value with the curve's.
    curve.pop("design_outdoor", None)
    options[PARAMETERS] = {
        **options.get(PARAMETERS, {}),
        "design_outdoor": user_input["design_outdoor"],
    }
    shown = CURVE_KEYS if _advanced(options) else ("design_flow",)
    for key in shown:
        value = user_input.get(key)
        if value in (None, ""):
            curve.pop(key, None)
        else:
            curve[key] = value
    control["curve"] = curve
    keys = ["hard_min", "hard_max", ACTIVATION_DELAY]
    if _advanced(options):
        keys += ["ceiling_band", "fallback_setpoint", "frost_limit", "frost_release", "frost_zone"]
    _set_or_drop(control, user_input, tuple(keys))
    options[CONTROL] = control


def apply_control_behaviour(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    control = dict(options.get(CONTROL, {}))
    _set_or_drop(control, user_input, tuple(control_behaviour_schema(options).schema))
    options[CONTROL] = control


def apply_control_alarms(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    """The alarm step's answers: only the fields it showed are changed (Y1)."""
    shown = {str(marker) for marker in control_alarms_schema(options).schema}
    control = dict(options.get(CONTROL, {}))
    control["alarm_reactions"] = {
        alarm: user_input[alarm] for alarm in reaction_alarms(options) if alarm in user_input
    }
    if RETURN_KEY in shown:
        # The switch's own opt-in is dropped where it is not shown: a method changed away from
        # the switch and back does not bring an old tick back unseen (SB-36).
        for key in (RETURN_KEY, RETURN_SWITCH_KEY):
            if key in shown and user_input.get(key) is True:
                control[key] = True
            else:
                control.pop(key, None)  # off: the default
    options[CONTROL] = control


def _set_or_drop(target: dict[str, Any], user_input: dict[str, Any], keys: tuple[Any, ...]) -> None:
    for key in (str(k) for k in keys):
        value = user_input.get(key)
        if value in (None, ""):
            target.pop(key, None)
        else:
            target[key] = value


# The first control step's entity fields and what each takes (checked again on submit, P-79).
CONTROL_ENTITY_FIELDS: Mapping[str, EntityFilter] = {
    "confirmed_entity": _READ_BACK_ENTITY,
    "ch_confirmed_entity": _ECHO_ENTITY,
    "thermostat_setpoint_entity": _THERMOSTAT_SETPOINT_ENTITY,
    "restart_entity": _RESTART_ENTITY,
}
# The writable-entity step's entity fields.
TARGET_ENTITY_FIELDS: Mapping[str, EntityFilter] = {
    "setpoint_entity": _SETPOINT_ENTITY,
    "ch_entity": _ON_OFF_ENTITY,
    "hand_back_entity": _ON_OFF_ENTITY,
}


def control_error(
    user_input: dict[str, Any], options: Mapping[str, Any] | None = None
) -> dict[str, str]:
    """What the first control step needs: a write path the boiler class suits (X8; ``options``:
    the options it is chosen in, where known); every write is checked against a read-back, and
    the topology decides what a hand-back does — both required, and suited to the write path
    (one table with the blockers, P-44). A gateway topology needs the answer about its
    thermostat terminals, one that fits it (decision 1). The relay needs none of them: its own
    state is its read-back, and its rest state what a hand-back does."""
    path = user_input.get("write_path")
    if path in (None, NO_CONTROL):
        return {}
    connection = None if options is None else stored_connection(options)
    if options is not None and control_mode_off(options):
        return {"write_path": "path_not_for_control_mode"}  # I6, decision 6
    if options is not None and path not in paths_for_class(options):
        # I6, decision 2: the connection decides the path where it is answered.
        return {
            "write_path": "path_not_for_connection" if connection else "path_not_for_boiler_class"
        }
    if path == WritePath.RELAY:
        return {}
    if not user_input.get("confirmed_entity"):
        return {"confirmed_entity": "confirmed_entity_missing"}
    topology = user_input.get("topology")
    if not topology:
        return {"topology": "topology_missing"}
    if Topology(topology) is Topology.MONITOR_MODE:
        return {"topology": "topology_no_control"}
    if Topology(topology) not in PATH_TOPOLOGIES[WritePath(path)]:
        return {"topology": "topology_not_for_path"}
    if connection in VIRTUAL_CONNECTIONS and Topology(topology) is not Topology.VIRTUAL:
        return {"topology": "topology_not_for_connection"}  # a controller on HA's side
    if Topology(topology) in GATEWAY_TOPOLOGIES:
        kind = parse_thermostat_kind(user_input.get(THERMOSTAT_KIND))
        if kind is None:
            return {THERMOSTAT_KIND: "thermostat_kind_missing"}
        if kind_contradicts_topology(Topology(topology), kind):
            return {THERMOSTAT_KIND: "thermostat_kind_contradicts_topology"}
    thermostat = user_input.get("thermostat_setpoint_entity")
    if thermostat and thermostat == user_input.get("confirmed_entity"):
        # The boiler's read-back shows the plugin's value, not the thermostat's own request.
        return {"thermostat_setpoint_entity": "thermostat_setpoint_same_as_read_back"}
    return {}


def mqtt_set_up(hass: HomeAssistant) -> bool:
    """P-69: the MQTT integration is set up and running, so a published command goes out."""
    return any(
        entry.state is ConfigEntryState.LOADED
        for entry in hass.config_entries.async_entries(
            MQTT_DOMAIN, include_ignore=False, include_disabled=False
        )
    )


def targets_used_by_zone(hass: HomeAssistant, user_input: Mapping[str, Any]) -> dict[str, str]:
    """PB-54: the entity path's write targets checked against the entities VT thermostats
    drive, as the relay is (R2) — VT's toggles would read as another controller's."""
    return {
        key: "entity_used_by_zone"
        for key in TARGET_ENTITY_FIELDS
        if isinstance(user_input.get(key), str) and relay_used_by_zone(hass, user_input[key])
    }


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
    if method == HandBack.SWITCH:
        if not user_input.get("hand_back_entity"):
            return {"hand_back_entity": "hand_back_entity_missing"}
        if user_input["hand_back_entity"] in (
            user_input.get("ch_entity"),
            user_input.get("setpoint_entity"),
        ):
            # One entity, one role (P-03, T-38): each hand-back would switch it on and off.
            return {"hand_back_entity": "hand_back_switch_is_heating_switch"}
        if user_input.get("hand_back_entity_write_type") not in writable:
            # Turned on at every take and off at every hand-back: never a stored setting (P-40).
            return {"hand_back_entity_write_type": "hand_back_entity_write_type_not_supported"}
    if method == HandBack.TIMEOUT and user_input.get("write_type") != WriteType.EXPIRING:
        # Only a value that lapses goes back on its own; any other would stay for good.
        return {"hand_back": "hand_back_timeout_not_expiring"}
    if (
        user_input.get(OWN_ROOM_CONTROLLER) is True
        and method == HandBack.VALUE
        and user_input.get("hand_back_value_effect") == ValueEffect.HEATING_STOPS
    ):
        # Nothing would be left for the boiler's own room controller to take over.
        return {OWN_ROOM_CONTROLLER: "own_room_controller_but_heating_stops"}
    return {}


def control_of(options: dict[str, Any]) -> ControlOptions | None:
    """The control options as the plugin reads them; ``None`` while they cannot be read (the
    save's own check then names the problem)."""
    try:
        return EntryConfig.from_options(options).control
    except AttributeError, ConfigError, KeyError, TypeError, ValueError:
        return None


def fixed_off(options: Mapping[str, Any]) -> bool:
    """EMS-ESP without a heating switch: "off" is its own setpoint 0 (I6, decision 4), not the
    option — neither asked nor checked."""
    control = options.get(CONTROL)
    return (
        stored_connection(options) is Connection.EMS_ESP
        and isinstance(control, Mapping)
        and control.get("write_path") == WritePath.ENTITY
        and not heating_writes(control)
    )


def off_too_close_in(options: Mapping[str, Any], hard_min: float | None = None) -> bool:
    """P-25: on a path without heating writes, "off" (stored, else its default) must stay at
    least 1 K below the lowest water temperature (``hard_min``: as entered, else stored). With a
    heating switch "off" is no setpoint: nothing to check. Decision 11 blocks control without
    one in 0.2.2; the check stays for when K4 lifts the block."""
    control = options.get(CONTROL)
    if not isinstance(control, Mapping) or not control.get("write_path"):
        return False
    if heating_writes(control) or fixed_off(options):
        return False
    try:
        off = float(control.get("off_setpoint", CONTROL_DEFAULTS["off_setpoint"]))
        lowest = float(control.get("hard_min", CONTROL_DEFAULTS["hard_min"]))
    except TypeError, ValueError:
        return False  # the save's own check names options that cannot be read
    return off_too_close_to_lowest(off, lowest if hard_min is None else hard_min)


def options_blockers(options: Mapping[str, Any]) -> list[str] | None:
    """The blockers the configuration itself gives control (no run-time ones); ``None`` without
    a control section, or where the options cannot be read."""
    try:
        config = EntryConfig.from_options(options)
    except AttributeError, KeyError, TypeError, ValueError:
        return None
    if not config.control.configured:
        return None
    return config_blockers(
        config.control,
        config.installation,
        config.shared_signals,
        signals=config.signals,
        others=config.watched_entities,
    )


def hand_back_value_problem(options: dict[str, Any], problem: str) -> bool:
    """Whether the options have this problem with the hand-back value (S-21, S-49), as the
    blockers find it."""
    control = control_of(options)
    return control is not None and problem in hand_back_value_problems(control)


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
ADVANCED_BUILDING_PARAMETERS = ("loss_coefficient", "heating_threshold")
# Parameters shown at both levels: emptied in the form, they go.
SIMPLE_PARAMETERS = ("boiler_min_power", "boiler_max_power", "design_outdoor")


def apply_signals(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    signals = _stored_signals(options)
    for key, (_filter, simple) in SIGNAL_FIELDS.items():
        if signal_shown(options, key, simple):  # one not shown keeps what is stored
            if user_input.get(key):
                signals[key] = user_input[key]
            else:
                signals.pop(key, None)
    options[SIGNALS] = signals
    options[WEATHER] = user_input.get(WEATHER) or None


def signal_fields(options: dict[str, Any]) -> dict[str, EntityFilter]:
    """The signals step's entity fields at the options' level, and what each takes."""
    fields: dict[str, EntityFilter] = {
        key: filter_
        for key, (filter_, simple) in SIGNAL_FIELDS.items()
        if signal_shown(options, key, simple)
    }
    fields[WEATHER] = {"domain": "weather"}  # no signal: it may be any weather entity
    return fields


def shared_signal_error(options: dict[str, Any], user_input: dict[str, Any]) -> dict[str, str]:
    """X5.2 (P-16, T-32): one entity feeds one signal — no pair may share one in 0.2.2
    (provisional, K4). Refused on the later field in the form's order; where that field is not
    shown at this level (a stored advanced signal), on the earlier one, which is. A field left
    empty is never a duplicate."""
    candidate = copy.deepcopy(options)
    apply_signals(candidate, user_input)
    shown = set(signal_fields(options))
    owner: dict[str, str] = {}
    for key in SIGNAL_FIELDS:
        entity = candidate[SIGNALS].get(key)
        if not entity:
            continue
        first = owner.setdefault(str(entity), key)
        if first != key:
            field = key if key in shown else first if first in shown else "base"
            return {field: "entity_for_two_signals"}
    return {}


def apply_boiler(options: dict[str, Any], user_input: dict[str, Any]) -> None:
    boiler = dict(options.get(BOILER, {}))
    boiler.update({k: user_input[k] for k in BOILER_KEYS if k in user_input})
    options[BOILER] = boiler
    _apply_parameters(options, user_input, BOILER_PARAMETER_KEYS)
    monitor = dict(options.get(MONITOR, {}))
    _set_or_drop(monitor, user_input, PRESSURE_KEYS)
    if monitor:
        options[MONITOR] = monitor
    else:
        options.pop(MONITOR, None)  # no section where nothing is set: the defaults apply


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
        elif key in SIMPLE_PARAMETERS or shown_advanced:
            params.pop(key, None)
    options[PARAMETERS] = params


def circuit_from_input(
    user_input: dict[str, Any],
    circuit_id: str,
    current: Mapping[str, Any] | None = None,
    advanced: bool = True,
) -> dict[str, Any]:
    """A circuit as the options store it. With a maximum, its too-hot alarm (decision 10): at
    the advanced level as entered, at the simple level as stored (its fields are hidden); where
    none is given, the pre-fill — the maximum + 5 K and 10 min — so never empty, and not changed
    by itself later. Without a maximum, no alarm."""
    circuit: dict[str, Any] = {"id": circuit_id, "control": user_input["control"]}
    for key in ("max_flow", "fixed_temperature", "flow_entity"):
        if user_input.get(key) not in (None, ""):
            circuit[key] = user_input[key]
    maximum = circuit.get("max_flow")
    if maximum is None:
        return circuit
    given = user_input if advanced else (current or {})
    alarm, minutes = given.get(MAX_FLOW_ALARM), given.get(MAX_FLOW_ALARM_MIN)
    circuit[MAX_FLOW_ALARM] = maximum + CIRCUIT_ALARM_RISE_K if alarm in (None, "") else alarm
    circuit[MAX_FLOW_ALARM_MIN] = CIRCUIT_ALARM_MIN if minutes in (None, "") else minutes
    return circuit


def circuit_left_with_zones(options: dict[str, Any], circuits: list[dict[str, Any]]) -> bool:
    """P-64: whether a zone still names a circuit the new list leaves out (a zone naming none
    takes the one circuit there is)."""
    ids = {str(circuit.get("id")) for circuit in circuits}
    return any(
        zone.get("circuit") not in (None, "") and str(zone["circuit"]) not in ids
        for zone in options.get(ZONES, [])
        if isinstance(zone, Mapping)
    )


# The control options that name an entity control writes to or reads (``ControlOptions.entities``).
CONTROL_ENTITY_KEYS = (
    "setpoint_entity",
    "ch_entity",
    "hand_back_entity",
    "confirmed_entity",
    "ch_confirmed_entity",
    "thermostat_setpoint_entity",
    "restart_entity",
    "relay_entity",
)


def boiler_side_entities(options: Mapping[str, Any]) -> list[str]:
    """What the plugin maps as a boiler signal, or control writes to or reads: a zone built on a
    climate of one of their devices would be the boiler's own thermostat (X5.19)."""
    signals = options.get(SIGNALS) or {}
    control = options.get(CONTROL) or {}
    found = [str(e) for e in signals.values() if e] if isinstance(signals, Mapping) else []
    if isinstance(control, Mapping):
        found += [str(control[key]) for key in CONTROL_ENTITY_KEYS if control.get(key)]
    return found


def _circuit_alarm_hidden(circuit: Mapping[str, Any]) -> bool:
    """A circuit's too-hot alarm set otherwise than its pre-fill (an advanced setting)."""
    maximum = circuit.get("max_flow")
    if maximum is None:
        return False
    alarm, minutes = circuit.get(MAX_FLOW_ALARM), circuit.get(MAX_FLOW_ALARM_MIN)
    return (alarm is not None and alarm != maximum + CIRCUIT_ALARM_RISE_K) or (
        minutes is not None and minutes != CIRCUIT_ALARM_MIN
    )


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
    """The monitor step's answers; the flue-gas limits it does not show, and the pressure limits
    the boiler step asks, are kept (I6)."""
    stored = options.get(MONITOR)
    kept = {
        key: stored[key]
        for key in (*FLUE_GAS_LIMITS, *PRESSURE_KEYS)
        if isinstance(stored, Mapping) and key in stored and key not in user_input
    }
    options[MONITOR] = {**kept, **user_input}


# The monitor's periods: how long the plugin has been watching, and over what the verdict is
# judged — "restore defaults" keeps them, as it keeps the facts (P-65); and the pressure limits,
# facts about the boiler (I6).
MONITOR_KEPT = ("monitoring_days", "verdict_window_days", *PRESSURE_KEYS)


def restore_advanced_defaults(options: dict[str, Any]) -> None:
    """Drop every tuning value only the advanced level shows, so its default applies again.
    Facts about the installation — what is mapped, the boiler, circuits, emitter sizes, values
    the user entered — stay (``SCOPE.md`` principle 10), and so do the monitor's periods."""
    options.get(REFERENCE_ROOM, {}).pop("switch_margin", None)
    monitor = options.get(MONITOR, {})
    kept = {key: monitor[key] for key in MONITOR_KEPT if key in monitor}
    if kept:
        options[MONITOR] = kept
    else:
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
    alarm_defaults = _schema_defaults(control_alarms_schema(advanced))
    control_defaults = (
        curve_defaults
        | _schema_defaults(control_behaviour_schema({}))
        | {RETURN_KEY: alarm_defaults[RETURN_KEY], RETURN_SWITCH_KEY: False}
    )
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
                *ADVANCED_BUILDING_PARAMETERS,
            )
        )
        or "design_load_kw" in options.get(BUILDING, {})
        or len(circuits) > 1
        or any("flow_entity" in c for c in circuits)
        or any(_circuit_alarm_hidden(c) for c in circuits)
        or any("reference_output_w" in z or "exponent" in z for z in zones)
        or any("threshold" in s for z in zones for s in z.get("foreign_heat", []))
        or _differ(
            options.get(REFERENCE_ROOM, {}),
            _schema_defaults(reference_schema(advanced)),
            ("switch_margin",),
        )
        or _differ(
            monitor,
            _schema_defaults(monitor_schema({})),
            [key for key in monitor if key not in PRESSURE_KEYS],  # the boiler step's (I6)
        )
        or _differ(
            control, control_defaults, [k for k in CONTROL_ADVANCED_KEYS if k != "alarm_reactions"]
        )
        # The ignored write's reaction is shown at both levels, and a stored one it does not
        # offer only informs (decision 7, Y1): none is hidden.
        or _differ(control.get("curve", {}), curve_defaults, ("room", "exponent", "offset"))
        # PB-71: a fact about the boiler the user gave at the advanced level; "restore
        # defaults" keeps it, as it keeps the other facts.
        or HEATS_ABOVE in control
    )


def validate_problem(options: dict[str, Any]) -> tuple[str, str | None] | None:
    """The first problem as a translation key and what it concerns, or None. Options this
    version cannot read at all are a problem too, shown on the signals step — never an
    exception at a save (P-70)."""
    try:
        EntryConfig.from_options(options)
    except ConfigError as err:
        return err.code, err.subject
    except AttributeError, KeyError, TypeError, ValueError:
        return "unreadable_options", None
    return None


_PROBLEM_STEPS = {
    "missing_signal": "signals",
    "no_circuit": "circuit",
    "duplicate_circuit": "circuit",
    "unknown_circuit": "circuit",
    "fixed_temperature_missing": "circuit",
    "duplicate_zone": "zones",
    "zone_without_circuit": "zones",
    "reference_zone_unknown": "reference",
    "alarm_limits_out_of_order": "monitor",
    # A stored value this version does not know: its section's step (P-70).
    "invalid_boiler": "boiler",
    "invalid_circuit": "circuit",
    "invalid_zone": "zones",
    "invalid_reference": "reference",
    "invalid_monitor": "monitor",
    "invalid_building": "building",
    "invalid_freshness": "freshness",
    "invalid_signals": "signals",
    "invalid_parameters": "building",
    "unreadable_options": "signals",
    "invalid_control": "control",
    # I6 (decision 12): an answer of the first panels this version cannot read.
    "invalid_connection": "connection",
    # Found at the save (P-12): control took the boiler, or began to owe it a hand-back, after
    # the control steps were answered; what the hand-back goes through is picked there.
    "hand_back_pending": "control",
    "control_holds_boiler": "control",
    # Found at the save: a later step lowered a maximum under the hand-back value, or moved
    # "off" next to it.
    "hand_back_value_above_max": "control_entity",
    "off_setpoint_near_hand_back_value": "control_behaviour",
}


def _given(data: Mapping[str, Any], key: str) -> Any:
    """An answer as given; an emptied field (``None`` or ``""``) is no answer."""
    found = data.get(key)
    return None if found in (None, "") else found


def _hand_back_answer(data: Mapping[str, Any], key: str) -> Any:
    """A hand-back answer as given, or the default the form fills in for it. The device's
    timeout judges the timeout method only: with another, the save drops it."""
    if key == HAND_BACK_TIMEOUT and _given(data, "hand_back") != HandBack.TIMEOUT:
        return None
    found = _given(data, key)
    return _HAND_BACK_DEFAULTS.get(key) if found is None else found


def problem_step(code: str, subject: str | None) -> str:
    """The step where the user can fix a problem the last check found."""
    if code == "implausible_parameter":
        return "boiler" if subject in BOILER_PARAMETER_KEYS else "building"
    if code == "invalid_boiler" and subject in PANEL_BOILER_KEYS:
        return "connection"  # I6: the class, the hot water and condensing are the panels'
    if code in ("invalid_monitor", "alarm_limits_out_of_order") and subject in (
        *PRESSURE_KEYS,
        "pressure_high",
    ):
        return "boiler"  # I6: the pressure limits are the boiler step's
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
    _unfed_zones: str = ""  # PB-23: the zones a count of 0 could never hear, for the form

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
        if not hasattr(self, f"async_step_{step}"):
            step = "signals"  # a section this flow does not have (the setup has no freshness)
        self._problem = (step, {"base": code})
        return await self._goto(step)

    def _next_after(self, step: str) -> str:
        raise NotImplementedError

    async def _goto(self, step: str) -> ConfigFlowResult:
        result: ConfigFlowResult = await getattr(self, f"async_step_{step}")()
        return result

    async def async_step_connection(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The first panel (I6): how the boiler is connected, the heat source, the boiler type;
        then the MQTT topics for a connection over MQTT."""
        if user_input is not None:
            apply_connection(self.options, user_input)
            if Connection(user_input[CONNECTION]) in TOPIC_KEYS:
                return await self.async_step_mqtt_topics()
            return await self.async_step_mode()
        return self._form(step_id="connection", data_schema=connection_schema(self.options))

    async def async_step_mqtt_topics(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The topics the interface publishes under (I6, decision 9)."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = {
                key: "mqtt_topic_invalid"
                for key, value in user_input.items()
                if not mqtt_topic_valid(value)
            }
            if not errors:
                boiler = dict(_stored_boiler(self.options))
                boiler.update({key: str(value).strip() for key, value in user_input.items()})
                self.options[BOILER] = boiler
                return await self.async_step_mode()
        return self._form(
            step_id="mqtt_topics", data_schema=mqtt_topics_schema(self.options), errors=errors
        )

    async def async_step_mode(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The second panel (I6): the control mode the connection can do, condensing and the
        hot-water priority where they apply."""
        if user_input is not None:
            apply_mode(self.options, user_input)
            return await self._goto(self._next_after("mode"))
        return self._form(step_id="mode", data_schema=mode_schema(self.options))

    async def async_step_signals(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            modulation = user_input.get("modulation")
            state = self.hass.states.get(modulation) if modulation else None  # type: ignore[attr-defined]
            errors = entity_errors(self.hass, user_input, signal_fields(self.options))  # type: ignore[attr-defined]
            unit = None if state is None else state.attributes.get("unit_of_measurement")
            if not errors and unit not in (None, "%"):
                errors = {"modulation": "modulation_not_percent"}  # e.g. a power sensor
            if not errors:
                errors = shared_signal_error(self.options, user_input)
            if not errors:
                apply_signals(self.options, user_input)
                return await self._goto(self._next_after("signals"))
        connection = stored_connection(self.options)
        suggested: dict[str, str] = {}
        if connection is Connection.OPENTHERM_GW and not _stored_signals(self.options):
            # Only where nothing is mapped yet: a signal the user cleared is not offered again.
            suggested = gateway_entities(self.hass, GATEWAY_SIGNALS)  # type: ignore[attr-defined]
        return self._form(
            step_id="signals",
            data_schema=signals_schema(self.options, suggested),
            errors=errors,
            description_placeholders={"hint": await self._async_signal_hint()},
        )

    async def _async_signal_hint(self) -> str:
        """What to pick for the connection, then for the heat source, in Home Assistant's
        language; nothing for an entry made before the questions."""
        connection = stored_connection(self.options)
        source = stored_heat_source(self.options)
        if connection is None and source is None:
            return ""
        hass: HomeAssistant = self.hass  # type: ignore[attr-defined]
        texts = await async_get_translations(hass, hass.config.language, "selector", [DOMAIN])
        prefix = f"component.{DOMAIN}.selector"
        found = [
            texts.get(f"{prefix}.{SIGNAL_HINT}.options.{connection.value}", "")
            if connection is not None
            else "",
            texts.get(f"{prefix}.{SOURCE_HINT}.options.{source.value}", "")
            if source is not None
            else "",
        ]
        return " ".join(text for text in found if text)

    async def async_step_boiler(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            low, high = user_input.get("boiler_min_power"), user_input.get("boiler_max_power")
            if low is not None and high is not None and low >= high:
                errors["base"] = "min_power_not_below_max"
            elif found := pressure_error(user_input):
                errors = found
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
            advanced = _advanced(self.options)
            circuit = circuit_from_input(
                user_input, current.get("id", f"circuit_{index + 1}"), current, advanced
            )
            if index == 0 and not current:
                circuit["id"] = "main"
            if not advanced and current.get("flow_entity"):
                circuit["flow_entity"] = current["flow_entity"]  # not shown: kept
            if (
                circuit["control"] == CircuitControl.PASSIVE_FIXED
                and "fixed_temperature" not in circuit
            ):
                errors["fixed_temperature"] = "fixed_temperature_missing"
            elif alarm_error := circuit_alarm_error(circuit, advanced):
                errors = alarm_error
            elif flow := entity_errors(self.hass, user_input, {"flow_entity": _TEMPERATURE}):  # type: ignore[attr-defined]
                errors = flow
            else:
                self._circuits_done.append(circuit)
                if user_input.get("add_another"):
                    return await self.async_step_circuit()
                kept = [] if _advanced(self.options) else existing[len(self._circuits_done) :]
                circuits = [*self._circuits_done, *kept]
                if circuit_left_with_zones(self.options, circuits):
                    # P-64: a zone would be left on a circuit that is gone; nothing is saved and
                    # this circuit's form shows again, where another can be added.
                    self._circuits_done.pop()
                    errors = {"base": "circuit_has_zones"}
                else:
                    self.options[CIRCUITS] = circuits
                    self._circuits_done = []
                    return await self._goto(self._next_after("circuit"))
        return self._form(
            step_id="circuit",
            data_schema=circuit_schema(self.options, current, more=index + 1 < len(existing)),
            errors=errors,
            description_placeholders={"number": str(index + 1)},
        )

    async def async_step_zones(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        placeholders = {"zone": "-"}
        if user_input is not None:
            picked = _listed(user_input.get("zones"))
            on_thermostat: list[str] = []
            if zones_not_vt(self.hass, picked):  # type: ignore[attr-defined]
                errors = {"zones": "zone_not_vt"}  # question 19: VT climates only
            elif on_thermostat := zones_on_boiler_thermostat(
                self.hass,  # type: ignore[attr-defined]
                [str(zone) for zone in picked],
                boiler_side_entities(self.options),
            ):
                # X5.19: it would ask for heat whenever the flame burns.
                errors = {"zones": "zone_on_boiler_thermostat"}
                placeholders = {
                    "zone": ", ".join(zone_name(self.hass, z) for z in on_thermostat)  # type: ignore[attr-defined]
                }
            else:
                self._zone_queue = [str(zone) for zone in picked]
                self._zones_done = []
                return await self.async_step_zone()
        return self._form(
            step_id="zones",
            data_schema=zones_schema(self.options),
            errors=errors,
            description_placeholders=placeholders,
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
            if user_input.get(CLOSES_WHEN_OFF) is True:
                # Decision 4's per-zone option, stored when ticked; off is its default.
                zone[CLOSES_WHEN_OFF] = True
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
                errors = entity_errors(
                    self.hass,  # type: ignore[attr-defined]
                    user_input,
                    {"foreign_heat": foreign_heat_filters(self.options)},
                )
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
        errors: dict[str, str] = {}
        if user_input is not None:
            if design_outdoor_too_warm(self.options, user_input["design_outdoor"]):
                errors["design_outdoor"] = "design_outdoor_too_warm"
            else:
                apply_building(self.options, user_input)
                return await self._goto(self._next_after("building"))
        return self._form(
            step_id="building", data_schema=building_schema(self.options), errors=errors
        )

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
            if reference.get("zone") and zones_not_vt(self.hass, [reference["zone"]]):  # type: ignore[attr-defined]
                errors["zone"] = "zone_not_vt"
            elif (
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


class _ControlSteps(_Steps):
    """The control steps, shared by the setup — where control is set up in the wizard (I6,
    decision 11) — and the options. The setup has no stored control and nothing to hand back:
    its hooks say so."""

    hass: HomeAssistant  # the flow's, from Home Assistant's flow classes
    _contact_asked_for: str | None = None  # the new relay whose tick was asked again (PB-45)
    _alarms_answer: dict[str, Any] | None = None  # awaiting the return's confirmation

    def _stored_control(self) -> Mapping[str, Any]:
        """The control section as stored before this flow; the setup has none."""
        return {}

    async def _async_hand_back_blocker(self) -> str | None:
        """Why what the hand-back goes through must not change now; the setup has none."""
        return None

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        raise NotImplementedError

    def _changed_read_back(self, user_input: dict[str, Any], blocker: str) -> str | None:
        """The read-back the answer re-picks on the path kept, where it judges a hand-back's
        release: a gateway's (R6, H2 with C1), the setpoint's and the heating switch's on the
        entity path (PB-09); ``None`` where none is."""
        current = self._stored_control()
        path = current.get("write_path")
        if user_input.get("write_path") != path:
            return None
        fixed = fixed_keys(path, owed=blocker == HAND_BACK_PENDING)
        return next(
            (
                key
                for key in ("confirmed_entity", "ch_confirmed_entity")
                if key in fixed and _given(user_input, key) != _given(current, key)
            ),
            None,
        )

    def _changes_hand_back(
        self, user_input: dict[str, Any], shown: vol.Schema | Collection[str], blocker: str
    ) -> bool:
        """Whether the answer changes how the boiler is given back, or what judges it, while
        ``blocker`` holds (PB-09). A field the form shows but the answer leaves out was cleared:
        the frontend leaves an emptied optional field out."""
        if isinstance(shown, vol.Schema):
            shown = {str(marker) for marker in shown.schema}
        current = self._stored_control()
        return any(
            _hand_back_answer(user_input, key) != _hand_back_answer(current, key)
            for key in fixed_keys(current.get("write_path"), owed=blocker == HAND_BACK_PENDING)
            if key in shown
        )

    # --- control: path and topology → path details → curve and limits → (advanced) behaviour
    # → alarm reactions → save

    async def async_step_control(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            path = user_input["write_path"]
            current = self._stored_control().get("write_path")
            errors = control_error(user_input, self.options)
            if not errors and path != NO_CONTROL:
                errors = entity_errors(self.hass, user_input, CONTROL_ENTITY_FIELDS)
            if not errors and path != NO_CONTROL and not _zone_entities(self.options):
                errors = {"base": "no_zones"}  # nothing could ever ask for heat (S-04)
            blocker = await self._async_hand_back_blocker()
            if not errors and path not in (NO_CONTROL, current) and blocker:
                # "No control" stays possible: the hand-back goes through the old path, retried
                # by a unit that only hands back.
                errors = {"write_path": blocker}
            elif not errors and blocker and (key := self._changed_read_back(user_input, blocker)):
                errors = {key: blocker}
            if errors:
                return self._form(
                    step_id="control",
                    data_schema=control_schema(self.options, self._control_suggestions()),
                    errors=errors,
                )
            apply_control(self.options, user_input)
            if path == NO_CONTROL:
                return await self.async_step_save()
            if path == WritePath.RELAY:
                # R14: moving over from VT's central boiler, where it is set up or its commands
                # are still kept: its settings offered, with the steps that follow.
                prefill = self._vt_prefill()
                moving = prefill is not None and prefill.exists
                return await self._goto("control_relay_from_vt" if moving else "control_relay")
            step = {
                WritePath.ENTITY: "control_entity",
                WritePath.OPENTHERM_GW: "control_gateway",
                WritePath.OTGW_MQTT: "control_mqtt",
            }[WritePath(path)]
            return await self._goto(step)
        return self._form(
            step_id="control", data_schema=control_schema(self.options, self._control_suggestions())
        )

    def _control_suggestions(self) -> dict[str, str]:
        """What the connection suggests on the first control step (I6, decision 2): the virtual
        topology for ESPHome and EMS-ESP; the one gateway's read-backs."""
        connection = stored_connection(self.options)
        if connection in VIRTUAL_CONNECTIONS:
            return {"topology": Topology.VIRTUAL.value}
        if connection is Connection.OPENTHERM_GW:
            return gateway_entities(self.hass, GATEWAY_READ_BACKS)
        return {}

    async def async_step_control_entity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            grid = read_grid(self.hass, user_input["setpoint_entity"])
            found = entity_errors(self.hass, user_input, TARGET_ENTITY_FIELDS) or (
                targets_used_by_zone(self.hass, user_input)  # PB-54
            )
            if found:
                errors = found
            elif temperature_unit_of(self.hass, user_input["setpoint_entity"]) is False:
                errors = {"setpoint_entity": "setpoint_unit_not_supported"}
            elif grid is not None and grid.too_coarse:
                # A value rounded to so coarse a step could read back as ignored (P-15).
                errors = {"setpoint_entity": "setpoint_step_too_coarse"}
            else:
                errors = control_details_error(
                    user_input, read_bounds(self.hass, user_input["setpoint_entity"])
                )
            if not errors and user_input.get("hand_back") == HandBack.VALUE:
                candidate = copy.deepcopy(self.options)
                apply_control_details(candidate, user_input)
                if hand_back_value_problem(candidate, "hand_back_value_above_max"):
                    # Never clamped: a clamped value would mean something else to the device.
                    errors = {"hand_back_value": "hand_back_value_above_max"}
            blocker = await self._async_hand_back_blocker()
            if (
                not errors
                and blocker
                and self._changes_hand_back(
                    user_input, control_entity_schema(self.options), blocker
                )
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
        # Only gateways enabled in Home Assistant are offered (P-69).
        entries = self.hass.config_entries.async_entries(
            OPENTHERM_GW_DOMAIN, include_ignore=False, include_disabled=False
        )
        gateways = sorted({str(entry.data["id"]) for entry in entries if entry.data.get("id")})
        if user_input is not None:
            picked = str(user_input["gateway_id"])
            if picked not in gateways:
                errors = {"gateway_id": "gateway_unknown"}  # every write would fail
            elif not any(
                entry.state is ConfigEntryState.LOADED
                for entry in entries
                if str(entry.data.get("id")) == picked
            ):
                errors = {"gateway_id": "gateway_not_set_up"}  # not running: nothing arrives
            elif (blocker := await self._async_hand_back_blocker()) and self._changes_hand_back(
                user_input, control_gateway_schema(self.options, gateways), blocker
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
            if not mqtt_set_up(self.hass):
                errors = {"base": "mqtt_not_set_up"}  # the commands would go nowhere (P-69)
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
                and self._changes_hand_back(user_input, control_mqtt_schema(self.options), blocker)
            ):
                errors = {"base": blocker}
            if not errors:
                apply_control_details(self.options, user_input)
                return await self.async_step_control_curve()
        return self._form(
            step_id="control_mqtt", data_schema=control_mqtt_schema(self.options), errors=errors
        )

    def _vt_prefill(self) -> VtCentralBoiler | None:
        """VT's central boiler settings, read only (R14)."""
        return vt_central_boiler_settings(self.hass, _zone_entities(self.options))

    async def async_step_control_relay(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return await self._async_relay_step("control_relay", user_input)

    async def async_step_control_relay_from_vt(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The relay step moving over from VT's central boiler: the same form, pre-filled, with
        the migration's steps in its description (R14)."""
        return await self._async_relay_step("control_relay_from_vt", user_input)

    async def _async_relay_step(
        self, step_id: str, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        """The relay and its own settings (R2, R3): refused in the form where the relay is no
        switch or boiler thermostat entity, cannot be set to heat and off, is driven by a VT
        zone, belongs to the boiler's gateway integration or to VT, or has another role; a
        declared timer needs its length, 10 min at least (K4.2). What the hand-back goes
        through — the relay and its rest state — cannot change while a hand-back is owed or
        control holds the relay."""
        prefill = self._vt_prefill()
        schema = control_relay_schema(self.options, prefill)
        errors: dict[str, str] = {}
        if user_input is not None:
            problem = relay_entity_error(self.hass, self.options, user_input.get(RELAY_ENTITY))
            if problem is not None:
                errors = {RELAY_ENTITY: problem}
            elif self._contact_to_confirm(user_input):
                errors = {"relay_is_separate_contact": "relay_contact_confirm_again"}
            elif user_input.get("relay_off_timer") == RelayTimer.MINUTES:
                length = user_input.get(RELAY_TIMER_MIN)
                if length in (None, ""):
                    errors = {RELAY_TIMER_MIN: "relay_off_timer_min_missing"}
                elif float(length) * 60.0 < TIMER_MIN_S:
                    # Decided by the user 2026-10-03 (K4.2): a shorter timer would start the
                    # boiler again at every lapse.
                    errors = {RELAY_TIMER_MIN: "relay_off_timer_min_short"}
            blocker = await self._async_hand_back_blocker()
            if not errors and blocker and self._changes_hand_back(user_input, schema, blocker):
                errors = {"base": blocker}
            if not errors:
                apply_control_relay(self.options, user_input)
                return await self.async_step_control_relay_behaviour()
        elif (
            prefill is not None
            and prefill.commands is VtCommands.NOT_SUPPORTED
            and not self.options.get(CONTROL, {}).get(RELAY_ENTITY)
        ):
            # VT's commands name no switch or boiler thermostat pair: the user picks the relay.
            errors = {"base": "vt_commands_not_supported"}
        return self._form(step_id=step_id, data_schema=schema, errors=errors)

    def _contact_to_confirm(self, user_input: Mapping[str, Any]) -> bool:
        """PB-45: the separate-contact tick declares one entity's contact. Where the relay
        changes from a stored one with the tick kept, the step asks once more, so a declaration
        about the old relay does not carry over to the new one."""
        stored = self.options.get(CONTROL, {}).get(RELAY_ENTITY)
        relay = user_input.get(RELAY_ENTITY)
        if not stored or relay == stored or user_input.get("relay_is_separate_contact") is not True:
            return False
        if self._contact_asked_for == relay:
            return False
        self._contact_asked_for = relay if isinstance(relay, str) else None
        return True

    async def async_step_control_relay_behaviour(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The relay path's behaviour: VT's activation delay at every level; at the advanced
        level the demand thresholds, learning pauses and frost fields, with the checks the
        curve and behaviour steps make (T-37 among them)."""
        prefill = self._vt_prefill()
        errors: dict[str, str] = {}
        if user_input is not None:
            if _advanced(self.options):
                errors = self._relay_behaviour_error(user_input)
            if not errors:
                apply_control_relay_behaviour(self.options, user_input)
                if alarm_step_offered(self.options):  # nothing is offered for relays (Y1)
                    return await self.async_step_control_alarms()
                return await self.async_step_save()
        return self._form(
            step_id="control_relay_behaviour",
            data_schema=control_relay_behaviour_schema(self.options, prefill),
            errors=errors,
            description_placeholders=self._unfed_placeholders(errors),
        )

    def _relay_behaviour_error(self, user_input: dict[str, Any]) -> dict[str, str]:
        count = int(user_input.get("count_threshold", CONTROL_DEFAULTS["count_threshold"]))
        if user_input.get("frost_limit", CONTROL_DEFAULTS["frost_limit"]) >= user_input.get(
            "frost_release", CONTROL_DEFAULTS["frost_release"]
        ):
            return {"frost_release": "frost_release_not_above_limit"}
        if found := self._frost_zone_error(user_input):
            return found
        if count > len(self.options.get(ZONES, [])):
            return {"count_threshold": "count_threshold_above_zones"}
        if count == 0 and not (
            user_input.get("power_threshold_kw") or user_input.get("opening_threshold")
        ):
            return {"count_threshold": "no_demand_criterion"}
        if (unfed := self._criterion_no_zone_feeds(user_input)) is not None:
            return {unfed: _UNFED[unfed]}
        return {}

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
            elif problems := self._curve_problems(user_input):
                field, key = problems[0]
                errors[field] = key
            elif off_too_close_in(self.options, user_input["hard_min"]):
                # P-25, at both levels: "off" as a low setpoint next to the lowest water.
                errors["hard_min"] = "off_setpoint_not_below_hard_min"
            elif self._lowest_above_max(user_input):
                errors["hard_min"] = "hard_min_above_max"
            elif found := self._frost_zone_error(user_input):
                errors = found
            elif (blocker := await self._async_hand_back_blocker()) and self._changes_hand_back(
                user_input, ("hard_min",), blocker
            ):
                # PB-09: an owed hand-back wrote the lowest first and is judged by it.
                errors["hard_min"] = blocker
            else:
                apply_control_curve(self.options, user_input)
                if _advanced(self.options):
                    return await self.async_step_control_behaviour()
                if alarm_step_offered(self.options):
                    # Y1: the reaction to an ignored write, where offered, at both levels.
                    return await self.async_step_control_alarms()
                return await self.async_step_save()
        # VT's own activation delay, where VT kept one, is offered for the user to confirm.
        vt_delay = VThermLink(self.hass, _zone_entities(self.options)).vt_central_activation_delay()
        return self._form(
            step_id="control_curve",
            data_schema=control_curve_schema(self.options, vt_delay),
            errors=errors,
            description_placeholders=water_limits(self.options),
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
            off = float(user_input.get("off_setpoint", CONTROL_DEFAULTS["off_setpoint"]))
            # PB-69: with a heating switch "off" is never written as a setpoint, so neither its
            # range nor its distance to the lowest is checked (as ``off_too_close_in``).
            as_setpoint = not heating_writes(self.options.get(CONTROL, {})) and not fixed_off(
                self.options
            )
            if as_setpoint and _outside(user_input.get("off_setpoint"), self._setpoint_bounds()):
                errors["off_setpoint"] = "off_setpoint_outside_entity_range"
            elif as_setpoint and off_too_close_to_lowest(off, hard_min):
                errors["off_setpoint"] = "off_setpoint_not_below_hard_min"  # 1 K below (P-43)
            elif self._off_near_hand_back_value(user_input):
                errors["off_setpoint"] = "off_setpoint_near_hand_back_value"
            elif count > len(self.options.get(ZONES, [])):
                errors["count_threshold"] = "count_threshold_above_zones"
            elif count == 0 and not (
                user_input.get("power_threshold_kw") or user_input.get("opening_threshold")
            ):
                errors["count_threshold"] = "no_demand_criterion"
            elif (unfed := self._criterion_no_zone_feeds(user_input)) is not None:
                errors[unfed] = _UNFED[unfed]
            else:
                apply_control_behaviour(self.options, user_input)
                if alarm_step_offered(self.options):
                    return await self.async_step_control_alarms()
                return await self.async_step_save()
        return self._form(
            step_id="control_behaviour",
            data_schema=control_behaviour_schema(self.options),
            errors=errors,
            description_placeholders=self._unfed_placeholders(errors),
        )

    def _curve_problems(self, user_input: dict[str, Any]) -> list[tuple[str, str]]:
        """X5.8 (P-68) at both levels: the curve's room as entered, else as stored, else its
        default."""
        stored = self.options.get(CONTROL, {}).get("curve", {})
        room = user_input.get("room", stored.get("room", CURVE_DEFAULTS["room"]))
        return curve_problems(
            user_input.get("design_flow"),
            float(user_input["design_outdoor"]),
            float(room),
            float(user_input["hard_min"]),
            float(user_input["hard_max"]),
        )

    def _lowest_above_max(self, user_input: dict[str, Any]) -> bool:
        """PB-26: the lowest water temperature as entered above a circuit's or the boiler's
        maximum, which the hand-back would send first; the options as they stand otherwise."""
        candidate = copy.deepcopy(self.options)
        apply_control_curve(candidate, user_input)
        control = control_of(candidate)
        return control is not None and lowest_above_max(control.loop.control)

    def _frost_zone_error(self, user_input: dict[str, Any]) -> dict[str, str]:
        """The frost zone is one of the configured zones, as the form offers (P-79)."""
        zone = user_input.get("frost_zone")
        if zone in (None, "") or zone in _zone_entities(self.options):
            return {}
        if zones_not_vt(self.hass, [zone]):
            return {"frost_zone": "zone_not_vt"}
        return {"frost_zone": "entity_not_suitable"}

    def _criterion_no_zone_feeds(self, user_input: dict[str, Any]) -> str | None:
        """P-14: a power or opening threshold no zone can feed could never be reached — VT
        publishes a device power of 0 where none is set, and a zone of VT's over_climate type
        no opening. Refused where at least one zone can be read and none feeds it; with none
        readable (VT away, or not started yet) nothing can be told, and it is kept — at run time
        the criterion then counts as without data, with an alarm. PB-23: with a zone count of 0,
        a readable zone that feeds none of the thresholds set could never ask for heat —
        refused too, naming it (``_unfed_zones``); one that cannot be read is not judged, and a
        calling zone without the data raises the run-time alarm. The field to fix, or
        ``None``."""
        power = user_input.get("power_threshold_kw")
        opening = user_input.get("opening_threshold")
        if not power and not opening:
            return None
        now = dt_util.utcnow().timestamp()
        link = VThermLink(self.hass, _zone_entities(self.options))
        readable = [zone for zone in link.zones() if zone.has_reported(now, None)]
        if not readable:
            return None
        if power and not any(feeds_power(zone) for zone in readable):
            return "power_threshold_kw"
        if opening and not any(feeds_opening(zone) for zone in readable):
            return "opening_threshold"
        count = int(user_input.get("count_threshold", CONTROL_DEFAULTS["count_threshold"]))
        unheard = [
            zone.zone_id
            for zone in readable
            if not (power and feeds_power(zone)) and not (opening and feeds_opening(zone))
        ]
        if count == 0 and unheard:
            self._unfed_zones = ", ".join(link.zone_name(zone) for zone in unheard)
            return "count_threshold"
        return None

    def _unfed_placeholders(self, errors: Mapping[str, str]) -> dict[str, str] | None:
        """PB-23: the zone the form's error names."""
        if errors.get("count_threshold") == _UNFED["count_threshold"]:
            return {"zone": self._unfed_zones}
        return None

    def _off_near_hand_back_value(self, user_input: dict[str, Any]) -> bool:
        """S-49: "off" sent as a low setpoint next to a hand-back value that returns the boiler
        to its own control would hand the boiler back instead of stopping heating."""
        candidate = copy.deepcopy(self.options)
        apply_control_behaviour(candidate, user_input)
        return hand_back_value_problem(candidate, "off_setpoint_near_hand_back_value")

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
            stored = self.options.get(CONTROL, {})
            if any(
                user_input.get(key) is True and stored.get(key) is not True
                for key in (RETURN_KEY, RETURN_SWITCH_KEY)
            ):
                # Switched on: confirmed a second time before it is saved (decision 6; the
                # switch's own opt-in too, SB-36).
                self._alarms_answer = user_input
                return await self.async_step_control_return_confirm()
            apply_control_alarms(self.options, user_input)
            return await self.async_step_save()
        return self._form(step_id="control_alarms", data_schema=control_alarms_schema(self.options))

    async def async_step_control_return_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """The second confirmation of the return by itself after another controller."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if user_input.get("understood") is True and self._alarms_answer is not None:
                apply_control_alarms(self.options, self._alarms_answer)
                self._alarms_answer = None
                return await self.async_step_save()
            errors = {"understood": "return_needs_confirmation"}
        return self._form(
            step_id="control_return_confirm",
            data_schema=control_return_confirm_schema(),
            errors=errors,
        )


class SmartBoilerConfigFlow(_ControlSteps, ConfigFlow, domain=DOMAIN):
    VERSION = 1
    # 2: the options 0.2.1 removed are gone; 3: a control section without the lowest water
    # temperature keeps 25 °C; 4: the "add water" threshold replaces the low-pressure limits, and
    # alarm reactions no longer offered go; 5: the high-pressure limits have no default, and an
    # entry from before keeps those it ran with; 6: the design outdoor temperature is one value,
    # the building's, the curve's moved there (see async_migrate_entry).
    MINOR_VERSION = 6

    def __init__(self) -> None:
        self.options: dict[str, Any] = {}
        self._title = DEFAULT_NAME
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return SmartBoilerOptionsFlow()

    ORDER = (
        "connection", "mode", "name", "signals", "boiler", "circuit", "zones", "building",
        "reference", "monitor", "control", "finish",
    )  # fmt: skip

    def _next_after(self, step: str) -> str:
        following = self.ORDER[self.ORDER.index(step) + 1]
        if following == "monitor" and not _advanced(self.options):
            following = "control"
        if following == "control" and not wants_control(self.options):
            following = "finish"
        return following

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The control steps' end, in the setup: the entry is made (I6, decision 11)."""
        return await self.async_step_finish()

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """The setup opens with how the boiler is connected (I6)."""
        return await self.async_step_connection()

    async def async_step_name(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            self._title = user_input["name"]
            self.options[LEVEL] = user_input[LEVEL]
            return await self._goto(self._next_after("name"))
        texts = await async_get_translations(
            self.hass, self.hass.config.language, "device", [DOMAIN]
        )
        name = texts.get(f"component.{DOMAIN}.device.{DEFAULT_NAME_KEY}.name") or DEFAULT_NAME
        return self.async_show_form(step_id="name", data_schema=user_schema({}, name))

    async def async_step_finish(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        problem = validate_problem(self.options)
        if problem is not None:
            return await self._back_to_problem(*problem)
        return self.async_create_entry(title=self._title, data={}, options=self.options)


class SmartBoilerOptionsFlow(_ControlSteps, OptionsFlow):
    """A menu of sections; each saves the options when done."""

    def __init__(self) -> None:
        self._zone_queue = []
        self._zones_done = []
        self._circuits_done = []
        self._options: dict[str, Any] | None = None
        self._alarms_answer: dict[str, Any] | None = None  # awaiting the return's confirmation
        # Blockers the edit would add to control, awaiting confirmation; confirmed: saved anyway.
        self._blocking: list[str] = []
        self._blocking_confirmed = False
        # Stored sections of another shape, each shown first at the save (PB-06).
        self._unreadable: list[str] = []
        # The new relay whose separate-contact tick was asked again (PB-45).
        self._contact_asked_for: str | None = None

    @property
    def options(self) -> dict[str, Any]:  # type: ignore[override]
        if self._options is None:
            options = copy.deepcopy(dict(self.config_entry.options))
            # PB-06: a section of another shape (a hand edit, an import) is edited from empty, so
            # its step and the menu can show; the save first sends the user to that step, with
            # its reason — nothing of it is dropped unseen.
            self._unreadable = [
                key for key in SECTION_CODES if not section_fits(key, options.get(key))
            ]
            for key in self._unreadable:
                options[key] = [] if key in (CIRCUITS, ZONES) else {}
            self._options = options
        return self._options

    def _next_unreadable(self) -> str | None:
        """The next stored section of another shape not shown yet (PB-06)."""
        _ = self.options  # made at first use, finding them
        return self._unreadable.pop(0) if self._unreadable else None

    def _stored_control(self) -> Mapping[str, Any]:
        """The stored control section; one of another shape reads as none (PB-06)."""
        current = self.config_entry.options.get(CONTROL)
        return current if isinstance(current, Mapping) else {}

    def _next_after(self, step: str) -> str:
        return "mode" if step == "connection" else "save"

    async def _async_hand_back_blocker(self) -> str | None:
        """Why what the hand-back goes through must not change now: it has not reached the
        boiler yet, or control holds the boiler — its hand-back must go through the device
        that has it, which the user gets by switching control off first. With the entry not
        running — its setup failed, say — its store tells: the next start makes what the last
        run left owed through what the options say then."""
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator is None:
            return HAND_BACK_PENDING if await self._async_owed_in_store() else None
        found = (getattr(coordinator, name, None) for name in ("control", "hand_back_unit"))
        units = [unit for unit in found if unit is not None]
        if any(unit.hand_back_owed for unit in units):
            return HAND_BACK_PENDING
        if any(unit.holding for unit in units):
            return "control_holds_boiler"
        return None

    async def _async_owed_in_store(self) -> bool:
        """What the entry's stored control state says, read as at setup: one that cannot be
        read owes a hand-back wherever control is configured."""
        from homeassistant.helpers.importlib import async_import_module

        await async_import_module(self.hass, f"{__package__}.coordinator")
        from .coordinator import async_read_control_state

        entry = self.config_entry
        read = await async_read_control_state(self.hass, entry.entry_id, entry.options)
        return read.owed

    def _saves_another_hand_back(self, *, owed: bool) -> bool:
        """Whether the options to be saved change what a hand-back goes through or what judges
        it: the path, what it writes to, the gateway or its topics, the read-backs, the write
        types, the device's timeout, and with a hand-back owed the lowest water temperature
        (P-12, PB-09). Taking control out changes nothing: the options that took the boiler
        still hand it back, through a unit that only does that."""
        new = self.options.get(CONTROL)
        if not isinstance(new, Mapping):
            return False
        current = self._stored_control()
        keys = ["write_path", *fixed_keys(new.get("write_path"), owed=owed)]
        return any(_hand_back_answer(new, key) != _hand_back_answer(current, key) for key in keys)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        menu = [
            "connection", "signals", "freshness", "boiler", "circuit", "zones", "building",
            "reference", "control",
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
        errors: dict[str, str] = {}
        if user_input is not None:
            candidate = copy.deepcopy(self.options)
            restoring = user_input[LEVEL] == LEVEL_SIMPLE and user_input.get("restore_defaults")
            if restoring:
                restore_advanced_defaults(candidate)
            if restoring and off_too_close_in(candidate):
                # P-25: the default "off" next to the lowest water temperature kept.
                errors = {"base": "off_setpoint_not_below_hard_min"}
            else:
                self._options = candidate
                self.options[LEVEL] = user_input[LEVEL]
                return await self.async_step_save()
        return self.async_show_form(
            step_id="level", data_schema=level_schema(self.options), errors=errors
        )

    async def async_step_freshness(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            apply_freshness(self.options, user_input)
            return await self.async_step_save()
        return self._form(step_id="freshness", data_schema=freshness_schema(self.options))

    async def async_step_save(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # A confirmation holds for the save right after it only: any way back to a step asks
        # again at the next save.
        confirmed, self._blocking_confirmed = self._blocking_confirmed, False
        if (key := self._next_unreadable()) is not None:
            # PB-06: a section stored in another shape is shown once, from empty, with its reason.
            return await self._back_to_problem(SECTION_CODES[key], key)
        problem = validate_problem(self.options)
        if problem is not None:
            return await self._back_to_problem(*problem)
        control = control_of(self.options)
        if control is not None and (problems := hand_back_value_problems(control)):
            # A maximum lowered under the hand-back value, or "off" moved next to it, since the
            # step that checks it (S-21, S-49): back to that step.
            return await self._back_to_problem(problems[0], None)
        if self._saves_another_hand_back(owed=True):
            # Checked again here, not only at the control steps: control may have taken the
            # boiler, or begun to owe it a hand-back, since they were answered (P-12). Nothing
            # is saved; the control step says why.
            blocker = await self._async_hand_back_blocker()
            if blocker is not None and self._saves_another_hand_back(
                owed=blocker == HAND_BACK_PENDING
            ):
                return await self._back_to_problem(blocker, None)
        if not confirmed and (blocking := self._new_blockers()):
            # Open after R6 #3: an edit that would keep control from running is confirmed first.
            self._blocking = blocking
            return await self.async_step_confirm_blocking()
        entry = self.config_entry
        if entry.state in (ConfigEntryState.SETUP_ERROR, ConfigEntryState.SETUP_RETRY):
            # The failed setup left no update listener to reload it (H9): the new options are
            # put in place first, then the entry is set up again with them.
            self.hass.config_entries.async_update_entry(entry, options=self.options)
            self.hass.config_entries.async_schedule_reload(entry.entry_id)
        return self.async_create_entry(data=self.options)

    def _new_blockers(self) -> list[str]:
        """The configuration blockers the options to be saved give control that the stored ones
        do not — only where both hold a control section (adding control stops nothing; taking it
        out is its own choice). Run-time blockers are not compared."""
        new = options_blockers(self.options)
        old = options_blockers(self.config_entry.options)
        if new is None or old is None:
            return []
        return [blocker for blocker in new if blocker not in old]

    async def async_step_confirm_blocking(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Open after R6 #3: the first new blocker's text and how many more; saved only when the
        user ticks "save anyway", else nothing is saved and the menu shows again."""
        if user_input is not None:
            if user_input.get("save_anyway") is True and self._blocking:
                self._blocking_confirmed = True
                return await self.async_step_save()
            self._options = None  # the answers of this edit go: nothing saved
            self._blocking = []
            return await self.async_step_init()
        first, *others = self._blocking
        return self.async_show_form(
            step_id="confirm_blocking",
            data_schema=confirm_blocking_schema(),
            description_placeholders={
                "first": await self._async_blocker_text(first),
                "more": str(len(others)),
            },
        )

    async def _async_blocker_text(self, blocker: str) -> str:
        """A blocker's text as the control switch gives it, in Home Assistant's language,
        without its sentence naming the other reasons — the form counts them; its key where
        there is none."""
        texts = await async_get_translations(
            self.hass, self.hass.config.language, "exceptions", [DOMAIN]
        )
        text = texts.get(f"component.{DOMAIN}.exceptions.blocked_{blocker}.message")
        if not text:
            return blocker
        at = text.find("{count}")  # the sentence counting the others (P-74)
        if at < 0:
            return text
        start = text.rfind(". ", 0, at)
        return text[: start + 1] if start >= 0 else text.replace("{count}", "-")
