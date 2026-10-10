"""What a VT climate entity's state and attributes mean for the plugin.

Verified in VT 10.4.0 (base_thermostat.py, thermostat_switch.py, thermostat_valve.py,
thermostat_climate*.py): the state is the HVAC mode ("sleep" is reported as "off");
``current_temperature`` and ``temperature`` are in Home Assistant's temperature unit;
``hvac_action`` is "heating" while the zone's device is active; ``on_percent`` is a fraction
0–1 (over_switch, over_valve, over_climate_valve); ``valve_open_percent`` is the commanded
opening 0–100 (valve types). These top-level keys are also kept by the recorder. Nested
dictionaries such as ``power_manager`` are live only: in VT 10.4.0 it is published whether or
not power management is configured, with ``device_power`` 0 when no power is set,
``mean_cycle_power`` (the device power times the cycle's duty) in ``power_unit``, and
``overpowering_state`` only while shedding is configured; ``safety_manager`` with its
``safety_state`` only where the safety feature is configured.

Before VT's first refresh of a thermostat (at a start, or during its reload) the climate shows a
placeholder "off" with neither ``is_ready`` nor ``specific_states``; then, once one of its
devices has reported and before its start, ``is_ready`` false — observed with VT 10.4.0
(``tests/integration/test_vendor.py``). While none of its devices ever reports (their
integration not set up), VT 10.4.0 keeps the placeholder for good (check C, 2026-10-06).

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
    ready: bool | None = None  # VT's ``is_ready``; ``None``: not published
    temperature_at: float | None = None  # epoch seconds, live only
    max_on_percent: float | None = None  # 0 to 1, live only
    mean_power: float | None = None  # kW, VT's mean power over the cycle, live only
    safety_on: bool = False  # VT's safety mode, live only
    shedding: bool = False  # VT's power shedding holds the zone off, live only
    reported: bool = False  # VT shows it started, with its mode known
    window_open: bool | None = None  # VT holds it for a window (G11 F); None: not known


def zone_values(
    state: str, attributes: Mapping[str, Any], temperature_unit: object = "°C"
) -> ZoneValues:
    """Zone values from a VT climate entity; anything missing or implausible is ``None``."""
    specific = attributes.get("specific_states")
    specific = specific if isinstance(specific, Mapping) else {}
    configuration = attributes.get("configuration")
    configuration = configuration if isinstance(configuration, Mapping) else {}
    active = specific.get("is_device_active")
    ready = attributes.get("is_ready")
    manager = attributes.get("power_manager")
    manager = manager if isinstance(manager, Mapping) else {}
    safety = attributes.get("safety_manager")
    safety = safety if isinstance(safety, Mapping) else {}
    heating_enabled = _heating_enabled(state)
    # VT shows it started: ``is_ready`` true, or — an older VT without the key (assumed) — its
    # state with ``specific_states``. Neither: VT's placeholder before its first refresh.
    started = ready is True or (
        isinstance(attributes.get("specific_states"), Mapping) and "is_ready" not in attributes
    )
    return ZoneValues(
        temperature=_temperature(attributes.get("current_temperature"), temperature_unit),
        target=_temperature(attributes.get("temperature"), temperature_unit),
        heating_enabled=heating_enabled,
        calling=_calling(attributes.get("hvac_action")),
        on_percent=_fraction(attributes.get("on_percent"), 1.0),
        valve_open=_fraction(attributes.get("valve_open_percent"), 100.0),
        power=_device_power(manager),
        auto_mode=state in AUTO_MODES,
        device_active=active if isinstance(active, bool) else None,
        # Published but not VT's true (false, ``None``, a string, a number): not started — the
        # cautious reading (SB-02). Not published: ``None``.
        ready=ready is True if "is_ready" in attributes else None,
        temperature_at=_moment(specific.get("last_temperature_datetime")),
        max_on_percent=_cap(configuration.get("max_on_percent")),
        mean_power=_power(manager, "mean_cycle_power", positive=False),
        safety_on=safety.get("safety_state") == "on",
        shedding=manager.get("overpowering_state") == "on",
        reported=started and heating_enabled is not None,
        window_open=_window_open(attributes),
    )


# VT 10.4.0 (``feature_window_manager.py``): its window detection — a sensor, or automatic by the
# temperature's slope — shows under ``window_manager``, each state "on" or "off" (unavailable
# where not configured); its action turning the zone off gives that reason too (G11 F).
WINDOW_STATES = ("window_state", "window_auto_state")
WINDOW_OFF_REASON = "hvac_off_window_detection"


def _window_open(attributes: Mapping[str, Any]) -> bool | None:
    """Whether VT holds the zone for a window: ``True`` where either detection reads "on" or
    VT turned it off for one; ``False`` where a detection reads "off" and none "on"; ``None``
    where VT shows neither — not configured, an older VT, a state not known."""
    if attributes.get("hvac_off_reason") == WINDOW_OFF_REASON:
        return True
    manager = attributes.get("window_manager")
    if not isinstance(manager, Mapping):
        return None
    states = [manager.get(key) for key in WINDOW_STATES]
    if "on" in states:
        return True
    return False if "off" in states else None


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


def _cap(raw: object) -> float | None:
    """VT's cap on the duty cycle: a fraction, or a percentage in older setups."""
    number = parse_number(raw)
    if number is None or number <= 0.0:
        return None
    if number <= 1.0:
        return number
    return number / 100.0 if number <= 100.0 else None


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


# VT before its power unit option read a device power above this as W, else as kW; its config
# migration keeps that rule (VT 10.4.0 const.py, THRESHOLD_POWER_WATT_KILO).
_VT_LEGACY_KILOWATT_MAX = 100.0


def _device_power(manager: Mapping[str, Any]) -> float | None:
    """The zone's device power in kW; 0 or less is no data — VT 10.4.0 publishes 0 when no power
    is configured (P-14)."""
    return _power(manager, "device_power", positive=True)


def _power(manager: Mapping[str, Any], key: str, *, positive: bool) -> float | None:
    """A power of VT's power manager in kW. VT 10.4.0 publishes its unit ("W" or "kW"); older
    versions publish none, and the power means what VT's legacy rule made of it. Negative, or
    with ``positive`` 0, is no data."""
    number = parse_number(manager.get(key))
    if number is None or number < 0 or (positive and number == 0):
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
