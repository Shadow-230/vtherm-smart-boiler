"""Binary sensors: connection, hot water available and foreign heat per zone, alarms, and the
alarms of control. An alarm exists only where its feature is not inactive (the missing-data
rule, Y4)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .control import ControlAlarm, control_alarms_for
from .coordinator import SmartBoilerConfigEntry, SmartBoilerCoordinator
from .core.alarms import AlarmKind
from .core.signal_check import OutdoorStatus, link_problems
from .core.signals import Signal
from .entity import ControlEntity, SmartBoilerEntity, feature_configured

# Early warnings are advanced: created but hidden until the user shows them.
EARLY_WARNINGS = frozenset(
    {AlarmKind.PRESSURE_FALLING, AlarmKind.FLUE_GAS_RISING, AlarmKind.HYSTERESIS_DRIFT}
)


def _alarm_kinds(coordinator: SmartBoilerCoordinator) -> list[AlarmKind]:
    """The monitor's alarms whose feature the configuration does not leave inactive (Y4): the
    burns' need the flame (X8, R4), the "add water" one its threshold (Y1), the pressure trend
    the flame and flow too, the flue gas ones a condensing boiler, the hysteresis drift the
    flame, the flow and zones, the low-flow one its inputs (P-99), the circuit's only with a
    maximum (decision 10). The flue gas trend also needs the return, over which it is computed
    (P-85)."""
    trend = Signal.RETURN in coordinator.config.signals
    return [
        kind
        for kind in AlarmKind
        if feature_configured(coordinator, f"alarm_{kind.value}")
        and (trend or kind is not AlarmKind.FLUE_GAS_RISING)
    ]


PARALLEL_UPDATES = 0  # read from the coordinator: no update requests to limit


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartBoilerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[BinarySensorEntity] = [ConnectionSensor(coordinator)]
    hot_water = feature_configured(coordinator, "hot_water")
    for zone_config, zone in zip(
        coordinator.config.zones, coordinator.config.installation.zones, strict=True
    ):
        if hot_water:
            entities.append(HotWaterSensor(coordinator, zone.zone_id))
        if zone_config.foreign_heat:
            entities.append(ForeignHeatSensor(coordinator, zone.zone_id))
    entities += [AlarmSensor(coordinator, kind) for kind in _alarm_kinds(coordinator)]
    if feature_configured(coordinator, "outdoor_sensor_problem"):
        entities.append(OutdoorSensorProblem(coordinator))
    if coordinator.control is not None:
        # Each path's own alarms (R15): the relay's only on the relay path, the boiler link's
        # and the missing confirmation not there; each only where its feature is not inactive.
        kinds = control_alarms_for(coordinator.control.options)
        entities += [
            ControlAlarmSensor(coordinator, kind)
            for kind in kinds
            if feature_configured(coordinator, f"alarm_{kind.value}")
        ]
    coordinator.expect_entities("binary_sensor", entities)
    async_add_entities(entities)


class ConnectionSensor(SmartBoilerEntity, BinarySensorEntity):
    """On while every mapped link signal (flame, flow) is known and fresh and, on the relay
    path, the relay is within reach; unknown with no link signal mapped and no relay (X8)."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "connection")

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.connected

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        problems = [signal.value for signal in link_problems(self.coordinator.data.health)]
        control = self.coordinator.config.control
        relay = control.relay.entity if control.write_path == "relay" else None
        if relay is not None:
            state = self.coordinator.hass.states.get(relay)
            if state is None or state.state in ("unavailable", "unknown"):
                problems.append("relay")
        return {"problems": problems}


class HotWaterSensor(SmartBoilerEntity, BinarySensorEntity):
    """Heat is reaching the zone's emitters; unknown when it cannot be told, with its reason.
    How far the flow stands above the room is left to the diagnostics (P-72)."""

    _attr_device_class = BinarySensorDeviceClass.HEAT

    def __init__(self, coordinator: SmartBoilerCoordinator, zone: str) -> None:
        super().__init__(coordinator, "hot_water", zone=zone)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.zones[self.zone or ""].hot_water.available

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        hot = self.coordinator.data.zones[self.zone or ""].hot_water
        return {"reason": None if hot.reason is None else hot.reason.value}


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
    """An alarm or early warning: on while active, unknown while it cannot be judged once its
    hour's hold is over (S-16) — never "OK" for want of data. Information only: the monitor's
    alarms never change control. The value it judged, which changes with every reading, is left
    to the diagnostics (P-72)."""

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
            "limit": alarm.limit,
            "reason": alarm.reason,
        }


class OutdoorSensorProblem(SmartBoilerEntity, BinarySensorEntity):
    """On when the boiler's outdoor sensor disagrees with the weather entity or is stuck."""

    _unrecorded_attributes = frozenset({"mean_difference"})
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_registry_visible_default = False

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "outdoor_sensor_problem")

    @property
    def is_on(self) -> bool | None:
        check = self.coordinator.outdoor_check(self.coordinator.data.now)
        if check is None:
            return None
        status = check.status
        if status is OutdoorStatus.UNKNOWN:
            return None
        return status is not OutdoorStatus.OK

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        check = self.coordinator.outdoor_check(self.coordinator.data.now)
        if check is None:
            return {}
        return {"status": check.status.value, "mean_difference": check.mean_difference}


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
    def is_on(self) -> bool | None:
        status = self.control.status
        if self.kind in status.unknown_alarms:
            return None  # it cannot be judged, its hour's hold over (S-16)
        return self.kind in status.alarms

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        status = self.control.status
        if self.kind is ControlAlarm.WRITE_IGNORED:
            return {"targets": list(status.ignored_targets)}
        if self.kind is ControlAlarm.CONFIRMATION_MISSING:
            return {"targets": list(status.unconfirmed_targets)}
        if self.kind is ControlAlarm.DEMAND_CRITERION_NO_DATA:
            return {
                "criteria": list(status.criteria_without_data),
                "zones": list(status.zones_without_data),  # calling, seen by none (PB-23)
            }
        return None
