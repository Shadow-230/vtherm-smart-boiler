"""A long burn that does not reach the rooms (G11 E): information and a warning, never control.

The case behind it: about 12 h of heat demand with the flame on throughout, the flow holding its
setpoint within about a kelvin, a low flue temperature, and rooms never reaching their setpoints
— the boiler had reserve; the water was simply too cool and nobody raised it. A run is the flame
burning, its gaps of up to ``GAP_S`` included (K4, the user's decision of 2026-11-17, J4's F10:
a boiler cycling at its minimum while the rooms stay short is the same case — Salford's test house
cycled and lost comfort at a low flow; Bennett: cycling from the minimum output against the
demand); the flame unknown ends it. The rule looks once a run has lasted ``LONG_RUN_S``, at the
rooms the caller counts — heating, known, not warmed by foreign heat — and, first that fits:

1. rooms short and not warming, the flame on without a break for ``LONG_RUN_S``, the flow below
   its setpoint by more than ``HOLDING_K`` at a modulation of at least ``HIGH_MODULATION`` → the
   boiler at its power limit (a warning);
2. rooms short and not warming — one counts like any other (addition 2) — and the water at its
   setpoint: with the flame on throughout the last ``AVERAGE_S``, the flow holding it within
   ``HOLDING_K``; with the burner stopping in that time, the flow having reached it within
   ``HOLDING_K`` → the water too cool for them (information: the curve too low; the comfort
   correction, where it is on, raises it, and at its limit names the room and the causes);
3. every room over its setpoint by at least ``TOO_HOT_K`` for ``TOO_HOT_S`` → the water too hot,
   lower the curve (information);
4. otherwise nothing — rooms at their setpoints is the ideal state: few starts, condensing.

"Not warming": a room whose temperature rose less than ``NOT_RISING_K`` over the run's last
``LONG_RUN_S``. The flow, setpoint and modulation are averaged over the last ``AVERAGE_S`` so the
class does not flicker with the burner's own swings; without them classes 1 and 2 are not judged.
Every value provisional (K4), each with its reason in ``docs/en/development/plans/plan-0.2-g11.md``
E.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from statistics import fmean

HOUR = 3600.0
LONG_RUN_S = 3 * HOUR  # a run this long is judged
GAP_S = 30 * 60.0  # the flame off longer ends a run: a boiler cycling keeps it (K4, F10)
NOT_RISING_K = 0.2  # a room rising less over the run's last 3 h is not warming: above sensor noise
HOLDING_K = 1.0  # the flow this close to its setpoint holds it: the boiler's own regulation band
HIGH_MODULATION = 90.0  # percent: the burner near its top
TOO_HOT_K = 0.3  # every room this far over its setpoint ... (``SHORT_K``'s mirror)
TOO_HOT_S = HOUR  # ... this long: the water too hot
AVERAGE_S = 30 * 60.0  # the flow, setpoint and modulation averaged over this long
SAMPLE_S = 5 * 60.0  # a room's temperature kept this often


class LongRunClass(StrEnum):
    POWER_LIMIT = "power_limit"  # a warning
    WATER_TOO_COOL = "water_too_cool"  # information
    WATER_TOO_HOT = "water_too_hot"  # information


@dataclass(frozen=True, slots=True)
class RoomLook:
    """One counted room now: its temperature and setpoint, and whether it is short — fully open
    and short by the comfort correction's own rule, with SmartPI's learning band."""

    zone_id: str
    temperature: float | None
    target: float | None
    short: bool


@dataclass(frozen=True, slots=True)
class LongRun:
    """A run of burning: since when, since when the flame has been on without a break (``None``
    while it is off), when it was last seen on, each room's temperatures every ``SAMPLE_S`` over
    its last ``LONG_RUN_S``, the water's last ``AVERAGE_S`` — (time, flow, setpoint, modulation,
    flame) — since when every room has been too warm, and the class found now with the rooms it
    names."""

    burning_since: float | None = None
    flame_since: float | None = None
    flame_seen: float | None = None
    rooms: tuple[tuple[str, tuple[tuple[float, float], ...]], ...] = ()
    water: tuple[tuple[float, float | None, float | None, float | None, bool], ...] = ()
    hot_since: float | None = None
    found: LongRunClass | None = None
    rooms_named: tuple[str, ...] = ()

    @property
    def burning_s(self) -> float | None:
        """How long this run has lasted, its gaps included, at its last look."""
        if self.burning_since is None or not self.water:
            return None
        return self.water[-1][0] - self.burning_since


def follow_long_run(
    state: LongRun,
    now: float,
    flame: bool | None,
    flow: float | None,
    setpoint: float | None,
    modulation: float | None,
    rooms: Sequence[RoomLook],
) -> LongRun:
    """One look. The flame unknown ends the run, and the flame off for more than ``GAP_S``
    since it was last seen on; a moment before the last look (the wall clock set back) starts it
    again."""
    if flame is None:
        return LongRun()
    if state.water and now < state.water[-1][0]:
        state = LongRun()
    if not flame and (state.flame_seen is None or now - state.flame_seen > GAP_S):
        return LongRun()
    since = now if state.burning_since is None else state.burning_since
    seen: float | None
    if flame:
        flame_since = now if state.flame_since is None else state.flame_since
        seen = now
    else:
        flame_since, seen = None, state.flame_seen
    water = (
        *(w for w in state.water if now - w[0] <= AVERAGE_S),
        (now, flow, setpoint, modulation, flame),
    )
    kept = dict(state.rooms)
    samples = {
        room.zone_id: _sampled(kept.get(room.zone_id, ()), now, room.temperature) for room in rooms
    }
    hot = bool(rooms) and all(_over(room) for room in rooms)
    hot_since = (now if state.hot_since is None else state.hot_since) if hot else None
    found: LongRunClass | None = None
    named: tuple[str, ...] = ()
    if now - since >= LONG_RUN_S:
        unbroken = flame_since is not None and now - flame_since >= LONG_RUN_S
        found, named = _classify(now, water, hot_since, rooms, samples, unbroken)
    return LongRun(
        since, flame_since, seen, tuple(sorted(samples.items())), water, hot_since, found, named
    )


def _sampled(
    samples: tuple[tuple[float, float], ...], now: float, temperature: float | None
) -> tuple[tuple[float, float], ...]:
    kept = tuple(s for s in samples if now - s[0] <= LONG_RUN_S + SAMPLE_S)
    if temperature is None or (kept and now - kept[-1][0] < SAMPLE_S):
        return kept
    return (*kept, (now, temperature))


def _over(room: RoomLook) -> bool:
    return (
        room.temperature is not None
        and room.target is not None
        and room.temperature - room.target >= TOO_HOT_K
    )


def _not_rising(samples: tuple[tuple[float, float], ...], now: float, room: RoomLook) -> bool:
    """Rose less than ``NOT_RISING_K`` since about ``LONG_RUN_S`` ago; not known: not judged."""
    old = [value for t, value in samples if now - t >= LONG_RUN_S - SAMPLE_S]
    if not old or room.temperature is None:
        return False
    return room.temperature - old[0] < NOT_RISING_K


def _classify(
    now: float,
    water: Sequence[tuple[float, float | None, float | None, float | None, bool]],
    hot_since: float | None,
    rooms: Sequence[RoomLook],
    samples: Mapping[str, tuple[tuple[float, float], ...]],
    unbroken: bool,
) -> tuple[LongRunClass | None, tuple[str, ...]]:
    """``unbroken``: the flame on without a break for ``LONG_RUN_S``."""
    short = tuple(
        sorted(
            room.zone_id
            for room in rooms
            if room.short and _not_rising(samples.get(room.zone_id, ()), now, room)
        )
    )
    burning = [w for w in water if w[4]]
    gaps = [sp - flow for _t, flow, sp, _m, _on in burning if flow is not None and sp is not None]
    levels = [m for _t, _f, _s, m, _on in burning if m is not None]
    if short and gaps:
        if len(burning) < len(water):  # the burner stopped within the window: it cycles
            if min(gaps) <= HOLDING_K:  # having reached its setpoint
                return LongRunClass.WATER_TOO_COOL, short
        else:
            gap = fmean(gaps)
            level = fmean(levels) if levels else None
            high = level is not None and level >= HIGH_MODULATION
            if unbroken and gap > HOLDING_K and high:
                return LongRunClass.POWER_LIMIT, short
            if abs(gap) <= HOLDING_K:
                return LongRunClass.WATER_TOO_COOL, short
    if hot_since is not None and now - hot_since >= TOO_HOT_S:
        return LongRunClass.WATER_TOO_HOT, tuple(sorted(room.zone_id for room in rooms))
    return None, ()


def tally(
    totals: Mapping[str, float],
    before: LongRunClass | None,
    after: LongRunClass | None,
    step_s: float,
) -> dict[str, float]:
    """The kept counts for 0.4's tuning: each class's runs, counted once as one begins, and its
    hours, ``step_s`` at a time while it holds."""
    result = dict(totals)
    if after is None:
        return result
    if after is not before:
        result[f"{after.value}_runs"] = result.get(f"{after.value}_runs", 0) + 1
    hours = f"{after.value}_hours"
    result[hours] = result.get(hours, 0.0) + max(0.0, step_s) / HOUR
    return result
