"""Generic profiles: boiler classes, houses and circuits. Typical values, no particular device."""

from __future__ import annotations

from dataclasses import dataclass

from custom_components.vtherm_smart_boiler.core.installation import EmitterType


@dataclass(frozen=True, slots=True)
class BoilerProfile:
    """A boiler with its own weather curve and on/off hysteresis around the setpoint.

    The burner stops when the flow exceeds the setpoint by ``hysteresis_off_k`` and restarts
    when it falls ``hysteresis_on_k`` below, no sooner than ``anti_cycle_s`` after stopping (its
    restart lockout; 5 K each side, provisional, K4). The pump runs on for ``pump_overrun_s``
    after the heating demand ends (5 min, a common factory value; provisional, K4). Its curve:
    ``setpoint = curve_offset + curve_slope · (20 − outdoor)``, clamped.
    """

    min_power_kw: float
    max_power_kw: float
    water_volume_l: float
    hysteresis_on_k: float = 5.0
    hysteresis_off_k: float = 5.0
    anti_cycle_s: float = 180.0
    pump_overrun_s: float = 300.0
    condensing: bool = True
    curve_offset: float = 25.0
    curve_slope: float = 1.0
    min_setpoint: float = 25.0
    max_setpoint: float = 70.0
    dhw_flow: float = 70.0
    dhw_changeover_s: float = 60.0  # burner off while the diverter valve switches to DHW
    pump_flow_kw_per_k: float = 1.0  # water flow times heat capacity


# The restart lockout of the relay and boiler scenarios (Z3, rule 8): a common factory setting
# of an on/off boiler's burner anti-cycling, adjustable 2–60 min on such boilers; test-only — the
# profiles below keep their own.
LONG_RESTART_LOCKOUT_S = 20 * 60.0

BOILERS: dict[str, BoilerProfile] = {
    "condensing_small": BoilerProfile(2.5, 15.0, 40.0),
    "condensing_large": BoilerProfile(4.0, 25.0, 60.0),
    "non_condensing": BoilerProfile(
        9.0,
        24.0,
        80.0,
        hysteresis_on_k=8.0,
        hysteresis_off_k=6.0,
        condensing=False,
        curve_offset=35.0,
        min_setpoint=40.0,
        max_setpoint=80.0,
    ),
    # Oversized and holding little water: in mild weather it starts every few minutes, as fast
    # as its restart lockout lets it (PB-92: with 8 L and a 30-s lockout it started about every
    # minute, and its starts depended on the simulator's step).
    "short_cycling": BoilerProfile(
        8.0,
        24.0,
        25.0,
        hysteresis_on_k=3.0,
        hysteresis_off_k=3.0,
    ),
}


@dataclass(frozen=True, slots=True)
class HouseProfile:
    """The whole house as one mass: loss coefficient, heat capacity and internal gains."""

    loss_kw_per_k: float
    capacity_kwh_per_k: float
    gains_kw: float

    def design_load_kw(self, indoor: float = 20.0, outdoor: float = -15.0) -> float:
        return self.loss_kw_per_k * (indoor - outdoor)


HOUSES: dict[str, HouseProfile] = {
    "average": HouseProfile(0.25, 10.0, 0.5),
    "well_insulated": HouseProfile(0.12, 12.0, 0.4),
    "leaky": HouseProfile(0.45, 8.0, 0.6),
}


@dataclass(frozen=True, slots=True)
class ZoneProfile:
    """A zone: its share of the house, emitter, setpoint and valve band.

    ``reference_output_kw`` is the emitter output at the type's reference condition; ``None``
    sizes it from the house design load times ``oversize``.
    """

    zone_id: str
    share: float
    emitter: EmitterType = EmitterType.RADIATOR
    target: float = 20.5
    valve_band_k: float = 1.0
    reference_output_kw: float | None = None
    oversize: float = 1.6


def radiator_zones() -> tuple[ZoneProfile, ...]:
    return (
        ZoneProfile("zone_living", 0.5),
        ZoneProfile("zone_bedroom", 0.3, target=19.5),
        ZoneProfile("zone_bath", 0.2, target=22.0),
    )


def underfloor_zones() -> tuple[ZoneProfile, ...]:
    return (
        ZoneProfile("zone_ground", 0.6, EmitterType.UNDERFLOOR, valve_band_k=0.6, oversize=1.2),
        ZoneProfile("zone_upstairs", 0.4, EmitterType.UNDERFLOOR, valve_band_k=0.6, oversize=1.2),
    )


def shared_loop_zones() -> tuple[ZoneProfile, ...]:
    """Radiators and underfloor on one unmixed loop."""
    return (
        ZoneProfile("zone_living", 0.5, EmitterType.UNDERFLOOR, valve_band_k=0.6, oversize=1.2),
        ZoneProfile("zone_bedroom", 0.3, target=19.5),
        ZoneProfile("zone_bath", 0.2, target=22.0),
    )
