"""Basic anti-cycling: minimum burn, minimum pause and a budget of starts per hour.

The plugin cannot keep a burner alight or put it out; it decides only whether heating is enabled.
So: it never disables heating during a burn younger than the minimum burn; it does not re-enable
heating sooner than the minimum pause after a heating burn ended; and it holds heating off while
the starts of the last hour have used up the budget. DHW burns count for none of these. Without a
known flame state nothing is held — a missing signal must not keep the house cold. Frost heating
is urgent and skips the pause and the budget.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

HOUR = 3600.0


@dataclass(frozen=True, slots=True)
class AntiCycleConfig:
    min_burn_s: float = 5 * 60.0
    min_pause_s: float = 5 * 60.0
    max_starts_per_hour: int = 6

    def __post_init__(self) -> None:
        if self.min_burn_s < 0 or self.min_pause_s < 0:
            raise ValueError("minimum burn and pause must not be negative")
        if self.max_starts_per_hour < 1:
            raise ValueError("the start budget must allow at least one start per hour")


@dataclass(frozen=True, slots=True)
class AntiCycleState:
    burning: bool | None = None  # last known flame state
    heating_burn: bool = False  # the current or last burn heated the rooms (not DHW)
    burn_started_at: float | None = None
    burn_ended_at: float | None = None  # end of the last heating burn
    starts: tuple[float, ...] = ()  # heating starts in the last hour


def observe_flame(
    state: AntiCycleState, flame: bool | None, dhw: bool | None, now: float
) -> AntiCycleState:
    """Update from the flame signal; only edges seen between known states count."""
    starts = tuple(t for t in state.starts if now - t < HOUR)
    if flame is None:
        return replace(state, burning=None, starts=starts)
    if state.burning is False and flame:
        heating = dhw is not True
        return AntiCycleState(
            True,
            heating,
            now,
            state.burn_ended_at,
            (*starts, now) if heating else starts,
        )
    if state.burning is True and not flame:
        ended = now if state.heating_burn else state.burn_ended_at
        return AntiCycleState(False, state.heating_burn, state.burn_started_at, ended, starts)
    if state.burning is None:
        # First known state after unknown: no edge was seen.
        return AntiCycleState(flame, dhw is not True, None, state.burn_ended_at, starts)
    heating = state.heating_burn and dhw is not True if flame else state.heating_burn
    return replace(state, heating_burn=heating, starts=starts)


class Hold(StrEnum):
    MIN_BURN = "min_burn"
    MIN_PAUSE = "min_pause"
    START_BUDGET = "start_budget"


@dataclass(frozen=True, slots=True)
class AntiCycleResult:
    ch_enable: bool
    hold: Hold | None = None
    until: float | None = None


def apply_anticycling(
    want_heat: bool,
    state: AntiCycleState,
    now: float,
    config: AntiCycleConfig,
    urgent: bool = False,
) -> AntiCycleResult:
    """Whether heating may be enabled now, and which rule holds it otherwise."""
    if state.burning is None:
        return AntiCycleResult(want_heat)
    if not want_heat:
        if (
            state.burning
            and state.heating_burn
            and state.burn_started_at is not None
            and now - state.burn_started_at < config.min_burn_s
        ):
            return AntiCycleResult(True, Hold.MIN_BURN, state.burn_started_at + config.min_burn_s)
        return AntiCycleResult(False)
    if state.burning or urgent:
        return AntiCycleResult(True)
    if state.burn_ended_at is not None and now - state.burn_ended_at < config.min_pause_s:
        return AntiCycleResult(False, Hold.MIN_PAUSE, state.burn_ended_at + config.min_pause_s)
    recent = [t for t in state.starts if now - t < HOUR]
    if len(recent) >= config.max_starts_per_hour:
        return AntiCycleResult(False, Hold.START_BUDGET, min(recent) + HOUR)
    return AntiCycleResult(True)
