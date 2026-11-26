"""The code convention "zone data only through vtherm_link.py" (TB-16).

VT's attribute names and its entry keys are written as string constants only in
``vtherm_link.py`` and ``vtherm_attributes.py``; any other module reads a zone through them.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/vtherm_smart_boiler"
ALLOWED = {"vtherm_link.py", "vtherm_attributes.py"}

# VT 10.4.0's climate attributes and central-configuration entry keys the plugin reads (nothing of
# SmartPI's since I12.9), and VT's events (I12.10: safety mode and the automatic window detection;
# no safety attribute any more); generic Home Assistant words ("heat", "temperature", "on") are not
# VT's.
VT_NAMES = frozenset(
    {
        "central_boiler_activation_service",
        "central_boiler_deactivation_service",
        "configuration",
        "delayed_activation_sec",
        "cycle_min",
        "device_power",
        "hvac_off_reason",
        "is_device_active",
        "is_ready",
        "is_used_by_central_boiler",
        "last_temperature_datetime",
        "max_on_percent",
        "mean_cycle_power",
        "on_percent",
        "overpowering_state",
        "power_manager",
        "power_unit",
        "specific_states",
        "temperature_sensor_entity_id",
        "underlying_entity_ids",
        "use_central_boiler_feature",
        "valve_open_percent",
        "versatile_thermostat_central_boiler_event",
        "versatile_thermostat_safety_event",
        "versatile_thermostat_window_auto_event",
        "window_sensor_entity_id",
        "hvac_off_window_detection",
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
