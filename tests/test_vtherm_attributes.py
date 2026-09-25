"""Reading VT climate states and attributes (names verified in VT 10.4.0)."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.vtherm_attributes import (
    CentralMode,
    ZoneValues,
    central_mode,
    zone_values,
)


def test_over_valve_zone() -> None:
    attributes = {
        "current_temperature": 20.4,
        "temperature": 21.0,
        "hvac_action": "heating",
        "on_percent": 0.35,
        "power_percent": 35,
        "valve_open_percent": 35,
        "power_manager": {"device_power": 1500, "power_unit": "W"},
    }
    assert zone_values("heat", attributes) == ZoneValues(
        20.4, 21.0, True, True, 0.35, pytest.approx(0.35), pytest.approx(1.5)
    )


def test_over_climate_zone_has_no_on_percent() -> None:
    values = zone_values(
        "heat", {"current_temperature": 19.0, "temperature": 20.0, "hvac_action": "idle"}
    )
    assert values.calling is False
    assert values.on_percent is None
    assert values.valve_open is None
    assert values.power is None


@pytest.mark.parametrize(
    ("state", "enabled"),
    [
        ("heat", True),
        ("auto", True),
        ("heat_cool", True),
        ("off", False),
        ("cool", False),
        ("unavailable", None),
        ("unknown", None),
    ],
)
def test_heating_enabled(state: str, enabled: bool | None) -> None:
    assert zone_values(state, {}).heating_enabled is enabled


def test_implausible_or_foreign_values_are_unknown() -> None:
    values = zone_values(
        "heat",
        {
            "current_temperature": "unavailable",
            "on_percent": 35,  # not a fraction
            "valve_open_percent": 140,
            "hvac_action": "bogus",
            "power_manager": {"device_power": -3},
        },
    )
    assert values == ZoneValues(heating_enabled=True)


def test_fahrenheit_system() -> None:
    values = zone_values("heat", {"current_temperature": 68.0, "temperature": 69.8}, "°F")
    assert values.temperature == pytest.approx(20.0)
    assert values.target == pytest.approx(21.0)


def test_kilowatt_power_unit() -> None:
    values = zone_values("heat", {"power_manager": {"device_power": 1.2, "power_unit": "kW"}})
    assert values.power == pytest.approx(1.2)


def test_central_mode() -> None:
    assert central_mode("Stopped") is CentralMode.STOPPED
    assert central_mode("Frost protection") is CentralMode.FROST_PROTECTION
    assert central_mode("unavailable") is None


@pytest.mark.parametrize("mode", ["auto", "heat_cool"])
def test_auto_zones_heat_by_their_action(mode: str) -> None:
    """An over_climate zone in "auto" or heat_cool may heat: its action says whether it does."""
    values = zone_values(mode, {"hvac_action": "heating"})
    assert values.heating_enabled is True
    assert values.auto_mode is True
    assert values.calling is True
    assert zone_values("heat", {}).auto_mode is False


def test_vt_readiness_device_activity_and_temperature_age() -> None:
    """VT 10.4.0: `is_ready`, and in `specific_states` whether a device is active (what VT's
    own central boiler counts) and when the room temperature was last measured."""
    values = zone_values(
        "heat",
        {
            "is_ready": False,
            "specific_states": {
                "is_device_active": True,
                "last_temperature_datetime": "2026-01-12T09:00:00+01:00",
            },
        },
    )
    assert values.ready is False
    assert values.device_active is True
    assert values.temperature_at == pytest.approx(1768204800.0)
    bare = zone_values("heat", {"specific_states": {"last_temperature_datetime": "bogus"}})
    assert (bare.ready, bare.device_active, bare.temperature_at) == (None, None, None)
