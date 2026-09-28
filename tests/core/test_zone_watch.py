"""Decision 3: the recognition period, each zone's grace, and every zone unknown."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.readings import ZoneState
from custom_components.vtherm_smart_boiler.core.zone_watch import (
    GRACE_S,
    NO_ZONE_ISSUE_S,
    RECOGNITION_S,
    ZoneWatch,
    follow_zones,
    graced,
    in_recognition,
    no_zone_issue_due,
)

MIN = 60.0


def zone(zone_id: str, t: float, **kw) -> ZoneState:
    """A zone VT has started, heating and calling."""
    kw.setdefault("heating_enabled", True)
    kw.setdefault("reported", True)
    kw.setdefault("valve_open", 0.6)
    return ZoneState(zone_id, reported_at=t, **kw)


def gone(zone_id: str) -> ZoneState:
    return ZoneState(zone_id)  # unavailable: no mode, nothing reported


def placeholder(zone_id: str, t: float) -> ZoneState:
    """What VT 10.4.0 shows before a thermostat's first refresh: "off", neither is_ready nor
    the rest of its state."""
    return ZoneState(zone_id, heating_enabled=False, reported=False, reported_at=t)


def run(steps, watch: ZoneWatch | None = None, starting=lambda _t: False) -> list[ZoneWatch]:
    watch = watch or ZoneWatch()
    seen = []
    for t, zones in steps:
        watch = follow_zones(watch, zones, t, None, starting=starting(t))
        seen.append(watch)
    return seen


def test_the_recognition_period_runs_from_the_first_step() -> None:
    assert in_recognition(ZoneWatch())  # before any step: the unit has just started
    [first] = run([(100.0, (placeholder("a", 100.0),))])
    assert in_recognition(first)
    assert first.recognition_since == 100.0


def test_recognition_ends_once_every_zone_has_reported() -> None:
    """Zones report one by one; a zone that reported and went away again still counts."""
    seen = run(
        [
            (0.0, (zone("a", 0.0), placeholder("b", 0.0))),
            (10.0, (gone("a"), placeholder("b", 10.0))),
            (20.0, (gone("a"), zone("b", 20.0))),
        ]
    )
    assert [in_recognition(w) for w in seen] == [True, True, False]


def test_recognition_ends_after_ten_minutes_whatever_the_zones_show() -> None:
    steps = [(t, (placeholder("a", t),)) for t in (0.0, RECOGNITION_S - 10.0, RECOGNITION_S)]
    seen = run(steps)
    assert [in_recognition(w) for w in seen] == [True, True, False]


def test_recognition_cannot_end_while_home_assistant_starts() -> None:
    """Every zone reported, or ten minutes gone: still not over until Home Assistant runs."""
    steps = [(t, (zone("a", t),)) for t in (0.0, 700.0, 710.0)]
    seen = run(steps, starting=lambda t: t < 710.0)
    assert [in_recognition(w) for w in seen] == [True, True, False]


def test_a_vt_reload_starts_a_recognition_period() -> None:
    """Every zone stops answering at once after having answered: VT reloads."""
    seen = run(
        [
            (0.0, (zone("a", 0.0), zone("b", 0.0))),
            (10.0, (gone("a"), placeholder("b", 10.0))),
            (20.0, (zone("a", 20.0), placeholder("b", 20.0))),
            (30.0, (zone("a", 30.0), zone("b", 30.0))),
        ]
    )
    assert [in_recognition(w) for w in seen] == [False, True, True, False]
    assert seen[1].recognition_since == 10.0


def test_zones_going_away_one_by_one_get_their_grace_not_a_recognition() -> None:
    """Not at once: each zone keeps its last answer for its own ten minutes."""
    seen = run(
        [
            (0.0, (zone("a", 0.0), zone("b", 0.0))),
            (10.0, (gone("a"), zone("b", 10.0))),
            (20.0, (gone("a"), gone("b"))),
        ]
    )
    assert not in_recognition(seen[1])
    assert set(graced(seen[1])) == {"a"}
    assert not in_recognition(seen[2])
    assert seen[2].lost_at == {"a": 10.0, "b": 20.0}


def test_no_zone_ever_answering_starts_no_new_recognition() -> None:
    steps = [(t, (gone("a"),)) for t in (0.0, RECOGNITION_S, RECOGNITION_S + 10.0)]
    seen = run(steps)
    assert [in_recognition(w) for w in seen] == [True, False, False]


def test_a_zone_keeps_its_last_answer_for_ten_minutes() -> None:
    first = zone("a", 0.0, valve_open=0.7)
    seen = run(
        [
            (0.0, (first, zone("b", 0.0))),
            (10.0, (gone("a"), zone("b", 10.0))),
            (10.0 + GRACE_S - 10.0, (gone("a"), zone("b", GRACE_S))),
            (10.0 + GRACE_S, (gone("a"), zone("b", GRACE_S + 10.0))),
        ]
    )
    assert graced(seen[1]) == {"a": first}
    assert graced(seen[2]) == {"a": first}
    assert graced(seen[3]) == {}  # dropped out: the known zones decide


def test_a_not_started_zone_keeps_its_grace() -> None:
    """VT's placeholder "off" during a thermostat's reload is not the user's "off": the zone's
    last answer holds."""
    first = zone("a", 0.0)
    seen = run([(0.0, (first, zone("b", 0.0))), (10.0, (placeholder("a", 10.0), zone("b", 10.0)))])
    assert graced(seen[1]) == {"a": first}


def test_a_zone_that_answers_again_leaves_its_grace() -> None:
    seen = run(
        [
            (0.0, (zone("a", 0.0), zone("b", 0.0))),
            (10.0, (gone("a"), zone("b", 10.0))),
            (20.0, (zone("a", 20.0, valve_open=0.1), zone("b", 20.0))),
        ]
    )
    assert graced(seen[2]) == {}
    assert seen[2].last["a"].valve_open == 0.1


def test_a_zone_never_known_this_session_gets_no_grace() -> None:
    seen = run([(0.0, (zone("b", 0.0), gone("a"))), (10.0, (zone("b", 10.0), gone("a")))])
    assert graced(seen[-1]) == {}


def test_a_zone_still_unknown_when_the_recognition_ends_drops_out_at_once() -> None:
    """A zone that answered during the recognition, then went away: no grace beyond it."""
    steps = [
        (0.0, (zone("a", 0.0), placeholder("b", 0.0))),
        (10.0, (gone("a"), placeholder("b", 10.0))),
        (RECOGNITION_S, (gone("a"), zone("b", RECOGNITION_S))),
    ]
    seen = run(steps)
    assert graced(seen[1]) == {"a": steps[0][1][0]}
    assert not in_recognition(seen[2])
    assert graced(seen[2]) == {}


def test_a_zone_taken_out_of_the_options_is_forgotten() -> None:
    seen = run([(0.0, (zone("a", 0.0), zone("b", 0.0))), (10.0, (zone("b", 10.0),))])
    assert set(seen[-1].last) == {"b"}
    assert graced(seen[-1]) == {}


def test_a_clock_set_back_restarts_the_waits_now() -> None:
    """C9: a start later than now counts as now, for the recognition and for a grace."""
    seen = run(
        [
            (1000.0, (zone("a", 1000.0), zone("b", 1000.0))),
            (1010.0, (gone("a"), zone("b", 1010.0))),
            (500.0, (gone("a"), zone("b", 500.0))),  # the clock went back
            (500.0 + GRACE_S - 10.0, (gone("a"), zone("b", 500.0))),
        ]
    )
    assert seen[2].lost_at["a"] == 500.0
    assert set(graced(seen[3])) == {"a"}
    back = 500.0
    recognition = run(
        [
            (t, (placeholder("a", t),))
            for t in (1000.0, back, back + RECOGNITION_S - 10.0, back + RECOGNITION_S)
        ]
    )
    assert recognition[1].recognition_since == back
    assert [in_recognition(w) for w in recognition] == [True, True, True, False]


def test_with_no_zone_configured_the_recognition_has_nothing_to_wait_for() -> None:
    [watch] = run([(0.0, ())])
    assert not in_recognition(watch)
    assert watch.unknown_since is None


@pytest.mark.parametrize(
    ("zones", "since"),
    [
        ((gone("a"), gone("b")), 0.0),
        ((gone("a"), zone("b", 0.0)), None),
        ((), None),  # no zone configured: nothing is unknown
    ],
)
def test_every_zone_unknown_since(zones: tuple[ZoneState, ...], since: float | None) -> None:
    [watch] = run([(0.0, zones)])
    assert watch.unknown_since == since


def test_the_no_zone_issue_is_due_after_ten_minutes_of_every_zone_unknown() -> None:
    steps = [(t, (gone("a"),)) for t in (0.0, NO_ZONE_ISSUE_S - 10.0, NO_ZONE_ISSUE_S)]
    seen = run(steps)
    assert [no_zone_issue_due(w, t) for w, (t, _z) in zip(seen, steps, strict=True)] == [
        False,
        False,
        True,
    ]
    [back] = run([(NO_ZONE_ISSUE_S + 10.0, (zone("a", 0.0),))], watch=seen[-1])
    assert back.unknown_since is None
    assert not no_zone_issue_due(back, NO_ZONE_ISSUE_S + 10.0)


def test_an_off_zone_vt_has_not_started_is_known_once_the_recognition_is_over() -> None:
    """S-34: after the recognition period an "off" zone VT never started counts as known, so
    every zone is not unknown."""
    steps = [(t, (placeholder("a", t),)) for t in (0.0, RECOGNITION_S)]
    seen = run(steps)
    assert seen[0].unknown_since == 0.0
    assert seen[1].unknown_since is None
