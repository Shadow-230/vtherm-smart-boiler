"""Whether the boiler is called for heat now, and why not (the user's decisions of 2026-10-14).

VT's central boiler decides whether the boiler heats (I12); the plugin shows whether it calls the
boiler now, with the water temperature and its safety rules on top: a zone may call while the
boiler is not fired — VT's central boiler not calling, its activation delay running, the boiler's
own fault.

"Called" is what the plugin commands, not proof that the boiler obeys: a write ignored, a relay
not confirmed, are told by their own alarms. Pure logic from the control state's mode and reasons.

Beside it, the house-wide "boiler gives no heat" signal (I12.9, the user's decision of
2026-11-25), with its reason: what a zone algorithm's user picks to keep it from learning from
heat that never came — SmartPI 1.0's "heating unavailable" input, or an automation.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from .controller import ControlMode, Reason


class CallReason(StrEnum):
    """Why the boiler is not called, or why it cannot be told."""

    NO_DEMAND = "no_demand"  # nothing calls
    BELOW_THRESHOLD = "below_threshold"  # rooms call; VT's central boiler does not
    ACTIVATION_DELAY = "activation_delay"  # VT's central boiler waits its activation delay
    BOILER_FAULT = "boiler_fault"  # the boiler reports its own fault: heating kept off
    NOT_CONTROLLING = "not_controlling"  # the plugin does not decide the boiler's heating now
    WAITING_DATA = "waiting_data"  # it controls but cannot tell yet


@dataclass(frozen=True, slots=True)
class BoilerCall:
    """``called``: the boiler is asked for space heating now; ``None`` while the plugin does not
    decide it or cannot tell. ``reason``: ``None`` while called."""

    called: bool | None
    reason: CallReason | None


_CALLED = frozenset({ControlMode.HEATING, ControlMode.FALLBACK})
_NOT_CONTROLLING = frozenset(
    {ControlMode.DISABLED, ControlMode.NOT_ALLOWED, ControlMode.HANDED_BACK}
)
# Every zone unknown, or the zones known and VT's decision not: nothing can ask for heat.
_UNKNOWN = frozenset({Reason.ZONES_UNKNOWN, Reason.VT_DECISION_UNKNOWN})
_UNDECIDED = _UNKNOWN | {Reason.ZONES_RECOGNITION}


def boiler_call(mode: ControlMode, reasons: Collection[Reason], calling: int) -> BoilerCall:
    """The call from the control state: its ``mode``, its ``reasons`` and how many zones call
    now (``calling``). Heating and the fallback setpoint call — the recognition period's held
    command too; a fault, VT's activation delay, rooms calling while VT's central boiler does
    not, and nothing calling do not, in that order; the recognition period holding "off", and
    every zone or VT's decision unknown, cannot be told."""
    if mode in _NOT_CONTROLLING:
        return BoilerCall(None, CallReason.NOT_CONTROLLING)
    if mode is ControlMode.WAITING_DATA:
        return BoilerCall(None, CallReason.WAITING_DATA)
    if mode is ControlMode.BOILER_FAULT:
        return BoilerCall(False, CallReason.BOILER_FAULT)
    if mode in _CALLED:
        return BoilerCall(True, None)
    if not _UNDECIDED.isdisjoint(reasons):
        return BoilerCall(None, CallReason.WAITING_DATA)
    if Reason.ACTIVATION_DELAY in reasons:
        return BoilerCall(False, CallReason.ACTIVATION_DELAY)
    if calling > 0:
        return BoilerCall(False, CallReason.BELOW_THRESHOLD)
    return BoilerCall(False, CallReason.NO_DEMAND)


class NoHeatReason(StrEnum):
    """Why the boiler gives the rooms no heat now (I12.9)."""

    VT_NOT_CALLING = "vt_not_calling"  # control works; VT's central boiler does not ask for heat
    ACTIVATION_DELAY = "activation_delay"  # VT's central boiler waits its activation delay
    HOT_WATER = "hot_water"  # the boiler heats domestic hot water, which takes the rooms' heat
    BOILER_FAULT = "boiler_fault"  # the boiler reports its own fault that stops it
    HANDED_BACK = "handed_back"  # the plugin cannot vouch for heat: handed back, blocked, unsure


@dataclass(frozen=True, slots=True)
class NoHeat:
    """The house-wide "boiler gives no heat" signal (I12.9): ``on`` while a room calls for heat
    and the boiler gives none (I13.1), ``off`` while it does as far as the plugin drives it or no
    room calls, ``None`` (shown unavailable) while it cannot be told. ``reason``: only while
    on."""

    on: bool | None
    reason: NoHeatReason | None = None


NO_HEAT_UNKNOWN = NoHeat(None)
_HEAT_GIVEN = frozenset({ControlMode.HEATING, ControlMode.FALLBACK})
_NOT_VOUCHED = frozenset({ControlMode.NOT_ALLOWED, ControlMode.HANDED_BACK})


def no_heat(
    mode: ControlMode,
    reasons: Collection[Reason],
    previous: NoHeat,
    *,
    hot_water: bool | None = None,
    writes_stopped: bool = False,
    starting: bool = False,
    rooms_calling: bool | None = None,
) -> NoHeat:
    """The signal from the control step: its ``mode`` and ``reasons``, the last value
    (``previous``), hot water taking the rooms' heat now (``hot_water``, only ``True`` counts),
    whether another controller has the boiler (``writes_stopped``), whether the only blockers
    are Home Assistant starting or VT's settings not known yet (``starting``, I12.16) and whether
    any room VT counts calls for heat now (``rooms_calling``, I13.1; ``None``: not known).

    While no room calls, no room is withheld heat: off, whatever the boiler does — a zone model
    learns from that rest (Hägglund and Åström 2000: learning held only while a controller asks
    for an input it does not get).

    Control switched off by the user: unknown — the plugin does not drive the boiler, and an "on"
    would hold a zone algorithm's learning back for as long as control stays off. Waiting for data
    (a stale link short of a loss, a read-back unknown, the recognition period with nothing held),
    or not allowed only for a start: the last value, nothing being written meanwhile — so a zone
    algorithm does not hold its integral at each start. Handed back, blocked, writes stopped, or
    VT's decision unknown: on, ``handed_back``. Then the boiler's fault; heating wanted (the
    recognition period's kept "on" included): off, or on for hot water; heating not wanted: on,
    for VT's activation delay or VT not calling."""
    if mode is ControlMode.DISABLED:
        return NO_HEAT_UNKNOWN
    if mode is ControlMode.WAITING_DATA or (mode is ControlMode.NOT_ALLOWED and starting):
        return previous
    if rooms_calling is False:
        return NoHeat(False)
    if mode in _NOT_VOUCHED or writes_stopped or not _UNKNOWN.isdisjoint(reasons):
        return NoHeat(True, NoHeatReason.HANDED_BACK)
    if mode is ControlMode.BOILER_FAULT:
        return NoHeat(True, NoHeatReason.BOILER_FAULT)
    if mode in _HEAT_GIVEN:
        return NoHeat(True, NoHeatReason.HOT_WATER) if hot_water is True else NoHeat(False)
    if Reason.ACTIVATION_DELAY in reasons:
        return NoHeat(True, NoHeatReason.ACTIVATION_DELAY)
    return NoHeat(True, NoHeatReason.VT_NOT_CALLING)
