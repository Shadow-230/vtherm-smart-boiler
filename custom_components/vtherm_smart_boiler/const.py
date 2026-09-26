"""Constants shared by the integration. No Home Assistant imports."""

from __future__ import annotations

DOMAIN = "vtherm_smart_boiler"
VT_DOMAIN = "versatile_thermostat"
STORAGE_VERSION = 1  # the entry's store, ``<DOMAIN>.<entry_id>``

# Control options removed in 0.2.1: VT decides whether to heat (anti-cycling and the summer
# switch went), and nothing is written to the boiler's memory (the daily cap went).
REMOVED_CONTROL_OPTIONS = (
    "min_change",
    "min_burn_min",
    "min_off_min",
    "min_on_min",
    "min_pause_min",
    "max_starts_per_hour",
    "max_switches_per_hour",
    "daily_cap",
    "cap_reaction",
    "summer_threshold",
)

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
CONTROL = "control"

# Clocks.
TICK_SECONDS = 30
# Control runs more often than its 30 s keep-alive, so a late tick never lets an override that
# must be repeated within a minute lapse.
CONTROL_TICK_SECONDS = 10
SUMMARY_SECONDS = 300
FORECAST_SECONDS = 30 * 60
HISTORY_DAYS = 8
REFRESH_COOLDOWN_SECONDS = 10


def owes_hand_back(stored_control: object) -> bool:
    """Whether the control part of an entry's store says the boiler may hold a value of ours or
    a hand-back is still owed."""
    return isinstance(stored_control, dict) and bool(
        stored_control.get("hand_back_pending") or stored_control.get("controlling")
    )
