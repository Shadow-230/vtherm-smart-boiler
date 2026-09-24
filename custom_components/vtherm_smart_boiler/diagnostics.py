"""Diagnostics download, redacted: entity IDs are replaced by stable placeholders."""

from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .coordinator import SmartBoilerCoordinator
from .core.parameters import ParameterKey, Source

ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
# Identifiers of the user's devices (an MQTT node name often holds a MAC address).
REDACTED_KEYS = frozenset({"gateway_id", "mqtt_node", "mqtt_top"})


class _Redactor:
    """Replaces every entity ID with ``entity_N``, the same N for the same ID, and hides device
    identifiers."""

    def __init__(self) -> None:
        self._names: dict[str, str] = {}

    def __call__(self, value: Any) -> Any:
        if isinstance(value, str) and ENTITY_ID.match(value):
            return self._names.setdefault(value, f"entity_{len(self._names) + 1}")
        if isinstance(value, dict):
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
        "status": asdict(status) | {"alarms": sorted(a.value for a in status.alarms)},
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
    coordinator: SmartBoilerCoordinator = entry.runtime_data
    data = coordinator.data
    redact = _Redactor()
    analysis = data.analysis
    summary: dict[str, Any] | None = None
    if analysis is not None:
        week, day = analysis.week, analysis.day
        summary = {
            "at": analysis.at,
            "verdict": analysis.verdict.verdict.value,
            "reasons": [asdict(reason) for reason in analysis.verdict.reasons],
            "day": {
                "heating": asdict(day.heating),
                "dhw": asdict(day.dhw),
                "condensing": None if day.condensing is None else asdict(day.condensing),
            },
            "week": {
                "heating": asdict(week.heating),
                "degree_days": None if week.degree_days is None else asdict(week.degree_days),
                "gas_per_degree_day": week.gas_per_degree_day,
                "load_below_min": None
                if week.load_below_min is None
                else asdict(week.load_below_min),
                "by_outdoor": {str(low): asdict(stats) for low, stats in week.by_outdoor.items()},
            },
            "trends": {kind.value: asdict(alarm) for kind, alarm in analysis.trends.items()},
            "fit": None if analysis.fit is None else asdict(analysis.fit),
        }
    return redact(
        {
            "options": dict(entry.options),
            "capabilities": asdict(data.capabilities),
            "central_mode": None if data.central_mode is None else data.central_mode.value,
            "monitoring_since": data.monitoring_since,
            "history_samples": {
                signal.value: len(series) for signal, series in coordinator.history.signals.items()
            }
            | {"weather": len(coordinator.history.weather)},
            "signals": {s.value: asdict(h) for s, h in data.health.items()},
            "features": {f.value: asdict(state) for f, state in data.features.items()},
            "parameters": _parameters(coordinator),
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
