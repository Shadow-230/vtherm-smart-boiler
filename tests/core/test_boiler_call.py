"""Whether the boiler is called for heat, and why not (the user's decisions of 2026-10-14): what
VT's central boiler shows on its binary sensor; and the house-wide "boiler gives no heat" signal
with its reason (I12.9), which SmartPI 1.0 takes as its "heating unavailable" input."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.boiler_call import (
    NO_HEAT_UNKNOWN,
    BoilerCall,
    CallReason,
    NoHeat,
    NoHeatReason,
    boiler_call,
    no_heat,
)
from custom_components.vtherm_smart_boiler.core.controller import ControlMode, Reason

CALLED = BoilerCall(True, None)
WAITING = BoilerCall(None, CallReason.WAITING_DATA)
NOT_CONTROLLING = BoilerCall(None, CallReason.NOT_CONTROLLING)


@pytest.mark.parametrize(
    ("mode", "reasons", "calling", "expected"),
    [
        (ControlMode.HEATING, (Reason.DEMAND,), 1, CALLED),
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


# --- I12.9: "boiler gives no heat" ------------------------------------------------------------

GIVEN = NoHeat(False)
ON_BEFORE = NoHeat(True, NoHeatReason.VT_NOT_CALLING)


def on(reason: NoHeatReason) -> NoHeat:
    return NoHeat(True, reason)


@pytest.mark.parametrize(
    ("mode", "reasons", "hot_water", "expected"),
    [
        # Heating wanted, nothing in the way: heat is given.
        (ControlMode.HEATING, (Reason.DEMAND,), False, GIVEN),
        (ControlMode.HEATING, (Reason.DEMAND,), None, GIVEN),  # hot water unknown: not counted
        (ControlMode.FALLBACK, (Reason.OUTDOOR_UNKNOWN, Reason.DEMAND), None, GIVEN),
        (ControlMode.HEATING, (Reason.CIRCUIT_ASKS,), None, GIVEN),
        # The recognition period keeping a heating command: heating.
        (ControlMode.HEATING, (Reason.ZONES_RECOGNITION,), None, GIVEN),
        # Hot water while heating is wanted.
        (ControlMode.HEATING, (Reason.DEMAND,), True, on(NoHeatReason.HOT_WATER)),
        (ControlMode.FALLBACK, (Reason.DEMAND,), True, on(NoHeatReason.HOT_WATER)),
        # Heating not wanted: VT's activation delay, or VT not calling.
        (
            ControlMode.IDLE,
            (Reason.NO_DEMAND, Reason.ACTIVATION_DELAY),
            None,
            on(NoHeatReason.ACTIVATION_DELAY),
        ),
        (ControlMode.IDLE, (Reason.NO_DEMAND,), None, on(NoHeatReason.VT_NOT_CALLING)),
        (ControlMode.IDLE, (Reason.NO_DEMAND,), True, on(NoHeatReason.VT_NOT_CALLING)),
        # The recognition period keeping "off".
        (ControlMode.IDLE, (Reason.ZONES_RECOGNITION,), None, on(NoHeatReason.VT_NOT_CALLING)),
        # The boiler's own fault, before hot water; in the recognition period too.
        (ControlMode.BOILER_FAULT, (Reason.BOILER_FAULT,), True, on(NoHeatReason.BOILER_FAULT)),
        (
            ControlMode.BOILER_FAULT,
            (Reason.ZONES_RECOGNITION, Reason.BOILER_FAULT),
            None,
            on(NoHeatReason.BOILER_FAULT),
        ),
        # The plugin cannot vouch for heat: an alarm or latch, a lost link, a blocker, nothing
        # asking with a working thermostat, VT's decision unknown with none.
        (ControlMode.HANDED_BACK, (Reason.ALARM_HAND_BACK,), None, on(NoHeatReason.HANDED_BACK)),
        (
            ControlMode.HANDED_BACK,
            (Reason.BOILER_LINK_STALE,),
            None,
            on(NoHeatReason.HANDED_BACK),
        ),
        (ControlMode.HANDED_BACK, (Reason.ZONES_UNKNOWN,), None, on(NoHeatReason.HANDED_BACK)),
        (ControlMode.NOT_ALLOWED, (Reason.PRECONDITION,), None, on(NoHeatReason.HANDED_BACK)),
        (ControlMode.IDLE, (Reason.ZONES_UNKNOWN,), None, on(NoHeatReason.HANDED_BACK)),
    ],
)
def test_the_no_heat_signal_follows_the_control_step(
    mode: ControlMode,
    reasons: tuple[Reason, ...],
    hot_water: bool | None,
    expected: NoHeat,
) -> None:
    assert no_heat(mode, reasons, NO_HEAT_UNKNOWN, hot_water=hot_water) == expected


def test_control_switched_off_cannot_tell() -> None:
    """Switched off by the user: unknown (shown unavailable), never on — SmartPI's learning
    would stay held for as long as control is off — whatever it showed before."""
    for previous in (NO_HEAT_UNKNOWN, GIVEN, ON_BEFORE):
        assert no_heat(ControlMode.DISABLED, (Reason.CONTROL_OFF,), previous) == NO_HEAT_UNKNOWN
        assert no_heat(ControlMode.DISABLED, (), previous, hot_water=True) == NO_HEAT_UNKNOWN


@pytest.mark.parametrize(
    "reasons",
    [(Reason.BOILER_LINK_STALE,), (Reason.READ_BACK_UNKNOWN,), (Reason.ZONES_RECOGNITION,)],
)
def test_waiting_for_data_keeps_the_last_value(reasons: tuple[Reason, ...]) -> None:
    """A stale link short of a loss, a read-back unknown, the recognition period with nothing
    held: nothing is written meanwhile, so the last value stands, its reason too; none before:
    unknown."""
    for previous in (GIVEN, ON_BEFORE, on(NoHeatReason.HOT_WATER), NO_HEAT_UNKNOWN):
        assert no_heat(ControlMode.WAITING_DATA, reasons, previous, hot_water=True) == previous


def test_writes_stopped_cannot_vouch_for_heat() -> None:
    """Another controller has the boiler: whatever control would decide, the plugin cannot vouch
    for heat."""
    assert no_heat(ControlMode.HEATING, (Reason.DEMAND,), GIVEN, writes_stopped=True) == on(
        NoHeatReason.HANDED_BACK
    )


def test_every_mode_gives_a_no_heat_value() -> None:
    """Every mode is mapped; only "switched off" and waiting for data with nothing before are
    unknown."""
    for mode in ControlMode:
        found = no_heat(mode, (), NO_HEAT_UNKNOWN)
        unknown = mode in (ControlMode.DISABLED, ControlMode.WAITING_DATA)
        assert (found.on is None) is unknown, mode
        assert (found.reason is None) is (found.on is not True), mode
