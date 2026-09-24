"""Sensors: boiler metrics, verdict, reference room, critical zones, emitter power factors, and
the state and setpoint of control."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .coordinator import MonitorData, SmartBoilerCoordinator
from .core.controller import ControlMode
from .core.emitters import FactorStatus
from .core.parameters import ParameterKey
from .core.signal_check import Feature, FeatureStatus, SignalStatus
from .core.signals import Signal
from .core.verdict import Verdict
from .core.zones import SelectionStatus
from .entity import ControlEntity, SmartBoilerEntity

type Value = float | str | None


@dataclass(frozen=True, kw_only=True)
class BoilerSensorDescription(SensorEntityDescription):
    value_fn: Callable[[MonitorData], Value]
    attributes_fn: Callable[[MonitorData], dict[str, Any]] | None = None
    needs: Feature | None = None  # created only when this feature is available or degraded


def _day(data: MonitorData):
    return data.analysis.day if data.analysis is not None else None


def _week(data: MonitorData):
    return data.analysis.week if data.analysis is not None else None


def _starts(data: MonitorData) -> Value:
    day = _day(data)
    return None if day is None else _round(day.heating.starts_per_hour, 2)


def _median_burn(data: MonitorData) -> Value:
    day = _day(data)
    if day is None or day.heating.median_burn_s is None:
        return None
    return round(day.heating.median_burn_s / 60.0, 1)


def _burner_hours(data: MonitorData) -> Value:
    day = _day(data)
    return None if day is None else round(day.heating.burn_s / 3600.0, 2)


def _short_share(data: MonitorData) -> Value:
    day = _day(data)
    return None if day is None else _percent(day.heating.short_burn_share)


def _condensing(data: MonitorData) -> Value:
    day = _day(data)
    return None if day is None or day.condensing is None else _percent(day.condensing.value)


def _degree_days(data: MonitorData) -> Value:
    week = _week(data)
    if week is None or week.degree_days is None:
        return None
    return _round(week.degree_days.estimated_total(), 1)


def _gas_per_degree_day(data: MonitorData) -> Value:
    week = _week(data)
    return None if week is None else _round(week.gas_per_degree_day, 3)


def _verdict(data: MonitorData) -> Value:
    return None if data.analysis is None else data.analysis.verdict.verdict.value


def _verdict_attributes(data: MonitorData) -> dict[str, Any]:
    reasons = [] if data.analysis is None else data.analysis.verdict.reasons
    return {
        "reasons": [
            {"code": r.code.value, "kind": r.kind.value, "value": r.value, "limit": r.limit}
            for r in reasons
        ],
        "monitoring_since": data.monitoring_since,
    }


def _signal_problems(data: MonitorData) -> Value:
    return sum(
        1
        for health in data.health.values()
        if health.status not in (SignalStatus.OK, SignalStatus.NOT_MAPPED)
    )


def _signal_attributes(data: MonitorData) -> dict[str, Any]:
    return {
        "signals": {signal.value: health.status.value for signal, health in data.health.items()},
        "features": {feature.value: state.status.value for feature, state in data.features.items()},
    }


def _reference_value(field: str) -> Callable[[MonitorData], Value]:
    def value(data: MonitorData) -> Value:
        if data.reference.status is not SelectionStatus.OK:
            return None  # never frozen at the last value
        return _round(getattr(data.reference, field), 2)

    return value


def _reference_state(data: MonitorData) -> Value:
    reference = data.reference
    if reference.status is not SelectionStatus.OK:
        return reference.status.value
    if reference.zone_id is None:
        return "average"
    return (
        data.zones[reference.zone_id].name if reference.zone_id in data.zones else reference.zone_id
    )


def _reference_attributes(data: MonitorData) -> dict[str, Any]:
    reference = data.reference
    return {
        "status": reference.status.value,
        "zone": reference.zone_id,
        "zones": list(reference.zones),
        "temperature": reference.temperature,
        "setpoint": reference.target,
        "deficit": _round(reference.deficit, 2),
    }


def _report_value(data: MonitorData) -> Value:
    report = None if data.analysis is None else data.analysis.report
    return None if report is None else _percent(report.relative_change)


def _report_attributes(data: MonitorData) -> dict[str, Any]:
    analysis = data.analysis
    if analysis is None or analysis.report is None:
        return {}
    report = analysis.report
    return {
        "unit": None if analysis.report_unit is None else analysis.report_unit.value,
        "previous": round(report.previous_total, 2),
        "current": round(report.current_total, 2),
        "contributions": {c.cause.value: round(c.amount, 2) for c in report.contributions},
        "not_judged": [cause.value for cause in report.unexplained],
    }


def _loss_value(data: MonitorData) -> Value:
    effective = data.parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    return None if effective is None else round(effective.value, 3)


def _loss_attributes(data: MonitorData) -> dict[str, Any]:
    effective = data.parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    if effective is None:
        return {}
    return {"source": effective.source.value, "confidence": round(effective.confidence, 2)}


def _round(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


def _percent(value: float | None) -> float | None:
    return None if value is None else round(value * 100.0, 1)


BOILER_SENSORS: tuple[BoilerSensorDescription, ...] = (
    BoilerSensorDescription(
        key="starts_per_hour",
        native_unit_of_measurement="/h",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_starts,
    ),
    BoilerSensorDescription(
        key="median_burn",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.MINUTES,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_median_burn,
    ),
    BoilerSensorDescription(
        key="burner_hours",
        device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.HOURS,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_visible_default=False,
        value_fn=_burner_hours,
    ),
    BoilerSensorDescription(
        key="short_burn_share",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_visible_default=False,
        value_fn=_short_share,
    ),
    BoilerSensorDescription(
        key="condensing_share",
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_condensing,
        needs=Feature.CONDENSING,
    ),
    BoilerSensorDescription(
        key="degree_days",
        native_unit_of_measurement="K·d",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_visible_default=False,
        value_fn=_degree_days,
        needs=Feature.DEGREE_DAYS,
    ),
    BoilerSensorDescription(
        key="gas_per_degree_day",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_gas_per_degree_day,
        needs=Feature.GAS,
    ),
    BoilerSensorDescription(
        key="verdict",
        device_class=SensorDeviceClass.ENUM,
        options=[v.value for v in Verdict],
        value_fn=_verdict,
        attributes_fn=_verdict_attributes,
    ),
    BoilerSensorDescription(
        key="signal_problems",
        entity_category=EntityCategory.DIAGNOSTIC,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_signal_problems,
        attributes_fn=_signal_attributes,
    ),
    BoilerSensorDescription(
        key="reference_room",
        value_fn=_reference_state,
        attributes_fn=_reference_attributes,
    ),
    BoilerSensorDescription(
        key="reference_room_temperature",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_reference_value("temperature"),
    ),
    BoilerSensorDescription(
        key="reference_room_setpoint",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_reference_value("target"),
    ),
    BoilerSensorDescription(
        key="change_report",
        native_unit_of_measurement=PERCENTAGE,
        entity_registry_visible_default=False,
        value_fn=_report_value,
        attributes_fn=_report_attributes,
    ),
    BoilerSensorDescription(
        key="loss_coefficient",
        native_unit_of_measurement="kW/K",
        entity_registry_visible_default=False,
        value_fn=_loss_value,
        attributes_fn=_loss_attributes,
    ),
    BoilerSensorDescription(
        key="forecast_snapshots",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=lambda data: data.forecast_snapshots,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: SmartBoilerCoordinator = entry.runtime_data
    data = coordinator.data
    entities: list[SensorEntity] = [
        BoilerSensor(coordinator, description)
        for description in BOILER_SENSORS
        if description.needs is None
        or data.features[description.needs].status is not FeatureStatus.UNAVAILABLE
    ]
    entities += [
        CriticalZoneSensor(coordinator, circuit.circuit_id)
        for circuit in coordinator.config.installation.circuits
    ]
    entities += [
        EmitterFactorSensor(coordinator, zone.zone_id)
        for zone in coordinator.config.installation.zones
    ]
    if coordinator.control is not None:
        entities += [ControlStateSensor(coordinator), ControlSetpointSensor(coordinator)]
    async_add_entities(entities)


class BoilerSensor(SmartBoilerEntity, SensorEntity):
    entity_description: BoilerSensorDescription

    def __init__(
        self, coordinator: SmartBoilerCoordinator, description: BoilerSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description
        if description.key == "gas_per_degree_day":
            self._attr_native_unit_of_measurement = f"{_gas_unit(coordinator)}/K·d"

    @property
    def native_value(self) -> Value:
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes_fn = self.entity_description.attributes_fn
        return None if attributes_fn is None else attributes_fn(self.coordinator.data)


def _gas_unit(coordinator: SmartBoilerCoordinator) -> str:
    entity = coordinator.config.signals.get(Signal.GAS_METER)
    state = coordinator.hass.states.get(entity) if entity else None
    unit = state.attributes.get("unit_of_measurement") if state is not None else None
    return str(unit) if unit else "gas"


class CriticalZoneSensor(SmartBoilerEntity, SensorEntity):
    def __init__(self, coordinator: SmartBoilerCoordinator, circuit: str) -> None:
        super().__init__(coordinator, "critical_zone", circuit=circuit)

    @property
    def native_value(self) -> str:
        critical = self.coordinator.data.critical[self.circuit or ""]
        if critical.status is not SelectionStatus.OK or critical.zone_id is None:
            return critical.status.value
        view = self.coordinator.data.zones.get(critical.zone_id)
        return view.name if view is not None else critical.zone_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        critical = self.coordinator.data.critical[self.circuit or ""]
        return {
            "status": critical.status.value,
            "zone": critical.zone_id,
            "demand": _percent(critical.demand),
            "deficit": _round(critical.deficit, 2),
            "saturated": critical.saturated,
        }


class EmitterFactorSensor(SmartBoilerEntity, SensorEntity):
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SmartBoilerCoordinator, zone: str) -> None:
        super().__init__(coordinator, "emitter_power_factor", zone=zone)

    @property
    def native_value(self) -> float | None:
        """Unknown (not unavailable) without a value, so the reason stays visible."""
        view = self.coordinator.data.zones[self.zone or ""]
        return _percent(view.factor.value)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        factor = self.coordinator.data.zones[self.zone or ""].factor
        return {
            "status": factor.status.value,
            "reason": None if factor.reason is None else factor.reason.value,
            "computed_at": factor.at,
            "output_w": _round(factor.output_w, 0),
            "held": factor.status is FactorStatus.HELD,
        }


def _time(t: float | None) -> str | None:
    return None if t is None else dt_util.utc_from_timestamp(t).isoformat()


class ControlStateSensor(ControlEntity, SensorEntity):
    """What control does now and why: mode, reasons, blockers, anti-cycling hold, hand-back."""

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control_state")
        self._attr_options = [mode.value for mode in ControlMode]

    @property
    def native_value(self) -> str:
        return self.control.status.mode.value

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        return {
            "reasons": list(status.reasons),
            "blockers": list(status.blockers),
            "target": _round(status.target, 1),
            "heating_on": status.heating_on,
            "hold_until": _time(status.hold_until),
            "hand_back_at": _time(status.hand_back_at),
            "learning_paused": list(status.paused_zones),
        }


class ControlSetpointSensor(ControlEntity, SensorEntity):
    """The flow setpoint control last wrote, with what the boiler reports back."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control_setpoint")

    @property
    def native_value(self) -> float | None:
        return _round(self.control.status.setpoint, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        return {
            "confirmed": _round(status.confirmed, 1),
            "last_change": _time(status.last_change_at),
        }
