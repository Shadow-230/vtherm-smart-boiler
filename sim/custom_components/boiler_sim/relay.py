"""A relay on an on/off boiler's room-thermostat terminals (X8; Z3 rule 7): its contact is the
boiler's heat demand. Its own settings — which the plugin cannot read — are the model's:

- its state after a power cut: off, on, or the last one (Tasmota's PowerOnState, a Shelly's
  initial state, ESPHome's restore mode, Zigbee's power-on behaviour);
- an optional switch-off timer, started by an "on": Tasmota's PulseTime restarts on every
  "on"; whether a Shelly's auto-off does is not documented (``timer_restarts_on_repeat``);
- an optional ``assumed_state``: an optimistic entity whose state confirms nothing.

What happens to it, for the scenarios: a restart — unavailable for ``RESTART_UNAVAILABLE_S``
(test-only), its contact open, then in its state after a power cut; a restart Home Assistant
does not see (a relay that reports no availability) — that state at once, with no unavailable
phase (the user's answer D); a Wi-Fi loss — unavailable for a set time, its contact and its
timer going on as they were; another controller switching it while it stays available — an
automation or its own button (answer C), once or again and again (answers L, N); and its state
not reported at all ("unknown"). Every change the relay makes itself is counted, so the Home
Assistant entity can give it a context of its own, never the plugin's.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

RESTART_UNAVAILABLE_S = 10.0  # test-only (Z3 rule 7)


class StartUp(StrEnum):
    """The relay's state after a power cut, its own setting."""

    OFF = "off"
    ON = "on"
    LAST = "last"


@dataclass
class RelayModel:
    start_up: StartUp = StartUp.OFF
    off_timer_s: float | None = None
    timer_restarts_on_repeat: bool = True
    assumed_state: bool = False
    on: bool = False
    available: bool = True
    known: bool = True  # False: it reports no state ("unknown") while available
    away_until: float | None = None
    restarting: bool = False  # the away phase ends in the state after a power cut
    before: bool = False  # its state when the restart began
    timer_from: float | None = None
    own_changes: int = 0  # changes it made itself; each gets a context of its own
    commands: list[tuple[float, bool]] = field(default_factory=list)

    def _set(self, t: float, on: bool) -> None:
        """An "on" starts the timer — again at every "on" where it restarts on a repeat; "off"
        stops it."""
        if on and self.off_timer_s is not None:
            if not self.on or self.timer_restarts_on_repeat or self.timer_from is None:
                self.timer_from = t
        elif not on:
            self.timer_from = None
        self.on = on

    def command(self, t: float, on: bool) -> None:
        """A command from Home Assistant; one that cannot reach it is lost."""
        self.commands.append((t, on))
        if self.available:
            self._set(t, on)

    def switch(self, t: float, on: bool) -> None:
        """Another controller — an automation, its own button — while it stays available."""
        if self.available:
            self._set(t, on)
            self.own_changes += 1

    def _start_up_state(self, last: bool) -> bool:
        if self.start_up is StartUp.LAST:
            return last
        return self.start_up is StartUp.ON

    def restart(self, t: float, reported: bool = True) -> None:
        """A power cut of the relay. ``reported``: Home Assistant sees it unavailable for a while,
        its contact open; otherwise it is found in its state after a power cut at once."""
        last = self.on
        if reported:
            self.available = False
            self.away_until = t + RESTART_UNAVAILABLE_S
            self.restarting = True
            self.before = last
            self.on = False
            self.timer_from = None
            return
        self.timer_from = None
        self._set(t, self._start_up_state(last))
        self.own_changes += 1

    def wifi_loss(self, t: float, seconds: float) -> None:
        """Out of reach for ``seconds``, its contact and its timer going on as they were."""
        self.available = False
        self.away_until = max(self.away_until or t, t + seconds)

    def advance(self, t: float) -> None:
        """Its own time: back from a restart or a Wi-Fi loss, and its timer."""
        if self.away_until is not None and t >= self.away_until:
            self.available = True
            self.away_until = None
            if self.restarting:
                self.restarting = False
                self._set(t, self._start_up_state(self.before))
                self.own_changes += 1
        timer, since = self.off_timer_s, self.timer_from
        if self.on and timer is not None and since is not None and t - since >= timer:
            self.on = False
            self.timer_from = None
            self.own_changes += 1

    @property
    def contact(self) -> bool:
        """Whether the boiler's room-thermostat terminals are closed: heat demand."""
        return self.on
