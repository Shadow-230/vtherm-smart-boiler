"""Current values: boiler signals, VT zones and weather, each with its freshness."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .signals import Signal

type Value = float | bool


@dataclass(frozen=True, slots=True)
class Reading:
    """The last value of a signal and when its source last reported it, changed or not.

    ``value`` is ``None`` when the source is unknown or unavailable. ``reported_at`` and
    ``changed_at`` are in seconds since the Unix epoch.
    """

    value: Value | None = None
    reported_at: float | None = None
    # When the source's value — or anything it reports with it — last changed (I6): a report
    # with nothing changed since is a repeat. ``None`` where not known.
    changed_at: float | None = None

    def age(self, now: float) -> float | None:
        """Seconds since the last report; ``None`` if never reported."""
        return None if self.reported_at is None else max(0.0, now - self.reported_at)

    def is_fresh(self, now: float, max_age: float | None) -> bool:
        """Known and, when ``max_age`` is set, reported within ``max_age`` seconds."""
        if self.value is None or self.reported_at is None:
            return False
        return max_age is None or now - self.reported_at <= max_age


UNKNOWN = Reading()

# One meaning each, wherever a zone's valve opening or duty cycle is judged.
ZONE_OPEN = 0.05  # above this the zone takes heat: it calls, it heats
ZONE_SATURATED = 0.95  # this open, the zone cannot give its room more


@dataclass(frozen=True, slots=True)
class BoilerSnapshot:
    """Boiler signals at time ``t``; a signal the user did not map is simply absent."""

    t: float
    readings: Mapping[Signal, Reading] = field(default_factory=dict)

    def reading(self, signal: Signal) -> Reading:
        return self.readings.get(signal, UNKNOWN)

    def is_mapped(self, signal: Signal) -> bool:
        return signal in self.readings

    def _usable(self, signal: Signal, max_age: float | None) -> Value | None:
        reading = self.reading(signal)
        if max_age is not None and not reading.is_fresh(self.t, max_age):
            return None
        return reading.value

    def number(self, signal: Signal, max_age: float | None = None) -> float | None:
        """Numeric value, or ``None`` if unknown or, with ``max_age``, not fresh."""
        value = self._usable(signal, max_age)
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return float(value)

    def flag(self, signal: Signal, max_age: float | None = None) -> bool | None:
        """Binary value, or ``None`` if unknown or, with ``max_age``, not fresh."""
        value = self._usable(signal, max_age)
        return value if isinstance(value, bool) else None


@dataclass(frozen=True, slots=True)
class ZoneState:
    """One VT thermostat as the plugin sees it: read from the thermostat VT handed to the
    plugin's feature manager (``vtherm_api``, I12.7), never from VT's climate entity.

    ``heating_enabled``: the zone is in a mode that may heat (``None``: its mode is not known —
    VT has not handed the thermostat over, or a mode the plugin does not read); ``auto_mode``:
    "auto" or heat_cool, where its action says whether it heats. ``calling``: its heater or valve
    is active now (VT's action). ``device_active``: VT's own view of its devices.
    ``on_percent``: the duty VT applied to its devices at its last cycle start, valve update or
    stop (VT's power hook), a fraction from 0 to 1; ``valve_open``: for a valve, the opening VT
    applied then, 0 to 1. Both are ``None`` until VT's first such call after the plugin starts,
    and for a plain over_climate, which VT never reports. ``reported_at``: when the plugin read
    the thermostat — VT's live values, fresh when read. ``started``: VT has started the
    thermostat — it called the manager's ``refresh_state``, which it does only once the
    thermostat is ready; ``False`` for a zone VT has not handed over (the link always sets it).
    ``temperature_at``: when VT last measured the room (VT's clock). ``room_sensor_lost``: the
    room's temperature is not trusted now (I12, decision 8; ``core.zones.room_trusted``) — VT
    runs it in safety mode, its thermometer is unavailable, or VT has not measured it since the
    plugin started — so it judges nothing of the curve. ``window_open``: VT holds the zone off
    for a window, its automatic window detection says open, or the window sensor VT reads is on.
    ``cycle_s``: the zone's cycle in seconds, VT's ``cycle_min`` in its ``entry_infos``; ``None``
    where not known — the comfort correction's pace then takes a cautious default (I13.3).
    """

    zone_id: str
    temperature: float | None = None
    target: float | None = None
    heating_enabled: bool | None = None
    calling: bool | None = None
    on_percent: float | None = None
    valve_open: float | None = None
    reported_at: float | None = None
    auto_mode: bool = False
    device_active: bool | None = None
    started: bool = True
    temperature_at: float | None = None
    room_sensor_lost: bool = False
    window_open: bool = False
    cycle_s: float | None = None

    @property
    def deficit(self) -> float | None:
        """Target minus temperature in kelvin; positive when the room is too cold."""
        if self.temperature is None or self.target is None:
            return None
        return self.target - self.temperature

    @property
    def fully_open(self) -> bool:
        """As open as the zone gets: ``ZONE_SATURATED`` or more. VT's cap on the duty cycle is
        not seen (I12.7): ``vtherm_api`` does not declare it, and the request VT's power hook
        tells is already capped, so a zone VT caps lower never counts as fully open — no rise of
        the water on a signal the plugin cannot read."""
        demand = self.demand
        return demand is not None and demand >= ZONE_SATURATED

    @property
    def demand(self) -> float | None:
        """How hard the zone's own controller works, 0 to 1: valve opening, else on-percent."""
        if self.valve_open is not None:
            return self.valve_open
        return self.on_percent

    def is_fresh(self, now: float, max_age: float | None) -> bool:
        """Read, and, with ``max_age``, read within it: VT keeps the thermostat's values live, so
        a zone is fresh when read (I12.7); how old the room's measurement is, VT's safety mode
        and the rooms' trust tell (``room_sensor_lost``)."""
        if self.reported_at is None:
            return False
        return max_age is None or now - self.reported_at <= max_age

    def is_known(self, now: float, max_age: float | None) -> bool:
        """Its mode is known, its data fresh, and VT has started it. A thermostat VT has not
        started is unknown whatever its mode, during the recognition period and after it: VT
        calls the manager's ``refresh_state`` only once the thermostat is ready (VT 10.6.5
        ``base_thermostat.py``), and a mode before then is not the user's "off" (SB-02, decision
        1 of 0.2.3). A started zone in "off" is known without demand (S-34)."""
        if self.heating_enabled is None or not self.is_fresh(now, max_age):
            return False
        return self.started

    def has_reported(self, now: float, max_age: float | None) -> bool:
        """VT has started it, and its mode and data are known: what the recognition period
        waits for (decision 3) — the same as known."""
        return self.is_known(now, max_age)


@dataclass(frozen=True, slots=True)
class WeatherReading:
    """Current outdoor temperature from a weather entity (°C)."""

    temperature: float | None = None
    reported_at: float | None = None
