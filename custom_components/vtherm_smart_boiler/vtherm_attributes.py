"""What a VT climate entity's state and attributes mean for the plugin.

Verified in VT 10.4.0 (base_thermostat.py, thermostat_switch.py, thermostat_valve.py,
thermostat_climate*.py): the state is the HVAC mode ("sleep" is reported as "off");
``current_temperature`` and ``temperature`` are in Home Assistant's temperature unit;
``hvac_action`` is "heating" while the zone's device is active; ``on_percent`` is a fraction
0–1 (over_switch, over_valve, over_climate_valve); ``valve_open_percent`` is the commanded
opening 0–100 (valve types). These top-level keys are also kept by the recorder. Nested
dictionaries such as ``power_manager`` are live only.

No Home Assistant imports: the history importer uses this module too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from .units import parse_number, power_to_kw, temperature_to_celsius

HEATING_MODES = frozenset({"heat"})
AUTO_MODES = frozenset({"auto", "heat_cool"})  # may heat: the action says whether it does
NOT_HEATING_MODES = frozenset({"off", "cool", "dry", "fan_only"})
ACTIVE_ACTIONS = frozenset({"heating", "preheating"})
INACTIVE_ACTIONS = frozenset({"idle", "off", "cooling", "drying", "fan"})


@dataclass(frozen=True, slots=True)
class ZoneValues:
    temperature: float | None = None  # °C
    target: float | None = None  # °C
    heating_enabled: bool | None = None
    calling: bool | None = None
    on_percent: float | None = None  # 0 to 1
    valve_open: float | None = None  # 0 to 1
    power: float | None = None  # kW, live only
    auto_mode: bool = False
    device_active: bool | None = None  # live only
    ready: bool | None = None
    temperature_at: float | None = None  # epoch seconds, live only


def zone_values(
    state: str, attributes: Mapping[str, Any], temperature_unit: str | None = "°C"
) -> ZoneValues:
    """Zone values from a VT climate entity; anything missing or implausible is ``None``."""
    specific = attributes.get("specific_states")
    specific = specific if isinstance(specific, Mapping) else {}
    active = specific.get("is_device_active")
    ready = attributes.get("is_ready")
    return ZoneValues(
        temperature=_temperature(attributes.get("current_temperature"), temperature_unit),
        target=_temperature(attributes.get("temperature"), temperature_unit),
        heating_enabled=_heating_enabled(state),
        calling=_calling(attributes.get("hvac_action")),
        on_percent=_fraction(attributes.get("on_percent"), 1.0),
        valve_open=_fraction(attributes.get("valve_open_percent"), 100.0),
        power=_device_power(attributes.get("power_manager")),
        auto_mode=state in AUTO_MODES,
        device_active=active if isinstance(active, bool) else None,
        ready=ready if isinstance(ready, bool) else None,
        temperature_at=_moment(specific.get("last_temperature_datetime")),
    )


def _temperature(raw: object, unit: str | None) -> float | None:
    number = parse_number(raw)
    return None if number is None else temperature_to_celsius(number, unit)


def _heating_enabled(state: str) -> bool | None:
    if state in HEATING_MODES or state in AUTO_MODES:
        return True
    if state in NOT_HEATING_MODES:
        return False
    return None


def _calling(action: object) -> bool | None:
    if action in ACTIVE_ACTIONS:
        return True
    if action in INACTIVE_ACTIONS:
        return False
    return None


def _moment(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        moment = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return moment.timestamp() if moment.tzinfo is not None else None


def _fraction(raw: object, full_scale: float) -> float | None:
    number = parse_number(raw)
    if number is None or not 0.0 <= number <= full_scale:
        return None
    return number / full_scale


def _device_power(manager: object) -> float | None:
    if not isinstance(manager, Mapping):
        return None
    number = parse_number(manager.get("device_power"))
    if number is None or number < 0:
        return None
    unit = manager.get("power_unit")
    return power_to_kw(number, unit if isinstance(unit, str) else None)


class CentralMode(StrEnum):
    """VT's central mode (select option strings, VT 10.4.0 const.py)."""

    AUTO = "Auto"
    STOPPED = "Stopped"
    HEAT_ONLY = "Heat only"
    COOL_ONLY = "Cool only"
    FROST_PROTECTION = "Frost protection"


def central_mode(state: object) -> CentralMode | None:
    try:
        return CentralMode(state)
    except ValueError:
        return None
