"""The modulation cap on the Home Assistant side (I13.7): applied while control holds the boiler,
released at every hand-back, at a stop, while hot water runs or is not known, when the user
switches it off, and for three hours after the boiler fell short at it.

The core decides (``core.modulation_cap``); this unit writes through the cap's own writer
(``transport.writers.CapWriter``), apart from the setpoint's guards: nothing it does holds
heating back, and a write that fails is only shown, and sent again a minute later. Before a cap
goes to the boiler the control store records that the boiler may hold one, so a crash leaves the
next start a release to make; a store that cannot be written keeps the cap from being written
(as control's own writes, PB-16). A release is done once its write went through and, where the
cap's number entity holds its value (ESPHome), once the entity shows it — until then it is sent
again every minute. One whose value lapses (EMS-ESP's ``selburnpow``, within about a minute) is
released by one write, which goes whatever comes of it: written again it would keep writing to
the boiler after the hand-back, and the value lapses anyway. The gateways read nothing back
here: their ``MM=`` cleared passes the thermostat's own value on, or 100 % stand-alone, which
says nothing of ours.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .control_config import ControlOptions, WritePath, cap_repeat_s
from .core.guards import WriteType
from .core.modulation_cap import (
    READ_BACK_WAIT_S,
    CapInputs,
    CapReason,
    CapState,
    cap_floor,
    cap_level,
    cap_step,
    read_back_shows,
    write_due,
)
from .transport.writers import CapWriter, WriteError, make_cap_writer
from .units import parse_number

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# The cap's states besides ``CapReason``'s: no target for it (on the entity path no number
# entity, or one in another role), its write failing, and a read-back that does not show it.
CAP_NO_TARGET = "no_target"
CAP_WRITE_FAILED = "write_failed"
CAP_NOT_SHOWN = "not_shown"
# A write that failed, or a release its read-back does not show yet, is sent again this often.
CAP_RETRY_S = 60.0

type CapWriterFactory = Callable[[HomeAssistant, ControlOptions], CapWriter | None]


@dataclass(frozen=True, slots=True)
class CapStatus:
    """What control's state shows: the cap in force now, in % (``None``: none), and why it is
    applied or released (``None`` where the cap is switched off and none is left)."""

    level: float | None = None
    state: str | None = None


def _since(moment: float | None, now: float) -> float | None:
    """How long ago ``moment`` was; ``None`` where never, or ahead of ``now`` (a clock set
    back)."""
    if moment is None or moment > now:
        return None
    return now - moment


class CapUnit:
    """The cap for one control unit. ``in_force``: the boiler may hold a cap of ours — stored
    with control's state, and released at the next start."""

    def __init__(
        self,
        hass: HomeAssistant,
        options: ControlOptions,
        save: Callable[[], Awaitable[bool | None]],
        factory: CapWriterFactory = make_cap_writer,
    ) -> None:
        self._hass = hass
        self._options = options
        self._save = save
        self._factory = factory
        self._writer: CapWriter | None = None
        self._built = False
        self.in_force = False
        self._written: float | None = None  # the cap last written in this run
        self._written_at: float | None = None
        self._released_at: float | None = None  # a release written, its read-back awaited
        self._failed_at: float | None = None
        self._expected: float | None = None  # what the read-back must show
        self._expected_at: float | None = None
        self._state = CapState()
        self.status = CapStatus()
        self._warned = False
        # A number entity whose values lapse (declared as the setpoint entity): its cap goes by
        # itself within about a minute once it is no longer written.
        self._lapses = (
            options.write_path is WritePath.ENTITY and options.write_type is WriteType.EXPIRING
        )

    def _target(self) -> CapWriter | None:
        if not self._built:
            self._built = True
            self._writer = self._factory(self._hass, self._options)
        return self._writer

    async def async_follow(
        self,
        now: float,
        *,
        holding: bool,
        hot_water: bool | None,
        flame: bool | None,
        flow: float | None,
        setpoint: float | None,
        min_power_kw: float | None,
        max_power_kw: float | None,
    ) -> None:
        """One control step: the cap applied, or released, as the core decides."""
        requested = self._options.modulation_cap_pct
        if requested is None:
            await self.async_release(now)
            # Switched off: nothing shown, unless a cap of ours is still to be released.
            self.status = CapStatus(state=CAP_WRITE_FAILED) if self.in_force else CapStatus()
            return
        writer = self._target()
        if writer is None:
            await self.async_release(now)
            self.status = CapStatus(state=CAP_NO_TARGET)
            return
        level = cap_level(requested, cap_floor(min_power_kw, max_power_kw))
        inputs = CapInputs(
            now,
            holding,
            hot_water,
            flame=flame,
            flow=flow,
            setpoint=setpoint,
            capped=self._written is not None,
        )
        self._state, reason = cap_step(self._state, inputs, level)
        if reason is CapReason.APPLIED:
            await self._apply(writer, now, level)
        else:
            await self.async_release(now)
        self.status = self._shown(reason, now)

    def _shown(self, reason: CapReason, now: float) -> CapStatus:
        level = self._written
        if self._failed_at is not None:
            return CapStatus(level, CAP_WRITE_FAILED)
        waited = _since(self._expected_at, now)
        if self._read_back() is False and waited is not None and waited >= READ_BACK_WAIT_S:
            return CapStatus(level, CAP_NOT_SHOWN)
        return CapStatus(level, reason.value)

    async def _apply(self, writer: CapWriter, now: float, level: int) -> None:
        if self._retry_wait(now):
            return
        if not write_due(
            self._written, float(level), self._written_at, now, cap_repeat_s(self._options)
        ):
            return
        if not self.in_force:
            # Recorded before the write: a crash then leaves the next start a release to make.
            self.in_force = True
            if await self._save() is False:
                self.in_force = False
                self._failed(now, "the control state could not be stored")
                return
        try:
            shown = await writer.write_cap(level)
        except WriteError as err:
            self._failed(now, str(err))
            return
        self._written = float(level)
        self._written_at = now
        self._released_at = None
        self._wrote(now, shown)

    async def async_release(self, now: float, timeout_s: float | None = None) -> None:
        """The device's own maximum again, where the boiler may hold a cap of ours. Never
        raises: a hand-back must not stop on it."""
        if not self.in_force:
            return
        writer = self._target()
        if writer is None:
            _LOGGER.warning(
                "A modulation cap of the plugin's may still be in force, and nothing is set up "
                "to release it: check the boiler's maximum modulation"
            )
            self._forget()
            return
        if self._released_at is not None:
            if self._read_back() is not False:
                self._forget()
                return
            waited = _since(self._released_at, now)
            if waited is not None and waited < CAP_RETRY_S:
                return
        if self._retry_wait(now):
            return
        try:
            shown = await writer.release(timeout_s)
        except WriteError as err:
            self._failed(now, str(err))
            self._lapse()
            return
        except Exception:  # a bug must not stop a hand-back: tried again a minute later
            _LOGGER.exception("Releasing the modulation cap failed")
            self._failed_at = now
            self._lapse()
            return
        if self._lapses:
            self._forget()  # one write: the value lapses by itself anyway
            return
        self._written = None
        self._written_at = None
        self._released_at = now
        self._wrote(now, shown)
        if self._read_back() is not False:
            self._forget()

    def _lapse(self) -> None:
        """A release that failed on an entity whose values lapse: never sent again — the cap
        goes by itself within about a minute."""
        if self._lapses:
            self._forget()

    def _retry_wait(self, now: float) -> bool:
        """A write failed less than ``CAP_RETRY_S`` ago: wait."""
        waited = _since(self._failed_at, now)
        return waited is not None and waited < CAP_RETRY_S

    def _wrote(self, now: float, shown: float | None) -> None:
        if self._warned:
            _LOGGER.info("The modulation cap's writes work again")
        self._failed_at = None
        self._warned = False
        if shown != self._expected or self._expected_at is None:
            self._expected_at = now
        self._expected = shown

    def _failed(self, now: float, message: str) -> None:
        self._failed_at = now
        if self._warned:
            _LOGGER.debug("The modulation cap's write failed again: %s", message)
            return
        _LOGGER.warning("The modulation cap's write failed; sent again in a minute: %s", message)
        self._warned = True

    def _read_back(self) -> bool | None:
        """Whether the cap's read-back shows what was last written; ``None``: nothing to judge
        — no read-back, or none reported."""
        entity = None if self._writer is None else self._writer.read_back
        if entity is None or self._expected is None:
            return None
        state = self._hass.states.get(entity)
        return read_back_shows(None if state is None else parse_number(state.state), self._expected)

    def _forget(self) -> None:
        self.in_force = False
        self._written = None
        self._written_at = None
        self._released_at = None
        self._expected = None
        self._expected_at = None
