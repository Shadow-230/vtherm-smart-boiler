"""I9: the contract of the water data for zone algorithms (`documentation/en/water-interface.md`).

Consumers detect what exists and changes only add, so no version number marks the interface:
these tests pin every name, type and allowed value the specification states. A change to one
fails here — the reminder to update the specification and to tell the consumers (§2, §8)."""

from __future__ import annotations

import re
from pathlib import Path

from custom_components.vtherm_smart_boiler import control, feature_manager, vtherm_link
from custom_components.vtherm_smart_boiler.const import DOMAIN
from custom_components.vtherm_smart_boiler.core.boiler_call import CallReason
from custom_components.vtherm_smart_boiler.core.demand import CountBy
from custom_components.vtherm_smart_boiler.core.heat import HeatReason
from custom_components.vtherm_smart_boiler.core.supply import SupplyReason

SPEC = Path(__file__).resolve().parents[1] / "documentation" / "en" / "water-interface.md"
FIELDS = (
    "supply_temperature",
    "supply_reason",
    "supply_measured_at",
    "heat_available",
    "heat_reason",
    # 2026-10-14, SmartPI's request (§4.3): the boiler's call and the demand.
    "boiler_called",
    "call_reason",
    "demand_count",
    "count_threshold",
    "count_by",
    "demand_power_kw",
    "power_threshold_kw",
    "demand_opening",
    "opening_threshold",
)
CALL_REASONS = {
    "below_threshold",
    "no_demand",
    "activation_delay",
    "boiler_fault",
    "not_controlling",
    "waiting_data",
}
SUPPLY_REASONS = {
    "not_mapped",
    "circuit_not_measured",
    "several_circuits",
    "flow_unknown",
    "flow_stale",
}
HEAT_REASONS = {
    "dhw_active",
    "flame_off",
    "flame_unknown",
    "flow_near_return",
    "flow_near_room",
    "flow_unknown",
    "flow_stale",
    "circuit_not_measured",
    "not_mapped",
    "room_unknown",
}


def _section(title: str) -> str:
    """The specification's text from a heading to the next heading of any level."""
    text = SPEC.read_text(encoding="utf-8")
    start = text.index(title)
    following = re.search(r"^#{2,3} ", text[start + len(title) :], re.MULTILINE)
    end = len(text) if following is None else start + len(title) + following.start()
    return text[start:end]


def _first_column(section: str) -> set[str]:
    """The backticked names in the first column of a section's table."""
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| `"):
            continue
        names |= set(re.findall(r"`([a-z_]+)`", line.split(" | ")[0]))
    return names


def test_the_names_are_the_specified_ones() -> None:
    """§3, §4: the manager's name, the fields in their order, the API's key and function, the
    attribute, the consumer's key and the learning service."""
    assert feature_manager.MANAGER_NAME == DOMAIN == "vtherm_smart_boiler"
    assert feature_manager.WATER_FIELDS == FIELDS
    assert feature_manager.API_KEY == "vtherm_smart_boiler_api"
    assert callable(feature_manager.SmartBoilerApi.zone_water)
    assert feature_manager.ATTRIBUTE == "smart_boiler"
    assert feature_manager.ATTRIBUTE_STEP_K == 1.0
    assert vtherm_link.WATER_DATA_KEY == "water_factor"
    assert control.SMARTPI_SERVICE == "set_smartpi_learning"
    for field in FIELDS:
        assert isinstance(getattr(feature_manager.SmartBoilerFeatureManager, field), property)


def test_the_property_types_are_the_specified_ones() -> None:
    """§4: each property's declared type."""
    hints = {
        name: getattr(feature_manager.SmartBoilerFeatureManager, name).fget.__annotations__[
            "return"
        ]
        for name in FIELDS
    }
    assert hints == {
        "supply_temperature": "float | None",
        "supply_reason": "str | None",
        "supply_measured_at": "datetime | None",
        "heat_available": "bool | None",
        "heat_reason": "str | None",
        "boiler_called": "bool | None",
        "call_reason": "str | None",
        "demand_count": "int | None",
        "count_threshold": "int | None",
        "count_by": "str | None",
        "demand_power_kw": "float | None",
        "power_threshold_kw": "float | None",
        "demand_opening": "float | None",
        "opening_threshold": "float | None",
    }


def test_the_reasons_are_the_specified_values() -> None:
    """§4.1, §4.2: the reason values, in the code and in the specification's tables alike."""
    assert {r.value for r in SupplyReason} == SUPPLY_REASONS
    assert {r.value for r in HeatReason} == HEAT_REASONS
    assert _first_column(_section("### 4.1 `supply_reason`")) == SUPPLY_REASONS
    assert _first_column(_section("### 4.2 `heat_reason`")) == HEAT_REASONS
    assert {r.value for r in CallReason} == CALL_REASONS
    assert _first_column(_section("### 4.3 `call_reason`")) == CALL_REASONS
    assert {by.value for by in CountBy} == {"devices", "zones"}  # count_by's values (§4)


def test_the_specification_lists_the_fields_and_the_attribute() -> None:
    """§4's table names the fields; §3.3's the attribute's keys; §3.2 the API."""
    assert _first_column(_section("## 4. The fields")) == set(FIELDS)
    assert _first_column(_section("### 3.3 The attribute on VT's thermostat")) == {
        "heat_available",
        "supply_temperature",
    }
    api = _section("### 3.2 The public API")
    assert '`hass.data["vtherm_smart_boiler_api"]`' in api
    assert "`zone_water(entity_id: str) -> Mapping[str, Any] | None`" in api
    assert "`water_factor`" in _section("### 3.4 What Smart Boiler reads from a consumer")
