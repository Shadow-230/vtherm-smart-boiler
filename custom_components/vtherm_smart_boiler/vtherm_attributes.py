"""What VT's thermostats tell the plugin.

Live reads (I12.7) go only through the thermostat VT hands to the plugin's feature manager: the
members ``vtherm_api`` declares (``RUNTIME_MEMBERS``), read by ``live_zone``. VT 10.6.5 fills each
from the same field as the climate attribute the plugin used to read (``base_thermostat.py``);
``vtherm_hvac_mode`` has the climate state's values and VT's own "sleep", which VT shows as "off"
(``vtherm_hvac_mode.py``).

The rooms' history is what the plugin read this way, kept in its own store (I12.7b): nothing of
VT's climate entities goes into it, and nothing of them is read (I12.11).

No Home Assistant imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from .units import parse_number, temperature_to_celsius

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
