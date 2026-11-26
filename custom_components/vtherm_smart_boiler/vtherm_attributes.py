"""What VT's thermostats tell the plugin, and what their climate entities meant for its history.

Live reads (I12.7) go only through the thermostat VT hands to the plugin's feature manager: the
members ``vtherm_api`` declares (``RUNTIME_MEMBERS``), read by ``live_zone``. VT 10.6.5 fills each
from the same field as the climate attribute the plugin used to read (``base_thermostat.py``);
``vtherm_hvac_mode`` has the climate state's values and VT's own "sleep", which VT shows as "off"
(``vtherm_hvac_mode.py``).

I12.7b: the zone history is still recorded from VT's climate entities (state and top-level
attributes, which the recorder keeps) — ``zone_values``, used by the coordinator's history and the
history importer only, until the plugin's own store replaces it. Verified in VT 10.4.0
(base_thermostat.py, thermostat_switch.py, thermostat_valve.py, thermostat_climate*.py): the state
is the HVAC mode ("sleep" is reported as "off"); ``current_temperature`` and ``temperature`` are in
Home Assistant's temperature unit; ``hvac_action`` is "heating" while the zone's device is active;
``on_percent`` is a fraction 0–1 (over_switch, over_valve, over_climate_valve);
``valve_open_percent`` is the commanded opening 0–100 (valve types); ``power_manager`` (live only)
has ``device_power`` 0 when no power is set, in ``power_unit``.

I12.11: the reload repair still reads whether VT's climate shows the thermostat running
(``shows_running``), and VT's central mode select (``central_mode``), until the rooms come from VT.

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
# VT's "sleep" (over_climate with valve regulation) is its climate "off" (VT 10.6.5
# ``vtherm_hvac_mode.py``): read as off, as the climate's state was.
NOT_HEATING_MODES = frozenset({"off", "cool", "dry", "fan_only", "sleep"})
ACTIVE_ACTIONS = frozenset({"heating", "preheating"})
INACTIVE_ACTIONS = frozenset({"idle", "off", "cooling", "drying", "fan"})

# What the plugin reads of a VT thermostat (the user's rule, 2026-11-24/25): the members
# ``vtherm_api`` declares (``InterfaceThermostatRuntime``; ``last_temperature_measure`` in
# ``InterfaceTemperatureTimestampRuntime`` from 0.12.0) that the plugin uses. Not ``on_percent``:
# VT 10.6.5's getter tells the algorithm the realized power whenever safety or the cap clamps it
# (``thermostat_prop.py``), so reading it would act on the regulation — VT's power hook tells the
# duty instead (``vtherm_link``). ``hvac_off_reason`` serves the window rule only.
RUNTIME_MEMBERS = (
    "current_temperature",
    "target_temperature",
    "vtherm_hvac_mode",
    "hvac_action",
    "is_device_active",
    "last_temperature_measure",
    "hvac_off_reason",
)


def live_zone(raw: Mapping[str, object], temperature_unit: object = "°C") -> dict[str, Any]:
    """The zone values a VT thermostat gave through ``vtherm_api``, keyed by the ``ZoneState``
    field each fills. A member it did not give, or one of another type, gives nothing: that
    field stays not known. Temperatures are taken to a tenth, as Home Assistant shows them; a
    mode or an action not known gives nothing either."""
    found: dict[str, Any] = {}
    for field_name, member in (
        ("temperature", "current_temperature"),
        ("target", "target_temperature"),
    ):
        value = raw.get(member)
        number = parse_number(value) if isinstance(value, int | float) else None  # not a text
        if number is not None:
            found[field_name] = temperature_to_celsius(round(number, 1), temperature_unit)
    mode = raw.get("vtherm_hvac_mode")
    if mode is not None:
        text = str(mode)
        enabled = _heating_enabled(text)
        if enabled is not None:
            found["heating_enabled"] = enabled
            found["auto_mode"] = text in AUTO_MODES
    calling = _calling(raw.get("hvac_action"))
    if calling is not None:
        found["calling"] = calling
    active = raw.get("is_device_active")
    if isinstance(active, bool):
        found["device_active"] = active
    moment = raw.get("last_temperature_measure")
    if isinstance(moment, datetime) and moment.tzinfo is not None:
        found["temperature_at"] = moment.timestamp()
    return found


@dataclass(frozen=True, slots=True)
class ZoneValues:
    """A VT climate entity's state as the zone history records it (I12.7b)."""

    temperature: float | None = None  # °C
    target: float | None = None  # °C
    heating_enabled: bool | None = None
    calling: bool | None = None
    on_percent: float | None = None  # 0 to 1
    valve_open: float | None = None  # 0 to 1
    power: float | None = None  # kW, live only


def zone_values(
    state: str, attributes: Mapping[str, Any], temperature_unit: object = "°C"
) -> ZoneValues:
    """I12.7b: the zone history's values from a VT climate entity (current or recorded);
    anything missing or implausible is ``None``."""
    manager = attributes.get("power_manager")
    manager = manager if isinstance(manager, Mapping) else {}
    return ZoneValues(
        temperature=_temperature(attributes.get("current_temperature"), temperature_unit),
        target=_temperature(attributes.get("temperature"), temperature_unit),
        heating_enabled=_heating_enabled(state),
        calling=_calling(attributes.get("hvac_action")),
        on_percent=_fraction(attributes.get("on_percent"), 1.0),
        valve_open=_fraction(attributes.get("valve_open_percent"), 100.0),
        power=_device_power(manager),
    )


def shows_running(state: str, attributes: Mapping[str, Any]) -> bool:
    """I12.11: VT's climate shows the thermostat started — ``is_ready`` true — in a mode the
    plugin reads. For the reload repair only, until the rooms come from VT."""
    return attributes.get("is_ready") is True and _heating_enabled(state) is not None


def _temperature(raw: object, unit: object) -> float | None:
    number = parse_number(raw)
    return None if number is None else temperature_to_celsius(number, unit)


def _heating_enabled(state: str) -> bool | None:
    if state in HEATING_MODES or state in AUTO_MODES:
        return True
    if state in NOT_HEATING_MODES:
        return False
    return None


def _calling(action: object) -> bool | None:
    if not isinstance(action, str):
        return None  # e.g. a list: not hashable, unknown (PB-41)
    if action in ACTIVE_ACTIONS:
        return True
    if action in INACTIVE_ACTIONS:
        return False
    return None


def _fraction(raw: object, full_scale: float) -> float | None:
    number = parse_number(raw)
    if number is None or not 0.0 <= number <= full_scale:
        return None
    return number / full_scale


# VT before its power unit option read a device power above this as W, else as kW; its config
# migration keeps that rule (VT 10.4.0 const.py, THRESHOLD_POWER_WATT_KILO).
_VT_LEGACY_KILOWATT_MAX = 100.0


def _device_power(manager: Mapping[str, Any]) -> float | None:
    """The zone's device power in kW; 0 or less is no data — VT 10.4.0 publishes 0 when no power
    is configured (P-14). VT 10.4.0 publishes its unit ("W" or "kW"); older versions publish
    none, and the power means what VT's legacy rule made of it."""
    number = parse_number(manager.get("device_power"))
    if number is None or number <= 0:
        return None
    unit = manager.get("power_unit")
    if not isinstance(unit, str):
        unit = "W" if number > _VT_LEGACY_KILOWATT_MAX else "kW"
    return power_to_kw(number, unit)


class CentralMode(StrEnum):
    """VT's central mode (select option strings, VT 10.4.0 const.py)."""

    AUTO = "Auto"
    STOPPED = "Stopped"
    HEAT_ONLY = "Heat only"
    COOL_ONLY = "Cool only"
    FROST_PROTECTION = "Frost protection"


def central_mode(state: object) -> CentralMode | None:
    if not isinstance(state, str):
        return None
    try:
        return CentralMode(state)
    except ValueError:
        return None
