"""Sensors: boiler metrics, verdict, reference room, critical zones, emitter power factors, the
building model's heat loss and heating threshold, the lowest water temperature's suggestion, the
features and what each lacks (the missing-data rule), and the state and setpoint of control.

Coded attributes stay codes, for automations; each list of codes — control's reasons, blockers
and latch, the verdict's reasons — has a sibling ``<name>_text`` in Home Assistant's language
(P-39), kept out of the recorder. Timestamps are ISO 8601 (P-78)."""

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
from homeassistant.const import EntityCategory, UnitOfRatio, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from .control_config import WritePath
from .coordinator import MonitorData, SmartBoilerConfigEntry, SmartBoilerCoordinator
from .core.controller import ControlMode
from .core.emitters import FactorStatus
from .core.lowest_water import SuggestionState
from .core.monitor import MonitorSummary
from .core.parameters import ParameterKey, Source
from .core.signal_check import (
    ENTITY_FOR_TWO_SIGNALS,
    Feature,
    FeatureState,
    FeatureStatus,
    SignalStatus,
)
from .core.signals import Signal
from .core.verdict import Reason, Verdict
from .core.zones import SelectionStatus
from .entity import ControlEntity, SmartBoilerEntity, code_text, coded_text, feature_configured

type Value = float | str | None


@dataclass(frozen=True, kw_only=True)
class BoilerSensorDescription(SensorEntityDescription):
    """A monitor sensor; whether it exists follows its feature (``entity.FEATURE_ENTITIES``)."""

    value_fn: Callable[[MonitorData], Value]
    attributes_fn: Callable[[MonitorData], dict[str, Any]] | None = None


def _day(data: MonitorData) -> MonitorSummary | None:
    return data.analysis.day if data.analysis is not None else None


def _week(data: MonitorData) -> MonitorSummary | None:
    return data.analysis.week if data.analysis is not None else None


def _starts(data: MonitorData) -> Value:
    day = _day(data)
    return None if day is None else _round(day.heating.starts_per_hour, 2)


def _starts_attributes(data: MonitorData) -> dict[str, Any]:
    """Heating starts in the last 24 h, and apart from them those of burns that may have been
    hot water."""
    day = _day(data)
    if day is None:
        return {}
    return {"starts": day.heating.starts, "unknown_kind_starts": day.unknown.starts}


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
    """Gas per degree-day in the meter's unit; the unit is added by the sensor, which shows no
    value until the meter's unit is known (P-75)."""
    week = _week(data)
    return None if week is None else _round(week.gas_per_degree_day, 3)


def _gas_attributes(data: MonitorData) -> dict[str, Any]:
    """S-31: the gas the meter counted over the week while the burner was known off — another
    consumer's, left out of heating gas and shown here; absent without a meter reading."""
    week = _week(data)
    if week is None or week.other_gas is None:
        return {}
    return {"other_gas": _round(week.other_gas, 3)}


def _verdict(data: MonitorData) -> Value:
    return None if data.analysis is None else data.analysis.verdict.verdict.value


def _reason(reason: Reason) -> dict[str, Any]:
    """A verdict reason: its code, kind, value and limit; for a problem whether 0.2.2's control
    changes it (S-22) — false is "not changed yet"; where one says more, why it was not judged
    (S-17: the building model an estimate only)."""
    shown: dict[str, Any] = {
        "code": reason.code.value,
        "kind": reason.kind.value,
        "value": reason.value,
        "limit": reason.limit,
    }
    if reason.changed_by_control is not None:
        shown["changed_by_control"] = reason.changed_by_control
    if reason.detail is not None:
        shown["detail"] = reason.detail
    return shown


def _verdict_attributes(data: MonitorData) -> dict[str, Any]:
    verdict = None if data.analysis is None else data.analysis.verdict
    reasons = [] if verdict is None else verdict.reasons
    return {
        "reasons": [_reason(r) for r in reasons],
        "monitoring_since": _time(data.monitoring_since),
        # P-96: days left out because the plugin controlled the boiler in them.
        "days_left_out": None if verdict is None else verdict.days_left_out,
    }


def _signal_problems(data: MonitorData) -> Value:
    return sum(
        1
        for health in data.health.values()
        if health.status not in (SignalStatus.OK, SignalStatus.NOT_MAPPED)
    )


def _signal_attributes(data: MonitorData) -> dict[str, Any]:
    """Each signal's health; the features have their own sensor (Y4)."""
    return {
        "signals": {signal.value: health.status.value for signal, health in data.health.items()},
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


def _parameter_value(key: ParameterKey, digits: int) -> Callable[[MonitorData], Value]:
    """The building value in use: the user's entry, else the measured one with the confidence
    the plugin counts, else the class default — its source shown beside it."""

    def value(data: MonitorData) -> Value:
        effective = data.parameters.get(key).effective()
        return None if effective is None else round(effective.value, digits)

    return value


def _parameter_attributes(
    key: ParameterKey, digits: int
) -> Callable[[MonitorData], dict[str, Any]]:
    """Where the value comes from; and the value entered beside the one measured, with whether
    they disagree beyond the tolerance (P77, P-90). An entered value always wins (P-92): the
    measured one never replaces it, it shows a mismatch."""

    def attributes(data: MonitorData) -> dict[str, Any]:
        parameter = data.parameters.get(key)
        effective = parameter.effective()
        if effective is None:
            return {}
        entered = parameter.estimate(Source.ENTERED)
        measured = parameter.estimate(Source.MEASURED)
        return {
            "source": effective.source.value,
            "confidence": round(effective.confidence, 2),
            "entered": None if entered is None else round(entered.value, digits),
            "measured": None if measured is None else round(measured.value, digits),
            "measured_confidence": None if measured is None else round(measured.confidence, 2),
            "mismatch": parameter.mismatch() is not None,
        }

    return attributes


def _lowest_water(data: MonitorData) -> Value:
    """X6 (decision 2): the lowest water temperature suggested, °C — unknown without a
    suggestion; never applied."""
    suggestion = data.lowest_water
    if suggestion is None or suggestion.state is not SuggestionState.SUGGESTION:
        return None
    return suggestion.value


def _lowest_water_attributes(data: MonitorData) -> dict[str, Any]:
    """The evidence behind it: its state, the burns counted and the share of them short (%),
    the reference, where the setpoint came from, the window, what is missing, and the "about"
    estimate from the boiler's minimum power with the input it lacks."""
    suggestion = data.lowest_water
    if suggestion is None:
        return {}
    estimate = suggestion.estimate
    return {
        "state": suggestion.state.value,
        "counted_burns": suggestion.counted,
        "short_share": _percent(suggestion.short_share),
        "reference": _round(suggestion.reference, 1),
        "source": None if suggestion.source is None else suggestion.source.value,
        "window_days": suggestion.window_days,
        "missing": list(suggestion.missing),
        "estimate_from_power": None if estimate is None else estimate.value,
        "estimate_gap": None if estimate is None or estimate.gap is None else estimate.gap.value,
    }


def _forecast_snapshots(data: MonitorData) -> Value:
    """How many forecast snapshots are kept; unknown while the weather entity is missing,
    unavailable or unknown (Y4)."""
    state = data.features_now.get(Feature.FORECASTS)
    if state is not None and state.status is FeatureStatus.INACTIVE:
        return None
    return data.forecast_snapshots


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
        attributes_fn=_starts_attributes,
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
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_visible_default=False,
        value_fn=_short_share,
    ),
    BoilerSensorDescription(
        key="condensing_share",
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_condensing,
    ),
    BoilerSensorDescription(
        key="degree_days",
        native_unit_of_measurement="K·d",
        state_class=SensorStateClass.MEASUREMENT,
        entity_registry_visible_default=False,
        value_fn=_degree_days,
    ),
    BoilerSensorDescription(
        key="gas_per_degree_day",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=_gas_per_degree_day,
        attributes_fn=_gas_attributes,
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
        native_unit_of_measurement=UnitOfRatio.PERCENTAGE,
        entity_registry_visible_default=False,
        value_fn=_report_value,
        attributes_fn=_report_attributes,
    ),
    BoilerSensorDescription(
        key="loss_coefficient",
        native_unit_of_measurement="kW/K",
        entity_registry_visible_default=False,
        value_fn=_parameter_value(ParameterKey.LOSS_COEFFICIENT, 3),
        attributes_fn=_parameter_attributes(ParameterKey.LOSS_COEFFICIENT, 3),
    ),
    BoilerSensorDescription(
        # P-90: the heating threshold in use — also the degree-days' base — with its source,
        # and the measured one beside an entered one; its reset button forgets the measured.
        key="heating_threshold",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        entity_registry_visible_default=False,
        value_fn=_parameter_value(ParameterKey.HEATING_THRESHOLD, 1),
        attributes_fn=_parameter_attributes(ParameterKey.HEATING_THRESHOLD, 1),
    ),
    BoilerSensorDescription(
        key="lowest_water_suggestion",
        device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        value_fn=_lowest_water,
        attributes_fn=_lowest_water_attributes,
    ),
    BoilerSensorDescription(
        key="forecast_snapshots",
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
        value_fn=_forecast_snapshots,
    ),
)


PARALLEL_UPDATES = 0  # read from the coordinator: no update requests to limit


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SmartBoilerConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        BoilerSensor(coordinator, description)
        for description in BOILER_SENSORS
        if feature_configured(coordinator, description.key)  # the missing-data rule (Y4)
    ]
    entities.append(FeaturesSensor(coordinator))
    entities += [
        CriticalZoneSensor(coordinator, circuit.circuit_id)
        for circuit in coordinator.config.installation.circuits
    ]
    if feature_configured(coordinator, "emitter_power_factor"):
        entities += [
            EmitterFactorSensor(coordinator, zone.zone_id)
            for zone in coordinator.config.installation.zones
        ]
    if coordinator.control is not None:
        entities.append(ControlStateSensor(coordinator))
        if coordinator.control.options.write_path is not WritePath.RELAY:
            # A relay sets no water temperature (R15).
            entities.append(ControlSetpointSensor(coordinator))
    coordinator.expect_entities("sensor", entities)
    async_add_entities(entities)


class BoilerSensor(SmartBoilerEntity, SensorEntity):
    entity_description: BoilerSensorDescription
    # Values and explanations that change with every analysis or update: kept out of the
    # recorder, which keeps the state itself.
    _unrecorded_attributes = frozenset(
        {
            "reasons",
            "reasons_text",
            "signals",
            "temperature",
            "setpoint",
            "deficit",
            "previous",
            "current",
            "contributions",
            "not_judged",
            "confidence",
            # The lowest water temperature's evidence, recomputed with every analysis.
            "counted_burns",
            "short_share",
            "reference",
            "missing",
            "missing_text",
            "estimate_from_power",
            "estimate_gap",
            # The week's gas without the burner, recomputed with every analysis (S-31).
            "other_gas",
        }
    )

    def __init__(
        self, coordinator: SmartBoilerCoordinator, description: BoilerSensorDescription
    ) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_unit_of_measurement(self) -> str | None:
        if self.entity_description.key == "gas_per_degree_day":
            # The gas meter's unit as it is now; none while it is not known (P-75).
            unit = _gas_unit(self.coordinator)
            return None if unit is None else f"{unit}/K·d"
        return self.entity_description.native_unit_of_measurement

    @property
    def native_value(self) -> Value:
        key = self.entity_description.key
        if key == "gas_per_degree_day" and _gas_unit(self.coordinator) is None:
            return None  # P-75: no value without its unit — a number would mean anything
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attributes_fn = self.entity_description.attributes_fn
        if attributes_fn is None:
            return None
        attributes = attributes_fn(self.coordinator.data)
        if self.entity_description.key == "verdict":
            attributes["reasons_text"] = _reasons_text(self.coordinator, attributes["reasons"])
        if "missing" in attributes and self.entity_description.key == "lowest_water_suggestion":
            # PB-77: the missing inputs' texts, as the other coded lists have.
            attributes["missing_text"] = coded_text(
                self.coordinator,
                "sensor",
                "lowest_water_suggestion",
                "missing",
                attributes["missing"],
            )
        return attributes


def _gas_unit(coordinator: SmartBoilerCoordinator) -> str | None:
    """The gas meter's unit, as its entity reports it now; ``None`` without a meter, while it
    reports none, or while it is not there (P-75)."""
    entity = coordinator.config.signals.get(Signal.GAS_METER)
    state = coordinator.hass.states.get(entity) if entity else None
    unit = state.attributes.get("unit_of_measurement") if state is not None else None
    return str(unit) if unit else None


def _reasons_text(coordinator: SmartBoilerCoordinator, reasons: list[dict[str, Any]]) -> str:
    """P-39: the verdict's reasons as one text — each reason's own, with why it is not judged
    or why it is not changed where a detail says so, else whether control changes it (S-22)."""

    def text(attribute: str, code: str) -> str:
        return code_text(coordinator, "sensor", "verdict", attribute, code)

    shown: list[str] = []
    for reason in reasons:
        part = text("reasons", reason["code"])
        detail = reason.get("detail")
        changed = reason.get("changed_by_control")
        if detail is not None:
            part += f" ({text('detail', detail)})"
        elif changed is not None:
            part += f" ({text('changed_by_control', 'true' if changed else 'false')})"
        shown.append(part)
    return ", ".join(shown)


class CriticalZoneSensor(SmartBoilerEntity, SensorEntity):
    _unrecorded_attributes = frozenset({"demand", "deficit", "saturated"})

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
    _unrecorded_attributes = frozenset({"status", "reason", "computed_at", "output_w", "held"})
    # A power user's diagnostic (SCOPE.md §4): there, but hidden until enabled.
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    _attr_native_unit_of_measurement = UnitOfRatio.PERCENTAGE
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
            "computed_at": _time(factor.at),
            "output_w": _round(factor.output_w, 0),
            "held": factor.status is FactorStatus.HELD,
        }


def _time(t: float | None) -> str | None:
    return None if t is None else dt_util.utc_from_timestamp(t).isoformat()


_SIGNAL_CODES = frozenset(signal.value for signal in Signal)


class FeaturesSensor(SmartBoilerEntity, SensorEntity):
    """The missing-data rule (Y4): how many features are inactive now, and for each its status —
    available, degraded or inactive — with the inputs it lacks as codes and as text. A signal
    dropped because its entity feeds an earlier one is named so, with the signal that kept it;
    a mapped signal that is not known now is named as unavailable."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_state_class = SensorStateClass.MEASUREMENT
    _unrecorded_attributes = frozenset(f"{feature.value}_missing_text" for feature in Feature)

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "features")

    @property
    def native_value(self) -> int:
        states = self.coordinator.data.features_now.values()
        return sum(1 for state in states if state.status is FeatureStatus.INACTIVE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        data = self.coordinator.data
        attributes: dict[str, Any] = {}
        missing: set[str] = set()
        for feature, state in data.features_now.items():
            attributes[feature.value] = state.status.value
            attributes[f"{feature.value}_missing"] = list(state.missing)
            attributes[f"{feature.value}_missing_text"] = self._missing_text(state)
            missing.update(state.missing)
        attributes["missing"] = sorted(missing)
        return attributes

    def _text(self, code: str) -> str:
        return code_text(self.coordinator, "sensor", "features", "missing", code)

    def _missing_text(self, state: FeatureState) -> str:
        health = self.coordinator.data.health
        shared = iter(state.shared)
        texts: list[str] = []
        for code in state.missing:
            pair = next(shared, None) if code == ENTITY_FOR_TWO_SIGNALS else None
            if pair is not None:
                # "Return temperature: its entity already feeds Flow temperature".
                dropped, kept = pair
                phrase = self._text(code)
                texts.append(f"{self._text(dropped.value)}: {phrase} {self._text(kept.value)}")
                continue
            text = self._text(code)
            signal = Signal(code) if code in _SIGNAL_CODES else None
            if signal is not None and health[signal].status is not SignalStatus.NOT_MAPPED:
                # Mapped, but not known now: named as unavailable.
                text = f"{text} ({self._text('unavailable_now')})"
            texts.append(text)
        return ", ".join(texts)


class ControlStateSensor(ControlEntity, SensorEntity):
    """What control does now and why: mode, reasons, blockers, latch and hand-back; each coded
    list with its text (P-39); SmartPI zones whose learning the plugin could not switch back on
    for a day, no longer tried (Y4)."""

    _unrecorded_attributes = frozenset(
        {
            "reasons",
            "reasons_text",
            "blockers_text",
            "blockers_waiting_text",
            "latched_by_text",
            "target",
            "heating_on",
            "heating_confirmation",
            "unknown_zones",
            "room_sensor_lost_zones",
            "learning_paused",
            "hand_back_confirmation",
            "comfort_correction",
            "activation_at",
            "relay_state",
            "relay_check",
            "boiler_heats",
        }
    )

    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control_state")
        self._attr_options = [mode.value for mode in ControlMode]

    @property
    def native_value(self) -> str:
        return self.control.status.mode.value

    def _text(self, attribute: str, codes: tuple[str, ...]) -> str:
        return coded_text(self.coordinator, "sensor", "control_state", attribute, codes)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        return {
            "reasons": list(status.reasons),
            "reasons_text": self._text("reasons", status.reasons),
            "blockers": list(status.blockers),
            "blockers_text": self._text("blockers", status.blockers),
            # Blockers that do not count yet: VT's central boiler unknown in its grace (P-105).
            "blockers_waiting": list(status.blockers_waiting),
            "blockers_waiting_text": self._text("blockers", status.blockers_waiting),
            "target": _round(status.target, 1),
            "heating_on": status.heating_on,
            "heating_confirmation": status.heating_check,
            "hand_back_at": _time(status.hand_back_at),
            "hand_back_confirmation": status.hand_back_check,
            "latched_by": list(status.latched_by),
            "latched_by_text": self._text("latched_by", status.latched_by),
            "unknown_zones": list(status.unknown_zones),
            "room_sensor_lost_zones": list(status.room_sensor_lost_zones),
            "learning_paused": list(status.paused_zones),
            # Y4: SmartPI zones the plugin could not switch back on for a day: no longer tried.
            "learning_not_resumed": list(status.learning_not_resumed),
            "writes_stopped": status.writes_stopped,
            "monitor_failed_since": _time(status.monitor_failed_since),
            # The comfort correction the session learned, K (P-38); the button resets it.
            "comfort_correction": _round(status.correction, 2),
            # A start waiting VT's activation delay is due then (decision 5).
            "activation_at": _time(status.activation_at),
            **self._relay(status),
        }

    def _relay(self, status: Any) -> dict[str, Any]:
        """The relay path (R15): the relay as seen, where the command stands with it, and
        whether the boiler shows it heats; nothing elsewhere."""
        if self.control.options.write_path is not WritePath.RELAY:
            return {}
        return {
            "relay_state": status.relay_state,
            "relay_check": status.relay_check,
            "boiler_heats": status.boiler_heats,
        }


class ControlSetpointSensor(ControlEntity, SensorEntity):
    """The flow setpoint as the device confirms it — unknown otherwise, never the requested one —
    with the value written and what the device reports back."""

    _unrecorded_attributes = frozenset({"requested", "read_back", "confirmation", "last_change"})

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: SmartBoilerCoordinator) -> None:
        super().__init__(coordinator, "control_setpoint")

    @property
    def native_value(self) -> float | None:
        return _round(self.control.status.confirmed_setpoint, 1)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        status = self.control.status
        return {
            "requested": _round(status.requested, 1),
            "read_back": _round(status.read_back, 1),
            "confirmation": status.setpoint_check,
            "last_change": _time(status.last_change_at),
        }
