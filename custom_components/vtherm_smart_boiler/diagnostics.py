"""Diagnostics download, redacted: entity IDs are replaced by stable placeholders and the
gateway's identifiers hidden; what is not personal — service names, versions — stays readable.
An entry whose setup failed has no runtime data: its diagnostics give the options, its state and
the control state read from its store, redacted alike (review question 20)."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from . import feature_manager
from .coordinator import SmartBoilerCoordinator, async_read_control_state
from .core.parameters import ParameterKey, Source

_LOGGER = logging.getLogger(__name__)

ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
# Identifiers of the user's devices (an MQTT node name often holds a MAC address).
REDACTED_KEYS = frozenset({"gateway_id", "mqtt_node", "mqtt_top"})


class _Redactor:
    """Replaces every entity ID with ``entity_N``, the same N for the same ID, and hides device
    identifiers. An entity ID is what Home Assistant knows as one, or what an option names as
    one; a service name or a version only looks like one and stays."""

    def __init__(self, hass: HomeAssistant, entities: frozenset[str] = frozenset()) -> None:
        self._hass = hass
        self._registry = er.async_get(hass)
        self._entities = entities
        self._names: dict[str, str] = {}

    def _is_entity(self, value: str) -> bool:
        return bool(ENTITY_ID.match(value)) and (
            value in self._entities
            or self._hass.states.get(value) is not None
            or self._registry.async_get(value) is not None
        )

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str) and self._is_entity(value):
            return self._names.setdefault(value, f"entity_{len(self._names) + 1}")
        if isinstance(value, Mapping):
            return {
                self(key): "**redacted**" if key in REDACTED_KEYS and item else self(item)
                for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [self(item) for item in value]
        return value


def _control(coordinator: SmartBoilerCoordinator) -> dict[str, Any] | None:
    control = coordinator.control
    if control is None:
        return None
    status = control.status
    return {
        "enabled": control.enabled,
        "allowed_services": sorted(f"{d}.{s}" for d, s in control.allowed_services),
        "status": asdict(status)
        | {
            "alarms": sorted(a.value for a in status.alarms),
            "unknown_alarms": sorted(a.value for a in status.unknown_alarms),
        },
        # The value the session learned (P-38), in K; the status carries it too.
        "comfort_correction": status.correction,
        "stored": control.stored(),
    }


def _parameters(coordinator: SmartBoilerCoordinator) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in ParameterKey:
        parameter = coordinator.parameters.get(key)
        estimates = {
            source.value: {"value": e.value, "confidence": e.confidence}
            for source in Source
            if (e := parameter.estimate(source)) is not None
        }
        if estimates:
            effective = parameter.effective()
            result[key.value] = {
                "effective": None if effective is None else effective.value,
                "sources": estimates,
            }
    return result


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator = getattr(entry, "runtime_data", None)
    if not isinstance(coordinator, SmartBoilerCoordinator):
        return await _async_not_running(hass, entry)
    data = coordinator.data
    # Every entity the options name — and those the stored control state names, such as the
    # options the boiler was taken with — also one that is away now (P-30).
    unit = coordinator.control or coordinator.hand_back_unit
    stored = unit.stored() if unit is not None else coordinator.stored_control
    redact = _Redactor(hass, _named_entities(entry.options) | _named_entities(stored))
    analysis = data.analysis
    summary: dict[str, Any] | None = None
    if analysis is not None:
        week, day = analysis.week, analysis.day
        summary = {
            "at": analysis.at,
            "failing": coordinator.analysis_failing,  # its last run failed (PB-18)
            "verdict": analysis.verdict.verdict.value,
            "reasons": [asdict(reason) for reason in analysis.verdict.reasons],
            "days_left_out": analysis.verdict.days_left_out,
            "day": {
                "heating": asdict(day.heating),
                "dhw": asdict(day.dhw),
                "condensing": None if day.condensing is None else asdict(day.condensing),
            },
            "week": {
                "heating": asdict(week.heating),
                "degree_days": None if week.degree_days is None else asdict(week.degree_days),
                "gas_per_degree_day": week.gas_per_degree_day,
                "other_gas": week.other_gas,
                "load_below_min": None
                if week.load_below_min is None
                else asdict(week.load_below_min),
                "by_outdoor": {str(low): asdict(stats) for low, stats in week.by_outdoor.items()},
            },
            "trends": {kind.value: asdict(alarm) for kind, alarm in analysis.trends.items()},
            "fit": None if analysis.fit is None else asdict(analysis.fit),
        }
    document: dict[str, Any] = redact(
        {
            "options": dict(entry.options),
            "capabilities": asdict(data.capabilities),
            "vt_feature_manager": _feature_manager(hass),
            "central_mode": None if data.central_mode is None else data.central_mode.value,
            "monitoring_since": data.monitoring_since,
            # P-95: when the plugin was not running, unknown in what is read back.
            "downtimes": [[since, until] for since, until in coordinator.down],
            "history_samples": {
                signal.value: len(series) for signal, series in coordinator.history.signals.items()
            }
            | {"weather": len(coordinator.history.weather)},
            "signals": {s.value: asdict(h) for s, h in data.health.items()},
            # Y4: by what the configuration gives (the entities follow it), and by what is
            # known now (the "Features" sensor).
            "features": {f.value: asdict(state) for f, state in data.features.items()},
            "features_now": {f.value: asdict(state) for f, state in data.features_now.items()},
            "parameters": _parameters(coordinator),
            # P-90: where the user reset a measured building value, the moment it happened.
            "fit_since": {key.value: at for key, at in coordinator.fit_since.items()},
            "zones": {
                zone_id: {
                    "circuit": view.circuit_id,
                    "state": asdict(view.state),
                    "hot_water": asdict(view.hot_water),
                    "factor": asdict(view.factor),
                    "foreign_heat": None
                    if view.foreign_heat is None
                    else asdict(view.foreign_heat),
                }
                for zone_id, view in data.zones.items()
            },
            "reference_room": asdict(data.reference),
            "critical": {cid: asdict(c) for cid, c in data.critical.items()},
            "alarms": {kind.value: asdict(alarm) for kind, alarm in data.alarms.items()},
            "analysis": summary,
            "control": _control(coordinator),
            "forecasts": {
                "snapshots": data.forecast_snapshots,
                "unsupported": sorted(k.value for k in coordinator.forecasts.unsupported)
                if coordinator.forecasts is not None
                else [],
            },
        }
    )
    return document


async def _async_not_running(hass: HomeAssistant, entry: ConfigEntry) -> dict[str, Any]:
    """Question 20: an entry without runtime data — its setup failed, or it is not loaded —
    gives its options, its state and the control state its store holds, all redacted."""
    try:
        read = await async_read_control_state(hass, entry.entry_id, entry.options)
    except Exception:  # the diagnostics still answer, with what could be read
        _LOGGER.exception("Could not read the stored control state for the diagnostics")
        state: dict[str, Any] = {}
        readable = False
    else:
        state, readable = dict(read.state), read.readable
    redact = _Redactor(hass, _named_entities(entry.options) | _named_entities(state))
    document: dict[str, Any] = redact(
        {
            "options": dict(entry.options),
            "state": entry.state.value,
            "control_state": state,
            "control_readable": readable,
        }
    )
    return document


def _feature_manager(hass: HomeAssistant) -> dict[str, Any]:
    registration = feature_manager.registration(hass)
    if registration is None:
        return {"state": None}
    return {"state": registration.state.value, "registered_at": registration.registered_at}


def _named_entities(value: Any) -> frozenset[str]:
    """Every entity ID the options name — also one that is away now — in any mapping, its keys
    too (the stored control state keys the zones it paused by their IDs): the entry's options
    are a read-only mapping (P-30)."""
    if isinstance(value, str):
        return frozenset({value}) if ENTITY_ID.match(value) else frozenset()
    if isinstance(value, Mapping):
        value = [*value.keys(), *value.values()]
    if isinstance(value, list | tuple):
        return frozenset().union(*(_named_entities(item) for item in value))
    return frozenset()
