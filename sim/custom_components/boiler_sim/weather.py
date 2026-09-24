"""A weather entity reading slightly off the boiler's outdoor sensor, with flat forecasts."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.components.weather import Forecast, WeatherEntity, WeatherEntityFeature
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import DOMAIN, SimHub
from .entity import SimEntity

BIAS_K = 0.5


async def async_setup_platform(
    hass: HomeAssistant,
    config: dict[str, Any],
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict[str, Any] | None = None,
) -> None:
    if discovery_info is None:
        return
    async_add_entities([SimWeather(hass.data[DOMAIN])])


class SimWeather(SimEntity, WeatherEntity):
    platform_domain = "weather"
    _attr_native_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        WeatherEntityFeature.FORECAST_HOURLY | WeatherEntityFeature.FORECAST_DAILY
    )
    _attr_condition = "cloudy"

    def __init__(self, hub: SimHub) -> None:
        super().__init__(hub, "weather", "weather")

    @property
    def native_temperature(self) -> float:
        return round(self.hub.sim.outdoor + BIAS_K, 1)

    def _forecast(self, step: timedelta, count: int) -> list[Forecast]:
        start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        temperature = self.native_temperature
        return [
            Forecast(
                datetime=(start + step * (i + 1)).isoformat(),
                native_temperature=temperature,
                native_templow=temperature - 4.0,
                condition="cloudy",
            )
            for i in range(count)
        ]

    async def async_forecast_hourly(self) -> list[Forecast]:
        return self._forecast(timedelta(hours=1), 48)

    async def async_forecast_daily(self) -> list[Forecast]:
        return self._forecast(timedelta(days=1), 7)
