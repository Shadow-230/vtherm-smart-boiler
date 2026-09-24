"""Constants shared by the integration. No Home Assistant imports."""

from __future__ import annotations

DOMAIN = "vtherm_smart_boiler"
VT_DOMAIN = "versatile_thermostat"

OPTIONS_VERSION = 1

# Keys of the config entry's options.
LEVEL = "level"
LEVEL_SIMPLE = "simple"
LEVEL_ADVANCED = "advanced"
SIGNALS = "signals"
WEATHER = "weather"
BOILER = "boiler"
PARAMETERS = "parameters"
CIRCUITS = "circuits"
ZONES = "zones"
BUILDING = "building"
REFERENCE_ROOM = "reference_room"
MONITOR = "monitor"
FRESHNESS = "freshness"

# Clocks.
TICK_SECONDS = 30
SUMMARY_SECONDS = 300
FORECAST_SECONDS = 30 * 60
HISTORY_DAYS = 8
REFRESH_COOLDOWN_SECONDS = 10
