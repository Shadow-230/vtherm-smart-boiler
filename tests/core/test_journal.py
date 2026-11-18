"""The plugin's journal (``docs/en/development/plans/plan-0.2-i10.md``, I10.6): what it decided
and why, from one look at control and the alarms to the next — the heat call on and off, a water
setpoint change of at least 1 K with its reason, a circuit's need holding the water, control
handed back and taken again, an alarm raised and cleared — kept 14 days, 2,000 entries at most."""

from __future__ import annotations

from dataclasses import replace

import pytest

from custom_components.vtherm_smart_boiler.core.journal import (
    JOURNAL_DAYS,
    JOURNAL_MAX,
    Entry,
    JournalState,
    Kind,
    Observed,
    entry_from_stored,
    entry_to_stored,
    follow,
    prune,
    settings_saved,
)

DAY = 86400.0

IDLE = Observed(
    controlling=True,
    called=False,
    call_reason="no_demand",
    water=None,
    reasons=("no_demand",),
    alarms={},
)
HEATING = Observed(
    controlling=True,
    called=True,
    call_reason=None,
    water=45.0,
    reasons=("demand", "outdoor_sensor"),
    alarms={},
)
OFF = Observed(
    controlling=False,
    called=None,
    call_reason="not_controlling",
    water=None,
    reasons=("control_off",),
    alarms={},
)


def run(*looks: Observed, start: float = 0.0) -> list[Entry]:
    """The entries of a run of looks, one a minute; the first sets the baseline."""
    state = JournalState()
    out: list[Entry] = []
    for k, look in enumerate(looks):
        state, entries = follow(state, look, start + 60.0 * k)
        out.extend(entries)
    return out


def test_the_first_look_after_a_start_journals_nothing() -> None:
    assert run(HEATING) == []
    assert run(OFF) == []


def test_the_heat_call_on_and_off_with_their_reasons() -> None:
    entries = run(IDLE, HEATING, IDLE)
    assert [(e.kind, e.reasons) for e in entries if e.kind in (Kind.CALL_ON, Kind.CALL_OFF)] == [
        (Kind.CALL_ON, ("demand", "outdoor_sensor")),
        (Kind.CALL_OFF, ("no_demand",)),
    ]
    assert [e.at for e in entries if e.kind is Kind.CALL_ON] == [60.0]


def test_a_call_that_ends_unknown_ends_with_why() -> None:
    waiting = replace(IDLE, called=None, call_reason="waiting_data", reasons=("zones_unknown",))
    entries = run(IDLE, HEATING, waiting)
    assert (entries[-1].kind, entries[-1].reasons) == (Kind.CALL_OFF, ("waiting_data",))
    # From unknown to off, nothing: no call was on.
    assert run(waiting, IDLE) == []


def test_the_water_from_its_first_value_then_steps_of_at_least_1_k() -> None:
    looks = [IDLE] + [replace(HEATING, water=w) for w in (45.0, 45.5, 45.9, 46.0, 44.9, 44.0)]
    water = [(e.value, e.previous) for e in run(*looks) if e.kind is Kind.WATER]
    # 45 first; 46.0 is 1 K from the 45 last journaled, 45.5 and 45.9 not; 44.9 is 1.1 K below
    # 46; 44.0 only 0.9 K below 44.9.
    assert water == [(45.0, None), (46.0, 45.0), (44.9, 46.0)]


def test_the_water_says_why() -> None:
    held = replace(HEATING, water=30.0, reasons=("demand", "limit_hard_min"))
    entries = [e for e in run(IDLE, HEATING, held) if e.kind is Kind.WATER]
    assert entries[-1].reasons == ("demand", "limit_hard_min")


def test_the_water_starts_again_after_control_was_given_back() -> None:
    entries = run(IDLE, HEATING, OFF, IDLE, replace(HEATING, water=45.4))
    assert [(e.value, e.previous) for e in entries if e.kind is Kind.WATER] == [
        (45.0, None),
        (45.4, None),
    ]


def test_a_circuit_need_holding_the_water() -> None:
    need = replace(HEATING, water=55.0, reasons=("circuit_asks", "limit_circuit_need"))
    entries = run(HEATING, need, need, HEATING)
    kinds = [e.kind for e in entries if e.kind in (Kind.CIRCUIT_NEED, Kind.CIRCUIT_NEED_END)]
    assert kinds == [Kind.CIRCUIT_NEED, Kind.CIRCUIT_NEED_END]
    assert next(e for e in entries if e.kind is Kind.CIRCUIT_NEED).value == 55.0


def test_control_handed_back_and_taken_again() -> None:
    back = replace(OFF, reasons=("alarm_hand_back",))
    entries = run(HEATING, back, IDLE)
    control = [(e.kind, e.reasons) for e in entries if e.kind in (Kind.HANDED_BACK, Kind.TOOK_OVER)]
    assert control == [
        (Kind.HANDED_BACK, ("alarm_hand_back",)),
        (Kind.TOOK_OVER, ("no_demand",)),
    ]
    # The call ends with the hand-back, and says so.
    assert (Kind.CALL_OFF, ("not_controlling",)) in [(e.kind, e.reasons) for e in entries]


def test_an_alarm_raised_its_level_raised_and_cleared() -> None:
    warning = replace(IDLE, alarms={"alarm_pressure_low": "warning"})
    alarm = replace(IDLE, alarms={"alarm_pressure_low": "alarm", "alarm_write_failed": "alarm"})
    entries = run(IDLE, warning, warning, alarm, IDLE)
    assert [(e.kind, e.subject, e.level) for e in entries] == [
        (Kind.ALARM_ON, "alarm_pressure_low", "warning"),
        (Kind.ALARM_ON, "alarm_pressure_low", "alarm"),
        (Kind.ALARM_ON, "alarm_write_failed", "alarm"),
        (Kind.ALARM_OFF, "alarm_pressure_low", None),
        (Kind.ALARM_OFF, "alarm_write_failed", None),
    ]


def test_an_alarm_that_cannot_be_judged_now_stays_as_it_was() -> None:
    on = replace(IDLE, alarms={"alarm_pressure_low": "alarm"})
    unknown = replace(IDLE, alarms={"alarm_pressure_low": None})
    entries = run(IDLE, on, unknown, unknown, IDLE)
    assert [e.kind for e in entries] == [Kind.ALARM_ON, Kind.ALARM_OFF]
    assert entries[-1].at == 240.0
    assert run(IDLE, unknown, IDLE) == []


def test_settings_saved_name_where_from_and_what() -> None:
    entry = settings_saved(100.0, "page", ("curve",))
    assert (entry.kind, entry.subject, entry.reasons) == (Kind.SETTINGS, "page", ("curve",))


def test_kept_14_days_and_2000_entries_the_oldest_dropped_first() -> None:
    assert (JOURNAL_DAYS, JOURNAL_MAX) == (14, 2000)
    now = 30 * DAY
    old = Entry(now - 15 * DAY, Kind.STARTED)
    kept = [Entry(now - DAY + k, Kind.CALL_ON) for k in range(2100)]
    pruned = prune([old, *kept], now)
    assert len(pruned) == JOURNAL_MAX
    assert pruned[0] == kept[100]
    assert pruned[-1] == kept[-1]


def test_an_entry_kept_and_read_back() -> None:
    entry = Entry(
        12.5,
        Kind.WATER,
        reasons=("demand",),
        value=45.04,
        previous=44.0,
        subject=None,
        level=None,
    )
    assert entry_from_stored(entry_to_stored(entry)) == entry
    alarm = Entry(3.0, Kind.ALARM_ON, subject="alarm_pressure_low", level="warning")
    assert entry_from_stored(entry_to_stored(alarm)) == alarm


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "x",
        {},
        {"at": "noon", "kind": "water"},
        {"at": 1.0, "kind": "something"},
        {"at": 1.0, "kind": "water", "value": "hot"},
        {"at": 1.0, "kind": "water", "reasons": "demand"},
    ],
)
def test_an_entry_that_cannot_be_read_is_left_out(raw: object) -> None:
    assert entry_from_stored(raw) is None
