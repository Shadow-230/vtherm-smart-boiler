"""The code convention "zone data only through vtherm_link.py" (TB-16).

VT's attribute names, its entry keys and SmartPI's domain are written as string constants only in
``vtherm_link.py`` and ``vtherm_attributes.py``; any other module reads a zone through them.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMPONENT = Path(__file__).resolve().parents[1] / "custom_components/vtherm_smart_boiler"
ALLOWED = {"vtherm_link.py", "vtherm_attributes.py"}

# VT 10.4.0's climate attributes and central-configuration entry keys the plugin reads, and
# SmartPI's domain; generic Home Assistant words ("heat", "temperature", "on") are not VT's.
VT_NAMES = frozenset(
    {
        "auto_tpi_continuous_kext",
        "auto_tpi_state",
        "boiler_activation_threshold",
        "boiler_power_activation_threshold",
        "central_boiler_activation_delay_sec",
        "central_boiler_activation_service",
        "central_boiler_deactivation_service",
        "central_boiler_state",
        "configuration",
        "device_power",
        "hvac_off_reason",
        "is_central_boiler_configured",
        "is_device_active",
        "is_ready",
        "is_used_by_central_boiler",
        "keep_alive_boiler_delay_sec",
        "last_temperature_datetime",
        "max_on_percent",
        "mean_cycle_power",
        "on_percent",
        "overpowering_state",
        "power_manager",
        "power_unit",
        "proportional_function",
        "safety_manager",
        "safety_state",
        "smartpi_learning_enabled",
        "specific_states",
        "temperature_sensor_entity_id",
        "thermostat_central_config",
        "thermostat_type",
        "underlying_entity_ids",
        "use_central_boiler_feature",
        "valve_open_percent",
        "vtherm_smartpi",
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
