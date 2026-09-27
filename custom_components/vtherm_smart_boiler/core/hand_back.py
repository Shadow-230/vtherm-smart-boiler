"""The hand-back's evidence: what shows a release, when a steady third value means another
controller holds a target, and when a two-valued target's change is a lost command.

The safe hand-back (``SCOPE.md`` §5; the user's decision of 2026-09-26/27) writes the lowest water
temperature first, then heating on where the boiler returns to a thermostat or its own control,
then the release — one part after another at once, waiting for no read-back. Only the
confirmation waits for the read-back, and what counts as a release depends on the target:

- a held value target (the device keeps the last value it was given: ESPHome, DIYLess and the
  like): only the hand-back value, read back within half a kelvin;
- an expiring value target, or a gateway: the hand-back value (``CS=0`` read back as 0), or a
  value more than half a kelvin from both the plugin's last value and the lowest just written —
  the device's own value, back once the override lapsed;
- the timeout method: the read-back back at the session's baseline (the value from before the
  plugin); with that unknown, a value away from both the plugin's last value and the lowest;
- a two-valued target (the heating switch, the external-control switch): its hand-back state.

Where the plugin's last value is unknown, a value away from the lowest counts only once it was
reported after the command. A read-back without a value never shows a release.

Another controller (decision "Safe hand-back", W3, W6): a held value target whose read-back shows
the same third value — neither the plugin's, nor the lowest, nor the hand-back value — at two
retry checks a minute apart (three over two minutes with hot water unknown; no judgement during a
draw or for two minutes after it) is held by another controller: the hand-back counts as done
there and is not retried. A two-valued target counts as held by another once its hand-back
state was read back and then changed with no trace of an outage; with a trace, the command was
lost and is written again. All values provisional (K4).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

RELEASE_TOLERANCE_K = 0.5  # a read-back within this of a value shows it
HELD_UNCONFIRMED_S = 10.0  # a held target not released this long after its release: an alarm
TIMEOUT_RELEASE_S = 180.0  # a timeout hand-back not released this long after it: an alarm
FOREIGN_CHECKS = 2  # retry checks, a minute apart, showing the same third value
FOREIGN_CHECKS_DHW_UNKNOWN = 3  # the same with hot water unknown: over two minutes
DHW_QUIET_S = 120.0  # no judgement during a hot-water draw or this long after it (W6)
OUTAGE_WINDOW_S = 300.0  # an outage this recent makes a two-valued change a lost command (X1's)
UNAVAILABLE_STATES = frozenset({"unavailable", "unknown"})


class CheckKind(StrEnum):
    """How a target shows that the hand-back reached it."""

    VALUE = "value"  # a held value target: the hand-back value
    LEAVES_VALUE = "leaves_value"  # an expiring value target, or a gateway
    BACK_TO_BASELINE = "back_to_baseline"  # the timeout method
    SWITCH = "switch"  # a two-valued target: its hand-back state


class CheckSource(StrEnum):
    """Where the evidence comes from."""

    SEPARATE = "separate"  # a read-back apart from the written entity: it confirms
    SELF = "self"  # the written entity itself: the same check, shown unverified
    ASSUMED = "assumed"  # an entity with ``assumed_state``: no check, done once written


class HandBackConfirmation(StrEnum):
    """Where the last hand-back stands, as shown."""

    CONFIRMED = "confirmed"
    CONFIRMED_BY_GATEWAY = "confirmed_by_gateway"
    UNVERIFIED = "unverified"
    WAITING = "waiting"
    NOT_CONFIRMED = "not_confirmed"
    TAKEN_BY_OTHER = "taken_by_other"


class SwitchVerdict(StrEnum):
    RELEASED = "released"  # it shows its hand-back state
    WAITING = "waiting"  # not shown yet: owed, and retried
    LOST = "lost"  # it left that state with a trace of an outage: written again
    TAKEN = "taken"  # it left that state with no trace: another controller holds it


@dataclass(frozen=True, slots=True)
class ReleaseRule:
    """What a value target's release is judged against (``None``: not known)."""

    kind: CheckKind
    expected: float | None = None  # the hand-back value; 0 on a gateway (``CS=0``)
    release_from: float | None = None  # the plugin's last value
    lowest: float | None = None  # the lowest water temperature the hand-back wrote first
    baseline: float | None = None  # the value from before the session (the timeout method)


def _near(value: float, other: float | None, tolerance: float) -> bool:
    return other is not None and abs(value - other) <= tolerance


def _away_from_ours(
    rule: ReleaseRule, read_back: float, reported_after: bool, tolerance: float
) -> bool:
    """More than ``tolerance`` from the lowest and from the plugin's last value; that value
    unknown, reported after the command instead."""
    if _near(read_back, rule.lowest, tolerance):
        return False
    if rule.release_from is None:
        return reported_after
    return not _near(read_back, rule.release_from, tolerance)


def released(
    rule: ReleaseRule,
    read_back: float | None,
    reported_after: bool,
    tolerance: float = RELEASE_TOLERANCE_K,
) -> bool:
    """Whether a value target's read-back shows its release. ``reported_after``: the read-back
    reported something after the hand-back's command."""
    if read_back is None:
        return False
    if rule.kind is CheckKind.VALUE:
        return _near(read_back, rule.expected, tolerance)
    if rule.kind is CheckKind.BACK_TO_BASELINE:
        if rule.baseline is not None:
            return _near(read_back, rule.baseline, tolerance)
        return _away_from_ours(rule, read_back, reported_after, tolerance)
    if rule.kind is CheckKind.LEAVES_VALUE:
        return _near(read_back, rule.expected, tolerance) or _away_from_ours(
            rule, read_back, reported_after, tolerance
        )
    return False


def third_value(
    rule: ReleaseRule, read_back: float | None, tolerance: float = RELEASE_TOLERANCE_K
) -> bool:
    """A read-back that holds neither the plugin's last value, nor the lowest, nor the hand-back
    value: someone else's, or the boiler's during a hot-water draw."""
    if read_back is None:
        return False
    return not any(
        _near(read_back, value, tolerance)
        for value in (rule.release_from, rule.lowest, rule.expected)
    )


@dataclass(frozen=True, slots=True)
class ForeignWatch:
    """A third value a held target's read-back holds at consecutive retry checks."""

    value: float
    checks: int = 1
    dhw_unknown: bool = False  # hot water was unknown at one of them: three checks needed


def watch_foreign(
    watch: ForeignWatch | None,
    read_back: float | None,
    third: bool,
    dhw: bool | None,
    dhw_recent: bool,
    tolerance: float = RELEASE_TOLERANCE_K,
) -> tuple[ForeignWatch | None, bool]:
    """One retry check of a held value target: the watch after it, and whether another
    controller holds the target. ``third``: the read-back holds a third value; ``dhw``: hot water
    now (``None``: unknown); ``dhw_recent``: a draw within ``DHW_QUIET_S``, which gives no
    judgement (W6)."""
    if not third or read_back is None or dhw is True or dhw_recent:
        return None, False
    if watch is None or not _near(read_back, watch.value, tolerance):
        watch = ForeignWatch(read_back, 1, dhw is None)
    else:
        watch = ForeignWatch(watch.value, watch.checks + 1, watch.dhw_unknown or dhw is None)
    needed = FOREIGN_CHECKS_DHW_UNKNOWN if watch.dhw_unknown else FOREIGN_CHECKS
    return watch, watch.checks >= needed


def judge_switch(state: str | None, expected: str, seen: bool, trace: bool) -> SwitchVerdict:
    """A two-valued target: released in its hand-back state. Once it was read back in that
    state, another known state means another controller — or, with a trace of an outage, a lost
    command. Before that, or without a known state, it stays owed."""
    if state == expected:
        return SwitchVerdict.RELEASED
    if not seen or state not in ("on", "off"):
        return SwitchVerdict.WAITING
    return SwitchVerdict.LOST if trace else SwitchVerdict.TAKEN


class RestartKind(StrEnum):
    """What an optional restart indicator shows (Q3.7)."""

    UPTIME = "uptime"  # a duration since the start: a restart makes it fall
    COUNTER = "counter"  # a restart count: a restart makes it go up (a reset, down)
    BOOT_TIME = "boot_time"  # the moment of the last start: a restart moves it


def restart_seen(before: float | None, after: float | None, kind: RestartKind) -> bool:
    """Whether a restart indicator's change from ``before`` to ``after`` shows a restart — a
    trace of an outage, where the device's entities may never have gone unavailable (the OTGW
    firmware over MQTT, EMS-ESP; Q3.7). A value not known shows nothing: its being unavailable or
    unknown is a trace of its own."""
    if before is None or after is None:
        return False
    if kind is RestartKind.UPTIME:
        return after < before
    return after != before


def outage_seen(
    outages: Mapping[str, float],
    entities: Iterable[str],
    now: float,
    window: float = OUTAGE_WINDOW_S,
) -> bool:
    """Whether one of ``entities`` was unavailable, unknown or missing within ``window`` before
    ``now`` (``outages``: when each was last seen so). One seen later than now — the wall clock
    set back — counts."""
    return any(now - outages[entity] <= window for entity in entities if entity in outages)


@dataclass(frozen=True, slots=True)
class TargetView:
    released: bool
    taken: bool
    source: CheckSource


def shown(
    targets: Sequence[TargetView], gateway: bool, failing: bool
) -> HandBackConfirmation | None:
    """Where the hand-back stands for the user, by its weakest target: still owed (sent again
    every minute once ``failing``), then taken by another controller, then unverified (only the
    written entity, or an optimistic one, shows it), else confirmed — by the gateway on a
    gateway path. ``None`` without a hand-back."""
    if not targets:
        return None
    if any(not t.released and not t.taken for t in targets):
        return HandBackConfirmation.NOT_CONFIRMED if failing else HandBackConfirmation.WAITING
    if any(t.taken for t in targets):
        return HandBackConfirmation.TAKEN_BY_OTHER
    if any(t.source is not CheckSource.SEPARATE for t in targets):
        return HandBackConfirmation.UNVERIFIED
    if gateway:
        return HandBackConfirmation.CONFIRMED_BY_GATEWAY
    return HandBackConfirmation.CONFIRMED
