"""Automatic freshness limits (I6, decision 9): a limit only for a source seen to repeat itself.

A freshness limit judges a value stale when its source has not reported it for that long. Many
sources report a value only when it changes (MQTT, ESPHome without ``force_update``): a flame that
stays off all night, or a flow temperature that does not move, would read stale though nothing is
wrong — and a stale flame or flow stops control and hands the boiler back, where nothing may ever
change again. So no limit is assumed: a source earns one only once it has been seen reporting an
unchanged value again — a heartbeat — at least ``HEARTBEATS_NEEDED`` times. A heartbeat is a report
with nothing changed since the last report seen — by the source's own change time, never by the
value alone: looked at every so often, a value that changed and changed back in between would
look repeated. Its limit is then
``RHYTHM_FACTOR`` times the median gap between those heartbeats, never below the floor nor above
the cap the caller gives. A changed value is a report, never proof of a rhythm: a flow that moves
every few seconds while the burner runs may still stand still for hours in summer.

What is seen is kept for the run only: after a restart a source earns its limit again.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

HEARTBEATS_NEEDED = 2
RHYTHM_FACTOR = 5.0
KEPT_GAPS = 8  # the newest heartbeat gaps the median is taken over


@dataclass(frozen=True, slots=True)
class Rhythm:
    """What has been seen of one source: its last report, the value it carried, and the gaps
    between its heartbeats, newest last."""

    reported_at: float | None = None
    value: object = None
    gaps: tuple[float, ...] = ()

    @property
    def heartbeats(self) -> int:
        return len(self.gaps)


def observe(
    rhythm: Rhythm, reported_at: float | None, value: object, changed_at: float | None
) -> Rhythm:
    """One look at a source. A report later than the last one seen, carrying the same known
    value and nothing changed since that one (``changed_at`` not after it), is a heartbeat: its
    gap is kept. Any other report — a changed value, an unknown one, one without its change
    time — is remembered and proves nothing. No report, or none newer, changes nothing."""
    if reported_at is None:
        return rhythm
    if rhythm.reported_at is None:
        return Rhythm(reported_at, value, rhythm.gaps)
    if reported_at <= rhythm.reported_at:
        return rhythm
    unchanged = changed_at is not None and changed_at <= rhythm.reported_at
    if unchanged and value is not None and value == rhythm.value:
        gaps = (*rhythm.gaps, reported_at - rhythm.reported_at)[-KEPT_GAPS:]
        return Rhythm(reported_at, value, gaps)
    return Rhythm(reported_at, value, rhythm.gaps)


def automatic_limit(rhythm: Rhythm, floor_s: float, cap_s: float) -> float | None:
    """The limit a source has earned: ``None`` before ``HEARTBEATS_NEEDED`` heartbeats; then
    ``RHYTHM_FACTOR`` times their median gap, within ``floor_s`` and ``cap_s``."""
    if rhythm.heartbeats < HEARTBEATS_NEEDED:
        return None
    return min(cap_s, max(floor_s, RHYTHM_FACTOR * median(rhythm.gaps)))
