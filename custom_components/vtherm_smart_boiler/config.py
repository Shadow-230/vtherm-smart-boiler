"""The config entry's options as core objects. No Home Assistant imports.

The config flow writes one options dictionary; everything else reads it through
``EntryConfig.from_options``, so there is a single definition of what each key means and of its
cautious default.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

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
from .control_config import ControlOptions, parse_control
from .core.alarms import (
    DEFAULT_FREQUENT_STARTS_PER_HOUR,
    DEFAULT_UNSTABLE_BURNS_PER_DAY,
    FLUE_GAS_CONDENSING_BAND,
    PRESSURE_HIGH_BAND,
    PRESSURE_LOW_BAND,
    Band,
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
from .core.signals import REQUIRED_SIGNALS, Signal
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
    """Limits of the current alarms (advanced options)."""

    pressure_low: Band = PRESSURE_LOW_BAND
    pressure_high: Band = PRESSURE_HIGH_BAND
    flue_gas: Band = FLUE_GAS_CONDENSING_BAND
    starts_per_hour: int = DEFAULT_FREQUENT_STARTS_PER_HOUR
    unstable_burns_per_day: int = DEFAULT_UNSTABLE_BURNS_PER_DAY


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

    @property
    def zone_entities(self) -> tuple[str, ...]:
        return tuple(z.entity_id for z in self.zones)

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
        return tuple(dict.fromkeys(entities))

    @classmethod
    def from_options(
        cls, options: Mapping[str, Any], strict_control: bool = True
    ) -> EntryConfig:
        """The entry's configuration. ``strict_control=False`` (at setup): a control section that
        cannot be used leaves control out with ``control_problem`` set instead of failing, so
        the monitor keeps running and a hand-back still owed can go out."""
        signals = _signals(options.get(SIGNALS, {}))
        boiler_data = options.get(BOILER, {})
        boiler = Boiler(
            BoilerClass(boiler_data.get("class", BoilerClass.READ_ONLY)),
            DhwType(boiler_data.get("dhw", DhwType.NONE)),
            bool(boiler_data.get("condensing", True)),
            bool(boiler_data.get("shared_return", False)),
        )
        circuits, flow_entities = _circuits(options.get(CIRCUITS, []))
        zones, zone_configs = _zones(options.get(ZONES, []), {c.circuit_id for c in circuits})
        installation = Installation(boiler, circuits, zones)
        errors = [i for i in installation.issues() if i.severity.value == "error"]
        if errors:
            raise ConfigError(errors[0].code.value, errors[0].subject)
        parameters = _parameters(options.get(PARAMETERS, {}), options.get(BUILDING, {}))
        reference = _reference(options.get(REFERENCE_ROOM, {}), [z.zone_id for z in zones])
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
            monitor=_monitor(options.get(MONITOR, {}), boiler_data),
            freshness=_freshness(options.get(FRESHNESS, {})),
            control=control,
            control_problem=control_problem,
        )


def _signals(data: Mapping[str, Any]) -> dict[Signal, str]:
    signals: dict[Signal, str] = {}
    for key, entity in data.items():
        if not entity:
            continue
        try:
            signal = Signal(key)
        except ValueError as err:
            raise ConfigError("unknown_signal", key) from err
        signals[signal] = str(entity)
    for signal in sorted(REQUIRED_SIGNALS):
        if signal not in signals:
            raise ConfigError("missing_signal", signal.value)
    return signals


def _circuits(data: Any) -> tuple[tuple[Circuit, ...], dict[str, str]]:
    if not data:
        return (Circuit("main"),), {}
    circuits: list[Circuit] = []
    flow_entities: dict[str, str] = {}
    for item in data:
        circuit_id = str(item["id"])
        circuits.append(
            Circuit(
                circuit_id,
                CircuitControl(item.get("control", CircuitControl.UNMIXED_SHARED)),
                _float_or_none(item.get("fixed_temperature")),
                _float_or_none(item.get("max_flow")),
            )
        )
        if item.get("flow_entity"):
            flow_entities[circuit_id] = str(item["flow_entity"])
    return tuple(circuits), flow_entities


def _zones(data: Any, circuit_ids: set[str]) -> tuple[tuple[Zone, ...], list[ZoneConfig]]:
    zones: list[Zone] = []
    configs: list[ZoneConfig] = []
    default_circuit = sorted(circuit_ids)[0] if len(circuit_ids) == 1 else None
    for item in data or []:
        entity_id = str(item["entity_id"])
        circuit = item.get("circuit") or default_circuit
        if circuit is None:
            raise ConfigError("zone_without_circuit", entity_id)
        zones.append(
            Zone(
                entity_id,
                str(circuit),
                EmitterType(item.get("emitter", EmitterType.RADIATOR)),
                _float_or_none(item.get("reference_output_w")),
                _float_or_none(item.get("exponent")),
            )
        )
        sources = tuple(
            ForeignHeatSource(
                str(source["entity_id"]),
                SourceKind(source.get("kind", SourceKind.SWITCH)),
                _float_or_none(source.get("threshold")),
            )
            for source in item.get("foreign_heat", [])
        )
        configs.append(ZoneConfig(entity_id, sources))
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
    if parameters.get(ParameterKey.LOSS_COEFFICIENT).estimate(Source.ENTERED) is None:
        loss: Estimate | None = None
        source = "design_load_kw" if building.get("design_load_kw") else "floor_area"
        try:
            if building.get("design_load_kw"):
                loss = loss_from_design_load(
                    float(building["design_load_kw"]), design_outdoor, indoor
                )
            elif building.get("floor_area") and building.get("insulation"):
                loss = loss_from_coarse_answers(
                    float(building["floor_area"]),
                    InsulationClass(building["insulation"]),
                    design_outdoor,
                    indoor,
                )
            if loss is not None:
                parameters = parameters.with_estimate(ParameterKey.LOSS_COEFFICIENT, loss)
        except ValueError as err:  # a heat loss no house has: the answers do not fit together
            raise ConfigError("implausible_parameter", source) from err
    if building.get("thermal_mass"):
        parameters = parameters.with_estimate(
            ParameterKey.THERMAL_TIME_CONSTANT,
            time_constant_from_mass(ThermalMass(building["thermal_mass"])),
        )
    return parameters


def _reference(data: Mapping[str, Any], zone_ids: list[str]) -> ReferenceRoomConfig:
    strategy = Strategy(data.get("strategy", Strategy.LARGEST_DEFICIT))
    zone = data.get("zone") or None
    if strategy is Strategy.CHOSEN_ZONE and zone not in zone_ids:
        raise ConfigError("reference_zone_unknown", zone)
    return ReferenceRoomConfig(
        strategy, zone, float(data.get("switch_margin", DEFAULT_SWITCH_MARGIN_K))
    )


def _monitor(data: Mapping[str, Any], boiler: Mapping[str, Any]) -> MonitorConfig:
    monitoring_days = float(data.get("monitoring_days", 7.0))
    return MonitorConfig(
        monitor=MonitorOptions(
            condensing_return=float(data.get("condensing_return", DEFAULT_CONDENSING_RETURN)),
            short_burn_s=float(data.get("short_burn_min", 10.0)) * 60.0,
            modulation_scale=ModulationScale(boiler.get("modulation_scale", ModulationScale.RANGE)),
            verdict=VerdictOptions(min_days=monitoring_days),
        ),
        monitoring_days=monitoring_days,
        near_room_k=float(data.get("near_room_k", DEFAULT_NEAR_ROOM_K)),
        foreign_heat_hold_s=float(data.get("foreign_heat_hold_min", DEFAULT_HOLD_S / 60.0)) * 60.0,
        alarms=_alarm_thresholds(data),
    )


def _band(data: Mapping[str, Any], name: str, default: Band) -> Band:
    warning = float(data.get(f"{name}_warning", default.warning))
    alarm = float(data.get(f"{name}_alarm", default.alarm))
    # The alarm limit lies beyond the warning limit, on the dangerous side.
    if (alarm <= warning) if default.rising else (alarm >= warning):
        raise ConfigError("alarm_limits_out_of_order", name)
    return Band(warning, alarm, default.rising, default.hysteresis)


def _alarm_thresholds(data: Mapping[str, Any]) -> AlarmThresholds:
    return AlarmThresholds(
        pressure_low=_band(data, "pressure_low", PRESSURE_LOW_BAND),
        pressure_high=_band(data, "pressure_high", PRESSURE_HIGH_BAND),
        flue_gas=_band(data, "flue_gas", FLUE_GAS_CONDENSING_BAND),
        starts_per_hour=int(data.get("starts_per_hour_limit", DEFAULT_FREQUENT_STARTS_PER_HOUR)),
        unstable_burns_per_day=int(
            data.get("unstable_burns_limit", DEFAULT_UNSTABLE_BURNS_PER_DAY)
        ),
    )


def _freshness(data: Mapping[str, Any]) -> dict[Signal, float | None]:
    result: dict[Signal, float | None] = {}
    for key, value in data.items():
        try:
            signal = Signal(key)
        except ValueError as err:
            raise ConfigError("unknown_signal", key) from err
        result[signal] = None if value is None else float(value)
    return result


def _control(
    data: Mapping[str, Any] | None, installation: Installation, parameters: ParameterSet
) -> ControlOptions:
    try:
        return parse_control(
            data, installation, parameters.value(ParameterKey.MAX_CH_SETPOINT)
        )
    except (KeyError, TypeError, ValueError) as err:
        raise ConfigError("invalid_control", str(err)) from err


def _float_or_none(value: object) -> float | None:
    if value is None or value == "":
        return None
    return float(value)  # type: ignore[arg-type]


def _value_or(value: float | None, default: float) -> float:
    return default if value is None else value
