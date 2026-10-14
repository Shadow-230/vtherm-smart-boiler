"""Whether the boiler is called for heat now, and why not (the user's decisions of 2026-10-14).

VT's central boiler shows whether it calls the boiler on its binary sensor; the plugin, which
replaces it, shows the same. SmartPI asked for it too (``water-interface.md`` §4): a zone may call
while the boiler is not fired — the demand criteria not met, the activation delay running, the
boiler's own fault — and a zone algorithm must not learn from heat that never came, which a
burner pause (``heat_reason`` ``flame_off``) does not tell apart.

"Called" is what the plugin commands, not proof that the boiler obeys: a write ignored, a relay
not confirmed, are told by their own alarms. Pure logic from the control state's mode and reasons.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from enum import StrEnum

from .controller import ControlMode, Reason


class CallReason(StrEnum):
    """Why the boiler is not called, or why it cannot be told."""

    NO_DEMAND = "no_demand"  # nothing calls
    BELOW_THRESHOLD = "below_threshold"  # zones call; the demand criteria are not met
    ACTIVATION_DELAY = "activation_delay"  # the criteria met; the start waits VT's delay
    BOILER_FAULT = "boiler_fault"  # the boiler reports its own fault: heating kept off
    NOT_CONTROLLING = "not_controlling"  # the plugin does not decide the boiler's heating now
    WAITING_DATA = "waiting_data"  # it controls but cannot tell yet


@dataclass(frozen=True, slots=True)
class BoilerCall:
    """``called``: the boiler is asked for space heating now (frost protection included);
    ``None`` while the plugin does not decide it or cannot tell. ``reason``: ``None`` while
    called."""

    called: bool | None
    reason: CallReason | None


_CALLED = frozenset({ControlMode.HEATING, ControlMode.FROST, ControlMode.FALLBACK})
_NOT_CONTROLLING = frozenset(
    {ControlMode.DISABLED, ControlMode.NOT_ALLOWED, ControlMode.HANDED_BACK}
)


def boiler_call(mode: ControlMode, reasons: Collection[Reason], calling: int) -> BoilerCall:
    """The call from the control state: its ``mode``, its ``reasons`` and how many zones call
    now (``calling``). Heating, frost protection and the fallback setpoint call — the
    recognition period's held command too; a fault, a pending start, zones under the thresholds
    and nothing calling do not, in that order; the recognition period holding "off" and every
    zone unknown cannot be told."""
    if mode in _NOT_CONTROLLING:
        return BoilerCall(None, CallReason.NOT_CONTROLLING)
    if mode is ControlMode.WAITING_DATA:
        return BoilerCall(None, CallReason.WAITING_DATA)
    if mode is ControlMode.BOILER_FAULT:
        return BoilerCall(False, CallReason.BOILER_FAULT)
    if mode in _CALLED:
        return BoilerCall(True, None)
    if Reason.ZONES_RECOGNITION in reasons or Reason.ZONES_UNKNOWN in reasons:
        return BoilerCall(None, CallReason.WAITING_DATA)
    if Reason.ACTIVATION_DELAY in reasons:
        return BoilerCall(False, CallReason.ACTIVATION_DELAY)
    if calling > 0:
        return BoilerCall(False, CallReason.BELOW_THRESHOLD)
    return BoilerCall(False, CallReason.NO_DEMAND)
