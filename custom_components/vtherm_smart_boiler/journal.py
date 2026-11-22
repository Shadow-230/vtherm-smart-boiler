"""The plugin's journal kept for the Boiler page (``docs/en/development/plans/plan-0.2-i10.md``,
I10.6): each change of control's state or of the monitor's alarms is looked at and journaled by
``core.journal``, with the plugin's starts and stops and each settings save — from the page or
the settings. Kept in a store of its own beside the entry's, written a minute after a change and
at once when the entry unloads; Home Assistant writes what is pending when it stops. The journal
only watches: a failure in it is logged and changes nothing else.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import JOURNAL_STORE_VERSION, journal_store_key
from .core.controller import ControlMode
from .core.journal import (
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
from .core.signal_check import OutdoorStatus

if TYPE_CHECKING:
    from .coordinator import SmartBoilerCoordinator

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY_S = 60.0
# A save the page started is the one the settings report within this time (I10.4's save drives
# the options flow, whose listener follows at once).
PAGE_SAVE_S = 60.0
# The modes in which control does not hold the boiler (``core.boiler_call``).
NOT_HOLDING = frozenset({ControlMode.DISABLED, ControlMode.NOT_ALLOWED, ControlMode.HANDED_BACK})


def journal_store(hass: HomeAssistant, entry_id: str) -> Store[dict[str, Any]]:
    return Store(hass, JOURNAL_STORE_VERSION, journal_store_key(entry_id), atomic_writes=True)


def observed(coordinator: SmartBoilerCoordinator) -> Observed:
    """One look at control and the alarms, as their entities show them: each alarm by the key of
    its entity, with its level while active, ``None`` while it cannot be judged."""
    alarms: dict[str, str | None] = {}
    data = coordinator.data
    if data is not None:
        for kind, alarm in data.alarms.items():
            if alarm.active is None:
                alarms[f"alarm_{kind.value}"] = None
            elif alarm.active:
                level = "alarm" if alarm.level is None else alarm.level.value
                alarms[f"alarm_{kind.value}"] = level
        if coordinator.long_run.found is not None:
            alarms["long_burn"] = "warning"
        check = coordinator.outdoor_check(data.now)
        if check is None or check.status is OutdoorStatus.UNKNOWN:
            alarms["outdoor_sensor_problem"] = None
        elif check.status is not OutdoorStatus.OK:
            alarms["outdoor_sensor_problem"] = "warning"
    control = coordinator.control
    if control is None:
        return Observed(False, None, None, None, (), alarms)
    status = control.status
    for raised in status.alarms:
        alarms[f"alarm_{raised.value}"] = "alarm"
    for unknown in status.unknown_alarms:
        alarms.setdefault(f"alarm_{unknown.value}", None)
    return Observed(
        controlling=status.mode not in NOT_HOLDING,
        called=status.boiler_called,
        call_reason=status.call_reason,
        # The setpoint written, to 0.1 K as its sensor shows it.
        water=None if status.requested is None else round(status.requested, 1),
        reasons=tuple(status.reasons),
        alarms=alarms,
    )


class Journal:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self.hass = hass
        self._store = journal_store(hass, entry_id)
        self._entries: list[Entry] = []
        self._state = JournalState()
        self._failing = False
        # The page's save waiting for the settings' report: when, and what it changed.
        self._page_save: tuple[float, tuple[str, ...]] | None = None
        self._coordinator: SmartBoilerCoordinator | None = None

    @property
    def entries(self) -> tuple[Entry, ...]:
        return tuple(self._entries)

    async def async_load(self) -> None:
        """Read what the last runs kept; a store that cannot be read starts an empty journal."""
        try:
            raw = await self._store.async_load()
        except Exception:  # a damaged journal must not stop the plugin
            _LOGGER.warning("The journal could not be read; it starts empty", exc_info=True)
            raw = None
        stored = raw.get("entries") if isinstance(raw, dict) else None
        read = (entry_from_stored(item) for item in stored) if isinstance(stored, list) else ()
        self._entries = prune((entry for entry in read if entry is not None), self._now())

    @callback
    def async_follow(self, coordinator: SmartBoilerCoordinator) -> CALLBACK_TYPE:
        """Journal the start, then every change of the monitor's data and control's state, and
        the stop of Home Assistant; returns what stops following."""
        self._coordinator = coordinator
        self._add([Entry(self._now(), Kind.STARTED)])

        @callback
        def look() -> None:
            try:
                self._state, entries = follow(self._state, observed(coordinator), self._now())
                self._add(entries)
            except Exception:  # the journal never disturbs what it watches
                if not self._failing:
                    _LOGGER.exception("The journal could not follow a change")
                self._failing = True
            else:
                self._failing = False

        @callback
        def stopping(_event: Event) -> None:
            self._add([*self._handed_back_at_stop(), Entry(self._now(), Kind.STOPPED)])

        unsubs = [
            coordinator.async_add_listener(look),
            self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, stopping),
        ]
        if coordinator.control is not None:
            unsubs.append(coordinator.control.async_add_listener(look))
        look()

        @callback
        def stop_following() -> None:
            for unsub in unsubs:
                unsub()

        return stop_following

    def note_page_save(self, changed: Iterable[str]) -> None:
        """The page is saving the settings: the save the settings report next is the page's."""
        self._page_save = (self._now(), tuple(changed))

    def forget_page_save(self) -> None:
        self._page_save = None

    def settings_saved(self, changed: Iterable[str]) -> None:
        """The settings were saved — from the page when it noted a save just before, naming
        what it changed, else from the settings, naming the sections that changed."""
        now = self._now()
        page, self._page_save = self._page_save, None
        if page is not None and now - page[0] <= PAGE_SAVE_S:
            self._add([settings_saved(now, "page", page[1])])
        else:
            self._add([settings_saved(now, "settings", changed)])

    async def async_stop(self) -> None:
        """The entry unloads: the stop is journaled and everything written at once."""
        self._add([*self._handed_back_at_stop(), Entry(self._now(), Kind.STOPPED)], save=False)
        await self._store.async_save(self._stored())

    def _handed_back_at_stop(self) -> list[Entry]:
        """The stop's own hand-back — an unload, a reload, Home Assistant stopping — which
        control makes before the stop is journaled, without a look of its own: journaled when
        the last look saw control holding the boiler and nothing is owed (J4 I10.10, F18). One
        still owed is not said to be made; its repair issue tells."""
        last = self._state.last
        coordinator = self._coordinator
        control = None if coordinator is None else coordinator.control
        if last is None or not last.controlling or control is None or control.hand_back_owed:
            return []
        self._state = JournalState(replace(last, controlling=False), None)
        return [Entry(self._now(), Kind.HANDED_BACK)]

    def _add(self, entries: Iterable[Entry], *, save: bool = True) -> None:
        added = list(entries)
        if not added:
            return
        self._entries = prune([*self._entries, *added], self._now())
        if save:
            self._store.async_delay_save(self._stored, SAVE_DELAY_S)

    def _stored(self) -> dict[str, Any]:
        return {"entries": [entry_to_stored(entry) for entry in self._entries]}

    @staticmethod
    def _now() -> float:
        return dt_util.utcnow().timestamp()
