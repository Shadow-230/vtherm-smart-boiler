"""Constants shared by the integration. No Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping

DOMAIN = "vtherm_smart_boiler"
VT_DOMAIN = "versatile_thermostat"
# The integrations the gateway paths write through: Home Assistant's OpenTherm Gateway, and MQTT
# for the OTGW firmware's commands.
OPENTHERM_GW_DOMAIN = "opentherm_gw"
MQTT_DOMAIN = "mqtt"
STORAGE_VERSION = 1  # the entry's store, ``<DOMAIN>.<entry_id>``
# The control store, ``<DOMAIN>.<entry_id>.control``: the control state alone, written at once.
CONTROL_STORE_VERSION = 1
# The last-run record, ``<DOMAIN>.<entry_id>.alive``: when the plugin last ran and its downtimes
# (P-95), small and written often, so the entry's store is not.
ALIVE_STORE_VERSION = 1
# In the entry's store: the control state lives in its own store (0.2.2 on). Without it, the
# entry's store is 0.2.1's, whose "control" copy is the state.
CONTROL_STORE_MARKER = "control_store"
# The repair issue of a control state that could not be read (a notice, not fixable).
UNREADABLE_ISSUE = "control_state_unreadable"

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


def main_store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}"


def control_store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.control"


def alive_store_key(entry_id: str) -> str:
    return f"{DOMAIN}.{entry_id}.alive"


def stored_flag(raw: object) -> bool:
    """A stored flag; anything that is not a clear "no" counts as set (the cautious side)."""
    return raw is not False and raw is not None and raw != 0


def owes_hand_back(stored_control: object) -> bool:
    """Whether the control part of an entry's store says the boiler may hold a value of ours or
    a hand-back is still owed. A flag that cannot be read counts as set."""
    return isinstance(stored_control, Mapping) and (
        stored_flag(stored_control.get("hand_back_pending"))
        or stored_flag(stored_control.get("controlling"))
    )


def has_control_section(options: object) -> bool:
    """Whether the options hold a control section: a ``control`` mapping naming a write path,
    whether or not it can be parsed. Such an entry may have held the boiler — unless it is on its
    first start, as one whose control was set up in the wizard (I6; ``coordinator``)."""
    if not isinstance(options, Mapping):
        return False
    control = options.get(CONTROL)
    return isinstance(control, Mapping) and control.get("write_path") not in (None, "")


def control_state_owed(state: object, *, readable: bool, has_control_section: bool) -> bool:
    """Whether a hand-back is owed, the same answer in setup, the options flow, removal and a
    report of unreadable options. A state that was read owes one when its flags say so. One that
    could not be read — a store missing, damaged or of another shape — owes one whenever control
    is configured, or when what is left of it (the entry store's copy) says so: a lost memory
    counts as "the plugin held the boiler"."""
    if owes_hand_back(state):
        return True
    return not readable and has_control_section


def assumed_owed_state(copy: object) -> dict[str, object]:
    """The state taken when it could not be read but a hand-back is owed: what the entry store's
    copy still holds (the options that took the boiler, the latches), with the boiler held and
    its hand-back owed."""
    kept = dict(copy) if isinstance(copy, Mapping) else {}
    return {**kept, "controlling": True, "hand_back_pending": True}
