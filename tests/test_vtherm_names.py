"""The code convention "zone data only through vtherm_link.py" (TB-16).

VT's attribute names and its entry keys are written as string constants only in
``vtherm_link.py`` and ``vtherm_attributes.py``; any other module reads a zone through them.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/vtherm_smart_boiler"
ALLOWED = {"vtherm_link.py", "vtherm_attributes.py"}

# VT's names the plugin reads (I12.7): the thermostat members ``vtherm_api`` declares and its
# power hook's kinds of device; the keys of a thermostat's ``entry_infos`` (VT 10.6.5
# ``const.py``); VT's events (I12.10: safety mode and the automatic window detection); and VT
# 10.4.0's climate attributes the zone history (I12.7b) and the reload repair (I12.11) still read.
# Generic Home Assistant words ("heat", "temperature", "on") are not VT's.
VT_NAMES = frozenset(
    {
        "central_boiler_activation_service",
        "central_boiler_deactivation_service",
        "cycle_min",
        "delayed_activation_sec",
        "device_power",
        "entry_infos",
        "hvac_off_reason",
        "hvac_off_window_detection",
        "is_device_active",
        "is_ready",
        "last_temperature_measure",
        "on_percent",
        "power_manager",
        "power_unit",
        "target_temperature",
        "temperature_sensor_entity_id",
        "thermostat_over_switch",
        "thermostat_type",
        "underlying_entity_ids",
        "use_central_boiler_feature",
        "used_by_controls_central_boiler",
        "valve_open_percent",
        "valve_regulation",
        "versatile_thermostat_central_boiler_event",
        "versatile_thermostat_safety_event",
        "versatile_thermostat_window_auto_event",
        "vtherm_hvac_mode",
        "window_sensor_entity_id",
    }
)


def _string_constants(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def test_vt_names_only_in_the_link_modules() -> None:
    """TB-16: no other module of the package names VT's attributes or entry keys."""
    allowed_names: set[str] = set()
    for name in ALLOWED:
        allowed_names |= _string_constants(COMPONENT / name)
    assert VT_NAMES <= allowed_names, "a name the walk guards is no longer used: update VT_NAMES"
    found = {
        (str(path.relative_to(COMPONENT)), name)
        for path in COMPONENT.rglob("*.py")
        if path.name not in ALLOWED or path.parent != COMPONENT
        for name in _string_constants(path) & VT_NAMES
    }
    assert sorted(found) == []
