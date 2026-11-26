"""What VT's thermostats tell the plugin through ``vtherm_api`` (I12.7), and the zone history's
reading of VT's climate states and attributes (I12.7b; names verified in VT 10.4.0)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.vtherm_attributes import (
    RUNTIME_MEMBERS,
    CentralMode,
    ZoneValues,
    central_mode,
    live_zone,
    shows_running,
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


@pytest.mark.parametrize(("device_power", "kw"), [(1.5, 1.5), (100.0, 100.0), (1500.0, 1.5)])
def test_a_power_without_its_unit_is_read_as_vt_did(device_power: float, kw: float) -> None:
    """P67: VT before its power unit option took a device power above 100 as W, else kW — the
    rule its own migration keeps; reading such a power as W made it 1000 times too small."""
    values = zone_values("heat", {"power_manager": {"device_power": device_power}})
    assert values.power == pytest.approx(kw)


def test_central_mode() -> None:
    assert central_mode("Stopped") is CentralMode.STOPPED
    assert central_mode("Frost protection") is CentralMode.FROST_PROTECTION
    assert central_mode("unavailable") is None


@pytest.mark.parametrize("device_power", [0, 0.0, -1.0, "0"])
def test_a_device_power_of_zero_is_no_data(device_power: object) -> None:
    """P-14: VT 10.4.0 publishes ``device_power`` 0 when no power is configured (observed)."""
    values = zone_values(
        "heat", {"power_manager": {"device_power": device_power, "power_unit": "kW"}}
    )
    assert values.power is None


@pytest.mark.parametrize(
    ("state", "attributes", "running"),
    [
        ("heat", {"is_ready": True, "specific_states": {}}, True),
        ("off", {"is_ready": True}, True),
        ("off", {"is_ready": False, "specific_states": {}}, False),  # VT has not started it
        ("off", {}, False),  # VT's placeholder before its first refresh
        ("sleep", {"is_ready": True}, True),  # VT's own mode, read as off
        ("unavailable", {"is_ready": True}, False),
        ("heat", {"is_ready": "yes"}, False),  # not VT's shape
    ],
)
def test_vts_climate_shows_the_thermostat_running(
    state: str, attributes: dict[str, object], running: bool
) -> None:
    """I12.11: the reload repair still reads whether VT's climate shows the thermostat started
    — ``is_ready`` true — in a mode the plugin reads."""
    assert shows_running(state, attributes) is running


@pytest.mark.parametrize("action", [["heating"], {"a": 1}])
def test_a_malformed_hvac_action_or_unit_is_unknown(action: object) -> None:
    """PB-41: an action or a temperature unit that is not text reads as unknown, never raises."""
    values = zone_values(
        "heat", {"current_temperature": 19.0, "hvac_action": action}, temperature_unit=["°C"]
    )
    assert values.calling is None
    assert values.temperature is None


def test_the_thermostats_members_give_the_zones_values() -> None:
    """I12.7: a zone is read from VT's thermostat alone — what ``vtherm_api`` declares:
    temperatures to a tenth, as Home Assistant shows them; the mode, the action, the device;
    the measurement's moment. A member missing gives nothing: no attribute stands in."""
    measured = datetime(2026, 11, 24, 10, 0, tzinfo=UTC)
    found = live_zone(
        {
            "current_temperature": 19.46,
            "target_temperature": 21.0,
            "vtherm_hvac_mode": "heat",
            "hvac_action": "heating",
            "is_device_active": True,
            "last_temperature_measure": measured,
            "hvac_off_reason": None,
        }
    )
    assert found == {
        "temperature": 19.5,
        "target": 21.0,
        "heating_enabled": True,
        "auto_mode": False,
        "calling": True,
        "device_active": True,
        "temperature_at": measured.timestamp(),
    }
    assert set(found) <= set(ZoneState.__dataclass_fields__)
    assert live_zone({"vtherm_hvac_mode": "auto"})["auto_mode"] is True
    assert live_zone({"current_temperature": 68.0}, "°F") == {"temperature": 20.0}
    assert live_zone({}) == {}


@pytest.mark.parametrize(
    "raw",
    [
        {"current_temperature": True, "target_temperature": "21"},  # not numbers
        {"current_temperature": float("nan")},
        {"vtherm_hvac_mode": "unknown"},  # VT's mode before its start
        {"vtherm_hvac_mode": None, "hvac_action": None},
        {"hvac_action": "something"},
        {"is_device_active": 1},  # not a boolean
        {"last_temperature_measure": datetime(2026, 11, 24, 10, 0)},  # no time zone
        {"last_temperature_measure": "2026-11-24T10:00:00+00:00"},  # a text, not a moment
    ],
)
def test_a_member_of_another_kind_gives_nothing(raw: dict) -> None:
    """Negative: a member of another type, or a mode or an action not known, gives nothing —
    the field stays not known."""
    assert live_zone(raw) == {}


@pytest.mark.parametrize(
    ("mode", "heating", "auto"),
    [
        ("heat", True, False),
        ("auto", True, True),
        ("heat_cool", True, True),
        ("cool", False, False),
        ("dry", False, False),
        ("fan_only", False, False),
        ("off", False, False),
        ("sleep", False, False),  # VT shows its "sleep" as "off" (``vtherm_hvac_mode.py``)
    ],
)
def test_every_vt_mode_reads_as_its_state(mode: str, heating: bool, auto: bool) -> None:
    """VT's modes (``vtherm_hvac_mode.py``, 10.6.5) through the API mean what the climate's state
    VT publishes from them means — for every thermostat type."""
    assert live_zone({"vtherm_hvac_mode": mode}) == {"heating_enabled": heating, "auto_mode": auto}
    state = zone_values("off" if mode == "sleep" else mode, {})
    assert state.heating_enabled is heating


@pytest.mark.parametrize("mode", ["unknown", "unavailable"])
def test_a_vt_mode_the_plugin_does_not_know_gives_nothing(mode: str) -> None:
    """VT's modes before a start read as nothing: the zone's mode is not known."""
    assert live_zone({"vtherm_hvac_mode": mode}) == {}
    assert zone_values(mode, {}).heating_enabled is None


def test_the_duty_cycle_is_not_read_from_the_thermostat() -> None:
    """VT 10.6.5's ``on_percent`` getter tells the algorithm the realized power whenever safety
    or the cap clamps it (``thermostat_prop.py``): a read that acts on the regulation — VT's
    power hook tells the duty instead."""
    assert "on_percent" not in RUNTIME_MEMBERS
    assert live_zone({"on_percent": 0.4}) == {}
