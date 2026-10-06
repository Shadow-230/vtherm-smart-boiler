"""The fixed values of ``SCOPE.md`` §7's table "Fixed values (S-37)", pinned where the plugin holds
them (TB-17), and the clocks of ``const.py`` (TB-18).

Each row names its SCOPE row. A value changed in the code without the table, or in the table
without the code, fails here; the user reviews the provisional ones at K4.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.vtherm_smart_boiler import (
    const,
    control,
    control_config,
    feature_manager,
    vtherm_link,
)
from custom_components.vtherm_smart_boiler import forecasts as forecasts_module
from custom_components.vtherm_smart_boiler.core import (
    alarms,
    controller,
    curve,
    daily,
    guards,
    hand_back,
    limits,
    readings,
    relay,
    signal_check,
    zone_watch,
)
from custom_components.vtherm_smart_boiler.core.learning import LearningConfig
from custom_components.vtherm_smart_boiler.transport import writers

H = 3600.0
DAY = 24 * H
LEARNING = LearningConfig()

ROWS: list[tuple[str, Any, Any]] = [
    ("control step 10 s", const.CONTROL_TICK_SECONDS, 10),
    ("keep-alive 30 s", control_config.KEEPALIVE_S, 30.0),
    ("lowest OTGW CS 8 C", writers.OTGW_MIN_SETPOINT, 8.0),
    ("confirmation timeout 120 s", guards.CONFIRM_TIMEOUT_S, 120.0),
    ("confirmation tolerance 0.5 K", guards.TOLERANCE_K, 0.5),
    ("write interval at least 5 s", guards.MIN_WRITE_INTERVAL_S, 5.0),
    ("rewrite window 24 h", guards.REWRITE_WINDOW_S, DAY),
    ("hand-back retry 60 s", control.HAND_BACK_RETRY_S, 60.0),
    ("lost link: 5 min stale", controller.OUTAGE_LOST_S, 300.0),
    ("lost link: within 10 min", controller.OUTAGE_WINDOW_S, 600.0),
    ("lost link: back after 60 s", controller.OUTAGE_BACK_S, 60.0),
    ("zone-unknown alarm 30 min", control.ZONE_UNKNOWN_ALARM_S, 1800.0),
    ("outdoor hold 3 h", curve.DEFAULT_HOLD_S, 3 * H),
    ("outdoor time constant 3 h", curve.DEFAULT_TIME_CONSTANT_S, 3 * H),
    ("stuck sensor: one value held 12 h", signal_check.STUCK_WINDOW_S, 12 * H),
    ("stuck sensor: the weather moves 3 K", signal_check.STUCK_WEATHER_RANGE_K, 3.0),
    ("stuck sensor: deviation 6 K", signal_check.DEFAULT_MAX_DEVIATION_K, 6.0),
    ("stuck sensor: 2 h of overlap", signal_check.MIN_OVERLAP_S, 2 * H),
    ("comfort correction +3 K", controller.CORRECTION_MAX_K, 3.0),
    ("comfort correction 30 min per K", controller.CORRECTION_RISE_S, 1800.0),
    ("comfort correction 3 h at the edge", controller.CORRECTION_LIMIT_S, 3 * H),
    ("comfort correction: 1 K over stops the rise", controller.OVERHEAT_K, 1.0),
    ("comfort correction: satisfied below 70 %", controller.SATISFIED, 0.7),
    ("comfort correction: short by 0.3 K", controller.SHORT_K, 0.3),
    ("comfort correction at most 3 K a day", controller.CORRECTION_DAY_K, 3.0),
    ("frost not warming: 2 h", controller.FROST_ALARM_S, 2 * H),
    ("frost not warming: 0.5 K", controller.FROST_WARMING_K, 0.5),
    ("a zone takes heat above 5 % open", readings.ZONE_OPEN, 0.05),
    ("a zone saturated at 95 %", readings.ZONE_SATURATED, 0.95),
    ("plausible room reading -30 to 45 C", limits.PLAUSIBLE_ROOM, (-30.0, 45.0)),
    ("learning: a swing of 5 K", LEARNING.swing_k, 5.0),
    ("learning: the swing within 30 min", LEARNING.swing_window_s, 1800.0),
    ("learning: a pause of at least 10 min", LEARNING.min_pause_s, 600.0),
    ("learning: resume within 3 K", LEARNING.resume_margin_k, 3.0),
    ("learning: longest pause 60 min", LEARNING.max_pause_s, 3600.0),
    ("learning: read back after 1 min", LEARNING.check_s, 60.0),
    ("low-flow warning after 15 min", alarms.LOW_FLOW_HOLD_S, 900.0),
    ("recognition period at most 10 min", zone_watch.RECOGNITION_S, 600.0),
    ("recognition grace 10 min", zone_watch.GRACE_S, 600.0),
    ("relay out of reach 5 min", relay.RELAY_UNREACHABLE_S, 300.0),
    ("untraced fall-back window 60 min", guards.FALL_BACK_WINDOW_S, H),
    ("a send explains a fall-back within 120 s", guards.EXPLAINED_S, 120.0),
    ("return by itself after 60 min", control.RETURN_QUIET_S, 3600.0),
    ("a relay's power-cut state: warning at 3", relay.RESTARTS_ANSWERED, 3),
    ("a relay's power-cut state: within 24 h", relay.RESTART_WINDOW_S, DAY),
    ("activation delay up to 600 s", controller.ACTIVATION_DELAY_MAX_S, 600.0),
    ("VT's activation delay up to 600 s", vtherm_link.VT_ACTIVATION_DELAY_MAX_S, 600.0),
    ("off at least 1 K below the lowest", control_config.OFF_BELOW_LOWEST_K, 1.0),
    ("off refused within 0.5 K of a hand-back", control_config.OFF_NEAR_HAND_BACK_K, 0.5),
    ("relay check 5 min", relay.RELAY_CHECK_S, 300.0),
    ("relay timer's lapse within 60 s", relay.TIMER_TOLERANCE_S, 60.0),
    ("relay timer's lapse at most 3x", relay.TIMER_MULTIPLES, 3),
    ("relay not taking commands: 3 checks", relay.RELAY_NOT_TAKEN_CHECKS, 3),
    ("held values resent every 5 min", guards.HELD_REFRESH_S, 300.0),
    ("commands lost at 3", guards.LOSSES_FOR_WARNING, 3),
    ("commands lost within 24 h", guards.LOSS_WINDOW_S, DAY),
    ("trace window 5 min", guards.TRACE_WINDOW_S, 300.0),
    ("a difference judged after 2 steps", guards.STEADY_STEPS, 2),
    ("ignored from the start: the first 3 sends", guards.START_ATTEMPTS, 3),
    ("clipped: sent values 1 K apart", guards.CLIP_SPREAD_K, 1.0),
    ("confirmation missing after 5 min", guards.CONFIRMATION_MISSING_S, 300.0),
    ("an echo not judged within 2 min of a draw", guards.DRAW_QUIET_S, 120.0),
    ("a hand-back taken after 2 retries", hand_back.FOREIGN_CHECKS, 2),
    ("an alarm level counts once held 5 min", alarms.ALARM_HOLD_S, 300.0),
    ("a notification closes after 60 min", alarms.NOTICE_CLOSE_S, 3600.0),
    ("an unknown input held 60 min", alarms.UNKNOWN_HOLD_S, 3600.0),
    ("a passive fixed circuit's margin 5 K", control_config.FIXED_CIRCUIT_MARGIN_K, 5.0),
    ("timeout hand-back released within 0.5 K", hand_back.RELEASE_TOLERANCE_K, 0.5),
    ("hand-back failed 3 min after the timeout", hand_back.TIMEOUT_RELEASE_S, 180.0),
    ("relay proof-of-heat window 30 min", relay.PROOF_WINDOW_S, 1800.0),
    ("the late report's wait 60 s at the start", control.START_GRACE_S, 60.0),
    ("the stop's whole hand-back within 15 s", control.STOP_BUDGET_S, 15.0),
    ("each write at the stop capped at 3 s", control.STOP_WRITE_TIMEOUT_S, 3.0),
    ("the stop's read-back wait 5 s", control.STOP_REPORT_WAIT_S, 5.0),
    ("a held release's alarm after 10 s", hand_back.HELD_UNCONFIRMED_S, 10.0),
    ("3 checks with hot water unknown", hand_back.FOREIGN_CHECKS_DHW_UNKNOWN, 3),
    ("none within 120 s of a draw", hand_back.DHW_QUIET_S, 120.0),
    ("the blocker-stopped-heating issue after 60 s", control.STOPPED_HEATING_S, 60.0),
    ("a joint fall-back within 20 s", guards.JOINT_FALL_BACK_S, 20.0),
    ("the P-105 grace 600 s", control.VT_BOILER_GRACE_S, 600.0),
    ("circuit-alarm hysteresis 1 K", alarms.CIRCUIT_ALARM_HYSTERESIS_K, 1.0),
    ("design flow at least the room + 5 K", control_config.DESIGN_FLOW_OVER_ROOM_K, 5.0),
    ("design outdoor at most the room - 10 K", control_config.DESIGN_OUTDOOR_UNDER_ROOM_K, 10.0),
    ("the 25 C migration floor", control_config.MIGRATED_HARD_MIN, 25.0),
    ("a 0.05 factor change", feature_manager.FACTOR_STEP, 0.05),
    ("a flow rise of 5 K as proof of heat", relay.PROOF_FLOW_RISE_K, 5.0),
    ("20 remembered contexts", relay.CONTEXTS_KEPT, 20),
    ("50 % known flame", alarms.KNOWN_SHARE, 0.5),
    ("the limit - 2", alarms.COUNT_CLEAR_MARGIN, 2),
    ("2 K", alarms.SETPOINT_REACHED_K, 2.0),
    ("a 10-K slope span", alarms.SLOPE_MIN_SPAN_K, 10.0),
    ("0.05 bar/K", alarms.SLOPE_MAX_BAR_PER_K, 0.05),
    ("40 C", alarms.REFERENCE_FLOW, 40.0),
    ("0.1 bar", alarms.ADD_WATER_HYSTERESIS_BAR, 0.1),
    ("a pressure sample every 10 min", alarms.PRESSURE_SAMPLE_S, 600.0),
    ("after 10 min without a flame", alarms.QUIET_FLAME_S, 600.0),
    ("forecast call timeout 30 s", forecasts_module.FORECAST_CALL_TIMEOUT_S, 30.0),
    ("the frost closed-zone issue on a 1 K move", control.FROST_CLOSED_SHOWN_K, 1.0),
    ("the control switch's restore waited 60 s", control.RESTORE_WAIT_S, 60.0),
    ("a write's timeout 10 s", writers.WRITE_TIMEOUT_S, 10.0),
    ("a control step counts 60 s at most", controller.MAX_STEP_S, 60.0),
    ("add water accepted within 0.1-2.0 bar", alarms.ADD_WATER_RANGE_BAR, (0.1, 2.0)),
    ("SmartPI's learning calls time out after 5 s", control.LEARNING_TIMEOUT_S, 5.0),
    ("the minimum VT version 10.2.0", vtherm_link.VT_FEATURE_MANAGERS_FROM, "10.2.0"),
    ("the reload-VT issue after 15 min", feature_manager.RELOAD_GRACE_S, 900),
    ("a day counts when 90 % of it is known", daily.FIT_COVERAGE, 0.9),
    ("the read-back waiting issue after 5 min", control.READ_BACK_WAIT_S, 300.0),
]


@pytest.mark.parametrize(("row", "value", "expected"), ROWS, ids=[row for row, _, _ in ROWS])
def test_every_fixed_value_of_the_scope_table(row: str, value: Any, expected: Any) -> None:
    assert value == expected, row


def test_the_clocks() -> None:
    """TB-18: the monitor's quick path every 30 s, control every 10 s, the analysis every 5 min,
    a forecast snapshot every 30 min, and eight days of history."""
    assert const.TICK_SECONDS == 30
    assert const.CONTROL_TICK_SECONDS == 10
    assert const.SUMMARY_SECONDS == 300
    assert const.FORECAST_SECONDS == 1800
    assert const.HISTORY_DAYS == 8
