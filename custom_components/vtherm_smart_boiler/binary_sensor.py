"""Binary sensors: connection, hot water available and foreign heat per zone, alarms, and the
alarms of control."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import ControlAlarm
from .coordinator import SmartBoilerCoordinator
from .core.alarms import AlarmKind
from .core.signal_check import Feature, FeatureStatus, OutdoorStatus, SignalStatus
from .core.signals import Signal
from .entity import ControlEntity, SmartBoilerEntity

# Early warnings are advanced: created but hidden until the user shows them.
EARLY_WARNINGS = frozenset(
    {AlarmKind.PRESSURE_FALLING, AlarmKind.FLUE_GAS_RISING, AlarmKind.HYSTERESIS_DRIFT}
)


def _alarm_kinds(coordinator: SmartBoilerCoordinator) -> list[AlarmKind]:
    signals = coordinator.config.signals
    kinds = [AlarmKind.FREQUENT_STARTS, AlarmKind.UNSTABLE_IGNITION]
    if Signal.PRESSURE in signals:
        kinds += [AlarmKind.PRESSURE_LOW, AlarmKind.PRESSURE_HIGH, AlarmKind.PRESSURE_FALLING]
    if Signal.FLUE_GAS in signals and coordinator.config.installation.boiler.condensing:
        kinds.append(AlarmKind.FLUE_GAS_HIGH)
    if Signal.FLUE_GAS in signals and Signal.RETURN in signals:
        kinds.append(AlarmKind.FLUE_GAS_RISING)
    kinds.append(AlarmKind.HYSTERESIS_DRIFT)
    if Signal.PUMP_RUNNING in signals or Signal.CH_ACTIVE in signals:
        kinds.append(AlarmKind.LOW_FLOW)
    if any(c.max_flow_alarm is not None for c in coordinator.config.installation.circuits):
        kinds.append(AlarmKind.CIRCUIT_TOO_HOT)  # only for a circuit with a maximum (decision 10)
    return kinds


PARALLEL_UPDATES = 0  # read from the coordinator: no update requests to limit


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator: SmartBoilerCoordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [ConnectionSensor(coordinator)]
    for zone_config, zone in zip(
        coordinator.config.zones, coordinator.config.installation.zones, strict=True
    ):
        entities.append(HotWaterSensor(coordinator, zone.zone_id))
        if zone_config.foreign_heat:
            entities.append(ForeignHeatSensor(coordinator, zone.zone_id))
    entities += [AlarmSensor(coordinator, kind) for kind in _alarm_kinds(coordinator)]
    if coordinator.data.features[Feature.OUTDOOR_CHECK].status is FeatureStatus.AVAILABLE:
        entities.append(OutdoorSensorProblem(coordinator))
    if coordinator.control is not None:
        entities += [ControlAlarmSensor(coordinator, kind) for kind in ControlAlarm]
    coordinator.expect_entities(entities)
    async_add_entities(entities)


class ConnectionSensor(SmartBoilerEntity, BinarySensorEntity):
    """On while every required boiler signal is known and fresh."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def is_on(self) -> bool:
        return self.coordinator.data.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        health = self.coordinator.data.health
        return {
            "problems": [
                signal.value
                for signal, h in health.items()
                if h.required and h.status is not SignalStatus.OK
            ]
        }


class HotWaterSensor(SmartBoilerEntity, BinarySensorEntity):
    _unrecorded_attributes = frozenset({"excess"})

    """Heat is reaching the zone's emitters; unknown when it cannot be told."""

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator: SmartBoilerCoordinator, zone: str) -> None:
        super().__init__(coordinator, "hot_water", zone=zone)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.zones[self.zone or ""].hot_water.available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hot = self.coordinator.data.zones[self.zone or ""].hot_water
        return {
            "reason": None if hot.reason is None else hot.reason.value,
            "excess": None if hot.excess is None else round(hot.excess, 1),
        }


class ForeignHeatSensor(SmartBoilerEntity, BinarySensorEntity):
    _unrecorded_attributes = frozenset({"unknown", "holding"})

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator: SmartBoilerCoordinator, zone: str) -> None:
        super().__init__(coordinator, "foreign_heat", zone=zone)

    @property
    def is_on(self) -> bool | None:
        state = self.coordinator.data.zones[self.zone or ""].foreign_heat
        return None if state is None else state.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.coordinator.data.zones[self.zone or ""].foreign_heat
        if state is None:
            return {}
        return {
            "sources": list(state.sources),
            "unknown": list(state.unknown),
            "holding": state.holding,
        }


class AlarmSensor(SmartBoilerEntity, BinarySensorEntity):
    _unrecorded_attributes = frozenset({"value"})

    """An alarm or early warning: on while active. Information only in the monitor."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: SmartBoilerCoordinator, kind: AlarmKind) -> None:
        super().__init__(coordinator, f"alarm_{kind.value}")
        self.kind = kind
        if kind in EARLY_WARNINGS:
            self._attr_entity_registry_visible_default = False

    @property
    def is_on(self) -> bool | None:
        alarm = self.coordinator.data.alarms.get(self.kind)
        return None if alarm is None else alarm.active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = self.coordinator.data.alarms.get(self.kind)
        if alarm is None:
            return {}
        return {
            "level": None if alarm.level is None else alarm.level.value,
            "value": alarm.value,
            "limit": alarm.limit,
            "reason": alarm.reason,
        }


class OutdoorSensorProblem(SmartBoilerEntity, BinarySensorEntity):
    _unrecorded_attributes = frozenset({"mean_difference"})

    """On when the boiler's outdoor sensor disagrees with the weather entity or is stuck."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "outdoor_sensor_problem")

    @property
    def is_on(self) -> bool | None:
        analysis = self.coordinator.data.analysis
        if analysis is None or analysis.outdoor is None:
            return None
        status = analysis.outdoor.status
        if status is OutdoorStatus.UNKNOWN:
            return None
        return status is not OutdoorStatus.OK

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        analysis = self.coordinator.data.analysis
        if analysis is None or analysis.outdoor is None:
            return {}
        return {
            "status": analysis.outdoor.status.value,
            "mean_difference": analysis.outdoor.mean_difference,
        }


class ControlAlarmSensor(ControlEntity, BinarySensorEntity):
    """A control alarm: a write failed or was ignored from the start, commands keep getting lost,
    the boiler's confirmation is missing, another controller changed a value, a hand-back failed,
    the boiler link was lost, control stopped on an internal error, a room is near freezing
    while a hand-back that stops heating holds, no zone answers, or a demand criterion no zone
    can feed. "Write ignored" and "confirmation missing" name their targets, the criterion
    alarm its criteria."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(self, coordinator: SmartBoilerCoordinator, kind: ControlAlarm) -> None:
        super().__init__(coordinator, f"alarm_{kind.value}")
        self.kind = kind

    @property
    def is_on(self) -> bool:
        return self.kind in self.control.status.alarms

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        status = self.control.status
        if self.kind is ControlAlarm.WRITE_IGNORED:
            return {"targets": list(status.ignored_targets)}
        if self.kind is ControlAlarm.CONFIRMATION_MISSING:
            return {"targets": list(status.unconfirmed_targets)}
        if self.kind is ControlAlarm.DEMAND_CRITERION_NO_DATA:
            return {"criteria": list(status.criteria_without_data)}
        return None
