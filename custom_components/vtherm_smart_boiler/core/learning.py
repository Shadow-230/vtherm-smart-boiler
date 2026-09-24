"""Learning pauses: keep the zone algorithms from learning what the boiler did to the rooms.

A zone's learning is paused while DHW runs and its valve is open (no hot water reaches it), while
foreign heat warms it, and while the water temperature swings widely. It resumes once the cause is
gone for the minimum pause and — after DHW — the flow is back near its setpoint.

The plugin only resumes what it paused itself and never touches a zone whose learning the user
has switched off. Every toggle costs the zone algorithm its observation in progress, so the
plugin does not toggle faster than the minimum pause.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

MINUTE = 60.0


class PauseCause(StrEnum):
    DHW = "dhw"
    FOREIGN_HEAT = "foreign_heat"
    WATER_SWING = "water_swing"


@dataclass(frozen=True, slots=True)
class LearningConfig:
    pause_on_dhw: bool = True
    pause_on_foreign_heat: bool = True
    pause_on_water_swing: bool = True
    swing_k: float = 5.0  # setpoint change within the window that counts as a swing
    swing_window_s: float = 30 * MINUTE
    min_pause_s: float = 10 * MINUTE
    resume_margin_k: float = 3.0  # after DHW, the flow must be this close to its setpoint


@dataclass(frozen=True, slots=True)
class ZoneLearning:
    """A zone as the pause logic sees it; ``learning`` is its algorithm's flag (None: unknown)."""

    zone_id: str
    learning: bool | None
    valve_open: bool
    foreign_heat: bool


@dataclass(frozen=True, slots=True)
class LearningState:
    paused: Mapping[str, float] = field(default_factory=dict)  # zones the plugin paused, since
    setpoints: tuple[tuple[float, float], ...] = ()  # recent setpoints, for swings
    last_toggle: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LearningPlan:
    state: LearningState
    pause: tuple[str, ...] = ()
    resume: tuple[str, ...] = ()
    causes: Mapping[str, tuple[PauseCause, ...]] = field(default_factory=dict)


def _swing(setpoints: Sequence[tuple[float, float]], config: LearningConfig) -> bool:
    values = [value for _t, value in setpoints]
    return bool(values) and max(values) - min(values) >= config.swing_k


def plan_learning(
    state: LearningState,
    zones: Sequence[ZoneLearning],
    dhw: bool | None,
    flow: float | None,
    setpoint: float | None,
    now: float,
    config: LearningConfig,
) -> LearningPlan:
    """Which zones to pause and resume now."""
    setpoints = tuple(
        (t, v)
        for t, v in (*state.setpoints, *(((now, setpoint),) if setpoint is not None else ()))
        if now - t <= config.swing_window_s
    )
    swing = config.pause_on_water_swing and _swing(setpoints, config)
    # Resume only once the water is back near its setpoint; when that cannot be told, the
    # minimum pause alone decides, so a pause never lasts for ever.
    flow_recovered = flow is None or setpoint is None or flow >= setpoint - config.resume_margin_k
    paused = dict(state.paused)
    toggles = dict(state.last_toggle)
    pause: list[str] = []
    resume: list[str] = []
    causes: dict[str, tuple[PauseCause, ...]] = {}
    for zone in zones:
        reasons: list[PauseCause] = []
        if config.pause_on_dhw and dhw is True and zone.valve_open:
            reasons.append(PauseCause.DHW)
        if config.pause_on_foreign_heat and zone.foreign_heat:
            reasons.append(PauseCause.FOREIGN_HEAT)
        if swing:
            reasons.append(PauseCause.WATER_SWING)
        causes[zone.zone_id] = tuple(reasons)
        last = toggles.get(zone.zone_id)
        settled = last is None or now - last >= config.min_pause_s
        ours = zone.zone_id in paused
        if reasons and not ours and zone.learning is True and settled:
            pause.append(zone.zone_id)
            paused[zone.zone_id] = now
            toggles[zone.zone_id] = now
        elif not reasons and ours and settled and flow_recovered:
            if zone.learning is not True:
                resume.append(zone.zone_id)
            paused.pop(zone.zone_id, None)
            toggles[zone.zone_id] = now
    return LearningPlan(
        LearningState(paused, setpoints, toggles), tuple(pause), tuple(resume), causes
    )


def release_all(state: LearningState, now: float) -> tuple[LearningState, tuple[str, ...]]:
    """Resume every zone the plugin paused (control switched off, unload, hand-back).

    A release is a toggle too: a zone is not paused again sooner than the minimum pause."""
    toggles = dict(state.last_toggle)
    toggles.update(dict.fromkeys(state.paused, now))
    return LearningState({}, state.setpoints, toggles), tuple(state.paused)
