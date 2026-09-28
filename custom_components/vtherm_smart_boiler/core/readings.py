"""Current values: boiler signals, VT zones and weather, each with its freshness."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .signals import SIGNAL_SPECS, Signal, SignalKind

type Value = float | bool


@dataclass(frozen=True, slots=True)
class Reading:
    """The last value of a signal and when its source last reported it, changed or not.

    ``value`` is ``None`` when the source is unknown or unavailable. ``reported_at`` is in
    seconds since the Unix epoch.
    """

    value: Value | None = None
    reported_at: float | None = None

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


def plausible_reading(signal: Signal, value: Value | None, reported_at: float | None) -> Reading:
    """A reading with values of the wrong type or outside the plausible range made unknown."""
    spec = SIGNAL_SPECS[signal]
    if value is None:
        return Reading(None, reported_at)
    if spec.kind is SignalKind.BINARY:
        return Reading(value if isinstance(value, bool) else None, reported_at)
    if isinstance(value, bool) or not isinstance(value, int | float):
        return Reading(None, reported_at)
    number = float(value)
    if number != number or not spec.plausible(number):  # NaN or out of range
        return Reading(None, reported_at)
    return Reading(number, reported_at)


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
    """One VT thermostat as the plugin sees it.

    ``heating_enabled``: the zone is in a mode that may heat (``None``: its mode is not known,
    e.g. the entity is unavailable); ``auto_mode``: "auto" or heat_cool, where its action says
    whether it heats. ``calling``: its heater or valve is active now (VT's action).
    ``device_active``: VT's own view of its devices (what its central boiler counts).
    ``on_percent`` and ``valve_open`` are fractions from 0 to 1. ``power`` is the device power
    as configured in VT, in kW — above 0, or unknown; ``mean_power`` VT's mean power over the
    zone's cycle, in kW (live only). ``ready``: VT's ``is_ready``, it has finished starting the
    thermostat. ``reported``: VT shows it started — ``is_ready`` true, or an older VT's state
    without that key — and ``False`` while it does not (before VT's first refresh a thermostat
    shows a placeholder "off" with neither); ``None``: not said, ``ready`` alone decides.
    ``temperature_at``: when the room temperature was last measured; the zone is fresh by it,
    else by the entity's report. ``room_sensor_lost``: the room sensor VT reads is gone,
    unavailable or unknown now, or VT's own safety mode is on — VT keeps the last temperature it
    had (live only). ``safety_on``: VT's safety mode; ``shedding``: VT's power shedding holds
    the zone off (live only).
    """

    zone_id: str
    temperature: float | None = None
    target: float | None = None
    heating_enabled: bool | None = None
    calling: bool | None = None
    on_percent: float | None = None
    valve_open: float | None = None
    power: float | None = None
    reported_at: float | None = None
    auto_mode: bool = False
    device_active: bool | None = None
    ready: bool | None = None
    temperature_at: float | None = None
    max_on_percent: float | None = None  # VT's cap on the duty cycle, 0 to 1
    room_sensor_lost: bool = False
    mean_power: float | None = None
    safety_on: bool = False
    shedding: bool = False
    reported: bool | None = None

    @property
    def started(self) -> bool:
        """VT shows it has started the thermostat (``reported``; without it, ``ready``)."""
        return self.reported if self.reported is not None else self.ready is not False

    @property
    def cycle_power(self) -> float | None:
        """The zone's mean power over its cycle, in kW, as VT counts it: VT's own where it
        publishes it, else the device power times the duty cycle (an older VT; the valve's
        opening without one); ``None`` without them."""
        if self.mean_power is not None:
            return self.mean_power
        ratio = self.on_percent if self.on_percent is not None else self.valve_open
        if self.power is not None and ratio is not None:
            return self.power * ratio
        return None

    @property
    def deficit(self) -> float | None:
        """Target minus temperature in kelvin; positive when the room is too cold."""
        if self.temperature is None or self.target is None:
            return None
        return self.target - self.temperature

    @property
    def fully_open(self) -> bool:
        """As open as the zone gets: fully, or at VT's cap on its duty cycle."""
        demand = self.demand
        if demand is None:
            return False
        limit = ZONE_SATURATED
        if self.max_on_percent is not None:
            limit = min(limit, self.max_on_percent - 0.01)
        return demand >= limit

    @property
    def demand(self) -> float | None:
        """How hard the zone's own controller works, 0 to 1: valve opening, else on-percent."""
        if self.valve_open is not None:
            return self.valve_open
        return self.on_percent

    def is_fresh(self, now: float, max_age: float | None) -> bool:
        at = self.temperature_at if self.temperature_at is not None else self.reported_at
        if at is None:
            return False
        return max_age is None or now - at <= max_age

    def is_known(self, now: float, max_age: float | None, recognition: bool = False) -> bool:
        """Its mode is known and its data fresh, and VT has started it — or, once the
        recognition period is over, it is in a mode that does not heat: such a zone has no
        demand whether VT runs it or not (S-34). A heating mode VT does not run is unknown."""
        if self.heating_enabled is None or not self.is_fresh(now, max_age):
            return False
        if self.started:
            return True
        return not self.heating_enabled and not recognition

    def has_reported(self, now: float, max_age: float | None) -> bool:
        """VT shows it started, and its mode and data are known: what the recognition period
        waits for (decision 3)."""
        return self.started and self.heating_enabled is not None and self.is_fresh(now, max_age)


@dataclass(frozen=True, slots=True)
class WeatherReading:
    """Current outdoor temperature from a weather entity (°C)."""

    temperature: float | None = None
    reported_at: float | None = None
