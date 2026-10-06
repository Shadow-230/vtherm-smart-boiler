"""The hand-back's evidence (V5): what shows a release, a steady third value that another
controller holds, a two-valued target's change, the trace of an outage, and what is shown."""

from __future__ import annotations

import pytest

from custom_components.vtherm_smart_boiler.core.hand_back import (
    DEVICE_TIMEOUT_BOUNDS_S,
    DEVICE_TIMEOUT_DEFAULT_S,
    DHW_QUIET_S,
    FOREIGN_CHECKS,
    FOREIGN_CHECKS_DHW_UNKNOWN,
    OUTAGE_WINDOW_S,
    CheckKind,
    CheckSource,
    ForeignWatch,
    HandBackConfirmation,
    ReleaseRule,
    SwitchVerdict,
    TargetView,
    judge_switch,
    outage_seen,
    released,
    shown,
    third_value,
    timeout_lapsed,
    timeout_late,
    watch_foreign,
)

HELD = ReleaseRule(CheckKind.VALUE, expected=50.0, release_from=45.0, lowest=25.0)
EXPIRING = ReleaseRule(CheckKind.LEAVES_VALUE, expected=50.0, release_from=45.0, lowest=25.0)
GATEWAY = ReleaseRule(CheckKind.LEAVES_VALUE, expected=0.0, release_from=45.0, lowest=25.0)
TIMEOUT = ReleaseRule(CheckKind.BACK_TO_BASELINE, release_from=60.0, lowest=25.0, baseline=45.0)


@pytest.mark.parametrize(
    ("read_back", "shown_released"),
    [(50.0, True), (50.4, True), (49.6, True), (25.0, False), (45.0, False), (38.0, False)],
)
def test_a_held_target_is_released_only_at_the_hand_back_value(
    read_back: float, shown_released: bool
) -> None:
    """The device keeps the last value it was given: anything else is not the release."""
    assert released(HELD, read_back, reported_after=True) is shown_released


@pytest.mark.parametrize(
    ("read_back", "shown_released"),
    [(50.0, True), (38.0, True), (45.4, False), (25.3, False), (44.0, True)],
)
def test_an_expiring_target_is_released_at_the_hand_back_value_or_away_from_ours(
    read_back: float, shown_released: bool
) -> None:
    """An expiring value lapses to the device's own: a value away from both the plugin's last
    value and the lowest just written counts."""
    assert released(EXPIRING, read_back, reported_after=True) is shown_released


@pytest.mark.parametrize(
    ("read_back", "reported_after", "shown_released"),
    [(0.0, False, True), (40.0, True, True), (40.0, False, False), (25.0, True, False)],
)
def test_a_gateway_without_the_plugins_last_value_needs_a_report_after_the_command(
    read_back: float, reported_after: bool, shown_released: bool
) -> None:
    """``CS=0`` read back is the release; a value away from the lowest counts only once it was
    reported after the command when the plugin's last value is not known."""
    rule = ReleaseRule(CheckKind.LEAVES_VALUE, expected=0.0, release_from=None, lowest=25.0)
    assert released(rule, read_back, reported_after=reported_after) is shown_released


def test_a_gateway_release_is_its_zero_or_the_thermostats_value() -> None:
    assert released(GATEWAY, 0.0, reported_after=True)
    assert released(GATEWAY, 40.0, reported_after=True)  # the thermostat's own value
    assert not released(GATEWAY, 25.0, reported_after=True)  # still the lowest written first
    assert not released(GATEWAY, 45.3, reported_after=True)  # still the plugin's


@pytest.mark.parametrize(
    "rule",
    [
        GATEWAY,
        ReleaseRule(CheckKind.BACK_TO_BASELINE, release_from=45.3, lowest=25.0, baseline=52.0),
    ],
)
def test_away_from_ours_counts_only_once_reported_after_the_command(rule: ReleaseRule) -> None:
    """PB-30: a polled read-back one ramp step behind the plugin's last value, not reported
    since the command, is no release — away from ours counts only once reported after it."""
    assert not released(rule, 43.5, reported_after=False)
    assert released(rule, 43.5, reported_after=True)
    assert not released(rule, None, reported_after=True)


@pytest.mark.parametrize(
    ("own", "read_back", "shown_released"),
    [
        (25.0, 25.0, True),  # the thermostat asks for the lowest
        (25.0, 25.4, True),
        (45.0, 45.0, True),  # the thermostat asks for the plugin's last value
        (30.0, 45.3, False),  # it asks for something else: still the plugin's
        (None, 25.0, False),  # its request not mapped, unknown or unavailable: the old rule
        (None, 45.0, False),
        (30.0, 25.0, False),  # it asks for something else: still the lowest written first
    ],
)
def test_a_gateway_release_is_also_the_thermostats_own_request(
    own: float | None, read_back: float, shown_released: bool
) -> None:
    """PB-10: the OTGW firmware over MQTT passes the thermostat's own request on after ``CS=0``
    and never shows 0; a request within half a kelvin of the lowest or the plugin's last value
    never left them. Its request, where its entity is mapped, shows the release."""
    rule = ReleaseRule(
        CheckKind.LEAVES_VALUE, expected=0.0, release_from=45.0, lowest=25.0, own=own
    )
    assert released(rule, read_back, reported_after=False) is shown_released


def test_only_a_gateway_check_counts_the_thermostats_request() -> None:
    """Negative: a held target, a timeout target and a switch never count it."""
    for rule in (
        ReleaseRule(CheckKind.VALUE, expected=50.0, release_from=45.0, lowest=25.0, own=25.0),
        ReleaseRule(
            CheckKind.BACK_TO_BASELINE, release_from=45.0, lowest=25.0, baseline=52.0, own=25.0
        ),
        ReleaseRule(CheckKind.SWITCH, own=25.0),
    ):
        assert not released(rule, 25.0, reported_after=True)


@pytest.mark.parametrize(
    ("baseline", "read_back", "shown_released"),
    [
        (45.0, 45.0, True),
        (45.0, 45.5, True),
        (45.0, 38.0, True),  # SB-04: the device's own value moved — away from ours and the lowest
        (45.0, 59.6, False),  # still the plugin's last value
        (45.0, 25.0, False),  # still the lowest written first
        (None, 38.0, True),  # the baseline unknown: away from ours and the lowest
        (None, 60.2, False),
        (None, 25.4, False),
    ],
)
def test_a_timeout_hand_back_is_released_at_the_baseline_or_away_from_ours(
    baseline: float | None, read_back: float, shown_released: bool
) -> None:
    """Decision 5 (SB-04): back within half a kelvin of the value from before the session, or
    more than half a kelvin from both the plugin's last value and the lowest — a device whose own
    value moves (an EMS boiler under its own controller or curve) never shows the baseline."""
    rule = ReleaseRule(
        CheckKind.BACK_TO_BASELINE, release_from=60.0, lowest=25.0, baseline=baseline
    )
    assert released(rule, read_back, reported_after=True) is shown_released


def test_a_timeout_with_the_baseline_known_and_its_last_value_not_needs_a_report() -> None:
    """The plugin's last value unknown: a value away from the lowest counts only once it was
    reported after the command — the baseline itself counts as it is."""
    rule = ReleaseRule(CheckKind.BACK_TO_BASELINE, lowest=25.0, baseline=45.0)
    assert not released(rule, 38.0, reported_after=False)
    assert released(rule, 38.0, reported_after=True)
    assert released(rule, 45.0, reported_after=False)


@pytest.mark.parametrize(
    ("since_write_s", "timeout_s", "lapsed", "late"),
    [
        (0.0, 60.0, False, False),
        (59.0, 60.0, False, False),
        (60.0, 60.0, True, False),  # the device's own timeout has run: its release can show
        (239.0, 60.0, True, False),
        (240.0, 60.0, True, True),  # three minutes after it: "hand-back failed"
        (1799.0, 1800.0, False, False),
        (1980.0, 1800.0, True, True),
    ],
)
def test_a_timeout_hand_back_is_judged_from_the_devices_timeout(
    since_write_s: float, timeout_s: float, lapsed: bool, late: bool
) -> None:
    """Decision 5: before the device's own timeout has run since the last write, the device
    holds the lowest by the user's declaration — no release is judged; the alarm comes three
    minutes after that timeout."""
    assert timeout_lapsed(since_write_s, timeout_s) is lapsed
    assert timeout_late(since_write_s, timeout_s) is late


def test_the_devices_timeout_default_lies_within_its_bounds() -> None:
    low, high = DEVICE_TIMEOUT_BOUNDS_S
    assert low <= DEVICE_TIMEOUT_DEFAULT_S <= high
    assert DEVICE_TIMEOUT_DEFAULT_S == low  # the shortest: an alarm rather too early than late


@pytest.mark.parametrize("rule", [HELD, EXPIRING, GATEWAY, TIMEOUT])
def test_a_read_back_without_a_value_never_shows_a_release(rule: ReleaseRule) -> None:
    """Negative: missing, unknown or unavailable is no release."""
    assert not released(rule, None, reported_after=True)


def test_a_timeout_without_any_known_value_needs_a_report_after_the_command() -> None:
    rule = ReleaseRule(CheckKind.BACK_TO_BASELINE, lowest=25.0)
    assert not released(rule, 38.0, reported_after=False)
    assert released(rule, 38.0, reported_after=True)


@pytest.mark.parametrize(
    ("read_back", "third"),
    [(60.0, True), (50.2, False), (45.3, False), (25.4, False), (None, False)],
)
def test_a_third_value_is_neither_ours_nor_the_lowest_nor_the_hand_back_value(
    read_back: float | None, third: bool
) -> None:
    assert third_value(HELD, read_back) is third


def test_a_third_value_with_the_plugins_last_value_unknown() -> None:
    rule = ReleaseRule(CheckKind.VALUE, expected=50.0, lowest=25.0)
    assert third_value(rule, 45.0)
    assert not third_value(rule, 25.0)


def test_two_checks_of_the_same_third_value_mean_another_controller() -> None:
    watch, taken = watch_foreign(None, 60.0, third=True, dhw=False, dhw_recent=False)
    assert watch == ForeignWatch(60.0, 1, False)
    assert not taken
    watch, taken = watch_foreign(watch, 60.3, third=True, dhw=False, dhw_recent=False)
    assert taken
    assert watch is not None
    assert watch.checks == FOREIGN_CHECKS


def test_hot_water_unknown_takes_three_checks() -> None:
    watch, taken = watch_foreign(None, 60.0, third=True, dhw=None, dhw_recent=False)
    watch, taken = watch_foreign(watch, 60.0, third=True, dhw=False, dhw_recent=False)
    assert not taken  # unknown at the first check: three needed
    watch, taken = watch_foreign(watch, 60.0, third=True, dhw=False, dhw_recent=False)
    assert taken
    assert watch is not None
    assert watch.checks == FOREIGN_CHECKS_DHW_UNKNOWN


@pytest.mark.parametrize(("dhw", "recent"), [(True, False), (False, True)])
def test_a_hot_water_draw_now_or_lately_gives_no_judgement(dhw: bool, recent: bool) -> None:
    """W6: the boiler's read-back may show the hot-water value during a draw and for 120 s."""
    watch = ForeignWatch(60.0, 1, False)
    assert DHW_QUIET_S == 120.0
    assert watch_foreign(watch, 60.0, third=True, dhw=dhw, dhw_recent=recent) == (None, False)


def test_a_moving_or_gone_third_value_starts_again() -> None:
    watch = ForeignWatch(60.0, 1, False)
    moved, taken = watch_foreign(watch, 65.0, third=True, dhw=False, dhw_recent=False)
    assert moved == ForeignWatch(65.0, 1, False)
    assert not taken
    assert watch_foreign(watch, 50.0, third=False, dhw=False, dhw_recent=False) == (None, False)
    assert watch_foreign(watch, None, third=False, dhw=False, dhw_recent=False) == (None, False)


@pytest.mark.parametrize(
    ("state", "seen", "trace", "verdict"),
    [
        ("on", False, False, SwitchVerdict.RELEASED),
        ("on", True, True, SwitchVerdict.RELEASED),
        ("off", False, False, SwitchVerdict.WAITING),  # never read back on: owed, retried
        ("off", True, False, SwitchVerdict.TAKEN),
        ("off", True, True, SwitchVerdict.LOST),  # a trace of an outage: written again
        ("unavailable", True, False, SwitchVerdict.WAITING),
        ("unknown", True, False, SwitchVerdict.WAITING),
        (None, True, False, SwitchVerdict.WAITING),
    ],
)
def test_a_two_valued_target_is_taken_only_after_it_was_read_back_once(
    state: str | None, seen: bool, trace: bool, verdict: SwitchVerdict
) -> None:
    assert judge_switch(state, "on", seen=seen, trace=trace) is verdict


def test_an_outage_within_five_minutes_is_a_trace() -> None:
    outages = {"switch.ch": 1000.0, "sensor.other_device": 1000.0}
    assert OUTAGE_WINDOW_S == 300.0
    assert outage_seen(outages, ("switch.ch",), 1300.0)
    assert not outage_seen(outages, ("switch.ch",), 1301.0)
    assert not outage_seen(outages, ("switch.elsewhere",), 1100.0)  # not one of its entities
    assert outage_seen(outages, ("switch.elsewhere", "sensor.other_device"), 1100.0)
    assert outage_seen(outages, ("switch.ch",), 900.0)  # a clock set back: still a trace
    assert not outage_seen({}, ("switch.ch",), 1000.0)  # no information: no trace


def test_what_is_shown_follows_the_weakest_target() -> None:
    separate = TargetView(released=True, taken=False, source=CheckSource.SEPARATE)
    self_echo = TargetView(released=True, taken=False, source=CheckSource.SELF)
    assumed = TargetView(released=True, taken=False, source=CheckSource.ASSUMED)
    pending = TargetView(released=False, taken=False, source=CheckSource.SEPARATE)
    taken = TargetView(released=False, taken=True, source=CheckSource.SEPARATE)
    assert shown((), gateway=False, failing=False) is None
    assert shown((separate,), gateway=False, failing=False) is HandBackConfirmation.CONFIRMED
    assert (
        shown((separate,), gateway=True, failing=False) is HandBackConfirmation.CONFIRMED_BY_GATEWAY
    )
    assert shown((separate, self_echo), gateway=False, failing=False) is (
        HandBackConfirmation.UNVERIFIED
    )
    assert shown((assumed,), gateway=False, failing=False) is HandBackConfirmation.UNVERIFIED
    assert shown((separate, pending), gateway=False, failing=False) is (
        HandBackConfirmation.WAITING
    )
    assert shown((pending, taken), gateway=False, failing=True) is (
        HandBackConfirmation.NOT_CONFIRMED
    )
    assert shown((separate, taken), gateway=False, failing=False) is (
        HandBackConfirmation.TAKEN_BY_OTHER
    )


def test_a_boiler_thermostats_modes_are_its_states() -> None:
    """X8: a relay's boiler thermostat entity — any mode it reports is a known state: after its
    rest state was read back, another mode with no trace is another controller's."""
    from custom_components.vtherm_smart_boiler.core.hand_back import SwitchVerdict, judge_switch

    assert judge_switch("off", "off", False, False, None) is SwitchVerdict.RELEASED
    assert judge_switch("auto", "off", True, False, None) is SwitchVerdict.TAKEN
    assert judge_switch("heat", "off", True, True, None) is SwitchVerdict.LOST
    assert judge_switch("unavailable", "off", True, False, None) is SwitchVerdict.WAITING
    assert judge_switch(None, "off", True, False, None) is SwitchVerdict.WAITING
    assert judge_switch("auto", "off", True, False) is SwitchVerdict.WAITING  # a switch: on/off


def test_a_restart_indicator_shows_a_restart_by_its_kind() -> None:
    """TB-28 (Q3.7), the pure cases moved from the transport test: an uptime that falls, a
    counter or a boot time that changes — a reset counter too, cautiously — show a restart; a
    value not known shows nothing."""
    from custom_components.vtherm_smart_boiler.core.hand_back import RestartKind, restart_seen

    assert restart_seen(5000.0, 12.0, RestartKind.UPTIME)
    assert not restart_seen(12.0, 72.0, RestartKind.UPTIME)  # counting on: no restart
    assert not restart_seen(12.0, 12.0, RestartKind.UPTIME)
    assert restart_seen(3.0, 4.0, RestartKind.COUNTER)
    assert restart_seen(4.0, 0.0, RestartKind.COUNTER)  # a reset counter: cautious, a trace
    assert not restart_seen(3.0, 3.0, RestartKind.COUNTER)
    assert restart_seen(1.0, 2.0, RestartKind.BOOT_TIME)
    assert not restart_seen(None, 2.0, RestartKind.BOOT_TIME)
    assert not restart_seen(2.0, None, RestartKind.UPTIME)
