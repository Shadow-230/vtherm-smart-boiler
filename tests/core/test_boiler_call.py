"""Whether the boiler is called for heat, and why not (the user's decisions of 2026-10-14): what
VT's central boiler shows on its binary sensor, and what SmartPI asks to tell a boiler not called
from a burner pause (water-interface.md §4)."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.boiler_call import (
    BoilerCall,
    CallReason,
    boiler_call,
)
from custom_components.vtherm_smart_boiler.core.controller import ControlMode, Reason

CALLED = BoilerCall(True, None)
WAITING = BoilerCall(None, CallReason.WAITING_DATA)
NOT_CONTROLLING = BoilerCall(None, CallReason.NOT_CONTROLLING)


@pytest.mark.parametrize(
    ("mode", "reasons", "calling", "expected"),
    [
        (ControlMode.HEATING, (Reason.DEMAND,), 1, CALLED),
        (ControlMode.FROST, (Reason.FROST,), 0, CALLED),
        # Heating without an outdoor temperature, on the fallback setpoint: called.
        (ControlMode.FALLBACK, (Reason.OUTDOOR_UNKNOWN, Reason.DEMAND), 1, CALLED),
        # A circuit run by other automation asking, no zone calling: called.
        (ControlMode.HEATING, (Reason.CIRCUIT_ASKS,), 0, CALLED),
        # The recognition period holding a heating command: it is in force.
        (ControlMode.HEATING, (Reason.ZONES_RECOGNITION,), 0, CALLED),
        (ControlMode.IDLE, (Reason.NO_DEMAND,), 0, BoilerCall(False, CallReason.NO_DEMAND)),
        # Zones calling under the thresholds (the case SmartPI asked about).
        (ControlMode.IDLE, (Reason.NO_DEMAND,), 2, BoilerCall(False, CallReason.BELOW_THRESHOLD)),
        (
            ControlMode.IDLE,
            (Reason.DEMAND, Reason.ACTIVATION_DELAY),
            1,
            BoilerCall(False, CallReason.ACTIVATION_DELAY),
        ),
        (
            ControlMode.BOILER_FAULT,
            (Reason.BOILER_FAULT,),
            1,
            BoilerCall(False, CallReason.BOILER_FAULT),
        ),
        # The recognition period holding "off", or every zone unknown: cannot be told.
        (ControlMode.IDLE, (Reason.ZONES_RECOGNITION,), 0, WAITING),
        (ControlMode.IDLE, (Reason.ZONES_UNKNOWN,), 0, WAITING),
        (ControlMode.WAITING_DATA, (Reason.BOILER_LINK_STALE,), 1, WAITING),
        (ControlMode.WAITING_DATA, (Reason.ZONES_RECOGNITION,), 0, WAITING),
        (ControlMode.DISABLED, (Reason.CONTROL_OFF,), 1, NOT_CONTROLLING),
        (ControlMode.NOT_ALLOWED, (Reason.PRECONDITION,), 1, NOT_CONTROLLING),
        (ControlMode.HANDED_BACK, (Reason.ALARM_HAND_BACK,), 1, NOT_CONTROLLING),
        (ControlMode.HANDED_BACK, (Reason.ZONES_UNKNOWN,), 0, NOT_CONTROLLING),
    ],
)
def test_the_boiler_call_follows_the_control_state(
    mode: ControlMode, reasons: tuple[Reason, ...], calling: int, expected: BoilerCall
) -> None:
    assert boiler_call(mode, reasons, calling) == expected


def test_every_mode_gives_a_call() -> None:
    """Every mode of the controller maps, so a mode added later must be placed here."""
    for mode in ControlMode:
        result = boiler_call(mode, (), 0)
        assert (result.called is True) is (result.reason is None)


def test_a_fault_comes_before_a_pending_start() -> None:
    """When several apply: the boiler's fault, then the activation delay, then the thresholds."""
    fault = boiler_call(ControlMode.BOILER_FAULT, (Reason.ACTIVATION_DELAY,), 1)
    assert fault.reason is CallReason.BOILER_FAULT
    waiting = boiler_call(ControlMode.IDLE, (Reason.NO_DEMAND, Reason.ACTIVATION_DELAY), 1)
    assert waiting.reason is CallReason.ACTIVATION_DELAY
