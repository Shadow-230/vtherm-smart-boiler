"""The plugin's journal, for the Boiler page's Journal tab
(``docs/en/development/plans/plan-0.2-i10.md``, I10.6): what the plugin decided and why.

Each look at control and the alarms is compared with the one before: the heat call on and off,
the water setpoint from its first value while control holds the boiler and then each change of at
least ``WATER_STEP_K`` from the value last journaled (so a ramp's small steps add up), a circuit's
need holding the water, control handed back and taken again, an alarm raised — or its level
raised — and cleared; each with the reasons control gave. The first look after a start only sets
the baseline: the start itself is journaled, not what was already so. An alarm that cannot be
judged now stays as it was. Kept ``JOURNAL_DAYS`` days and ``JOURNAL_MAX`` entries at most, the
oldest dropped first (provisional, K4). The journal only watches: it changes nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, TypeGuard

JOURNAL_DAYS = 14
JOURNAL_MAX = 2000
WATER_STEP_K = 1.0
CIRCUIT_NEED = "limit_circuit_need"  # ``core.controller.Reason.LIMIT_CIRCUIT_NEED``
DAY = 86400.0


class Kind(StrEnum):
    STARTED = "started"  # the plugin started (a restart, a reload)
    STOPPED = "stopped"  # the plugin stopped
    CALL_ON = "call_on"  # the boiler called for heat
    CALL_OFF = "call_off"  # the call ended, and why
    WATER = "water"  # the water setpoint written
    CIRCUIT_NEED = "circuit_need"  # a circuit's need holds the water up
    CIRCUIT_NEED_END = "circuit_need_end"
    HANDED_BACK = "handed_back"  # control no longer holds the boiler
    TOOK_OVER = "took_over"  # control holds the boiler again
    ALARM_ON = "alarm_on"  # an alarm raised, or its level raised
    ALARM_OFF = "alarm_off"
    SETTINGS = "settings"  # the settings saved, from the page or the settings


@dataclass(frozen=True, slots=True)
class Entry:
    at: float
    kind: Kind
    reasons: tuple[str, ...] = ()  # control's reasons, the call's, or what the settings changed
    value: float | None = None  # the water now, °C
    previous: float | None = None  # the water last journaled, °C
    subject: str | None = None  # the alarm's entity key, or where the settings were saved from
    level: str | None = None  # an alarm's level ("warning", "alarm")


@dataclass(frozen=True, slots=True)
class Observed:
    """One look at control and the alarms."""

    controlling: bool  # control holds the boiler (its mode is neither off nor handed back)
    called: bool | None  # the boiler called for heat; ``None`` while not told
    call_reason: str | None  # why not called
    water: float | None  # the water setpoint written, °C
    reasons: tuple[str, ...]  # control's reasons now
    # Each alarm by its entity key, with its level while active; ``None``: it cannot be judged
    # now. An alarm not listed is clear.
    alarms: Mapping[str, str | None] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JournalState:
    last: Observed | None = None  # the last look, its unknown alarms filled from the one before
    water: float | None = None  # the water last journaled, while control holds the boiler


def follow(state: JournalState, now: Observed, at: float) -> tuple[JournalState, tuple[Entry, ...]]:
    """The entries ``now`` makes against the last look, and the state for the next."""
    previous = state.last
    alarms = _alarms(now.alarms, None if previous is None else previous.alarms)
    seen = Observed(now.controlling, now.called, now.call_reason, now.water, now.reasons, alarms)
    if previous is None:
        return JournalState(seen, now.water if now.controlling else None), ()
    entries: list[Entry] = []
    if previous.controlling and not now.controlling:
        entries.append(Entry(at, Kind.HANDED_BACK, now.reasons))
    elif now.controlling and not previous.controlling:
        entries.append(Entry(at, Kind.TOOK_OVER, now.reasons))
    if now.called is True and previous.called is not True:
        entries.append(Entry(at, Kind.CALL_ON, now.reasons))
    elif previous.called is True and now.called is not True:
        reason = () if now.call_reason is None else (now.call_reason,)
        entries.append(Entry(at, Kind.CALL_OFF, reason))
    water = state.water if now.controlling else None
    if (
        now.controlling
        and now.water is not None
        and (water is None or abs(now.water - water) >= WATER_STEP_K)
    ):
        entries.append(Entry(at, Kind.WATER, now.reasons, value=now.water, previous=water))
        water = now.water
    need, needed = CIRCUIT_NEED in now.reasons, CIRCUIT_NEED in previous.reasons
    if need and not needed:
        entries.append(Entry(at, Kind.CIRCUIT_NEED, now.reasons, value=now.water))
    elif needed and not need:
        entries.append(Entry(at, Kind.CIRCUIT_NEED_END, now.reasons, value=now.water))
    for key in sorted(alarms):
        if alarms[key] != previous.alarms.get(key):
            entries.append(Entry(at, Kind.ALARM_ON, subject=key, level=alarms[key]))
    entries.extend(
        Entry(at, Kind.ALARM_OFF, subject=key)
        for key in sorted(previous.alarms)
        if key not in alarms
    )
    return JournalState(seen, water), tuple(entries)


def _alarms(
    now: Mapping[str, str | None], before: Mapping[str, str | None] | None
) -> dict[str, str | None]:
    """The active alarms with their levels; one that cannot be judged now as it was."""
    active: dict[str, str | None] = {k: v for k, v in now.items() if v is not None}
    for key, level in now.items():
        if level is None and before is not None and key in before:
            active[key] = before[key]
    return active


def settings_saved(at: float, source: str, changed: Iterable[str]) -> Entry:
    """The settings saved from ``source`` ("page" or "settings"), naming what changed."""
    return Entry(at, Kind.SETTINGS, tuple(changed), subject=source)


def prune(entries: Iterable[Entry], now: float) -> list[Entry]:
    """The entries of the last ``JOURNAL_DAYS`` days, ``JOURNAL_MAX`` at most, oldest first."""
    kept = [entry for entry in entries if entry.at >= now - JOURNAL_DAYS * DAY]
    return kept[-JOURNAL_MAX:]


def entry_to_stored(entry: Entry) -> dict[str, Any]:
    stored: dict[str, Any] = {"at": round(entry.at, 1), "kind": entry.kind.value}
    if entry.reasons:
        stored["reasons"] = list(entry.reasons)
    if entry.value is not None:
        stored["value"] = round(entry.value, 2)
    if entry.previous is not None:
        stored["previous"] = round(entry.previous, 2)
    if entry.subject is not None:
        stored["subject"] = entry.subject
    if entry.level is not None:
        stored["level"] = entry.level
    return stored


def entry_from_stored(raw: object) -> Entry | None:
    """An entry as stored; ``None`` for one that cannot be read, which is left out."""
    if not isinstance(raw, Mapping):
        return None
    at, kind, reasons = raw.get("at"), raw.get("kind"), raw.get("reasons", [])
    if not _number(at) or not isinstance(kind, str) or kind not in Kind._value2member_map_:
        return None
    if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
        return None
    try:
        value, previous = _optional_float(raw.get("value")), _optional_float(raw.get("previous"))
        subject, level = _optional_text(raw.get("subject")), _optional_text(raw.get("level"))
    except ValueError:
        return None
    return Entry(
        float(at),
        Kind(kind),
        tuple(reasons),
        value=value,
        previous=previous,
        subject=subject,
        level=level,
    )


def _number(value: object) -> TypeGuard[int | float]:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    if not _number(value):
        raise ValueError(value)
    return float(value)


def _optional_text(value: object) -> str | None:
    if value is not None and not isinstance(value, str):
        raise ValueError(value)
    return value
