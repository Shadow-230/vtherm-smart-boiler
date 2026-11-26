"""Which zones count: plausible room readings and setpoints."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.limits import PLAUSIBLE_ROOM
from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.zones import (
    SETPOINT_HIGH,
    SETPOINT_LOW,
    has_valid_readings,
    plausible_room,
    room_trusted,
)

NOW = 1000.0
AGE = 600.0


def zone(temp: float | None, target: float | None) -> ZoneState:
    return ZoneState("a", temperature=temp, target=target, heating_enabled=True, reported_at=NOW)


# --- Mutation testing (2026-10-12): bounds of the plausible room reading and setpoint ---


@pytest.mark.parametrize("temperature", PLAUSIBLE_ROOM)
def test_a_room_reading_at_either_bound_is_plausible(temperature: float) -> None:
    """The plausible room range (S-06) includes both its bounds: a very cold room at the lower
    one is still a room."""
    assert plausible_room(temperature)


@pytest.mark.parametrize("target", [SETPOINT_LOW, SETPOINT_HIGH])
def test_a_setpoint_at_either_bound_is_valid(target: float) -> None:
    """The plausible setpoint range includes both its bounds."""
    assert has_valid_readings(zone(20.0, target), NOW, AGE)


@pytest.mark.parametrize(
    ("temp", "target"),
    [
        (None, 21.0),
        (PLAUSIBLE_ROOM[1] + 1.0, 21.0),
        (20.0, None),
        (20.0, SETPOINT_LOW - 1.0),
        (20.0, SETPOINT_HIGH + 1.0),
    ],
)
def test_a_missing_or_implausible_reading_is_not_valid(
    temp: float | None, target: float | None
) -> None:
    """Negative: a zone needs both a plausible room temperature and a plausible setpoint — one
    of them missing or out of range is enough to leave it out."""
    assert not has_valid_readings(zone(temp, target), NOW, AGE)


# --- I12.10 (decision 8): the rooms' trust -----------------------------------------------------

START = 500.0


def trusted(**kw: object) -> bool:
    values: dict = {"safety": False, "thermometer_lost": False, "measured_at": 600.0}
    values.update(kw)
    return room_trusted(started_at=START, **values)


def test_a_room_measured_after_the_start_with_its_thermometer_and_no_safety_is_trusted() -> None:
    assert trusted()


@pytest.mark.parametrize(
    "changes",
    [{"safety": True}, {"thermometer_lost": True}, {"safety": True, "thermometer_lost": True}],
    ids=["safety", "thermometer", "both"],
)
def test_vts_safety_mode_or_a_lost_thermometer_leaves_the_room_out(changes: dict) -> None:
    """Negative: VT's safety mode (its event), or the room's thermometer unavailable or unknown,
    leaves its temperature out of every judgement of the curve, however fresh."""
    assert not trusted(**changes)


@pytest.mark.parametrize(
    ("measured_at", "trust"),
    [(None, False), (START - 60.0, False), (START, False), (START + 0.001, True)],
    ids=["unknown", "before", "at_the_start", "after"],
)
def test_a_room_counts_only_once_measured_after_the_plugins_start(
    measured_at: float | None, trust: bool
) -> None:
    """After a restart the plugin cannot know what it missed: a room counts only once VT's
    last measurement of it is newer than the start — not at it, not before it, not unknown."""
    assert trusted(measured_at=measured_at) is trust
