"""Write guards: what may actually be written, whatever the controller asks for.

One guard per write target — the flow setpoint, and heating on/off as 1 and 0. The guards are
fixed; their values are options:

- nothing goes to the boiler's persistent memory: a target declared persistent, or of unknown
  write type, is never written (the configuration keeps control off for it anyway);
- how often it is written follows the write type: an expiring override is repeated every
  keep-alive period; a value the device holds, on change only;
- a write-rate guard against a runaway loop: a write repeated within one control step waits for
  the next one — failed attempts count too, and nothing waits longer;
- every write is read back where something echoes it (a target without an echo is never judged,
  only shown unverified): not confirmed within the timeout → reported as ignored, never assumed
  applied; changed from outside after it was confirmed → written again once, then blocked and
  reported, also when that one rewrite is not confirmed within the timeout (whatever was reported
  before it); a further outside change within a day of the rewrite is not rewritten, whatever the
  plugin wrote in between — the plugin does not fight another controller;
- a value never confirmed while the read-back shows another steady value from its sending on —
  another controller still writing — counts as changed from outside (the user's decision,
  2026-09-25); the read-back showing our previous value is only "ignored";
- a write that failed is sent again at the next step; a mismatch it explains is not taken for
  another controller. Nor is a read-back that falls back to the value from before the session —
  the override dropped: a boiler's Data-Invalid answer clears an OTGW's override, a gateway reset
  loses it — nor an expiring override that lapsed because the plugin itself went silent (stale
  data): both are simply sent again, and a drop that keeps coming back is reported as ignored.
  Heating on/off has only two values, so its fall back cannot be told from another controller:
  any change after a confirmation counts as changed from outside.

Keep-alive repeats of an expiring override are not rewrites. Heating on/off follows what the
controller asks at once: nothing counted or timed holds it against VT (``SCOPE.md`` principle 12)
beyond the one-step write-rate guard.

A hand-back write is not planned here: nothing holds it back.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

DAY = 86400.0
REWRITE_WINDOW_S = DAY  # after the one rewrite, further outside changes this soon are not fought
# Writes to one target at least this far apart: one per control step (10 s), whatever the
# timer's jitter or a step run early (switching control on).
MIN_WRITE_INTERVAL_S = 5.0


class WriteType(StrEnum):
    EXPIRING = "expiring"  # an override that lapses unless repeated
    PERSISTENT = "persistent"  # stored in the boiler's memory: every write wears it; never written
    HELD = "held"  # kept by the gateway and sent on by itself: no repeat, no wear
    UNKNOWN = "unknown"  # may be persistent: never written


class WriteKind(StrEnum):
    CHANGE = "change"
    KEEPALIVE = "keepalive"
    REWRITE = "rewrite"
    RESEND = "resend"  # the same value again: after a failed write, a drop or a lapse


class GuardEvent(StrEnum):
    IGNORED = "ignored"
    OUTSIDE_CHANGE = "outside_change"


class Confirmation(StrEnum):
    """Where the value last written stands with the device."""

    CONFIRMED = "confirmed"
    WAITING = "waiting"  # sent, not confirmed yet
    NOT_CONFIRMED = "not_confirmed"  # not confirmed within the timeout: reported as ignored
    CHANGED_FROM_OUTSIDE = "changed_from_outside"  # another controller: writes stopped
    UNVERIFIED = "unverified"  # nothing echoes the value


@dataclass(frozen=True, slots=True)
class GuardConfig:
    write_type: WriteType = WriteType.UNKNOWN
    keepalive_s: float = 30.0
    confirm_timeout_s: float = 120.0
    tolerance: float = 0.5  # on/off as 1 and 0: any tolerance below 1
    min_interval_s: float = MIN_WRITE_INTERVAL_S
    read_back: bool = True  # False: nothing echoes the value; it is never judged
    two_valued: bool = False  # on/off: a fall back to the value before the session is no drop

    def __post_init__(self) -> None:
        if self.keepalive_s <= 0 or self.confirm_timeout_s <= 0:
            raise ValueError("keep-alive and confirmation timeout must be positive")
        if not 0 < self.min_interval_s < self.keepalive_s:
            raise ValueError("the write interval must be positive and below the keep-alive")
        if self.tolerance < 0:
            raise ValueError("the tolerance must not be negative")

    @property
    def writable(self) -> bool:
        """Only values that expire or that the device holds; nothing the boiler stores."""
        return self.write_type in (WriteType.EXPIRING, WriteType.HELD)


@dataclass(frozen=True, slots=True)
class GuardState:
    written: float | None = None
    written_at: float | None = None  # the last write attempt, failed ones included
    sent_at: float | None = None  # when the current value was last sent (keep-alives aside)
    confirmed_at: float | None = None  # when the device confirmed the current value
    previous: float | None = None  # the value written before the current one
    baseline: float | None = None  # the read-back before the session's first write
    foreign: float | None = None  # another value the read-back holds since the send
    dropped_at: float | None = None  # when the read-back last fell back to the baseline
    rewritten_at: float | None = None  # when the one rewrite after an outside change was sent
    ignored_reported: bool = False
    blocked: GuardEvent | None = None  # no more writes until the guard is reset
    retry: bool = False  # the last write failed: send it again


@dataclass(frozen=True, slots=True)
class WriteAction:
    value: float
    kind: WriteKind


@dataclass(frozen=True, slots=True)
class GuardResult:
    state: GuardState
    action: WriteAction | None = None
    events: tuple[GuardEvent, ...] = ()


def _matches(a: float | None, b: float | None, tolerance: float) -> bool:
    return a is not None and b is not None and abs(a - b) <= tolerance


def write_failed(state: GuardState) -> GuardState:
    """The planned write did not go through: it is sent again at the next step. The attempt
    still counts for the write-rate guard."""
    return replace(state, retry=True)


def confirmation(state: GuardState, config: GuardConfig) -> Confirmation | None:
    """Where the value last written stands; ``None`` before the first write."""
    if state.blocked is not None:
        return Confirmation.CHANGED_FROM_OUTSIDE
    if state.written is None:
        return None
    if not config.read_back:
        return Confirmation.UNVERIFIED
    if state.confirmed_at is not None:
        return Confirmation.CONFIRMED
    return Confirmation.NOT_CONFIRMED if state.ignored_reported else Confirmation.WAITING


def plan_write(
    state: GuardState,
    desired: float | None,
    confirmed: float | None,
    now: float,
    config: GuardConfig,
) -> GuardResult:
    """What to write to one target now, given what the device confirms (``None``: unknown)."""
    if not config.writable or state.blocked is not None:
        return GuardResult(state)
    if not config.read_back:
        confirmed = None  # nothing to judge: never ignored, never another controller
    state, verdict = _follow_read_back(state, confirmed, now, config)
    events: list[GuardEvent] = []
    if verdict is _Verdict.IGNORED:
        events.append(GuardEvent.IGNORED)
        state = replace(state, ignored_reported=True)
    elif verdict is _Verdict.REWRITE_FAILED:
        # The one rewrite did not hold: another controller keeps its value. Stop and report
        # rather than fight it.
        return _block(state, events)
    if desired is None:
        return GuardResult(state, None, tuple(events))
    if state.written is None:
        return _write(state, desired, WriteKind.CHANGE, confirmed, now, config, events)
    if state.retry:
        # Our own write failed: what the device shows says nothing about other controllers.
        kind = WriteKind.CHANGE if _differs(state, desired, config) else WriteKind.RESEND
        value = desired if kind is WriteKind.CHANGE else state.written
        return _write(state, value, kind, confirmed, now, config, events)
    if _mismatch(state, confirmed, config) and _lapsed(state, now, config):
        # We went silent (stale data) long enough for the override to lapse: not another
        # controller's doing.
        return _write(state, state.written, WriteKind.RESEND, confirmed, now, config, events)
    if verdict is _Verdict.FOREIGN or _changed_from_outside(state, confirmed, config):
        if state.rewritten_at is not None and now - state.rewritten_at < REWRITE_WINDOW_S:
            return _block(state, events)
        return _write(state, state.written, WriteKind.REWRITE, confirmed, now, config, events)
    if _dropped(state, confirmed, config):
        again = state.dropped_at is not None and now - state.dropped_at <= config.confirm_timeout_s
        if again and not state.ignored_reported:
            events.append(GuardEvent.IGNORED)  # it keeps falling back: the boiler rejects it
            state = replace(state, ignored_reported=True)
        state = replace(state, dropped_at=now)
        return _write(state, state.written, WriteKind.RESEND, confirmed, now, config, events)
    if _differs(state, desired, config):
        return _write(state, desired, WriteKind.CHANGE, confirmed, now, config, events)
    if (
        config.write_type is WriteType.EXPIRING
        and state.written_at is not None
        and now - state.written_at >= config.keepalive_s
    ):
        return _write(state, state.written, WriteKind.KEEPALIVE, confirmed, now, config, events)
    return GuardResult(state, None, tuple(events))


class _Verdict(StrEnum):
    NONE = "none"
    IGNORED = "ignored"  # not confirmed in time: report once, keep writing
    FOREIGN = "foreign"  # not confirmed in time, another steady value held: an outside change
    REWRITE_FAILED = "rewrite_failed"  # the one rewrite not confirmed in time: block


def _follow_read_back(
    state: GuardState,
    confirmed: float | None,
    now: float,
    config: GuardConfig,
) -> tuple[GuardState, _Verdict]:
    """Note a confirmation, follow another value the read-back holds, and judge a send the
    device has not confirmed within the timeout. An "ignored" report ends once the value has
    held for the timeout."""
    if not config.read_back or state.written is None or state.sent_at is None:
        return state, _Verdict.NONE
    if state.confirmed_at is not None:
        held = (
            state.ignored_reported
            and now - state.confirmed_at >= config.confirm_timeout_s
            and _matches(confirmed, state.written, config.tolerance)
        )
        return (replace(state, ignored_reported=False) if held else state), _Verdict.NONE
    if _matches(confirmed, state.written, config.tolerance):
        return replace(state, confirmed_at=now, foreign=None), _Verdict.NONE
    if confirmed is not None and not _matches(confirmed, state.foreign, config.tolerance):
        state = replace(state, foreign=None)  # the read-back moved: nothing steady
    if now - state.sent_at <= config.confirm_timeout_s:
        return state, _Verdict.NONE
    if state.rewritten_at is not None and state.sent_at == state.rewritten_at:
        return state, _Verdict.REWRITE_FAILED
    if _matches(confirmed, state.foreign, config.tolerance):
        return state, _Verdict.FOREIGN
    if state.ignored_reported:
        return state, _Verdict.NONE
    return state, _Verdict.IGNORED


def _differs(state: GuardState, desired: float, config: GuardConfig) -> bool:
    return not _matches(desired, state.written, config.tolerance)


def _mismatch(
    state: GuardState, confirmed: float | None, config: GuardConfig
) -> bool:
    """The device confirmed our value, and now shows another."""
    return (
        state.confirmed_at is not None
        and confirmed is not None
        and not _matches(confirmed, state.written, config.tolerance)
    )


def _dropped(
    state: GuardState, confirmed: float | None, config: GuardConfig
) -> bool:
    """The read-back fell back to its value from before the session: our override dropped."""
    return (
        not config.two_valued
        and _mismatch(state, confirmed, config)
        and _matches(confirmed, state.baseline, config.tolerance)
    )


def _changed_from_outside(
    state: GuardState, confirmed: float | None, config: GuardConfig
) -> bool:
    """Another value after ours was confirmed — not our dropped override, nor our own lapse."""
    return _mismatch(state, confirmed, config) and not _dropped(state, confirmed, config)


def _lapsed(state: GuardState, now: float, config: GuardConfig) -> bool:
    """An expiring override the plugin stopped repeating long enough for it to lapse."""
    return (
        config.write_type is WriteType.EXPIRING
        and state.written_at is not None
        and now - state.written_at > 2 * config.keepalive_s
    )


def _block(state: GuardState, events: list[GuardEvent]) -> GuardResult:
    events.append(GuardEvent.OUTSIDE_CHANGE)
    return GuardResult(replace(state, blocked=GuardEvent.OUTSIDE_CHANGE), None, tuple(events))


def _write(
    state: GuardState,
    value: float | None,
    kind: WriteKind,
    confirmed: float | None,
    now: float,
    config: GuardConfig,
    events: list[GuardEvent],
) -> GuardResult:
    if value is None or (
        state.written_at is not None and now - state.written_at < config.min_interval_s
    ):
        return GuardResult(state, None, tuple(events))  # waits for the next step
    first = state.written is None
    changed = kind is WriteKind.CHANGE and (first or _differs(state, value, config))
    sent = changed or kind is not WriteKind.KEEPALIVE
    if not sent:
        return GuardResult(
            replace(state, written_at=now, retry=False),
            WriteAction(value, kind),
            tuple(events),
        )
    previous = state.written if changed else state.previous
    # Another value the read-back holds as we send — neither ours now nor ours before.
    foreign = (
        confirmed
        if not _matches(confirmed, value, config.tolerance)
        and not _matches(confirmed, previous, config.tolerance)
        else None
    )
    new_state = replace(
        state,
        written=value,
        written_at=now,
        sent_at=now,
        confirmed_at=None,
        previous=previous,
        baseline=confirmed if first else state.baseline,
        foreign=foreign,
        ignored_reported=False if changed else state.ignored_reported,
        rewritten_at=now if kind is WriteKind.REWRITE else state.rewritten_at,
        retry=False,
    )
    return GuardResult(new_state, WriteAction(value, kind), tuple(events))
