"""Automatic freshness limits: earned only by a source seen to repeat an unchanged value."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.freshness import (
    HEARTBEATS_NEEDED,
    KEPT_GAPS,
    Rhythm,
    automatic_limit,
    observe,
)

FLOOR, CAP = 300.0, 1800.0


def seen(*reports: tuple) -> Rhythm:
    """Reports as (time, value) — the value set at that time when it differs from the last, else
    unchanged since — or as (time, value, changed at)."""
    rhythm = Rhythm()
    changed: float | None = None
    last: object = object()
    for report in reports:
        if len(report) == 3:
            reported_at, value, changed = report
        else:
            reported_at, value = report
            if value != last or changed is None:
                changed = reported_at
        last = value
        rhythm = observe(rhythm, reported_at, value, changed)
    return rhythm


def test_a_source_that_repeats_an_unchanged_value_earns_a_limit() -> None:
    """Two heartbeats 60 s apart (the OTGW firmware's repeat): five times that, 300 s."""
    rhythm = seen((0.0, 40.0), (60.0, 40.0), (120.0, 40.0))
    assert rhythm.heartbeats == HEARTBEATS_NEEDED
    assert automatic_limit(rhythm, FLOOR, CAP) == 300.0


def test_a_source_that_reports_only_changes_earns_none() -> None:
    """A flow that moves at every report — as on change-only MQTT while the burner runs — has
    no rhythm to judge by: no limit, however often it reports."""
    rhythm = seen(*((t * 10.0, 40.0 + t) for t in range(30)))
    assert rhythm.heartbeats == 0
    assert automatic_limit(rhythm, FLOOR, CAP) is None


def test_one_heartbeat_is_not_enough() -> None:
    rhythm = seen((0.0, True), (30.0, True))
    assert rhythm.heartbeats == 1
    assert automatic_limit(rhythm, FLOOR, CAP) is None


def test_the_limit_stays_within_its_floor_and_cap() -> None:
    """A fast source (every 10 s) gets the floor; a slow one (hourly) the cap."""
    fast = seen((0.0, 1.0), (10.0, 1.0), (20.0, 1.0), (30.0, 1.0))
    assert automatic_limit(fast, FLOOR, CAP) == FLOOR
    slow = seen((0.0, 1.0), (3600.0, 1.0), (7200.0, 1.0))
    assert automatic_limit(slow, FLOOR, CAP) == CAP


def test_the_limit_follows_the_median_heartbeat_gap() -> None:
    """One long gap (a source back after an outage) does not stretch the limit."""
    rhythm = seen((0.0, 1.0), (100.0, 1.0), (200.0, 1.0), (300.0, 1.0), (3300.0, 1.0))
    assert automatic_limit(rhythm, 0.0, 10_000.0) == 500.0


@pytest.mark.parametrize(
    "reports",
    [
        # Unknown or unavailable: no value to repeat.
        ((0.0, None), (60.0, None), (120.0, None)),
        # No report, or none newer than the last seen.
        ((None, 1.0), (None, 1.0), (None, 1.0)),
        ((60.0, 1.0), (60.0, 1.0), (30.0, 1.0)),
    ],
)
def test_nothing_but_a_newer_known_unchanged_report_is_a_heartbeat(reports: tuple) -> None:
    assert seen(*reports).heartbeats == 0


def test_a_change_keeps_the_heartbeats_already_seen() -> None:
    """A source that showed its rhythm keeps it when its value then changes: the change is a
    report, and a later repeat of the new value is a heartbeat again."""
    rhythm = seen((0.0, 1.0), (60.0, 1.0), (120.0, 1.0), (180.0, 2.0), (240.0, 2.0))
    assert rhythm.heartbeats == 3
    assert rhythm.value == 2.0
    assert rhythm.reported_at == 240.0


def test_only_the_newest_gaps_are_kept() -> None:
    rhythm = seen(*((t * 10.0, 1.0) for t in range(KEPT_GAPS + 5)))
    assert rhythm.heartbeats == KEPT_GAPS


def test_a_value_that_changed_and_changed_back_between_looks_is_no_heartbeat() -> None:
    """The plugin looks every 30 s: a change-only source that went 40.0 → 40.1 → 40.0 in
    between shows the same value again, but it changed meanwhile — no heartbeat. Only a report
    with nothing changed since the last one seen counts."""
    rhythm = seen((0.0, 40.0, 0.0), (30.0, 40.0, 25.0), (60.0, 40.0, 55.0), (90.0, 40.0, 85.0))
    assert rhythm.heartbeats == 0
    assert automatic_limit(rhythm, FLOOR, CAP) is None


def test_a_report_without_its_change_time_proves_nothing() -> None:
    rhythm = Rhythm()
    for t in (0.0, 60.0, 120.0):
        rhythm = observe(rhythm, t, 40.0, None)
    assert rhythm.heartbeats == 0
