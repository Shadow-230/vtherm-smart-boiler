"""Learning pauses: keep the zone algorithms from learning what the boiler did to the rooms.

A zone's learning is paused while DHW runs, or control sends its "off" for a boiler fault, and its
valve is open (no heat reaches it) — every draw, however short and on a combi boiler too, as the
zone gets no heat meanwhile (S-41; the fault: decision 14) — while foreign heat warms it, and
while the water temperature swings widely. Each pause keeps its causes (P-89). It resumes once
every cause is gone and the minimum pause has passed; after hot water or a fault the flow must
also be back within a tolerance of its setpoint — or heating be off. After foreign heat or a
swing no flow condition applies. A pause whose causes are not known (stored by an earlier
version) is taken for hot water: the cautious rule.

A pause ends at the latest an hour after it began, even while its cause lasts (decision 14;
provisional, K4): the causes then on — the draw, the fault "off", foreign heat, the swing — pause
the zone again only once their signal has read off; a draw or fault signal unknown meanwhile is
taken for the same one. That is not stored: after a restart a cause still on pauses once more.

The plugin only resumes what it paused itself and never touches a zone whose learning the user
has switched off. Every toggle costs the zone algorithm its observation in progress, so the
plugin does not toggle faster than the minimum pause — except that a draw or a fault "off"
pauses a zone even within it after the plugin's own resume (decision 14). Not after a pause that
did not take, nor after a release: the plugin never fights the user, nor toggles with a control
switched off and on.

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
    BOILER_FAULT = "boiler_fault"  # control's "off" for a boiler fault (decision 14)


# The calling zones get no heat: these pause even within the minimum pause after the plugin's
# own resume, and after them the flow must come back first (S-41, decision 14).
NO_HEAT = frozenset({PauseCause.DHW, PauseCause.BOILER_FAULT})


@dataclass(frozen=True, slots=True)
class LearningConfig:
    pause_on_dhw: bool = True
    pause_on_foreign_heat: bool = True
    pause_on_water_swing: bool = True
    pause_on_fault: bool = True
    swing_k: float = 5.0  # setpoint change within the window that counts as a swing
    swing_window_s: float = 30 * MINUTE
    min_pause_s: float = 10 * MINUTE
    # After hot water or a fault, the flow must be back within this of its setpoint...
    resume_margin_k: float = 3.0
    # ...and a pause ends this long after it began, even while its cause lasts (decision 14;
    # provisional, K4).
    max_pause_s: float = 60 * MINUTE
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
    # Resumes given up a day after the first one (Y4): since when; shown until the zone's flag
    # reads on again or the plugin pauses it again.
    given_up: Mapping[str, float] = field(default_factory=dict)
    # Zones the plugin resumed within the minimum pause, since when: a draw or a fault "off"
    # pauses them again at once (decision 14). Not stored.
    resumed: Mapping[str, float] = field(default_factory=dict)
    # The causes a pause's hour outlasted, per zone: they pause it again only once their signal
    # has read off (decision 14). Not stored.
    outlasted: Mapping[str, tuple[PauseCause, ...]] = field(default_factory=dict)


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
    # A zone given up whose flag reads on again — switched back on, say by the user — is done.
    given_up = {z: t for z, t in state.given_up.items() if flags.get(z) is not True}
    again: list[str] = []
    for zone_id, sent_at in state.resuming.items():
        flag = flags.get(zone_id)
        if flag is True or now - since[zone_id] >= config.give_up_s:
            resuming.pop(zone_id)
            since.pop(zone_id)
            if flag is not True:
                given_up[zone_id] = now  # Y4: recorded, to be told once and shown
        elif flag is False and now - sent_at >= config.check_s:
            again.append(zone_id)
            resuming[zone_id] = now
    followed = replace(state, resuming=resuming, resume_since=since, given_up=given_up)
    return followed, tuple(again)


def _signals(
    zone: ZoneLearning, dhw: bool | None, fault: bool | None, swing: bool, config: LearningConfig
) -> dict[PauseCause, bool | None]:
    """Each cause's signal for a zone, its valve aside: on, off, or unknown (``None``)."""
    return {
        PauseCause.DHW: dhw if config.pause_on_dhw else False,
        PauseCause.BOILER_FAULT: fault if config.pause_on_fault else False,
        PauseCause.FOREIGN_HEAT: config.pause_on_foreign_heat and zone.foreign_heat,
        PauseCause.WATER_SWING: swing,
    }


def plan_learning(
    state: LearningState,
    zones: Sequence[ZoneLearning],
    dhw: bool | None,
    flow: float | None,
    setpoint: float | None,
    now: float,
    config: LearningConfig,
    heating: bool | None = None,
    fault: bool | None = None,
) -> LearningPlan:
    """Which zones to pause and resume now. ``setpoint`` is the heating setpoint (not a low
    "off" value); ``heating`` whether the boiler is to heat now; ``fault`` whether control sends
    its "off" for a boiler fault (decision 14) — ``None``: unknown, which pauses nothing."""
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
    given_up = dict(state.given_up)
    resumed = {z: t for z, t in state.resumed.items() if 0.0 <= now - t < config.min_pause_s}
    outlasted = dict(state.outlasted)
    pause: list[str] = []
    resume: list[str] = list(again)
    causes: dict[str, tuple[PauseCause, ...]] = {}
    for zone in zones:
        zone_id = zone.zone_id
        signals = _signals(zone, dhw, fault, swing, config)
        reasons = tuple(
            cause
            for cause, on in signals.items()
            if on is True and (zone.valve_open or cause not in NO_HEAT)
        )
        causes[zone_id] = reasons
        # A cause the hour outlasted counts again once its signal has read off.
        lasting = tuple(c for c in outlasted.pop(zone_id, ()) if signals[c] is not False)
        if lasting:
            outlasted[zone_id] = lasting
        fresh = tuple(r for r in reasons if r not in lasting)
        since = paused.get(zone_id)
        if since is not None and zone.learning is True and now - since >= config.check_s:
            # The pause did not take, or the user switched learning back on: not ours now.
            paused.pop(zone_id)
            kept.pop(zone_id, None)
            since = None
        if since is not None:
            # Every cause the pause has seen; unknown ones (an earlier version's store) are
            # taken for hot water.
            seen = kept.get(zone_id) or (PauseCause.DHW,)
            kept[zone_id] = (*seen, *(r for r in fresh if r not in seen))
        last = toggles.get(zone_id)
        settled = last is None or now - last >= config.min_pause_s
        # A draw or a fault "off" right after the plugin's own resume: paused at once.
        no_heat = zone_id in resumed and any(r in NO_HEAT for r in fresh)
        if (
            fresh
            and since is None
            and zone_id not in resuming
            and zone.learning is True
            and (settled or no_heat)
        ):
            pause.append(zone_id)
            paused[zone_id] = now
            toggles[zone_id] = now
            kept[zone_id] = fresh
            given_up.pop(zone_id, None)  # a new pause: an earlier give-up is over
            resumed.pop(zone_id, None)
        elif (
            since is not None
            and settled
            and (
                now - since >= config.max_pause_s
                or (not fresh and _may_resume(kept[zone_id], flow_recovered))
            )
        ):
            if zone.learning is not True:
                resume.append(zone_id)
                resuming[zone_id] = now
                resume_since.setdefault(zone_id, now)
            on = tuple(c for c, value in signals.items() if value is True)
            if on and now - since >= config.max_pause_s:
                outlasted[zone_id] = on  # decision 14: the hour is up, the causes last
            paused.pop(zone_id, None)
            kept.pop(zone_id, None)
            toggles[zone_id] = now
            resumed[zone_id] = now
    return LearningPlan(
        LearningState(
            paused,
            setpoints,
            toggles,
            resuming,
            resume_since,
            kept,
            given_up,
            resumed,
            outlasted,
        ),
        tuple(pause),
        tuple(resume),
        causes,
    )


def _may_resume(causes: Sequence[PauseCause], flow_recovered: bool) -> bool:
    """A pause whose causes are gone and whose minimum pause has passed ends — after hot water
    or a fault only once the flow is back (or heating is off); after foreign heat or a swing at
    once (P-89). The hour since the pause began ends it whatever the flow (decision 14)."""
    return flow_recovered or not any(cause in NO_HEAT for cause in causes)


def release_all(state: LearningState, now: float) -> tuple[LearningState, tuple[str, ...]]:
    """Resume every zone the plugin paused (control switched off, unload, hand-back); each is
    followed until its flag reads on.

    A release is a toggle too: a zone is not paused again sooner than the minimum pause, not
    even by a draw — control switched off and on must not toggle it (decision 14). What an
    hour outlasted stays: control off sees no signal read off."""
    toggles = dict(state.last_toggle)
    toggles.update(dict.fromkeys(state.paused, now))
    resuming = {**state.resuming, **dict.fromkeys(state.paused, now)}
    since = {**dict.fromkeys(state.paused, now), **state.resume_since}
    # The causes are forgotten; what was given up stays shown.
    released = LearningState(
        {},
        state.setpoints,
        toggles,
        resuming,
        since,
        given_up=state.given_up,
        resumed=state.resumed,
        outlasted=state.outlasted,
    )
    return released, tuple(state.paused)


def rename_zone(state: LearningState, old: str, new: str) -> LearningState:
    """The state with a zone renamed (P-19: its VT climate got another entity ID): what the
    plugin holds for it — its pause, its resume, their causes and times — follows it. The same
    state where the zone is not in it."""

    def moved[T](values: Mapping[str, T]) -> dict[str, T]:
        return {(new if zone == old else zone): value for zone, value in values.items()}

    keyed = (
        state.paused,
        state.last_toggle,
        state.resuming,
        state.resume_since,
        state.causes,
        state.given_up,
        state.resumed,
        state.outlasted,
    )
    if not any(old in values for values in keyed):
        return state
    return replace(
        state,
        paused=moved(state.paused),
        last_toggle=moved(state.last_toggle),
        resuming=moved(state.resuming),
        resume_since=moved(state.resume_since),
        causes=moved(state.causes),
        given_up=moved(state.given_up),
        resumed=moved(state.resumed),
        outlasted=moved(state.outlasted),
    )
