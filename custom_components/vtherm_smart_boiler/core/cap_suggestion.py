"""The modulation cap's suggestion (I13.7) — the monitor's, never applied by itself: the cap
that still covers the house's design heat load with a margin, as an installer range-rates a
boiler to the house's heat loss, offered where the verdict finds mostly short burns.

Apart from ``core.modulation_cap``: control reads no building model (review question 11). Every
number here is provisional, K4. No Home Assistant imports.
"""

from __future__ import annotations

import math

from .building import trusted
from .modulation_cap import cap_floor
from .parameters import ParameterKey, ParameterSet
from .verdict import ReasonCode, ReasonKind, VerdictResult

# The house's design heat load with this margin, rounded up to the step; none where it comes to
# this share of the maximum or more — little to gain.
DESIGN_MARGIN = 1.2
SUGGESTION_STEP_PCT = 5.0
NO_GAIN_PCT = 90.0


def suggested_cap(
    design_load_kw: float | None, min_power_kw: float | None, max_power_kw: float | None
) -> int | None:
    """The cap that still covers the house's design heat load with ``DESIGN_MARGIN``, as a share
    of the boiler's maximum — the cautious reading of OpenTherm's percent: on its other reading,
    a share of the range above the minimum, the same value gives more heat — rounded up to
    ``SUGGESTION_STEP_PCT`` and never below the floor. ``None`` without both powers and the load,
    or where it comes to ``NO_GAIN_PCT`` or more."""
    if design_load_kw is None or min_power_kw is None or max_power_kw is None:
        return None
    if design_load_kw <= 0.0 or not 0.0 < min_power_kw < max_power_kw:
        return None
    wanted = max(
        100.0 * design_load_kw * DESIGN_MARGIN / max_power_kw,
        cap_floor(min_power_kw, max_power_kw),
    )
    level = SUGGESTION_STEP_PCT * math.ceil(wanted / SUGGESTION_STEP_PCT - 1e-9)
    return None if level >= NO_GAIN_PCT else int(level)


def design_load_kw(parameters: ParameterSet) -> float | None:
    """The house's heat load at its design outdoor temperature, from a heat loss the user entered
    or the plugin measured with confidence — never a rule of thumb: the loss times the indoor
    reference less the design outdoor temperature (internal gains left out: the cautious side)."""
    loss = parameters.get(ParameterKey.LOSS_COEFFICIENT).effective()
    indoor = parameters.value(ParameterKey.INDOOR_REFERENCE)
    outdoor = parameters.value(ParameterKey.DESIGN_OUTDOOR)
    if not trusted(loss) or loss is None or indoor is None or outdoor is None:
        return None
    span = indoor - outdoor
    return loss.value * span if span > 0.0 else None


def cap_suggestion(verdict: VerdictResult | None, parameters: ParameterSet) -> int | None:
    """The suggested cap, where the verdict finds mostly short heating burns and the boiler's
    minimum and maximum outputs and the house's design load are known; ``None`` otherwise.
    Shown, never applied."""
    if verdict is None or not any(
        reason.code is ReasonCode.SHORT_BURNS and reason.kind is ReasonKind.PROBLEM
        for reason in verdict.reasons
    ):
        return None
    return suggested_cap(
        design_load_kw(parameters),
        parameters.value(ParameterKey.BOILER_MIN_POWER),
        parameters.value(ParameterKey.BOILER_MAX_POWER),
    )
