"""The config entry's options as core objects. No Home Assistant imports.

The config flow writes one options dictionary; everything else reads it through
``EntryConfig.from_options``, so there is a single definition of what each key means and of its
cautious default. A stored value this version does not know raises a ``ConfigError`` naming its
section (``invalid_boiler``, ``invalid_circuit``, ...), which the options flow shows on that
section's step (P-70); so does a section of another shape (PB-06), and a number the form bounds
stored not finite or outside the form's bounds — refused, never used or widened (PB-24). One
entity mapped to two signals is kept for the first in the form's order; the later signal is
dropped and recorded in ``shared_signals`` — control gets a blocker, the monitor runs (X5.2). No
signal is required (X8): flame and flow serve the monitor and water-temperature control, which
gets a blocker without them.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, SupportsFloat

from .const import (
    BOILER,
    BUILDING,
    CH_ENABLED,
    CIRCUITS,
    CONTROL,
    FRESHNESS,
    LEVEL,
    LEVEL_SIMPLE,
    MONITOR,
    PARAMETERS,
    SIGNALS,
    WEATHER,
    ZONES,
    has_control_section,
)
from .control_config import (
    CONNECTION_MODES,
    Connection,
    ControlMode,
    ControlOptions,
    WritePath,
    boiler_class_for,
    map_control_entities,
    mqtt_topic_valid,
    parse_control,
    with_boiler_inputs,
)
from .core.alarms import (
    ADD_WATER_RANGE_BAR,
    CIRCUIT_ALARM_MIN,
    CIRCUIT_ALARM_RISE_K,
    DEFAULT_FREQUENT_STARTS_PER_HOUR,
    DEFAULT_UNSTABLE_BURNS_PER_DAY,
    FLUE_GAS_CONDENSING_BAND,
    Band,
    add_water_band,
    pressure_high_band,
)
from .core.building import loss_from_design_load
from .core.installation import (
    Boiler,
    BoilerClass,
    BoilerType,
    Circuit,
    CircuitControl,
    DhwType,
    EmitterType,
    HeatSource,
    Installation,
    Zone,
)
from .core.metrics import DEFAULT_CONDENSING_RETURN, ModulationScale
from .core.monitor import MonitorOptions
from .core.parameters import Estimate, ParameterKey, ParameterSet, Source
from .core.signals import SIGNAL_PRECEDENCE, Signal
from .core.verdict import VerdictOptions

_LOGGER = logging.getLogger(__name__)


def _ignore_unknown(section: str, key: str) -> None:
    """PB-68: a key this version does not know — saved by a later version, then a downgrade —
    is left out rather than stopping the entry; the user sees it in the log."""
    _LOGGER.warning("Ignoring the unknown %s key %r in the options", section, key)


class ConfigError(ValueError):
    """The options cannot be used; ``code`` is a translation key, ``subject`` what it concerns."""

    def __init__(self, code: str, subject: str | None = None) -> None:
        super().__init__(f"{code}: {subject}" if subject else code)
        self.code = code
        self.subject = subject


# The options form's bounds of every stored number it takes (PB-24); the form reads them here. A
# stored one not finite or outside them — a hand edit, an import — is refused with its section's
# reason. Freshness limits are stored in seconds, the form's 1 to 1440 minutes.
CIRCUIT_BOUNDS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "max_flow": (20.0, 90.0),
        "fixed_temperature": (20.0, 70.0),
        "max_flow_alarm": (20.0, 100.0),
        "max_flow_alarm_min": (1.0, 120.0),
        "needed_temperature": (20.0, 90.0),  # I8 (F3): a circuit run by other automation's
    }
)
# Shorter would let control start before the monitoring period (X5); the integration tests lift
# it in their one place to start control at once.
MONITORING_DAYS_BOUNDS = (7.0, 60.0)
MONITOR_BOUNDS: Mapping[str, tuple[float, float]] = MappingProxyType(
    {
        "condensing_return": (40.0, 65.0),
        "short_burn_min": (1.0, 60.0),
        "verdict_window_days": (7.0, 365.0),
        "pressure_high_warning": (1.5, 4.0),
        "pressure_high_alarm": (1.5, 4.0),
        "flue_gas_warning": (40.0, 200.0),
        "flue_gas_alarm": (40.0, 200.0),
        "starts_per_hour_limit": (2.0, 60.0),
        "unstable_burns_limit": (1.0, 100.0),
    }
)
FRESHNESS_BOUNDS_MIN = (1.0, 1440.0)
# A freshness limit the user switched off (a stored 0): availability only (I6, decision 9).
FRESHNESS_OFF = 0.0

# Each section's reason where it is stored in another shape (PB-06); circuits and zones are
# lists, every other section a mapping.
SECTION_CODES: Mapping[str, str] = MappingProxyType(
    {
        SIGNALS: "invalid_signals",
        BOILER: "invalid_boiler",
        CIRCUITS: "invalid_circuit",
        ZONES: "invalid_zone",
        PARAMETERS: "invalid_parameters",
        BUILDING: "invalid_building",
        MONITOR: "invalid_monitor",
        FRESHNESS: "invalid_freshness",
        CONTROL: "invalid_control",
    }
)
_LIST_SECTIONS = frozenset({CIRCUITS, ZONES})


def section_fits(key: str, value: object) -> bool:
    """Whether a stored section has its shape: nothing, a list of mappings for circuits and
    zones, a mapping for every other section."""
    if value is None:
        return True
    if key in _LIST_SECTIONS:
        return isinstance(value, list | tuple) and all(isinstance(i, Mapping) for i in value)
    return isinstance(value, Mapping)


def _section(options: Mapping[str, Any], key: str) -> Any:
    """A stored section; none stored, an empty one. One of another shape — a list where a mapping
    belongs, text where a section belongs — raises ``ConfigError(invalid_<section>, key)``
    (PB-06)."""
    value = options.get(key)
    if not section_fits(key, value):
        raise ConfigError(SECTION_CODES[key], key)
    if value is None:
        return [] if key in _LIST_SECTIONS else {}
    return value


@dataclass(frozen=True, slots=True)
class ZoneConfig:
    entity_id: str


@dataclass(frozen=True, slots=True)
class AlarmThresholds:
    """Limits of the current alarms (advanced options). ``pressure_low``: the "add water" band
    from the threshold the user took from the boiler's manual — none by default, and then no
    low-pressure alarm at all (Y1)."""

    pressure_low: Band | None = None
    pressure_high: Band | None = None  # decision 13: none without the user's limits
    flue_gas: Band = FLUE_GAS_CONDENSING_BAND
    starts_per_hour: int = DEFAULT_FREQUENT_STARTS_PER_HOUR
    unstable_burns_per_day: int = DEFAULT_UNSTABLE_BURNS_PER_DAY

    @property
    def add_water_below(self) -> float | None:
        """The "add water" threshold, bar; ``None``: not entered."""
        return None if self.pressure_low is None else self.pressure_low.alarm


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    monitor: MonitorOptions = field(default_factory=MonitorOptions)
    monitoring_days: float = 7.0
    alarms: AlarmThresholds = field(default_factory=AlarmThresholds)


# The setup's first answers (I6), stored in the boiler section: the connection, the control mode,
# the heat source, the boiler type and its hot-water priority. The boiler class and the hot-water
# kind follow from them and are stored too, so a version without them reads the entry the same.
INVALID_CONNECTION = "invalid_connection"


@dataclass(frozen=True, slots=True)
class BoilerPanel:
    """The setup's first answers (I6, decisions 1, 6, 7, 8); ``None`` for an entry made before
    them, which works as before."""

    connection: Connection | None = None
    control_mode: ControlMode | None = None
    heat_source: HeatSource | None = None
    boiler_type: BoilerType | None = None
    dhw_priority: bool = True  # hot water takes the heat from the rooms while it runs
    # The MQTT topics the boiler interface publishes under (decision 9): the OTGW firmware's top
    # level and node, EMS-ESP's base; ``None`` where not given.
    mqtt_top: str | None = None
    mqtt_node: str | None = None
    ems_esp_base: str | None = None


def _answer[E: StrEnum](kind: type[E], data: Mapping[str, Any], key: str) -> E | None:
    """One of the setup's first answers; none stored, ``None``; one this version does not know
    raises ``ConfigError(invalid_connection, key)`` (decision 12)."""
    raw = data.get(key)
    if raw is None:
        return None
    try:
        return kind(raw)
    except ValueError as err:
        raise ConfigError(INVALID_CONNECTION, key) from err


def _panel(data: Mapping[str, Any]) -> BoilerPanel:
    """The setup's first answers from the boiler section. A mode the connection cannot do — a
    hand edit — cannot be read either."""
    connection = _answer(Connection, data, "connection")
    mode = _answer(ControlMode, data, "control_mode")
    if connection is not None and mode is not None and mode not in CONNECTION_MODES[connection]:
        raise ConfigError(INVALID_CONNECTION, "control_mode")
    return BoilerPanel(
        connection=connection,
        control_mode=mode,
        heat_source=_answer(HeatSource, data, "heat_source"),
        boiler_type=_answer(BoilerType, data, "type"),
        dhw_priority=_flag(INVALID_CONNECTION, data, "dhw_priority", True),
        mqtt_top=_topic(data, "mqtt_top"),
        mqtt_node=_topic(data, "mqtt_node"),
        ems_esp_base=_topic(data, "ems_esp_base"),
    )


def _topic(data: Mapping[str, Any], key: str) -> str | None:
    """A stored MQTT topic level; none stored, ``None``; one with a wildcard, a space or a
    slash at an end cannot be read (decision 12)."""
    raw = data.get(key)
    if raw in (None, ""):
        return None
    if not isinstance(raw, str) or not mqtt_topic_valid(raw) or raw != raw.strip():
        raise ConfigError(INVALID_CONNECTION, key)
    return raw


def _resolved_boiler(data: Mapping[str, Any], panel: BoilerPanel) -> Mapping[str, Any]:
    """The boiler section as the analysis reads it: where the panel is answered, the class and
    the hot-water kind follow from it, whatever a hand edit left beside them."""
    resolved = dict(data)
    if panel.connection is not None and panel.control_mode is not None:
        resolved["class"] = boiler_class_for(panel.connection, panel.control_mode).value
    if panel.boiler_type is not None:
        resolved["dhw"] = panel.boiler_type.dhw.value
    return resolved


@dataclass(frozen=True, slots=True)
class EntryConfig:
    level: str
    signals: dict[Signal, str]
    weather: str | None
    installation: Installation
    parameters: ParameterSet
    zones: tuple[ZoneConfig, ...]
    circuit_flow_entities: dict[str, str]
    monitor: MonitorConfig
    freshness: dict[Signal, float | None]
    control: ControlOptions = field(default_factory=ControlOptions)
    control_problem: str | None = None  # why control was left out (non-strict parsing only)
    # The weather entity's own age limit (X2): none by default — availability only; never the
    # outdoor sensor's.
    weather_max_age_s: float | None = None
    # Signals dropped because their entity feeds an earlier signal, each with the signal that
    # kept it (X5.2): inactive and named; control is blocked.
    shared_signals: Mapping[Signal, Signal] = field(default_factory=dict)
    panel: BoilerPanel = field(default_factory=BoilerPanel)  # the setup's first answers (I6)
    # I8 (decision F3): circuits run by other automation's request and need entities.
    circuit_request_entities: dict[str, str] = field(default_factory=dict)
    circuit_need_entities: dict[str, str] = field(default_factory=dict)

    @property
    def zone_entities(self) -> tuple[str, ...]:
        return tuple(z.entity_id for z in self.zones)

    @property
    def setpoint_read_back(self) -> str | None:
        """The control's setpoint read-back, recorded into the history where the boiler's CH
        setpoint signal is not mapped: the lowest water temperature's evidence reads the setpoint
        from it while the plugin sets the water (X6). ``None`` otherwise."""
        if Signal.CH_SETPOINT in self.signals or not self.control.configured:
            return None
        return self.control.confirmed_entity

    @property
    def watched_entities(self) -> tuple[str, ...]:
        """Every entity whose changes the plugin follows."""
        entities = [
            *self.signals.values(),
            *self.zone_entities,
            *self.circuit_flow_entities.values(),
            *self.circuit_request_entities.values(),
            *self.circuit_need_entities.values(),
        ]
        if self.weather:
            entities.append(self.weather)
        if self.setpoint_read_back:
            entities.append(self.setpoint_read_back)
        return tuple(dict.fromkeys(entities))

    @classmethod
    def from_options(cls, options: Mapping[str, Any], strict_control: bool = True) -> EntryConfig:
        """The entry's configuration. ``strict_control=False`` (at setup): a control section that
        cannot be used leaves control out with ``control_problem`` set instead of failing, so
        the monitor keeps running and a hand-back still owed can go out."""
        signals, shared = _signals(_section(options, SIGNALS))
        stored_boiler = _section(options, BOILER)
        panel_problem: str | None = None
        try:
            panel = _panel(stored_boiler)
        except ConfigError as err:
            # Decision 12: an answer this version does not know leaves control out at setup,
            # the monitor running; the options show it on its panel.
            if strict_control:
                raise
            panel, panel_problem = BoilerPanel(), str(err)
        boiler_data = _resolved_boiler(stored_boiler, panel)
        boiler = Boiler(
            _enum(BoilerClass, boiler_data, "class", BoilerClass.READ_ONLY, "invalid_boiler"),
            _enum(DhwType, boiler_data, "dhw", DhwType.NONE, "invalid_boiler"),
            _flag("invalid_boiler", boiler_data, "condensing", True),
            _flag("invalid_boiler", boiler_data, "bypass", False),
        )
        circuits, circuit_entities = _circuits(_section(options, CIRCUITS))
        zones, zone_configs = _zones(
            _section(options, ZONES),
            {c.circuit_id for c in circuits},
            options.get(CIRCUITS),
        )
        installation = Installation(boiler, circuits, zones)
        errors = [i for i in installation.issues() if i.severity.value == "error"]
        if errors:
            raise ConfigError(errors[0].code.value, errors[0].subject)
        parameters = _parameters(_section(options, PARAMETERS), _section(options, BUILDING))
        freshness, weather_max_age = _freshness(_section(options, FRESHNESS))
        monitor = _monitor(
            _section(options, MONITOR),
            boiler_data,
            control_sets_water(boiler, options.get(CONTROL)),
        )
        control_problem: str | None = None
        try:
            control = _control(
                _section(options, CONTROL),
                installation,
                parameters,
                panel,
                _section(options, SIGNALS),
                frozenset(circuit_entities.requests),
            )
        except ConfigError as err:
            if strict_control:
                raise
            control, control_problem = ControlOptions(), str(err)
        if panel_problem is not None and has_control_section(options):
            control, control_problem = ControlOptions(), panel_problem
        return cls(
            level=str(options.get(LEVEL, LEVEL_SIMPLE)),
            signals=signals,
            weather=options.get(WEATHER) or None,
            installation=installation,
            parameters=parameters,
            zones=tuple(zone_configs),
            circuit_flow_entities=circuit_entities.flow,
            circuit_request_entities=circuit_entities.requests,
            circuit_need_entities=circuit_entities.needs,
            monitor=monitor,
            freshness=freshness,
            control=control,
            control_problem=control_problem,
            weather_max_age_s=weather_max_age,
            shared_signals=shared,
            panel=panel,
        )


type EntityVisit = Callable[[str, str], str]


def named_entities(options: Mapping[str, Any]) -> dict[str, tuple[str, ...]]:
    """Every entity the options name, each with the fields that name it (``signals.flame``,
    ``zones``, ``control.setpoint_entity``, ...) — what a rename is followed in and a removal
    names (P-19). Options of another shape (a hand edit) are read as far as they go."""
    found: dict[str, list[str]] = {}

    def note(field_name: str, entity: str) -> str:
        found.setdefault(entity, []).append(field_name)
        return entity

    _map_entities(options, note)
    return {entity: tuple(fields) for entity, fields in found.items()}


def rename_entity(options: Mapping[str, Any], old: str, new: str) -> dict[str, Any]:
    """The options with the entity ``old`` renamed ``new`` wherever they name it (P-19: Home
    Assistant renamed it); equal to them where they do not. The stored options are not
    touched."""
    return _map_entities(options, lambda _field, entity: new if entity == old else entity)


def _map_entities(options: Mapping[str, Any], visit: EntityVisit) -> dict[str, Any]:
    """The options rebuilt with ``visit(field, entity)`` for every entity they name — one list
    of fields for following and for renaming. A part of another shape stays as it is."""
    result = dict(options)
    signals = options.get(SIGNALS)
    if isinstance(signals, Mapping):
        result[SIGNALS] = {
            key: _visit(visit, f"{SIGNALS}.{key}", value) for key, value in signals.items()
        }
    if WEATHER in options:
        result[WEATHER] = _visit(visit, WEATHER, options[WEATHER])
    circuits = options.get(CIRCUITS)
    if isinstance(circuits, list):
        result[CIRCUITS] = [_circuit_entities(visit, item) for item in circuits]
    zones = options.get(ZONES)
    if isinstance(zones, list):
        result[ZONES] = [_zone_entities(visit, item) for item in zones]
    control = options.get(CONTROL)
    if isinstance(control, Mapping):
        result[CONTROL] = map_control_entities(
            control, lambda key, entity: visit(f"{CONTROL}.{key}", entity)
        )
    return result


def _visit(visit: EntityVisit, field_name: str, value: Any) -> Any:
    return visit(field_name, value) if isinstance(value, str) and value else value


def _visit_item(
    visit: EntityVisit, item: Mapping[str, Any], key: str, field_name: str
) -> dict[str, Any]:
    result = dict(item)
    if key in item:
        result[key] = _visit(visit, field_name, item[key])
    return result


def _circuit_entities(visit: EntityVisit, item: Any) -> Any:
    """A circuit with its flow sensor and the zones it lists visited (I8, decision F4: the
    zones are the circuits')."""
    if not isinstance(item, Mapping):
        return item
    prefix = f"{CIRCUITS}.{item.get('id')}"
    result = _visit_item(visit, item, "flow_entity", f"{prefix}.flow_entity")
    for key in (REQUEST_ENTITY, NEEDED_ENTITY):  # I8 (F3)
        result = _visit_item(visit, result, key, f"{prefix}.{key}")
    for key in (CIRCUIT_ZONES, *CIRCUIT_EMITTERS):
        listed = item.get(key)
        if isinstance(listed, list):  # named as the zones, as before: no internal ID shown
            result[key] = [_visit(visit, ZONES, entity) for entity in listed]
    return result


def _zone_entities(visit: EntityVisit, item: Any) -> Any:
    """A zone item with its thermostat visited."""
    if not isinstance(item, Mapping):
        return item
    return _visit_item(visit, item, "entity_id", ZONES)


def _enum[E: StrEnum](kind: type[E], data: Mapping[str, Any], key: str, default: E, code: str) -> E:
    """A stored choice; one this version does not know raises ``ConfigError(code, key)``."""
    try:
        return kind(data.get(key, default))
    except ValueError as err:
        raise ConfigError(code, key) from err


def _signals(data: Mapping[str, Any]) -> tuple[dict[Signal, str], dict[Signal, Signal]]:
    """The mapped signals, in the form's order, and those dropped because their entity feeds an
    earlier one (each with the signal that kept it): one entity feeds one signal (X5.2). A field
    left empty maps nothing."""
    given: dict[Signal, str] = {}
    for key, entity in data.items():
        if not entity or key == CH_ENABLED:  # control's read-back only (I8.5b)
            continue
        try:
            signal = Signal(key)
        except ValueError:
            _ignore_unknown("signals", key)
            continue
        given[signal] = str(entity)
    signals: dict[Signal, str] = {}
    shared: dict[Signal, Signal] = {}
    owner: dict[str, Signal] = {}
    for signal in SIGNAL_PRECEDENCE:
        entity = given.get(signal)
        if entity is None:
            continue
        if entity in owner:
            shared[signal] = owner[entity]
            continue
        owner[entity] = signal
        signals[signal] = entity
    # No signal is required for the entry (X8): a home with only a relay is monitored too, and
    # water-temperature control gets a blocker where flame or flow is missing.
    return signals, shared


def _read[T](code: str, key: str, read: Callable[[], T]) -> T:
    """A stored value read by ``read``; one that cannot be read — of a kind this version does
    not know, not a number, missing where required — raises ``ConfigError(code, key)``."""
    try:
        return read()
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise ConfigError(code, key) from err


def _bounded(
    code: str, data: Mapping[str, Any], key: str, bounds: tuple[float, float]
) -> float | None:
    """A stored number the form bounds; none stored, ``None``. One that is not a finite number
    within ``bounds`` — nan, inf, out of range, a flag — raises ``ConfigError(code, key)``: never
    used, never widened (PB-24)."""
    raw = data.get(key)
    value = None if isinstance(raw, bool) else _read(code, key, lambda: _float_or_none(raw))
    if value is None and raw in (None, ""):
        return None
    low, high = bounds
    if value is None or not low <= value <= high:  # nan fails too
        raise ConfigError(code, key)
    return value


def _flag(code: str, data: Mapping[str, Any], key: str, default: bool) -> bool:
    """A stored yes or no; none stored, ``default``. Anything else — "false" as text, a number —
    raises ``ConfigError(code, key)``: never read as true (PB-24)."""
    value = data.get(key)
    if value is None:
        return default
    if not isinstance(value, bool):
        raise ConfigError(code, key)
    return value


def _item_text(item: Any, key: str, code: str) -> str:
    """A list item's required text (a circuit's ID, a zone's entity); missing or of another
    shape, ``ConfigError(code, key)``."""
    try:
        return str(item[key])
    except (KeyError, TypeError, IndexError) as err:
        raise ConfigError(code, key) from err


def _circuit_number(item: Mapping[str, Any], key: str) -> float | None:
    return _bounded("invalid_circuit", item, key, CIRCUIT_BOUNDS[key])


# What a circuit run by other automation reads (I8, decision F3): whether it asks for heat,
# and the water it needs.
REQUEST_ENTITY = "request_entity"
NEEDED_ENTITY = "needed_entity"
NEEDED_TEMPERATURE = "needed_temperature"


@dataclass(frozen=True, slots=True)
class CircuitEntities:
    """The entities circuits name: a mixed or fixed circuit's own flow sensor, and a circuit
    run by other automation's request and need (I8, decision F3) — each by circuit."""

    flow: dict[str, str] = field(default_factory=dict)
    requests: dict[str, str] = field(default_factory=dict)
    needs: dict[str, str] = field(default_factory=dict)


def _circuits(data: Any) -> tuple[tuple[Circuit, ...], CircuitEntities]:
    if not data:
        return (Circuit("main"),), CircuitEntities()
    circuits: list[Circuit] = []
    entities = CircuitEntities()
    for item in data:
        circuit_id = _item_text(item, "id", "invalid_circuit")
        max_flow = _circuit_number(item, "max_flow")
        alarm_at = alarm_s = None
        if max_flow is not None:
            # Decision 10: the too-hot alarm's temperature and time, pre-filled with the maximum
            # + 5 K and 10 minutes where none is stored — never empty.
            alarm_at = _circuit_number(item, "max_flow_alarm")
            if alarm_at is None:
                alarm_at = max_flow + CIRCUIT_ALARM_RISE_K
            minutes = _circuit_number(item, "max_flow_alarm_min")
            alarm_s = (CIRCUIT_ALARM_MIN if minutes is None else minutes) * 60.0
        control = _enum(
            CircuitControl, item, "control", CircuitControl.UNMIXED_SHARED, "invalid_circuit"
        )
        other = control is CircuitControl.SEPARATE  # its request and need, kept otherwise
        circuits.append(
            Circuit(
                circuit_id,
                control,
                _circuit_number(item, "fixed_temperature"),
                max_flow,
                alarm_at,
                alarm_s,
                _circuit_number(item, NEEDED_TEMPERATURE) if other else None,
            )
        )
        if item.get("flow_entity"):
            entities.flow[circuit_id] = str(item["flow_entity"])
        for key, found in ((REQUEST_ENTITY, entities.requests), (NEEDED_ENTITY, entities.needs)):
            if other and item.get(key):
                found[circuit_id] = str(item[key])
    return tuple(circuits), entities


def circuits_hold_zones(circuits: Any) -> bool:
    """I8 (decision F4): the zones are the circuits' — each lists those it feeds; an entry from
    before minor version 20 (or a hand edit) still names a circuit in each zone."""
    return isinstance(circuits, list) and any(
        isinstance(item, Mapping) and CIRCUIT_ZONES in item for item in circuits
    )


# I8 (decisions F2, F4): what a circuit lists — the VT zones it feeds, and of them those with
# underfloor heating and those with convectors (the rest radiators).
CIRCUIT_ZONES = "zones"
CIRCUIT_EMITTERS = {"underfloor": EmitterType.UNDERFLOOR, "convectors": EmitterType.CONVECTOR}


def _zones(
    data: Any, circuit_ids: set[str], circuits: Any = None
) -> tuple[tuple[Zone, ...], list[ZoneConfig]]:
    if circuits_hold_zones(circuits):
        return _circuit_zones(data, circuits)
    zones: list[Zone] = []
    configs: list[ZoneConfig] = []
    default_circuit = sorted(circuit_ids)[0] if len(circuit_ids) == 1 else None
    for item in data or []:
        entity_id = _item_text(item, "entity_id", "invalid_zone")
        circuit = item.get("circuit") or default_circuit
        if circuit is None:
            raise ConfigError("zone_without_circuit", entity_id)
        zones.append(
            Zone(
                entity_id,
                str(circuit),
                _enum(EmitterType, item, "emitter", EmitterType.RADIATOR, "invalid_zone"),
                # Decision 4: only a clear "yes" counts; the zone step shows it (X5).
                closes_when_off=item.get("closes_when_off") is True,
            )
        )
        configs.append(ZoneConfig(entity_id))
    return tuple(zones), configs


def zones_on_circuits(options: Mapping[str, Any]) -> dict[str, Any] | None:
    """The circuits and the zones' section as this version stores them (I8.7c, decisions F2 and
    F4), from an entry that names a circuit in each zone: each circuit lists the zones it
    feeds, and of them those with underfloor heating and with convectors; the zones' section
    keeps whether a zone's valves close when it is off. A zone naming no circuit is the one
    circuit's, where there is one; with none stored, the one the options imply (``main``, fed
    straight) gets them. ``None`` where the circuits hold the zones already, or the stored
    shapes leave nothing to move safely — zones or circuits of another shape, a zone naming a
    circuit that is not there, or none among several: the check reports them."""
    zones = options.get(ZONES)
    circuits = options.get(CIRCUITS)
    if circuits_hold_zones(circuits):
        return None
    if circuits is None or circuits == []:
        if not isinstance(zones, list) or not zones:
            return None
        circuits = [{"id": "main", "control": CircuitControl.UNMIXED_SHARED.value}]
    listed = [] if zones is None else zones
    if not isinstance(circuits, list) or not isinstance(listed, list):
        return None
    if not all(isinstance(c, Mapping) and c.get("id") not in (None, "") for c in circuits):
        return None
    if not all(isinstance(z, Mapping) and z.get("entity_id") for z in listed):
        return None
    lists: dict[str, dict[str, list[str]]] = {
        str(c["id"]): {CIRCUIT_ZONES: [], "underfloor": [], "convectors": []} for c in circuits
    }
    only = next(iter(lists)) if len(lists) == 1 else None
    for zone in listed:
        circuit = zone.get("circuit") or only
        if circuit is None or str(circuit) not in lists:
            return None
        found = lists[str(circuit)]
        entity = str(zone["entity_id"])
        found[CIRCUIT_ZONES].append(entity)
        for key, emitter in CIRCUIT_EMITTERS.items():
            if zone.get("emitter") == emitter.value:
                found[key].append(entity)
    moved: dict[str, Any] = {
        CIRCUITS: [
            {**c, **{k: v for k, v in lists[str(c["id"])].items() if v or k == CIRCUIT_ZONES}}
            for c in circuits
        ]
    }
    if zones is not None:
        moved[ZONES] = [
            {"entity_id": str(z["entity_id"]), "closes_when_off": True}
            for z in listed
            if z.get("closes_when_off") is True
        ]
    return moved


def _circuit_zones(data: Any, circuits: list[Any]) -> tuple[tuple[Zone, ...], list[ZoneConfig]]:
    """The zones as the circuits list them (I8, decision F4): each zone in its circuit, its
    emitter as the circuit lists it (F2); whether its valves close when it is off from the
    zones' own section (decision 4: only a clear "yes" counts). A zone in two circuits is the
    installation check's to report."""
    closes = {
        str(item.get("entity_id")): item.get("closes_when_off") is True
        for item in data or []
        if isinstance(item, Mapping)
    }
    zones: list[Zone] = []
    configs: list[ZoneConfig] = []
    for circuit in circuits:
        if not isinstance(circuit, Mapping):
            raise ConfigError("invalid_circuit", "-")
        circuit_id = _item_text(circuit, "id", "invalid_circuit")
        listed = _zone_list(circuit, CIRCUIT_ZONES, circuit_id)
        emitters = {
            entity: emitter
            for key, emitter in CIRCUIT_EMITTERS.items()
            for entity in _zone_list(circuit, key, circuit_id)
        }
        for entity_id in listed:
            emitter = emitters.get(entity_id, EmitterType.RADIATOR)
            zones.append(Zone(entity_id, circuit_id, emitter, closes.get(entity_id, False)))
            configs.append(ZoneConfig(entity_id))
    return tuple(zones), configs


def _zone_list(circuit: Mapping[str, Any], key: str, circuit_id: str) -> list[str]:
    raw = circuit.get(key)
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(e, str) and e for e in raw):
        raise ConfigError("invalid_circuit", circuit_id)
    return list(raw)


# I8 (decision B5): the heat loss is entered as the design load only; a stored loss coefficient
# (a hand edit — the migration turned the form's into the design load it gives) is left out.
NOT_ENTERED = frozenset({ParameterKey.LOSS_COEFFICIENT})


def _parameters(data: Mapping[str, Any], building: Mapping[str, Any]) -> ParameterSet:
    parameters = ParameterSet()
    for key, value in data.items():
        if value is None or value == "":
            continue
        try:
            parameter = ParameterKey(key)
        except ValueError:
            _ignore_unknown("parameters", key)
            continue
        if parameter in NOT_ENTERED:
            _LOGGER.warning(
                "Ignoring the %s in the options: the heat loss is entered as the design load", key
            )
            continue
        try:
            parameters = parameters.with_estimate(parameter, Estimate(float(value), Source.ENTERED))
        except ValueError as err:
            raise ConfigError("implausible_parameter", key) from err
    design_outdoor = _value_or(parameters.value(ParameterKey.DESIGN_OUTDOOR), -15.0)
    indoor = _value_or(parameters.value(ParameterKey.INDOOR_REFERENCE), 20.0)
    if building.get("design_load_kw"):
        try:
            loss = loss_from_design_load(float(building["design_load_kw"]), design_outdoor, indoor)
            parameters = parameters.with_estimate(ParameterKey.LOSS_COEFFICIENT, loss)
        except (TypeError, ValueError) as err:  # a heat loss no house has: they do not fit
            raise ConfigError("implausible_parameter", "design_load_kw") from err
    return parameters


def _monitor_value(data: Mapping[str, Any], key: str, default: float | None) -> float:
    """A stored monitor number within the form's bounds; none stored, ``default``."""
    bounds = MONITORING_DAYS_BOUNDS if key == "monitoring_days" else MONITOR_BOUNDS[key]
    value = _bounded("invalid_monitor", data, key, bounds)
    if value is None:
        value = default
    if value is None:  # a band without a default limit: nothing to fall back on
        raise ConfigError("invalid_monitor", key)
    return value


def control_sets_water(boiler: Boiler, control: Any) -> bool:
    """S-22: whether 0.2.2's control sets the water temperature here — a flow-setpoint boiler
    whose control section, where there is one, does not switch a relay. Then low condensing is
    a problem control changes; through a relay (X8), or for a boiler control is not offered
    for, no problem the verdict finds is."""
    if boiler.boiler_class is not BoilerClass.FLOW_SETPOINT:
        return False
    return not (isinstance(control, Mapping) and control.get("write_path") == WritePath.RELAY)


def _monitor(
    data: Mapping[str, Any], boiler: Mapping[str, Any], sets_water: bool = False
) -> MonitorConfig:
    monitoring_days = _monitor_value(data, "monitoring_days", 7.0)
    window_days = _bounded(
        "invalid_monitor", data, "verdict_window_days", MONITOR_BOUNDS["verdict_window_days"]
    )
    window = None if window_days is None else int(window_days)
    return MonitorConfig(
        monitor=MonitorOptions(
            condensing_return=_monitor_value(data, "condensing_return", DEFAULT_CONDENSING_RETURN),
            short_burn_s=_monitor_value(data, "short_burn_min", 10.0) * 60.0,
            modulation_scale=_enum(
                ModulationScale, boiler, "modulation_scale", ModulationScale.RANGE, "invalid_boiler"
            ),
            # Declared without hot water: every burn heats. Never declared: burns are told apart.
            has_dhw=boiler.get("dhw") != DhwType.NONE,
            verdict=VerdictOptions(
                min_days=monitoring_days,
                condensing_boiler=_flag("invalid_boiler", boiler, "condensing", True),
                control_sets_water=sets_water,
            ),
            # Never shorter than the monitoring period: the verdict could not be reached.
            verdict_window_days=(
                None if window is None else max(window, math.ceil(monitoring_days))
            ),
        ),
        monitoring_days=monitoring_days,
        alarms=_alarm_thresholds(data),
    )


def _band(data: Mapping[str, Any], name: str, default: Band) -> Band:
    warning = _monitor_value(data, f"{name}_warning", default.warning)
    alarm = _monitor_value(data, f"{name}_alarm", default.alarm)
    # The alarm limit lies beyond the warning limit, on the dangerous side.
    if (alarm <= warning) if default.rising else (alarm >= warning):
        raise ConfigError("alarm_limits_out_of_order", name)
    return Band(warning, alarm, default.rising, default.hysteresis)


def _pressure_high(data: Mapping[str, Any]) -> Band | None:
    """The high-pressure band (decision 13): each limit optional, none by default; the alarm
    above the warning only where both are set."""
    warning, alarm = (
        _bounded("invalid_monitor", data, key, MONITOR_BOUNDS[key])
        for key in ("pressure_high_warning", "pressure_high_alarm")
    )
    if warning is not None and alarm is not None and alarm <= warning:
        raise ConfigError("alarm_limits_out_of_order", "pressure_high")
    return pressure_high_band(warning, alarm)


# Decision 13 of 0.2.3 (SB-18): minor version 5 took the high-pressure limits' defaults away;
# an entry from before keeps the ones it ran with (2.5 / 2.8 bar), so no alarm drops silently.
MIGRATED_PRESSURE_HIGH = (("pressure_high_warning", 2.5), ("pressure_high_alarm", 2.8))


def migrated_pressure_high(options: Mapping[str, Any]) -> dict[str, Any] | None:
    """The monitor section of an entry from before decision 13 with the water pressure mapped,
    each high-pressure limit it did not store set to the one it ran with; a stored limit stays
    as stored. ``None``: nothing to write — the pressure not mapped, both limits stored, or a
    section of another shape, which the reader refuses with its reason."""
    signals = options.get("signals")
    monitor = options.get("monitor", {})
    if not isinstance(signals, Mapping) or not isinstance(monitor, Mapping):
        return None
    if not signals.get(Signal.PRESSURE.value):
        return None
    missing = {k: v for k, v in MIGRATED_PRESSURE_HIGH if monitor.get(k) in (None, "")}
    return {**monitor, **missing} if missing else None


# 0.2.1's low-pressure limits and their defaults (Y1's migration).
OLD_LOW_PRESSURE = (("pressure_low_warning", 1.0), ("pressure_low_alarm", 0.7))


def migrated_monitor(monitor: Mapping[str, Any]) -> dict[str, Any]:
    """Y1's entry migration of the monitor section: 0.2.1's two low-pressure limits go; the
    first of them stored with a value other than its default — the warning, else the alarm —
    becomes the "add water" threshold, where it lies within 0.1–2.0 bar (provisional, K4);
    at their defaults (1.0 / 0.7 bar) nothing is carried over: none by default. A threshold
    already stored is kept."""
    result = {k: v for k, v in monitor.items() if k not in dict(OLD_LOW_PRESSURE)}
    if result.get("add_water_below") not in (None, ""):
        return result
    for key, default in OLD_LOW_PRESSURE:
        try:
            value = _float_or_none(monitor.get(key))
        except TypeError, ValueError:
            continue
        if value is None or not math.isfinite(value) or value == default:
            continue
        low, high = ADD_WATER_RANGE_BAR
        if low <= value <= high:
            result["add_water_below"] = round(value, 1)
        break
    return result


def _add_water(data: Mapping[str, Any]) -> Band | None:
    """The "add water" band (Y1): none without a threshold; one outside 0.1–2.0 bar — a hand
    edit — cannot be used. 0.2.1's two low-pressure limits are no longer read."""
    key = "add_water_below"
    threshold = _read("invalid_monitor", key, lambda: _float_or_none(data.get(key)))
    if threshold is None:
        return None
    low, high = ADD_WATER_RANGE_BAR
    if not low <= threshold <= high:
        raise ConfigError("invalid_monitor", key)
    return add_water_band(threshold)


def _alarm_thresholds(data: Mapping[str, Any]) -> AlarmThresholds:
    starts, burns = "starts_per_hour_limit", "unstable_burns_limit"
    return AlarmThresholds(
        pressure_low=_add_water(data),
        pressure_high=_pressure_high(data),
        flue_gas=_band(data, "flue_gas", FLUE_GAS_CONDENSING_BAND),
        starts_per_hour=int(_monitor_value(data, starts, DEFAULT_FREQUENT_STARTS_PER_HOUR)),
        unstable_burns_per_day=int(_monitor_value(data, burns, DEFAULT_UNSTABLE_BURNS_PER_DAY)),
    )


def _freshness(data: Mapping[str, Any]) -> tuple[dict[Signal, float | None], float | None]:
    """The age limit the user set for each signal, and the weather entity's own, stored under
    ``weather`` beside them and taken out first: it is no signal. A signal not stored — and the
    weather as ``None`` — takes its automatic limit, earned by its source (I6, decision 9);
    ``FRESHNESS_OFF`` (a stored 0): no limit, availability only, as the user chose."""

    low, high = FRESHNESS_BOUNDS_MIN

    def limit(key: str, value: Any) -> float | None:
        if value == 0 and not isinstance(value, bool):
            return FRESHNESS_OFF
        return _bounded("invalid_freshness", {key: value}, key, (low * 60.0, high * 60.0))

    result: dict[Signal, float | None] = {}
    for key, value in data.items():
        if key == WEATHER:
            continue
        try:
            signal = Signal(key)
        except ValueError:
            _ignore_unknown("freshness", key)
            continue
        result[signal] = limit(key, value)
    return result, limit(WEATHER, data.get(WEATHER))


def _control(
    data: Mapping[str, Any],
    installation: Installation,
    parameters: ParameterSet,
    panel: BoilerPanel | None = None,
    signals: Mapping[str, Any] | None = None,
    requests: frozenset[str] = frozenset(),
) -> ControlOptions:
    panel = BoilerPanel() if panel is None else panel
    entered = parameters.get(ParameterKey.DESIGN_OUTDOOR).estimate(Source.ENTERED)
    # I8.4b: the firmware's topics are the connection's, stored once; I8.5b: the read-backs are
    # boiler signals.
    topics = {"mqtt_top": panel.mqtt_top, "mqtt_node": panel.mqtt_node}
    try:
        return parse_control(
            with_boiler_inputs(data, topics, signals),
            installation,
            parameters.value(ParameterKey.MAX_CH_SETPOINT),
            connection=panel.connection,
            control_mode=panel.control_mode,
            design_outdoor=None if entered is None else entered.value,
            requests=requests,
        )
    except (AttributeError, KeyError, TypeError, ValueError) as err:
        raise ConfigError("invalid_control", str(err)) from err


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str | SupportsFloat):
        raise TypeError(f"not a number: {value!r}")
    return float(value)


def _value_or(value: float | None, default: float) -> float:
    return default if value is None else value
