"""The modulation cap's unit on the Home Assistant side (I13.7): what it writes and when, with a
writer of the test's own — the failures, the store, a clock set back, a release with nothing to
release it through."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import pytest
from homeassistant.core import HomeAssistant

from custom_components.vtherm_smart_boiler.control_config import ControlOptions, parse_control
from custom_components.vtherm_smart_boiler.core.installation import (
    Boiler,
    BoilerClass,
    Circuit,
    Installation,
)
from custom_components.vtherm_smart_boiler.modulation_cap import (
    CAP_NO_TARGET,
    CAP_RETRY_S,
    CAP_WRITE_FAILED,
    CapStatus,
    CapUnit,
)
from custom_components.vtherm_smart_boiler.transport.writers import CapWriter, WriteError

INSTALLATION = Installation(Boiler(BoilerClass.FLOW_SETPOINT), (Circuit("main"),))
GATEWAY = {"write_path": "opentherm_gw", "gateway_id": "gw", "modulation_cap": True}
T = 1_000_000.0


@dataclass
class Writer:
    """A cap writer that records its writes; ``fail`` makes the next ones fail with it."""

    read_back: str | None = None
    fail: BaseException | None = None
    calls: list[Any] = field(default_factory=list)

    @property
    def services(self) -> frozenset[tuple[str, str]]:
        return frozenset()

    async def write_cap(self, level: int, timeout_s: float | None = None) -> float:
        self.calls.append(level)
        if self.fail is not None:
            raise self.fail
        return float(level)

    async def release(self, timeout_s: float | None = None) -> float | None:
        self.calls.append("release")
        if self.fail is not None:
            raise self.fail
        return 100.0 if self.read_back else None


def unit(
    hass: HomeAssistant,
    writer: Writer | None,
    section: dict[str, Any] = GATEWAY,
    saved: bool | None = True,
) -> CapUnit:
    options: ControlOptions = parse_control(section, INSTALLATION, None)

    async def save() -> bool | None:
        return saved

    def factory(_hass: HomeAssistant, _options: ControlOptions) -> CapWriter | None:
        return writer

    return CapUnit(hass, options, save, factory)


async def follow(cap: CapUnit, now: float, **changes: Any) -> None:
    inputs: dict[str, Any] = {
        "holding": True,
        "hot_water": False,
        "flame": False,
        "flow": 40.0,
        "setpoint": 40.0,
        "min_power_kw": None,
        "max_power_kw": None,
    }
    await cap.async_follow(now, **(inputs | changes))


async def test_a_failing_write_waits_a_minute_and_is_logged_once(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    writer = Writer(fail=WriteError("gone"))
    cap = unit(hass, writer)
    with caplog.at_level(logging.DEBUG):
        await follow(cap, T)
        await follow(cap, T + CAP_RETRY_S - 1)
        await follow(cap, T + CAP_RETRY_S)
    assert writer.calls == [70, 70]
    assert cap.status == CapStatus(None, CAP_WRITE_FAILED)
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warned) == 1
    writer.fail = None
    await follow(cap, T + 2 * CAP_RETRY_S)
    assert cap.status == CapStatus(70.0, "applied")
    assert "work again" in caplog.text


async def test_no_cap_without_the_store(hass: HomeAssistant) -> None:
    """PB-16: the store cannot record that the boiler may hold a cap: none is written."""
    writer = Writer()
    cap = unit(hass, writer, saved=False)
    await follow(cap, T)
    assert writer.calls == []
    assert not cap.in_force
    assert cap.status.state == CAP_WRITE_FAILED


async def test_a_release_with_nothing_to_release_it_through(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """The store says a cap may be in force, and the options give it no target: told, and
    forgotten — there is nothing to write it to."""
    section = {"write_path": "entity", "setpoint_entity": "number.flow", "modulation_cap": True}
    cap = unit(hass, None, section)
    cap.in_force = True
    await follow(cap, T)
    assert not cap.in_force
    assert cap.status == CapStatus(state=CAP_NO_TARGET)
    assert "nothing is set up to release it" in caplog.text


async def test_a_bug_in_a_release_never_stops_a_hand_back(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    writer = Writer(fail=RuntimeError("boom"))
    cap = unit(hass, writer)
    cap.in_force = True
    await cap.async_release(T)
    assert cap.in_force  # kept: tried again a minute later
    assert "Releasing the modulation cap failed" in caplog.text
    writer.fail = None
    await cap.async_release(T + 1)
    assert writer.calls == ["release"]
    await cap.async_release(T + CAP_RETRY_S)
    assert not cap.in_force


async def test_a_lapsing_cap_whose_release_fails_is_not_written_again(hass: HomeAssistant) -> None:
    """On an entity whose values lapse, a release that fails is not sent again: the cap goes
    by itself within a minute."""
    section = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "expiring",
        "modulation_cap": True,
        "modulation_cap_entity": "number.cap",
    }
    writer = Writer(read_back="number.cap", fail=WriteError("gone"))
    cap = unit(hass, writer, section)
    cap.in_force = True
    await cap.async_release(T)
    assert writer.calls == ["release"]
    assert not cap.in_force


async def test_switched_off_with_a_cap_still_to_release_says_so(hass: HomeAssistant) -> None:
    writer = Writer(fail=WriteError("gone"))
    section = {"write_path": "opentherm_gw", "gateway_id": "gw"}
    cap = unit(hass, writer, section)
    cap.in_force = True
    await follow(cap, T)
    assert cap.status == CapStatus(state=CAP_WRITE_FAILED)
    writer.fail = None
    await follow(cap, T + CAP_RETRY_S)
    assert cap.status == CapStatus()
    assert not cap.in_force


async def test_a_clock_set_back_writes_at_once(hass: HomeAssistant) -> None:
    writer = Writer()
    cap = unit(hass, writer)
    await follow(cap, T)
    await follow(cap, T - 100)  # the clock set back: the repeat is due
    assert writer.calls == [70, 70]
    writer.fail = WriteError("gone")
    await follow(cap, T + 400)
    await follow(cap, T + 300)  # set back past the failure: written again at once
    assert writer.calls == [70, 70, 70, 70]


async def test_a_release_the_entity_shows_later_is_done_without_writing_again(
    hass: HomeAssistant,
) -> None:
    """A held entity that shows the release only at a later step: done then, not written
    again."""
    section = {
        "write_path": "entity",
        "setpoint_entity": "number.flow",
        "write_type": "held",
        "modulation_cap": True,
        "modulation_cap_entity": "number.cap",
    }
    hass.states.async_set("number.cap", "50")
    writer = Writer(read_back="number.cap")
    cap = unit(hass, writer, section)
    cap.in_force = True
    await cap.async_release(T)
    assert cap.in_force  # not shown yet
    hass.states.async_set("number.cap", "100")
    await cap.async_release(T + 10)
    assert not cap.in_force
    assert writer.calls == ["release"]
