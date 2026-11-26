"""What VT's thermostats tell the plugin through ``vtherm_api`` (I12.7), and what the reload
repair still reads of VT's climate and its central mode (I12.11). Nothing of VT's climates goes
into the rooms' history (I12.7b)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.vtherm_smart_boiler import vtherm_attributes
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.vtherm_attributes import (
    RUNTIME_MEMBERS,
    CentralMode,
    central_mode,
    live_zone,
    shows_running,
)


def test_central_mode() -> None:
    assert central_mode("Stopped") is CentralMode.STOPPED
    assert central_mode("Frost protection") is CentralMode.FROST_PROTECTION
    assert central_mode("unavailable") is None


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
    found = live_zone({"current_temperature": 19.0, "hvac_action": action}, ["°C"])
    assert "calling" not in found
    assert found.get("temperature") is None


def test_nothing_reads_vts_climate_for_the_rooms_history() -> None:
    """I12.7b: the parser of VT's climate states and attributes for the history is gone — the
    rooms' history is the plugin's own reads through ``vtherm_api``."""
    assert not hasattr(vtherm_attributes, "zone_values")
    assert not hasattr(vtherm_attributes, "ZoneValues")


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


@pytest.mark.parametrize("mode", ["unknown", "unavailable"])
def test_a_vt_mode_the_plugin_does_not_know_gives_nothing(mode: str) -> None:
    """VT's modes before a start read as nothing: the zone's mode is not known."""
    assert live_zone({"vtherm_hvac_mode": mode}) == {}


def test_the_duty_cycle_is_not_read_from_the_thermostat() -> None:
    """VT 10.6.5's ``on_percent`` getter tells the algorithm the realized power whenever safety
    or the cap clamps it (``thermostat_prop.py``): a read that acts on the regulation — VT's
    power hook tells the duty instead."""
    assert "on_percent" not in RUNTIME_MEMBERS
    assert live_zone({"on_percent": 0.4}) == {}
