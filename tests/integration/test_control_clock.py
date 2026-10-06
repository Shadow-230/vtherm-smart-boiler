"""The control unit's waits under a wall clock set back, and an owed hand-back's retry with a
retake in one step — the tests step 3.2a of 0.2.3 left (PB-28, PB-31; review of 2026-10-04).

- PB-28 (C9): a "since" later than now — the wall clock set back an hour — counts from now: the
  frost alarm's hold, the timeout hand-back's early alarm and the external-control switch's
  exemption last their own time after the set-back, not an hour more.
  So does the monitoring period's start: with none configured, control is not blocked.
- PB-31 (probe D): an owed hand-back whose minute retry is due in the step control takes the
  boiler again: only the retake goes out, never the lowest, the release and the new setpoint in
  one step.

The rig — the gateway, VT's zones and the boiler signals as fakes — is the control tests'.
"""

# The control tests' ``rig`` fixture is imported by name: each test's parameter of that name is
# the fixture pytest injects, not a redefinition.
# ruff: noqa: F811

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.vtherm_smart_boiler.core.alarms import UNKNOWN_HOLD_S
from custom_components.vtherm_smart_boiler.core.guards import PREVIOUS_EXEMPT_S

from .test_control import (  # the rig fixture comes with them
    EXPECTED,
    LOWEST,
    TIMEOUT_PATH,
    FakeNumber,
    FakeSwitch,
    Rig,
    alarm,
    in_frost,
    low_setpoint_off,  # noqa: F401
    rig,  # noqa: F401
    room,
    start,
    switch_method,
    unit_of,
)

pytestmark = pytest.mark.usefixtures("enable_custom_integrations")

SET_BACK = timedelta(hours=1)


async def set_back(rig: Rig) -> None:
    """The wall clock set back an hour (a correction, a wrong time server)."""
    rig.freezer.move_to(datetime.now(UTC) - SET_BACK)


async def steps(rig: Rig, seconds: float, step: float = 10.0) -> None:
    """The timer's steps after a set-back — the scheduler, its moments an hour ahead, left
    behind — with the gateway's reports."""
    unit = unit_of(rig)
    elapsed = 0.0
    while elapsed < seconds:
        rig.freezer.tick(step)
        elapsed += step
        rig.live()
        await unit._async_timer(datetime.now(UTC))
        await rig.hass.async_block_till_done(wait_background_tasks=True)


async def test_a_clock_set_back_does_not_block_control_by_the_monitoring_period(
    rig: Rig,
) -> None:
    """PB-28: no monitoring period configured, the clock set back an hour soon after the start:
    the start "later than now" counts from now — control is not blocked for the hour."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    await set_back(rig)
    await steps(rig, 30.0)
    shown = rig.state("sensor", "control_state")
    assert "monitoring_period" not in shown.attributes["blockers"]
    assert shown.state == "heating"


async def test_a_clock_set_back_does_not_stretch_the_frost_alarms_hold(rig: Rig) -> None:
    """PB-28: the frost alarm raised, then its only room unknown and the clock set back an hour:
    held for its hour from the set-back, then unknown — not for two hours."""
    await start(rig, topology="gateway_standalone")
    room(rig, 4.0)
    await rig.advance(10)
    assert in_frost(rig) == "on"
    rig.zones.set("living", "unavailable", current_temperature=None)
    await rig.advance(10)
    await set_back(rig)
    await steps(rig, UNKNOWN_HOLD_S - 120.0, step=60.0)
    assert in_frost(rig) == "on"  # held
    await steps(rig, 180.0, step=60.0)
    assert in_frost(rig) == "unknown"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_clock_set_back_does_not_delay_the_timeout_hand_backs_alarm(rig: Rig) -> None:
    """PB-28: a timeout hand-back the device's timer does not release (1 min), the clock set back
    an hour 30 s after it: ``hand_back_failed`` rises the device's timeout and three minutes after
    the set-back, not an hour later."""
    number = FakeNumber(rig.hass, value=45.0)
    number.register()
    await start(
        rig,
        **TIMEOUT_PATH,
        setpoint_entity=number.entity_id,
        confirmed_entity=number.entity_id,
        topology="virtual",
    )
    await rig.switch(True)
    await rig.advance(30)
    await rig.switch(False)
    await rig.advance(30)
    await set_back(rig)
    late = 60.0 + 180.0
    await steps(rig, late - 10.0)
    assert alarm(rig) == "off"
    await steps(rig, 20.0)
    assert alarm(rig) == "on"


@pytest.mark.usefixtures("low_setpoint_off")
async def test_a_clock_set_back_does_not_extend_the_external_switchs_exemption(rig: Rig) -> None:
    """PB-28: the external-control switch turned on and never shown on, the clock set back an
    hour a minute later: its five minutes' exemption counts from the set-back — the plugin
    steps aside then, not an hour later."""
    number = FakeNumber(rig.hass)
    number.register()
    external = FakeSwitch(
        rig.hass, entity_id="input_boolean.fake_external", on=False, stuck_off=True
    )
    external.register()
    await start(rig, **switch_method(number, external.entity_id, "held"))
    # Past the five minutes the unit's own start counts as a trace — and an hour more: a start
    # "later than now" after the set-back would count as one too (the cautious reading).
    await rig.advance(310 + 3600, step=60)
    await rig.switch(True)
    assert external.writes == [True]
    await rig.advance(60)
    await set_back(rig)
    await steps(rig, PREVIOUS_EXEMPT_S - 10.0)
    assert rig.state("sensor", "control_state").state != "handed_back"  # still exempt
    await steps(rig, 30.0)
    state = rig.state("sensor", "control_state")
    assert state.state == "handed_back"
    assert state.attributes["latched_by"] == ["outside_change"]


async def test_an_owed_retry_and_a_retake_never_go_out_in_one_step(rig: Rig) -> None:
    """PB-31 (probe D): switched off, the gateway keeps the override — the hand-back stays owed,
    tried again every minute. Switched on again when a retry is due: that step writes only the
    retake (the setpoint, heating on), never the lowest, the release and the new setpoint
    together; the retake folds the debt."""
    await start(rig)
    await rig.switch(True)
    await rig.advance(20)
    rig.gateway.ignore_release = True
    await rig.switch(False)
    unit = unit_of(rig)
    assert unit.hand_back_owed
    retry = len(rig.gateway.calls)
    await rig.advance(60)
    assert rig.gateway.calls[retry:] == [("ch", True), ("setpoint", 0.0)]  # the minute retry
    await rig.advance(50)
    count = len(rig.gateway.calls)
    rig.freezer.tick(10)  # the next retry due: switched on in that step
    rig.live()
    await rig.switch(True)
    step = rig.gateway.calls[count:]
    assert ("setpoint", 0.0) not in step
    assert ("setpoint", LOWEST) not in step
    assert step[:2] == [("setpoint", EXPECTED), ("ch", True)]
    assert not unit.hand_back_owed
