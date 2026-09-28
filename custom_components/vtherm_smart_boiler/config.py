"""The config entry's options as core objects. No Home Assistant imports.

The config flow writes one options dictionary; everything else reads it through
``EntryConfig.from_options``, so there is a single definition of what each key means and of its
cautious default. A stored value this version does not know raises a ``ConfigError`` naming its
section (``invalid_boiler``, ``invalid_circuit``, ...), which the options flow shows on that
section's step (P-70). One entity mapped to two signals is kept for the first in the form's
order; the later signal is dropped and recorded in ``shared_signals`` — control gets a blocker,
the monitor runs (X5.2). No signal is required (X8): flame and flow serve the monitor and
water-temperature control, which gets a blocker without them.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, SupportsFloat

from .const import (
    BOILER,
    BUILDING,
    CIRCUITS,
    CONTROL,
    FRESHNESS,
    LEVEL,
    LEVEL_SIMPLE,
    MONITOR,
    PARAMETERS,
    REFERENCE_ROOM,
    SIGNALS,
    WEATHER,
    ZONES,
)
from .control_config import ControlOptions, WritePath, map_control_entities, parse_control
from .core.alarms import (
    ADD_WATER_RANGE_BAR,
    CIRCUIT_ALARM_MIN,
    CIRCUIT_ALARM_RISE_K,
    DEFAULT_FREQUENT_STARTS_PER_HOUR,
    DEFAULT_UNSTABLE_BURNS_PER_DAY,
    FLUE_GAS_CONDENSING_BAND,
    PRESSURE_HIGH_BAND,
    Band,
    add_water_band,
)
from .core.building import (
    InsulationClass,
    ThermalMass,
    loss_from_coarse_answers,
    loss_from_design_load,
    time_constant_from_mass,
)
from .core.foreign_heat import DEFAULT_HOLD_S, ForeignHeatSource, SourceKind
from .core.hot_water import DEFAULT_NEAR_ROOM_K
from .core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    CircuitControl,
    DhwType,
    EmitterType,
    Installation,
    Zone,
)
from .core.metrics import DEFAULT_CONDENSING_RETURN, ModulationScale
from .core.monitor import MonitorOptions
from .core.parameters import Estimate, ParameterKey, ParameterSet, Source
from .core.reference_room import DEFAULT_SWITCH_MARGIN_K, Strategy
from .core.signals import SIGNAL_PRECEDENCE, Signal
from .core.verdict import VerdictOptions


class ConfigError(ValueError):
    """The options cannot be used; ``code`` is a translation key, ``subject`` what it concerns."""

    def __init__(self, code: str, subject: str | None = None) -> None:
        super().__init__(f"{code}: {subject}" if subject else code)
        self.code = code
        self.subject = subject


@dataclass(frozen=True, slots=True)
class ZoneConfig:
    entity_id: str
    foreign_heat: tuple[ForeignHeatSource, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceRoomConfig:
    strategy: Strategy = Strategy.LARGEST_DEFICIT
    zone: str | None = None
    switch_margin: float = DEFAULT_SWITCH_MARGIN_K


@dataclass(frozen=True, slots=True)
class AlarmThresholds:
    """Limits of the current alarms (advanced options). ``pressure_low``: the "add water" band
    from the threshold the user took from the boiler's manual — none by default, and then no
    low-pressure alarm at all (Y1)."""

    pressure_low: Band | None = None
    pressure_high: Band = PRESSURE_HIGH_BAND
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
    near_room_k: float = DEFAULT_NEAR_ROOM_K
    foreign_heat_hold_s: float = DEFAULT_HOLD_S
    alarms: AlarmThresholds = field(default_factory=AlarmThresholds)


@dataclass(frozen=True, slots=True)
class EntryConfig:
    level: str
    signals: dict[Signal, str]
    weather: str | None
    installation: Installation
    parameters: ParameterSet
    zones: tuple[ZoneConfig, ...]
    circuit_flow_entities: dict[str, str]
    reference_room: ReferenceRoomConfig
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
        ]
        entities += [source.source_id for zone in self.zones for source in zone.foreign_heat]
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
        signals, shared = _signals(options.get(SIGNALS, {}))
        boiler_data = options.get(BOILER, {})
        boiler = Boiler(
            _enum(BoilerClass, boiler_data, "class", BoilerClass.READ_ONLY, "invalid_boiler"),
            _enum(DhwType, boiler_data, "dhw", DhwType.NONE, "invalid_boiler"),
            bool(boiler_data.get("condensing", True)),
            bool(boiler_data.get("bypass", False)),
        )
        circuits, flow_entities = _circuits(options.get(CIRCUITS, []))
        zones, zone_configs = _zones(options.get(ZONES, []), {c.circuit_id for c in circuits})
        installation = Installation(boiler, circuits, zones)
        errors = [i for i in installation.issues() if i.severity.value == "error"]
        if errors:
            raise ConfigError(errors[0].code.value, errors[0].subject)
        parameters = _parameters(options.get(PARAMETERS, {}), options.get(BUILDING, {}))
        reference = _reference(options.get(REFERENCE_ROOM, {}), [z.zone_id for z in zones])
        freshness, weather_max_age = _freshness(options.get(FRESHNESS, {}))
        control_problem: str | None = None
        try:
            control = _control(options.get(CONTROL), installation, parameters)
        except ConfigError as err:
            if strict_control:
                raise
            control, control_problem = ControlOptions(), str(err)
        return cls(
            level=str(options.get(LEVEL, LEVEL_SIMPLE)),
            signals=signals,
            weather=options.get(WEATHER) or None,
            installation=installation,
            parameters=parameters,
            zones=tuple(zone_configs),
            circuit_flow_entities=flow_entities,
            reference_room=reference,
            monitor=_monitor(
                options.get(MONITOR, {}),
                boiler_data,
                control_sets_water(boiler, options.get(CONTROL)),
            ),
            freshness=freshness,
            control=control,
            control_problem=control_problem,
            weather_max_age_s=weather_max_age,
            shared_signals=shared,
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
        result[CIRCUITS] = [
            _visit_item(visit, item, "flow_entity", f"{CIRCUITS}.{item.get('id')}.flow_entity")
            if isinstance(item, Mapping)
            else item
            for item in circuits
        ]
    zones = options.get(ZONES)
    if isinstance(zones, list):
        result[ZONES] = [_zone_entities(visit, item) for item in zones]
    reference = options.get(REFERENCE_ROOM)
    if isinstance(reference, Mapping):
        result[REFERENCE_ROOM] = _visit_item(visit, reference, "zone", f"{REFERENCE_ROOM}.zone")
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


def _zone_entities(visit: EntityVisit, item: Any) -> Any:
    """A zone item with its thermostat and its foreign-heat sources visited."""
    if not isinstance(item, Mapping):
        return item
    zone = _visit_item(visit, item, "entity_id", ZONES)
    sources = item.get("foreign_heat")
    if isinstance(sources, list):
        field_name = f"{ZONES}.foreign_heat ({item.get('entity_id')})"
        zone["foreign_heat"] = [
            _visit_item(visit, source, "entity_id", field_name)
            if isinstance(source, Mapping)
            else source
            for source in sources
        ]
    return zone


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
        if not entity:
            continue
        try:
            signal = Signal(key)
        except ValueError as err:
            raise ConfigError("unknown_signal", key) from err
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
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError(code, key) from err


def _item_text(item: Any, key: str, code: str) -> str:
    """A list item's required text (a circuit's ID, a zone's entity); missing or of another
    shape, ``ConfigError(code, key)``."""
    try:
        return str(item[key])
    except (KeyError, TypeError, IndexError) as err:
        raise ConfigError(code, key) from err


def _circuit_number(item: Mapping[str, Any], key: str) -> float | None:
    return _read("invalid_circuit", key, lambda: _float_or_none(item.get(key)))


def _circuits(data: Any) -> tuple[tuple[Circuit, ...], dict[str, str]]:
    if not data:
        return (Circuit("main"),), {}
    circuits: list[Circuit] = []
    flow_entities: dict[str, str] = {}
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
        circuits.append(
            Circuit(
                circuit_id,
                _enum(
                    CircuitControl,
                    item,
                    "control",
                    CircuitControl.UNMIXED_SHARED,
                    "invalid_circuit",
                ),
                _circuit_number(item, "fixed_temperature"),
                max_flow,
                alarm_at,
                alarm_s,
            )
        )
        if item.get("flow_entity"):
            flow_entities[circuit_id] = str(item["flow_entity"])
    return tuple(circuits), flow_entities


def _zone_number(item: Mapping[str, Any], key: str) -> float | None:
    return _read("invalid_zone", key, lambda: _float_or_none(item.get(key)))


def _sources(item: Mapping[str, Any]) -> tuple[ForeignHeatSource, ...]:
    def read() -> tuple[ForeignHeatSource, ...]:
        return tuple(
            ForeignHeatSource(
                str(source["entity_id"]),
                SourceKind(source.get("kind", SourceKind.SWITCH)),
                _float_or_none(source.get("threshold")),
            )
            for source in item.get("foreign_heat", [])
        )

    return _read("invalid_zone", "foreign_heat", read)


def _zones(data: Any, circuit_ids: set[str]) -> tuple[tuple[Zone, ...], list[ZoneConfig]]:
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
                _zone_number(item, "reference_output_w"),
                _zone_number(item, "exponent"),
                # Decision 4: only a clear "yes" counts; the zone step shows it (X5).
                closes_when_off=item.get("closes_when_off") is True,
            )
        )
        configs.append(ZoneConfig(entity_id, _sources(item)))
    return tuple(zones), configs


def _parameters(data: Mapping[str, Any], building: Mapping[str, Any]) -> ParameterSet:
    parameters = ParameterSet()
    for key, value in data.items():
        if value is None or value == "":
            continue
        try:
            parameter = ParameterKey(key)
        except ValueError as err:
            raise ConfigError("unknown_parameter", key) from err
        try:
            parameters = parameters.with_estimate(parameter, Estimate(float(value), Source.ENTERED))
        except ValueError as err:
            raise ConfigError("implausible_parameter", key) from err
    design_outdoor = _value_or(parameters.value(ParameterKey.DESIGN_OUTDOOR), -15.0)
    indoor = _value_or(parameters.value(ParameterKey.INDOOR_REFERENCE), 20.0)
    # The building's choices first: one this version does not know is named, not taken for an
    # implausible house.
    insulation = (
        _enum(InsulationClass, building, "insulation", InsulationClass.AVERAGE, "invalid_building")
        if building.get("insulation")
        else None
    )
    mass = (
        _enum(ThermalMass, building, "thermal_mass", ThermalMass.MEDIUM, "invalid_building")
        if building.get("thermal_mass")
        else None
    )
    if parameters.get(ParameterKey.LOSS_COEFFICIENT).estimate(Source.ENTERED) is None:
        loss: Estimate | None = None
        source = "design_load_kw" if building.get("design_load_kw") else "floor_area"
        try:
            if building.get("design_load_kw"):
                loss = loss_from_design_load(
                    float(building["design_load_kw"]), design_outdoor, indoor
                )
            elif building.get("floor_area") and insulation is not None:
                loss = loss_from_coarse_answers(
                    float(building["floor_area"]), insulation, design_outdoor, indoor
                )
            if loss is not None:
                parameters = parameters.with_estimate(ParameterKey.LOSS_COEFFICIENT, loss)
        except (TypeError, ValueError) as err:  # a heat loss no house has: they do not fit
            raise ConfigError("implausible_parameter", source) from err
    if mass is not None:
        parameters = parameters.with_estimate(
            ParameterKey.THERMAL_TIME_CONSTANT, time_constant_from_mass(mass)
        )
    return parameters


def _reference(data: Mapping[str, Any], zone_ids: list[str]) -> ReferenceRoomConfig:
    strategy = _enum(Strategy, data, "strategy", Strategy.LARGEST_DEFICIT, "invalid_reference")
    zone = data.get("zone") or None
    if strategy is Strategy.CHOSEN_ZONE and zone not in zone_ids:
        raise ConfigError("reference_zone_unknown", zone)
    margin = _read(
        "invalid_reference",
        "switch_margin",
        lambda: float(data.get("switch_margin", DEFAULT_SWITCH_MARGIN_K)),
    )
    return ReferenceRoomConfig(strategy, zone, margin)


def _monitor_value(data: Mapping[str, Any], key: str, default: float | None) -> float:
    return _read("invalid_monitor", key, lambda: float(data.get(key, default)))


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
    window = _read(
        "invalid_monitor",
        "verdict_window_days",
        lambda: (
            None
            if data.get("verdict_window_days") in (None, "")
            else int(data["verdict_window_days"])
        ),
    )
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
                condensing_boiler=bool(boiler.get("condensing", True)),
                control_sets_water=sets_water,
            ),
            # Never shorter than the monitoring period: the verdict could not be reached.
            verdict_window_days=(
                None if window is None else max(window, math.ceil(monitoring_days))
            ),
        ),
        monitoring_days=monitoring_days,
        near_room_k=_monitor_value(data, "near_room_k", DEFAULT_NEAR_ROOM_K),
        foreign_heat_hold_s=_monitor_value(data, "foreign_heat_hold_min", DEFAULT_HOLD_S / 60.0)
        * 60.0,
        alarms=_alarm_thresholds(data),
    )


def _band(data: Mapping[str, Any], name: str, default: Band) -> Band:
    warning = _monitor_value(data, f"{name}_warning", default.warning)
    alarm = _monitor_value(data, f"{name}_alarm", default.alarm)
    # The alarm limit lies beyond the warning limit, on the dangerous side.
    if (alarm <= warning) if default.rising else (alarm >= warning):
        raise ConfigError("alarm_limits_out_of_order", name)
    return Band(warning, alarm, default.rising, default.hysteresis)


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
        pressure_high=_band(data, "pressure_high", PRESSURE_HIGH_BAND),
        flue_gas=_band(data, "flue_gas", FLUE_GAS_CONDENSING_BAND),
        starts_per_hour=_read(
            "invalid_monitor",
            starts,
            lambda: int(data.get(starts, DEFAULT_FREQUENT_STARTS_PER_HOUR)),
        ),
        unstable_burns_per_day=_read(
            "invalid_monitor", burns, lambda: int(data.get(burns, DEFAULT_UNSTABLE_BURNS_PER_DAY))
        ),
    )


def _freshness(data: Mapping[str, Any]) -> tuple[dict[Signal, float | None], float | None]:
    """The age limit of each signal, and the weather entity's own, stored under ``weather`` beside
    them and taken out first: it is no signal. ``None``: no limit — availability only."""

    def limit(key: str, value: Any) -> float | None:
        return _read("invalid_freshness", key, lambda: None if value is None else float(value))

    result: dict[Signal, float | None] = {}
    for key, value in data.items():
        if key == WEATHER:
            continue
        try:
            signal = Signal(key)
        except ValueError as err:
            raise ConfigError("unknown_signal", key) from err
        result[signal] = limit(key, value)
    return result, limit(WEATHER, data.get(WEATHER))


def _control(
    data: Mapping[str, Any] | None, installation: Installation, parameters: ParameterSet
) -> ControlOptions:
    try:
        return parse_control(data, installation, parameters.value(ParameterKey.MAX_CH_SETPOINT))
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError("invalid_control", str(err)) from err


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str | SupportsFloat):
        raise TypeError(f"not a number: {value!r}")
    return float(value)


def _value_or(value: float | None, default: float) -> float:
    return default if value is None else value
