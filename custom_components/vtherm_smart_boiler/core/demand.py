"""Boiler demand: VT's central boiler decides whether the boiler heats (I12, the user's decision of
2026-11-25); the plugin counts the zones that call.

VT's central boiler, set up in VT with its own thresholds and activation delay, switches a helper
the user created; the plugin follows the helper's state — ``True`` VT wants heat, ``False`` not,
``None`` not known. The plugin still reads the zones: how many call (shown, and the call's reason
"rooms call, VT's central boiler does not"), which are unknown, and — through decision 3 — whether
anything can ask at all: with no zone known, or VT's decision unknown, nothing can ask for heat
(``wanted`` ``None``).

A zone calls when it is in a mode that may heat and VT says one of its devices is active; without
that, by VT's own rule — its valve open at all, or without a valve its duty cycle above 0 — else
when VT says it is heating. A zone in "auto" or heat_cool calls only while its action says so;
one VT's power shedding holds off calls for nothing. Only zones whose state is known count: a zone
that is unavailable, or one VT has not started, is unknown; a zone in its grace period keeps its
last known answer (``memory``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .readings import ZoneState


@dataclass(frozen=True, slots=True)
class Demand:
    wanted: bool | None  # VT's decision; None: it is not known, or no zone is known
    zones_wanting: int = 0  # the known zones that call now
    fresh_zones: int = 0  # the zones known now, those in their grace period included
    unknown: tuple[str, ...] = ()  # zones whose state is not known


def zone_wants_heat(zone: ZoneState) -> bool:
    if zone.heating_enabled is not True or zone.shedding:
        return False
    if zone.auto_mode:
        if zone.calling is not None:
            return zone.calling
        return _open(zone)
    if zone.device_active is not None:
        return zone.device_active
    if zone.valve_open is not None or zone.on_percent is not None:
        return _open(zone)
    return zone.calling is True


def _open(zone: ZoneState) -> bool:
    """VT's rule where VT gives no device state (2026-10-14): a valve open at all decides where
    the zone has one; without a valve, a duty cycle above 0 — the zone asks for some heat within
    its cycle."""
    if zone.valve_open is not None:
        return zone.valve_open > 0.0
    return zone.on_percent is not None and zone.on_percent > 0.0


def boiler_demand(
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    vt_wants: bool | None,
    *,
    memory: Mapping[str, ZoneState] | None = None,
) -> Demand:
    """Demand now: VT's decision (``vt_wants``), and the zones that call. ``memory``: the last
    known state of each zone in its grace period, which stands for the zone whatever it shows
    now. With no zone known, nothing can ask for heat, whatever VT's helper shows (decision 3)."""
    memory = memory or {}
    known: list[ZoneState] = []
    unknown: list[str] = []
    for zone in zones:
        if zone.zone_id in memory:
            known.append(memory[zone.zone_id])
        elif zone.is_known(now, max_age):
            known.append(zone)
        else:
            unknown.append(zone.zone_id)
    if not known:
        return Demand(None, unknown=tuple(unknown))
    wanting = sum(1 for zone in known if zone_wants_heat(zone))
    return Demand(vt_wants, wanting, len(known), tuple(unknown))
