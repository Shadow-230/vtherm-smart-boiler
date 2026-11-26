"""The modulation cap (I13.7): an opt-in limit on the boiler's maximum modulation while control
holds the boiler, offered as a suggestion only.

At low load a boiler whose minimum output is above the house's need starts again and again.
Lowering its maximum does not lower its minimum, so a cap helps only where the boiler's range or
its regulation runs it near its maximum in short bursts; the evidence for the gain is weak — a
laboratory test and practitioners (HEM-VAL-05, DESNZ 2023; Bennett et al. 2019). So the cap is
off by default, and where the user switches it on:

- it never goes below a safe floor, nor near the boiler's minimum output where both its powers
  are known: a boiler capped at its minimum is driven to on and off (HEM-VAL-05, p. 11);
- it is released while hot water runs, and while hot water is not known on a boiler that heats
  it: OpenTherm's maximum modulation (ID 14) is not limited to heating by its specification, and
  on a combi a cap could starve the tap;
- it is lifted for a while when the boiler, capped, cannot bring the water to its setpoint: less
  heat in cold weather is its main risk;
- control releases it at every hand-back (``control.py``).

The suggestion — never applied by itself — is the monitor's (``core.cap_suggestion``): control
reads no building model (review question 11).

Every number here is provisional, K4. No Home Assistant imports.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

# The option's bounds and its value's default, in % (provisional, K4): the safe floor up to the
# full range; 70 % where the user ticks it without a value — the cautious side of the range.
CAP_BOUNDS_PCT = (30.0, 100.0)
CAP_DEFAULT_PCT = 70.0
# Never below this, whatever the user picks: boilers' minimum lies at 20–30 % of their maximum
# (Bennett 2018), and a cap at the minimum makes the boiler run on and off (HEM-VAL-05).
SAFE_FLOOR_PCT = 30.0
# Never within this of the boiler's minimum output, as a share of its maximum, where both powers
# are known: read on the boiler's capacity — the higher of the two readings OpenTherm's percent
# may have, so the cap stays above the minimum whichever the boiler uses.
ABOVE_MINIMUM_PCT = 10.0
RELEASED_PCT = 100.0
# The boiler short at the cap: the flow this far below the setpoint with the flame on, held this
# long, lifts the cap for ``LIFTED_S``.
SHORT_K = 5.0
SHORT_S = 600.0
LIFTED_S = 3 * 3600.0
# The cap's read-back (the entity path): what it shows is the cap within this, once it has had
# this long to report.
READ_BACK_TOLERANCE_PCT = 1.0
READ_BACK_WAIT_S = 120.0


class CapReason(StrEnum):
    """Why the cap is applied or released now."""

    APPLIED = "applied"
    NOT_HOLDING = "not_holding"  # control does not hold the boiler
    HOT_WATER = "hot_water"  # hot water runs
    HOT_WATER_UNKNOWN = "hot_water_unknown"  # the boiler heats hot water and it is not known
    LIFTED = "lifted"  # the boiler fell short at the cap: lifted for a while
    FULL_RANGE = "full_range"  # the cap allowed is the full range: nothing to cap


@dataclass(frozen=True, slots=True)
class CapState:
    """``short_since``: since when the boiler, capped, has been short of its setpoint;
    ``lifted_until``: the cap is lifted until then."""

    short_since: float | None = None
    lifted_until: float | None = None


@dataclass(frozen=True, slots=True)
class CapInputs:
    """One step's view: whether control holds the boiler; hot water now (``None``: unknown —
    ``False`` also where the boiler heats none); the flame, the flow and the setpoint written;
    ``capped``: the cap is in force now, so a shortfall is the cap's."""

    now: float
    holding: bool
    hot_water: bool | None
    flame: bool | None = None
    flow: float | None = None
    setpoint: float | None = None
    capped: bool = False


def cap_floor(min_power_kw: float | None, max_power_kw: float | None) -> float:
    """The lowest cap allowed, in %: the safe floor, and above the boiler's minimum output by
    ``ABOVE_MINIMUM_PCT`` where both its powers are known and make sense."""
    floor = SAFE_FLOOR_PCT
    if min_power_kw is not None and max_power_kw is not None and 0.0 < min_power_kw < max_power_kw:
        floor = max(floor, 100.0 * min_power_kw / max_power_kw + ABOVE_MINIMUM_PCT)
    return min(RELEASED_PCT, floor)


def cap_level(requested: float, floor: float) -> int:
    """The cap written, a whole percent (a gateway takes whole numbers): the user's value,
    never below the floor, never above the full range; rounded up — the cautious side."""
    value = min(RELEASED_PCT, max(floor, requested))
    return math.ceil(value - 1e-9)


def cap_step(state: CapState, inputs: CapInputs, level: float) -> tuple[CapState, CapReason]:
    """Whether the cap applies now, and why not. A lift holds its hours whatever else happens; a
    clock set back counts as past."""
    now = inputs.now
    lifted_until = state.lifted_until
    if lifted_until is not None and not now < lifted_until <= now + LIFTED_S:
        lifted_until = None
    kept = CapState(lifted_until=lifted_until)
    if level >= RELEASED_PCT:
        return kept, CapReason.FULL_RANGE
    if not inputs.holding:
        return kept, CapReason.NOT_HOLDING
    if inputs.hot_water is None:
        return kept, CapReason.HOT_WATER_UNKNOWN
    if inputs.hot_water:
        return kept, CapReason.HOT_WATER
    if lifted_until is not None:
        return kept, CapReason.LIFTED
    short = (
        inputs.capped
        and inputs.flame is True
        and inputs.flow is not None
        and inputs.setpoint is not None
        and inputs.flow < inputs.setpoint - SHORT_K
    )
    if not short:
        return CapState(), CapReason.APPLIED
    since = state.short_since
    if since is None or since > now:
        since = now
    if now - since >= SHORT_S:
        return CapState(lifted_until=now + LIFTED_S), CapReason.LIFTED
    return CapState(short_since=since), CapReason.APPLIED


def write_due(
    written: float | None, wanted: float, written_at: float | None, now: float, repeat_s: float
) -> bool:
    """A cap or a release is written: a new value, never written, or its repeat due — a clock
    set back counts as due."""
    if written != wanted or written_at is None:
        return True
    elapsed = now - written_at
    return elapsed < 0 or elapsed >= repeat_s


def read_back_shows(shown: float | None, written: float) -> bool | None:
    """Whether a read-back shows the value written: ``None`` while it shows nothing."""
    if shown is None:
        return None
    return abs(shown - written) <= READ_BACK_TOLERANCE_PCT
