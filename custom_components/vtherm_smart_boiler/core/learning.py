"""Learning pauses: keep the zone algorithms from learning what the boiler did to the rooms.

A zone's learning is paused while DHW runs and its valve is open (no hot water reaches it) — every
draw, however short and on a combi boiler too, as the zone gets no heat meanwhile (S-41) — while
foreign heat warms it, and while the water temperature swings widely. Each pause keeps its causes
(P-89). It resumes once every cause is gone and the minimum pause has passed; after hot water the
flow must also be back within a tolerance of its setpoint — or heating be off — at the latest an
hour after the draw ended (the anchor provisional, K4). After foreign heat or a swing no flow
condition applies. A pause whose causes are not known (stored by an earlier version) is taken for
hot water: the cautious rule.

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
    max_pause_s: float = 60 * MINUTE  # ...or this long since the draw ended (provisional, K4)
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
    # ...and when it was first sent: a zone is followed for ``give_up_s`` from then at most.
    resume_since: Mapping[str, float] = field(default_factory=dict)
    # The causes each running pause has seen (P-89); a paused zone without an entry: unknown,
    # taken for hot water.
    causes: Mapping[str, tuple[PauseCause, ...]] = field(default_factory=dict)
    # A paused zone whose hot water has ended: since when — its flow wait is capped from then.
    dhw_ended: Mapping[str, float] = field(default_factory=dict)


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
    ``check_s`` while it reads off; no longer followed ``give_up_s`` after the first resume —
    one that never takes (the user may have switched learning off on purpose), or a zone gone
    (another zone, or the algorithm replaced). A zone not seen is not sent again: once it is
    back, its flag decides. Returns the zones to resume again now."""
    resuming = dict(state.resuming)
    # A resume stored without its start (by 0.2.1) counts from its last send.
    since = {zone_id: state.resume_since.get(zone_id, sent) for zone_id, sent in resuming.items()}
    again: list[str] = []
    for zone_id, sent_at in state.resuming.items():
        flag = flags.get(zone_id)
        if flag is True or now - since[zone_id] >= config.give_up_s:
            resuming.pop(zone_id)
            since.pop(zone_id)
        elif flag is False and now - sent_at >= config.check_s:
            again.append(zone_id)
            resuming[zone_id] = now
    return replace(state, resuming=resuming, resume_since=since), tuple(again)


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
    resume_since = dict(state.resume_since)
    kept = {z: c for z, c in state.causes.items() if z in paused}
    ended = {z: t for z, t in state.dhw_ended.items() if z in paused}
    pause: list[str] = []
    resume: list[str] = list(again)
    causes: dict[str, tuple[PauseCause, ...]] = {}
    for zone in zones:
        zone_id = zone.zone_id
        reasons: list[PauseCause] = []
        if config.pause_on_dhw and dhw is True and zone.valve_open:
            reasons.append(PauseCause.DHW)
        if config.pause_on_foreign_heat and zone.foreign_heat:
            reasons.append(PauseCause.FOREIGN_HEAT)
        if swing:
            reasons.append(PauseCause.WATER_SWING)
        causes[zone_id] = tuple(reasons)
        since = paused.get(zone_id)
        if since is not None and zone.learning is True and now - since >= config.check_s:
            # The pause did not take, or the user switched learning back on: not ours now.
            paused.pop(zone_id)
            kept.pop(zone_id, None)
            ended.pop(zone_id, None)
            since = None
        if since is not None:
            # Every cause the pause has seen; unknown ones (an earlier version's store) are
            # taken for hot water. The flow wait after hot water is capped from its end.
            seen = kept.get(zone_id) or (PauseCause.DHW,)
            kept[zone_id] = (*seen, *(r for r in reasons if r not in seen))
            if PauseCause.DHW in reasons:
                ended.pop(zone_id, None)
            elif PauseCause.DHW in kept[zone_id]:
                ended[zone_id] = min(ended.get(zone_id, now), now)
        last = toggles.get(zone_id)
        settled = last is None or now - last >= config.min_pause_s
        resuming_now = zone_id in resuming
        if reasons and since is None and not resuming_now and zone.learning is True and settled:
            pause.append(zone_id)
            paused[zone_id] = now
            toggles[zone_id] = now
            kept[zone_id] = tuple(reasons)
        elif (
            not reasons
            and since is not None
            and settled
            and _may_resume(kept[zone_id], ended.get(zone_id), flow_recovered, now, config)
        ):
            if zone.learning is not True:
                resume.append(zone_id)
                resuming[zone_id] = now
                resume_since.setdefault(zone_id, now)
            paused.pop(zone_id, None)
            kept.pop(zone_id, None)
            ended.pop(zone_id, None)
            toggles[zone_id] = now
    return LearningPlan(
        LearningState(paused, setpoints, toggles, resuming, resume_since, kept, ended),
        tuple(pause),
        tuple(resume),
        causes,
    )


def _may_resume(
    causes: Sequence[PauseCause],
    dhw_ended: float | None,
    flow_recovered: bool,
    now: float,
    config: LearningConfig,
) -> bool:
    """A pause whose causes are gone and whose minimum pause has passed ends — after hot water
    only once the flow is back (or heating is off), at the latest ``max_pause_s`` after the draw
    ended; after foreign heat or a swing at once (P-89)."""
    if PauseCause.DHW not in causes:
        return True
    return flow_recovered or (dhw_ended is not None and now - dhw_ended >= config.max_pause_s)


def release_all(state: LearningState, now: float) -> tuple[LearningState, tuple[str, ...]]:
    """Resume every zone the plugin paused (control switched off, unload, hand-back); each is
    followed until its flag reads on.

    A release is a toggle too: a zone is not paused again sooner than the minimum pause."""
    toggles = dict(state.last_toggle)
    toggles.update(dict.fromkeys(state.paused, now))
    resuming = {**state.resuming, **dict.fromkeys(state.paused, now)}
    since = {**dict.fromkeys(state.paused, now), **state.resume_since}
    released = LearningState({}, state.setpoints, toggles, resuming, since)  # causes forgotten
    return released, tuple(state.paused)
