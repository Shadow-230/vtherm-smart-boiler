"""Reading VT climate states and attributes (names verified in VT 10.4.0)."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import ZoneState
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


@pytest.mark.parametrize(("raw", "cap"), [(0.8, 0.8), (80, 0.8), (1, 1.0), (None, None), (0, None)])
def test_vt_cap_on_the_duty_cycle(raw: object, cap: float | None) -> None:
    values = zone_values("heat", {"configuration": {"max_on_percent": raw}})
    assert values.max_on_percent == (None if cap is None else pytest.approx(cap))


# --- X3: power 0 is no data (P-14), VT's safety and shedding, the mean power, "reported" -------


@pytest.mark.parametrize("device_power", [0, 0.0, -1.0, "0"])
def test_a_device_power_of_zero_is_no_data(device_power: object) -> None:
    """P-14: VT 10.4.0 publishes ``device_power`` 0 when no power is configured (observed)."""
    values = zone_values(
        "heat", {"power_manager": {"device_power": device_power, "power_unit": "kW"}}
    )
    assert values.power is None


@pytest.mark.parametrize(
    ("manager", "safety"),
    [
        ({"safety_state": "on", "safety_delay_min": 5}, True),
        ({"safety_state": "off"}, False),
        ({"safety_state": "unknown"}, False),
        ({"safety_state": None}, False),
        ({}, False),
        (None, False),  # safety not configured: VT publishes no safety_manager
        ("on", False),  # not VT's shape
    ],
)
def test_vt_safety_state_on_is_read(manager: object, safety: bool) -> None:
    """S-35: VT 10.4.0 publishes ``safety_manager.safety_state`` where safety is configured."""
    attributes = {} if manager is None else {"safety_manager": manager}
    assert zone_values("heat", attributes).safety_on is safety


@pytest.mark.parametrize(
    ("state", "shedding"),
    [("on", True), ("off", False), ("unknown", False), (None, False), (True, False)],
)
def test_overpowering_state_on_is_read(state: object, shedding: bool) -> None:
    """T-45: VT's power shedding holds the zone off: ``power_manager.overpowering_state``."""
    manager = {"device_power": 1.0, "power_unit": "kW", "overpowering_state": state}
    assert zone_values("heat", {"power_manager": manager}).shedding is shedding
    assert zone_values("heat", {}).shedding is False  # missing: not shedding


@pytest.mark.parametrize(
    ("mean", "unit", "kw"),
    [
        (600.0, "W", 0.6),
        (0.6, "kW", 0.6),
        (0.0, "kW", 0.0),  # nothing over this cycle: known, none
        (None, "kW", None),  # VT 10.4.0 without a device power: None
        (-1.0, "W", None),
        ("bogus", "W", None),
        (1500.0, None, 1.5),  # no unit: read as VT's legacy rule reads a power
    ],
)
def test_mean_cycle_power_is_read_in_its_unit(
    mean: object, unit: str | None, kw: float | None
) -> None:
    manager: dict[str, object] = {"device_power": 2.0, "mean_cycle_power": mean}
    if unit is not None:
        manager["power_unit"] = unit
    values = zone_values("heat", {"power_manager": manager})
    assert values.mean_power == (None if kw is None else pytest.approx(kw))


@pytest.mark.parametrize(
    ("state", "attributes", "reported"),
    [
        ("heat", {"is_ready": True, "specific_states": {}}, True),
        ("off", {"is_ready": True}, True),
        ("off", {"is_ready": False, "specific_states": {}}, False),  # VT has not started it
        ("heat", {"is_ready": False, "specific_states": {}}, False),
        # VT 10.4.0 before its first refresh: its placeholder "off", nothing more (observed).
        ("off", {}, False),
        ("heat", {"current_temperature": 20.0}, False),
        # An older VT without ``is_ready`` (assumed): its state, with its mode known.
        ("heat", {"specific_states": {"is_device_active": False}}, True),
        ("sleep", {"specific_states": {}}, False),  # a mode not known
        ("unavailable", {"is_ready": True}, False),
        ("heat", {"is_ready": "yes", "specific_states": {}}, False),  # not VT's shape
    ],
)
def test_a_zone_without_vt_attributes_has_not_reported(
    state: str, attributes: dict[str, object], reported: bool
) -> None:
    assert zone_values(state, attributes).reported is reported


RECOGNISED = 1000.0  # a step after the recognition period


def _known_after_recognition(state: str, attributes: dict[str, object]) -> bool:
    values = zone_values(state, attributes)
    zone = ZoneState(
        "z",
        heating_enabled=values.heating_enabled,
        ready=values.ready,
        reported=values.reported,
        reported_at=RECOGNISED,
    )
    return zone.is_known(RECOGNISED, None)


@pytest.mark.parametrize("state", ["off", "cool", "heat"])
@pytest.mark.parametrize("ready", [False, None, "true", 1, 0])
def test_a_zone_vt_shows_not_ready_is_unknown_after_the_recognition(
    state: str, ready: object
) -> None:
    """SB-02 (decision 1 of 2026-10-05): VT shows a thermostat it cannot start (a device
    unavailable) "off" — "heat" for over_valve — with ``is_ready`` false for as long as it
    cannot: unknown after the recognition period too, not the user's "off". A published value
    that is not VT's true (``None``, a string, a number) is read the same way: the cautious
    reading."""
    values = zone_values(state, {"is_ready": ready, "specific_states": {}})
    assert values.ready is False
    assert not values.reported
    assert not _known_after_recognition(state, {"is_ready": ready, "specific_states": {}})


@pytest.mark.parametrize(
    ("state", "attributes", "ready"),
    [
        ("off", {"is_ready": True, "specific_states": {}}, True),  # started: the user's "off"
        ("cool", {"is_ready": True}, True),
        ("off", {}, None),  # VT 10.4.0's placeholder: as before, S-34
        ("off", {"specific_states": {}}, None),  # an older VT without ``is_ready`` (assumed)
    ],
)
def test_an_off_zone_started_or_without_is_ready_stays_known_without_demand(
    state: str, attributes: dict[str, object], ready: bool | None
) -> None:
    """S-34 kept: "off" on a zone VT has started, or that shows no ``is_ready`` at all, is
    known — without demand — once the recognition period is over."""
    assert zone_values(state, attributes).ready is ready
    assert _known_after_recognition(state, attributes)
