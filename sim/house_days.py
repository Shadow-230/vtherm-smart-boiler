"""Days of a house with a known heat loss, for checking the building fit's range (I13.4).

The plant simulator (``sim.simulator``) runs a house minute by minute; checking how often a
range covers the true loss needs hundreds of months, so this model works by the day. A day's
heat is the house's loss less its gains, never below zero —
``24 · max(0, H · (indoor − outdoor) − gains − sun)`` kWh — plus, on a day that needs heat, an
error that carries over from one day to the next, as the building's mass, people and the
weather do. The day's mean outdoor
temperature follows a slow random walk around a seasonal mean; the sun's gain is drawn afresh
each day and left out of the fit, as the plugin's fit leaves it out (Leiria et al. 2024). The
true heating threshold is ``indoor − (gains + mean sun) / H``. Seeded: the same days every run.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from custom_components.vtherm_smart_boiler.core.building import DayPoint

DAY = 86400.0


@dataclass(frozen=True, slots=True)
class HouseDays:
    loss_kw_per_k: float = 0.25
    gains_kw: float = 0.8
    sun_kw: float = 0.4  # the most the sun adds on a day; drawn evenly from 0 to it
    indoor: float = 20.0
    mean_outdoor: float = 4.0  # the season's mean daily outdoor temperature, °C
    outdoor_sd: float = 4.0
    outdoor_rho: float = 0.8  # how much of a day's departure carries to the next
    error_share: float = 0.1  # the error's spread against the heat of a day at the mean outdoor
    error_rho: float = 0.5  # how much of a day's error carries to the next

    @property
    def threshold(self) -> float:
        return self.indoor - (self.gains_kw + self.sun_kw / 2) / self.loss_kw_per_k

    def days(self, count: int, seed: int) -> list[DayPoint]:
        """``count`` days, each with its start, one day apart."""
        rng = random.Random(seed)
        typical = 24.0 * max(
            0.1, self.loss_kw_per_k * (self.threshold - self.mean_outdoor)
        )  # kWh on a day at the mean outdoor temperature
        error_sd = self.error_share * typical
        outdoor = rng.gauss(0.0, self.outdoor_sd)
        error = rng.gauss(0.0, error_sd)
        out: list[DayPoint] = []
        for day in range(count):
            mean = self.mean_outdoor + outdoor
            sun = rng.uniform(0.0, self.sun_kw)
            need = self.loss_kw_per_k * (self.indoor - mean) - self.gains_kw - sun
            energy = max(0.0, 24.0 * need + error) if need > 0 else 0.0
            out.append(DayPoint(mean, energy, day * DAY))
            outdoor = self.outdoor_rho * outdoor + rng.gauss(
                0.0, self.outdoor_sd * math.sqrt(1 - self.outdoor_rho**2)
            )
            error = self.error_rho * error + rng.gauss(
                0.0, error_sd * math.sqrt(1 - self.error_rho**2)
            )
        return out
