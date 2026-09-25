"""Learning pauses: keep the zone algorithms from learning what the boiler did to the rooms.

A zone's learning is paused while DHW runs and its valve is open (no hot water reaches it), while
foreign heat warms it, and while the water temperature swings widely. It resumes once the cause is
gone for the minimum pause and — after DHW — the flow is back within a tolerance of its setpoint,
at the latest after the longest pause.

The plugin only resumes what it paused itself and never touches a zone whose learning the user
has switched off. Every toggle costs the zone algorithm its observation in progress, so the
plugin does not toggle faster than the minimum pause.

Every pause and resume is read back from the zone algorithm's flag: SmartPI skips a thermostat
it cannot find without an error, and keeps its flag for good. A pause whose flag still reads on a
minute later did not take — or the user switched learning back on — and is not the plugin's any
more. A resume is followed until the flag reads on, and sent again every minute until it does;
a zone gone for a day is no longer followed. A switch-off by the user during the plugin's own
pause cannot be told from the pause itself: the flag reads off either way.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum

MINUTE = 60.0
DAY = 86400.0


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
    resume_margin_k: float = 3.0  # after DHW, the flow must be back within this of its setpoint
    max_pause_s: float = 60 * MINUTE  # ...or the pause this long, once its causes are gone
    check_s: float = MINUTE  # a pause or resume is read back after this
    give_up_s: float = DAY  # a zone gone this long after a resume is no longer followed


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
    # Zones the plugin resumed, until their flag reads on: when the resume was last sent.
    resuming: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LearningPlan:
    state: LearningState
    pause: tuple[str, ...] = ()
    resume: tuple[str, ...] = ()
    causes: Mapping[str, tuple[PauseCause, ...]] = field(default_factory=dict)


def _swing(setpoints: Sequence[tuple[float, float]], config: LearningConfig) -> bool:
    values = [value for _t, value in setpoints]
    return bool(values) and max(values) - min(values) >= config.swing_k


def follow_resumes(
    state: LearningState,
    flags: Mapping[str, bool | None],
    now: float,
    config: LearningConfig,
) -> tuple[LearningState, tuple[str, ...]]:
    """Zones resumed by the plugin, read back: done once the flag reads on; sent again every
    ``check_s`` while it reads off; dropped once gone for ``give_up_s``. Returns the zones to
    resume again now."""
    resuming = dict(state.resuming)
    again: list[str] = []
    for zone_id, sent_at in state.resuming.items():
        flag = flags.get(zone_id)
        if flag is True:
            resuming.pop(zone_id)
        elif flag is False:
            if now - sent_at >= config.check_s:
                again.append(zone_id)
                resuming[zone_id] = now
        elif now - sent_at >= config.give_up_s:
            resuming.pop(zone_id)  # gone for long: another zone, or the algorithm replaced
    return replace(state, resuming=resuming), tuple(again)


def plan_learning(
    state: LearningState,
    zones: Sequence[ZoneLearning],
    dhw: bool | None,
    flow: float | None,
    setpoint: float | None,
    now: float,
    config: LearningConfig,
    heating: bool | None = None,
) -> LearningPlan:
    """Which zones to pause and resume now. ``setpoint`` is the heating setpoint (not a low
    "off" value); ``heating`` whether the boiler is to heat now (``None``: unknown)."""
    state, again = follow_resumes(state, {z.zone_id: z.learning for z in zones}, now, config)
    setpoints = tuple(
        (t, v)
        for t, v in (*state.setpoints, *(((now, setpoint),) if setpoint is not None else ()))
        if now - t <= config.swing_window_s
    )
    swing = config.pause_on_water_swing and _swing(setpoints, config)
    # Resume only once the water is back near its setpoint; when that cannot be told, or heating
    # is off so the water will not come back, the minimum pause alone decides.
    flow_recovered = (
        flow is None
        or setpoint is None
        or heating is False
        or abs(flow - setpoint) <= config.resume_margin_k
    )
    paused = dict(state.paused)
    toggles = dict(state.last_toggle)
    resuming = dict(state.resuming)
    pause: list[str] = []
    resume: list[str] = list(again)
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
        since = paused.get(zone.zone_id)
        if since is not None and zone.learning is True and now - since >= config.check_s:
            # The pause did not take, or the user switched learning back on: not ours now.
            paused.pop(zone.zone_id)
            since = None
        last = toggles.get(zone.zone_id)
        settled = last is None or now - last >= config.min_pause_s
        resuming_now = zone.zone_id in resuming
        if reasons and since is None and not resuming_now and zone.learning is True and settled:
            pause.append(zone.zone_id)
            paused[zone.zone_id] = now
            toggles[zone.zone_id] = now
        elif (
            not reasons
            and since is not None
            and settled
            and (flow_recovered or now - since >= config.max_pause_s)
        ):
            if zone.learning is not True:
                resume.append(zone.zone_id)
                resuming[zone.zone_id] = now
            paused.pop(zone.zone_id, None)
            toggles[zone.zone_id] = now
    return LearningPlan(
        LearningState(paused, setpoints, toggles, resuming), tuple(pause), tuple(resume), causes
    )


def release_all(state: LearningState, now: float) -> tuple[LearningState, tuple[str, ...]]:
    """Resume every zone the plugin paused (control switched off, unload, hand-back); each is
    followed until its flag reads on.

    A release is a toggle too: a zone is not paused again sooner than the minimum pause."""
    toggles = dict(state.last_toggle)
    toggles.update(dict.fromkeys(state.paused, now))
    resuming = {**state.resuming, **dict.fromkeys(state.paused, now)}
    return LearningState({}, state.setpoints, toggles, resuming), tuple(state.paused)
