"""Decision 3: the recognition period, each zone's grace, and every zone unknown.

The zones report one by one after a start, and VT shows a placeholder while it starts a
thermostat — "off", before its first refresh neither ``is_ready`` nor the rest of its state
(observed with VT 10.4.0, 2026-09-28), kept for good while none of its devices reports (check C,
2026-10-06) — so nothing VT shows then is taken for an answer, nor after the recognition period:

- **The recognition period** runs from the control unit's start (Home Assistant starting, the
  entry reloading), and again whenever every configured zone stops answering at once — all of
  them answered at the step before (VT reloading). No new decision is taken until every
  configured zone has reported since it began — VT shows it started, and its mode and data are
  known — or for at most ``RECOGNITION_S``, and never before Home Assistant runs.
- **The grace:** a zone that stops answering after it answered — unknown, or showing again that
  VT has not started it (a thermostat's reload) — keeps its last answer for ``GRACE_S``; then it
  drops out and the known zones decide. A zone that never answered has no last answer; one still
  not answering when the recognition period ends drops out at once. Nothing of it is stored: the
  recognition period covers restarts.
- **Every zone unknown:** since when no configured zone is known, for the repair issue that
  follows after ``NO_ZONE_ISSUE_S`` (every mode, the monitor only included).
- **No criterion judged** (PB-03, decision 3 of 0.2.3): since when the zones are known but no
  configured demand criterion can be judged — the same end state, and the same repair issue
  after ``NO_ZONE_ISSUE_S``, naming the criterion. The controller follows it after the demand.

A fact about the zones, not the session: it is followed at every step, whatever holds control,
and switching control off and on does not start it again.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .readings import ZoneState

RECOGNITION_S = 600.0  # decided: at most ten minutes (decision 3)
GRACE_S = 600.0  # decided: ten minutes (decision 3)
NO_ZONE_ISSUE_S = 600.0  # every zone unknown this long: the repair issue (decision 3)


@dataclass(frozen=True, slots=True)
class ZoneWatch:
    begun: bool = False  # the first step has been seen: the recognition period began then
    recognition_since: float | None = None  # the running recognition period began; None: none
    reported: frozenset[str] = frozenset()  # zones that reported since it began
    last: Mapping[str, ZoneState] = field(default_factory=dict)  # each zone's last answer
    lost_at: Mapping[str, float] = field(default_factory=dict)  # a zone in its grace: since
    all_answering: bool = False  # at the last step, every configured zone answered
    unknown_since: float | None = None  # every configured zone unknown since then
    unjudged_since: float | None = None  # zones known, no configured criterion judged since then


def in_recognition(watch: ZoneWatch) -> bool:
    """The recognition period runs, or the unit has just started and seen no step yet."""
    return not watch.begun or watch.recognition_since is not None


def graced(watch: ZoneWatch) -> dict[str, ZoneState]:
    """The last answer of each zone in its grace period: it stands for the zone in demand."""
    return {zone_id: watch.last[zone_id] for zone_id in watch.lost_at if zone_id in watch.last}


def no_zone_issue_due(watch: ZoneWatch, now: float) -> bool:
    """Every configured zone has been unknown for ``NO_ZONE_ISSUE_S``: the repair issue."""
    return issue_due(watch.unknown_since, now)


def criteria_issue_due(watch: ZoneWatch, now: float) -> bool:
    """No configured criterion judged, the zones known, for ``NO_ZONE_ISSUE_S`` (PB-03)."""
    return issue_due(watch.unjudged_since, now)


def unjudged_since(previous: float | None, unjudged: bool, now: float) -> float | None:
    """Since when no configured criterion can be judged while zones are known (``None``: one
    can, or no zone is known)."""
    if not unjudged:
        return None
    return now if previous is None else _not_after(previous, now)


def issue_due(unknown_since: float | None, now: float) -> bool:
    """Every configured zone unknown since ``unknown_since``, for ``NO_ZONE_ISSUE_S``."""
    return unknown_since is not None and now - unknown_since >= NO_ZONE_ISSUE_S


def every_zone_unknown_since(
    previous: float | None,
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
) -> float | None:
    """Since when no configured zone is known (``None``: one is, or none is configured); the
    monitor follows it without a recognition period."""
    if not zones or any(zone.is_known(now, max_age) for zone in zones):
        return None
    return now if previous is None else _not_after(previous, now)


def _not_after(since: float, now: float) -> float:
    """A wait begun later than now means the wall clock was set back: it begins now (C9)."""
    return min(since, now)


def follow_zones(
    watch: ZoneWatch,
    zones: Sequence[ZoneState],
    now: float,
    max_age: float | None,
    *,
    starting: bool = False,
) -> ZoneWatch:
    """The watch after a step that saw ``zones`` — every configured zone — at ``now``.
    ``starting``: Home Assistant is starting, so the recognition period cannot end yet."""
    ids = [zone.zone_id for zone in zones]
    answering = {zone.zone_id: zone for zone in zones if zone.has_reported(now, max_age)}
    since = watch.recognition_since
    reported = watch.reported
    if not watch.begun:
        since, reported = now, frozenset()
    elif since is None and ids and not answering and watch.all_answering:
        since, reported = now, frozenset()  # every zone stopped answering at once: VT reloads
    ended = False
    if since is not None:
        since = _not_after(since, now)
        reported = reported | answering.keys()
        done = all(zone_id in reported for zone_id in ids) or now - since >= RECOGNITION_S
        if done and not starting:
            since, reported, ended = None, frozenset(), True
    last = {zone_id: state for zone_id, state in watch.last.items() if zone_id in ids}
    lost_at: dict[str, float] = {}
    for zone_id in ids:
        if zone_id in answering:
            last[zone_id] = answering[zone_id]
            continue
        if zone_id not in last:
            continue  # never answered: no last answer, no grace
        lost = _not_after(watch.lost_at.get(zone_id, now), now)
        if ended or now - lost >= GRACE_S:
            del last[zone_id]  # dropped out: the known zones decide
        else:
            lost_at[zone_id] = lost
    unknown_since = every_zone_unknown_since(watch.unknown_since, zones, now, max_age)
    return ZoneWatch(
        begun=True,
        recognition_since=since,
        reported=reported,
        last=last,
        lost_at=lost_at,
        all_answering=bool(ids) and len(answering) == len(ids),
        unknown_since=unknown_since,
        unjudged_since=watch.unjudged_since,  # the controller follows it after the demand
    )
